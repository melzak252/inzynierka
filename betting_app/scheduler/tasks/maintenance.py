"""Maintenance / heavy-cycle tasks."""

import logging
from datetime import datetime

from .scrape import _run_module

logger = logging.getLogger(__name__)


def refresh_golgg() -> dict:
    """Refresh GolGG data (scrape + import)."""
    logger.info("Starting GolGG refresh")
    start = datetime.utcnow()
    
    steps = {
        "refresh": _run_module("betting_app.scripts.refresh_golgg_results", timeout=600),
        "import": _run_module("betting_app.scripts.import_golgg_to_db", timeout=300),
    }
    
    duration = (datetime.utcnow() - start).total_seconds()
    all_ok = all(steps.values())
    
    logger.info(f"GolGG refresh: {'OK' if all_ok else 'FAIL'} ({duration:.1f}s)")
    
    return {
        "success": all_ok,
        "steps": steps,
        "duration_s": duration,
    }


def rebuild_ratings() -> dict:
    """Rebuild team Elo ratings.
    
    NOTE: Full rebuild processes ~40k matches and takes ~2 hours.
    Timeout set to 7200s (2h) to allow completion.
    """
    logger.info("Rebuilding team ratings")
    start = datetime.utcnow()
    
    success = _run_module("betting_app.scripts.rebuild_ratings", timeout=7200)
    duration = (datetime.utcnow() - start).total_seconds()
    
    logger.info(f"Ratings rebuild: {'OK' if success else 'FAIL'} ({duration:.1f}s)")
    
    return {"success": success, "duration_s": duration}


def rebuild_rolling_features() -> dict:
    """Rebuild W20 rolling features."""
    logger.info("Rebuilding rolling features")
    start = datetime.utcnow()
    
    success = _run_module("betting_app.scripts.rebuild_w20_features", timeout=300)
    duration = (datetime.utcnow() - start).total_seconds()
    
    logger.info(f"Features rebuild: {'OK' if success else 'FAIL'} ({duration:.1f}s)")
    
    return {"success": success, "duration_s": duration}


def run_heavy_cycle() -> dict:
    """Run the full heavy maintenance cycle:
    1. Refresh GolGG
    2. Rebuild ratings
    3. Rebuild rolling features
    """
    logger.info("Starting heavy maintenance cycle")
    start = datetime.utcnow()
    
    results = {
        "golgg": refresh_golgg(),
        "ratings": rebuild_ratings(),
        "features": rebuild_rolling_features(),
    }
    
    duration = (datetime.utcnow() - start).total_seconds()
    all_ok = all(r.get("success", False) for r in results.values())
    
    logger.info(f"Heavy cycle: {'OK' if all_ok else 'PARTIAL'} ({duration:.1f}s)")
    
    return {
        "success": all_ok,
        "results": results,
        "duration_s": duration,
    }
