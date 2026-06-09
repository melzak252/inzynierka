"""Services for bookmaker-team to GOL.GG-team mapping."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from betting_app.core.db import query_df, transaction
from betting_app.core.matching import best_match, normalize_team_name, similarity
from betting_app.core.config import PROJECT_ROOT


BOOKMAKER_TO_GOLGG_ALIASES = {
    # BRION changed naming/sponsors across bookmakers and seasons.
    "brion": "BRION",
    "hanjin brion": "BRION",
    "oksavingsbank brion": "BRION",
    "ok savingsbank brion": "BRION",
    # Common short forms used by bookmakers.
    "9z": "9z Globant",
    "anyones legend": "Anyone's Legend",
    "arctic pandas": "Arctic Pandas",
    "barca": "Barca eSports",
    "barczaca": "Barczaca",
    "bilibili": "Bilibili",
    "bnk fearx": "FearX",
    "bomba": "BOMBA Team",
    "bubliki": "Bubliki Esports",
    "bulldog": "Bulldog Esports",
    "ccg": "CCG Esports",
    "conviction": "Conviction Esports",
    "dplus": "Dplus KIA",
    "dplus challengers": "Dplus KIA Challengers",
    "dplus kia": "Dplus KIA",
    "dk": "Dplus KIA",
    "deep cross": "Deep Cross Gaming",
    "dn soopers": "DN SOOPers",
    "drx": "DRX",
    "edward": "EDward Gaming",
    "eintracht spandau": "Eintracht Spandau",
    "esuba": "Esuba",
    "fc barcelona": "Barca eSports",
    "fearx": "FearX",
    "fluxo w7m": "Fluxo W7M",
    "flyquest": "FlyQuest",
    "forsaken": "Forsaken",
    "g2 nord": "G2 Nord",
    "galions": "Galions",
    "gam": "GAM Esports",
    "gen g": "Gen.G",
    "gen g global academy": "Gen.G Global Academy",
    "geng": "Gen.G",
    "giantx": "GiantX",
    "gmblers": "GMBLERS",
    "hanwha life": "Hanwha Life Esports",
    "hmble": "HMBLE",
    "jd": "JD Gaming",
    "karmine corp": "Karmine Corp",
    "karmine corp blue": "Karmine Corp Blue",
    "kt rolster": "KT Rolster",
    "lgd": "LGD Gaming",
    "liquid": "Team Liquid",
    "los": "Los Grandes",
    "los grandes": "Los Grandes",
    "meavedron": "Meavedron",
    "mvk": "MVK",
    "natus vincere": "Natus Vincere",
    "nongshim redforce": "Nongshim RedForce",
    "nongshim redforce challengers": "Nongshim RedForce Challengers",
    "ns red force": "Nongshim RedForce",
    "ok savingsbank brion": "BRION",
    "oksavingsbank brion": "BRION",
    "red canids": "RED Canids",
    "red canids kalunga": "RED Canids",
    "ronaldo": "Ronaldo Team",
    "ronaldoteam": "Ronaldo Team",
    "secret whales": "Secret Whales",
    "sentinels": "Sentinels",
    "shopify rebellion": "Shopify Rebellion",
    "soopers": "DN SOOPers",
    "soopers challengers": "DN SOOPers Challengers",
    "t1": "T1",
    "tes": "Top Esports",
    "thundertalk": "ThunderTalk Gaming",
    "top": "Top Esports",
    "vitality": "Team Vitality",
    "we": "Weibo Gaming",
}


def load_golgg_team_candidates() -> list[str]:
    """Load known team names from local GOL.GG data and existing aliases."""

    candidates: set[str] = set()
    try:
        db_teams = query_df("SELECT DISTINCT team_name FROM golgg_teams WHERE team_name IS NOT NULL")
    except Exception:
        db_teams = pd.DataFrame()
    for value in db_teams.get("team_name", []):
        if isinstance(value, str) and value.strip():
            candidates.add(value.strip())
    if candidates:
        alias_df = query_df("SELECT DISTINCT alias FROM team_aliases WHERE alias IS NOT NULL")
        for value in alias_df.get("alias", []):
            if isinstance(value, str) and value.strip():
                candidates.add(value.strip())
        return sorted(candidates)

    matches_path = PROJECT_ROOT / "data" / "golgg_matches.json"
    if matches_path.exists():
        with matches_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        rows = payload if isinstance(payload, list) else payload.get("matches", []) if isinstance(payload, dict) else []
        top_level_keys = (
            "team1",
            "team2",
            "team1_name",
            "team2_name",
            "sname_t1",
            "sname_t2",
            "won",
            "lost",
            "blue_team",
            "red_team",
        )
        game_level_keys = ("t1_name", "t2_name", "team1_name", "team2_name")
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in top_level_keys:
                value = row.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.add(value.strip())
            for game in row.get("games", []) or []:
                if not isinstance(game, dict):
                    continue
                for key in game_level_keys:
                    value = game.get(key)
                    if isinstance(value, str) and value.strip():
                        candidates.add(value.strip())
    alias_df = query_df("SELECT DISTINCT alias FROM team_aliases WHERE alias IS NOT NULL")
    for value in alias_df.get("alias", []):
        if isinstance(value, str) and value.strip():
            candidates.add(value.strip())
    return sorted(candidates)


def sync_golgg_teams() -> int:
    """Populate the local canonical team table from available GOL.GG data."""

    teams = load_golgg_team_candidates()
    with transaction() as connection:
        for team in teams:
            connection.execute(
                """
                INSERT INTO golgg_teams(team_name, normalized_name)
                VALUES (?, ?)
                ON CONFLICT(team_name) DO UPDATE SET
                    normalized_name = excluded.normalized_name
                """,
                (team, normalize_team_name(team)),
            )
    return len(teams)


def known_golgg_teams() -> pd.DataFrame:
    """Return known canonical team names."""

    return query_df("SELECT * FROM golgg_teams ORDER BY team_name")


def suggest_mapping(raw_name: str) -> tuple[str | None, float, str]:
    """Suggest a canonical GOL.GG team for a raw bookmaker name.

    Returns (golgg_name, confidence, source) where source is one of:
    'alias'  — matched via team_aliases table (confidence 1.0)
    'builtin' — matched via BOOKMAKER_TO_GOLGG_ALIASES dict (confidence 1.0)
    'fuzzy'  — matched via fuzzy string similarity (confidence < 1.0)
    'blocked' — a blocked alias exists, mapping suppressed (None, 0.0)
    """

    normalized = normalize_team_name(raw_name)

    # Check for blocked alias first
    blocked = query_df(
        "SELECT 1 FROM team_aliases WHERE normalized_name = ? AND alias = '' AND source = 'blocked' LIMIT 1",
        (normalized,),
    )
    if not blocked.empty:
        return None, 0.0, "blocked"

    confirmed = query_df(
        "SELECT alias FROM team_aliases WHERE normalized_name = ? AND alias IS NOT NULL LIMIT 1",
        (normalized,),
    )
    if not confirmed.empty:
        return str(confirmed.iloc[0]["alias"]), 1.0, "alias"

    alias_target = BOOKMAKER_TO_GOLGG_ALIASES.get(normalized) or BOOKMAKER_TO_GOLGG_ALIASES.get(
        normalized.replace(" ", "")
    )
    if alias_target:
        teams = known_golgg_teams()
        candidates = teams["team_name"].tolist() if not teams.empty else load_golgg_team_candidates()
        for candidate in candidates:
            if normalize_team_name(candidate) == normalize_team_name(alias_target):
                return candidate, 1.0, "builtin"
        return alias_target, 1.0, "builtin"

    teams = known_golgg_teams()
    candidates = teams["team_name"].tolist() if not teams.empty else load_golgg_team_candidates()
    golgg_name, confidence = best_match(raw_name, candidates)
    return golgg_name, confidence, "fuzzy"


def upsert_alias(raw_name: str, golgg_team_name: str, source: str = "manual", confirmed: bool = True) -> int:
    """Create/update a raw-name alias mapping."""

    normalized = normalize_team_name(raw_name)
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO team_aliases(normalized_name, alias, source)
            VALUES (?, ?, ?)
            ON CONFLICT(normalized_name, source) DO UPDATE SET
                alias = excluded.alias
            """,
            (normalized, golgg_team_name, source),
        )
        row = connection.execute(
            "SELECT id FROM team_aliases WHERE normalized_name = ? AND source = ?", (normalized, source)
        ).fetchone()
        return int(row["id"])


