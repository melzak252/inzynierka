"""Staking helpers for diagnostic bet sizing."""

from __future__ import annotations


def fixed_stake(amount: float, bankroll: float) -> float:
    """Return a fixed stake capped by bankroll."""

    return max(0.0, min(float(amount), float(bankroll)))


def percent_stake(bankroll: float, fraction: float, min_stake: float = 2.0, max_stake: float = 100.0) -> float:
    """Return a bankroll-percent stake with min/max limits."""

    if bankroll <= 0:
        return 0.0
    stake = bankroll * fraction
    stake = min(max(stake, min_stake), max_stake)
    return stake if stake <= bankroll else 0.0


def fractional_kelly_stake(
    bankroll: float,
    probability: float,
    decimal_odds: float,
    fraction: float = 0.05,
    tax_rate: float = 0.12,
    min_stake: float = 2.0,
    max_stake: float = 100.0,
) -> float:
    """Calculate fractional Kelly stake for taxed decimal odds."""

    if bankroll <= 0 or decimal_odds <= 1.0 or not 0 < probability < 1:
        return 0.0
    net_decimal = decimal_odds * (1.0 - tax_rate)
    b_value = net_decimal - 1.0
    if b_value <= 0:
        return 0.0
    full_kelly = ((b_value * probability) - (1.0 - probability)) / b_value
    if full_kelly <= 0:
        return 0.0
    stake = bankroll * full_kelly * fraction
    stake = min(max(stake, min_stake), max_stake)
    return stake if stake <= bankroll else 0.0
