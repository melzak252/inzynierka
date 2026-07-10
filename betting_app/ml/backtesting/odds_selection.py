"""Policies deciding which historical odds snapshot a backtest would use."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from betting_app.ml.config import BacktestConfig
from betting_app.ml.backtesting.types import MatchLabel, OddsQuote


def select_quotes_for_match(
    quotes: Iterable[OddsQuote],
    label: MatchLabel,
    config: BacktestConfig,
) -> list[OddsQuote]:
    """Return quotes eligible under the configured historical timing policy.

    The default policy, ``latest_pre_match``, answers the practical question
    "when would we have bet?" by taking the latest available pre-match snapshot
    per bookmaker, optionally requiring a minimum buffer before match start.
    """

    valid = [q for q in quotes if q.odds_a > 1.0 and q.odds_b > 1.0]
    if label.start_time is not None:
        latest_allowed = label.start_time - timedelta(minutes=config.min_minutes_before_start)
        valid = [q for q in valid if q.scraped_at <= latest_allowed]

    policy = config.odds_policy.lower()
    if policy == "all_pre_match":
        return sorted(valid, key=lambda q: q.scraped_at)
    if policy != "latest_pre_match":
        raise ValueError(f"Unsupported odds policy: {config.odds_policy}")

    latest_by_bookmaker: dict[int, OddsQuote] = {}
    for quote in sorted(valid, key=lambda q: q.scraped_at):
        latest_by_bookmaker[quote.bookmaker_id] = quote
    return list(latest_by_bookmaker.values())
