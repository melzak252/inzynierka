CREATE TABLE IF NOT EXISTS bookmakers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    base_url TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS golgg_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_name TEXT NOT NULL UNIQUE,
    normalized_name TEXT NOT NULL UNIQUE,
    last_seen_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS team_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    golgg_team_id INTEGER,
    golgg_team_name TEXT,
    confidence REAL NOT NULL DEFAULT 0,
    confirmed_manually INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(normalized_name, source),
    FOREIGN KEY(golgg_team_id) REFERENCES golgg_teams(id)
);

CREATE TABLE IF NOT EXISTS golgg_matches (
    match_id TEXT PRIMARY KEY,
    date TEXT,
    tournament_name TEXT,
    patch TEXT,
    team1_name TEXT,
    team2_name TEXT,
    team1_id TEXT,
    team2_id TEXT,
    team1_score INTEGER,
    team2_score INTEGER,
    team1_win INTEGER,
    team2_win INTEGER,
    draw INTEGER,
    games_played INTEGER,
    best_of INTEGER,
    winner_name TEXT,
    loser_name TEXT,
    source_link TEXT,
    raw_json TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS golgg_games (
    game_id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    date TEXT,
    tournament_name TEXT,
    patch TEXT,
    team1_name TEXT,
    team2_name TEXT,
    team1_id TEXT,
    team2_id TEXT,
    team1_win INTEGER,
    team2_win INTEGER,
    draw INTEGER,
    team1_side TEXT,
    team2_side TEXT,
    game_duration INTEGER,
    team1_stats_json TEXT,
    team2_stats_json TEXT,
    raw_json TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(match_id) REFERENCES golgg_matches(match_id)
);

CREATE TABLE IF NOT EXISTS golgg_game_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    team_id TEXT,
    team_name TEXT,
    side TEXT NOT NULL CHECK(side IN ('t1', 't2')),
    role TEXT NOT NULL,
    player_id TEXT,
    player_name TEXT,
    champion_id TEXT,
    champion_name TEXT,
    champion_image TEXT,
    stats_json TEXT,
    raw_json TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(game_id, side, role),
    FOREIGN KEY(game_id) REFERENCES golgg_games(game_id),
    FOREIGN KEY(match_id) REFERENCES golgg_matches(match_id)
);

CREATE TABLE IF NOT EXISTS upcoming_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_match_id INTEGER,
    canonical_team_a TEXT,
    canonical_team_b TEXT,
    raw_team_a TEXT NOT NULL,
    raw_team_b TEXT NOT NULL,
    match_start_time TEXT,
    league TEXT,
    offer_url TEXT,
    status TEXT NOT NULL DEFAULT 'upcoming',
    bookmaker_match_key TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bookmaker_match_key),
    FOREIGN KEY(canonical_match_id) REFERENCES canonical_matches(id)
);

CREATE TABLE IF NOT EXISTS canonical_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_key TEXT NOT NULL UNIQUE,
    team_a_name TEXT NOT NULL,
    team_b_name TEXT NOT NULL,
    normalized_team_a TEXT NOT NULL,
    normalized_team_b TEXT NOT NULL,
    start_time_normalized TEXT,
    league TEXT,
    status TEXT NOT NULL DEFAULT 'upcoming',
    match_confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bookmaker_id INTEGER NOT NULL,
    match_id INTEGER,
    canonical_match_id INTEGER,
    scraped_at TEXT NOT NULL,
    source_url TEXT,
    offer_url TEXT,
    raw_league TEXT,
    raw_team_a TEXT NOT NULL,
    raw_team_b TEXT NOT NULL,
    mapped_team_a TEXT,
    mapped_team_b TEXT,
    match_start_time TEXT,
    odds_a REAL NOT NULL,
    odds_b REAL NOT NULL,
    market_type TEXT NOT NULL DEFAULT 'match_winner',
    is_live INTEGER NOT NULL DEFAULT 0,
    scraper_name TEXT,
    scraper_version TEXT,
    raw_payload TEXT,
    page_html_path TEXT,
    screenshot_path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(bookmaker_id) REFERENCES bookmakers(id),
    FOREIGN KEY(match_id) REFERENCES upcoming_matches(id),
    FOREIGN KEY(canonical_match_id) REFERENCES canonical_matches(id)
);

