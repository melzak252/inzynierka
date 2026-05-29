"""Services for odds snapshots and upcoming matches."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from betting_app.core.database import query_df, transaction
from betting_app.core.matching import normalize_team_name
from betting_app.services.canonical_match_service import resolve_canonical_match


def utc_now_iso() -> str:
    """Return current UTC timestamp as ISO string."""

    return datetime.now(UTC).replace(microsecond=0).isoformat()


def get_or_create_bookmaker(name: str, base_url: str | None = None) -> int:
    """Return bookmaker ID, creating it if needed."""

    with transaction() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO bookmakers(name, base_url) VALUES (?, ?)",
            (name, base_url),
        )
        row = connection.execute("SELECT id FROM bookmakers WHERE name = ?", (name,)).fetchone()
        return int(row["id"])


def make_match_key(bookmaker: str, raw_team_a: str, raw_team_b: str, start_time: str | None) -> str:
    """Build a stable bookmaker match key from raw data."""

    return "|".join(
        [bookmaker, normalize_team_name(raw_team_a), normalize_team_name(raw_team_b), start_time or "unknown"]
    )


def upsert_upcoming_match(
    bookmaker: str,
    raw_team_a: str,
    raw_team_b: str,
    match_start_time: str | None = None,
    league: str | None = None,
    offer_url: str | None = None,
    canonical_team_a: str | None = None,
    canonical_team_b: str | None = None,
) -> int:
    """Create or update an upcoming match and return its ID."""

    key = make_match_key(bookmaker, raw_team_a, raw_team_b, match_start_time)
    canonical_match_id = resolve_canonical_match(
        raw_team_a=canonical_team_a or raw_team_a,
        raw_team_b=canonical_team_b or raw_team_b,
        match_start_time=match_start_time,
        league=league,
    )
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO upcoming_matches(
                canonical_match_id, canonical_team_a, canonical_team_b, raw_team_a, raw_team_b,
                match_start_time, league, offer_url, bookmaker_match_key, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(bookmaker_match_key) DO UPDATE SET
                canonical_match_id = excluded.canonical_match_id,
                canonical_team_a = excluded.canonical_team_a,
                canonical_team_b = excluded.canonical_team_b,
                raw_team_a = excluded.raw_team_a,
                raw_team_b = excluded.raw_team_b,
                match_start_time = excluded.match_start_time,
                league = excluded.league,
                offer_url = COALESCE(excluded.offer_url, upcoming_matches.offer_url),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                canonical_match_id,
                canonical_team_a,
                canonical_team_b,
                raw_team_a,
                raw_team_b,
                match_start_time,
                league,
                offer_url,
                key,
            ),
        )
        row = connection.execute("SELECT id FROM upcoming_matches WHERE bookmaker_match_key = ?", (key,)).fetchone()
        return int(row["id"])


def insert_odds_snapshot(snapshot: dict[str, Any]) -> int:
    """Insert one normalized odds snapshot."""

    bookmaker_name = str(snapshot.get("bookmaker", "manual"))
    bookmaker_id = get_or_create_bookmaker(bookmaker_name, snapshot.get("base_url"))
    scraped_at = str(snapshot.get("scraped_at") or utc_now_iso())
    match_id = upsert_upcoming_match(
        bookmaker=bookmaker_name,
        raw_team_a=str(snapshot["raw_team_a"]),
        raw_team_b=str(snapshot["raw_team_b"]),
        match_start_time=snapshot.get("match_start_time"),
        league=snapshot.get("raw_league"),
        offer_url=snapshot.get("offer_url"),
        canonical_team_a=snapshot.get("mapped_team_a"),
        canonical_team_b=snapshot.get("mapped_team_b"),
    )
    canonical_match_id = get_upcoming_canonical_match_id(match_id)
    raw_payload = snapshot.get("raw_payload")
    if raw_payload is not None and not isinstance(raw_payload, str):
        raw_payload = json.dumps(raw_payload, ensure_ascii=False)

    with transaction() as connection:
        cursor = connection.execute(
            """
            INSERT INTO odds_snapshots(
                bookmaker_id, match_id, canonical_match_id, scraped_at, source_url, offer_url, raw_league,
                raw_team_a, raw_team_b, mapped_team_a, mapped_team_b,
                match_start_time, odds_a, odds_b, market_type, is_live,
                scraper_name, scraper_version, raw_payload, page_html_path, screenshot_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bookmaker_id,
                match_id,
                canonical_match_id,
                scraped_at,
                snapshot.get("source_url"),
                snapshot.get("offer_url"),
                snapshot.get("raw_league"),
                snapshot["raw_team_a"],
                snapshot["raw_team_b"],
                snapshot.get("mapped_team_a"),
                snapshot.get("mapped_team_b"),
                snapshot.get("match_start_time"),
                float(snapshot["odds_a"]),
                float(snapshot["odds_b"]),
                snapshot.get("market_type", "match_winner"),
                int(bool(snapshot.get("is_live", False))),
                snapshot.get("scraper_name"),
                snapshot.get("scraper_version"),
                raw_payload,
                str(snapshot.get("page_html_path")) if snapshot.get("page_html_path") else None,
                str(snapshot.get("screenshot_path")) if snapshot.get("screenshot_path") else None,
            ),
        )
        return int(cursor.lastrowid)


