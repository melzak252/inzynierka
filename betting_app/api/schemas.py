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
    best_of: int | None = None

    team_a_name: str | None = None
    team_b_name: str | None = None
    team_a_golgg_name: str | None = None
    team_b_golgg_name: str | None = None
    team_a_mapping_source: str | None = None
    team_b_mapping_source: str | None = None
    has_unmapped_teams: bool = False
    match_confidence: float | None = None

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
    
    # Fusion SymAug probabilities and EV
    fusion_symaug_prob_a: float | None = None
    fusion_symaug_prob_b: float | None = None
    fusion_symaug_ev_a: float | None = None
    fusion_symaug_ev_b: float | None = None

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
    ev_a: float | None = None
    ev_b: float | None = None
    kelly_a: float | None = None
    kelly_b: float | None = None


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
    player_id: str | None = None
    player_name: str | None = None
    role: str | None = None
    champion_name: str | None = None
    elo_rating: float | None = None
    glicko_rating: float | None = None
    glicko_rd: float | None = None
    trueskill_rating: float | None = None
    rating_uncertainty: float | None = None
    games_played: int | None = None


class RosterInfo(BaseModel):
    team_name: str | None = None
    source_match_id: str | None = None
    source_date: str | None = None
    source_tournament: str | None = None
    roster_source: str | None = None
    avg_elo: float | None = None
    avg_glicko: float | None = None
    avg_glicko_rd: float | None = None
    players_with_rating: int | None = None
    players: list[RosterPlayer] = []


class TeamRecentStats(BaseModel):
    team_name: str | None = None
    matches_count: int | None = None
    games_count: int | None = None
    win_rate: float | None = None
    avg_kills: float | None = None
    avg_deaths: float | None = None
    avg_gd15: float | None = None
    avg_dragons: float | None = None
    avg_nashors: float | None = None
    avg_towers: float | None = None
    avg_game_duration: float | None = None
    last_match_at: str | None = None


class TeamMappingInfo(BaseModel):
    canonical_name: str | None = None
    golgg_name: str | None = None
    confidence: float | None = None
    source: str | None = None  # 'alias', 'builtin', 'blocked', or None when unmapped


class TeamComparisonInfo(BaseModel):
    team_a: TeamMappingInfo | None = None
    team_b: TeamMappingInfo | None = None
    team_a_rating: float | None = None
    team_b_rating: float | None = None
    rating_system: str | None = None
    team_a_elo: float | None = None
    team_b_elo: float | None = None
    team_a_glicko: float | None = None
    team_b_glicko: float | None = None
    team_a_glicko_rd: float | None = None
    team_b_glicko_rd: float | None = None
    team_a_games_played: int | None = None
    team_b_games_played: int | None = None
    rating_probabilities: dict[str, float] = {}


class BookmakerEvSide(BaseModel):
    ev: float | None = None
    odds: float | None = None
    model_prob: float | None = None
    kelly: float | None = None
    market_prob: float | None = None
    odds_snapshot_id: int | None = None
    scraped_at: str | None = None


class BookmakerEvDetail(BaseModel):
    side_a: BookmakerEvSide = BookmakerEvSide()
    side_b: BookmakerEvSide = BookmakerEvSide()


class MatchResultItem(BaseModel):
    canonical_match_id: int
    team_a_name: str | None = None
    team_b_name: str | None = None
    league: str | None = None
    start_time_normalized: str | None = None
    best_of: int | None = None
    status: str | None = None
    winner_name: str | None = None
    loser_name: str | None = None
    winner_side: str | None = None  # "team_a" or "team_b"
    team_a_score: int | None = None
    team_b_score: int | None = None
    result_source: str | None = None
    result_recorded_at: str | None = None
    # EV signals (best across all bookmakers)
    best_ev_a: float | None = None
    best_ev_b: float | None = None
    bookmakers_with_ev: list[str] = []
    best_odds_a: float | None = None
    best_odds_b: float | None = None
    # Model probabilities (for Kelly staking)
    model_prob_a: float | None = None
    model_prob_b: float | None = None
    # Kelly fractions (full Kelly, after tax)
    kelly_a: float | None = None
    kelly_b: float | None = None
    # Per-bookmaker EV/odds details
    bookmaker_ev_details: dict[str, BookmakerEvDetail] = {}
    model_name: str | None = None
    model_version: str | None = None
    odds_mode: str | None = None