-- Normalized odds tracking schema.
-- Keep odds_snapshots above for the simple two-sided MVP UI. The tables below
-- are the canonical audit trail for real bookmaker APIs: scrape run -> event ->
-- market -> single outcome odds ticks. They support CLV, line movement and
-- deduplication even when the API returns only one selection from a market.

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bookmaker_id INTEGER NOT NULL,
    scraper_name TEXT NOT NULL,
    scraper_version TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    source_url TEXT,
    request_url TEXT,
    items_seen INTEGER NOT NULL DEFAULT 0,
    items_inserted INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(bookmaker_id) REFERENCES bookmakers(id)
);

CREATE TABLE IF NOT EXISTS bookmaker_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bookmaker_id INTEGER NOT NULL,
    bookmaker_event_id TEXT NOT NULL,
    match_id INTEGER,
    canonical_match_id INTEGER,
    raw_team_a TEXT NOT NULL,
    raw_team_b TEXT NOT NULL,
    mapped_team_a TEXT,
    mapped_team_b TEXT,
    match_start_time TEXT,
    sport_id TEXT,
    sport_name TEXT,
    category_id TEXT,
    category_name TEXT,
    league_id TEXT,
    league_name TEXT,
    offer_url TEXT,
    status TEXT NOT NULL DEFAULT 'upcoming',
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bookmaker_id, bookmaker_event_id),
    FOREIGN KEY(bookmaker_id) REFERENCES bookmakers(id),
    FOREIGN KEY(match_id) REFERENCES upcoming_matches(id),
    FOREIGN KEY(canonical_match_id) REFERENCES canonical_matches(id)
);

CREATE TABLE IF NOT EXISTS bookmaker_markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bookmaker_event_id INTEGER NOT NULL,
    bookmaker_market_key TEXT NOT NULL,
    market_name TEXT NOT NULL,
    market_type TEXT NOT NULL DEFAULT 'unknown',
    line_id TEXT,
    line_name TEXT,
    is_extra_market INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bookmaker_event_id, bookmaker_market_key),
    FOREIGN KEY(bookmaker_event_id) REFERENCES bookmaker_events(id)
);

CREATE TABLE IF NOT EXISTS odds_outcome_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bookmaker_id INTEGER NOT NULL,
    bookmaker_event_id INTEGER NOT NULL,
    bookmaker_market_id INTEGER NOT NULL,
    scrape_run_id INTEGER,
    scraped_at TEXT NOT NULL,
    source_url TEXT,
    offer_url TEXT,
    outcome_key TEXT NOT NULL,
    outcome_name TEXT NOT NULL,
    outcome_side TEXT,
    decimal_odds REAL NOT NULL,
    is_live INTEGER NOT NULL DEFAULT 0,
    scraper_name TEXT,
    scraper_version TEXT,
    raw_payload TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scrape_run_id, outcome_key),
    FOREIGN KEY(bookmaker_id) REFERENCES bookmakers(id),
    FOREIGN KEY(bookmaker_event_id) REFERENCES bookmaker_events(id),
    FOREIGN KEY(bookmaker_market_id) REFERENCES bookmaker_markets(id),
    FOREIGN KEY(scrape_run_id) REFERENCES scrape_runs(id)
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    predicted_at TEXT NOT NULL,
    prob_a REAL NOT NULL,
    prob_b REAL NOT NULL,
    features_version TEXT,
    ratings_version TEXT,
    data_cutoff_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(match_id) REFERENCES upcoming_matches(id)
);

