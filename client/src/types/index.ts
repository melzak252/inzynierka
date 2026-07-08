// Match board types
export interface MatchBoardItem {
  canonical_match_id: number;
  match: string;
  league: string | null;
  start_time_normalized: string | null;
  best_of: number | null;
  team_a_name: string | null;
  team_b_name: string | null;
  team_a_golgg_name: string | null;
  team_b_golgg_name: string | null;
  team_a_mapping_source: string | null;
  team_b_mapping_source: string | null;
  has_unmapped_teams: boolean;
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
  source: string | null;
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
  best_of: number | null;
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
    task_name: string;
    status: string;
    last_scraped_at: string | null;
    started_at: string | null;
    duration_seconds: number | null;
    snapshot_count: number;
  }>;
  last_automation_runs: Array<{
    run_type: string;
    task_name: string;
    status: string;
    started_at: string | null;
    finished_at: string | null;
    duration_seconds: number | null;
    summary: string | null;
  }>;
}

export interface BookmakerStatus {
  id: number;
  name: string;
  base_url: string | null;
  last_scraped_at: string | null;
  last_scrape: string | null;
  snapshot_count: number;
}

// Scheduler types
export interface SchedulerTask {
  id: string;
  task_id: string;
  name: string;
  description: string;
  schedule: string;
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
  trigger: string;
  pending: boolean;
}

export interface SchedulerRun {
  id: number;
  run_type: string;
  task_name: string;
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
  step_order: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  duration_seconds: number | null;
  output: string | null;
}

