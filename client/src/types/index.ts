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
  match_confidence: number | null;
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
  player_id: string | null;
  player_name: string | null;
  role: string | null;
  champion_name: string | null;
  elo_rating: number | null;
  glicko_rating: number | null;
  glicko_rd: number | null;
  trueskill_rating: number | null;
  rating_uncertainty: number | null;
  games_played: number | null;
}

export interface RosterInfo {
  team_name: string | null;
  source_match_id: string | null;
  source_date: string | null;
  source_tournament: string | null;
  roster_source: string | null;
  avg_elo: number | null;
  avg_glicko: number | null;
  avg_glicko_rd: number | null;
  players_with_rating: number | null;
  players: RosterPlayer[];
}

export interface RosterOverridePlayerInput {
  player_id?: string | null;
  player_name: string;
  role?: string | null;
}

export interface RosterPlayerCandidate {
  player_id: string;
  player_name: string;
  role: string | null;
  team_name: string | null;
  is_expected_team: boolean;
}

export interface MatchRosterOverrideResponse {
  canonical_match_id: number;
  team_side: 'a' | 'b';
  roster: RosterInfo;
  message: string;
}

export interface TeamRecentStats {
  team_name: string | null;
  matches_count: number | null;
  games_count: number | null;
  win_rate: number | null;
  avg_kills: number | null;
  avg_deaths: number | null;
  avg_gd15: number | null;
  avg_dragons: number | null;
  avg_nashors: number | null;
  avg_towers: number | null;
  avg_game_duration: number | null;
  last_match_at: string | null;
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
  team_a_elo: number | null;
  team_b_elo: number | null;
  team_a_glicko: number | null;
  team_b_glicko: number | null;
  team_a_glicko_rd: number | null;
  team_b_glicko_rd: number | null;
  team_a_games_played: number | null;
  team_b_games_played: number | null;
  rating_probabilities: Record<string, number>;
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
  roster_a_is_manual: boolean;
  roster_b_is_manual: boolean;
  recent_stats_a: TeamRecentStats | null;
  recent_stats_b: TeamRecentStats | null;
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
  evaluation_scope?: {
    kind: string;
    prediction_source: string;
    prediction_rule: string;
    warning: string;
  };
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
  aggregation_level: 'model_match_horizon' | string;
}

export interface ModelClvModelSummary {
  model_key: ModelAnalysisKey | string;
  model_label: string;
  bins: ModelClvBin[];
}

export interface ModelClvByHorizonResponse {
  metadata: {
    max_days_back: number;
    max_odds_age_hours: number;
    tax_rate: number;
    min_ev: number;
    aggregation_level: string;
    entry_definition: string;
    closing_definition: string;
    clv_odds_pct_definition: string;
    aggregation_definition?: string;
  };
  total_predictions_scanned: number;
  total_entries: number;
  models: ModelClvModelSummary[];
  bins: ModelClvBin[];
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
  model_prob: number | null;
  kelly: number | null;
  market_prob?: number | null;
  odds_snapshot_id?: number | null;
  scraped_at?: string | null;
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
  model_prob_a: number | null;
  model_prob_b: number | null;
  kelly_a: number | null;
  kelly_b: number | null;
  bookmaker_ev_details: Record<string, BookmakerEvDetail>;
  model_name?: string | null;
  model_version?: string | null;
  odds_mode?: string | null;
}

export interface MatchResultsResponse {
  total: number;
  days_back: number;
  model_name?: string | null;
  model_version?: string | null;
  odds_mode?: string | null;
  results: MatchResultItem[];
}

export interface FinancialBucket {
  key: string;
  label: string;
  bets: number;
  matches: number;
  staked: number;
  profit: number;
  roi: number | null;
  hit_rate: number | null;
  avg_ev: number | null;
  avg_clv_odds_pct: number | null;
  median_clv_odds_pct: number | null;
}

export interface FinancialLedgerEntry {
  canonical_match_id: number;
  start_time: string | null;
  league: string | null;
  team_a_name: string | null;
  team_b_name: string | null;
  bookmaker: string;
  side: string;
  entry_odds: number;
  close_odds: number | null;
  hours_before: number | null;
  horizon: string;
  model_prob: number;
  market_prob: number;
  ev: number;
  stake: number;
  profit: number;
  bankroll_after: number;
  won: boolean;
  clv_odds_pct: number | null;
  entry_scraped_at: string | null;
  close_scraped_at: string | null;
}

export interface FinancialAnalysisResponse {
  methodology: string;
  data_scope: string;
  days_back: number;
  odds_mode: string;
  model_name: string;
  model_version: string;
  staking_mode: string;
  min_ev: number;
  initial_bankroll: number;
  final_bankroll: number;
  total_bets: number;
  total_matches: number;
  total_staked: number;
  total_profit: number;
  roi: number | null;
  hit_rate: number | null;
  max_drawdown_pct: number | null;
  avg_clv_odds_pct: number | null;
  positive_clv_rate: number | null;
  max_open_stake: number;
  max_open_bets: number;
  temporal_exclusions: Record<string, number>;
  horizon_buckets: FinancialBucket[];
  bookmaker_buckets: FinancialBucket[];
  league_buckets: FinancialBucket[];
  bankroll_curve: Array<{ index: number; bankroll: number; profit: number; start_time: string | null; canonical_match_id?: number | null }>;
  ledger: FinancialLedgerEntry[];
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
  metadata?: {
    aggregation_level?: string;
    sample_size_definition?: string;
    bootstrap_unit?: string;
    snapshot_role?: string;
  };
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
  team_a_mapping?: TeamMappingInfo | null;
  team_b_mapping?: TeamMappingInfo | null;
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

// ─── Embedding Diagnostics ───────────────────────────────────────────

export interface ChampionEmbeddingPoint {
  champion_id: string;
  champion_name: string;
  role: string | null;
  x: number;
  y: number;
  x_norm: number;
  y_norm: number;
  n_games: number | null;
  recent_games: number | null;
  recent_window_days: number | null;
  recent_date_max: string | null;
  win_rate: number | null;
  fallback_level: string | null;
  window_days: number | null;
  shrinkage_weight_observed: number | null;
  age_days_mean: number | null;
  kda: number | null;
  damage_share: number | null;
  gold_share: number | null;
  kill_participation: number | null;
  cluster_id: number | null;
  cluster_label: string | null;
}

export interface ChampionEmbeddingProjectionResponse {
  metadata: {
    artifact_path: string;
    method: 'umap' | 'tsne' | 'pca';
    requested_method: 'umap' | 'tsne' | 'pca';
    preset: 'local' | 'balanced' | 'global';
    preset_config: {
      label: string;
      description: string;
      umap_n_neighbors: number;
      umap_min_dist: number;
      umap_metric: string;
      tsne_perplexity: number;
    };
    projection_warning?: string | null;
    snapshot: string;
    available_snapshots: string[];
    role: string;
    min_games: number;
    min_games_column: string;
    recent_window_days: number | null;
    total_points: number;
    cluster_count: number;
    cluster_counts: Record<string, number>;
    available_roles: string[];
    source_rows: number | null;
    reference_date: string | null;
    embedding_dim: number | null;
    model_name: string;
    model_version: string;
    fallback_counts: Record<string, number>;
  };
  points: ChampionEmbeddingPoint[];
}