CREATE TABLE IF NOT EXISTS bet_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    prediction_id INTEGER NOT NULL,
    odds_snapshot_id INTEGER NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('a', 'b')),
    odds REAL NOT NULL,
    model_prob REAL NOT NULL,
    market_prob REAL NOT NULL,
    ev REAL NOT NULL,
    tax_rate REAL NOT NULL,
    suggested_stake REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(match_id) REFERENCES upcoming_matches(id),
    FOREIGN KEY(prediction_id) REFERENCES predictions(id),
    FOREIGN KEY(odds_snapshot_id) REFERENCES odds_snapshots(id)
);

CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER,
    model_ev_signal_id INTEGER,
    bookmaker_account_id INTEGER,
    canonical_match_id INTEGER,
    placed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    bookmaker_id INTEGER,
    side TEXT NOT NULL CHECK(side IN ('a', 'b')),
    stake REAL NOT NULL,
    taken_odds REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    result TEXT,
    profit REAL NOT NULL DEFAULT 0,
    settled_at TEXT,
    team_a TEXT,
    team_b TEXT,
    league TEXT,
    match_start_time TEXT,
    model_prob REAL,
    ev REAL,
    tax_rate REAL DEFAULT 0.12,
    source TEXT NOT NULL DEFAULT 'manual',
    note TEXT,
    FOREIGN KEY(signal_id) REFERENCES bet_signals(id),
    FOREIGN KEY(model_ev_signal_id) REFERENCES model_ev_signals(id),
    FOREIGN KEY(bookmaker_account_id) REFERENCES bookmaker_accounts(id),
    FOREIGN KEY(canonical_match_id) REFERENCES canonical_matches(id),
    FOREIGN KEY(bookmaker_id) REFERENCES bookmakers(id)
);

CREATE TABLE IF NOT EXISTS bookmaker_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bookmaker_id INTEGER NOT NULL,
    account_name TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'PLN',
    opening_balance REAL NOT NULL DEFAULT 0,
    current_balance REAL NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bookmaker_id, account_name),
    FOREIGN KEY(bookmaker_id) REFERENCES bookmakers(id)
);

CREATE TABLE IF NOT EXISTS bookmaker_wallet_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bookmaker_account_id INTEGER NOT NULL,
    bet_id INTEGER,
    transaction_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    transaction_type TEXT NOT NULL,
    amount REAL NOT NULL,
    balance_after REAL NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(bookmaker_account_id) REFERENCES bookmaker_accounts(id),
    FOREIGN KEY(bet_id) REFERENCES bets(id)
);

CREATE TABLE IF NOT EXISTS bankroll_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    amount REAL NOT NULL,
    bankroll_after REAL NOT NULL,
    bet_id INTEGER,
    note TEXT,
    FOREIGN KEY(bet_id) REFERENCES bets(id)
);

CREATE TABLE IF NOT EXISTS rating_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('team', 'player')),
    team_name TEXT,
    player_name TEXT,
    rating_system TEXT NOT NULL,
    rating_value REAL NOT NULL,
    rd REAL,
    sigma REAL,
    source TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Operational model-inference schema.
-- These tables are intentionally separate from research artefacts. They store
-- the current rating/features state needed to score upcoming canonical matches.

CREATE TABLE IF NOT EXISTS model_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    artifact_path TEXT,
    feature_schema_json TEXT,
    model_params_json TEXT,
    training_cutoff_at TEXT,
    metrics_json TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(model_name, model_version)
);

