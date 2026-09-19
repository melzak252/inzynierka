"""Consumer contracts for match recommendations; no database required."""

import pytest

from betting_app.api.routers.matches import _build_match_recommendation
from betting_app.api.schemas import BookmakerOddsRow
from betting_app.services.market_service import kelly_fraction


def recommendation(**changes):
    params = dict(
        team_a_name="Alpha",
        team_b_name="Beta",
        has_unmapped_teams=False,
        odds_rows=[
            BookmakerOddsRow(
                bookmaker="sts", canonical_odds_a=1.6, canonical_odds_b=2.4
            )
        ],
        hybrid_prob_a=0.45,
        hybrid_prob_b=0.55,
        pure_prob_a=0.4,
        pure_prob_b=0.6,
        hybrid_diagnostics={
            "p_low_a": 0.40,
            "p_low_b": 0.52,
            "epistemic_sigma_z": 0.2,
            "rating_disagreement": 0.04,
            "uncertainty_required": True,
        },
    )
    params.update(changes)
    return _build_match_recommendation(**params)


def test_unmapped_or_missing_odds_cannot_recommend():
    assert not recommendation(has_unmapped_teams=True).has_value
    assert not recommendation(odds_rows=[]).has_value


def test_qualified_side_uses_conservative_ev_and_stake_but_displays_mean():
    rec = recommendation()
    assert rec.has_value and rec.side == "b"
    assert rec.hybrid_prob == 0.55
    assert rec.ev == pytest.approx(0.52 * 2.4 * 0.88 - 1, abs=1e-4)
    assert rec.quarter_kelly == pytest.approx(
        kelly_fraction(0.52, 2.4, 0.12) / 4, abs=1e-4
    )


def test_positive_mean_ev_without_safe_bound_cannot_recommend():
    rec = recommendation(
        hybrid_diagnostics={
            "p_low_a": 0.30,
            "p_low_b": 0.40,
            "epistemic_sigma_z": 0.7,
            "rating_disagreement": 0.04,
        }
    )
    assert not rec.has_value
    assert rec.quarter_kelly is None


def test_pure_diagnostics_cannot_substitute_for_missing_hybrid_bounds():
    rec = recommendation(
        hybrid_diagnostics=None,
        diagnostics={
            "p_low_a": 0.4,
            "p_low_b": 0.59,
            "epistemic_sigma_z": 0.1,
            "rating_disagreement": 0.01,
        },
    )
    assert not rec.has_value


def test_tier1_mean_market_gap_is_not_hidden_by_lower_bound():
    rec = recommendation(
        league="LCK 2026",
        hybrid_prob_a=0.2,
        hybrid_prob_b=0.8,
        hybrid_diagnostics={
            "p_low_a": 0.1,
            "p_low_b": 0.52,
            "epistemic_sigma_z": 0.5,
            "rating_disagreement": 0.02,
        },
    )
    assert not rec.has_value


def test_side_with_larger_ev_cannot_bypass_its_safety_rejection():
    rec = recommendation(
        hybrid_prob_a=0.5,
        hybrid_prob_b=0.5,
        odds_rows=[
            BookmakerOddsRow(
                bookmaker="sts", canonical_odds_a=3.5, canonical_odds_b=3.6
            )
        ],
        hybrid_diagnostics={
            "p_low_a": 0.48,
            "p_low_b": 0.30,
            "epistemic_sigma_z": 0.5,
            "rating_disagreement": 0.04,
        },
    )
    assert rec.has_value and rec.side == "a"
