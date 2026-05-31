"""Cross-bookmaker canonical match resolution."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from betting_app.core.db import query_df, transaction
from betting_app.core.matching import normalize_team_name, similarity


TEAM_ALIASES = {
    "brion": "brion",
    "hanjin brion": "brion",
    "oksavingsbank brion": "brion",
    "ok savingsbank brion": "brion",
    "dn freecs": "dn soopers",
    "dn soopers": "dn soopers",
    "dplus kia": "dplus kia",
    "dk": "dplus kia",
    "giantx": "giantx",
    "giant x": "giantx",
    "top esports": "top esports",
    "top": "top esports",
    "tes": "top esports",
    "edward": "edward gaming",
    "edward gaming": "edward gaming",
    "anyones legend": "anyones legend",
    "anyone s legend": "anyones legend",
    "anyone legend": "anyones legend",
    "fearx": "bnk fearx",
    "bnk fearx": "bnk fearx",
    "karmine corp blue": "karmine corp blue",
    "kc blue": "karmine corp blue",
    "geng": "gen g",
    "gen g": "gen g",
    "gen.g": "gen g",
}


def canonical_team_key(name: str) -> str:
    """Normalize a raw team name into a cross-bookmaker key."""

    normalized = normalize_team_name(name)
    compact = normalized.replace(" ", "")
    if normalized in TEAM_ALIASES:
        return TEAM_ALIASES[normalized]
    if compact in TEAM_ALIASES:
        return TEAM_ALIASES[compact]
    return normalized


def resolve_canonical_match(
    *,
    raw_team_a: str,
    raw_team_b: str,
    match_start_time: str | None = None,
    league: str | None = None,
    min_confidence: float = 0.78,
) -> int:
    """Find or create a canonical match shared by all bookmakers."""

    team_a_key = canonical_team_key(raw_team_a)
    team_b_key = canonical_team_key(raw_team_b)
    start_norm = normalize_start_time(match_start_time)
    league_norm = normalize_league(league)

    with transaction() as connection:
        candidates = connection.execute(
            """
            SELECT * FROM canonical_matches
            WHERE status = 'upcoming'
            ORDER BY updated_at DESC
            LIMIT 500
            """
        ).fetchall()
        best_id: int | None = None
        best_score = 0.0
        for candidate in candidates:
            score = canonical_match_score(
                team_a_key,
                team_b_key,
                start_norm,
                league_norm,
                dict(candidate),
            )
            if score > best_score:
                best_score = score
                best_id = int(candidate["id"])
        if best_id is not None and best_score >= min_confidence:
            connection.execute(
                """
                UPDATE canonical_matches
                SET start_time_normalized = COALESCE(start_time_normalized, ?),
                    league = COALESCE(league, ?),
                    match_confidence = MAX(match_confidence, ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (start_norm, league, best_score, best_id),
            )
            return best_id

        canonical_key = build_canonical_key(team_a_key, team_b_key, start_norm, league_norm)
        connection.execute(
            """
            INSERT OR IGNORE INTO canonical_matches(
                canonical_key, team_a_name, team_b_name, normalized_team_a, normalized_team_b,
                start_time_normalized, league, match_confidence, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1.0, CURRENT_TIMESTAMP)
            """,
            (canonical_key, raw_team_a, raw_team_b, team_a_key, team_b_key, start_norm, league),
        )
        row = connection.execute("SELECT id FROM canonical_matches WHERE canonical_key = ?", (canonical_key,)).fetchone()
        return int(row["id"])


def canonical_match_score(
    team_a_key: str,
    team_b_key: str,
    start_norm: str | None,
    league_norm: str | None,
    candidate: dict[str, Any],
) -> float:
    """Score whether a raw bookmaker event belongs to a canonical match."""

    cand_a = str(candidate.get("normalized_team_a") or "")
    cand_b = str(candidate.get("normalized_team_b") or "")
    direct = (similarity(team_a_key, cand_a) + similarity(team_b_key, cand_b)) / 2
    swapped = (similarity(team_a_key, cand_b) + similarity(team_b_key, cand_a)) / 2
    team_score = max(direct, swapped)
    if team_score < 0.68:
        return team_score * 0.7

    time_score = time_match_score(start_norm, candidate.get("start_time_normalized"))
    league_score = league_match_score(league_norm, candidate.get("league"))
    return 0.72 * team_score + 0.23 * time_score + 0.05 * league_score


def time_match_score(left: str | None, right: str | None) -> float:
    """Score start-time compatibility."""

    if not left or not right:
        return 0.45
    left_dt = parse_iso(left)
    right_dt = parse_iso(right)
    if not left_dt or not right_dt:
        return 0.45 if left == right else 0.0
    diff_minutes = abs((left_dt - right_dt).total_seconds()) / 60
    if diff_minutes <= 20:
        return 1.0
    if diff_minutes <= 90:
        return 0.75
    if diff_minutes <= 240:
        return 0.35
    return 0.0


def league_match_score(left: str | None, right: str | None) -> float:
    """Score league-name compatibility."""

    if not left or not right:
        return 0.5
    return similarity(left, right)


