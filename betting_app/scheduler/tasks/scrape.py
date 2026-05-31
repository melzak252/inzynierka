"""Scraping tasks for all bookmakers."""

import logging
import subprocess
import sys
from datetime import datetime

logger = logging.getLogger(__name__)

BOOKMAKERS = ("sts", "betclic", "superbet", "efortuna", "betfan", "totalbet", "lebull")
HEADLESS_BOOKMAKERS = {"betclic", "superbet", "efortuna", "betfan"}


def _run_module(module: str, args: list[str] | None = None, timeout: int = 300) -> bool:
    """Run a Python module as subprocess. Returns True on success."""
    cmd = [sys.executable, "-m", module]
    if args:
        cmd.extend(args)
    
    logger.info(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.error(f"Module {module} failed (rc={result.returncode}): {result.stderr[:500]}")
            return False
        if result.stdout:
            logger.info(f"Output: {result.stdout[:300]}")
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"Module {module} timed out after {timeout}s")
        return False
    except Exception as e:
        logger.error(f"Module {module} error: {e}")
        return False


def scrape_bookmaker(bookmaker: str) -> dict:
    """Scrape odds from a single bookmaker.
    
    Returns dict with status info.
    """
    logger.info(f"Starting scrape for: {bookmaker}")
    start = datetime.utcnow()
    
    headless = "--headless" if bookmaker in HEADLESS_BOOKMAKERS else ""
    args = ["--bookmaker", bookmaker]
    if headless:
        args.append(headless)
    
    success = _run_module("betting_app.scripts.scrape_odds", args, timeout=300)
    
    duration = (datetime.utcnow() - start).total_seconds()
    logger.info(f"Scrape {bookmaker}: {'OK' if success else 'FAIL'} ({duration:.1f}s)")
    
    return {
        "bookmaker": bookmaker,
        "success": success,
        "duration_s": duration,
        "timestamp": start.isoformat(),
    }


def scrape_all() -> dict:
    """Scrape all bookmakers sequentially."""
    logger.info("Starting full scrape cycle")
    start = datetime.utcnow()
    results = []
    
    for bk in BOOKMAKERS:
        result = scrape_bookmaker(bk)
        results.append(result)
    
    success_count = sum(1 for r in results if r["success"])
    duration = (datetime.utcnow() - start).total_seconds()
    
    logger.info(f"Full scrape done: {success_count}/{len(BOOKMAKERS)} OK ({duration:.1f}s)")
    
    return {
        "total": len(BOOKMAKERS),
        "success": success_count,
        "failed": len(BOOKMAKERS) - success_count,
        "results": results,
        "duration_s": duration,
    }
