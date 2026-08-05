"""Maintenance / heavy-cycle tasks."""

import logging
from datetime import datetime

from .scrape import _run_module

logger = logging.getLogger(__name__)


def refresh_golgg() -> dict:
    """Refresh GolGG data (direct scrape → DB, no JSON cache)."""
    logger.info("Starting GolGG direct refresh")
    start = datetime.utcnow()

    # Scan all tournament lists and refresh recent existing match metadata, not only
    # brand-new match IDs. This prevents in-progress series snapshots (e.g. 1-1 draw
    # mid-Bo5) from staying permanently stale after the match finishes.
    success = _run_module(
        "betting_app.scripts.refresh_golgg_direct",
        args=["--refresh-matches", "--refresh-existing-days", "45"],
        timeout=900,
    )
    duration = (datetime.utcnow() - start).total_seconds()
    
    roster_success = _run_module("betting_app.scripts.refresh_current_team_rosters", timeout=300) if success else False
    logger.info(f"GolGG direct refresh: {'OK' if success else 'FAIL'} ({duration:.1f}s), current rosters: {'OK' if roster_success else 'FAIL'}")
    
    return {"success": success and roster_success, "duration_s": duration, "current_rosters": roster_success}


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
    
    success = _run_module("betting_app.scripts.rebuild_w20_features", timeout=600)
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


def backfill_expired_matches() -> dict:
    """Map expired canonical matches to existing GOL.GG results.

    Runs backfill_finished_expired_matches() from refresh_golgg_direct,
    which finds completed, not-yet-mapped GOL.GG matches in the date range
    covered by currently expired canonical matches, maps them, and marks
    matched canonical rows as `finished` with winners.
    """
    logger.info("Starting expired match backfill to GOL.GG")
    start = datetime.utcnow()

    success = _run_module(
        "betting_app.scripts.refresh_golgg_direct",
        args=["--backfill-finished"],
        timeout=600,
    )
    duration = (datetime.utcnow() - start).total_seconds()

    logger.info(f"Expired match backfill: {'OK' if success else 'FAIL'} ({duration:.1f}s)")

    return {"success": success, "duration_s": duration}


def run_horizon_bootstrap() -> dict:
    """Run the monthly block bootstrap analysis for prediction horizons.

    Runs horizon_block_bootstrap.py which compares Thesis and Hybrid models
    vs Bookmaker across 6 time horizons using 10,000 monthly block resamples.
    Results are cached to /app/docs/assets/horizon_block_bootstrap/.
    """
    logger.info("Starting horizon bootstrap analysis")
    start = datetime.utcnow()

    success = _run_module(
        "betting_app.scripts.horizon_block_bootstrap",
        timeout=600,
    )
    duration = (datetime.utcnow() - start).total_seconds()

    logger.info(f"Horizon bootstrap: {'OK' if success else 'FAIL'} ({duration:.1f}s)")

    return {"success": success, "duration_s": duration}


def refresh_model_analysis_cache() -> dict:
    """Precompute Model Analysis JSON payloads for the frontend.

    The Model Analysis endpoints are intentionally cache-first because the raw
    calculations scan many historical odds snapshots and model predictions.
    This task refreshes the default 90-day view once per day.
    """
    logger.info("Starting Model Analysis cache refresh")
    start = datetime.utcnow()

    success = _run_module(
        "betting_app.scripts.refresh_model_analysis_cache",
        args=["--days-back", "90", "--min-matches-per-bin", "10", "--max-odds-age-hours", "4", "--tax-rate", "0.12", "--min-ev", "0"],
        timeout=900,
    )
    duration = (datetime.utcnow() - start).total_seconds()

    logger.info(f"Model Analysis cache refresh: {'OK' if success else 'FAIL'} ({duration:.1f}s)")

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
