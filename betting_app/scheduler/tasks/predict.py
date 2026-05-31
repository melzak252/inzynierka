"""Prediction pipeline tasks."""

import logging
from datetime import datetime

from .scrape import _run_module

logger = logging.getLogger(__name__)


def rematch_canonical() -> bool:
    """Rematch scraped matches to canonical matches."""
    logger.info("Rematching canonical matches")
    return _run_module("betting_app.scripts.rematch_canonical", timeout=120)


def run_prediction_pipeline() -> dict:
    """Run the full prediction pipeline:
    1. Rematch canonical matches
    2. Run predictions
    3. List predictions
    """
    logger.info("Starting prediction pipeline")
    start = datetime.utcnow()
    
    steps = {
        "rematch": rematch_canonical(),
        "predict": _run_module("betting_app.scripts.predict", timeout=180),
        "list_predictions": _run_module("betting_app.scripts.list_predictions", timeout=60),
    }
    
    duration = (datetime.utcnow() - start).total_seconds()
    all_ok = all(steps.values())
    
    logger.info(f"Prediction pipeline: {'OK' if all_ok else 'PARTIAL'} ({duration:.1f}s)")
    
    return {
        "success": all_ok,
        "steps": steps,
        "duration_s": duration,
    }
