"""Tests for /api/predictions endpoint."""

import json

import pytest
from fastapi.testclient import TestClient

from betting_app.api.routers import matches as matches_router
from betting_app.core.db import get_session
from betting_app.services.upcoming_inference_service import (
    DEFAULT_FEATURE_VERSION,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_VERSION,
    DEFAULT_RATINGS_VERSION,
    register_operational_model,
    series_probability,
)
from betting_app.ml.model_lifecycle import RETIRED_PUBLIC_MODEL_NAME



class TestPredictions:
    def test_empty_returns_zero(self, client: TestClient):
        resp = client.get("/predictions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["signals"] == []


def test_ev_signals_exclude_retired_tabular_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from betting_app.api.routers import predictions as predictions_router

    def fake_query(_db, sql: str, params: dict[str, object]):
        assert "cp.model_name <> :retired_model_name" in sql
        assert params["retired_model_name"] == RETIRED_PUBLIC_MODEL_NAME
        return []

    monkeypatch.setattr(predictions_router, "query_df", fake_query)

    result = predictions_router.list_predictions(db=object())

    assert result.total == 0


def test_prediction_history_excludes_retired_tabular_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_query(_db, sql: str, params: dict[str, object]):
        if "SELECT id FROM canonical_matches" in sql:
            return [{"id": 1}]
        assert "model_name <> :retired_model_name" in sql
        assert params["retired_model_name"] == RETIRED_PUBLIC_MODEL_NAME
        return []

    monkeypatch.setattr(matches_router, "query_df", fake_query)

    assert matches_router.prediction_history(1, db=object()) == []


def test_regional_operational_artifact_is_immutable_and_versioned(
    client: TestClient,
) -> None:
    artifact_id = register_operational_model()

    with get_session() as session:
        row = session.execute(
            __import__("sqlalchemy").text(
                """
                SELECT model_name, model_version, feature_schema_json, model_params_json
                FROM model_artifacts
                WHERE id = :artifact_id
                """
            ),
            {"artifact_id": artifact_id},
        ).mappings().one()
    schema = json.loads(str(row["feature_schema_json"]))
    assert row["model_name"] == DEFAULT_MODEL_NAME
    assert row["model_version"] == DEFAULT_MODEL_VERSION
    assert schema["ratings_version"] == DEFAULT_RATINGS_VERSION
    assert schema["regional_projection"]["excluded_system"] == "gl"
    assert register_operational_model() == artifact_id

    with pytest.raises(ValueError, match="operational model contract"):
        register_operational_model(feature_version=DEFAULT_FEATURE_VERSION + "-other")


@pytest.mark.parametrize(
    ("map_probability", "best_of"),
    [
        (0.5, 1),
        (0.6, 3),
        (0.6, 5),
    ],
)
def test_operational_model_projects_map_probability_to_best_of_series(
    map_probability: float, best_of: int
) -> None:
    probability = series_probability(map_probability, best_of)
    assert 0.0 < probability < 1.0
    if best_of == 1:
        assert probability == pytest.approx(map_probability)
    else:
        assert probability > map_probability


@pytest.mark.parametrize(
    ("map_probability", "best_of"),
    [
        (0.01, 1),
        (0.01, 3),
        (0.25, 5),
        (0.60, 7),
        (0.99, 7),
    ],
)
def test_series_projection_is_side_symmetric(
    map_probability: float, best_of: int
) -> None:
    assert series_probability(map_probability, best_of) == pytest.approx(
        1.0 - series_probability(1.0 - map_probability, best_of)
    )


@pytest.mark.parametrize("best_of", [0, 2, 4, 6, 9, "not-a-format"])
def test_series_projection_rejects_unsupported_formats(best_of: object) -> None:
    with pytest.raises(ValueError, match="best_of must be one of 1, 3, 5, 7"):
        series_probability(0.6, best_of)


def test_match_predict_route_uses_operational_model(monkeypatch: pytest.MonkeyPatch) -> None:
    match = {
        "id": 17,
        "team_a_name": "Team A",
        "team_b_name": "Team B",
        "best_of": 3,
    }
    calls: list[dict] = []

    def fake_query_df(_db, sql: str, _params=None):
        if "SELECT * FROM canonical_matches" in sql:
            return [match]
        if "SELECT prob_a, prob_b" in sql:
            return []
        pytest.fail(f"unexpected query: {sql}")

    def fake_predict(payload: dict, **kwargs):
        calls.append({"match": payload, **kwargs})
        return {
            "prob_a": 0.648,
            "prob_b": 0.352,
            "diagnostics": {"best_of": 3},
        }

    monkeypatch.setattr(matches_router, "query_df", fake_query_df)
    monkeypatch.setattr(matches_router, "_load_roster_overrides", lambda _match_id: {})
    monkeypatch.setattr(matches_router, "predict_operational_match", fake_predict)
    monkeypatch.setattr(matches_router, "generate_hybrid_predictions", lambda: [])

    response = matches_router.predict_match(17, db=object())

    assert calls == [{"match": match, "team_a_roster_override": None, "team_b_roster_override": None}]
    assert response.status == "ok"
    assert response.model_name == DEFAULT_MODEL_NAME
    assert response.model_version == DEFAULT_MODEL_VERSION
    assert response.prob_a == pytest.approx(0.648)
