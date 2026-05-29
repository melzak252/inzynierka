CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Future hypertables after Postgres migration.  They are commented out because
-- current MVP still creates SQLite tables; enable after Alembic/Postgres schema
-- lands.
-- SELECT create_hypertable('odds_outcome_snapshots', 'scraped_at', if_not_exists => TRUE);
-- SELECT create_hypertable('odds_snapshots', 'scraped_at', if_not_exists => TRUE);
-- SELECT create_hypertable('bookmaker_wallet_transactions', 'transaction_time', if_not_exists => TRUE);
