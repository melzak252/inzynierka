"""Weekly retraining pipeline for production candidate models.

This is intentionally a plain-Python pipeline: it can be executed directly in
Docker today and later wrapped as Kedro nodes without changing the core logic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from betting_app.core.db import get_session
from betting_app.ml.registry.repository import EvaluationRunRecord, ModelVersionRecord, record_evaluation_run, register_model_version
from betting_app.ml.training.artifacts import DEFAULT_ARTIFACT_ROOT, train_and_save_model
from betting_app.ml.training.candidates import default_candidate_specs
from betting_app.ml.training.features import load_training_dataset
from betting_app.ml.training.types import CandidateEvaluation, ModelCandidateSpec, TrainedModelArtifact
from betting_app.ml.training.walk_forward import evaluate_candidate_walk_forward, select_best_evaluation


@dataclass(frozen=True)
class WeeklyRetrainConfig:
    model_name: str = "Operational-Retrained-Tabular"
    model_version: str | None = None
    feature_version: str | None = None
    ratings_version: str | None = None
    days_back: int | None = None
    min_features: int = 5
    min_train_size: int = 80
    test_size: int = 20
    step_size: int | None = None
    artifact_root: str = str(DEFAULT_ARTIFACT_ROOT)
    register_model: bool = True
    status_on_success: str = "candidate"
    run_type: str = "weekly_retrain"


@dataclass(frozen=True)
class WeeklyRetrainResult:
    artifact: TrainedModelArtifact
    best_evaluation: CandidateEvaluation
    all_evaluations: list[CandidateEvaluation]
    evaluation_run_id: str
    dataset_size: int
    feature_count: int


def _default_model_version() -> str:
    return datetime.now(UTC).strftime("weekly-%Y%m%d-%H%M%S")


def _dataset_hash(example_ids: list[int], feature_names: list[str]) -> str:
    payload = json.dumps({"example_ids": example_ids, "feature_names": feature_names}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _evaluation_to_metrics(evaluation: CandidateEvaluation) -> dict[str, Any]:
    return {
        "candidate_name": evaluation.candidate.name,
        "estimator_type": evaluation.candidate.estimator_type,
        "candidate_params": evaluation.candidate.params,
        "folds": len(evaluation.folds),
        "mean_log_loss": round(evaluation.mean_log_loss, 6),
        "mean_brier": round(evaluation.mean_brier, 6),
        "mean_accuracy": round(evaluation.mean_accuracy, 6),
        "fold_results": [asdict(fold) for fold in evaluation.folds],
    }


def run_weekly_retrain_pipeline(
    config: WeeklyRetrainConfig | None = None,
    *,
    candidate_specs: list[ModelCandidateSpec] | None = None,
    session: Session | None = None,
) -> WeeklyRetrainResult:
    """Train candidate models, pick best walk-forward result and save artifact."""
    cfg = config or WeeklyRetrainConfig()
    model_version = cfg.model_version or _default_model_version()
    own_session = session is None
    sess = session or get_session()
    try:
        dataset = load_training_dataset(
            feature_version=cfg.feature_version,
            ratings_version=cfg.ratings_version,
            days_back=cfg.days_back,
            min_features=cfg.min_features,
        )
        if dataset.size == 0:
            raise ValueError("Training dataset is empty")

        specs = candidate_specs or default_candidate_specs()
        evaluations = [
            evaluate_candidate_walk_forward(
                dataset,
                spec,
                min_train_size=cfg.min_train_size,
                test_size=cfg.test_size,
                step_size=cfg.step_size,
            )
            for spec in specs
        ]
        best = select_best_evaluation(evaluations)
        metrics: dict[str, Any] = {
            "dataset_size": dataset.size,
            "feature_count": len(dataset.feature_names),
            "dataset_hash": _dataset_hash([ex.canonical_match_id for ex in dataset.examples], dataset.feature_names),
            "best_candidate": _evaluation_to_metrics(best),
            "candidates": [_evaluation_to_metrics(ev) for ev in evaluations],
        }

        artifact = train_and_save_model(
            dataset,
            best.candidate,
            model_name=cfg.model_name,
            model_version=model_version,
            metrics=metrics,
            artifact_root=Path(cfg.artifact_root),
        )

        if cfg.register_model:
            register_model_version(
                ModelVersionRecord(
                    model_name=cfg.model_name,
                    model_version=model_version,
                    status=cfg.status_on_success,
                    artifact_path=artifact.artifact_path,
                    feature_version=cfg.feature_version,
                    dataset_hash=str(metrics["dataset_hash"]),
                    metrics=metrics,
                    notes="Auto-registered by weekly retraining pipeline",
                ),
                session=sess,
            )

        run = record_evaluation_run(
            EvaluationRunRecord(
                model_name=cfg.model_name,
                model_version=model_version,
                run_type=cfg.run_type,
                status="completed",
                config=asdict(cfg),
                metrics=metrics,
                notes="Weekly retraining candidate selection",
            ),
            session=sess,
        )
        return WeeklyRetrainResult(
            artifact=artifact,
            best_evaluation=best,
            all_evaluations=evaluations,
            evaluation_run_id=run.id,
            dataset_size=dataset.size,
            feature_count=len(dataset.feature_names),
        )
    finally:
        if own_session:
            sess.close()
