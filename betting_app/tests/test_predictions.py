"""Tests for /api/predictions endpoint."""

import json

import pytest
from fastapi.testclient import TestClient

from betting_app.core.db import get_session
from betting_app.services.upcoming_inference_service import (
    DEFAULT_FEATURE_VERSION,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_VERSION,
    DEFAULT_RATINGS_VERSION,
    register_operational_model,
)


class TestPredictions:
    def test_empty_returns_zero(self, client: TestClient):
        resp = client.get("/predictions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["signals"] == []


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
