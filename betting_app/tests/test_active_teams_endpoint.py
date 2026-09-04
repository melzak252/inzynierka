"""Regression tests for the active-team suggestion endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from betting_app.core.db import get_session
from betting_app.services.rating_contract import OPERATIONAL_RATINGS_VERSION


def test_active_teams_returns_current_operational_ratings(client: TestClient) -> None:
    session = get_session()
    try:
        session.execute(
            text(
                """
                INSERT INTO entity_ratings (
                    ratings_version, entity_type, entity_name, normalized_entity_name,
                    rating_system, rating_value, games_played, last_match_at
                ) VALUES (
                    :ratings_version, 'team', 'Current Team', 'current team',
                    'gl', 1875, 12, '2026-09-01T12:00:00+00:00'
                )
                """
            ),
            {"ratings_version": OPERATIONAL_RATINGS_VERSION},
        )
        session.commit()
    finally:
        session.close()

    response = client.get("/matches/active-teams")

    assert response.status_code == 200
    assert response.json()["teams"] == [
        {
            "name": "Current Team",
            "rating": 1875.0,
            "games": 12,
            "last_active": "2026-09-01",
        }
    ]
