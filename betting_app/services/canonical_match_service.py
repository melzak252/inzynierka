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
    "soopers": "dn soopers",
    "dplus kia": "dplus kia",
    "dk": "dplus kia",
    "drx": "drx",
    "kiwoom drx": "drx",
    "giantx": "giantx",
    "giant x": "giantx",
    "top esports": "top esports",
    "top": "top esports",
    "tes": "top esports",
    "thundertalk gaming": "thundertalk",
    "thundertalk": "thundertalk",
    "tt gaming": "thundertalk",
    "tt": "thundertalk",
    "edward": "edward gaming",
    "edward gaming": "edward gaming",
    "anyones legend": "anyones legend",
    "anyone s legend": "anyones legend",
    "anyone legend": "anyones legend",
    "fearx": "bnk fearx",
    "bnk fearx": "bnk fearx",
    "karmine corp blue": "karmine corp blue",
    "kc blue": "karmine corp blue",
    "karmine corp": "karmine corp",
    "geng": "gen g",
    "gen g": "gen g",
    "gen.g": "gen g",
    "dplus": "dplus kia",
    "barca esports": "barca esports",
    "barca": "barca esports",
    "fc barcelona": "barca esports",
    "movistar koi": "koi",
    "movister koi": "koi",
    "nongshim redforce": "nongshim redforce",
    "ns red force": "nongshim redforce",
    "red canids": "red canids",
    "red canids kalunga": "red canids",
    "ruddy corporation": "ruddy",
    "ruddy esports": "ruddy",
    "ruddy": "ruddy",
    "los": "los",
    "los grandes": "los",
    "ronaldo": "ronaldoteam",
    "ronaldoteam": "ronaldoteam",
    "soopers challengers": "soopers challengers",
    "anyones legend": "anyones legend",
    "anyone s legend": "anyones legend",
    "anyone legend": "anyones legend",
    "we love": "wlgaming",
    "wlgaming": "wlgaming",
    "ucam club": "ucam",
    "ucam ec": "ucam",
    "ucam tokiers": "ucam",
    "ucam": "ucam",
    "e wie einfach": "e wie einfach e sports",
}


# ---------------------------------------------------------------------------
# League → best-of mapping
# ---------------------------------------------------------------------------
# Bo3 leagues (major regions + some minor that use Bo3 regular season)
# NOTE: substring matching is used, so order matters — more specific patterns
# should come first.  "lpl" would also match "lplol" (LPLOL), so we use
# "lpl" with an exclusion check inside infer_best_of().
_BO3_LEAGUE_PATTERNS: list[str] = [
    "lck",
    "lpl",
    "lec",
    "lck challengers",
    "lck road to msi",
    "cblo",
    "ljl",
    "lcs na",
    "lcs",
    "tcl",
    "lcp",
    "tj sports lol / lpl",
]

# Leagues whose names contain a Bo3 pattern substring but are actually Bo1.
_BO1_OVERRIDE_PATTERNS: list[str] = [
    "lpol",   # LPLOL, Inygon / LPLOL
    "nacl",   # NACL (contains "lcs" substring via "na challengers league")
    "na challengers",
]

# Bo5 is only for playoffs / finals — we cannot reliably detect that from
# the league name alone, so default regular-season Bo3 leagues to 3.
# Everything else defaults to Bo1.


