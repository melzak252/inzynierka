"""Router: /api/timing — odds timing analysis for betting strategy.

Key metrics:
  - Fixed 2-hour time buckets (0-2h, 2-4h, 4-6h, ..., up to 72h+)
  - % deviation from closing odds (last pre-match snapshot)
  - Shows whether earlier odds are better/worse than closing
  - Convergence pattern analysis
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from betting_app.api.deps import get_db, query_df

router = APIRouter(prefix="/timing", tags=["timing"])


def _parse_dt(val: Any) -> datetime | None:
    """Parse datetime from various formats."""
    if val is None:
        return None
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=UTC)
        return val
    return None


def _align(
    n_a: str, n_b: str,
    raw_a: str, raw_b: str,
    odds_a: float | None, odds_b: float | None,
) -> tuple[float, float] | None:
    """Align odds to canonical sides."""
    from betting_app.services.canonical_match_service import align_snapshot_odds
    aligned = align_snapshot_odds(n_a, n_b, raw_a, raw_b, odds_a, odds_b)
    if aligned and aligned[0] and aligned[1]:
        return (float(aligned[0]), float(aligned[1]))
    return None


@router.get("/analysis")
def timing_analysis(
    days_back: int = 60,
    min_snapshots: int = 2,
    db=Depends(get_db),
):
    """Analyze odds movement relative to closing odds.

    For each finished/expired match, finds the closing odds (last snapshot
    before match start) and measures how earlier odds deviated from closing.
    Results are grouped into fixed 2-hour time buckets.

    Returns:
      - time_buckets: avg % deviation from closing per 2h window
      - drift_summary: convergence/divergence pattern
      - best_window: most favorable betting window
    """
    now = datetime.now(UTC)
    cutoff = (now - timedelta(days=days_back)).isoformat(timespec="seconds")

    # --- 1. Get finished/expired matches ---
    matches = query_df(
        db,
        """
        SELECT cm.id, cm.start_time_normalized,
               cm.normalized_team_a, cm.normalized_team_b
        FROM canonical_matches cm
        WHERE cm.status IN ('finished', 'completed', 'expired')
          AND cm.start_time_normalized IS NOT NULL
          AND cm.start_time_normalized > :cutoff
        ORDER BY cm.start_time_normalized DESC
        LIMIT 500
        """,
        {"cutoff": cutoff},
    )
    if not matches:
        return _empty_result()

    match_map = {m["id"]: m for m in matches}
    match_ids = list(match_map.keys())

    # --- 2. Get all odds snapshots for these matches ---
    placeholders = ",".join(f":mid{i}" for i in range(len(match_ids)))
    params: dict[str, Any] = {f"mid{i}": mid for i, mid in enumerate(match_ids)}

    snapshots = query_df(
        db,
        f"""
        SELECT os.canonical_match_id, os.scraped_at,
               os.odds_a, os.odds_b,
               os.raw_team_a, os.raw_team_b,
               b.name AS bookmaker
        FROM odds_snapshots os
        JOIN bookmakers b ON b.id = os.bookmaker_id
        WHERE os.canonical_match_id IN ({placeholders})
          AND os.market_type = 'match_winner'
          AND COALESCE(os.is_live, 0) = 0
          AND os.odds_a IS NOT NULL
          AND os.odds_b IS NOT NULL
        ORDER BY os.canonical_match_id, os.scraped_at
        """,
        params,
    )

    # Group by match
    match_snaps: dict[int, list[dict]] = {}
    for s in snapshots:
        mid = s["canonical_match_id"]
        match_snaps.setdefault(mid, []).append(s)

    # --- 3. Process each match ---
    BUCKET_SIZE = 2  # hours
    buckets_raw: dict[str, list[dict]] = {}
    matches_with_data = 0

    for mid in match_ids:
        m = match_map.get(mid)
        s_list = match_snaps.get(mid)
        if not m or not s_list or len(s_list) < min_snapshots:
            continue

        match_start = _parse_dt(m.get("start_time_normalized"))
        if not match_start:
            continue

        n_a = str(m.get("normalized_team_a") or "")
        n_b = str(m.get("normalized_team_b") or "")

        # Parse and filter pre-match only
        pre_match: list[tuple[float, dict]] = []
        for s in s_list:
            st = _parse_dt(s["scraped_at"])
            if not st:
                continue
            hours_before = (match_start - st).total_seconds() / 3600.0
            if hours_before < 0:
                continue
            pre_match.append((hours_before, s))

        if len(pre_match) < min_snapshots:
            continue

        # Sort by hours_before ascending (closest to match first)
        pre_match.sort(key=lambda x: x[0])

        # --- Closing odds = last snapshot before match ---
        closing_hours, closing_snap = pre_match[0]
        closing_aligned = _align(
            n_a, n_b,
            str(closing_snap.get("raw_team_a") or ""),
            str(closing_snap.get("raw_team_b") or ""),
            closing_snap.get("odds_a"),
            closing_snap.get("odds_b"),
        )
        if not closing_aligned:
            continue

        closing_a, closing_b = closing_aligned
        matches_with_data += 1

        # --- Process each snapshot ---
        for hours_before, s in pre_match:
            aligned = _align(
                n_a, n_b,
                str(s.get("raw_team_a") or ""),
                str(s.get("raw_team_b") or ""),
                s.get("odds_a"),
                s.get("odds_b"),
            )
            if not aligned:
                continue

            odds_a, odds_b = aligned

            # % deviation from closing
            dev_a_pct = ((odds_a - closing_a) / closing_a) * 100.0 if closing_a else 0.0
            dev_b_pct = ((odds_b - closing_b) / closing_b) * 100.0 if closing_b else 0.0

            # Assign to 2h bucket
            bucket_start = int(hours_before) // BUCKET_SIZE * BUCKET_SIZE
            bucket_end = bucket_start + BUCKET_SIZE
            bucket_label = f"{bucket_start}-{bucket_end}h"

            buckets_raw.setdefault(bucket_label, []).append({
                "match_id": mid,
                "hours_before": hours_before,
                "odds_a": odds_a,
                "odds_b": odds_b,
                "closing_a": closing_a,
                "closing_b": closing_b,
                "deviation_a_pct": dev_a_pct,
                "deviation_b_pct": dev_b_pct,
                "bookmaker": s.get("bookmaker"),
            })

    if not buckets_raw:
        return _empty_result(matches_with_data)

    # --- 4. Aggregate buckets ---
    # Determine max bucket range (round up to even, min 48h)
    all_hours = []
    for items in buckets_raw.values():
        for item in items:
            all_hours.append(item["hours_before"])
    if not all_hours:
        return _empty_result(matches_with_data)

    max_hours = max(all_hours)
    max_bucket_end = int(max_hours) + BUCKET_SIZE
    if max_bucket_end % BUCKET_SIZE != 0:
        max_bucket_end += BUCKET_SIZE
    max_bucket_end = max(max_bucket_end, 48)

    # Create all 2h bucket slots
    ordered_slots = []
    for start_h in range(0, max_bucket_end, BUCKET_SIZE):
        end_h = start_h + BUCKET_SIZE
        label = f"{start_h}-{end_h}h"
        ordered_slots.append(label)

    time_buckets = []
    for label in ordered_slots:
        items = buckets_raw.get(label, [])
        if not items:
            continue

        n = len(items)
        dev_a = [it["deviation_a_pct"] for it in items]
        dev_b = [it["deviation_b_pct"] for it in items]
        odds_a_list = [it["odds_a"] for it in items]
        odds_b_list = [it["odds_b"] for it in items]
        closing_a_list = [it["closing_a"] for it in items]
        closing_b_list = [it["closing_b"] for it in items]
        unique_matches = len(set(it["match_id"] for it in items))

        avg_dev_a = sum(dev_a) / n
        avg_dev_b = sum(dev_b) / n

        # Std dev of deviation
        if n > 1:
            std_dev_a = (sum((d - avg_dev_a) ** 2 for d in dev_a) / (n - 1)) ** 0.5
            std_dev_b = (sum((d - avg_dev_b) ** 2 for d in dev_b) / (n - 1)) ** 0.5
        else:
            std_dev_a = std_dev_b = 0.0

        time_buckets.append({
            "bucket": label,
            "hours_start": int(label.split("-")[0]),
            "hours_end": int(label.split("-")[1].rstrip("h")),
            "snapshot_count": n,
            "match_count": unique_matches,
            "avg_deviation_a_pct": round(avg_dev_a, 2),
            "avg_deviation_b_pct": round(avg_dev_b, 2),
            "std_deviation_a_pct": round(std_dev_a, 2),
            "std_deviation_b_pct": round(std_dev_b, 2),
            "avg_odds_a": round(sum(odds_a_list) / n, 3),
            "avg_odds_b": round(sum(odds_b_list) / n, 3),
            "avg_closing_odds_a": round(sum(closing_a_list) / n, 3),
            "avg_closing_odds_b": round(sum(closing_b_list) / n, 3),
        })

    # --- 5. Drift summary ---
    drift_summary = None
    if len(time_buckets) >= 2:
        earliest = time_buckets[-1]  # farthest from match
        latest = time_buckets[0]     # closest to match

        drift_summary = {
            "earliest_bucket": earliest["bucket"],
            "latest_bucket": latest["bucket"],
            "open_deviation_a_pct": earliest["avg_deviation_a_pct"],
            "open_deviation_b_pct": earliest["avg_deviation_b_pct"],
            "close_deviation_a_pct": latest["avg_deviation_a_pct"],
            "close_deviation_b_pct": latest["avg_deviation_b_pct"],
            "convergence_a_pct": round(
                earliest["avg_deviation_a_pct"] - latest["avg_deviation_a_pct"], 2
            ),
            "convergence_b_pct": round(
                earliest["avg_deviation_b_pct"] - latest["avg_deviation_b_pct"], 2
            ),
        }

    # --- 6. Best betting window ---
    # The best window is where deviation is highest (odds furthest above closing)
    # For each side independently, then combined
    best_window = None
    if time_buckets:
        scored = []
        for b in time_buckets:
            # "Favorable deviation" = max positive deviation from closing
            # Positive = odds better than closing
            fav_dev = max(b["avg_deviation_a_pct"], b["avg_deviation_b_pct"])
            # Also consider stability
            stability = (b["std_deviation_a_pct"] + b["std_deviation_b_pct"]) / 2
            scored.append((b["bucket"], fav_dev, stability, b["match_count"], b))

        # Filter to buckets with reasonable sample
        scored = [s for s in scored if s[3] >= 3]
        if scored:
            # Find bucket where favorable deviation is highest
            scored.sort(key=lambda x: x[1], reverse=True)
            best = scored[0][4]
            best_window = {
                "bucket": best["bucket"],
                "hours_start": best["hours_start"],
                "hours_end": best["hours_end"],
                "avg_favorable_deviation_pct": max(
                    best["avg_deviation_a_pct"], best["avg_deviation_b_pct"]
                ),
                "avg_deviation_a_pct": best["avg_deviation_a_pct"],
                "avg_deviation_b_pct": best["avg_deviation_b_pct"],
                "match_count": best["match_count"],
                "snapshot_count": best["snapshot_count"],
                "recommendation": _build_recommendation(best),
            }

    return {
        "total_matches": matches_with_data,
        "total_snapshots": sum(len(v) for v in buckets_raw.values()),
        "time_buckets": time_buckets,
        "drift_summary": drift_summary,
        "best_betting_window": best_window,
    }


def _build_recommendation(bucket: dict) -> str:
    """Generate human-readable betting recommendation."""
    dev_a = bucket["avg_deviation_a_pct"]
    dev_b = bucket["avg_deviation_b_pct"]

    parts = []
    if dev_a > 1:
        parts.append(f"Team A odds average {dev_a:+.1f}% above closing")
    elif dev_a < -1:
        parts.append(f"Team A odds average {dev_a:+.1f}% below closing")

    if dev_b > 1:
        parts.append(f"Team B odds average {dev_b:+.1f}% above closing")
    elif dev_b < -1:
        parts.append(f"Team B odds average {dev_b:+.1f}% below closing")

    if not parts:
        return f"Odds in the {bucket['bucket']} window are near closing levels."

    return (
        f"In the {bucket['bucket']} window before match: "
        f"{'; '.join(parts)}. "
        f"This window shows the most favorable odds vs closing prices."
    )


def _empty_result(matches_found: int = 0) -> dict:
    return {
        "total_matches": 0,
        "total_snapshots": 0,
        "time_buckets": [],
        "drift_summary": None,
        "best_betting_window": None,
        "summary": {
            "message": "No finished matches with sufficient odds history found."
            if matches_found == 0
            else "Not enough data after processing."
        },
    }


@router.get("/match/{match_id}/movement")
def match_odds_movement(match_id: int, db=Depends(get_db)):
    """Get detailed odds movement for a specific match.

    Returns time series of odds with % deviation from closing.
    """
    match = query_df(
        db,
        "SELECT * FROM canonical_matches WHERE id=:id",
        {"id": match_id},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    m = match[0]
    match_start = _parse_dt(m.get("start_time_normalized"))
    n_a = str(m.get("normalized_team_a") or "")
    n_b = str(m.get("normalized_team_b") or "")

    odds = query_df(
        db,
        """
        SELECT os.scraped_at, os.odds_a, os.odds_b,
               os.raw_team_a, os.raw_team_b,
               b.name AS bookmaker
        FROM odds_snapshots os
        JOIN bookmakers b ON b.id = os.bookmaker_id
        WHERE os.canonical_match_id = :mid
          AND os.market_type = 'match_winner'
          AND COALESCE(os.is_live, 0) = 0
          AND os.odds_a IS NOT NULL
          AND os.odds_b IS NOT NULL
        ORDER BY os.scraped_at
        """,
        {"mid": match_id},
    )

    if not odds:
        return {
            "match_id": match_id,
            "team_a": m.get("team_a_name"),
            "team_b": m.get("team_b_name"),
            "movement_points": [],
            "summary": {"message": "No odds history available"},
        }

    # Align all snapshots
    points = []
    closing_a = closing_b = None

    for row in odds:
        st = _parse_dt(row["scraped_at"])
        if not st or not match_start:
            continue
        hours_before = (match_start - st).total_seconds() / 3600.0
        if hours_before < 0:
            continue

        aligned = _align(
            n_a, n_b,
            str(row.get("raw_team_a") or ""),
            str(row.get("raw_team_b") or ""),
            row.get("odds_a"),
            row.get("odds_b"),
        )
        if not aligned:
            continue

        points.append({
            "scraped_at": str(st),
            "hours_before_match": round(hours_before, 2),
            "bookmaker": row.get("bookmaker"),
            "odds_a": round(aligned[0], 3),
            "odds_b": round(aligned[1], 3),
        })

    if not points:
        return {
            "match_id": match_id,
            "team_a": m.get("team_a_name"),
            "team_b": m.get("team_b_name"),
            "movement_points": [],
            "summary": {"message": "No valid pre-match odds data"},
        }

    # Sort by hours_before descending (earliest first)
    points.sort(key=lambda p: p["hours_before_match"], reverse=True)
    closing = points[0]  # closest to match start
    closing_a = closing["odds_a"]
    closing_b = closing["odds_b"]

    # Add deviation % to each point
    for p in points:
        p["deviation_a_pct"] = round(
            ((p["odds_a"] - closing_a) / closing_a) * 100.0, 2
        )
        p["deviation_b_pct"] = round(
            ((p["odds_b"] - closing_b) / closing_b) * 100.0, 2
        )

    first = points[-1]  # farthest from match

    return {
        "match_id": match_id,
        "team_a": m.get("team_a_name"),
        "team_b": m.get("team_b_name"),
        "start_time": m.get("start_time_normalized"),
        "movement_points": points,
        "summary": {
            "total_snapshots": len(points),
            "first_snapshot": first["scraped_at"],
            "last_snapshot": closing["scraped_at"],
            "opening_odds_a": first["odds_a"],
            "opening_odds_b": first["odds_b"],
            "closing_odds_a": closing_a,
            "closing_odds_b": closing_b,
            "opening_deviation_a_pct": first["deviation_a_pct"],
            "opening_deviation_b_pct": first["deviation_b_pct"],
            "total_drift_a": round(closing_a - first["odds_a"], 3),
            "total_drift_b": round(closing_b - first["odds_b"], 3),
        },
    }
