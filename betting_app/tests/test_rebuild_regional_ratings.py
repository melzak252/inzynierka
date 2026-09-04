from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from betting_app.core.db import connect, dispose_engine, init_db, transaction
from betting_app.scripts.rebuild_regional_ratings import (
    ALL_RATING_SYSTEMS,
    REGIONAL_RATINGS_VERSION,
    rebuild_regional_ratings,
)


@pytest.fixture
def regional_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    database = tmp_path / "regional-ratings.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    dispose_engine()
    init_db()
    try:
        yield
    finally:
        dispose_engine()


def _insert_match(
    *,
    match_id: str,
    match_date: str,
    tournament: str,
    team_a: tuple[str, str],
    team_b: tuple[str, str],
    roster_a: Sequence[tuple[str, str]],
    roster_b: Sequence[tuple[str, str]],
    score_a: int,
) -> None:
    game_id = f"{match_id}01"
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO golgg_matches(
                match_id, date, tournament_name, team1_id, team2_id,
                team1_name, team2_name, team1_score, team2_score,
                team1_win, team2_win, draw, games_played
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
            """,
            (
                match_id,
                match_date,
                tournament,
                team_a[0],
                team_b[0],
                team_a[1],
                team_b[1],
                score_a,
                1 - score_a,
                score_a,
                1 - score_a,
            ),
        )
        connection.execute(
            """
            INSERT INTO golgg_games(
                game_id, match_id, date, tournament_name,
                team1_id, team2_id, team1_name, team2_name,
                team1_win, team2_win, draw
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                game_id,
                match_id,
                match_date,
                tournament,
                team_a[0],
                team_b[0],
                team_a[1],
                team_b[1],
                score_a,
                1 - score_a,
            ),
        )
        for side, team, roster in (("1", team_a, roster_a), ("2", team_b, roster_b)):
            for role, (player_id, player_name) in zip(("TOP", "JUNGLE"), roster, strict=True):
                connection.execute(
                    """
                    INSERT INTO golgg_game_players(
                        game_id, match_id, team_id, team_name, side,
                        role, player_id, player_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (game_id, match_id, team[0], team[1], side, role, player_id, player_name),
                )


def _insert_history() -> None:
    _insert_match(
        match_id="100", match_date="2024-01-01", tournament="LCK 2024 Spring",
        team_a=("kr-a", "Korea Alpha"), team_b=("kr-b", "Korea Beta"),
        roster_a=(("k1", "K One"), ("k2", "K Two")),
        roster_b=(("k3", "K Three"), ("k4", "K Four")), score_a=1,
    )
    _insert_match(
        match_id="101", match_date="2024-01-01", tournament="LEC 2024 Spring",
        team_a=("eu-a", "Europe Alpha"), team_b=("eu-b", "Europe Beta"),
        roster_a=(("e1", "E One"), ("e2", "E Two")),
        roster_b=(("e3", "E Three"), ("e4", "E Four")), score_a=1,
    )
    _insert_match(
        match_id="200", match_date="2024-02-01", tournament="Worlds 2024 Main Event",
        team_a=("kr-a", "Korea Alpha"), team_b=("eu-a", "Europe Alpha"),
        roster_a=(("k1", "K One"), ("k2", "K Two")),
        roster_b=(("e1", "E One"), ("e2", "E Two")), score_a=1,
    )


def test_unified_snapshot_contains_one_regional_gl_and_five_raw_systems(regional_db: None) -> None:
    _insert_history()

    stats = rebuild_regional_ratings()

    assert stats["version"] == REGIONAL_RATINGS_VERSION
    assert stats["rating_systems"] == list(ALL_RATING_SYSTEMS)
    with connect() as connection:
        systems = connection.execute(
            """
            SELECT DISTINCT rating_system
            FROM entity_ratings
            WHERE ratings_version = ?
            ORDER BY rating_system
            """,
            (REGIONAL_RATINGS_VERSION,),
        ).fetchall()
        gl_row = connection.execute(
            """
            SELECT state_json
            FROM entity_ratings
            WHERE ratings_version = ? AND rating_system = 'gl'
              AND entity_type = 'team' AND normalized_entity_name = 'korea alpha'
            """,
            (REGIONAL_RATINGS_VERSION,),
        ).fetchone()
        run = connection.execute(
            "SELECT systems_json FROM rating_runs WHERE ratings_version = ?",
            (REGIONAL_RATINGS_VERSION,),
        ).fetchone()

    assert {row["rating_system"] for row in systems} == set(ALL_RATING_SYSTEMS)
    assert gl_row is not None
    gl_state = json.loads(str(gl_row["state_json"]))
    assert gl_state["competition_calibration"] == "family-calibrated-glicko2-v1"
    assert gl_state["family"] == "LCK"
    assert "family_variance" in gl_state
    payload = json.loads(str(run["systems_json"]))
    assert payload["contract_version"] == REGIONAL_RATINGS_VERSION
    assert set(payload["raw_systems"]) == {"elo", "ts", "os", "pl", "tm"}
    assert payload["gl"]["engine"] == "family-calibrated-glicko2-v1"