def delete_alias(raw_name: str, source: str = "manual") -> bool:
    """Delete a raw-name alias mapping. Returns True if a row was deleted."""
    normalized = normalize_team_name(raw_name)
    with transaction() as connection:
        cursor = connection.execute(
            "DELETE FROM team_aliases WHERE normalized_name = ? AND source = ?",
            (normalized, source),
        )
        return cursor.rowcount > 0


def block_alias(raw_name: str) -> int:
    """Block a fuzzy match by inserting a 'blocked' alias entry.

    This prevents suggest_mapping from returning a fuzzy match for this name.
    The alias column is set to empty string to indicate a block rather than a mapping.
    """
    normalized = normalize_team_name(raw_name)
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO team_aliases(normalized_name, alias, source)
            VALUES (?, '', 'blocked')
            ON CONFLICT(normalized_name, source) DO UPDATE SET
                alias = excluded.alias
            """,
            (normalized,),
        )
        row = connection.execute(
            "SELECT id FROM team_aliases WHERE normalized_name = ? AND source = 'blocked'",
            (normalized,),
        ).fetchone()
        return int(row["id"])


def unblock_alias(raw_name: str) -> bool:
    """Remove a blocked alias entry. Returns True if a row was deleted."""
    normalized = normalize_team_name(raw_name)
    with transaction() as connection:
        cursor = connection.execute(
            "DELETE FROM team_aliases WHERE normalized_name = ? AND source = 'blocked'",
            (normalized,),
        )
        return cursor.rowcount > 0


def unmapped_raw_teams() -> pd.DataFrame:
    """Return raw bookmaker names without confirmed canonical mapping."""

    return query_df(
        """
        WITH raw_names AS (
            SELECT raw_team_a AS raw_name FROM odds_snapshots
            UNION
            SELECT raw_team_b AS raw_name FROM odds_snapshots
        )
        SELECT raw_name
        FROM raw_names
        WHERE lower(trim(raw_name)) NOT IN (
            SELECT lower(trim(normalized_name)) FROM team_aliases
        )
        ORDER BY raw_name
        """
    )
