from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from betting_app.core.db import connect, dispose_engine, init_db
from betting_app.services.upcoming_inference_service import register_operational_model


@pytest.fixture
def model_contract_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    database = tmp_path / "model-contract.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    dispose_engine()
    init_db()
    try:
        yield
    finally:
        dispose_engine()


def test_operational_model_version_is_bound_to_one_feature_and_rating_contract(
    model_contract_db: None,
) -> None:
    artifact_id = register_operational_model(
        model_version="regional-contract-test",
        feature_version="player-team-ratings-w20-v0.3",
        ratings_version="ratings-v2",
    )

    assert register_operational_model(
        model_version="regional-contract-test",
        feature_version="player-team-ratings-w20-v0.3",
        ratings_version="ratings-v2",
    ) == artifact_id
    with pytest.raises(ValueError, match="bound to"):
        register_operational_model(
            model_version="regional-contract-test",
            feature_version="player-team-ratings-w20-v0.2",
            ratings_version="latest-full",
        )

    with connect() as connection:
        row = connection.execute(
            "SELECT feature_schema_json FROM model_artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
    assert row is not None
    schema = json.loads(str(row["feature_schema_json"]))
    assert schema["feature_version"] == "player-team-ratings-w20-v0.3"
    assert schema["ratings_version"] == "ratings-v2"
    assert schema["competition_calibration"] == "shared_family_tier_posterior"
