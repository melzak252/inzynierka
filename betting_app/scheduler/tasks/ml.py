"""ML/retraining scheduler tasks."""

import logging
from datetime import datetime

from .scrape import _run_module

logger = logging.getLogger(__name__)


def run_weekly_retraining() -> dict:
    """Run the production ML weekly retraining pipeline.

    The pipeline trains candidate models on historical finished matches,
    performs walk-forward validation, saves an immutable dataset/model artifact,
    and registers the model version as a shadow candidate.
    """
    logger.info("Starting weekly ML retraining")
    start = datetime.utcnow()

    success = _run_module(
        "betting_app.ml.pipelines.weekly_retrain_cli",
        args=[
            "--model-name",
            "Operational-Retrained-Tabular",
            "--status-on-success",
            "shadow",
            "--json",
        ],
        timeout=1800,
    )

    duration = (datetime.utcnow() - start).total_seconds()
    logger.info(f"Weekly ML retraining: {'OK' if success else 'FAIL'} ({duration:.1f}s)")

    return {
        "success": success,
        "duration_s": duration,
        "timestamp": start.isoformat(),
    }


def run_shadow_inference() -> dict:
    """Run inference for registered shadow ML models.

    This does not promote or replace the current production/thesis model. It
    only writes active `canonical_predictions` rows for models registered with
    `status='shadow'`, so they become visible in match detail/history views.
    """
    logger.info("Starting shadow ML inference")
    start = datetime.utcnow()

    success = _run_module(
        "betting_app.ml.inference.cli",
        args=["--status", "shadow", "--json"],
        timeout=600,
    )

    duration = (datetime.utcnow() - start).total_seconds()
    logger.info(f"Shadow ML inference: {'OK' if success else 'FAIL'} ({duration:.1f}s)")

    return {
        "success": success,
        "duration_s": duration,
        "timestamp": start.isoformat(),
    }


def run_thesis_model_healthcheck() -> dict:
    """Run a read-only rolling evaluation of the current thesis model.

    The healthcheck intentionally uses ``--no-register``: it should verify
    recent model-vs-market quality and emit logs, not create/promote model
    versions.  This gives the scheduler a lightweight recurring guardrail for
    the production model without affecting inference state.
    """
    logger.info("Starting thesis model healthcheck")
    start = datetime.utcnow()

    success = _run_module(
        "betting_app.ml.pipelines.evaluate_existing_model",
        args=[
            "--model-name",
            "Sym-Cal LR-ElasticNet-W20-Binomial",
            "--model-version",
            "exp-039",
            "--days-back",
            "90",
            "--no-register",
            "--json",
        ],
        timeout=900,
    )

    duration = (datetime.utcnow() - start).total_seconds()
    logger.info(f"Thesis model healthcheck: {'OK' if success else 'FAIL'} ({duration:.1f}s)")

    return {
        "success": success,
        "duration_s": duration,
        "timestamp": start.isoformat(),
    }
