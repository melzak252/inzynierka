"""Prediction pipeline tasks."""

import logging
from datetime import UTC, datetime

from .scrape import _run_module

logger = logging.getLogger(__name__)


def rematch_canonical() -> bool:
    """Rematch scraped matches to canonical matches."""
    logger.info("Rematching canonical matches")
    return _run_module(
        "betting_app.scripts.rematch_canonical_matches",
        args=["--no-overview"],
        timeout=300,
    )


def run_prediction_pipeline() -> dict:
    """Run the full prediction pipeline:
    1. Rematch canonical matches
    2. Build features + predict + hybrid + EV signals
    """
    logger.info("Starting prediction pipeline")
    start = datetime.now(UTC)
    
    rematch_ok = rematch_canonical()
    if rematch_ok:
        predict_ok = _run_module(
            "betting_app.scripts.run_upcoming_prediction_pipeline",
            args=["--include-partial", "--operational-hybrid"],
            timeout=900,
        )
    else:
        logger.error("Skipping prediction because canonical rematching failed")
        predict_ok = False

    steps = {
        "rematch": rematch_ok,
        "predict": predict_ok,
    }
    duration = (datetime.now(UTC) - start).total_seconds()
    all_ok = all(steps.values())

    logger.info(f"Prediction pipeline: {'OK' if all_ok else 'PARTIAL'} ({duration:.1f}s)")

    return {
        "success": all_ok,
        "steps": steps,
        "duration_s": duration,
        "error": "Canonical rematching failed" if not rematch_ok else None,
    }
