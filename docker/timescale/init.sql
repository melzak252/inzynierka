/* TimescaleDB initialisation: full schema + hypertables. */

/* Enable the extension */
CREATE EXTENSION IF NOT EXISTS timescaledb;

/* ── Bookmakers ──────────────────────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS bookmakers (
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(100) UNIQUE NOT NULL,
    base_url VARCHAR(500),
    is_active INTEGER DEFAULT 1
);

INSERT INTO bookmakers(name, base_url) VALUES
    ('manual', NULL),
    ('sts', 'https://www.sts.pl/'),
    ('betclic', 'https://www.betclic.pl/'),
    ('superbet', 'https://superbet.pl/'),
    ('efortuna', 'https://www.efortuna.pl/'),
    ('fortuna', 'https://www.efortuna.pl/'),
    ('betfan', 'https://betfan.pl/'),
    ('totalbet', 'https://totalbet.pl/'),
    ('lebull', 'https://www.lebull.pl/')
ON CONFLICT (name) DO NOTHING;

/* ── Bookmaker accounts / wallets ────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS bookmaker_accounts (
    id               SERIAL PRIMARY KEY,
    bookmaker_id     INTEGER NOT NULL REFERENCES bookmakers(id),
    account_name     VARCHAR(100) NOT NULL,
    currency         VARCHAR(10) DEFAULT 'PLN',
    opening_balance  NUMERIC(12,2) DEFAULT 0,
    current_balance  NUMERIC(12,2) DEFAULT 0,
    is_active        INTEGER DEFAULT 1,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(bookmaker_id, account_name)
);

/* ── Bets ────────────────────────────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS bets (
    id                    SERIAL PRIMARY KEY,
    signal_id             INTEGER,
    model_ev_signal_id    INTEGER,
    bookmaker_account_id  INTEGER REFERENCES bookmaker_accounts(id),
    canonical_match_id    INTEGER REFERENCES canonical_matches(id),
    placed_at             TIMESTAMPTZ DEFAULT NOW(),
    bookmaker_id          INTEGER,
    side                  VARCHAR(1) CHECK (side IN ('a','b')) NOT NULL,
    stake                 NUMERIC(12,2) NOT NULL,
    taken_odds            NUMERIC(8,4) NOT NULL,
    status                VARCHAR(20) DEFAULT 'open',
    result                VARCHAR(20),
    profit                NUMERIC(12,2) DEFAULT 0,
    settled_at            TIMESTAMPTZ,
    team_a                VARCHAR(200),
    team_b                VARCHAR(200),
    league                VARCHAR(100),
    match_start_time      TIMESTAMPTZ,
    model_prob            NUMERIC(6,4),
    ev                    NUMERIC(10,4),
    tax_rate              NUMERIC(4,2) DEFAULT 0.12,
    note                  TEXT,
    source                VARCHAR(50) DEFAULT 'manual'
);

/* ── Wallet transactions (time-series) ───────────────────────────────────── */
CREATE TABLE IF NOT EXISTS bookmaker_wallet_transactions (
    id                    SERIAL PRIMARY KEY,
    bookmaker_account_id  INTEGER NOT NULL REFERENCES bookmaker_accounts(id),
    bet_id                INTEGER REFERENCES bets(id),
    transaction_time      TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    transaction_type      VARCHAR(50) NOT NULL,
    amount                NUMERIC(12,2) NOT NULL,
    balance_after         NUMERIC(12,2) NOT NULL,
    note                  TEXT
);
SELECT create_hypertable('bookmaker_wallet_transactions', 'transaction_time',
    if_not_exists => TRUE, migrate_data => TRUE);

