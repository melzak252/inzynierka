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
    series_probability,
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
        row = (
            session.execute(
                __import__("sqlalchemy").text("""
                SELECT model_name, model_version, feature_schema_json, model_params_json
                FROM model_artifacts
                WHERE id = :artifact_id
                """),
                {"artifact_id": artifact_id},
            )
            .mappings()
            .one()
        )
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


def test_backfill_detects_reversed_team_alignment() -> None:
    from betting_app.scripts.backfill_operational_predictions import (
        _is_reversed_mapping,
    )

    assert not _is_reversed_mapping("Dplus", "DRX", "Dplus KIA", "Kiwoom DRX")
    assert _is_reversed_mapping("GIANTX", "Vitality", "Team Vitality", "GIANTX")
    assert _is_reversed_mapping(
        "BRION", "Hanwha Life", "Hanwha Life Esports", "HANJIN BRION"
    )
    assert not _is_reversed_mapping("Gen.G", "T1", "Gen.G", "T1")
    assert _is_reversed_mapping("T1", "Gen.G", "Gen.G", "T1")