CREATE TABLE IF NOT EXISTS rating_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ratings_version TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT 'golgg_sqlite',
    data_cutoff_at TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    systems_json TEXT,
    matches_processed INTEGER NOT NULL DEFAULT 0,
    games_processed INTEGER NOT NULL DEFAULT 0,
    players_processed INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS entity_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rating_run_id INTEGER NOT NULL,
    ratings_version TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('team', 'player')),
    entity_name TEXT NOT NULL,
    normalized_entity_name TEXT NOT NULL,
    team_name TEXT,
    role TEXT,
    rating_system TEXT NOT NULL,
    rating_value REAL NOT NULL,
    rd REAL,
    sigma REAL,
    games_played INTEGER NOT NULL DEFAULT 0,
    last_match_at TEXT,
    state_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ratings_version, entity_type, normalized_entity_name, rating_system),
    FOREIGN KEY(rating_run_id) REFERENCES rating_runs(id)
);

CREATE TABLE IF NOT EXISTS team_rolling_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_version TEXT NOT NULL,
    team_name TEXT NOT NULL,
    normalized_team_name TEXT NOT NULL,
    window_size INTEGER NOT NULL DEFAULT 20,
    data_cutoff_at TEXT,
    matches_count INTEGER NOT NULL DEFAULT 0,
    games_count INTEGER NOT NULL DEFAULT 0,
    win_rate REAL,
    avg_kills REAL,
    avg_deaths REAL,
    avg_gd15 REAL,
    avg_dpm REAL,
    avg_vspm REAL,
    avg_gold REAL,
    avg_towers REAL,
    avg_dragons REAL,
    avg_nashors REAL,
    avg_game_duration REAL,
    features_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(feature_version, normalized_team_name, window_size)
);

CREATE TABLE IF NOT EXISTS upcoming_match_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_match_id INTEGER NOT NULL,
    feature_version TEXT NOT NULL,
    ratings_version TEXT,
    data_cutoff_at TEXT,
    team_a_golgg_name TEXT,
    team_b_golgg_name TEXT,
    feature_status TEXT NOT NULL DEFAULT 'pending',
    missing_reason TEXT,
    features_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(canonical_match_id, feature_version, ratings_version),
    FOREIGN KEY(canonical_match_id) REFERENCES canonical_matches(id)
);

CREATE TABLE IF NOT EXISTS canonical_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_match_id INTEGER NOT NULL,
    model_artifact_id INTEGER,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    predicted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    prob_a REAL NOT NULL,
    prob_b REAL NOT NULL,
    features_version TEXT,
    ratings_version TEXT,
    data_cutoff_at TEXT,
    prediction_status TEXT NOT NULL DEFAULT 'active',
    diagnostics_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(canonical_match_id) REFERENCES canonical_matches(id),
    FOREIGN KEY(model_artifact_id) REFERENCES model_artifacts(id)
);

CREATE TABLE IF NOT EXISTS model_ev_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_match_id INTEGER NOT NULL,
    canonical_prediction_id INTEGER NOT NULL,
    odds_snapshot_id INTEGER NOT NULL,
    bookmaker_id INTEGER NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('a', 'b')),
    odds REAL NOT NULL,
    model_prob REAL NOT NULL,
    market_prob REAL,
    ev REAL NOT NULL,
    tax_rate REAL NOT NULL DEFAULT 0.12,
    stake_suggestion REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(canonical_match_id) REFERENCES canonical_matches(id),
    FOREIGN KEY(canonical_prediction_id) REFERENCES canonical_predictions(id),
    FOREIGN KEY(odds_snapshot_id) REFERENCES odds_snapshots(id),
    FOREIGN KEY(bookmaker_id) REFERENCES bookmakers(id)
);

-- Automation/scheduler observability.  These tables let the Streamlit UI show
-- what the laptop daemon did recently without SSH-ing into the machine.
CREATE TABLE IF NOT EXISTS automation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT NOT NULL,
    trigger_source TEXT NOT NULL DEFAULT 'scheduler',
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    interval_seconds INTEGER,
    next_run_at TEXT,
    host TEXT,
    pid INTEGER,
    commands_total INTEGER NOT NULL DEFAULT 0,
    commands_failed INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS automation_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    command TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    returncode INTEGER,
    duration_seconds REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES automation_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_odds_scraped_at ON odds_snapshots(scraped_at);