/* ── GOL.GG data ─────────────────────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS golgg_teams (
    id              SERIAL PRIMARY KEY,
    team_name       VARCHAR(200) UNIQUE NOT NULL,
    team_id         INTEGER UNIQUE,
    normalized_name VARCHAR(200)
);

CREATE TABLE IF NOT EXISTS golgg_matches (
    match_id        VARCHAR(50) PRIMARY KEY,
    date            VARCHAR(20),
    tournament_name VARCHAR(300),
    patch           VARCHAR(20),
    team1_name      VARCHAR(200),
    team2_name      VARCHAR(200),
    team1_id        VARCHAR(50),
    team2_id        VARCHAR(50),
    team1_score     INTEGER,
    team2_score     INTEGER,
    team1_win       INTEGER,
    team2_win       INTEGER,
    draw            INTEGER,
    games_played    INTEGER,
    best_of         INTEGER,
    winner_name     VARCHAR(200),
    loser_name      VARCHAR(200),
    source_link     VARCHAR(500),
    raw_json        TEXT
);

CREATE TABLE IF NOT EXISTS golgg_games (
    game_id         VARCHAR(50) PRIMARY KEY,
    match_id        VARCHAR(50) NOT NULL REFERENCES golgg_matches(match_id),
    date            VARCHAR(20),
    tournament_name VARCHAR(300),
    patch           VARCHAR(20),
    team1_name      VARCHAR(200),
    team2_name      VARCHAR(200),
    team1_id        VARCHAR(50),
    team2_id        VARCHAR(50),
    team1_win       INTEGER,
    team2_win       INTEGER,
    draw            INTEGER,
    team1_side      VARCHAR(10),
    team2_side      VARCHAR(10),
    game_duration   INTEGER,
    team1_stats_json TEXT,
    team2_stats_json TEXT,
    raw_json        TEXT
);
CREATE INDEX IF NOT EXISTS idx_golgg_games_match ON golgg_games(match_id);

CREATE TABLE IF NOT EXISTS golgg_game_players (
    id              SERIAL PRIMARY KEY,
    game_id         VARCHAR(50) NOT NULL REFERENCES golgg_games(game_id),
    match_id        VARCHAR(50) REFERENCES golgg_matches(match_id),
    team_id         VARCHAR(50),
    team_name       VARCHAR(200),
    side            VARCHAR(5) NOT NULL,
    role            VARCHAR(20),
    player_id       VARCHAR(50),
    player_name     VARCHAR(200),
    champion_id     VARCHAR(50),
    champion_name   VARCHAR(100),
    champion_image  VARCHAR(500),
    stats_json      TEXT,
    raw_json        TEXT,
    UNIQUE(game_id, side, role)
);
CREATE INDEX IF NOT EXISTS idx_golgg_game_players_player ON golgg_game_players(player_id);

CREATE TABLE IF NOT EXISTS team_aliases (
    id              SERIAL PRIMARY KEY,
    normalized_name VARCHAR(200) NOT NULL,
    alias           VARCHAR(200) NOT NULL,
    source          VARCHAR(50) NOT NULL,
    UNIQUE(normalized_name, source)
);

/* ── Canonical matches ───────────────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS canonical_matches (
    id                    SERIAL PRIMARY KEY,
    canonical_key         VARCHAR(100) UNIQUE NOT NULL,
    team_a_name           VARCHAR(200) NOT NULL,
    team_b_name           VARCHAR(200) NOT NULL,
    normalized_team_a     VARCHAR(200) NOT NULL,
    normalized_team_b     VARCHAR(200) NOT NULL,
    start_time_normalized VARCHAR(50),
    league                VARCHAR(100),
    status                VARCHAR(50) DEFAULT 'upcoming',
    match_confidence      REAL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS upcoming_matches (
    id                  SERIAL PRIMARY KEY,
    bookmaker_id        INTEGER NOT NULL REFERENCES bookmakers(id),
    bookmaker_match_key VARCHAR(200) NOT NULL,
    canonical_match_id  INTEGER REFERENCES canonical_matches(id),
    raw_team_a          VARCHAR(200) NOT NULL,
    raw_team_b          VARCHAR(200) NOT NULL,
    normalized_team_a   VARCHAR(200) NOT NULL,
    normalized_team_b   VARCHAR(200) NOT NULL,
    match_start_time    VARCHAR(50),
    league              VARCHAR(100),
    source_url          VARCHAR(500),
    offer_url           VARCHAR(500),
    is_live             INTEGER DEFAULT 0,
    UNIQUE(bookmaker_match_key)
);

/* ── Odds snapshots (time-series) ────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS odds_snapshots (
    id                  SERIAL,
    bookmaker_id        INTEGER NOT NULL REFERENCES bookmakers(id),
    match_id            INTEGER,
    canonical_match_id  INTEGER REFERENCES canonical_matches(id),
    market_type         VARCHAR(50) DEFAULT 'match_winner',
    raw_team_a          VARCHAR(200),
    raw_team_b          VARCHAR(200),
    odds_a              REAL,
    odds_b              REAL,
    is_live             INTEGER DEFAULT 0,
    scraped_at          TIMESTAMPTZ DEFAULT NOW(),
    source_url          VARCHAR(500),
    offer_url           VARCHAR(500),
    raw_payload         TEXT
);
SELECT create_hypertable('odds_snapshots', 'scraped_at',
    if_not_exists => TRUE, migrate_data => TRUE);
CREATE INDEX IF NOT EXISTS idx_odds_bookmaker ON odds_snapshots(bookmaker_id, scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_odds_canonical ON odds_snapshots(canonical_match_id);

/* ── Scrape runs ─────────────────────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS scrape_runs (
    id              SERIAL PRIMARY KEY,
    bookmaker_id    INTEGER REFERENCES bookmakers(id),
    scraper_name    VARCHAR(100) NOT NULL,
    scraper_version VARCHAR(50),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    status          VARCHAR(50) DEFAULT 'running',
    source_url      VARCHAR(500),
    request_url     VARCHAR(500),
    items_seen      INTEGER DEFAULT 0,
    items_inserted  INTEGER DEFAULT 0,
    error           TEXT
);

/* ── Bookmaker events / outcomes ─────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS bookmaker_events (
    id                  SERIAL PRIMARY KEY,
    bookmaker_id        INTEGER NOT NULL REFERENCES bookmakers(id),
    bookmaker_event_id  VARCHAR(100) NOT NULL,
    canonical_match_id  INTEGER REFERENCES canonical_matches(id),
    raw_team_a          VARCHAR(200) NOT NULL,
    raw_team_b          VARCHAR(200) NOT NULL,
    match_start_time    VARCHAR(50),
    sport_id            VARCHAR(20),
    sport_name          VARCHAR(100),
    category_id         VARCHAR(20),
    category_name       VARCHAR(100),
    league_id           VARCHAR(20),
    league_name         VARCHAR(100),
    first_seen_at       TIMESTAMPTZ,
    last_seen_at        TIMESTAMPTZ,
    offer_url           VARCHAR(500),
    UNIQUE(bookmaker_id, bookmaker_event_id)
);

CREATE TABLE IF NOT EXISTS bookmaker_markets (
    id                    SERIAL PRIMARY KEY,
    bookmaker_event_id    VARCHAR(100) NOT NULL,
    bookmaker_market_key  VARCHAR(200) NOT NULL,
    market_name           VARCHAR(200),
    market_type           VARCHAR(50) DEFAULT 'match_winner',
    line_id               VARCHAR(50),
    line_name             VARCHAR(200),
    is_extra_market       INTEGER DEFAULT 0,
    UNIQUE(bookmaker_event_id, bookmaker_market_key)
);

/* ── Odds outcome snapshots (time-series) ───────────────────────────────── */
CREATE TABLE IF NOT EXISTS odds_outcome_snapshots (
    id                  SERIAL,
    scrape_run_id       INTEGER REFERENCES scrape_runs(id),
    bookmaker_event_id  VARCHAR(100) NOT NULL,
    bookmaker_market_key VARCHAR(200) NOT NULL,
    outcome_key         VARCHAR(200) NOT NULL,
    scraped_at          TIMESTAMPTZ DEFAULT NOW(),
    source_url          VARCHAR(500),
    offer_url           VARCHAR(500),
    outcome_name        VARCHAR(200),
    outcome_side        VARCHAR(10),
    decimal_odds        REAL,
    raw_payload         TEXT,
    UNIQUE(scrape_run_id, outcome_key)
);
SELECT create_hypertable('odds_outcome_snapshots', 'scraped_at',
    if_not_exists => TRUE, migrate_data => TRUE);
