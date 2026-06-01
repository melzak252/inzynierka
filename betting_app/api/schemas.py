"""Pydantic request/response schemas for the betting API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Health ──────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


# ── Match board ─────────────────────────────────────────────────────────────


class MatchBoardItem(BaseModel):
    canonical_match_id: int
    match: str
    league: str | None = None
    start_time_normalized: str | None = None

    team_a_name: str | None = None
    team_b_name: str | None = None

    bookmaker_count: int = 0

    best_odds_a: float | None = None
    best_bookmaker_a: str | None = None
    best_offer_url_a: str | None = None
    avg_odds_a: float | None = None

    best_odds_b: float | None = None
    best_bookmaker_b: str | None = None
    best_offer_url_b: str | None = None
    avg_odds_b: float | None = None

    arb_no_tax: bool = False
    arb_after_tax: bool = False
    arb_margin_no_tax: float | None = None
    arb_margin_after_tax: float | None = None

    # Model/hybrid probabilities and EV (enriched per row in board)
    model_prob_a: float | None = None
    model_prob_b: float | None = None
    hybrid_prob_a: float | None = None
    hybrid_prob_b: float | None = None
    hybrid_ev_a: float | None = None
    hybrid_ev_b: float | None = None

    last_scraped_at: str | None = None


class MatchBoardResponse(BaseModel):
    total: int
    matches: list[MatchBoardItem]


# ── Match detail ────────────────────────────────────────────────────────────


class BookmakerOddsRow(BaseModel):
    bookmaker: str
    raw_team_a: str | None = None
    raw_team_b: str | None = None
    canonical_odds_a: float | None = None
    canonical_odds_b: float | None = None
    scraped_at: str | None = None
    source_url: str | None = None
    offer_url: str | None = None


class PredictionRow(BaseModel):
    model_name: str
    model_version: str
    prob_a: float | None = None
    prob_b: float | None = None
    predicted_at: str | None = None
    ev_a: float | None = None
    ev_b: float | None = None
    kelly_a: float | None = None
    kelly_b: float | None = None


class RosterPlayer(BaseModel):
    player_name: str | None = None
    role: str | None = None
    champion_name: str | None = None
    glicko_rating: float | None = None
    glicko_rd: float | None = None
    games_played: int | None = None


class RosterInfo(BaseModel):
    team_name: str | None = None
    source_match_id: str | None = None
    source_date: str | None = None
    players: list[RosterPlayer] = []


class MatchDetailResponse(BaseModel):
    canonical_match_id: int
    team_a_name: str | None = None
    team_b_name: str | None = None
    league: str | None = None
    start_time_normalized: str | None = None
    status: str | None = None

    odds: list[BookmakerOddsRow] = []
    predictions: list[PredictionRow] = []
    roster_a: RosterInfo | None = None
    roster_b: RosterInfo | None = None


# ── Odds history (line movement) ────────────────────────────────────────────


class OddsHistoryPoint(BaseModel):
    bookmaker: str
    scraped_at: str
    odds_a: float | None = None
    odds_b: float | None = None
    canonical_odds_a: float | None = None
    canonical_odds_b: float | None = None


# ── Predictions / EV+ signals ───────────────────────────────────────────────


class EVSignal(BaseModel):
    canonical_match_id: int
    match: str
    league: str | None = None
    start_time_normalized: str | None = None
    model_name: str
    model_version: str
    side: str  # "a" or "b"
    odds: float
    bookmaker: str
    model_prob: float
    market_prob: float | None = None
    ev: float
    kelly: float = 0.0
    offer_url: str | None = None


class EVSignalResponse(BaseModel):
    total: int
    signals: list[EVSignal]


# ── System status ───────────────────────────────────────────────────────────


class SystemStatusResponse(BaseModel):
    counts: dict[str, int]
    last_scrape_runs: list[dict[str, Any]] = []
    last_automation_runs: list[dict[str, Any]] = []


class AutomationTriggerResponse(BaseModel):
    status: str
    message: str


# ── Wallets and bets ────────────────────────────────────────────────────────


class WalletResponse(BaseModel):
    id: int
    bookmaker: str | None = None
    account_name: str
    currency: str = "PLN"
    current_balance: float
    is_active: bool = True


class BetCreate(BaseModel):
    bookmaker_account_id: int
    canonical_match_id: int | None = None
    team_a: str | None = None
    team_b: str | None = None
    league: str | None = None
    match_start_time: str | None = None
    side: str = Field(pattern="^(a|b)$")
    stake: float = Field(gt=0)
    odds: float = Field(gt=1)
    model_prob: float | None = Field(default=None, ge=0, le=1)
    ev: float | None = None
    tax_rate: float = 0.12
    note: str | None = None


class BetResponse(BaseModel):
    id: int
    bookmaker_account_id: int
    canonical_match_id: int | None = None
    team_a: str | None = None
    team_b: str | None = None
    stake: float
    odds: float
    side: str
    status: str
    profit: float | None = None
    placed_at: str | None = None
    settled_at: str | None = None
    note: str | None = None


class BetSettle(BaseModel):
    result: str = Field(pattern="^(won|lost|void|cancelled)$")
    settlement_odds: float | None = None


# ── Bookmakers ──────────────────────────────────────────────────────────────


class BookmakerStatus(BaseModel):
    id: int
    name: str
    base_url: str | None = None
    last_scraped_at: str | None = None
    snapshot_count: int = 0


# ── Scheduler ───────────────────────────────────────────────────────────────


class SchedulerTaskResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    interval_minutes: int | None = None
    cron_trigger: str | None = None
    enabled: bool = True


class SchedulerJobResponse(BaseModel):
    id: str
    name: str
    enabled: bool = True
    next_run_time: str | None = None
    last_run_at: str | None = None
    last_run_status: str | None = None
    is_running: bool = False


class SchedulerTriggerResponse(BaseModel):
    task_id: str
    status: str
    message: str
