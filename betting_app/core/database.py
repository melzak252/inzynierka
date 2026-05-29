"""SQLite database utilities for the betting app."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd

from betting_app.core.config import load_config


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def get_db_path(db_path: str | Path | None = None) -> Path:
    """Resolve the database path."""

    return Path(db_path) if db_path else load_config().db_path


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with row dictionaries and foreign keys enabled."""

    path = get_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(db_path: str | Path | None = None) -> Path:
    """Create or migrate the local SQLite database using the bundled schema."""

    path = get_db_path(db_path)
    with connect(path) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _apply_lightweight_migrations(connection)
        connection.commit()
    return path


def _apply_lightweight_migrations(connection: sqlite3.Connection) -> None:
    """Apply additive SQLite migrations for already-created local MVP DBs."""

    add_column_if_missing(connection, "upcoming_matches", "offer_url", "TEXT")
    add_column_if_missing(connection, "upcoming_matches", "canonical_match_id", "INTEGER")
    add_column_if_missing(connection, "odds_snapshots", "offer_url", "TEXT")
    add_column_if_missing(connection, "odds_snapshots", "canonical_match_id", "INTEGER")
    add_column_if_missing(connection, "bookmaker_events", "offer_url", "TEXT")
    add_column_if_missing(connection, "bookmaker_events", "canonical_match_id", "INTEGER")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_odds_canonical_match ON odds_snapshots(canonical_match_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_upcoming_canonical_match ON upcoming_matches(canonical_match_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_canonical_match_start ON canonical_matches(start_time_normalized)")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_bookmaker_events_canonical_match ON bookmaker_events(canonical_match_id)"
    )
    add_column_if_missing(connection, "odds_outcome_snapshots", "offer_url", "TEXT")
    add_column_if_missing(connection, "team_rolling_features", "avg_gd15", "REAL")
    add_column_if_missing(connection, "team_rolling_features", "avg_dpm", "REAL")
    add_column_if_missing(connection, "team_rolling_features", "avg_vspm", "REAL")
    add_column_if_missing(connection, "bets", "model_ev_signal_id", "INTEGER")
    add_column_if_missing(connection, "bets", "bookmaker_account_id", "INTEGER")
    add_column_if_missing(connection, "bets", "canonical_match_id", "INTEGER")
    add_column_if_missing(connection, "bets", "team_a", "TEXT")
    add_column_if_missing(connection, "bets", "team_b", "TEXT")
    add_column_if_missing(connection, "bets", "league", "TEXT")
    add_column_if_missing(connection, "bets", "match_start_time", "TEXT")
    add_column_if_missing(connection, "bets", "model_prob", "REAL")
    add_column_if_missing(connection, "bets", "ev", "REAL")
    add_column_if_missing(connection, "bets", "tax_rate", "REAL DEFAULT 0.12")
    add_column_if_missing(connection, "bets", "source", "TEXT NOT NULL DEFAULT 'manual'")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_bets_bookmaker_account ON bets(bookmaker_account_id, status, placed_at)")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_wallet_transactions_account ON bookmaker_wallet_transactions(bookmaker_account_id, transaction_time)"
    )


def add_column_if_missing(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    """Add a column only if it is absent from an existing SQLite table."""

    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


@contextmanager
def transaction(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager that commits on success and rolls back on failure."""

    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def query_df(sql: str, params: tuple | dict | None = None, db_path: str | Path | None = None) -> pd.DataFrame:
    """Read a SQL query into a DataFrame."""

    with connect(db_path) as connection:
        return pd.read_sql_query(sql, connection, params=params or {})