CREATE INDEX IF NOT EXISTS idx_outcome_event ON odds_outcome_snapshots(bookmaker_event_id, scraped_at DESC);

/* ── Model registry ──────────────────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS model_artifacts (
    id                SERIAL PRIMARY KEY,
    model_name        VARCHAR(200) NOT NULL,
    model_version     VARCHAR(50) NOT NULL,
    artifact_path     VARCHAR(500),
    feature_schema_json TEXT,
    model_params_json TEXT,
    training_cutoff_at VARCHAR(50),
    metrics_json      TEXT,
    status            VARCHAR(50) DEFAULT 'registered',
    UNIQUE(model_name, model_version)
);

/* ── Rating runs / entity ratings (time-series) ──────────────────────────── */
CREATE TABLE IF NOT EXISTS rating_runs (
    id                SERIAL PRIMARY KEY,
    ratings_version   VARCHAR(100) UNIQUE NOT NULL,
    source            VARCHAR(100),
    data_cutoff_at    VARCHAR(50),
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    status            VARCHAR(50) DEFAULT 'running',
    systems_json      TEXT,
    matches_processed INTEGER DEFAULT 0,
    games_processed   INTEGER DEFAULT 0,
    players_processed INTEGER DEFAULT 0,
    error             TEXT
);

CREATE TABLE IF NOT EXISTS entity_ratings (
    id                    SERIAL,
    rating_run_id         INTEGER REFERENCES rating_runs(id),
    ratings_version       VARCHAR(100) NOT NULL,
    snapshot_at           TIMESTAMPTZ DEFAULT NOW(),
    entity_type           VARCHAR(20) NOT NULL,
    entity_name           VARCHAR(200) NOT NULL,
    normalized_entity_name VARCHAR(200) NOT NULL,
    team_name             VARCHAR(200),
    role                  VARCHAR(20),
    rating_system         VARCHAR(20) NOT NULL,
    rating_value          REAL,
    rd                    REAL,
    sigma                 REAL,
    games_played          INTEGER DEFAULT 0,
    last_match_at         VARCHAR(50),
    state_json            TEXT,
    UNIQUE(ratings_version, entity_type, normalized_entity_name, rating_system)
);
SELECT create_hypertable('entity_ratings', 'snapshot_at',
    if_not_exists => TRUE, migrate_data => TRUE);