def normalize_start_time(value: str | None) -> str | None:
    """Normalize bookmaker start labels to ISO-like UTC where possible."""

    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit() and len(raw) >= 12:
        return datetime.fromtimestamp(int(raw) / 1000, tz=UTC).replace(microsecond=0).isoformat()
    match = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{1,2}):(\d{2})$", raw)
    if match:
        day, month, year, hour, minute = map(int, match.groups())
        return datetime(year, month, day, hour, minute, tzinfo=UTC).isoformat()
    today = date.today()
    rel = re.match(r"^(?:dzi[śs]|dzisiaj)\s+(\d{1,2}):(\d{2})$", raw, re.IGNORECASE)
    if rel:
        hour, minute = map(int, rel.groups())
        return datetime(today.year, today.month, today.day, hour, minute, tzinfo=UTC).isoformat()
    rel = re.match(r"^jutro\s+(\d{1,2}):(\d{2})$", raw, re.IGNORECASE)
    if rel:
        target = today + timedelta(days=1)
        hour, minute = map(int, rel.groups())
        return datetime(target.year, target.month, target.day, hour, minute, tzinfo=UTC).isoformat()
    countdown = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})$", raw)
    if countdown:
        hours, minutes, seconds = map(int, countdown.groups())
        target = datetime.now(UTC) + timedelta(hours=hours, minutes=minutes, seconds=seconds)
        return target.replace(second=0, microsecond=0).isoformat()
    parsed = parse_iso(raw)
    if parsed:
        return parsed.replace(microsecond=0).isoformat()
    return None


def parse_iso(value: str | None) -> datetime | None:
    """Parse ISO timestamp if possible."""

    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    if parsed.year < 2000 or parsed.year > 2100:
        return None
    return parsed


def normalize_league(value: str | None) -> str | None:
    """Normalize league text for matching."""

    normalized = normalize_team_name(value or "")
    return normalized or None


def build_canonical_key(team_a_key: str, team_b_key: str, start_norm: str | None, league_norm: str | None) -> str:
    """Build stable unique key for a canonical match."""

    left, right = sorted([team_a_key, team_b_key])
    time_bucket = start_norm[:13] if start_norm else "unknown"
    base = f"{left}|{right}|{time_bucket}|{league_norm or 'unknown'}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    return f"{base}|{digest}"


def canonical_match_overview(limit: int = 100):
    """Return latest canonical matches with bookmaker coverage."""

    rows = query_df(
        """
        WITH ranked AS (
            SELECT
                cm.id AS canonical_match_id,
                cm.team_a_name,
                cm.team_b_name,
                cm.normalized_team_a,
                cm.normalized_team_b,
                cm.start_time_normalized,
                cm.league,
                b.name AS bookmaker,
                os.raw_team_a,
                os.raw_team_b,
                os.odds_a,
                os.odds_b,
                os.scraped_at,
                ROW_NUMBER() OVER (
                    PARTITION BY cm.id, b.name
                    ORDER BY os.scraped_at DESC, os.id DESC
                ) AS rn
            FROM canonical_matches cm
            LEFT JOIN odds_snapshots os ON os.canonical_match_id = cm.id
            LEFT JOIN bookmakers b ON b.id = os.bookmaker_id
        )
        SELECT * FROM ranked
        WHERE rn = 1 OR rn IS NULL
        """,
    )
    if rows.empty:
        return rows

    aggregated: list[dict[str, Any]] = []
    for match_id, group in rows.groupby("canonical_match_id", dropna=False):
        first = group.iloc[0]
        odds_a: list[float] = []
        odds_b: list[float] = []
        bookmakers: list[str] = []
        for row in group.to_dict("records"):
            if not row.get("bookmaker"):
                continue
            aligned = align_snapshot_odds(
                str(first["normalized_team_a"]),
                str(first["normalized_team_b"]),
                str(row.get("raw_team_a") or ""),
                str(row.get("raw_team_b") or ""),
                row.get("odds_a"),
                row.get("odds_b"),
            )
            if aligned is None:
                continue
            aligned_a, aligned_b = aligned
            odds_a.append(aligned_a)
            odds_b.append(aligned_b)
            bookmakers.append(str(row["bookmaker"]))
        aggregated.append(
            {
                "canonical_match_id": int(match_id),
                "team_a_name": first["team_a_name"],
                "team_b_name": first["team_b_name"],
                "start_time_normalized": first["start_time_normalized"],
                "league": first["league"],
                "bookmaker_count": len(set(bookmakers)),
                "bookmakers": ",".join(sorted(set(bookmakers))),
                "min_odds_a": min(odds_a) if odds_a else None,
                "max_odds_a": max(odds_a) if odds_a else None,
                "min_odds_b": min(odds_b) if odds_b else None,
                "max_odds_b": max(odds_b) if odds_b else None,
                "last_scraped_at": group["scraped_at"].dropna().max() if "scraped_at" in group else None,
            }
        )
    frame = pd.DataFrame(aggregated)
    if frame.empty:
        return frame
    frame = frame.sort_values(["last_scraped_at", "start_time_normalized"], ascending=[False, True], na_position="last")
    return frame.head(limit).reset_index(drop=True)


def align_snapshot_odds(
    canonical_a: str,
    canonical_b: str,
    raw_team_a: str,
    raw_team_b: str,
    odds_a: Any,
    odds_b: Any,
) -> tuple[float, float] | None:
    """Align bookmaker odds to canonical team_a/team_b orientation."""

    if odds_a is None or odds_b is None:
        return None
    raw_a = canonical_team_key(raw_team_a)
    raw_b = canonical_team_key(raw_team_b)
    direct = (similarity(canonical_a, raw_a) + similarity(canonical_b, raw_b)) / 2
    swapped = (similarity(canonical_a, raw_b) + similarity(canonical_b, raw_a)) / 2
    left = float(odds_a)
    right = float(odds_b)
    if swapped > direct:
        return right, left
    return left, right
