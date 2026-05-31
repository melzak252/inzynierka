"""SQLAlchemy-based database layer supporting both SQLite (dev) and PostgreSQL (prod).

Usage:

    from betting_app.core.db import get_session, query_df, init_db

    with get_session() as session:
        rows = query_df(session, "SELECT * FROM matches WHERE id=:id", {"id": 1})

For FastAPI:

    from betting_app.core.db import get_async_db

    @router.get("/matches")
    async def list_matches(db=Depends(get_async_db)):
        rows = query_df(db, "SELECT ...", {...})
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import URL, create_engine, text, pool
from sqlalchemy.orm import Session, sessionmaker

from betting_app.core.config import load_config

_DATABASE_URL: str | None = None
_sync_engine = None
_SyncSession: sessionmaker | None = None


def database_url() -> str:
    """Return the active database URL (PostgreSQL via env or SQLite fallback)."""
    global _DATABASE_URL
    if _DATABASE_URL is not None:
        return _DATABASE_URL

    url = os.getenv("DATABASE_URL", "")
    if url:
        _DATABASE_URL = url
        return url

    # SQLite fallback
    db_path = load_config().db_path
    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    _DATABASE_URL = f"sqlite:///{path}"
    return _DATABASE_URL


def is_pg() -> bool:
    return database_url().startswith("postgresql")


def is_sqlite() -> bool:
    return not is_pg()


def get_db_path(db_path: str | Path | None = None) -> Path:
    """Return the SQLite path (for informational purposes / migrations)."""
    if db_path:
        return Path(db_path)
    return Path(load_config().db_path)


def _get_engine():
    global _sync_engine
    if _sync_engine is None:
        url = database_url()
        if is_sqlite():
            _sync_engine = create_engine(
                url,
                connect_args={"check_same_thread": False},
                poolclass=pool.NullPool,
            )
            # Optimise for test isolation: avoid WAL/journal locks
            with _sync_engine.connect() as c:
                c.execute(text("PRAGMA journal_mode=MEMORY"))
                c.execute(text("PRAGMA synchronous=OFF"))
        else:
            _sync_engine = create_engine(url, pool_pre_ping=True)
    return _sync_engine


def get_session() -> Session:
    """Return a synchronous SQLAlchemy session (for scripts / CLI)."""
    global _SyncSession
    if _SyncSession is None:
        _SyncSession = sessionmaker(bind=_get_engine())
    return _SyncSession()


def init_db() -> Path | None:
    """Create all tables from SQLAlchemy models and seed static data.
    
    Returns the database path for SQLite, None for PostgreSQL (backward-compatible).
    """
    from betting_app.models.base import Base
    Base.metadata.create_all(_get_engine())

    # Seed bookmakers (idempotent)
    _seed_bookmakers()
    
    # Return path for SQLite, None for PostgreSQL
    return get_db_path() if is_sqlite() else None


def _seed_bookmakers() -> None:
    """Insert default bookmakers if they don't exist yet."""
    from sqlalchemy import text
    bookmakers = [
        ("manual", None),
        ("sts", "https://www.sts.pl/"),
        ("betclic", "https://www.betclic.pl/"),
        ("superbet", "https://superbet.pl/"),
        ("efortuna", "https://www.efortuna.pl/"),
        ("fortuna", "https://www.efortuna.pl/"),
        ("betfan", "https://betfan.pl/"),
        ("totalbet", "https://totalbet.pl/"),
        ("lebull", "https://www.lebull.pl/"),
    ]
    with get_session() as session:
        for name, url in bookmakers:
            session.execute(
                text("INSERT OR IGNORE INTO bookmakers (name, base_url) VALUES (:name, :url)"),
                {"name": name, "url": url},
            )
        session.commit()


def dispose_engine() -> None:
    """Release engine resources (call at process exit if needed)."""
    global _sync_engine, _SyncSession
    if _sync_engine:
        _sync_engine.dispose()
    _sync_engine = None
    _SyncSession = None


# ── Query helpers ────────────────────────────────────────────────────────────


