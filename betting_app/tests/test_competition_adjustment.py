from __future__ import annotations

import math

import pytest

from src.ratings.competition_adjustment import (
    CompetitionAdjustment,
    NEUTRAL_COMPETITION_ADJUSTMENT,
    adjust_probability,
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
