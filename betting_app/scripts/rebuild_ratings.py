"""Rebuild operational Elo/Glicko/TrueSkill/OpenSkill ratings from GOL.GG SQLite.

This mirrors the historical rating flow from
`scripts/05_ratingi_baseline/03_generate_ratings.py`:

- matches are processed chronologically,
- ratings are updated only after each finished game/match,
- Glicko RD time decay is applied before each match,
- Elo/TrueSkill/OpenSkill/Plackett-Luce/Thurstone-Mosteller update per game,
- Glicko updates per game after the match via `RatingManager.update_after_match`.

The output is written to `rating_runs` and `entity_ratings` for upcoming-match
inference.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from betting_app.core.db import connect, init_db, transaction  # noqa: E402
from betting_app.core.matching import normalize_team_name  # noqa: E402
from src.ratings.manager import RatingManager  # noqa: E402


RATING_SYSTEM_PARAMS: dict[str, dict[str, Any]] = {
    "elo": {"k_player": 48, "k_team": 64},
    "ts": {"mu": 25.0, "sigma": 8.333, "beta": 4.16, "tau": 0.25},
    "os": {"mu": 25.0, "sigma": 3.5},
    "pl": {"mu": 25.0, "sigma": 8.333, "beta": 18.75, "tau": 0.05},
    "tm": {"mu": 25.0, "sigma": 8.333, "beta": 18.75, "tau": 0.05},
}


@dataclass
class MatchForRatings:
    match_id: str
    match_date: date
    team1_id: str
    team2_id: str
    team1_name: str
    team2_name: str
    games: list[dict[str, Any]]
    players1: list[str]
    players2: list[str]


def main() -> None:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Process only first N chronological matches for a smoke test.")
    parser.add_argument("--ratings-version", default=None, help="Override ratings version label.")
    parser.add_argument("--source", default="golgg_sqlite_rating_manager", help="Source label stored in rating_runs.")
    args = parser.parse_args()

    init_db()
    version = args.ratings_version or datetime.now(UTC).strftime("ratings-%Y%m%dT%H%M%SZ")
    run_id = create_rating_run(version, args.source)
    try:
        stats = rebuild_ratings(version, run_id, limit=args.limit)
    except Exception as exc:
        finish_rating_run(run_id, status="failed", error=str(exc))
        raise
    finish_rating_run(
        run_id,
        status="completed",
        matches_processed=stats["matches"],
        games_processed=stats["games"],
        players_processed=stats["players"],
        data_cutoff_at=stats.get("data_cutoff_at"),
    )
    print(
        "Rebuilt ratings:",
        f"version={version}",
        f"matches={stats['matches']}",
        f"games={stats['games']}",
        f"entities={stats['entities']}",
        f"rows={stats['rows']}",
        f"cutoff={stats.get('data_cutoff_at')}",
    )


def create_rating_run(version: str, source: str) -> int:
    """Create a rating run metadata row, replacing stale rows of the same version."""

    with transaction() as connection:
        existing = connection.execute("SELECT id FROM rating_runs WHERE ratings_version = ?", (version,)).fetchone()
        if existing:
            connection.execute("DELETE FROM entity_ratings WHERE ratings_version = ?", (version,))
            connection.execute("DELETE FROM rating_runs WHERE id = ?", (existing["id"],))
        cursor = connection.execute(
            """
            INSERT INTO rating_runs(ratings_version, source, systems_json, status)
            VALUES (?, ?, ?, 'running')
            """,
            (version, source, json.dumps(RATING_SYSTEM_PARAMS, sort_keys=True)),
        )
        return int(cursor.lastrowid)


def finish_rating_run(
    run_id: int,
    *,
    status: str,
    matches_processed: int = 0,
    games_processed: int = 0,
    players_processed: int = 0,
    data_cutoff_at: str | None = None,
    error: str | None = None,
) -> None:
    """Finish a rating run metadata row."""

    with transaction() as connection:
        connection.execute(
            """
            UPDATE rating_runs
            SET status = ?, finished_at = CURRENT_TIMESTAMP, matches_processed = ?,
                games_processed = ?, players_processed = ?, data_cutoff_at = ?, error = ?
            WHERE id = ?
            """,
            (status, matches_processed, games_processed, players_processed, data_cutoff_at, error, run_id),
        )


def rebuild_ratings(version: str, run_id: int, limit: int | None = None) -> dict[str, Any]:
    """Compute final ratings and persist them to entity_ratings."""

    manager = RatingManager(RATING_SYSTEM_PARAMS)
    matches = load_matches(limit=limit)
    team_names: dict[str, str] = {}
    player_names: dict[str, str] = {}
    player_teams: dict[str, str] = {}
    team_games: Counter[str] = Counter()
    player_games: Counter[str] = Counter()
    team_last_match: dict[str, str] = {}
    player_last_match: dict[str, str] = {}
    games_processed = 0

    for match in tqdm(matches, desc="Rebuilding ratings"):
        if not match.players1 or not match.players2 or not match.games:
            continue
        team_names[match.team1_id] = match.team1_name
        team_names[match.team2_id] = match.team2_name
        match_info_date = match.match_date.isoformat()

        manager.update_before_match(match.team1_id, match.team2_id, match.players1, match.players2, match.match_date)
        scores: list[int] = []
        for game in match.games:
            score_1 = game_score_for_match_team1(match, game)
            score_2 = 1 - score_1
            scores.append(score_1)
            manager.update_after_game(match.team1_id, match.team2_id, match.players1, match.players2, score_1, score_2)
            games_processed += 1

        manager.update_after_match(match.team1_id, match.team2_id, match.players1, match.players2, scores)
        team_games[match.team1_id] += len(scores)
        team_games[match.team2_id] += len(scores)
        team_last_match[match.team1_id] = match_info_date
        team_last_match[match.team2_id] = match_info_date
        for player_id in match.players1:
            player_games[player_id] += len(scores)
            player_last_match[player_id] = match_info_date
            player_teams[player_id] = match.team1_name
        for player_id in match.players2:
            player_games[player_id] += len(scores)
            player_last_match[player_id] = match_info_date
            player_teams[player_id] = match.team2_name

        for game in match.games[:1]:
            player_names.update(load_player_display_names(game["game_id"]))

    data_cutoff = max((m.match_date for m in matches), default=None)
    rows = persist_entity_ratings(
        manager=manager,
        version=version,
        run_id=run_id,
        snapshot_at=data_cutoff.isoformat() if data_cutoff else datetime.now(UTC).date().isoformat(),
        team_names=team_names,
        player_names=player_names,
        player_teams=player_teams,
        team_games=team_games,
        player_games=player_games,
        team_last_match=team_last_match,
        player_last_match=player_last_match,
    )
    return {
        "matches": len(matches),
        "games": games_processed,
        "players": len(player_games),
        "entities": len(team_names) + len(player_games),
        "rows": rows,
        "data_cutoff_at": data_cutoff.isoformat() if data_cutoff else None,
    }


def load_matches(limit: int | None = None) -> list[MatchForRatings]:
    """Load finished non-draw matches and rosters from SQLite."""

    query = """
        SELECT match_id, date, team1_id, team2_id, team1_name, team2_name
        FROM golgg_matches
        WHERE COALESCE(draw, 0) = 0
          AND date IS NOT NULL
        ORDER BY date ASC, CAST(match_id AS INTEGER) ASC
    """
    if limit:
        query += f" LIMIT {int(limit)}"
    with connect() as connection:
        match_rows = connection.execute(query).fetchall()
        matches: list[MatchForRatings] = []
        for row in match_rows:
            games = [dict(game) for game in connection.execute(
                """
                SELECT game_id, team1_id, team2_id, team1_name, team2_name,
                       team1_win, team2_win, draw
                FROM golgg_games
                WHERE match_id = ?
                ORDER BY CAST(game_id AS INTEGER) ASC
                """,
                (row["match_id"],),
            ).fetchall()]
            if not games:
                continue
            team1_id = stable_team_id(row["team1_id"], row["team1_name"])
            team2_id = stable_team_id(row["team2_id"], row["team2_name"])
            players1 = load_players_for_match_side(connection, row["match_id"], team1_id, row["team1_name"])
            players2 = load_players_for_match_side(connection, row["match_id"], team2_id, row["team2_name"])
            if not players1 or not players2:
                continue
            matches.append(
                MatchForRatings(
                    match_id=str(row["match_id"]),
                    match_date=date.fromisoformat(str(row["date"])),
                    team1_id=team1_id,
                    team2_id=team2_id,
                    team1_name=str(row["team1_name"] or team1_id),
                    team2_name=str(row["team2_name"] or team2_id),
                    games=games,
                    players1=players1,
                    players2=players2,
                )
            )
    return matches


def stable_team_id(team_id: Any, team_name: Any) -> str:
    """Return stable team identifier used by historical ratings."""

    if team_id:
        return str(team_id)
    return f"name:{normalize_team_name(str(team_name or 'unknown'))}"


def load_players_for_match_side(connection, match_id: str, team_id: str, team_name: str | None) -> list[str]:
    """Return first-game roster for a match side, matching historical behavior."""

    first_game = connection.execute(
        """
        SELECT gp.game_id
        FROM golgg_game_players gp
        WHERE gp.match_id = ?
          AND (
                gp.team_id = ?
             OR (gp.team_id IS NULL AND lower(gp.team_name) = lower(?))
             OR (gp.team_id = '' AND lower(gp.team_name) = lower(?))
          )
        ORDER BY CAST(gp.game_id AS INTEGER) ASC
        LIMIT 1
        """,
        (match_id, team_id, team_name or "", team_name or ""),
    ).fetchone()
    if not first_game:
        return []
    rows = connection.execute(
        """
        SELECT gp.player_id, gp.player_name
        FROM golgg_game_players gp
        WHERE gp.match_id = ?
          AND gp.game_id = ?
          AND (
                gp.team_id = ?
             OR (gp.team_id IS NULL AND lower(gp.team_name) = lower(?))
             OR (gp.team_id = '' AND lower(gp.team_name) = lower(?))
          )
        ORDER BY CASE gp.role WHEN 'TOP' THEN 1 WHEN 'JUNGLE' THEN 2 WHEN 'MID' THEN 3 WHEN 'ADC' THEN 4 WHEN 'SUPPORT' THEN 5 ELSE 9 END
        """,
        (match_id, first_game["game_id"], team_id, team_name or "", team_name or ""),
    ).fetchall()
    return [str(row["player_id"] or row["player_name"] or "") for row in rows if row["player_id"] or row["player_name"]]


def load_player_display_names(game_id: str) -> dict[str, str]:
    """Load player display names for one game."""

    with connect() as connection:
        rows = connection.execute(
            "SELECT player_id, player_name FROM golgg_game_players WHERE game_id = ?",
            (game_id,),
        ).fetchall()
    return {str(row["player_id"] or row["player_name"]): str(row["player_name"] or row["player_id"]) for row in rows}


def game_score_for_match_team1(match: MatchForRatings, game: dict[str, Any]) -> int:
    """Return binary game result from match team-1 perspective."""

    if stable_team_id(game.get("team1_id"), game.get("team1_name")) == match.team1_id:
        return int(bool(game.get("team1_win")))
    if stable_team_id(game.get("team2_id"), game.get("team2_name")) == match.team1_id:
        return int(bool(game.get("team2_win")))
    return int(bool(game.get("team1_win")))


def persist_entity_ratings(
    *,
    manager: RatingManager,
    version: str,
    run_id: int,
    snapshot_at: str,
    team_names: dict[str, str],
    player_names: dict[str, str],
    player_teams: dict[str, str],
    team_games: Counter[str],
    player_games: Counter[str],
    team_last_match: dict[str, str],
    player_last_match: dict[str, str],
) -> int:
    """Persist current manager ratings into entity_ratings."""

    rows: list[tuple[Any, ...]] = []
    for system_name, system in manager.systems.items():
        for team_id, rating in dict(system.team_ratings).items():
            team_name = team_names.get(str(team_id), str(team_id))
            rows.append(entity_rating_row(
                run_id, version, snapshot_at, "team", team_name, normalize_team_name(team_name), None, None,
                system_name, rating, team_games[str(team_id)], team_last_match.get(str(team_id)), {"team_id": str(team_id)},
            ))
        for player_id, rating in dict(system.player_ratings).items():
            player_key = str(player_id)
            display_name = player_names.get(player_key, player_key)
            rows.append(entity_rating_row(
                run_id, version, snapshot_at, "player", display_name, player_key, player_teams.get(player_key), None,
                system_name, rating, player_games[player_key], player_last_match.get(player_key), {"player_id": player_key},
            ))

    with transaction() as connection:
        connection.executemany(
            """
            INSERT INTO entity_ratings(
                rating_run_id, ratings_version, snapshot_at, entity_type, entity_name,
                normalized_entity_name, team_name, role, rating_system, rating_value,
                rd, sigma, games_played, last_match_at, state_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ratings_version, entity_type, normalized_entity_name, rating_system)
            DO UPDATE SET
                rating_run_id = excluded.rating_run_id,
                snapshot_at = excluded.snapshot_at,
                entity_name = excluded.entity_name,
                team_name = excluded.team_name,
                role = excluded.role,
                rating_value = excluded.rating_value,
                rd = excluded.rd,
                sigma = excluded.sigma,
                games_played = excluded.games_played,
                last_match_at = excluded.last_match_at,
                state_json = excluded.state_json
            """,
            rows,
        )
    return len(rows)


def entity_rating_row(
    run_id: int,
    version: str,
    snapshot_at: str,
    entity_type: str,
    entity_name: str,
    normalized_entity_name: str,
    team_name: str | None,
    role: str | None,
    system_name: str,
    rating: Any,
    games_played: int,
    last_match_at: str | None,
    extra_state: dict[str, Any],
) -> tuple[Any, ...]:
    """Serialize one rating object to an entity_ratings row."""

    rating_value, rd, sigma, state = unpack_rating(rating)
    state.update(extra_state)
    return (
        run_id,
        version,
        snapshot_at,
        entity_type,
        entity_name,
        normalized_entity_name,
        team_name,
        role,
        system_name,
        rating_value,
        rd,
        sigma,
        int(games_played),
        last_match_at,
        json.dumps(state, ensure_ascii=False, sort_keys=True),
    )


def unpack_rating(rating: Any) -> tuple[float, float | None, float | None, dict[str, Any]]:
    """Return (primary value, rd, sigma, JSON state) for supported rating objects."""

    if isinstance(rating, (int, float)):
        value = float(rating)
        return value, None, None, {"rating": value}
    if hasattr(rating, "rating") and hasattr(rating, "rd"):
        value = float(rating.rating)
        rd = float(rating.rd)
        volatility = getattr(rating, "vol", getattr(rating, "volatility", None))
        state = {"rating": value, "rd": rd}
        if volatility is not None:
            state["volatility"] = float(volatility)
        return value, rd, None, state
    if hasattr(rating, "mu") and hasattr(rating, "sigma"):
        mu = float(rating.mu)
        sigma = float(rating.sigma)
        return mu, None, sigma, {"mu": mu, "sigma": sigma}
    value = float(rating)
    return value, None, None, {"rating": value}


if __name__ == "__main__":
    main()
