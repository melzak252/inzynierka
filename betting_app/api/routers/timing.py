"""Router: /api/timing — odds timing analysis for betting strategy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from betting_app.api.deps import get_db, query_df

router = APIRouter(prefix="/timing", tags=["timing"])


@router.get("/analysis")
def timing_analysis(
    days_back: int = 30,
    min_snapshots: int = 3,
    db=Depends(get_db),
):
    """Analyze how odds change over time before matches.
    
    Returns aggregated statistics about odds movement patterns:
    - Average odds drift by time bucket (hours before match)
    - Best time to bet based on historical patterns
    - Volatility metrics per time bucket
    """
    now = datetime.now(UTC)
    cutoff = (now - timedelta(days=days_back)).isoformat(timespec="seconds")

    # Get all finished matches with odds history
    matches = query_df(
        db,
        """
        SELECT cm.id, cm.start_time_normalized, cm.team_a_name, cm.team_b_name,
               cm.normalized_team_a, cm.normalized_team_b
        FROM canonical_matches cm
        WHERE cm.status IN ('finished', 'completed')
          AND cm.start_time_normalized IS NOT NULL
          AND cm.start_time_normalized > :cutoff
        ORDER BY cm.start_time_normalized DESC
        LIMIT 500
        """,
        {"cutoff": cutoff},
    )

    if not matches:
        return {
            "total_matches": 0,
            "time_buckets": [],
            "summary": {
                "message": "No finished matches with odds history found in the specified period."
            }
        }

    # Collect odds snapshots with time-to-match calculation
    all_snapshots = []
    for match in matches:
        match_id = match["id"]
        start_time = match.get("start_time_normalized")
        if not start_time:
            continue

        # Parse match start time
        try:
            if isinstance(start_time, str):
                match_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            else:
                continue
        except (ValueError, TypeError):
            continue

        # Get odds history for this match
        odds = query_df(
            db,
            """
            SELECT os.scraped_at, os.odds_a, os.odds_b,
                   os.raw_team_a, os.raw_team_b,
                   b.name AS bookmaker
            FROM odds_snapshots os
            JOIN bookmakers b ON b.id=os.bookmaker_id
            WHERE os.canonical_match_id=:mid 
              AND os.market_type='match_winner'
              AND COALESCE(os.is_live,0)=0
              AND os.odds_a IS NOT NULL 
              AND os.odds_b IS NOT NULL
            ORDER BY os.scraped_at
            """,
            {"mid": match_id},
        )

        if len(odds) < min_snapshots:
            continue

        n_a = match.get("normalized_team_a") or ""
        n_b = match.get("normalized_team_b") or ""

        # Import alignment function
        from betting_app.services.canonical_match_service import align_snapshot_odds

        for row in odds:
            scraped_at = row.get("scraped_at")
            if not scraped_at:
                continue

            try:
                if isinstance(scraped_at, str):
                    scrape_time = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
                elif isinstance(scraped_at, datetime):
                    scrape_time = scraped_at
                    if scrape_time.tzinfo is None:
                        scrape_time = scrape_time.replace(tzinfo=UTC)
                else:
                    continue
            except (ValueError, TypeError):
                continue

            # Calculate hours before match
            hours_before = (match_start - scrape_time).total_seconds() / 3600
            if hours_before < 0:  # Skip post-match snapshots
                continue

            # Align odds to canonical sides
            aligned = align_snapshot_odds(
                n_a, n_b,
                str(row.get("raw_team_a") or ""),
                str(row.get("raw_team_b") or ""),
                row.get("odds_a"),
                row.get("odds_b"),
            )

            if aligned and aligned[0] and aligned[1]:
                all_snapshots.append({
                    "match_id": match_id,
                    "hours_before": hours_before,
                    "odds_a": aligned[0],
                    "odds_b": aligned[1],
                    "bookmaker": row.get("bookmaker"),
                })

    if not all_snapshots:
        return {
            "total_matches": len(matches),
            "total_snapshots": 0,
            "time_buckets": [],
            "summary": {
                "message": "No odds snapshots found for finished matches."
            }
        }

    # Bucket by hours before match
    buckets = {}
    for snap in all_snapshots:
        hours = snap["hours_before"]
        
        # Create time buckets: 0-1h, 1-3h, 3-6h, 6-12h, 12-24h, 24-48h, 48h+
        if hours <= 1:
            bucket = "0-1h"
        elif hours <= 3:
            bucket = "1-3h"
        elif hours <= 6:
            bucket = "3-6h"
        elif hours <= 12:
            bucket = "6-12h"
        elif hours <= 24:
            bucket = "12-24h"
        elif hours <= 48:
            bucket = "24-48h"
        else:
            bucket = "48h+"

        if bucket not in buckets:
            buckets[bucket] = {"odds_a": [], "odds_b": [], "count": 0}

        buckets[bucket]["odds_a"].append(snap["odds_a"])
        buckets[bucket]["odds_b"].append(snap["odds_b"])
        buckets[bucket]["count"] += 1

    # Calculate statistics per bucket
    time_buckets = []
    bucket_order = ["0-1h", "1-3h", "3-6h", "6-12h", "12-24h", "24-48h", "48h+"]
    
    for bucket_name in bucket_order:
        if bucket_name not in buckets:
            continue

        data = buckets[bucket_name]
        odds_a_list = data["odds_a"]
        odds_b_list = data["odds_b"]

        if not odds_a_list or not odds_b_list:
            continue

        # Calculate statistics
        avg_a = sum(odds_a_list) / len(odds_a_list)
        avg_b = sum(odds_b_list) / len(odds_b_list)
        
        # Volatility (standard deviation)
        var_a = sum((x - avg_a) ** 2 for x in odds_a_list) / len(odds_a_list)
        var_b = sum((x - avg_b) ** 2 for x in odds_b_list) / len(odds_b_list)
        std_a = var_a ** 0.5
        std_b = var_b ** 0.5

        # Min/Max
        min_a = min(odds_a_list)
        max_a = max(odds_a_list)
        min_b = min(odds_b_list)
        max_b = max(odds_b_list)

        time_buckets.append({
            "bucket": bucket_name,
            "snapshot_count": data["count"],
            "avg_odds_a": round(avg_a, 3),
            "avg_odds_b": round(avg_b, 3),
            "std_odds_a": round(std_a, 3),
            "std_odds_b": round(std_b, 3),
            "min_odds_a": round(min_a, 3),
            "max_odds_a": round(max_a, 3),
            "min_odds_b": round(min_b, 3),
            "max_odds_b": round(max_b, 3),
        })

    # Calculate odds drift (compare early vs late buckets)
    early_bucket = next((b for b in time_buckets if b["bucket"] in ["24-48h", "48h+"]), None)
    late_bucket = next((b for b in time_buckets if b["bucket"] in ["0-1h", "1-3h"]), None)

    drift_analysis = None
    if early_bucket and late_bucket:
        drift_a = late_bucket["avg_odds_a"] - early_bucket["avg_odds_a"]
        drift_b = late_bucket["avg_odds_b"] - early_bucket["avg_odds_b"]
        
        drift_analysis = {
            "early_bucket": early_bucket["bucket"],
            "late_bucket": late_bucket["bucket"],
            "drift_odds_a": round(drift_a, 3),
            "drift_odds_b": round(drift_b, 3),
            "interpretation": (
                "Odds tend to decrease closer to match start" if drift_a < 0 and drift_b < 0
                else "Odds tend to increase closer to match start" if drift_a > 0 and drift_b > 0
                else "Mixed odds movement patterns"
            )
        }

    # Find best betting window (lowest volatility + reasonable odds)
    best_window = None
    if time_buckets:
        # Score each bucket: lower volatility is better
        scored = []
        for b in time_buckets:
            volatility_score = (b["std_odds_a"] + b["std_odds_b"]) / 2
            scored.append((b["bucket"], volatility_score, b["snapshot_count"]))
        
        # Sort by volatility (lower is better), but require minimum sample size
        scored = [s for s in scored if s[2] >= 10]
        if scored:
            scored.sort(key=lambda x: x[1])
            best_window = {
                "bucket": scored[0][0],
                "avg_volatility": round(scored[0][1], 3),
                "sample_size": scored[0][2],
                "recommendation": f"Most stable odds in the {scored[0][0]} window before match start"
            }

    return {
        "total_matches": len(matches),
        "total_snapshots": len(all_snapshots),
        "time_buckets": time_buckets,
        "drift_analysis": drift_analysis,
        "best_betting_window": best_window,
        "summary": {
            "period_days": days_back,
            "min_snapshots_per_match": min_snapshots,
        }
    }


@router.get("/match/{match_id}/movement")
def match_odds_movement(match_id: int, db=Depends(get_db)):
    """Get detailed odds movement for a specific match over time.
    
    Returns time series of odds changes with calculated metrics.
    """
    # Get match metadata
    match = query_df(
        db,
        "SELECT * FROM canonical_matches WHERE id=:id",
        {"id": match_id},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    m = match[0]
    start_time = m.get("start_time_normalized")
    
    # Parse match start time
    match_start = None
    if start_time:
        try:
            if isinstance(start_time, str):
                match_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    # Get all odds snapshots
    odds = query_df(
        db,
        """
        SELECT os.scraped_at, os.odds_a, os.odds_b,
               os.raw_team_a, os.raw_team_b,
               b.name AS bookmaker
        FROM odds_snapshots os
        JOIN bookmakers b ON b.id=os.bookmaker_id
        WHERE os.canonical_match_id=:mid 
          AND os.market_type='match_winner'
          AND COALESCE(os.is_live,0)=0
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
            "summary": {"message": "No odds history available"}
        }

    n_a = m.get("normalized_team_a") or ""
    n_b = m.get("normalized_team_b") or ""

    from betting_app.services.canonical_match_service import align_snapshot_odds

    movement_points = []
    for row in odds:
        scraped_at = row.get("scraped_at")
        if not scraped_at:
            continue

        try:
            if isinstance(scraped_at, str):
                scrape_time = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
            elif isinstance(scraped_at, datetime):
                scrape_time = scraped_at
                if scrape_time.tzinfo is None:
                    scrape_time = scrape_time.replace(tzinfo=UTC)
            else:
                continue
        except (ValueError, TypeError):
            continue

        hours_before = None
        if match_start:
            hours_before = round((match_start - scrape_time).total_seconds() / 3600, 2)
            if hours_before < 0:
                continue

        aligned = align_snapshot_odds(
            n_a, n_b,
            str(row.get("raw_team_a") or ""),
            str(row.get("raw_team_b") or ""),
            row.get("odds_a"),
            row.get("odds_b"),
        )

        if aligned and aligned[0] and aligned[1]:
            movement_points.append({
                "scraped_at": str(scraped_at),
                "hours_before_match": hours_before,
                "bookmaker": row.get("bookmaker"),
                "odds_a": round(aligned[0], 3),
                "odds_b": round(aligned[1], 3),
            })

    # Calculate movement statistics
    if movement_points:
        first = movement_points[0]
        last = movement_points[-1]
        
        total_drift_a = last["odds_a"] - first["odds_a"]
        total_drift_b = last["odds_b"] - first["odds_b"]
        
        # Find max/min odds
        max_odds_a = max(p["odds_a"] for p in movement_points)
        min_odds_a = min(p["odds_a"] for p in movement_points)
        max_odds_b = max(p["odds_b"] for p in movement_points)
        min_odds_b = min(p["odds_b"] for p in movement_points)

        summary = {
            "total_snapshots": len(movement_points),
            "first_snapshot": first["scraped_at"],
            "last_snapshot": last["scraped_at"],
            "opening_odds_a": first["odds_a"],
            "opening_odds_b": first["odds_b"],
            "closing_odds_a": last["odds_a"],
            "closing_odds_b": last["odds_b"],
            "total_drift_a": round(total_drift_a, 3),
            "total_drift_b": round(total_drift_b, 3),
            "max_odds_a": max_odds_a,
            "min_odds_a": min_odds_a,
            "range_odds_a": round(max_odds_a - min_odds_a, 3),
            "max_odds_b": max_odds_b,
            "min_odds_b": min_odds_b,
            "range_odds_b": round(max_odds_b - min_odds_b, 3),
        }
    else:
        summary = {"message": "No valid odds data"}

    return {
        "match_id": match_id,
        "team_a": m.get("team_a_name"),
        "team_b": m.get("team_b_name"),
        "start_time": start_time,
        "movement_points": movement_points,
        "summary": summary,
    }