class MatchResultsResponse(BaseModel):
    total: int
    days_back: int | None = None
    model_name: str | None = None
    model_version: str | None = None
    odds_mode: str | None = None
    results: list[MatchResultItem]


class MatchBestOfUpdate(BaseModel):
    best_of: int = Field(ge=1, le=7)


class MatchDetailResponse(BaseModel):
    canonical_match_id: int
    team_a_name: str | None = None
    team_b_name: str | None = None
    league: str | None = None
    start_time_normalized: str | None = None
    status: str | None = None
    best_of: int | None = None

    odds: list[BookmakerOddsRow] = []
    predictions: list[PredictionRow] = []
    roster_a: RosterInfo | None = None
    roster_b: RosterInfo | None = None
    recent_stats_a: TeamRecentStats | None = None
    recent_stats_b: TeamRecentStats | None = None
    team_comparison: TeamComparisonInfo | None = None


# ── Odds history (line movement) ────────────────────────────────────────────


class OddsHistoryPoint(BaseModel):
    bookmaker: str
    scraped_at: str
    odds_a: float | None = None
    odds_b: float | None = None
    canonical_odds_a: float | None = None
    canonical_odds_b: float | None = None


# ── Prediction & EV history timeline ────────────────────────────────────────


class PredictionHistoryPoint(BaseModel):
    timestamp: str
    model_name: str
    model_version: str
    prob_a: float | None = None
    prob_b: float | None = None
    avg_odds_a: float | None = None
    avg_odds_b: float | None = None
    market_prob_a: float | None = None
    market_prob_b: float | None = None
    ev_a: float | None = None
    ev_b: float | None = None


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
    task_id: str
    name: str
    description: str = ""
    schedule: str
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
    trigger: str
    pending: bool = False


class SchedulerTriggerResponse(BaseModel):
    task_id: str
    status: str
    message: str


# ── Single-match prediction ────────────────────────────────────────────────


class PredictResponse(BaseModel):
    status: str = "ok"
    message: str = ""
    prob_a: float | None = None
    prob_b: float | None = None
    hybrid_prob_a: float | None = None
    hybrid_prob_b: float | None = None
    model_name: str | None = None
    model_version: str | None = None
    diagnostics: dict[str, Any] | None = None


# ── Team alias mapping ──────────────────────────────────────────────────────


class AliasCreateRequest(BaseModel):
    raw_name: str = Field(min_length=1, description="Bookmaker/raw team name to map")
    golgg_team_name: str = Field(min_length=1, description="GolGG canonical team name to map to")


class AliasCreateResponse(BaseModel):
    id: int
    normalized_name: str
    alias: str
    source: str


class AliasDeleteRequest(BaseModel):
    raw_name: str = Field(min_length=1, description="Bookmaker/raw team name to unmap")


class AliasBlockRequest(BaseModel):
    raw_name: str = Field(min_length=1, description="Bookmaker/raw team name to mark as blocked")


class GolggTeamsResponse(BaseModel):
    teams: list[str]


# ── Match mapping ───────────────────────────────────────────────────────────


class UnmappedMatchItem(BaseModel):
    canonical_match_id: int
    team_a_name: str
    team_b_name: str
    team_a_mapping: TeamMappingInfo | None = None
    team_b_mapping: TeamMappingInfo | None = None
    start_time_normalized: str | None = None
    league: str | None = None
    status: str
    bookmakers: list[str] = []


class UnmappedMatchesResponse(BaseModel):
    total: int
    matches: list[UnmappedMatchItem]


class GolggMatchCandidate(BaseModel):
    match_id: str
    team1_name: str
    team2_name: str
    date: str
    team1_win: bool | None = None
    team2_win: bool | None = None


class GolggMatchCandidatesResponse(BaseModel):
    candidates: list[GolggMatchCandidate]


class MatchMappingRequest(BaseModel):
    canonical_match_id: int
    golgg_match_id: str


class MappingCheckResponse(BaseModel):
    is_mapped: bool
    canonical_match_id: int | None = None
    team_a: str | None = None
    team_b: str | None = None
    start_time: str | None = None
