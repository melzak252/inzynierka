"""Offline regressions for conservative pure/hybrid recommendation semantics."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pandas as pd
import pytest

from betting_app.core.models import EXP081_SIAMESE, HybridSpec, PredictionEngine
from betting_app.core.staking import fractional_kelly_stake
from betting_app.services import upcoming_inference_service as service


def _diagnostics(low_a=0.55, low_b=0.35):
    return {
        "uncertainty_required": True,
        "p_low_a": low_a,
        "p_low_b": low_b,
        "epistemic_sigma_z": 0.3,
        "rating_disagreement": 0.04,
    }


def _row(diagnostics):
    return {
        "canonical_match_id": 1,
        "prediction_id": 1,
        "base_prediction_id": 1,
        "prob_a": 0.6,
        "prob_b": 0.4,
        "model_prob_a": 0.6,
        "diagnostics_json": diagnostics,
        "odds_snapshot_id": 1,
        "bookmaker_id": 1,
        "bookmaker": "offline",
        "team_a_name": "Alpha",
        "team_b_name": "Beta",
        "normalized_team_a": "alpha",
        "normalized_team_b": "beta",
        "raw_team_a": "Alpha",
        "raw_team_b": "Beta",
        "odds_a": 3.5,
        "odds_b": 3.5,
        "league": "Unmapped invitational",
        "offer_url": None,
    }


def _offline_storage(monkeypatch, row):
    # Exercise service probability/EV/staking logic without any database connection.
    responses = iter([pd.DataFrame([{"open_stake": 0.0}]), pd.DataFrame([row])])
    monkeypatch.setattr(service, "query_df", lambda *args: next(responses))
    inserts = []

    class Connection:
        def execute(self, sql, parameters):
            if "INSERT INTO" in sql:
                inserts.append(parameters)
            return SimpleNamespace(fetchone=lambda: {"id": len(inserts)})

    @contextmanager
    def transaction():
        yield Connection()

    monkeypatch.setattr(service, "transaction", transaction)
    return inserts


def test_each_side_uses_own_lower_probability_for_ev_and_staking(monkeypatch):
    inserts = _offline_storage(monkeypatch, _row(json.dumps(_diagnostics())))
    signals = service.generate_model_ev_signals(
        model_name=EXP081_SIAMESE.name, bankroll=100
    )
    assert {signal["side"] for signal in signals} == {"a", "b"}
    reserved = 0.0
    for signal in signals:
        lower = {"a": 0.55, "b": 0.35}[signal["side"]]
        assert signal["model_prob"] == {"a": 0.6, "b": 0.4}[signal["side"]]
        assert signal["prob_conservative"] == lower
        assert signal["competition_tier"] == "unknown"
        assert signal["ev"] == pytest.approx(lower * 3.5 * 0.88 - 1)
        expected_stake = fractional_kelly_stake(
            100,
            lower,
            3.5,
            fraction=0.05,
            tax_rate=0.12,
            reserved_bankroll=reserved,
        )
        assert signal["stake_suggestion"] == pytest.approx(expected_stake)
        reserved += expected_stake
    assert [values[6] for values in inserts] == [0.6, 0.4]
    assert [values[8] for values in inserts] == pytest.approx(
        [s["ev"] for s in signals]
    )


def test_more_uncertainty_cannot_create_a_signal(monkeypatch):
    sides = []
    for bounds in [(0.6, 0.4), (0.55, 0.35), (0.4, 0.2), (0.1, 0.05)]:
        _offline_storage(monkeypatch, _row(_diagnostics(*bounds)))
        sides.append({s["side"] for s in service.generate_model_ev_signals()})
    assert sides[0] == {"a", "b"}
    assert sides[-1] == set()
    assert all(later <= earlier for earlier, later in zip(sides, sides[1:]))


def test_swapping_sides_swaps_ev_and_preserves_conservative_risk(monkeypatch):
    row = _row(_diagnostics())
    _offline_storage(monkeypatch, row)
    original = {s["side"]: s for s in service.generate_model_ev_signals()}
    swapped = {
        **row,
        "prob_a": row["prob_b"],
        "prob_b": row["prob_a"],
        "diagnostics_json": _diagnostics(0.35, 0.55),
    }
    _offline_storage(monkeypatch, swapped)
    reversed_signals = {s["side"]: s for s in service.generate_model_ev_signals()}
    assert reversed_signals.keys() == original.keys()
    for side, opposite in (("a", "b"), ("b", "a")):
        assert reversed_signals[opposite]["ev"] == pytest.approx(original[side]["ev"])
        assert (
            reversed_signals[opposite]["prob_conservative"]
            == original[side]["prob_conservative"]
        )


@pytest.mark.parametrize(
    "diagnostics",
    [
        None,
        "{",
        "[]",
        {},
        {"prob_risk_adjusted_p_low": 0.55},
        {**_diagnostics(), "p_low_b": None},
        {**_diagnostics(), "p_low_b": 0.45},
        {**_diagnostics(), "p_low_a": "bad"},
        {**_diagnostics(), "epistemic_sigma_z": float("nan")},
        {**_diagnostics(), "epistemic_sigma_z": -1},
        {**_diagnostics(), "rating_disagreement": "bad"},
        {**_diagnostics(), "rating_disagreement": float("inf")},
        {**_diagnostics(), "rating_disagreement": None},
    ],
)
def test_bad_or_missing_prediction_safety_diagnostics_never_qualify(
    monkeypatch, diagnostics
):
    _offline_storage(monkeypatch, _row(diagnostics))
    assert service.generate_model_ev_signals() == []


@pytest.mark.parametrize("odds", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_odds_never_generate_signals(monkeypatch, odds):
    row = {**_row(_diagnostics()), "odds_a": odds}
    _offline_storage(monkeypatch, row)
    assert service.generate_model_ev_signals() == []


@pytest.mark.parametrize("mode", ["linear", "logit_shrinkage"])
def test_hybrid_transforms_both_bounds_with_the_same_sidewise_transform(
    monkeypatch, mode
):
    row = _row(_diagnostics())
    _offline_storage(monkeypatch, row)
    monkeypatch.setattr(service, "query_df", lambda *args: pd.DataFrame([row]))
    monkeypatch.setattr(service, "register_hybrid_model", lambda **kwargs: 1)
    (result,) = service.generate_hybrid_predictions(
        alpha=0.5, temperature=0.8, blending_mode=mode
    )
    spec = HybridSpec(
        base_model=EXP081_SIAMESE, alpha=0.5, temperature=0.8, blending_mode=mode
    )
    transform = lambda p: PredictionEngine.blend_with_market(p, 0.5, spec)
    assert result["prob_a"] == pytest.approx(transform(0.6))
    assert result["prob_a"] + result["prob_b"] == pytest.approx(1.0)
    diag = result["diagnostics"]
    assert diag["p_low_a"] == pytest.approx(transform(0.55))
    assert diag["p_low_b"] == pytest.approx(transform(0.35))
    assert diag["p_low_b"] < result["prob_b"]
    assert diag["rating_disagreement"] == 0.04
    # Stored hybrid bounds, not the raw-model bounds, must drive hybrid EV.
    hybrid_row = {
        **row,
        "prob_a": result["prob_a"],
        "prob_b": result["prob_b"],
        "diagnostics_json": json.dumps(diag),
    }
    _offline_storage(monkeypatch, hybrid_row)
    signals = service.generate_model_ev_signals(
        model_name=service.DEFAULT_HYBRID_MODEL_NAME
    )
    for signal in signals:
        assert signal["ev"] == pytest.approx(
            diag[f"p_low_{signal['side']}"] * 3.5 * 0.88 - 1
        )


def test_hybrid_missing_base_uncertainty_does_not_emit_predictions(monkeypatch):
    row = _row({})
    _offline_storage(monkeypatch, row)
    monkeypatch.setattr(service, "query_df", lambda *args: pd.DataFrame([row]))
    monkeypatch.setattr(service, "register_hybrid_model", lambda **kwargs: 1)
    assert service.generate_hybrid_predictions() == []


@pytest.mark.parametrize("mode", ["linear", "logit_shrinkage"])
def test_more_uncertainty_never_adds_hybrid_qualified_sides(monkeypatch, mode):
    qualified = []
    means = []
    for low_a, low_b in [(0.6, 0.4), (0.4, 0.2), (0.1, 0.05)]:
        row = _row(_diagnostics(low_a, low_b))
        _offline_storage(monkeypatch, row)
        monkeypatch.setattr(service, "query_df", lambda *args: pd.DataFrame([row]))
        monkeypatch.setattr(service, "register_hybrid_model", lambda **kwargs: 1)
        (hybrid,) = service.generate_hybrid_predictions(blending_mode=mode)
        means.append(hybrid["prob_a"])
        _offline_storage(
            monkeypatch,
            {
                **row,
                "prob_a": hybrid["prob_a"],
                "prob_b": hybrid["prob_b"],
                "diagnostics_json": hybrid["diagnostics"],
            },
        )
        qualified.append(
            {
                s["side"]
                for s in service.generate_model_ev_signals(
                    model_name=service.DEFAULT_HYBRID_MODEL_NAME,
                )
            }
        )
    assert means == pytest.approx([means[0]] * 3)
    assert qualified[0] == {"a", "b"}
    assert qualified[-1] == set()
    assert all(later <= earlier for earlier, later in zip(qualified, qualified[1:]))