/* ── Team rolling features ───────────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS team_rolling_features (
    id                    SERIAL PRIMARY KEY,
    feature_version       VARCHAR(100) NOT NULL,
    team_name             VARCHAR(200) NOT NULL,
    normalized_team_name  VARCHAR(200) NOT NULL,
    window_size           INTEGER DEFAULT 20,
    data_cutoff_at        VARCHAR(50),
    matches_count         INTEGER DEFAULT 0,
    games_count           INTEGER DEFAULT 0,
    win_rate              REAL,
    avg_kills             REAL,
    avg_deaths            REAL,
    avg_gd15              REAL,
    avg_dpm               REAL,
    avg_vspm              REAL,
    avg_gold              REAL,
    avg_towers            REAL,
    avg_dragons           REAL,
    avg_nashors           REAL,
    avg_game_duration     REAL,
    features_json         TEXT,
    UNIQUE(feature_version, normalized_team_name, window_size)
);

/* ── Upcoming match features ─────────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS upcoming_match_features (
    id                    SERIAL PRIMARY KEY,
    canonical_match_id    INTEGER NOT NULL REFERENCES canonical_matches(id),
    feature_version       VARCHAR(100) NOT NULL,
    ratings_version       VARCHAR(100) NOT NULL,
    data_cutoff_at        VARCHAR(50),
    team_a_golgg_name     VARCHAR(200),
    team_b_golgg_name     VARCHAR(200),
    feature_status        VARCHAR(50) DEFAULT 'pending',
    missing_reason        TEXT,
    features_json         TEXT,
    UNIQUE(canonical_match_id, feature_version, ratings_version)
);

/* ── Canonical predictions ───────────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS canonical_predictions (
    id                    SERIAL PRIMARY KEY,
    canonical_match_id    INTEGER NOT NULL REFERENCES canonical_matches(id),
    model_artifact_id     INTEGER REFERENCES model_artifacts(id),
    model_name            VARCHAR(200) NOT NULL,
    model_version         VARCHAR(50) NOT NULL,
    predicted_at          TIMESTAMPTZ DEFAULT NOW(),
    prob_a                REAL,
    prob_b                REAL,
    features_version      VARCHAR(100),
    ratings_version       VARCHAR(100),
    data_cutoff_at        VARCHAR(50),
    prediction_status     VARCHAR(50) DEFAULT 'active',
    diagnostics_json      TEXT
);

/* ── Model EV signals ────────────────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS model_ev_signals (
    id                    SERIAL PRIMARY KEY,
    canonical_match_id    INTEGER NOT NULL REFERENCES canonical_matches(id),
    canonical_prediction_id INTEGER REFERENCES canonical_predictions(id),
    odds_snapshot_id      INTEGER,
    bookmaker_id          INTEGER NOT NULL REFERENCES bookmakers(id),
    side                  VARCHAR(5) NOT NULL,
    odds                  REAL,
    model_prob            REAL,
    market_prob           REAL,
    ev                    REAL,
    tax_rate              REAL DEFAULT 0.12,
    stake_suggestion      REAL,
    status                VARCHAR(50) DEFAULT 'new'
);

/* ── Automation ──────────────────────────────────────────────────────────── */
CREATE TABLE IF NOT EXISTS automation_runs (
    id                SERIAL PRIMARY KEY,
    run_type          VARCHAR(50) NOT NULL,
    trigger_source    VARCHAR(50) DEFAULT 'scheduler',
    status            VARCHAR(50) DEFAULT 'running',
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    interval_seconds  INTEGER,
    next_run_at       TIMESTAMPTZ,
    host              VARCHAR(200),
    pid               INTEGER,
    commands_total    INTEGER DEFAULT 0,
    commands_failed   INTEGER DEFAULT 0,
    error             TEXT
);

