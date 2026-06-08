"""Router: /api/timing — odds timing analysis for betting strategy.

Key metrics:
  - Fixed 2-hour time buckets (0-2h, 2-4h, 4-6h, ..., up to 72h+)
  - % deviation from closing odds (last pre-match snapshot)
  - Shows whether earlier odds are better/worse than closing
  - Convergence pattern analysis
  - Horizon accuracy: LogLoss & AUC by hours-before-match bin
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
import numpy as np
from sklearn.metrics import log_loss, roc_auc_score

from betting_app.api.deps import get_db, query_df

router = APIRouter(prefix="/timing", tags=["timing"])

THESIS_MODEL_NAME = "Sym-Cal LR-ElasticNet-W20-Binomial"
THESIS_MODEL_VERSION = "exp-039"
THESIS_HYBRID_MODEL_NAME = "Hybrid-Thesis-Market"


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


def _implied_prob(odds: float) -> float:
    """Convert decimal odds to implied probability (no-margin)."""
    if odds is None or odds <= 1.0:
        return 0.5
    return 1.0 / odds


def _remove_margin(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Remove bookmaker margin by normalizing probabilities to sum to 1."""
    total = prob_a + prob_b
    if total <= 0:
        return (0.5, 0.5)
    return (prob_a / total, prob_b / total)


def _compute_auc(y_true: list[int], y_score: list[float]) -> float | None:
    """Compute AUC-ROC, return None if degenerate."""
    try:
        if len(set(y_true)) < 2:
            return None
        val = roc_auc_score(y_true, y_score)
        return round(float(val), 4)
    except Exception:
        return None


def _compute_logloss(y_true: list[int], y_prob: list[float], eps: float = 1e-15) -> float | None:
    """Compute LogLoss, return None if degenerate."""
    try:
        n = len(y_true)
        if n == 0:
            return None
        arr_true = np.array(y_true, dtype=float)
        arr_prob = np.array(y_prob, dtype=float)
        arr_prob = np.clip(arr_prob, eps, 1 - eps)
        ll = -np.mean(arr_true * np.log(arr_prob) + (1 - arr_true) * np.log(1 - arr_prob))
        return round(float(ll), 4)
    except Exception:
        return None


