"""FastAPI dependencies: database connection, shared helpers."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import sqlite3

from betting_app.core.database import get_db_path


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Yield a read-write SQLite connection.

    FastAPI manages the context: opens before the handler, closes after.
    """
    path = get_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def query_df(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Return query result as a list of dicts (lightweight, no pandas dependency)."""
    cur = conn.execute(sql, params)
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def query_one(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = query_df(conn, sql, params)
    return rows[0] if rows else None
