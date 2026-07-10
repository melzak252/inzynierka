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
