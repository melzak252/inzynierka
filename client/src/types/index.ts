// Match board types
export interface MatchBoardItem {
  canonical_match_id: number;
  match: string;
  league: string | null;
  start_time_normalized: string | null;
  team_a_name: string | null;
  team_b_name: string | null;
  bookmaker_count: number;
  best_odds_a: number | null;
  best_bookmaker_a: string | null;
  avg_odds_a: number | null;
  best_odds_b: number | null;
  best_bookmaker_b: string | null;
  avg_odds_b: number | null;
  arb_no_tax: boolean;
  arb_after_tax: boolean;
  arb_margin_no_tax: number | null;
  arb_margin_after_tax: number | null;
  model_prob_a: number | null;
  model_prob_b: number | null;
  hybrid_prob_a: number | null;
  hybrid_prob_b: number | null;
  hybrid_ev_a: number | null;
  hybrid_ev_b: number | null;
  last_scraped_at: string | null;
}

export interface MatchBoardResponse {
  total: number;
  matches: MatchBoardItem[];
}

// Match detail types
export interface BookmakerOddsRow {
  bookmaker: string;
  raw_team_a: string | null;
  raw_team_b: string | null;
  canonical_odds_a: number | null;
  canonical_odds_b: number | null;
  scraped_at: string | null;
  source_url: string | null;
  offer_url: string | null;
  ev_a: number | null;
  ev_b: number | null;
  kelly_a: number | null;
  kelly_b: number | null;
}

export interface PredictionRow {
  model_name: string;
  model_version: string;
  prob_a: number | null;
  prob_b: number | null;
  predicted_at: string | null;
  ev_a: number | null;
  ev_b: number | null;
  kelly_a: number | null;
  kelly_b: number | null;
}

export interface RosterPlayer {
  player_name: string | null;
  role: string | null;
  champion_name: string | null;
  glicko_rating: number | null;
  glicko_rd: number | null;
  games_played: number | null;
}

export interface RosterInfo {
  team_name: string | null;
  source_match_id: string | null;
  source_date: string | null;
  players: RosterPlayer[];
}

export interface TeamMappingInfo {
  canonical_name: string | null;
  golgg_name: string | null;
  confidence: number | null;
}

export interface TeamComparisonInfo {
  team_a: TeamMappingInfo | null;
  team_b: TeamMappingInfo | null;
  team_a_rating: number | null;
  team_b_rating: number | null;
  rating_system: string | null;
}

export interface MatchDetailResponse {
  canonical_match_id: number;
  team_a_name: string | null;
  team_b_name: string | null;
  league: string | null;
  start_time_normalized: string | null;
  status: string | null;
  odds: BookmakerOddsRow[];
  predictions: PredictionRow[];
  roster_a: RosterInfo | null;
  roster_b: RosterInfo | null;
  team_comparison: TeamComparisonInfo | null;
}

// System status types
export interface SystemStatusResponse {
  counts: Record<string, number>;
  last_scrape_runs: Array<{
    name: string;
    last_scraped_at: string | null;
    snapshot_count: number;
  }>;
  last_automation_runs: Array<{
    run_type: string;
    status: string;
    started_at: string | null;
    finished_at: string | null;
    summary: string | null;
  }>;
}

export interface BookmakerStatus {
  id: number;
  name: string;
  base_url: string | null;
  last_scraped_at: string | null;
  snapshot_count: number;
}

// Scheduler types
export interface SchedulerTask {
  id: string;
  name: string;
  description: string;
  interval_minutes: number | null;
  cron_trigger: string | null;
  enabled: boolean;
}

export interface SchedulerJob {
  id: string;
  name: string;
  enabled: boolean;
  next_run_time: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
  is_running: boolean;
}

export interface SchedulerRun {
  id: number;
  run_type: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  duration_seconds: number | null;
}

export interface SchedulerCommand {
  id: number;
  command: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface SchedulerTriggerResponse {
  task_id: string;
  status: string;
  message: string;
}

// Timing analysis types — NEW FORMAT (2h fixed buckets, % dev from closing)
export interface TimingBucket {
  bucket: string;                // e.g. "0-2h", "2-4h", "4-6h"
  hours_start: number;           // e.g. 0, 2, 4
  hours_end: number;             // e.g. 2, 4, 6
  snapshot_count: number;
  match_count: number;
  avg_deviation_a_pct: number;   // avg % diff from closing odds for team A
  avg_deviation_b_pct: number;   // avg % diff from closing odds for team B
  std_deviation_a_pct: number;
  std_deviation_b_pct: number;
  avg_odds_a: number;
  avg_odds_b: number;
  avg_closing_odds_a: number;
  avg_closing_odds_b: number;
}

export interface DriftSummary {
  earliest_bucket: string;
  latest_bucket: string;
  open_deviation_a_pct: number;
  open_deviation_b_pct: number;
  close_deviation_a_pct: number;
  close_deviation_b_pct: number;
  convergence_a_pct: number;     // how much deviation shrunk (positive = converging)
  convergence_b_pct: number;
}

export interface BestBettingWindow {
  bucket: string;
  hours_start: number;
  hours_end: number;
  avg_favorable_deviation_pct: number;
  avg_deviation_a_pct: number;
  avg_deviation_b_pct: number;
  match_count: number;
  snapshot_count: number;
  recommendation: string;
}

export interface TimingAnalysisResponse {
  total_matches: number;
  total_snapshots: number;
  time_buckets: TimingBucket[];
  drift_summary: DriftSummary | null;
  best_betting_window: BestBettingWindow | null;
  summary?: {
    message?: string;
  };
}

// Match movement — NEW FORMAT with deviation % from closing
export interface OddsMovementPoint {
  scraped_at: string;
  hours_before_match: number | null;
  bookmaker: string;
  odds_a: number;
  odds_b: number;
  deviation_a_pct?: number;
  deviation_b_pct?: number;
}

// Horizon accuracy types
export interface HorizonBin {
  label: string;                 // e.g. "0-2h", "2-6h", "6-12h"
  hours_start: number;
  hours_end: number | null;      // null for 48h+ (unbounded)
  snapshot_count: number;
  match_count: number;
  avg_logloss: number | null;
  avg_auc: number | null;
  avg_prob_winner: number | null;
  avg_prob_loser: number | null;
}

export interface HorizonAccuracyResponse {
  total_matches_with_odds: number;
  total_finished_matches: number;
  total_odds_processed: number;
  bins: HorizonBin[];
  min_matches_per_bin: number;
}

export interface MatchMovementResponse {
  match_id: number;
  team_a: string | null;
  team_b: string | null;
  start_time: string | null;
  movement_points: OddsMovementPoint[];
  summary: {
    total_snapshots?: number;
    first_snapshot?: string;
    last_snapshot?: string;
    opening_odds_a?: number;
    opening_odds_b?: number;
    closing_odds_a?: number;
    closing_odds_b?: number;
    opening_deviation_a_pct?: number;
    opening_deviation_b_pct?: number;
    total_drift_a?: number;
    total_drift_b?: number;
    message?: string;
  };
}