@router.get("/horizon-accuracy")
def horizon_accuracy(
    min_matches_per_bin: int = 10,
    max_days_back: int = 90,
    db=Depends(get_db),
):
    """Analyze prediction accuracy (LogLoss, AUC) by hours-before-match.

    Uses odds as implied probabilities.  Groups snapshots into time bins
    relative to match start.  Each bin reflects the market's implied
    probability accuracy at that horizon.

    Returns:
      - bins: list of {label, hours_start, hours_end,
               snapshot_count, match_count,
               avg_logloss, avg_auc,
               avg_prob_winner, avg_prob_loser}
      - Only bins with >= min_matches_per_bin are included.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=max_days_back)).isoformat()

    # --- 1. Get finished matches with result and start time ---
    matches = query_df(
        db,
        """
        SELECT cm.id, cm.start_time_normalized,
               cm.normalized_team_a, cm.normalized_team_b,
               cm.winner_side
        FROM canonical_matches cm
        WHERE cm.status IN ('finished', 'completed')
          AND cm.winner_side IS NOT NULL
          AND cm.start_time_normalized IS NOT NULL
          AND cm.start_time_normalized > :cutoff
        ORDER BY cm.start_time_normalized DESC
        """,
        {"cutoff": cutoff},
    )
    if not matches:
        return _empty_horizon_result()

    match_map = {m["id"]: m for m in matches}
    match_ids = list(match_map.keys())

    # --- 2. Get all pre-match odds snapshots ---
    placeholders = ",".join(f":mid{i}" for i in range(len(match_ids)))
    params: dict[str, Any] = {f"mid{i}": mid for i, mid in enumerate(match_ids)}

    snapshots = query_df(
        db,
        f"""
        SELECT os.canonical_match_id, os.scraped_at,
               os.bookmaker_id, os.odds_a, os.odds_b,
               os.raw_team_a, os.raw_team_b
        FROM odds_snapshots os
        WHERE os.canonical_match_id IN ({placeholders})
          AND os.market_type = 'match_winner'
          AND COALESCE(os.is_live, 0) = 0
          AND os.odds_a IS NOT NULL
          AND os.odds_b IS NOT NULL
        ORDER BY os.canonical_match_id, os.scraped_at
        """,
        params,
    )

    # --- 3. Build bins ---
    # Bin definitions: (label, max_hours)
    # Cumulative bins: a snapshot at 4h counts in ≤2h AND ≤6h bins.
    BIN_DEFS = [
        ("≤2h",     0,   2),
        ("≤6h",     0,   6),
        ("≤12h",    0,  12),
        ("≤24h",    0,  24),
        ("≤48h",    0,  48),
        ("48h+",    0, 9999),
    ]

    # Accumulate per bin at match level.
    # A match may have many bookmaker snapshots in the same horizon bin.  We
    # first average the market probability for that match/bin, then compute
    # metrics across matches.  This prevents matches covered by many
    # bookmakers/scrapes from dominating LogLoss/AUC.
    bin_data: dict[str, dict] = {
        label: {
            "per_match": defaultdict(lambda: {
                "y_true": None,
                "bookmaker_scores": defaultdict(list),
                "bookmaker_prob_winner": defaultdict(list),
                "bookmaker_prob_loser": defaultdict(list),
            }),
            "snapshot_count": 0,
        }
        for label, _, _ in BIN_DEFS
    }

    matches_with_odds = set()
    odds_processed = 0

    for snap in snapshots:
        mid = snap["canonical_match_id"]
        m = match_map.get(mid)
        if not m:
            continue

        match_start = _parse_dt(m.get("start_time_normalized"))
        scraped = _parse_dt(snap.get("scraped_at"))
        if not match_start or not scraped:
            continue

        hours_before = (match_start - scraped).total_seconds() / 3600.0
        if hours_before < 0:
            continue  # post-match / in-play

        # Align odds to canonical sides
        aligned = _align(
            str(m.get("normalized_team_a") or ""),
            str(m.get("normalized_team_b") or ""),
            str(snap.get("raw_team_a") or ""),
            str(snap.get("raw_team_b") or ""),
            snap.get("odds_a"),
            snap.get("odds_b"),
        )
        if not aligned:
            continue

        odds_a, odds_b = aligned

        # Convert to implied probabilities (margin-removed)
        prob_a = _implied_prob(odds_a)
        prob_b = _implied_prob(odds_b)
        prob_a_norm, prob_b_norm = _remove_margin(prob_a, prob_b)

        # Ground truth: which side won?
        winner_side = str(m.get("winner_side") or "")
        if winner_side not in ("team_a", "team_b"):
            continue

        # y_true: 1 if team_a won, 0 if team_b won
        # y_score: implied probability that team_a wins
        y_true = 1 if winner_side == "team_a" else 0
        y_score = prob_a_norm

        # Probability assigned to the actual winner / loser
        if winner_side == "team_a":
            prob_winner = prob_a_norm
            prob_loser = prob_b_norm
        else:
            prob_winner = prob_b_norm
            prob_loser = prob_a_norm

        # Find bin(s) — cumulative: snapshot counts in ALL bins where hours_before < hmax
        for label, hmin, hmax in BIN_DEFS:
            if hours_before < hmax:
                bd = bin_data[label]
                md = bd["per_match"][mid]
                bookmaker_key = snap.get("bookmaker_id") or "unknown"
                md["y_true"] = y_true
                md["bookmaker_scores"][bookmaker_key].append(y_score)
                md["bookmaker_prob_winner"][bookmaker_key].append(prob_winner)
                md["bookmaker_prob_loser"][bookmaker_key].append(prob_loser)
                bd["snapshot_count"] += 1
                matches_with_odds.add(mid)
                odds_processed += 1

    if odds_processed == 0:
        return _empty_horizon_result(len(matches))

    # --- 4. Compute metrics per bin ---
    bins = []
    for label, hmin, hmax in BIN_DEFS:
        bd = bin_data[label]
        per_match = bd["per_match"]
        n_matches = len(per_match)
        n_snapshots = bd["snapshot_count"]

        # Skip bins with insufficient matches
        if n_matches < min_matches_per_bin:
            continue

        # One observation per match: mean bookmaker/snapshot probability in
        # this bin, then metrics across matches.
        y_true: list[int] = []
        y_score: list[float] = []
        prob_winner_by_match: list[float] = []
        prob_loser_by_match: list[float] = []
        for md in per_match.values():
            if md["y_true"] is None or not md["bookmaker_scores"]:
                continue
            bookmaker_scores = [float(np.mean(vals)) for vals in md["bookmaker_scores"].values() if vals]
            bookmaker_winner = [float(np.mean(vals)) for vals in md["bookmaker_prob_winner"].values() if vals]
            bookmaker_loser = [float(np.mean(vals)) for vals in md["bookmaker_prob_loser"].values() if vals]
            if not bookmaker_scores:
                continue
            y_true.append(int(md["y_true"]))
            y_score.append(float(np.mean(bookmaker_scores)))
            if bookmaker_winner:
                prob_winner_by_match.append(float(np.mean(bookmaker_winner)))
            if bookmaker_loser:
                prob_loser_by_match.append(float(np.mean(bookmaker_loser)))

        auc_val = _compute_auc(y_true, y_score)
        ll_val = _compute_logloss(y_true, y_score)
        avg_prob_winner = round(np.mean(prob_winner_by_match), 4) if prob_winner_by_match else None
        avg_prob_loser = round(np.mean(prob_loser_by_match), 4) if prob_loser_by_match else None

        bins.append({
            "label": label,
            "hours_start": hmin,
            "hours_end": hmax if hmax < 9999 else None,
            "snapshot_count": n_snapshots,
            "match_count": n_matches,
            "avg_logloss": ll_val,
            "avg_auc": auc_val,
            "avg_prob_winner": avg_prob_winner,
            "avg_prob_loser": avg_prob_loser,
        })

    # --- 5. Compute per-bookmaker metrics ---
    bookmaker_bins = _compute_bookmaker_bins(bin_data, BIN_DEFS, min_matches_per_bin, db)

    # --- 6. Compute overall model accuracy reference lines ---
    model_refs, hybrid_model_bins = _compute_model_reference_metrics(db, cutoff)

    return {
        "total_matches_with_odds": len(matches_with_odds),
        "total_finished_matches": len(matches),
        "total_odds_processed": odds_processed,
        "bins": bins,
        "min_matches_per_bin": min_matches_per_bin,
        "model_references": model_refs,
        "hybrid_model_bins": hybrid_model_bins,
        "bookmaker_bins": bookmaker_bins,
    }


def _compute_bookmaker_bins(
    bin_data: dict, bin_defs: list, min_matches: int, db,
) -> list[dict]:
    """Compute per-bookmaker LogLoss/AUC for each horizon bin.

    Uses the same per-match aggregated data from horizon_accuracy().
    For each bookmaker in each bin, computes metrics using only that
    bookmaker's snapshots (one observation per match after averaging
    same-bookmaker snapshots for that match).

    Returns list of {bookmaker_id, bookmaker_name, bins: [...]}.
    """
    # Look up bookmaker names
    bookmaker_rows = query_df(db, "SELECT id, name FROM bookmakers ORDER BY id")
    bk_names: dict[int, str] = {}
    for r in bookmaker_rows:
        bk_names[int(r["id"])] = str(r["name"])

    # Collect all bookmaker IDs seen across bins
    all_bk_ids: set[int] = set()
    for label, _, _ in bin_defs:
        bd = bin_data[label]
        for md in bd["per_match"].values():
            for bk_id in md["bookmaker_scores"].keys():
                try:
                    all_bk_ids.add(int(bk_id))
                except (ValueError, TypeError):
                    pass

    result: list[dict] = []
    for bk_id in sorted(all_bk_ids):
        bk_name = bk_names.get(bk_id, f"bookmaker_{bk_id}")
        bk_bins: list[dict] = []

        for label, hmin, hmax in bin_defs:
            bd = bin_data[label]
            per_match = bd["per_match"]

            y_true: list[int] = []
            y_score: list[float] = []
            for md in per_match.values():
                if md["y_true"] is None:
                    continue
                scores = md["bookmaker_scores"].get(bk_id)
                if not scores:
                    continue
                y_true.append(int(md["y_true"]))
                y_score.append(float(np.mean(scores)))

            n_matches = len(y_true)
            if n_matches < min_matches:
                continue
            if len(set(y_true)) < 2:
                continue

            ll = _compute_logloss(y_true, y_score)
            auc = _compute_auc(y_true, y_score)

            bk_bins.append({
                "label": label,
                "hours_start": hmin,
                "hours_end": hmax if hmax < 9999 else None,
                "match_count": n_matches,
                "avg_logloss": ll,
                "avg_auc": auc,
            })

        if bk_bins:
            result.append({
                "bookmaker_id": bk_id,
                "bookmaker_name": bk_name,
                "bins": bk_bins,
            })

    return result


def _compute_model_reference_metrics(db, cutoff: str) -> tuple[list[dict], list[dict]]:
    """Compute overall LogLoss & AUC for each registered prediction model.

    For pure models (thesis, operational): returns single LogLoss/AUC values.
    For hybrid models: returns per-bin metrics computed dynamically using
    thesis_prob + market_prob from each time bin.

    Returns:
        tuple of (pure_model_refs, hybrid_model_bins)
    """
    refs: list[dict] = []
    hybrid_bins: list[dict] = []

    # Bin definitions (cumulative, same as in horizon_accuracy)
    BIN_DEFS = [
        ("≤2h",     0,   2),
        ("≤6h",     0,   6),
        ("≤12h",    0,  12),
        ("≤24h",    0,  24),
        ("≤48h",    0,  48),
        ("48h+",    0, 9999),
    ]

    model_defs = query_df(
        db,
        """
        SELECT DISTINCT cp.model_name, cp.model_version
        FROM canonical_predictions cp
        JOIN canonical_matches cm ON cm.id = cp.canonical_match_id
        WHERE cp.model_name IN (:thesis_model, :hybrid_model)
          AND cm.status IN ('finished', 'completed')
          AND cm.winner_side IS NOT NULL
          AND cm.start_time_normalized > :cutoff
        ORDER BY cp.model_name
        """,
        {
            "cutoff": cutoff,
            "thesis_model": THESIS_MODEL_NAME,
            "hybrid_model": THESIS_HYBRID_MODEL_NAME,
        },
    )

    for md in model_defs:
        model_name = md["model_name"]
        model_version = md["model_version"]
        
        # Check if this is a hybrid model
        is_hybrid = "hybrid" in model_name.lower()
        
        if is_hybrid:
            # For hybrid models: compute per-bin metrics dynamically
            # Need: thesis_prob (from canonical_predictions) + market_prob (from odds_snapshots per bin)
            hybrid_bin_metrics = _compute_hybrid_bins_dynamic(
                db, cutoff, model_name, model_version, BIN_DEFS
            )
            if hybrid_bin_metrics:
                hybrid_bins.append({
                    "model_name": model_name,
                    "model_version": model_version,
                    "bins": hybrid_bin_metrics,
                })
        else:
            # For pure models: compute single LogLoss/AUC
            preds = query_df(
                db,
                """
                WITH ranked AS (
                    SELECT cp.prob_a, cp.prob_b,
                           cm.winner_side,
                           cm.normalized_team_a, cm.normalized_team_b,
                           ROW_NUMBER() OVER (
                               PARTITION BY cp.canonical_match_id
                               ORDER BY cp.predicted_at DESC NULLS LAST, cp.id DESC
                           ) AS rn
                    FROM canonical_predictions cp
                    JOIN canonical_matches cm ON cm.id = cp.canonical_match_id
                    WHERE cp.model_name = :mname
                      AND cp.model_version = :mver
                      AND cm.status IN ('finished', 'completed')
                      AND cm.winner_side IS NOT NULL
                      AND cm.start_time_normalized > :cutoff
                )
                SELECT prob_a, prob_b, winner_side, normalized_team_a, normalized_team_b
                FROM ranked
                WHERE rn = 1
                """,
                {"mname": model_name, "mver": model_version, "cutoff": cutoff},
            )
            if not preds:
                continue

            y_true: list[int] = []
            y_score: list[float] = []
            for p in preds:
                winner = str(p.get("winner_side") or "")
                if winner not in ("team_a", "team_b"):
                    continue
                prob_a = p.get("prob_a")
                if prob_a is None:
                    continue
                prob_a = float(prob_a)
                if not (0 < prob_a < 1):
                    continue
                y_score.append(prob_a)
                y_true.append(1 if winner == "team_a" else 0)

            if len(y_true) < 2 or len(set(y_true)) < 2:
                continue

            ll = _compute_logloss(y_true, y_score)
            auc = _compute_auc(y_true, y_score)
            refs.append({
                "model_name": model_name,
                "model_version": model_version,
                "avg_logloss": ll,
                "avg_auc": auc,
                "n_matches": len(y_true),
            })

    return refs, hybrid_bins


def _compute_hybrid_bins_dynamic(
    db, cutoff: str, model_name: str, model_version: str, bin_defs: list
) -> list[dict]:
    """Compute hybrid model metrics per time bin dynamically.
    
    For each bin:
    1. Get thesis model predictions for finished matches
    2. Get average market probabilities from odds_snapshots in that bin
    3. Compute hybrid_prob = alpha * thesis_prob + (1-alpha) * market_prob
    4. Calculate LogLoss/AUC for that bin
    
    Returns list of bin dicts with metrics.
    """
    # Extract alpha and temperature from model_version (format: "a0.50-t0.80")
    alpha = 0.50  # default
    temperature = 0.80  # default
    if model_version.startswith("a") and "-t" in model_version:
        try:
            parts = model_version.split("-t")
            alpha = float(parts[0][1:])  # remove 'a' prefix
            temperature = float(parts[1])
        except (IndexError, ValueError):
            pass
    
    # Get latest pure thesis model predictions for finished matches.
    # Do not filter by prediction_status here: for historical evaluation the
    # last prediction made before/around a match is still the valid forecast,
    # even if later scheduler runs marked it as stale while the match was not
    # yet auto-finished.
    thesis_preds = query_df(
        db,
        """
        WITH ranked AS (
            SELECT cp.canonical_match_id, cp.prob_a as thesis_prob_a,
                   cm.winner_side, cm.start_time_normalized,
                   ROW_NUMBER() OVER (
                       PARTITION BY cp.canonical_match_id
                       ORDER BY cp.predicted_at DESC NULLS LAST, cp.id DESC
                   ) AS rn
            FROM canonical_predictions cp
            JOIN canonical_matches cm ON cm.id = cp.canonical_match_id
            WHERE cp.model_name = :base_model
              AND cp.model_version = :base_version
              AND cm.status IN ('finished', 'completed')
              AND cm.winner_side IS NOT NULL
              AND cm.start_time_normalized > :cutoff
        )
        SELECT canonical_match_id, thesis_prob_a, winner_side, start_time_normalized
        FROM ranked
        WHERE rn = 1
        """,
        {
            "base_model": THESIS_MODEL_NAME,
            "base_version": THESIS_MODEL_VERSION,
            "cutoff": cutoff,
        },
    )
    
    if not thesis_preds:
        return []
    
    # Build match_id -> thesis_prob mapping
    match_thesis = {p["canonical_match_id"]: float(p["thesis_prob_a"]) for p in thesis_preds}
    match_ids = list(match_thesis.keys())
    
    # Get odds snapshots for these matches
    placeholders = ",".join(f":mid{i}" for i in range(len(match_ids)))
    params = {f"mid{i}": mid for i, mid in enumerate(match_ids)}
    
    snapshots = query_df(
        db,
        f"""
        SELECT os.canonical_match_id, os.scraped_at,
               os.bookmaker_id, os.odds_a, os.odds_b,
               os.raw_team_a, os.raw_team_b
        FROM odds_snapshots os
        WHERE os.canonical_match_id IN ({placeholders})
          AND os.market_type = 'match_winner'
          AND COALESCE(os.is_live, 0) = 0
          AND os.odds_a IS NOT NULL
          AND os.odds_b IS NOT NULL
        ORDER BY os.canonical_match_id, os.scraped_at
        """,
        params,
    )
    
    # Get match metadata (start_time, winner_side, team names)
    match_meta = query_df(
        db,
        f"""
        SELECT id, start_time_normalized, winner_side,
               normalized_team_a, normalized_team_b
        FROM canonical_matches
        WHERE id IN ({placeholders})
        """,
        params,
    )
    meta_map = {m["id"]: m for m in match_meta}
    
    # Accumulate per bin at match level.  Average market/hybrid predictions
    # inside each match/bin first, then compute metrics across matches.
    bin_data = {
        label: {
            "per_match": defaultdict(lambda: {
                "y_true": None,
                "bookmaker_scores": defaultdict(list),
            }),
            "snapshot_count": 0,
        }
        for label, _, _ in bin_defs
    }
    
    for snap in snapshots:
        mid = snap["canonical_match_id"]
        if mid not in match_thesis:
            continue
        
        meta = meta_map.get(mid)
        if not meta:
            continue
        
        match_start = _parse_dt(meta.get("start_time_normalized"))
        scraped = _parse_dt(snap.get("scraped_at"))
        if not match_start or not scraped:
            continue
        
        hours_before = (match_start - scraped).total_seconds() / 3600.0
        if hours_before < 0:
            continue
        
        # Align odds to canonical sides
        aligned = _align(
            str(meta.get("normalized_team_a") or ""),
            str(meta.get("normalized_team_b") or ""),
            str(snap.get("raw_team_a") or ""),
            str(snap.get("raw_team_b") or ""),
            snap.get("odds_a"),
            snap.get("odds_b"),
        )
        if not aligned:
            continue
        
        odds_a, odds_b = aligned
        
        # Convert to implied probabilities (margin-removed)
        prob_a = _implied_prob(odds_a)
        prob_b = _implied_prob(odds_b)
        market_prob_a, market_prob_b = _remove_margin(prob_a, prob_b)
        
        # Apply temperature scaling to market probs
        market_prob_a = apply_temperature_probability(market_prob_a, temperature)
        market_prob_b = apply_temperature_probability(market_prob_b, temperature)
        
        # Get thesis probability
        thesis_prob_a = match_thesis[mid]
        thesis_prob_b = 1.0 - thesis_prob_a
        
        # Compute hybrid probability
        hybrid_prob_a = alpha * thesis_prob_a + (1 - alpha) * market_prob_a
        hybrid_prob_b = alpha * thesis_prob_b + (1 - alpha) * market_prob_b
        
        # Normalize to sum to 1
        total = hybrid_prob_a + hybrid_prob_b
        if total > 0:
            hybrid_prob_a /= total
            hybrid_prob_b /= total
        
        # Ground truth
        winner_side = str(meta.get("winner_side") or "")
        if winner_side not in ("team_a", "team_b"):
            continue
        
        y_true = 1 if winner_side == "team_a" else 0
        y_score = hybrid_prob_a
        
        # Find bin(s) — cumulative: snapshot counts in ALL bins where hours_before < hmax
        for label, hmin, hmax in bin_defs:
            if hours_before < hmax:
                bd = bin_data[label]
                md = bd["per_match"][mid]
                bookmaker_key = snap.get("bookmaker_id") or "unknown"
                md["y_true"] = y_true
                md["bookmaker_scores"][bookmaker_key].append(y_score)
                bd["snapshot_count"] += 1
    
    # Compute metrics per bin
    result_bins = []
    for label, hmin, hmax in bin_defs:
        bd = bin_data[label]
        per_match = bd["per_match"]
        n_matches = len(per_match)
        n_snapshots = bd["snapshot_count"]
        
        if n_matches < 5:  # lower threshold for hybrid bins
            continue
        
        y_true: list[int] = []
        y_score: list[float] = []
        for md in per_match.values():
            if md["y_true"] is None or not md["bookmaker_scores"]:
                continue
            bookmaker_scores = [float(np.mean(vals)) for vals in md["bookmaker_scores"].values() if vals]
            if not bookmaker_scores:
                continue
            y_true.append(int(md["y_true"]))
            y_score.append(float(np.mean(bookmaker_scores)))

        if len(set(y_true)) < 2:
            continue
        
        ll = _compute_logloss(y_true, y_score)
        auc = _compute_auc(y_true, y_score)
        
        result_bins.append({
            "label": label,
            "hours_start": hmin,
            "hours_end": hmax if hmax < 9999 else None,
            "snapshot_count": n_snapshots,
            "match_count": n_matches,
            "avg_logloss": ll,
            "avg_auc": auc,
        })
    
    return result_bins


def apply_temperature_probability(prob: float, temperature: float) -> float:
    """Apply temperature scaling to a probability."""
    if temperature == 1.0:
        return prob
    # Convert to log-odds, scale, convert back
    eps = 1e-15
    prob = max(eps, min(1 - eps, prob))
    log_odds = math.log(prob / (1 - prob))
    scaled_log_odds = log_odds / temperature
    return 1.0 / (1.0 + math.exp(-scaled_log_odds))


def _empty_horizon_result(total_matches: int = 0) -> dict:
    return {
        "total_matches_with_odds": 0,
        "total_finished_matches": total_matches,
        "total_odds_processed": 0,
        "bins": [],
        "min_matches_per_bin": 10,
        "model_references": [],
        "hybrid_model_bins": [],
        "bookmaker_bins": [],
    }


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