def start_scrape_run(
    bookmaker: str,
    scraper_name: str,
    scraper_version: str | None = None,
    source_url: str | None = None,
    request_url: str | None = None,
) -> int:
    """Create a scrape run audit record and return its ID."""

    bookmaker_id = get_or_create_bookmaker(bookmaker)
    with transaction() as connection:
        cursor = connection.execute(
            """
            INSERT INTO scrape_runs(
                bookmaker_id, scraper_name, scraper_version, source_url, request_url, status
            ) VALUES (?, ?, ?, ?, ?, 'running')
            """,
            (bookmaker_id, scraper_name, scraper_version, source_url, request_url),
        )
        return int(cursor.lastrowid)


def finish_scrape_run(
    scrape_run_id: int,
    *,
    status: str = "success",
    items_seen: int = 0,
    items_inserted: int = 0,
    error: str | None = None,
) -> None:
    """Mark a scrape run as finished."""

    with transaction() as connection:
        connection.execute(
            """
            UPDATE scrape_runs
            SET finished_at = CURRENT_TIMESTAMP,
                status = ?,
                items_seen = ?,
                items_inserted = ?,
                error = ?
            WHERE id = ?
            """,
            (status, items_seen, items_inserted, error, scrape_run_id),
        )


def _market_type_from_name(market_name: str) -> str:
    """Map bookmaker market labels to coarse internal market types."""

    normalized = market_name.strip().lower()
    if normalized in {"zwycięzca meczu", "mecz", "zwyciezca meczu"}:
        return "match_winner"
    if "handicap" in normalized:
        return "handicap"
    if "dokładny wynik" in normalized or "dokladny wynik" in normalized:
        return "correct_score"
    if "mapa" in normalized:
        return "map_prop"
    return "other"


def upsert_bookmaker_event(snapshot: dict[str, Any]) -> int:
    """Create/update bookmaker event and linked upcoming match."""

    bookmaker_name = str(snapshot.get("bookmaker", "manual"))
    bookmaker_id = get_or_create_bookmaker(bookmaker_name, snapshot.get("base_url"))
    match_id = upsert_upcoming_match(
        bookmaker=bookmaker_name,
        raw_team_a=str(snapshot["raw_team_a"]),
        raw_team_b=str(snapshot["raw_team_b"]),
        match_start_time=snapshot.get("match_start_time"),
        league=snapshot.get("league_name") or snapshot.get("raw_league"),
        offer_url=snapshot.get("offer_url"),
        canonical_team_a=snapshot.get("mapped_team_a"),
        canonical_team_b=snapshot.get("mapped_team_b"),
    )
    canonical_match_id = get_upcoming_canonical_match_id(match_id)
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO bookmaker_events(
                bookmaker_id, bookmaker_event_id, match_id, canonical_match_id, raw_team_a, raw_team_b,
                mapped_team_a, mapped_team_b, match_start_time, sport_id, sport_name,
                category_id, category_name, league_id, league_name, offer_url, last_seen_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(bookmaker_id, bookmaker_event_id) DO UPDATE SET
                match_id = excluded.match_id,
                canonical_match_id = excluded.canonical_match_id,
                raw_team_a = excluded.raw_team_a,
                raw_team_b = excluded.raw_team_b,
                mapped_team_a = excluded.mapped_team_a,
                mapped_team_b = excluded.mapped_team_b,
                match_start_time = excluded.match_start_time,
                sport_id = excluded.sport_id,
                sport_name = excluded.sport_name,
                category_id = excluded.category_id,
                category_name = excluded.category_name,
                league_id = excluded.league_id,
                league_name = excluded.league_name,
                offer_url = COALESCE(excluded.offer_url, bookmaker_events.offer_url),
                last_seen_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                bookmaker_id,
                str(snapshot["bookmaker_event_id"]),
                match_id,
                canonical_match_id,
                snapshot["raw_team_a"],
                snapshot["raw_team_b"],
                snapshot.get("mapped_team_a"),
                snapshot.get("mapped_team_b"),
                snapshot.get("match_start_time"),
                snapshot.get("sport_id"),
                snapshot.get("sport_name"),
                snapshot.get("category_id"),
                snapshot.get("category_name"),
                snapshot.get("league_id"),
                snapshot.get("league_name"),
                snapshot.get("offer_url"),
            ),
        )
        row = connection.execute(
            "SELECT id FROM bookmaker_events WHERE bookmaker_id = ? AND bookmaker_event_id = ?",
            (bookmaker_id, str(snapshot["bookmaker_event_id"])),
        ).fetchone()
        return int(row["id"])


def get_upcoming_canonical_match_id(match_id: int) -> int | None:
    """Return canonical match ID linked to upcoming match."""

    with transaction() as connection:
        row = connection.execute("SELECT canonical_match_id FROM upcoming_matches WHERE id = ?", (match_id,)).fetchone()
        return int(row["canonical_match_id"]) if row and row["canonical_match_id"] is not None else None


