"""Project one family-calibrated Glicko location posterior into any rating system.

The regional posterior is learned once by ``FamilyCalibratedGlicko2``.  Elo,
TrueSkill, OpenSkill, Plackett--Luce, and Thurstone--Mosteller retain their
native local-skill state and consume this projection only at matchup time.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .competition_adjustment import (
    CompetitionAdjustment,
    NEUTRAL_COMPETITION_ADJUSTMENT,
)

CALIBRATION_KIND = "family-calibrated-glicko2-v1"
UNKNOWN_AFFILIATION = "unknown"


@dataclass(frozen=True, slots=True)
class CompetitionLocation:
    """One side's persisted family/tier location posterior."""

    family: str
    tier: str
    family_mean: float
    family_variance: float
    tier_mean: float
    tier_variance: float

    def __post_init__(self) -> None:
        if not self.family or not self.tier:
            raise ValueError("competition family and tier must be non-empty")
        for name, value in (
            ("family_mean", self.family_mean),
            ("tier_mean", self.tier_mean),
            ("family_variance", self.family_variance),
            ("tier_variance", self.tier_variance),
        ):
            if not math.isfinite(value) or ("variance" in name and value < 0.0):
                raise ValueError(f"{name} must be finite and variances non-negative")

    @classmethod
    def from_rating_state(cls, state: Mapping[str, Any] | None) -> "CompetitionLocation | None":
        """Decode a calibrated ``gl`` entity state, otherwise return no posterior.

        Legacy snapshots intentionally have no calibration marker.  Unknown or
        incomplete affiliations are neutral rather than speculative evidence.
        """

        if not state or state.get("competition_calibration") != CALIBRATION_KIND:
            return None
        family = str(state.get("family") or "")
        tier = str(state.get("tier") or "")
        if family == UNKNOWN_AFFILIATION or tier == UNKNOWN_AFFILIATION:
            return None
        try:
            return cls(
                family=family,
                tier=tier,
                family_mean=float(state["family_residual"]),
                family_variance=float(state["family_variance"]),
                tier_mean=float(state["tier_offset"]),
                tier_variance=float(state["tier_variance"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid family-calibrated competition location state") from error


def adjustment_between(
    side_a: CompetitionLocation | None,
    side_b: CompetitionLocation | None,
) -> CompetitionAdjustment:
    """Return the frozen-posterior location difference for a matchup.

    A domestic matchup shares a family location, so both family and tier terms
    cancel exactly.  Missing affiliation has no directional evidence and is
    represented by the neutral adjustment.
    """

    if side_a is None or side_b is None or side_a.family == side_b.family:
        return NEUTRAL_COMPETITION_ADJUSTMENT

    mean = side_a.family_mean - side_b.family_mean
    variance = side_a.family_variance + side_b.family_variance
    if side_a.tier != side_b.tier:
        mean += side_a.tier_mean - side_b.tier_mean
        variance += side_a.tier_variance + side_b.tier_variance
    return CompetitionAdjustment(mean=mean, variance=variance)
