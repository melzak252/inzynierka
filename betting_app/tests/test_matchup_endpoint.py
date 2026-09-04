import pytest
import pandas as pd

from fastapi.testclient import TestClient

from betting_app.api.main import app
from betting_app.api.routers import matches as matches_router


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_simulate_matchup_endpoint_basic(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    received_kwargs: list[dict] = []

    def fake_build_features(match: dict, **kwargs):
        received_kwargs.append(kwargs)
        return {
            "status": "ready_player",
            "features": {
                "mapping": {
                    "team_a_golgg_name": "T1",
                    "team_b_golgg_name": "Gen.G",
                    "team_a_confidence": 1.0,
                    "team_b_confidence": 1.0,
                    "team_a_source": "exact",
                    "team_b_source": "exact",
                },
                "ratings": {
                    "probabilities": {"consensus": 0.65},
                    "team_a": {"gl": {"rating_value": 1850.0, "rd": 70.0}},
                    "team_b": {"gl": {"rating_value": 1700.0, "rd": 75.0}},
                },
                "player_ratings": {
                    "probabilities": {"consensus": 0.68},
                    "team_a_roster": {
                        "team_name": "T1",
                        "players": [{"player_id": "t1-top", "player_name": "Zeus", "role": "TOP"}],
                    },
                    "team_b_roster": {
                        "team_name": "Gen.G",
                        "players": [{"player_id": "geng-top", "player_name": "Kiin", "role": "TOP"}],
                    },
                    "team_a": {
                        "gl": {
                            "avg_rating_value": 1820.0,
                            "avg_rd": 65.0,
                            "players_with_rating": 1,
                            "players": [{
                                "normalized_entity_name": "t1-top",
                                "entity_name": "ZEUS",
                                "rating_value": 1825.0,
                                "rd": 65.0,
                                "games_played": 20,
                            }],
                        }
                    },
                    "team_b": {"gl": {"avg_rating_value": 1710.0, "avg_rd": 68.0, "players": []}},
                },
                "w20": {
                    "probability": 0.60,
                    "team_a": {"team_name": "T1", "win_rate": 0.75},
                    "team_b": {"team_name": "Gen.G", "win_rate": 0.65},
                },
            },
        }

    monkeypatch.setattr("betting_app.services.upcoming_inference_service.build_features_for_match", fake_build_features)

    # Test Bo1
    resp = client.post(
        "/matches/matchup",
        json={"team_a_name": "T1", "team_b_name": "Gen.G", "best_of": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["team_a_name"] == "T1"
    assert data["team_b_name"] == "Gen.G"
    assert data["best_of"] == 1
    assert data["map_prob_a"] == pytest.approx(0.666, abs=0.01)
    assert data["series_prob_a"] == data["map_prob_a"]
    assert data["team_comparison"]["team_a"] == {
        "canonical_name": "T1",
        "golgg_name": "T1",
        "confidence": 1.0,
        "source": "exact",
    }
    roster_a_player = data["roster_a"]["players"][0]
    assert roster_a_player["player_id"] == "t1-top"
    assert roster_a_player["player_name"] == "Zeus"
    assert roster_a_player["role"] == "TOP"
    assert roster_a_player["glicko_rating"] == 1825.0
    assert roster_a_player["glicko_rd"] == 65.0
    assert roster_a_player["games_played"] == 20
    assert data["roster_b"]["players"][0]["player_name"] == "Kiin"
    assert data["roster_b"]["players"][0]["glicko_rating"] is None

    # Test Bo3
    resp3 = client.post(
        "/matches/matchup",
        json={"team_a_name": "T1", "team_b_name": "Gen.G", "best_of": 3},
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3["best_of"] == 3
    # In Bo3, p > 0.5 expands further upward under binomial tail
    assert data3["series_prob_a"] > data3["map_prob_a"]
    assert len(received_kwargs) == 2
    assert all(kwargs["persist"] is False for kwargs in received_kwargs)


def test_synthetic_matchup_feature_build_does_not_upsert(monkeypatch: pytest.MonkeyPatch) -> None:
    from betting_app.services import upcoming_inference_service as inference

    persisted: list[dict] = []
    roster = {"players": [{"player_id": "1", "player_name": "Player"}] * 5}

    monkeypatch.setattr(inference, "golgg_name_from_id", lambda team_id: f"Team {team_id}")
    monkeypatch.setattr(inference, "load_team_ratings", lambda *_: {})
    monkeypatch.setattr(inference, "load_regional_adjustment", lambda *_: None)
    monkeypatch.setattr(inference, "rating_probabilities", lambda *_: {})
    monkeypatch.setattr(inference, "regional_adjustment_state", lambda *_: {})
    monkeypatch.setattr(inference, "load_w20", lambda *_: {"win_rate": 0.5})
    monkeypatch.setattr(inference, "load_last_roster", lambda *_: roster)
    monkeypatch.setattr(inference, "load_roster_player_ratings", lambda *_: {})
    monkeypatch.setattr(inference, "player_rating_probabilities", lambda *_: {})
    monkeypatch.setattr(inference, "latest_data_cutoff", lambda *_: None)
    monkeypatch.setattr(
        inference,
        "upsert_upcoming_features",
        lambda **kwargs: persisted.append(kwargs),
    )

    result = inference.build_features_for_match(
        {
            "id": 0,
            "team_a_name": "T1",
            "team_b_name": "Gen.G",
            "team_a_golgg_id": 1,
            "team_b_golgg_id": 2,
        },
        feature_version="test",
        ratings_version="test",
        w20_version="test",
        min_mapping_confidence=0.5,
        persist=False,
    )

    assert result["canonical_match_id"] == 0
    assert persisted == []


def test_player_ratings_preserve_roster_names_and_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    from betting_app.services import upcoming_inference_service as inference

    query: dict[str, object] = {}

    def fake_query_df(sql: str, params: tuple[object, ...]) -> pd.DataFrame:
        query["sql"] = sql
        query["params"] = params
        return pd.DataFrame(
            [{
                "rating_system": "gl",
                "entity_name": "Zeus",
                "normalized_entity_name": "golgg-123",
                "rating_value": 1825.0,
                "rd": 65.0,
                "sigma": 0.06,
                "games_played": 20,
                "last_match_at": "2026-09-01T12:00:00+00:00",
            }]
        )

    monkeypatch.setattr(inference, "query_df", fake_query_df)

    ratings = inference.load_roster_player_ratings(
        {
            "players": [{
                "player_id": "Zeus",
                "player_name": "Choi Hyeon-jun",
                "role": "TOP",
            }]
        },
        "test",
    )

    assert "LOWER(entity_name)" in str(query["sql"])
    assert "zeus" in query["params"]

    assert ratings["gl"]["players"][0]["player_id"] == "Zeus"
    assert ratings["gl"]["players"][0]["player_name"] == "Choi Hyeon-jun"
    assert ratings["gl"]["players"][0]["role"] == "TOP"