def upsert_bookmaker_market(event_id: int, snapshot: dict[str, Any]) -> int:
    """Create/update bookmaker market for an event."""

    market_name = str(snapshot.get("market_name") or snapshot.get("line_name") or "unknown")
    market_key = str(snapshot.get("market_key") or f"{snapshot.get('line_id') or 'unknown'}:{market_name}")
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO bookmaker_markets(
                bookmaker_event_id, bookmaker_market_key, market_name, market_type,
                line_id, line_name, is_extra_market, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(bookmaker_event_id, bookmaker_market_key) DO UPDATE SET
                market_name = excluded.market_name,
                market_type = excluded.market_type,
                line_id = excluded.line_id,
                line_name = excluded.line_name,
                is_extra_market = excluded.is_extra_market,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                event_id,
                market_key,
                market_name,
                snapshot.get("market_type") or _market_type_from_name(market_name),
                snapshot.get("line_id"),
                snapshot.get("line_name") or market_name,
                int(bool(snapshot.get("is_extra_market", False))),
            ),
        )
        row = connection.execute(
            "SELECT id FROM bookmaker_markets WHERE bookmaker_event_id = ? AND bookmaker_market_key = ?",
            (event_id, market_key),
        ).fetchone()
        return int(row["id"])


def insert_outcome_snapshot(snapshot: dict[str, Any]) -> int:
    """Insert one atomic outcome odds snapshot into normalized odds tables."""

    bookmaker_name = str(snapshot.get("bookmaker", "manual"))
    bookmaker_id = get_or_create_bookmaker(bookmaker_name, snapshot.get("base_url"))
    event_id = upsert_bookmaker_event(snapshot)
    market_id = upsert_bookmaker_market(event_id, snapshot)
    raw_payload = snapshot.get("raw_payload")
    if raw_payload is not None and not isinstance(raw_payload, str):
        raw_payload = json.dumps(raw_payload, ensure_ascii=False)

    with transaction() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO odds_outcome_snapshots(
                bookmaker_id, bookmaker_event_id, bookmaker_market_id, scrape_run_id,
                scraped_at, source_url, offer_url, outcome_key, outcome_name, outcome_side,
                decimal_odds, is_live, scraper_name, scraper_version, raw_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bookmaker_id,
                event_id,
                market_id,
                snapshot.get("scrape_run_id"),
                str(snapshot.get("scraped_at") or utc_now_iso()),
                snapshot.get("source_url"),
                snapshot.get("offer_url"),
                str(snapshot["outcome_key"]),
                str(snapshot["outcome_name"]),
                snapshot.get("outcome_side"),
                float(snapshot["decimal_odds"]),
                int(bool(snapshot.get("is_live", False))),
                snapshot.get("scraper_name"),
                snapshot.get("scraper_version"),
                raw_payload,
            ),
        )
        return int(cursor.lastrowid)


def insert_snapshot(snapshot: dict[str, Any]) -> int:
    """Insert either a legacy two-sided snapshot or normalized outcome snapshot."""

    if snapshot.get("snapshot_type") == "outcome" or "decimal_odds" in snapshot:
        return insert_outcome_snapshot(snapshot)
    return insert_odds_snapshot(snapshot)


def latest_outcome_odds(limit: int = 200) -> pd.DataFrame:
    """Return latest normalized outcome odds snapshots."""

    return query_df(
        """
        SELECT
            oos.*,
            b.name AS bookmaker,
            be.bookmaker_event_id,
            be.raw_team_a,
            be.raw_team_b,
            be.match_start_time,
            be.sport_name,
            be.category_name,
            be.league_name,
            be.offer_url AS event_offer_url,
            bm.market_name,
            bm.market_type,
            bm.line_id,
            bm.line_name
        FROM odds_outcome_snapshots oos
        JOIN bookmakers b ON b.id = oos.bookmaker_id
        JOIN bookmaker_events be ON be.id = oos.bookmaker_event_id
        JOIN bookmaker_markets bm ON bm.id = oos.bookmaker_market_id
        ORDER BY oos.scraped_at DESC, oos.id DESC
        LIMIT ?
        """,
        (limit,),
    )


def latest_odds(limit: int = 200) -> pd.DataFrame:
    """Return latest odds snapshots with bookmaker and match info."""

    return query_df(
        """
        SELECT os.*, b.name AS bookmaker, um.canonical_team_a, um.canonical_team_b, um.status AS match_status,
               um.offer_url AS match_offer_url
        FROM odds_snapshots os
        JOIN bookmakers b ON b.id = os.bookmaker_id
        LEFT JOIN upcoming_matches um ON um.id = os.match_id
        ORDER BY os.scraped_at DESC, os.id DESC
        LIMIT ?
        """,
        (limit,),
    )


def export_snapshots(path: str | Path) -> Path:
    """Export all odds snapshots to CSV for audit/debug."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    latest_odds(limit=1_000_000).to_csv(output, index=False)
    return output
