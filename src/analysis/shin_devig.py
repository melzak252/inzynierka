"""Closed-form 2-way Shin (1992) devigging implementation."""

import math


def shin_implied_probabilities(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Calculate true fair probabilities by stripping bookmaker margin and longshot bias.

    Hyun Song Shin (1992): 'Prices of State Contingent Claims with Insider Traders,
    and the Favorite-Longshot Bias'.

    Solves analytically for insider proportion z in 2-way market:
        q_i = 1 / odds_i
        S = sum(q_i) > 1
        z = (sqrt((q_A - q_B)^2 + 4*(S - 1)) - (S - 1)) / (2*(S - 1))
        pi_i = (sqrt(z^2 + 4*(1 - z)*(q_i^2 / S)) - z) / (2*(1 - z))
    """
    if odds_a <= 1.0 or odds_b <= 1.0 or not math.isfinite(odds_a) or not math.isfinite(odds_b):
        raise ValueError(f"Odds must be > 1.0 and finite: {odds_a}, {odds_b}")

    q_a = 1.0 / odds_a
    q_b = 1.0 / odds_b
    s = q_a + q_b

    # If bookmaker margin is zero or negative (arbitrage/fair odds)
    if s <= 1.0001:
        tot = q_a + q_b
        return q_a / tot, q_b / tot

    diff = q_a - q_b
    s_minus_one = s - 1.0

    # Solve for insider parameter z
    discriminant = diff * diff + 4.0 * s_minus_one
    sqrt_disc = math.sqrt(max(0.0, discriminant))
    z = (sqrt_disc - s_minus_one) / (2.0 * s_minus_one)
    z = max(0.0, min(0.999, z))

    # Solve for fair synthetic probabilities pi_a and pi_b
    denom = 2.0 * (1.0 - z)
    if denom <= 1e-9:
        tot = q_a + q_b
        return q_a / tot, q_b / tot

    pi_a = (math.sqrt(z * z + 4.0 * (1.0 - z) * (q_a * q_a / s)) - z) / denom
    pi_b = (math.sqrt(z * z + 4.0 * (1.0 - z) * (q_b * q_b / s)) - z) / denom

    # Normalize to exact sum = 1.0
    tot_pi = pi_a + pi_b
    return float(pi_a / tot_pi), float(pi_b / tot_pi)