def infer_best_of(league: str | None) -> int:
    """Return the best-of value for a given league name.

    Uses substring matching so that variants like "Riot LoL / LCK" still
    resolve correctly.  Bo1 overrides take precedence over Bo3 patterns
    (e.g. LPLOL contains "lpl" but is Bo1).
    """
    if not league:
        return 1
    low = league.lower()
    # Check Bo1 overrides first — they take precedence
    for pattern in _BO1_OVERRIDE_PATTERNS:
        if pattern in low:
            return 1
    for pattern in _BO3_LEAGUE_PATTERNS:
        if pattern in low:
            return 3
    return 1


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
    best_of: int | None = None,
) -> int:
    """Find or create a canonical match shared by all bookmakers."""

    team_a_key = canonical_team_key(raw_team_a)
    team_b_key = canonical_team_key(raw_team_b)
    start_norm = normalize_start_time(match_start_time)
    league_norm = normalize_league(league)

    # Prefer scraper-provided best_of over heuristic; fall back to heuristic
    # when the scraper did not detect the format (e.g. no "liczba map" line).
    best_of_val = best_of if best_of is not None else infer_best_of(league)

    # Search across upcoming, expired, AND finished matches when we have a
    # trustworthy start time.  Including finished is essential: once GOL.GG
    # marks a match finished, later bookmaker odds for the same real match
    # must attach to the finished row, not create an expired duplicate.
    # The time_match_score naturally rejects old finished matches (decays to
    # 0.0 at 3+ days), and the identical-teams boost in canonical_match_score
    # is intentionally NOT applied to finished candidates, so finished matches
    # only match when both teams AND time are close.
    # Without a trustworthy time restrict to upcoming rows only, so a new
    # feed item is not accidentally attached to an old finished match.
    candidate_where = "WHERE status IN ('upcoming', 'expired', 'finished')" if start_norm else "WHERE status = 'upcoming'"
    candidate_params: tuple = ()

    with transaction() as connection:
        candidates = connection.execute(
            f"""
            SELECT * FROM canonical_matches
            {candidate_where}
            ORDER BY id DESC
            LIMIT 1000
            """,
            candidate_params,
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
            # When the scraper provides best_of, always update it (the scraper
            # has direct evidence from the bookmaker page).  Otherwise only
            # fill in null values via COALESCE to preserve manual edits.
            if best_of is not None:
                best_of_sql = "best_of = ?"
                best_of_params: tuple[int, ...] = (best_of_val,)
            else:
                best_of_sql = "best_of = COALESCE(best_of, ?)"
                best_of_params = (best_of_val,)
            connection.execute(
                f"""
                UPDATE canonical_matches
                SET start_time_normalized = COALESCE(start_time_normalized, ?),
                    league = COALESCE(league, ?),
                    match_confidence = GREATEST(match_confidence, ?),
                    {best_of_sql}
                WHERE id = ?
                """,
                (start_norm, league, best_score, *best_of_params, best_id),
            )
            return best_id

        canonical_key = build_canonical_key(team_a_key, team_b_key, start_norm, league_norm)
        connection.execute(
            """
            INSERT INTO canonical_matches(
                canonical_key, team_a_name, team_b_name, normalized_team_a, normalized_team_b,
                start_time_normalized, league, match_confidence, best_of
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1.0, ?)
            ON CONFLICT (canonical_key) DO NOTHING
            """,
            (canonical_key, raw_team_a, raw_team_b, team_a_key, team_b_key, start_norm, league, best_of_val),
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
    score = 0.72 * team_score + 0.23 * time_score + 0.05 * league_score

    # Boost: identical teams on an *upcoming* match means it IS the same
    # canonical match even when bookmaker start labels move a bit.  Do not
    # apply this to expired/finished rows: repeated fixtures with the same two
    # teams would otherwise be attached to an old expired canonical match when
    # the date/time is different (e.g. next-day rematches/tournament series).
    if team_score >= 0.95 and candidate.get("status") == "upcoming":
        score = max(score, 0.85)

    return score


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
    # Explicitly reject countdown labels before any other parser gets a chance
    # to interpret them as clock times. Betfan and similar feeds can emit a
    # changing HH:MM:SS countdown shortly before kickoff; treating that as a
    # start time creates a new match key/canonical row on every scrape and
    # corrupts odds history used for CLV analysis.
    if is_countdown_start_label(raw):
        return None
    if raw.isdigit() and len(raw) >= 12:
        return datetime.fromtimestamp(int(raw) / 1000, tz=UTC).replace(microsecond=0).isoformat()
    match = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{1,2}):(\d{2})$", raw)
    if match:
        day, month, year, hour, minute = map(int, match.groups())
        return datetime(year, month, day, hour, minute, tzinfo=UTC).isoformat()
    # eFortuna full-date format with day-of-week prefix, e.g. "śro., 14.06.2026, 22:00"
    match = re.match(r"^[a-ząćęłńóśźż]{2,8}\.,\s*(\d{2})\.(\d{2})\.(\d{4}),\s*(\d{1,2}):(\d{2})$", raw, re.IGNORECASE)
    if match:
        day, month, year, hour, minute = map(int, match.groups())
        return datetime(year, month, day, hour, minute, tzinfo=UTC).isoformat()
    # Use UTC date so "dziś/dzisiaj" resolves correctly even when the
    # scraper runs after midnight in the local timezone (CEST/UTC+2).
    today = datetime.now(UTC).date()
    rel = re.match(r"^(?:dzi[śs]|dzisiaj)\s+(\d{1,2}):(\d{2})$", raw, re.IGNORECASE)
    if rel:
        hour, minute = map(int, rel.groups())
        return datetime(today.year, today.month, today.day, hour, minute, tzinfo=UTC).isoformat()
    rel = re.match(r"^jutro\s+(\d{1,2}):(\d{2})$", raw, re.IGNORECASE)
    if rel:
        target = today + timedelta(days=1)
        hour, minute = map(int, rel.groups())
        return datetime(target.year, target.month, target.day, hour, minute, tzinfo=UTC).isoformat()
    parsed = parse_iso(raw)
    if parsed:
        return parsed.replace(microsecond=0).isoformat()
    return None


def is_countdown_start_label(value: str | None) -> bool:
    """Return True for unstable countdown labels such as HH:MM:SS."""

    if not value:
        return False
    raw = str(value).strip()
    match = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})$", raw)
    if not match:
        return False
    hours, minutes, seconds = map(int, match.groups())
    return minutes < 60 and seconds < 60 and hours < 48


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
