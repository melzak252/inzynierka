import pytest
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
                "ratings": {
                    "probabilities": {"consensus": 0.65},
                    "team_a": {"gl": {"rating_value": 1850.0, "rd": 70.0}},
                    "team_b": {"gl": {"rating_value": 1700.0, "rd": 75.0}},
                },
                "player_ratings": {
                    "probabilities": {"consensus": 0.68},
                    "team_a": {"gl": {"avg_rating_value": 1820.0, "avg_rd": 65.0, "players": []}},
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
