"""Behavioral tests for the team and player rankings API."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from betting_app.core.db import get_session


def _seed_completed_rankings() -> None:
    with get_session() as session:
        session.execute(
            text(
                """
                INSERT INTO rating_runs(
                    id, ratings_version, data_cutoff_at, started_at, finished_at,
                    status, matches_processed, games_processed, players_processed
                ) VALUES (
                    1, 'ratings-old', '2026-08-01T00:00:00+00:00',
                    '2026-08-01T00:00:00+00:00', '2026-08-01T00:05:00+00:00',
                    'completed', 20, 40, 100
                ), (
                    2, 'ratings-current', '2026-09-01T00:00:00+00:00',
                    '2026-09-01T00:00:00+00:00', '2026-09-01T00:05:00+00:00',
                    'completed', 30, 60, 150
                ), (
                    3, 'ratings-running', '2026-09-02T00:00:00+00:00',
                    '2026-09-02T00:00:00+00:00', NULL,
                    'running', 0, 0, 0
                )
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO entity_ratings(
                    rating_run_id, ratings_version, snapshot_at, entity_type,
                    entity_name, normalized_entity_name, team_name, role,
                    rating_system, rating_value, rd, sigma, games_played, last_match_at
                ) VALUES
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'team',
                     'Gen.G', 'gen g', NULL, NULL, 'elo', 1710.5, NULL, NULL, 45, '2026-08-31'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'team',
                     'T1', 't1', NULL, NULL, 'elo', 1690.25, NULL, NULL, 52, '2026-08-30'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'team',
                     'Bilibili Gaming', 'bilibili gaming', NULL, NULL, 'elo', 1650.0, NULL, NULL, 40, '2026-08-29'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'team',
                     'Rookie Team', 'rookie team', NULL, NULL, 'elo', 1800.0, NULL, NULL, 2, '2026-08-29'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'team',
                     'Gen.G', 'gen g', NULL, NULL, 'ts', 28.4, NULL, 4.1, 45, '2026-08-31'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'team',
                     'T1', 't1', NULL, NULL, 'ts', 29.0, NULL, 3.9, 52, '2026-08-30'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'team',
                     'Bilibili Gaming', 'bilibili gaming', NULL, NULL, 'ts', 27.0, NULL, 4.4, 40, '2026-08-29'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'team',
                     'Rookie Team', 'rookie team', NULL, NULL, 'ts', 31.0, NULL, 5.2, 2, '2026-08-29'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'team',
                     'SK Telecom T1', 'sk telecom t1', NULL, NULL, 'elo', 1900.0, NULL, NULL, 90, '2019-11-03'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'team',
                     'SK Telecom T1', 'sk telecom t1', NULL, NULL, 'ts', 32.0, NULL, 3.0, 90, '2019-11-03'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'team',
                     'T1 Esports Academy', 't1 academy', NULL, NULL, 'elo', 1850.0, NULL, NULL, 70, '2026-08-20'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'team',
                     'T1 Esports Academy', 't1 academy', NULL, NULL, 'ts', 31.0, NULL, 3.5, 70, '2026-08-20'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'player',
                     'Faker', 'faker-id', 'T1', 'MID', 'elo', 1640.0, NULL, NULL, 110, '2026-08-30'),
                    (2, 'ratings-current', '2026-09-01T00:05:00+00:00', 'player',
                     'Chovy', 'chovy-id', 'Gen.G', 'MID', 'elo', 1665.0, NULL, NULL, 105, '2026-08-31')
                """
            )
        )
        session.commit()


def test_rankings_empty_without_completed_run(client: TestClient) -> None:
    response = client.get("/rankings")

    assert response.status_code == 200
    assert response.json() == {
        "entity_type": "team",
        "rating_system": "unified",
        "ratings_version": None,
        "active_since": None,
        "squad_scope": "main",
        "data_cutoff_at": None,
        "snapshot_at": None,
        "total": 0,
        "available_rating_systems": [],
        "rankings": [],
    }


def test_team_rankings_use_latest_completed_snapshot_and_filters(client: TestClient) -> None:
    _seed_completed_rankings()

    response = client.get("/rankings", params={"entity_type": "team", "rating_system": "elo", "min_games": 10})

    assert response.status_code == 200
    data = response.json()
    assert data["ratings_version"] == "ratings-current"
    assert data["data_cutoff_at"] == "2026-09-01T00:00:00+00:00"
    assert data["available_rating_systems"] == ["elo", "ts"]
    assert data["total"] == 3
    assert [(row["rank"], row["entity_name"]) for row in data["rankings"]] == [
        (1, "Gen.G"),
        (2, "T1"),
        (3, "Bilibili Gaming"),
    ]
    assert data["rankings"][0]["rating_value"] == 1710.5
    assert data["rankings"][0]["system_count"] == 1


def test_player_rankings_support_name_search(client: TestClient) -> None:
    _seed_completed_rankings()

    response = client.get(
        "/rankings",
        params={"entity_type": "player", "rating_system": "elo", "search": "Fak", "min_games": 1},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["rankings"][0]["entity_name"] == "Faker"
    assert data["rankings"][0]["team_name"] == "T1"
    assert data["rankings"][0]["role"] == "MID"


def test_unified_rankings_average_system_percentiles_and_preserve_global_rank(client: TestClient) -> None:
    _seed_completed_rankings()

    response = client.get(
        "/rankings",
        params={"entity_type": "team", "rating_system": "unified", "search": "Gen", "min_games": 10},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["rankings"][0]["entity_name"] == "Gen.G"
    assert data["rankings"][0]["rank"] == 2
    assert data["rankings"][0]["rating_value"] == 75.0
    assert data["rankings"][0]["system_count"] == 2


def test_default_cohort_excludes_stale_and_explicit_development_squads(client: TestClient) -> None:
    _seed_completed_rankings()

    default_response = client.get(
        "/rankings",
        params={"entity_type": "team", "rating_system": "unified", "search": "T1", "min_games": 10},
    )
    development_response = client.get(
        "/rankings",
        params={
            "entity_type": "team",
            "rating_system": "unified",
            "search": "T1",
            "min_games": 10,
            "squad_scope": "development",
        },
    )
    historical_response = client.get(
        "/rankings",
        params={
            "entity_type": "team",
            "rating_system": "unified",
            "search": "T1",
            "min_games": 10,
            "squad_scope": "all",
            "active_within_months": 0,
        },
    )

    assert default_response.status_code == 200
    assert default_response.json()["active_since"] == "2026-03-01"
    assert [row["entity_name"] for row in default_response.json()["rankings"]] == ["T1"]
    assert [row["entity_name"] for row in development_response.json()["rankings"]] == ["T1 Esports Academy"]
    assert {row["entity_name"] for row in historical_response.json()["rankings"]} == {
        "T1",
        "SK Telecom T1",
        "T1 Esports Academy",
    }
