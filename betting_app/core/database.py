"""SQLite ↔ PostgreSQL unified database layer.

When ``DATABASE_URL`` is set → PostgreSQL via SQLAlchemy.
Otherwise → local SQLite fallback (raw ``sqlite3``).

All existing code using ``betting_app.core.database`` continues to work:
- ``connect()`` returns an object with ``.execute(sql, params)``
- ``query_df(sql, params)`` returns a pandas DataFrame
- ``init_db()`` creates the schema
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pandas as pd


def _use_pg() -> bool:
    return bool(os.getenv("DATABASE_URL", ""))


def _pg_url() -> str:
    return os.getenv("DATABASE_URL", "")


# ── Public API (same interface as the old sqlite3 module) ──────────────────


class PGWrapper:
    """Wraps a SQLAlchemy :class:`Session` so it quacks like a ``sqlite3.Connection``.

    - ``.execute(sql, params)`` → accepts both ``?`` positional and ``:named``
    - ``dict``-like row access works via SQLAlchemy Row mappings.
    """

    def __init__(self, url: str) -> None:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session

        self._engine = create_engine(url, pool_pre_ping=True)
        self._session = Session(self._engine)
        self._text = text
        self.closed = False

    def execute(self, sql: str, params: Any = None):
        """Execute SQL, auto-converting SQLite syntax to PG syntax."""

        if params is not None and not isinstance(params, dict):
            pos = sql.count("?")
            params_list = list(params) if isinstance(params, (list, tuple)) else [params]
            for i in range(pos):
                old = "?"
                new = f":p{i}"
                sql = sql.replace(old, new, 1)
            params = {f"p{i}": v for i, v in enumerate(params_list)}

        # Convert SQLite INSERT OR IGNORE → PG ON CONFLICT DO NOTHING
        import re
        sql = re.sub(
            r"INSERT\s+OR\s+IGNORE\s+INTO\s+(\w+)\s*\((.+?)\)\s*VALUES\s*\((.+?)\)",
            r"INSERT INTO \1 (\2) VALUES (\3) ON CONFLICT DO NOTHING",
            sql,
            flags=re.DOTALL,
        )

        # Convert SQLite scalar MAX(a, b) → PG GREATEST(a, b)
        sql = re.sub(
            r"MAX\(([^)]+),\s*([^)]+)\)",
            r"GREATEST(\1, \2)",
            sql,
        )

        result = self._session.execute(self._text(sql), params or {})
        return _PGResult(result, wrapper=self)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def close(self) -> None:
        if not self.closed:
            self._session.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class _PGResult:
    """Wraps ``CursorResult`` so that ``.fetchone()`` / ``.fetchall()``
    return dict-like rows. Also exposes ``.lastrowid`` via ``SELECT LASTVAL()``."""

    def __init__(self, result: Any, wrapper: Any = None) -> None:
        self._result = result
        self._wrapper = wrapper
        self._rows: list[dict[str, Any]] | None = None
        self._lastrowid: int | None = None
        self.description: Any = None

    @property
    def lastrowid(self) -> int | None:
        if self._lastrowid is None and self._wrapper is not None:
            try:
                row = self._wrapper._session.execute(self._wrapper._text("SELECT LASTVAL()")).fetchone()
                self._lastrowid = int(row[0]) if row and row[0] is not None else None
            except Exception:
                self._lastrowid = None
            # For hypertables LASTVAL() may be None → try MAX(id)
            if self._lastrowid is None:
                try:
                    row = self._wrapper._session.execute(
                        self._wrapper._text("SELECT MAX(id) FROM odds_snapshots")
                    ).fetchone()
                    self._lastrowid = int(row[0]) if row else None
                except Exception:
                    self._lastrowid = None
        return self._lastrowid

    def fetchone(self) -> dict[str, Any] | None:
        if self._rows is None:
            self._rows = self._all_rows()
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        if self._rows is None:
            self._rows = self._all_rows()
        return self._rows

    def _all_rows(self) -> list[dict[str, Any]]:
        import datetime
        rows = self._result.fetchall()
        if not rows:
            return []
        keys = rows[0]._fields if hasattr(rows[0], "_fields") else list(rows[0].keys())
        out = []
        for row in rows:
            d = dict(row._mapping) if hasattr(row, "_mapping") else dict(zip(keys, row))
            # Convert datetimes -> ISO strings
            for k, v in d.items():
                if isinstance(v, datetime.datetime):
                    d[k] = v.isoformat()
            out.append(d)
        return out


# ── Backend selection ──────────────────────────────────────────────────────


def connect(db_path: str | Path | None = None):
    """Return a connection-like object (raw ``sqlite3.Connection`` or ``PGWrapper``)."""
    if _use_pg():
        return PGWrapper(_pg_url())

    # Original SQLite path
    from betting_app.core.config import load_config
    path = Path(db_path) if db_path else load_config().db_path
    path.parent.mkdir(parents=True, exist_ok=True)

    import sqlite3
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path | None = None) -> Path | None:
    """Create or migrate the database schema."""
    if _use_pg():
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session
        from betting_app.models.base import Base
        engine = create_engine(_pg_url(), pool_pre_ping=True)
        Base.metadata.create_all(engine)
        # Seed bookmakers
        bookmakers = [
            ("manual", None), ("sts", "https://www.sts.pl/"),
            ("betclic", "https://www.betclic.pl/"), ("superbet", "https://superbet.pl/"),
            ("efortuna", "https://www.efortuna.pl/"), ("fortuna", "https://www.efortuna.pl/"),
            ("betfan", "https://betfan.pl/"), ("totalbet", "https://totalbet.pl/"),
            ("lebull", "https://www.lebull.pl/"),
        ]
        with Session(engine) as session:
            for name, url in bookmakers:
                session.execute(
                    text("INSERT INTO bookmakers (name, base_url) VALUES (:name, :url) ON CONFLICT (name) DO NOTHING"),
                    {"name": name, "url": url},
                )
            session.commit()
        engine.dispose()
        return None

    # SQLite path
    from betting_app.core.config import load_config
    path = Path(db_path) if db_path else load_config().db_path
    SCHEMA_PATH = Path(__file__).with_name("schema.sql")
    import sqlite3
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _apply_lightweight_migrations(conn)
        conn.commit()
    return path


def get_db_path(db_path: str | Path | None = None) -> Path:
    """Return the SQLite path (for informational purposes)."""
    from betting_app.core.config import load_config
    return Path(db_path) if db_path else load_config().db_path


@contextmanager
def transaction(db_path: str | Path | None = None) -> Iterator[Any]:
    """Context manager: commit on success, rollback on error (works with both backends)."""
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
        if isinstance(connection, PGWrapper):
            import datetime
            rows = connection.execute(sql, params).fetchall()
            return pd.DataFrame(rows) if rows else pd.DataFrame()
        else:
            return pd.read_sql_query(sql, connection, params=params or {})


# ── Lightweight SQLite migrations (kept for backward compatibility) ────────


def _apply_lightweight_migrations(connection) -> None:
    """Run additive column migrations (SQLite only)."""
    def add_column_if_missing(conn, table, column, definition):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    add_column_if_missing(connection, "upcoming_matches", "offer_url", "TEXT")
    add_column_if_missing(connection, "odds_snapshots", "canonical_match_id", "INTEGER")
    add_column_if_missing(connection, "bets", "tax_rate", "REAL DEFAULT 0.12")
    add_column_if_missing(connection, "bets", "source", "TEXT NOT NULL DEFAULT 'manual'")
