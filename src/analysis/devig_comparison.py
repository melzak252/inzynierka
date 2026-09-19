"""Devigging methods implementation for 2-way sports betting markets.

Methods:
1. Basic / Unnormalized Implied: p_i = 1 / O_i (does not sum to 1, raw bookmaker implied)
2. Multiplicative / Proportional: p_i = (1 / O_i) / sum(1 / O_j)
3. Power / Logarithmic: solves for k such that sum((1 / O_i)^k) = 1.0 (favors favorites)
4. Additive: p_i = (1 / O_i) - (overround - 1) / 2
5. Shin (1992): structural model solving for insider trading z
"""

from __future__ import annotations

import math
import numpy as np
from scipy.optimize import brentq


def devig_basic(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Basic raw implied probabilities: p_i = 1 / O_i."""
    return 1.0 / odds_a, 1.0 / odds_b


def devig_multiplicative(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Multiplicative / Proportional devigging: p_i = q_i / (q_a + q_b)."""
    if odds_a <= 1.0 or odds_b <= 1.0 or not math.isfinite(odds_a) or not math.isfinite(odds_b):
        raise ValueError(f"Odds must be > 1.0 and finite: {odds_a}, {odds_b}")
    qa = 1.0 / odds_a
    qb = 1.0 / odds_b
    tot = qa + qb
    return qa / tot, qb / tot


def devig_additive(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Additive devigging: subtracts half of the overround from each side."""
    qa = 1.0 / odds_a
    qb = 1.0 / odds_b
    overround = (qa + qb) - 1.0
    half_ov = overround / 2.0
    pa = max(1e-6, min(1.0 - 1e-6, qa - half_ov))
    pb = max(1e-6, min(1.0 - 1e-6, qb - half_ov))
    tot = pa + pb
    return pa / tot, pb / tot


def devig_power(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Power / Logarithmic devigging: solves for k such that qa^k + qb^k = 1.0."""
    qa = 1.0 / odds_a
    qb = 1.0 / odds_b
    tot = qa + qb
    if abs(tot - 1.0) < 1e-5:
        return qa / tot, qb / tot

    def obj(k):
        return (qa ** k) + (qb ** k) - 1.0

    try:
        # k typically ranges between 1.0 and 1.5 for positive overround
        k_opt = brentq(obj, 0.5, 3.0)
        pa = qa ** k_opt
        pb = qb ** k_opt
        tot_p = pa + pb
        return pa / tot_p, pb / tot_p
    except Exception:
        # Fallback to multiplicative if solver fails
        return qa / tot, qb / tot


def devig_shin(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Shin (1992) devigging solving for insider trading parameter z."""
    from src.analysis.shin_devig import shin_implied_probabilities
    return shin_implied_probabilities(odds_a, odds_b)
