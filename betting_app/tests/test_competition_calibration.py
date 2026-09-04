from __future__ import annotations

import pytest

from betting_app.services.upcoming_inference_service import (
    competition_adjustment_from_team_ratings,
    rating_probabilities,
)
from src.ratings.competition_calibration import (
    CALIBRATION_KIND,
    CompetitionLocation,
    adjustment_between,
)


def _state(
    family: str,
    tier: str,
    *,
    family_mean: float,
    family_variance: float,
    tier_mean: float,
    tier_variance: float,
) -> dict[str, object]:
    return {
        "competition_calibration": CALIBRATION_KIND,
        "family": family,
        "tier": tier,
        "family_residual": family_mean,
        "family_variance": family_variance,
        "tier_offset": tier_mean,
        "tier_variance": tier_variance,
    }


def test_same_family_location_cancels_exactly_even_when_tiers_differ() -> None:
    lck_major = CompetitionLocation.from_rating_state(
        _state("LCK", "major", family_mean=18.0, family_variance=49.0, tier_mean=5.0, tier_variance=9.0)
    )
    lck_academy = CompetitionLocation.from_rating_state(
        _state("LCK", "academy", family_mean=18.0, family_variance=49.0, tier_mean=-6.0, tier_variance=16.0)
    )

    adjustment = adjustment_between(lck_major, lck_academy)

    assert adjustment.mean == 0.0
    assert adjustment.variance == 0.0


def test_cross_family_projection_uses_one_shared_posterior() -> None:
    lck = CompetitionLocation.from_rating_state(
        _state("LCK", "major", family_mean=30.0, family_variance=100.0, tier_mean=4.0, tier_variance=9.0)
    )
    lec = CompetitionLocation.from_rating_state(
        _state("LEC", "major", family_mean=-10.0, family_variance=64.0, tier_mean=4.0, tier_variance=9.0)
    )

    adjustment = adjustment_between(lck, lec)

    assert adjustment.mean == pytest.approx(40.0)
    assert adjustment.variance == pytest.approx(164.0)


def test_legacy_or_unknown_snapshot_has_no_directional_adjustment() -> None:
    legacy = {"rating": 1600.0}
    regional = _state("LCK", "major", family_mean=25.0, family_variance=100.0, tier_mean=0.0, tier_variance=0.0)

    adjustment = competition_adjustment_from_team_ratings(
        {"gl": {"state": legacy}},
        {"gl": {"state": regional}},
    )

    assert adjustment.mean == 0.0
    assert adjustment.variance == 0.0


def test_non_glicko_systems_receive_same_matchup_adjustment_once() -> None:
    lck = _state("LCK", "major", family_mean=40.0, family_variance=0.0, tier_mean=0.0, tier_variance=0.0)
    lec = _state("LEC", "major", family_mean=0.0, family_variance=0.0, tier_mean=0.0, tier_variance=0.0)
    ratings_a = {
        "elo": {"rating_value": 1500.0},
        "gl": {"rating_value": 1540.0, "state": lck},
        "ts": {"rating_value": 25.0},
        "os": {"rating_value": 25.0},
        "pl": {"rating_value": 25.0},
        "tm": {"rating_value": 25.0},
    }
    ratings_b = {
        "elo": {"rating_value": 1500.0},
        "gl": {"rating_value": 1500.0, "state": lec},
        "ts": {"rating_value": 25.0},
        "os": {"rating_value": 25.0},
        "pl": {"rating_value": 25.0},
        "tm": {"rating_value": 25.0},
    }

    adjustment = competition_adjustment_from_team_ratings(ratings_a, ratings_b)
    probabilities = rating_probabilities(ratings_a, ratings_b, adjustment)

    assert adjustment.mean == 40.0
    assert probabilities["elo"] > 0.5
    assert probabilities["ts"] > 0.5
    assert probabilities["os"] > 0.5
    assert probabilities["pl"] > 0.5
    assert probabilities["tm"] > 0.5
    assert probabilities["gl"] == pytest.approx(1.0 / (1.0 + 10 ** (-40.0 / 400.0)))
