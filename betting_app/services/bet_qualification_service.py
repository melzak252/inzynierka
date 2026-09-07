"""Capital risk qualification and safety gating for betting recommendations."""

from __future__ import annotations

from typing import Any


def is_bet_eligible(
    prob_model: float,
    odds: float,
    prob_market_novig: float | None = None,
    tax_rate: float = 0.12,
    min_ev_net: float = 0.05,
) -> tuple[bool, str, dict[str, Any]]:
    """Determine whether a proposed bet satisfies mathematical EV and safety boundaries.

    Parameters
    ----------
    prob_model : float
        Calibrated model probability of winning (in (0, 1)).
    odds : float
        Decimal bookmaker odds (> 1.0).
    prob_market_novig : float | None, optional
        Consensus no-vig fair market probability, if available.
    tax_rate : float, default=0.12
        Mandatory turnover tax fraction (e.g. 0.12 for Poland).
    min_ev_net : float, default=0.05
        Minimum net expected value required for qualification (+5%).

    Returns
    -------
    tuple[bool, str, dict[str, Any]]
        (is_eligible, reason_code, diagnostics)
    """
    if not 0.0 < prob_model < 1.0:
        raise ValueError(f"prob_model must be in (0, 1), got {prob_model}")
    if odds <= 1.0:
        raise ValueError(f"odds must be > 1.0, got {odds}")
    if not 0.0 <= tax_rate < 1.0:
        raise ValueError(f"tax_rate must be in [0, 1), got {tax_rate}")
    if prob_market_novig is not None and not 0.0 < prob_market_novig < 1.0:
        raise ValueError(f"prob_market_novig must be in (0, 1), got {prob_market_novig}")

    return_factor = odds * (1.0 - tax_rate)
    ev_net = (prob_model * return_factor) - 1.0

    diag: dict[str, Any] = {
        "prob_model": prob_model,
        "odds": odds,
        "tax_rate": tax_rate,
        "prob_market_novig": prob_market_novig,
        "ev_net": round(ev_net, 4),
        "min_ev_net": min_ev_net,
        "quarantine": False,
    }

    if ev_net < min_ev_net:
        return False, "insufficient_ev", diag

    return True, "eligible", diag
