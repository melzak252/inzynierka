"""Maintenance / heavy-cycle tasks."""

import logging
from datetime import datetime

from .scrape import _run_module

logger = logging.getLogger(__name__)


def refresh_golgg() -> dict:
    """Refresh GolGG data (direct scrape → DB, no JSON cache)."""
    logger.info("Starting GolGG direct refresh")
    start = datetime.utcnow()
    
    success = _run_module("betting_app.scripts.refresh_golgg_direct", timeout=900)
    duration = (datetime.utcnow() - start).total_seconds()
    
    logger.info(f"GolGG direct refresh: {'OK' if success else 'FAIL'} ({duration:.1f}s)")
    
    return {"success": success, "duration_s": duration}


def rebuild_ratings() -> dict:
    """Incrementally update Elo/Glicko/etc. ratings after GOL.GG refresh."""
    logger.info("Updating ratings incrementally")
    start = datetime.utcnow()

    success = _run_module("betting_app.scripts.rebuild_ratings", timeout=900)
    duration = (datetime.utcnow() - start).total_seconds()

    logger.info(f"Ratings incremental update: {'OK' if success else 'FAIL'} ({duration:.1f}s)")

    return {"success": success, "duration_s": duration}


def rebuild_rolling_features() -> dict:
    """Rebuild W20 rolling features."""
    logger.info("Rebuilding rolling features")
    start = datetime.utcnow()
    
    success = _run_module("betting_app.scripts.rebuild_w20_features", timeout=300)
    duration = (datetime.utcnow() - start).total_seconds()
    
    logger.info(f"Features rebuild: {'OK' if success else 'FAIL'} ({duration:.1f}s)")
    
    return {"success": success, "duration_s": duration}


def expire_matches(grace_hours: int = 3) -> dict:
    """Expire old matches whose start time has passed.

    Marks canonical_matches with status='upcoming' as 'expired' when
    start_time_normalized < NOW() - grace_hours.
    """
    logger.info(f"Expiring old matches (grace_hours={grace_hours})")
    start = datetime.utcnow()

    success = _run_module(
        "betting_app.scripts.expire_old_matches",
        args=["--grace-hours", str(grace_hours)],
        timeout=120,
    )
    duration = (datetime.utcnow() - start).total_seconds()

    logger.info(f"Match expiration: {'OK' if success else 'FAIL'} ({duration:.1f}s)")

    return {"success": success, "duration_s": duration}


def expire_stale_matches(stale_seen_hours: int = 6) -> dict:
    """Expire matches that haven't been seen by scrapers recently.

    Marks canonical_matches with status='upcoming' as 'expired' when
    ALL their upcoming_matches have last_seen_at older than stale_seen_hours.
    This catches cancelled/postponed matches that disappeared from scrapers.
    """
    logger.info(f"Expiring stale-seen matches (stale_seen_hours={stale_seen_hours})")
    start = datetime.utcnow()

    success = _run_module(
        "betting_app.scripts.expire_old_matches",
        args=["--stale-seen-hours", str(stale_seen_hours)],
        timeout=120,
    )
    duration = (datetime.utcnow() - start).total_seconds()

    logger.info(f"Stale-seen match expiration: {'OK' if success else 'FAIL'} ({duration:.1f}s)")

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