def query_df(
    sql: str,
    params: tuple | dict | None = None,
    db_path: str | Path | None = None,
    session: Session | None = None,
) -> "pd.DataFrame":
    """Execute raw SQL and return a pandas DataFrame.
    
    Backward-compatible with old database.query_df() signature.
    If session is provided, uses it; otherwise creates a new one.
    """
    import pandas as pd
    
    own_session = session is None
    sess = session or get_session()
    try:
        # Convert positional ? params to named :p0, :p1, ...
        if params is not None and not isinstance(params, dict):
            pos = sql.count("?")
            params_list = list(params) if isinstance(params, (list, tuple)) else [params]
            for i in range(pos):
                sql = sql.replace("?", f":p{i}", 1)
            params = {f"p{i}": v for i, v in enumerate(params_list)}
        
        result = sess.execute(text(sql), params or {})
        columns = result.keys()
        rows = result.fetchall()
        return pd.DataFrame([dict(zip(columns, row)) for row in rows]) if rows else pd.DataFrame()
    finally:
        if own_session:
            sess.close()


def query_one(
    sql: str,
    params: tuple | dict | None = None,
    session: Session | None = None,
) -> dict[str, Any] | None:
    """Execute raw SQL, return first row as dict or None."""
    own_session = session is None
    sess = session or get_session()
    try:
        # Convert positional ? params to named :p0, :p1, ...
        if params is not None and not isinstance(params, dict):
            pos = sql.count("?")
            params_list = list(params) if isinstance(params, (list, tuple)) else [params]
            for i in range(pos):
                sql = sql.replace("?", f":p{i}", 1)
            params = {f"p{i}": v for i, v in enumerate(params_list)}
        
        result = sess.execute(text(sql), params or {})
        columns = result.keys()
        row = result.fetchone()
        return dict(zip(columns, row)) if row else None
    finally:
        if own_session:
            sess.close()


# ── Backward-compatible connection API ───────────────────────────────────────


class _ConnectionWrapper:
    """Wraps SQLAlchemy Session to quack like sqlite3.Connection.
    
    Supports:
    - .execute(sql, params) with ? positional params
    - .commit() / .rollback()
    - context manager (with statement)
    """
    
    def __init__(self, session: Session) -> None:
        self._session = session
        self.closed = False
    
    def execute(self, sql: str, params: tuple | list | dict | None = None):
        """Execute SQL, converting ? params to :named params."""
        if params is not None and not isinstance(params, dict):
            pos = sql.count("?")
            params_list = list(params) if isinstance(params, (list, tuple)) else [params]
            for i in range(pos):
                sql = sql.replace("?", f":p{i}", 1)
            params = {f"p{i}": v for i, v in enumerate(params_list)}
        
        result = self._session.execute(text(sql), params or {})
        return _ResultWrapper(result, self._session)
    
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


class _ResultWrapper:
    """Wraps SQLAlchemy CursorResult to provide dict-like rows."""
    
    def __init__(self, result: Any, session: Session) -> None:
        self._result = result
        self._session = session
        self._rows: list[dict[str, Any]] | None = None
        self.description = None
    
    @property
    def lastrowid(self) -> int | None:
        """Get last inserted row ID (PostgreSQL only)."""
        if is_pg():
            try:
                row = self._session.execute(text("SELECT LASTVAL()")).fetchone()
                return int(row[0]) if row and row[0] is not None else None
            except Exception:
                return None
        return None
    
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
        columns = rows[0]._fields if hasattr(rows[0], "_fields") else list(rows[0].keys())
        out = []
        for row in rows:
            d = dict(row._mapping) if hasattr(row, "_mapping") else dict(zip(columns, row))
            # Convert datetimes to ISO strings for consistency
            for k, v in d.items():
                if isinstance(v, datetime.datetime):
                    d[k] = v.isoformat()
            out.append(d)
        return out


def connect(db_path: str | Path | None = None) -> _ConnectionWrapper:
    """Return a connection-like object (backward-compatible with database.connect()).
    
    Usage:
        with connect() as conn:
            conn.execute("INSERT INTO ...", (val1, val2))
            conn.commit()
    """
    return _ConnectionWrapper(get_session())


from contextlib import contextmanager
from typing import Iterator


@contextmanager
def transaction(db_path: str | Path | None = None) -> Iterator[_ConnectionWrapper]:
    """Context manager: commit on success, rollback on error.
    
    Usage:
        with transaction() as conn:
            conn.execute("INSERT INTO ...", (val1, val2))
            # auto-commit on success, auto-rollback on exception
    """
    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


# ── FastAPI dependency ───────────────────────────────────────────────────────


from collections.abc import Generator as GenType


def get_db() -> GenType[Session, None, None]:
    """FastAPI dependency — yields an SQLAlchemy session, closes on teardown."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


# Re-export for convenience
from sqlalchemy import text as sql_text  # noqa: E402, F401