CREATE TABLE IF NOT EXISTS automation_commands (
    id          SERIAL PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES automation_runs(id),
    command     VARCHAR(500) NOT NULL,
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    status      VARCHAR(50) DEFAULT 'pending',
    exit_code   INTEGER,
    output      TEXT,
    error       TEXT
);

/* ── Indexes ─────────────────────────────────────────────────────────────── */
CREATE INDEX IF NOT EXISTS idx_golgg_matches_date ON golgg_matches(date);
CREATE INDEX IF NOT EXISTS idx_golgg_matches_teams ON golgg_matches(team1_name, team2_name);
CREATE INDEX IF NOT EXISTS idx_golgg_matches_tournament ON golgg_matches(tournament_name);
CREATE INDEX IF NOT EXISTS idx_bets_account ON bets(bookmaker_account_id, status, placed_at DESC);
CREATE INDEX IF NOT EXISTS idx_canonical_start ON canonical_matches(start_time_normalized);
CREATE INDEX IF NOT EXISTS idx_canonical_pred_match ON canonical_predictions(canonical_match_id, predicted_at DESC);
CREATE INDEX IF NOT EXISTS idx_ev_signal_match ON model_ev_signals(canonical_match_id, status, ev DESC);
CREATE INDEX IF NOT EXISTS idx_rating_version ON entity_ratings(ratings_version, entity_type, rating_system);
CREATE INDEX IF NOT EXISTS idx_team_rolling_version ON team_rolling_features(feature_version, normalized_team_name);
CREATE INDEX IF NOT EXISTS idx_upcoming_features_match ON upcoming_match_features(canonical_match_id);
CREATE INDEX IF NOT EXISTS idx_scrape_bookmaker ON scrape_runs(bookmaker_id, started_at DESC);