CREATE INDEX IF NOT EXISTS idx_odds_match ON odds_snapshots(match_id);
CREATE INDEX IF NOT EXISTS idx_golgg_matches_date ON golgg_matches(date);
CREATE INDEX IF NOT EXISTS idx_golgg_matches_teams ON golgg_matches(team1_name, team2_name);
CREATE INDEX IF NOT EXISTS idx_golgg_matches_tournament ON golgg_matches(tournament_name);
CREATE INDEX IF NOT EXISTS idx_golgg_games_match ON golgg_games(match_id);
CREATE INDEX IF NOT EXISTS idx_golgg_game_players_match ON golgg_game_players(match_id);
CREATE INDEX IF NOT EXISTS idx_golgg_game_players_player ON golgg_game_players(player_id);
CREATE INDEX IF NOT EXISTS idx_scrape_runs_bookmaker_started ON scrape_runs(bookmaker_id, started_at);
CREATE INDEX IF NOT EXISTS idx_bookmaker_events_lookup ON bookmaker_events(bookmaker_id, bookmaker_event_id);
CREATE INDEX IF NOT EXISTS idx_bookmaker_events_start ON bookmaker_events(match_start_time);
CREATE INDEX IF NOT EXISTS idx_bookmaker_markets_event ON bookmaker_markets(bookmaker_event_id);
CREATE INDEX IF NOT EXISTS idx_outcome_snapshots_event_time ON odds_outcome_snapshots(bookmaker_event_id, scraped_at);
CREATE INDEX IF NOT EXISTS idx_outcome_snapshots_market_time ON odds_outcome_snapshots(bookmaker_market_id, scraped_at);
CREATE INDEX IF NOT EXISTS idx_outcome_snapshots_outcome ON odds_outcome_snapshots(outcome_key);
CREATE INDEX IF NOT EXISTS idx_signals_status ON bet_signals(status);
CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status);
CREATE INDEX IF NOT EXISTS idx_wallet_transactions_account ON bookmaker_wallet_transactions(bookmaker_account_id, transaction_time);
CREATE INDEX IF NOT EXISTS idx_alias_normalized ON team_aliases(normalized_name);
CREATE INDEX IF NOT EXISTS idx_entity_ratings_lookup ON entity_ratings(ratings_version, entity_type, normalized_entity_name, rating_system);
CREATE INDEX IF NOT EXISTS idx_rating_runs_status ON rating_runs(status, data_cutoff_at);
CREATE INDEX IF NOT EXISTS idx_team_rolling_lookup ON team_rolling_features(feature_version, normalized_team_name, window_size);
CREATE INDEX IF NOT EXISTS idx_upcoming_features_match ON upcoming_match_features(canonical_match_id, feature_status);
CREATE INDEX IF NOT EXISTS idx_canonical_predictions_match ON canonical_predictions(canonical_match_id, prediction_status, predicted_at);
CREATE INDEX IF NOT EXISTS idx_model_ev_signals_match ON model_ev_signals(canonical_match_id, status);
CREATE INDEX IF NOT EXISTS idx_automation_runs_started ON automation_runs(started_at, status);
CREATE INDEX IF NOT EXISTS idx_automation_commands_run ON automation_commands(run_id, started_at);

INSERT OR IGNORE INTO bookmakers(name, base_url) VALUES
    ('manual', NULL),
    ('sts', 'https://www.sts.pl/'),
    ('betclic', 'https://www.betclic.pl/'),
    ('superbet', 'https://superbet.pl/'),
    ('efortuna', 'https://www.efortuna.pl/'),
    ('fortuna', 'https://www.efortuna.pl/'),
    ('betfan', 'https://betfan.pl/'),
    ('totalbet', 'https://totalbet.pl/'),
    ('lebull', 'https://www.lebull.pl/');
