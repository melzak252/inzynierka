"""Dataclasses used by deterministic historical backtests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Side = Literal["a", "b"]


@dataclass(frozen=True)
class HistoricalPrediction:
    canonical_match_id: int
    model_name: str
    model_version: str
    prob_a: float
    prob_b: float
    predicted_at: datetime | None = None
    data_cutoff_at: datetime | None = None
    prediction_id: int | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MatchLabel:
    canonical_match_id: int
    winner_side: Side
    start_time: datetime | None = None
    league: str | None = None


@dataclass(frozen=True)
class OddsQuote:
    canonical_match_id: int
    bookmaker_id: int
    bookmaker_name: str
    odds_a: float
    odds_b: float
    scraped_at: datetime
    odds_snapshot_id: int | None = None
    offer_url: str | None = None


@dataclass(frozen=True)
class BacktestBet:
    canonical_match_id: int
    side: Side
    bookmaker_id: int
    bookmaker_name: str
    odds_snapshot_id: int | None
    placed_at: datetime
    odds: float
    model_prob: float
    market_prob: float
    ev: float
    stake: float
    profit: float
    result: Literal["won", "lost"]
    bankroll_before: float
    bankroll_after: float
    prediction_id: int | None = None


@dataclass(frozen=True)
class BacktestResult:
    bets: list[BacktestBet]
    bankroll_start: float
    bankroll_end: float
    total_staked: float
    total_profit: float
    roi: float
    hit_rate: float
    max_drawdown: float
    matches_seen: int
    matches_bet: int


@dataclass(frozen=True)
class PredictionMarketComparison:
    observations: int
    model_log_loss: float
    market_log_loss: float
    model_brier: float
    market_brier: float
    model_accuracy: float
    market_accuracy: float
