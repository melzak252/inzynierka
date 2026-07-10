"""Artifact persistence for retrained models."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from betting_app.ml.training.candidates import build_estimator
from betting_app.ml.training.types import ModelCandidateSpec, TrainedModelArtifact, TrainingDataset
from betting_app.ml.training.walk_forward import dataset_to_matrix

DEFAULT_ARTIFACT_ROOT = Path("betting_app/models/ml")


def train_and_save_model(
    dataset: TrainingDataset,
    candidate: ModelCandidateSpec,
    *,
    model_name: str,
    model_version: str,
    metrics: dict[str, Any],
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
) -> TrainedModelArtifact:
    artifact_dir = artifact_root / model_name / model_version
    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / "model.joblib"
    metadata_path = artifact_dir / "metadata.json"

    x, y, feature_names = dataset_to_matrix(dataset)
    estimator = build_estimator(candidate)
    estimator.fit(x, y)
    joblib.dump({"estimator": estimator, "feature_names": feature_names}, model_path)

    metadata = {
        "model_name": model_name,
        "model_version": model_version,
        "candidate": {"name": candidate.name, "estimator_type": candidate.estimator_type, "params": candidate.params},
        "trained_at": datetime.now(UTC).isoformat(),
        "training_examples": dataset.size,
        "feature_count": len(feature_names),
        "feature_names": feature_names,
        "metrics": metrics,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return TrainedModelArtifact(
        model_name=model_name,
        model_version=model_version,
        artifact_path=str(model_path),
        metadata_path=str(metadata_path),
        feature_names=feature_names,
        metrics=metrics,
    )
