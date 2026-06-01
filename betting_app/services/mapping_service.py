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
    "dplus": "Dplus KIA",
    "dk": "Dplus KIA",
    "dn soopers": "DN SOOPers",
    "soopers": "DN SOOPers",
    "top": "Top Esports",
    "tes": "Top Esports",
    "edward": "EDward Gaming",
    "fearx": "FearX",
    "bnk fearx": "FearX",
    "geng": "Gen.G",
    "gen g": "Gen.G",
    "barca": "Barca eSports",
    "bomba": "BOMBA Team",
    "ccg": "CCG Esports",
    "deep cross": "Deep Cross Gaming",
    "ronaldoteam": "Ronaldo Team",
    "los": "Los Grandes",
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
                ON CONFLICT(normalized_name) DO UPDATE SET
                    team_name = excluded.team_name
                """,
                (team, normalize_team_name(team)),
            )
    return len(teams)


def known_golgg_teams() -> pd.DataFrame:
    """Return known canonical team names."""

    return query_df("SELECT * FROM golgg_teams ORDER BY team_name")


def suggest_mapping(raw_name: str) -> tuple[str | None, float]:
    """Suggest a canonical GOL.GG team for a raw bookmaker name."""

    confirmed = query_df(
        "SELECT alias FROM team_aliases WHERE normalized_name = ? AND alias IS NOT NULL LIMIT 1",
        (normalize_team_name(raw_name),),
    )
    if not confirmed.empty:
        return str(confirmed.iloc[0]["alias"]), 1.0

    normalized = normalize_team_name(raw_name)
    alias_target = BOOKMAKER_TO_GOLGG_ALIASES.get(normalized) or BOOKMAKER_TO_GOLGG_ALIASES.get(
        normalized.replace(" ", "")
    )
    if alias_target:
        teams = known_golgg_teams()
        candidates = teams["team_name"].tolist() if not teams.empty else load_golgg_team_candidates()
        for candidate in candidates:
            if normalize_team_name(candidate) == normalize_team_name(alias_target):
                return candidate, 1.0
        return alias_target, 1.0

    teams = known_golgg_teams()
    candidates = teams["team_name"].tolist() if not teams.empty else load_golgg_team_candidates()
    return best_match(raw_name, candidates)


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
