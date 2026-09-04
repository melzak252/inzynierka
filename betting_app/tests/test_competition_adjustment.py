from __future__ import annotations

import math

import pytest

from src.ratings.competition_adjustment import (
    CompetitionAdjustment,
    NEUTRAL_COMPETITION_ADJUSTMENT,
    adjust_probability,
)
from betting_app.services.upcoming_inference_service import (
    player_rating_probabilities,
    rating_probabilities,
)


def test_neutral_adjustment_is_exact_identity_including_boundaries() -> None:
    for probability in (0.0, 0.2, 0.5, 0.8, 1.0):
        assert adjust_probability(probability, NEUTRAL_COMPETITION_ADJUSTMENT) == probability


def test_positive_location_difference_increases_side_a_probability() -> None:
    adjusted = adjust_probability(
        0.5,
        CompetitionAdjustment(mean=100.0, variance=0.0),
    )

    assert adjusted == pytest.approx(1.0 / (1.0 + 10.0 ** -0.25))
    assert adjusted > 0.5


def test_orientation_reversal_preserves_probability_symmetry() -> None:
    adjustment = CompetitionAdjustment(mean=73.0, variance=2_500.0)

    forward = adjust_probability(0.63, adjustment)
    reversed_probability = adjust_probability(0.37, adjustment.reversed())

    assert forward + reversed_probability == pytest.approx(1.0)


def test_uncertain_bridge_attenuates_probability_toward_half() -> None:
    certain = adjust_probability(
        0.7,
        CompetitionAdjustment(mean=80.0, variance=0.0),
    )
    uncertain = adjust_probability(
        0.7,
        CompetitionAdjustment(mean=80.0, variance=40_000.0),
    )

    assert 0.5 < uncertain < certain


@pytest.mark.parametrize(
    "adjustment",
    [
        CompetitionAdjustment(mean=0.0, variance=0.0),
        CompetitionAdjustment(mean=-20.0, variance=10.0),
    ],
)
def test_adjusted_probability_is_bounded(adjustment: CompetitionAdjustment) -> None:
    for probability in (0.0, 1e-15, 0.5, 1.0 - 1e-15, 1.0):
        result = adjust_probability(probability, adjustment)
        assert math.isfinite(result)
        assert 0.0 <= result <= 1.0


@pytest.mark.parametrize(
    ("mean", "variance"),
    [(math.nan, 0.0), (0.0, math.nan), (0.0, -1.0), (math.inf, 0.0)],
)
def test_invalid_adjustments_fail_closed(mean: float, variance: float) -> None:
    with pytest.raises(ValueError):
        CompetitionAdjustment(mean=mean, variance=variance)


@pytest.mark.parametrize("probability", [-0.1, 1.1, math.nan, math.inf])
def test_invalid_base_probability_fails_closed(probability: float) -> None:
    with pytest.raises(ValueError):
        adjust_probability(probability, NEUTRAL_COMPETITION_ADJUSTMENT)


def test_regional_posterior_projects_once_onto_raw_systems_not_glicko() -> None:
    systems = ("elo", "gl", "ts", "os", "pl", "tm")
    team_a = {system: {"rating_value": 100.0} for system in systems}
    team_b = {system: {"rating_value": 100.0} for system in systems}
    player_a = {system: {"avg_rating_value": 100.0} for system in systems}
    player_b = {system: {"avg_rating_value": 100.0} for system in systems}
    adjustment = CompetitionAdjustment(mean=100.0, variance=0.0)

    team_probabilities = rating_probabilities(team_a, team_b, adjustment)
    player_probabilities = player_rating_probabilities(player_a, player_b, adjustment)

    for probabilities in (team_probabilities, player_probabilities):
        assert probabilities["gl"] == 0.5
        assert all(probabilities[system] > 0.5 for system in systems if system != "gl")
        assert probabilities["consensus"] > 0.5
