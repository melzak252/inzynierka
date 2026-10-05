"""Offline C0 mean-probability EV contracts."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pandas as pd
import pytest

from betting_app.services import upcoming_inference_service as service


def _row():
    return {
        "canonical_match_id": 1,
        "prediction_id": 1,
        "base_prediction_id": 1,
        "prob_a": 0.6,
        "prob_b": 0.4,
        "model_prob_a": 0.6,
        "diagnostics_json": json.dumps({}),
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


def test_c0_ev_uses_each_sides_mean_probability(monkeypatch):
    _offline_storage(monkeypatch, _row())
    signals = service.generate_model_ev_signals(bankroll=100)

    assert {signal["side"] for signal in signals} == {"a", "b"}
    for signal in signals:
        mean = {"a": 0.6, "b": 0.4}[signal["side"]]
        assert signal["model_prob"] == mean
        assert signal["ev"] == pytest.approx(mean * 3.5 * 0.88 - 1)


def test_swapping_c0_probability_sides_swaps_ev_sides(monkeypatch):
    first = _row()
    _offline_storage(monkeypatch, first)
    forward = {signal["side"]: signal for signal in service.generate_model_ev_signals()}

    reversed_row = {
        **first,
        "prob_a": first["prob_b"],
        "prob_b": first["prob_a"],
        "model_prob_a": first["prob_b"],
    }
    _offline_storage(monkeypatch, reversed_row)
    reversed_signals = {
        signal["side"]: signal for signal in service.generate_model_ev_signals()
    }

    assert reversed_signals["a"]["ev"] == pytest.approx(forward["b"]["ev"])
    assert reversed_signals["b"]["ev"] == pytest.approx(forward["a"]["ev"])
