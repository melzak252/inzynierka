"""SQLAlchemy DeclarativeBase and engine/session helpers.

Supports both async (PostgreSQL) and sync (SQLite fallback) backends.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# ── Backend selection ────────────────────────────────────────────────────────

DB_URL = os.getenv("DATABASE_URL") or ""
USE_ASYNC = DB_URL.startswith("postgresql+asyncpg")


def is_timescale() -> bool:
    """Are we pointing at a TimescaleDB / PostgreSQL instance?"""
    return "postgresql" in DB_URL


def is_sqlite() -> bool:
    """Are we using the local SQLite fallback?"""
    return not is_timescale()


# ── Base ─────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


# ── Sync engine (SQLite fallback) ────────────────────────────────────────────

_sync_engine = None
_SyncSession = None


def _get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        if is_timescale():
            _sync_engine = create_engine(
                DB_URL.replace("+asyncpg", "+psycopg2"),
                pool_pre_ping=True,
            )
        else:
            from betting_app.core.database import get_db_path

            _sync_engine = create_engine(
                f"sqlite:///{get_db_path()}",
                connect_args={"check_same_thread": False},
            )
    return _sync_engine


def get_sync_session():
    engine = _get_sync_engine()
    return sessionmaker(bind=engine)


# ── Async engine (PostgreSQL) ────────────────────────────────────────────────

_async_engine = None
_AsyncSession = None


def get_async_engine():
    global _async_engine
    if _async_engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine

        url = DB_URL if USE_ASYNC else "sqlite+aiosqlite://"
        _async_engine = create_async_engine(url, pool_pre_ping=True)
    return _async_engine


def get_async_session():
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(bind=get_async_engine(), expire_on_commit=False)