export interface SchedulerTriggerResponse {
  task_id: string;
  status: string;
  message: string;
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

export interface ModelReferenceMetrics {
  model_name: string;
  model_version: string;
  avg_logloss: number | null;
  avg_auc: number | null;
  n_matches: number;
}

export interface HybridBinMetrics {
  label: string;
  hours_start: number;
  hours_end: number | null;
  snapshot_count: number;
  match_count: number;
  avg_logloss: number | null;
  avg_auc: number | null;
}

export interface HybridModelBins {
  model_name: string;
  model_version: string;
  bins: HybridBinMetrics[];
}

export interface BookmakerBinMetrics {
  bookmaker_id: number;
  bookmaker_name: string;
  bins: HybridBinMetrics[];
}

export interface MarketCloseCompetitor {
  name: string;
  display_name: string;
  n_matches: number;
  avg_logloss: number | null;
  avg_auc: number | null;
  avg_brier: number | null;
  accuracy: number | null;
  rank: number;
}

export interface MarketCloseBookmaker extends MarketCloseCompetitor {
  bookmaker_id: number;
  bookmaker_name: string;
}

export interface MarketCloseComparison {
  sample_definition: string;
  n_matches: number;
  min_matches: number;
  avg_bookmakers_per_match: number | null;
  model_delta_logloss_vs_market: number | null;
  hybrid_delta_logloss_vs_market: number | null;
  status: 'model_better' | 'model_on_market_level' | 'model_worse' | 'no_data' | 'unknown';
  competitors: MarketCloseCompetitor[];
  bookmakers: MarketCloseBookmaker[];
}

export interface ModelVsBookmakerTest {
  id: string;
  label: string;
  metric: 'logloss' | 'brier' | string;
  model_name: string;
  baseline_name: string;
  alternative: string;
  interpretation: string;
  n: number;
  df: number;
  mean_diff: number;
  sd_diff: number;
  sem_diff: number;
  t_stat: number | null;
  p_value_one_sided: number;
  alpha: number;
  t_critical_95_one_sided: number | null;
  significant: boolean;
}

export interface HorizonAccuracyResponse {
  total_matches_with_odds: number;
  total_finished_matches: number;
  total_odds_processed: number;
  bins: HorizonBin[];
  min_matches_per_bin: number;
  model_references: ModelReferenceMetrics[];
  hybrid_model_bins: HybridModelBins[];
  bookmaker_bins: BookmakerBinMetrics[];
  model_vs_bookmaker_tests: ModelVsBookmakerTest[];
  market_close_comparison: MarketCloseComparison;
}

export type ModelAnalysisKey = 'thesis' | 'hybrid';

export interface ModelClvBin {
  model_key: ModelAnalysisKey | string;
  model_label: string;
  label: string;
  hours_start: number;
  hours_end: number | null;
  entry_count: number;
  match_count: number;
  observation_count: number;
  avg_hours_before: number | null;
  avg_clv_odds_pct: number | null;
  median_clv_odds_pct: number | null;
  avg_clv_probability_pp: number | null;
  median_clv_probability_pp: number | null;
  positive_clv_rate: number | null;
  avg_ev: number | null;
  weighting: 'signal' | 'match' | string;
}

export interface ModelClvModelSummary {
  model_key: ModelAnalysisKey | string;
  model_label: string;
  signal_weighted_bins: ModelClvBin[];
  match_weighted_bins: ModelClvBin[];
}

export interface ModelClvByHorizonResponse {
  metadata: {
    max_days_back: number;
    max_odds_age_hours: number;
    tax_rate: number;
    min_ev: number;
    entry_definition: string;
    closing_definition: string;
    clv_odds_pct_definition: string;
  };
  total_predictions_scanned: number;
  total_entries: number;
  models: ModelClvModelSummary[];
  signal_weighted_bins: ModelClvBin[];
  match_weighted_bins: ModelClvBin[];
  skips: Record<string, number>;
}

// Prediction & EV history timeline
export interface PredictionHistoryPoint {
  timestamp: string;
  model_name: string;
  model_version: string;
  prob_a: number | null;
  prob_b: number | null;
  avg_odds_a: number | null;
  avg_odds_b: number | null;
  market_prob_a: number | null;
  market_prob_b: number | null;
  ev_a: number | null;
  ev_b: number | null;
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

// Match result types
export interface BookmakerEvSide {
  ev: number | null;
  odds: number | null;
}

export interface BookmakerEvDetail {
  side_a: BookmakerEvSide;
  side_b: BookmakerEvSide;
}

export interface MatchResultItem {
  canonical_match_id: number;
  team_a_name: string | null;
  team_b_name: string | null;
  league: string | null;
  start_time_normalized: string | null;
  best_of: number | null;
  status: string | null;
  winner_name: string | null;
  loser_name: string | null;
  winner_side: string | null;
  team_a_score: number | null;
  team_b_score: number | null;
  result_source: string | null;
  result_recorded_at: string | null;
  best_ev_a: number | null;
  best_ev_b: number | null;
  bookmakers_with_ev: string[];
  best_odds_a: number | null;
  best_odds_b: number | null;
  bookmaker_ev_details: Record<string, BookmakerEvDetail>;
}

export interface MatchResultsResponse {
  total: number;
  days_back: number;
  results: MatchResultItem[];
}

// Alias mapping types
export interface AliasCreateRequest {
  raw_name: string;
  golgg_team_name: string;
}

export interface AliasCreateResponse {
  id: number;
  normalized_name: string;
  alias: string;
  source: string;
}

export interface AliasDeleteRequest {
  raw_name: string;
}

export interface AliasBlockRequest {
  raw_name: string;
}

export interface GolggTeamsResponse {
  teams: string[];
}

// ─── Bootstrap Analysis Types ─────────────────────────────────────────

export interface HorizonBootstrapBin {
  model_label: string;
  model_name: string;
  comparison: string;
  label: string;
  hours_start: number | null;
  hours_end: number | null;
  sample_size: number | null;
  n_blocks: number | null;
  model_logloss: number | null;
  benchmark_logloss: number | null;
  observed_difference: number | null;
  ci_low: number | null;
  ci_high: number | null;
  p_one_sided: number | null;
  significant_05: boolean;
}

export interface HorizonBootstrapMonthly {
  month: string;
  n_snapshots: number | null;
  n_matches: number | null;
  model_logloss: number | null;
  bookmaker_logloss: number | null;
  mean_difference: number | null;
  horizon_bin: string;
  model_label: string;
}

export interface HorizonBootstrapResponse {
  bins: HorizonBootstrapBin[];
  monthly: HorizonBootstrapMonthly[];
  last_updated: string | null;
  plot_available: boolean;
  match_stats: {
    upcoming: number | null;
    finished: number | null;
    expired: number | null;
  };
}

// Match mapping types
export interface UnmappedMatchItem {
  canonical_match_id: number;
  team_a_name: string;
  team_b_name: string;
  start_time_normalized: string | null;
  league: string | null;
  status: string;
  bookmakers?: string[];
}

export interface UnmappedMatchesResponse {
  total: number;
  matches: UnmappedMatchItem[];
}

export interface GolggMatchCandidate {
  match_id: number;
  team1_name: string;
  team2_name: string;
  date: string;
  team1_win: boolean | null;
  team2_win: boolean | null;
}

export interface GolggMatchCandidatesResponse {
  candidates: GolggMatchCandidate[];
}

export interface MatchMappingRequest {
  canonical_match_id: number;
  golgg_match_id: number;
}

export interface MappingCheckResponse {
  is_mapped: boolean;
  canonical_match_id: number | null;
  team_a: string | null;
  team_b: string | null;
  start_time: string | null;
}
