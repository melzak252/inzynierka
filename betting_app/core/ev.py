"""Expected value and market probability calculations."""

from __future__ import annotations


def implied_probability(decimal_odds: float) -> float:
    """Return raw implied probability from decimal odds."""

    if decimal_odds <= 1.0:
        raise ValueError("Decimal odds must be greater than 1.0")
    return 1.0 / decimal_odds


def fair_market_probabilities(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Remove two-way bookmaker margin from decimal odds."""

    raw_a = implied_probability(odds_a)
    raw_b = implied_probability(odds_b)
    overround = raw_a + raw_b
    if overround <= 0:
        raise ValueError("Invalid overround")
    return raw_a / overround, raw_b / overround


def expected_value(model_prob: float, decimal_odds: float, tax_rate: float = 0.12) -> float:
    """Calculate expected value with Polish betting tax convention."""

    if not 0 <= model_prob <= 1:
        raise ValueError("model_prob must be in [0, 1]")
    if not 0 <= tax_rate < 1:
        raise ValueError("tax_rate must be in [0, 1)")
    return model_prob * decimal_odds * (1.0 - tax_rate) - 1.0


def best_ev_side(prob_a: float, odds_a: float, odds_b: float, tax_rate: float, min_ev: float) -> dict[str, float | str] | None:
    """Select the side with the highest EV if it crosses the threshold."""

    prob_b = 1.0 - prob_a
    ev_a = expected_value(prob_a, odds_a, tax_rate)
    ev_b = expected_value(prob_b, odds_b, tax_rate)
    market_a, market_b = fair_market_probabilities(odds_a, odds_b)

    if ev_a >= ev_b and ev_a > min_ev:
        return {"side": "a", "odds": odds_a, "model_prob": prob_a, "market_prob": market_a, "ev": ev_a}
    if ev_b > min_ev:
        return {"side": "b", "odds": odds_b, "model_prob": prob_b, "market_prob": market_b, "ev": ev_b}
    return None
