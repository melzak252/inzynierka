"""Tournament Simulation Caching Service.

Pre-computes and caches Monte Carlo tournament simulations across standardized
path depths (5,000, 10,000, 20,000, and 100,000 iterations) using Consolidated A1.
Provides O(1) instant retrieval for API requests and on-demand recalculation.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from betting_app.services.liquipedia_bracket_service import LiquipediaBracketService
from betting_app.services.tournament_service import (
    SUPPORTED_BRACKETS,
    TournamentSimulator,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data" / "tournament_sim_cache"
DEFAULT_DEPTHS = (5000, 10000, 20000, 100000)


def _ensure_cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def get_cache_file(tournament_id: str) -> Path:
    """Return the filesystem path for a tournament simulation cache file."""
    return _ensure_cache_dir() / f"{tournament_id}.json"


def get_cached_simulation(
    tournament_id: str,
    n_simulations: int = 10000,
) -> dict[str, Any] | None:
    """Load cached tournament simulation from disk.

    Returns the simulation matching the requested path depth if present,
    or the closest available depth. Returns None if cache does not exist or is corrupt.
    """
    cache_path = get_cache_file(tournament_id)
    if not cache_path.is_file():
        return None

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        depths_data = data.get("depths", {})
        str_key = str(n_simulations)

        # Check exact depth match
        if str_key in depths_data:
            result = dict(depths_data[str_key])
            result["cached"] = True
            result["cached_at"] = data.get("cached_at")
            result["available_depths"] = [int(k) for k in depths_data.keys() if k.isdigit()]
            return result

        # Fallback to closest available depth
        if depths_data:
            available = sorted([int(k) for k in depths_data.keys() if k.isdigit()])
            closest = min(available, key=lambda d: abs(d - n_simulations))
            result = dict(depths_data[str(closest)])
            result["cached"] = True
            result["cached_at"] = data.get("cached_at")
            result["available_depths"] = available
            result["depth_requested"] = n_simulations
            result["depth_served"] = closest
            return result

        # Fallback to legacy single-run cache
        if "standings" in data:
            result = dict(data)
            result["cached"] = True
            return result

    except Exception as exc:
        logger.warning("Failed to read simulation cache for %s: %s", tournament_id, exc)

    return None


def recalculate_and_cache(
    tournament_id: str,
    depths: Sequence[int] = DEFAULT_DEPTHS,
    manual_overrides: dict[str, str] | None = None,
    use_a1: bool = True,
    force_sync: bool = False,
    calibrate: bool = True,
) -> dict[str, Any]:
    """Run Monte Carlo simulation across multiple path depths using A1 and update the cache."""
    builder = SUPPORTED_BRACKETS.get(tournament_id)
    if not builder:
        raise ValueError(f"Tournament {tournament_id} not supported")

    # Sync bracket state
    service = LiquipediaBracketService()
    sync_res = service.sync_bracket(tournament_id, source="auto", force=force_sync)
    bracket = sync_res.get("bracket") or builder()

    # Determine tournament tier
    region = getattr(bracket, "region", "LEC")
    comp_tier = "major" if region in {"LCK", "LPL", "LEC", "LCS"} else "international"

    simulator = TournamentSimulator(use_a1=use_a1, competition_tier=comp_tier, calibrate=calibrate)

    depths_results: dict[str, Any] = {}
    primary_result: dict[str, Any] | None = None

    for depth in depths:
        clamped_depth = min(max(int(depth), 100), 100000)
        sim_res = simulator.simulate(
            bracket,
            n_simulations=clamped_depth,
            manual_overrides=manual_overrides,
        )
        sim_res["source"] = sync_res.get("source", "curated")
        sim_res["status"] = sync_res.get("status", "ready")
        sim_res["synced_at"] = sync_res.get("synced_at")
        sim_res["updated_matches"] = sync_res.get("updated_matches", 0)

        depths_results[str(clamped_depth)] = sim_res
        if primary_result is None or clamped_depth == 10000:
            primary_result = sim_res

    now_iso = datetime.now(timezone.utc).isoformat()
    cache_payload = {
        "tournament_id": tournament_id,
        "cached_at": now_iso,
        "probability_model": "Consolidated-A1" if use_a1 else "gl_logistic_map_iid_series",
        "has_manual_overrides": bool(manual_overrides),
        "available_depths": list(depths),
        "depths": depths_results,
    }

    cache_file = get_cache_file(tournament_id)
    cache_file.write_text(json.dumps(cache_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Saved multi-depth simulation cache for %s to %s", tournament_id, cache_file)

    if primary_result is None:
        primary_result = list(depths_results.values())[0]

    out = dict(primary_result)
    out["cached"] = False
    out["cached_at"] = now_iso
    out["available_depths"] = list(depths)
    return out
