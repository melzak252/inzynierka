"""Persistence helpers for unattended scheduler/job status."""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime

import pandas as pd

from betting_app.core.database import connect, query_df


def utc_now_iso() -> str:
    """Return second-precision UTC timestamp."""

    return datetime.now(UTC).replace(microsecond=0).isoformat()


def start_run(
    run_type: str,
    *,
    trigger_source: str = "scheduler",
    interval_seconds: int | None = None,
) -> int:
    """Create an automation run row and return its id."""

    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO automation_runs(
                run_type, trigger_source, status, started_at,
                interval_seconds, host, pid
            )
            VALUES (?, ?, 'running', ?, ?, ?, ?)
            """,
            (run_type, trigger_source, utc_now_iso(), interval_seconds, socket.gethostname(), os.getpid()),
        )
        connection.commit()
        return int(cursor.lastrowid)


def finish_run(
    run_id: int | None,
    *,
    status: str,
    error: str | None = None,
    next_run_at: str | None = None,
) -> None:
    """Mark an automation run as completed/failed."""

    if run_id is None:
        return
    with connect() as connection:
        connection.execute(
            """
            UPDATE automation_runs
            SET status = ?, finished_at = ?, error = ?, next_run_at = ?
            WHERE id = ?
            """,
            (status, utc_now_iso(), error, next_run_at, run_id),
        )
        connection.commit()


def start_command(run_id: int | None, command: list[str]) -> int | None:
    """Create a child command row for a scheduler command."""

    if run_id is None:
        return None
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO automation_commands(run_id, command, status, started_at)
            VALUES (?, ?, 'running', ?)
            """,
            (run_id, " ".join(command), utc_now_iso()),
        )
        connection.execute(
            "UPDATE automation_runs SET commands_total = commands_total + 1 WHERE id = ?",
            (run_id,),
        )
        connection.commit()
        return int(cursor.lastrowid)


def finish_command(command_id: int | None, *, returncode: int) -> None:
    """Mark a scheduler command as completed/failed."""

    if command_id is None:
        return
    status = "completed" if returncode == 0 else "failed"
    with connect() as connection:
        row = connection.execute(
            "SELECT run_id, started_at FROM automation_commands WHERE id = ?",
            (command_id,),
        ).fetchone()
        finished_at = utc_now_iso()
        duration = None
        if row and row["started_at"]:
            try:
                started = datetime.fromisoformat(str(row["started_at"]))
                finished = datetime.fromisoformat(finished_at)
                duration = max((finished - started).total_seconds(), 0.0)
            except ValueError:
                duration = None
        connection.execute(
            """
            UPDATE automation_commands
            SET status = ?, returncode = ?, finished_at = ?, duration_seconds = ?
            WHERE id = ?
            """,
            (status, returncode, finished_at, duration, command_id),
        )
        if row and returncode != 0:
            connection.execute(
                "UPDATE automation_runs SET commands_failed = commands_failed + 1 WHERE id = ?",
                (row["run_id"],),
            )
        connection.commit()


def latest_runs(limit: int = 20) -> pd.DataFrame:
    """Return recent automation runs."""

    return query_df(
        """
        SELECT id, run_type, trigger_source, status, started_at, finished_at,
               interval_seconds, next_run_at, commands_total, commands_failed,
               host, pid, error
        FROM automation_runs
        ORDER BY started_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )


def latest_commands(limit: int = 50, run_id: int | None = None) -> pd.DataFrame:
    """Return recent automation commands, optionally for one run."""

    if run_id is not None:
        return query_df(
            """
            SELECT id, run_id, command, status, returncode, started_at,
                   finished_at, duration_seconds
            FROM automation_commands
            WHERE run_id = ?
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (run_id, limit),
        )
    return query_df(
        """
        SELECT id, run_id, command, status, returncode, started_at,
               finished_at, duration_seconds
        FROM automation_commands
        ORDER BY started_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )


def latest_scrape_status() -> pd.DataFrame:
    """Return latest scrape status per bookmaker."""

    return query_df(
        """
        WITH ranked AS (
            SELECT b.name AS bookmaker, sr.status, sr.started_at, sr.finished_at,
                   sr.items_seen, sr.items_inserted, sr.error,
                   ROW_NUMBER() OVER (PARTITION BY sr.bookmaker_id ORDER BY sr.started_at DESC, sr.id DESC) AS rn
            FROM scrape_runs sr
            JOIN bookmakers b ON b.id = sr.bookmaker_id
        )
        SELECT bookmaker, status, started_at, finished_at, items_seen, items_inserted, error
        FROM ranked
        WHERE rn = 1
        ORDER BY bookmaker
        """
    )


def system_counts() -> pd.DataFrame:
    """Return operational row counts for the status dashboard."""

    return query_df(
        """
        SELECT 'canonical_matches' AS table_name, COUNT(*) AS rows FROM canonical_matches
        UNION ALL SELECT 'odds_snapshots', COUNT(*) FROM odds_snapshots
        UNION ALL SELECT 'scrape_runs', COUNT(*) FROM scrape_runs
        UNION ALL SELECT 'golgg_matches', COUNT(*) FROM golgg_matches
        UNION ALL SELECT 'entity_ratings', COUNT(*) FROM entity_ratings
        UNION ALL SELECT 'team_rolling_features', COUNT(*) FROM team_rolling_features
        UNION ALL SELECT 'upcoming_match_features', COUNT(*) FROM upcoming_match_features
        UNION ALL SELECT 'canonical_predictions', COUNT(*) FROM canonical_predictions
        UNION ALL SELECT 'model_ev_signals', COUNT(*) FROM model_ev_signals
        UNION ALL SELECT 'automation_runs', COUNT(*) FROM automation_runs
        """
    )
