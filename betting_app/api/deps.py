"""FastAPI dependencies — SQLAlchemy session, query helpers."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from betting_app.core.db import get_session, query_df as _query_df, query_one as _query_one


def get_db() -> Generator[Any, None, None]:
    """Yield an SQLAlchemy session, close on teardown."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def query_df(db: Any, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute raw SQL with named parameters, return list of dicts (datetimes as strings)."""
    rows = _query_df(db, sql, params or {})
    # Convert PG datetimes to ISO strings
    from datetime import datetime as _dt
    for row in rows:
        for k, v in row.items():
            if isinstance(v, _dt):
                row[k] = v.isoformat()
    return rows


def query_one(db: Any, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Execute raw SQL, return first row as dict or None."""
    return _query_one(db, sql, params or {})
