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
from betting_app.core.clv import clv_odds_pct, clv_probability_points
from betting_app.core.ev import best_ev_side
from betting_app.services.thesis_inference_service import THESIS_HYBRID_ALPHA, THESIS_HYBRID_TEMPERATURE

router = APIRouter(prefix="/timing", tags=["timing"])

THESIS_MODEL_NAME = "Sym-Cal LR-ElasticNet-W20-Binomial"
THESIS_MODEL_VERSION = "exp-039"
THESIS_HYBRID_MODEL_NAME = "Hybrid-Thesis-Market"

HORIZON_BIN_DEFS = [
    ("0-2h", 0, 2),
    ("2-6h", 2, 6),
    ("6-12h", 6, 12),
    ("12-24h", 12, 24),
    ("24-48h", 24, 48),
    ("48h+", 48, 9999),
]


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


def _compute_brier(y_true: list[int], y_prob: list[float]) -> float | None:
    """Compute Brier score, return None if no observations."""
    if not y_true:
        return None
    arr_true = np.array(y_true, dtype=float)
    arr_prob = np.array(y_prob, dtype=float)
    return round(float(np.mean((arr_prob - arr_true) ** 2)), 4)


def _compute_accuracy(y_true: list[int], y_prob: list[float]) -> float | None:
    """Compute threshold-0.5 binary accuracy."""
    if not y_true:
        return None
    preds = [1 if float(p) >= 0.5 else 0 for p in y_prob]
    correct = sum(1 for y, p in zip(y_true, preds, strict=False) if int(y) == int(p))
    return round(float(correct / len(y_true)), 4)


def _logloss_one(y_true: int, y_prob: float, eps: float = 1e-15) -> float:
    """Binary LogLoss for a single paired observation."""
    p = max(eps, min(1 - eps, float(y_prob)))
    y = 1.0 if int(y_true) == 1 else 0.0
    return float(-(y * math.log(p) + (1 - y) * math.log(1 - p)))


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for incomplete beta (Numerical Recipes)."""
    max_iter = 200
    eps = 3e-14
    fpmin = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a,b), used for t-test p-values."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _student_t_cdf(t: float, df: int) -> float:
    """CDF of Student's t distribution without SciPy dependency."""
    if df <= 0:
        return 0.5
    x = df / (df + t * t)
    ib = _regularized_incomplete_beta(df / 2.0, 0.5, x)
    if t >= 0:
        return 1.0 - 0.5 * ib
    return 0.5 * ib


def _student_t_ppf(prob: float, df: int) -> float | None:
    """Inverse CDF by bisection; sufficient for critical values shown in UI."""
    if df <= 0 or not (0.0 < prob < 1.0):
        return None
    lo, hi = -50.0, 50.0
    for _ in range(120):
        mid = (lo + hi) / 2.0
        if _student_t_cdf(mid, df) < prob:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _paired_t_test(differences: list[float], alpha: float = 0.05) -> dict | None:
    """One-sided paired t-test for mean(differences) > 0."""
    n = len(differences)
    if n < 2:
        return None
    arr = np.array(differences, dtype=float)
    mean_diff = float(np.mean(arr))
    sd_diff = float(np.std(arr, ddof=1))
    df = n - 1
    if sd_diff <= 0:
        t_stat = math.inf if mean_diff > 0 else (-math.inf if mean_diff < 0 else 0.0)
        p_value = 0.0 if mean_diff > 0 else 1.0
        sem = 0.0
    else:
        sem = sd_diff / math.sqrt(n)
        t_stat = mean_diff / sem
        p_value = 1.0 - _student_t_cdf(t_stat, df)
    critical = _student_t_ppf(1.0 - alpha, df)
    return {
        "n": n,
        "df": df,
        "mean_diff": round(mean_diff, 6),
        "sd_diff": round(sd_diff, 6),
        "sem_diff": round(sem, 6),
        "t_stat": round(float(t_stat), 4) if math.isfinite(t_stat) else None,
        "p_value_one_sided": round(float(p_value), 6),
        "alpha": alpha,
        "t_critical_95_one_sided": round(float(critical), 4) if critical is not None else None,
        "significant": bool(p_value < alpha and mean_diff > 0),
    }


def _compute_model_vs_bookmaker_tests(db, cutoff: str) -> list[dict]:
    """Paired tests: is model better than average bookmaker?

    Positive difference means: bookmaker error - model error > 0, i.e. the
    model has lower error than the average bookmaker on the same match.
    We use paired observations per match to avoid overweighting matches with
    many bookmakers/scrapes.
    """
    preds = query_df(
        db,
        """
        WITH ranked AS (
            SELECT cp.canonical_match_id, cp.prob_a AS thesis_prob_a,
                   cm.winner_side, cm.start_time_normalized,
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
        SELECT canonical_match_id, thesis_prob_a, winner_side,
               start_time_normalized, normalized_team_a, normalized_team_b
        FROM ranked
        WHERE rn = 1
        """,
        {"mname": THESIS_MODEL_NAME, "mver": THESIS_MODEL_VERSION, "cutoff": cutoff},
    )
    if not preds:
        return []

    pred_map = {
        p["canonical_match_id"]: p
        for p in preds
        if p.get("thesis_prob_a") is not None
        and str(p.get("winner_side") or "") in ("team_a", "team_b")
    }
    if not pred_map:
        return []

    match_ids = list(pred_map.keys())
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

    # Per match, average first within bookmaker, then across bookmakers.
    market_by_match: dict[int, dict[Any, list[float]]] = defaultdict(lambda: defaultdict(list))
    hybrid_by_match: dict[int, dict[Any, list[float]]] = defaultdict(lambda: defaultdict(list))
    alpha = THESIS_HYBRID_ALPHA
    temperature = THESIS_HYBRID_TEMPERATURE

    for snap in snapshots:
        mid = snap["canonical_match_id"]
        meta = pred_map.get(mid)
        if not meta:
            continue
        match_start = _parse_dt(meta.get("start_time_normalized"))
        scraped = _parse_dt(snap.get("scraped_at"))
        if not match_start or not scraped:
            continue
        if (match_start - scraped).total_seconds() < 0:
            continue
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
        prob_a = _implied_prob(odds_a)
        prob_b = _implied_prob(odds_b)
        market_prob_a, market_prob_b = _remove_margin(prob_a, prob_b)
        thesis_prob_a = float(meta["thesis_prob_a"])
        thesis_prob_a_t = apply_temperature_probability(thesis_prob_a, temperature)
        hybrid_prob_a = alpha * thesis_prob_a_t + (1.0 - alpha) * market_prob_a
        bookmaker_key = snap.get("bookmaker_id") or "unknown"
        market_by_match[mid][bookmaker_key].append(market_prob_a)
        hybrid_by_match[mid][bookmaker_key].append(hybrid_prob_a)

    thesis_ll_diffs: list[float] = []
    thesis_brier_diffs: list[float] = []
    hybrid_ll_diffs: list[float] = []
    hybrid_brier_diffs: list[float] = []

    for mid, meta in pred_map.items():
        bookmaker_probs = [float(np.mean(vals)) for vals in market_by_match[mid].values() if vals]
        hybrid_probs = [float(np.mean(vals)) for vals in hybrid_by_match[mid].values() if vals]
        if not bookmaker_probs:
            continue
        y_true = 1 if str(meta.get("winner_side") or "") == "team_a" else 0
        market_prob = float(np.mean(bookmaker_probs))
        thesis_prob = float(meta["thesis_prob_a"])
        hybrid_prob = float(np.mean(hybrid_probs)) if hybrid_probs else thesis_prob

        market_ll = _logloss_one(y_true, market_prob)
        thesis_ll = _logloss_one(y_true, thesis_prob)
        hybrid_ll = _logloss_one(y_true, hybrid_prob)
        market_brier = (market_prob - y_true) ** 2
        thesis_brier = (thesis_prob - y_true) ** 2
        hybrid_brier = (hybrid_prob - y_true) ** 2

        thesis_ll_diffs.append(market_ll - thesis_ll)
        thesis_brier_diffs.append(market_brier - thesis_brier)
        hybrid_ll_diffs.append(market_ll - hybrid_ll)
        hybrid_brier_diffs.append(market_brier - hybrid_brier)

    definitions = [
        ("thesis_logloss", "Thesis model vs średni bukmacher — LogLoss", "logloss", THESIS_MODEL_NAME, thesis_ll_diffs),
        ("thesis_brier", "Thesis model vs średni bukmacher — Brier", "brier", THESIS_MODEL_NAME, thesis_brier_diffs),
        ("hybrid_logloss", "Hybrid thesis+market vs średni bukmacher — LogLoss", "logloss", THESIS_HYBRID_MODEL_NAME, hybrid_ll_diffs),
        ("hybrid_brier", "Hybrid thesis+market vs średni bukmacher — Brier", "brier", THESIS_HYBRID_MODEL_NAME, hybrid_brier_diffs),
    ]
    results: list[dict] = []
    for test_id, label, metric, model_name, diffs in definitions:
        stats = _paired_t_test(diffs)
        if not stats:
            continue
        results.append({
            "id": test_id,
            "label": label,
            "metric": metric,
            "model_name": model_name,
            "baseline_name": "Average bookmaker",
            "alternative": "mean(bookmaker_error - model_error) > 0",
            "interpretation": "positive_mean_diff_means_model_better",
            **stats,
        })
    return results


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
    # Interval bins: each snapshot is assigned to exactly one time window.
    # A match can still appear in multiple bins if it has odds snapshots in
    # multiple windows. Metrics for each bin are computed only from odds in
    # that specific interval.
    BIN_DEFS = [
        ("0-2h",     0,   2),
        ("2-6h",     2,   6),
        ("6-12h",    6,  12),
        ("12-24h",  12,  24),
        ("24-48h",  24,  48),
        ("48h+",    48, 9999),
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

        # Find bin — interval: snapshot counts only in its exact time window.
        # A match can appear in multiple bins if it has snapshots in multiple
        # windows, but each bin's stats use only odds from that window.
        for label, hmin, hmax in BIN_DEFS:
            if hmin <= hours_before < hmax:
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
                break

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
    model_refs, hybrid_model_bins = _compute_model_reference_metrics(db, cutoff, min_matches_per_bin)

    # --- 7. Statistical tests: model vs average bookmaker ---
    model_vs_bookmaker_tests = _compute_model_vs_bookmaker_tests(db, cutoff)

    # --- 8. Strict market-close comparison on identical match samples ---
    market_close_comparison = _compute_market_close_comparison(db, cutoff, min_matches_per_bin)

    return {
        "total_matches_with_odds": len(matches_with_odds),
        "total_finished_matches": len(matches),
        "total_odds_processed": odds_processed,
        "bins": bins,
        "min_matches_per_bin": min_matches_per_bin,
        "model_references": model_refs,
        "hybrid_model_bins": hybrid_model_bins,
        "bookmaker_bins": bookmaker_bins,
        "model_vs_bookmaker_tests": model_vs_bookmaker_tests,
        "market_close_comparison": market_close_comparison,
    }


@router.get("/model-clv-by-horizon")
def model_clv_by_horizon(
    max_days_back: int = 90,
    max_odds_age_hours: float = 4.0,
    tax_rate: float = 0.12,
    min_ev: float = 0.0,
    db=Depends(get_db),
):
    """Compute Closing Line Value for model-selected EV entries by horizon.

    This endpoint evaluates market timing, not match-outcome accuracy. For each
    Thesis/Hybrid prediction it finds the latest available bookmaker odds before
    `predicted_at` (entry line), requires the entry odds to be fresh enough, picks
    the side with the highest positive after-tax EV, and compares that entry line
    with the same bookmaker's final valid pre-match line (closing line).

    Positive CLV means the model selected a price that later closed shorter.
    Results include signal-weighted aggregates (all entries) and match-weighted
    aggregates (one averaged observation per model/horizon/match), because the
    latter is the safer headline metric for model evaluation.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=max_days_back)).isoformat()

    predictions = query_df(
        db,
        """
        SELECT cp.id AS prediction_id,
               cp.canonical_match_id,
               cp.model_name,
               cp.model_version,
               cp.predicted_at,
               cp.prob_a,
               cp.prob_b,
               cm.start_time_normalized,
               cm.normalized_team_a,
               cm.normalized_team_b,
               cm.status
        FROM canonical_predictions cp
        JOIN canonical_matches cm ON cm.id = cp.canonical_match_id
        WHERE cp.model_name IN (:thesis_model, :hybrid_model)
          AND cp.predicted_at IS NOT NULL
          AND cp.prob_a IS NOT NULL
          AND cp.prob_b IS NOT NULL
          AND cm.start_time_normalized IS NOT NULL
          AND cm.start_time_normalized > :cutoff
        ORDER BY cp.predicted_at ASC
        """,
        {
            "thesis_model": THESIS_MODEL_NAME,
            "hybrid_model": THESIS_HYBRID_MODEL_NAME,
            "cutoff": cutoff,
        },
    )
    if not predictions:
        return _empty_clv_result(max_days_back, max_odds_age_hours, tax_rate, min_ev)

    match_ids = sorted({int(p["canonical_match_id"]) for p in predictions})
    placeholders = ",".join(f":mid{i}" for i in range(len(match_ids)))
    params: dict[str, Any] = {f"mid{i}": mid for i, mid in enumerate(match_ids)}
    odds_rows = query_df(
        db,
        f"""
        SELECT os.id AS odds_snapshot_id,
               os.canonical_match_id,
               os.bookmaker_id,
               b.name AS bookmaker_name,
               os.scraped_at,
               os.raw_team_a,
               os.raw_team_b,
               os.odds_a,
               os.odds_b,
               cm.normalized_team_a,
               cm.normalized_team_b
        FROM odds_snapshots os
        JOIN canonical_matches cm ON cm.id = os.canonical_match_id
        JOIN bookmakers b ON b.id = os.bookmaker_id
        WHERE os.canonical_match_id IN ({placeholders})
          AND os.market_type = 'match_winner'
          AND COALESCE(os.is_live, 0) = 0
          AND os.odds_a IS NOT NULL
          AND os.odds_b IS NOT NULL
        ORDER BY os.canonical_match_id, os.bookmaker_id, os.scraped_at
        """,
        params,
    )

    odds_by_match_book: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in odds_rows:
        scraped = _parse_dt(row.get("scraped_at"))
        if not scraped:
            continue
        aligned = _align(
            str(row.get("normalized_team_a") or ""),
            str(row.get("normalized_team_b") or ""),
            str(row.get("raw_team_a") or ""),
            str(row.get("raw_team_b") or ""),
            row.get("odds_a"),
            row.get("odds_b"),
        )
        if not aligned:
            continue
        odds_a, odds_b = aligned
        if odds_a <= 1.0 or odds_b <= 1.0:
            continue
        enriched = dict(row)
        enriched["scraped_dt"] = scraped
        enriched["canonical_odds_a"] = odds_a
        enriched["canonical_odds_b"] = odds_b
        odds_by_match_book[(int(row["canonical_match_id"]), int(row["bookmaker_id"]))].append(enriched)

    for rows in odds_by_match_book.values():
        rows.sort(key=lambda r: r["scraped_dt"])

    entries: list[dict[str, Any]] = []
    skips: dict[str, int] = defaultdict(int)

    for pred in predictions:
        match_id = int(pred["canonical_match_id"])
        predicted_at = _parse_dt(pred.get("predicted_at"))
        match_start = _parse_dt(pred.get("start_time_normalized"))
        if not predicted_at or not match_start:
            skips["invalid_datetime"] += 1
            continue
        if predicted_at >= match_start:
            skips["prediction_after_start"] += 1
            continue

        hours_before = (match_start - predicted_at).total_seconds() / 3600.0
        if hours_before < 0:
            skips["prediction_after_start"] += 1
            continue
        horizon = _horizon_label(hours_before)
        if not horizon:
            skips["outside_horizon"] += 1
            continue

        prob_a = float(pred["prob_a"])
        model_key = "hybrid" if pred["model_name"] == THESIS_HYBRID_MODEL_NAME else "thesis"
        model_label = "Hybrid model" if model_key == "hybrid" else "Thesis model"
        books_for_match = [key for key in odds_by_match_book.keys() if key[0] == match_id]
        if not books_for_match:
            skips["no_odds_for_match"] += 1
            continue

        had_fresh_odds = False
        had_positive_ev = False
        had_closing = False
        for key in books_for_match:
            rows = odds_by_match_book[key]
            entry = _latest_before(rows, predicted_at)
            if not entry:
                continue
            entry_age_hours = (predicted_at - entry["scraped_dt"]).total_seconds() / 3600.0
            if entry_age_hours < 0 or entry_age_hours > max_odds_age_hours:
                continue
            had_fresh_odds = True

            odds_a = float(entry["canonical_odds_a"])
            odds_b = float(entry["canonical_odds_b"])
            try:
                best = best_ev_side(prob_a, odds_a, odds_b, tax_rate=tax_rate, min_ev=min_ev)
            except ValueError:
                skips["invalid_entry_odds"] += 1
                continue
            if not best:
                continue
            had_positive_ev = True

            closing = _latest_before(rows, match_start)
            if not closing:
                continue
            had_closing = True
            side = str(best["side"])
            taken_odds = float(best["odds"])
            closing_odds = float(closing["canonical_odds_a"] if side == "a" else closing["canonical_odds_b"])
            if taken_odds <= 1.0 or closing_odds <= 1.0:
                skips["invalid_closing_odds"] += 1
                continue

            entries.append({
                "model_key": model_key,
                "model_label": model_label,
                "model_name": pred["model_name"],
                "model_version": pred["model_version"],
                "prediction_id": pred["prediction_id"],
                "canonical_match_id": match_id,
                "bookmaker_id": key[1],
                "bookmaker_name": entry.get("bookmaker_name"),
                "horizon_label": horizon[0],
                "hours_start": horizon[1],
                "hours_end": None if horizon[2] >= 9999 else horizon[2],
                "hours_before": hours_before,
                "entry_age_hours": entry_age_hours,
                "side": side,
                "taken_odds": taken_odds,
                "closing_odds": closing_odds,
                "ev": float(best["ev"]),
                "model_prob": float(best["model_prob"]),
                "market_prob": float(best["market_prob"]),
                "clv_odds_pct": clv_odds_pct(taken_odds, closing_odds),
                "clv_probability_pp": clv_probability_points(taken_odds, closing_odds),
                "predicted_at": predicted_at.isoformat(),
                "entry_scraped_at": entry["scraped_dt"].isoformat(),
                "closing_scraped_at": closing["scraped_dt"].isoformat(),
            })

        if not had_fresh_odds:
            skips["no_fresh_entry_odds"] += 1
        elif not had_positive_ev:
            skips["no_positive_ev"] += 1
        elif not had_closing:
            skips["no_closing_odds"] += 1

    bins = _aggregate_clv_entries_match_oriented(entries)

    return {
        "metadata": {
            "max_days_back": max_days_back,
            "max_odds_age_hours": max_odds_age_hours,
            "tax_rate": tax_rate,
            "min_ev": min_ev,
            "aggregation_level": "model_match_horizon",
            "entry_definition": "latest bookmaker odds at or before prediction time, max_age_hours constrained",
            "closing_definition": "latest valid non-live same-bookmaker pre-match odds",
            "clv_odds_pct_definition": "taken_odds / closing_odds - 1; positive means entry beat closing",
            "aggregation_definition": "all EV entries for the same model, canonical match and horizon are collapsed into one match-level observation before averaging",
        },
        "total_predictions_scanned": len(predictions),
        "total_entries": len(entries),
        "models": [
            {
                "model_key": key,
                "model_label": "Hybrid model" if key == "hybrid" else "Thesis model",
                "bins": [b for b in bins if b["model_key"] == key],
            }
            for key in ("thesis", "hybrid")
        ],
        "bins": bins,
        "skips": dict(sorted(skips.items())),
    }


def _horizon_label(hours_before: float) -> tuple[str, int, int] | None:
    for label, hmin, hmax in HORIZON_BIN_DEFS:
        if hmin <= hours_before < hmax:
            return label, hmin, hmax
    return None


def _latest_before(rows: list[dict[str, Any]], timestamp: datetime) -> dict[str, Any] | None:
    latest = None
    for row in rows:
        if row["scraped_dt"] <= timestamp:
            latest = row
        else:
            break
    return latest


def _mean(values: list[float]) -> float | None:
    return round(float(np.mean(values)), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(float(np.median(values)), 4) if values else None


def _aggregate_clv_entries_match_oriented(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate CLV as one observation per model/match/horizon.

    Odds snapshots and bookmakers can generate many EV opportunities for the same
    match. For model evaluation we collapse them first, so no match can dominate a
    horizon bin only because it had many scraped prices.
    """
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        grouped[(entry["model_key"], entry["horizon_label"], int(entry["canonical_match_id"]))].append(entry)

    rows: list[dict[str, Any]] = []
    for (_model_key, _label, match_id), group in grouped.items():
        first = group[0]
        rows.append({
            "model_key": first["model_key"],
            "model_label": first["model_label"],
            "horizon_label": first["horizon_label"],
            "hours_start": first["hours_start"],
            "hours_end": first["hours_end"],
            "canonical_match_id": match_id,
            "entries": len(group),
            "clv_odds_pct": float(np.mean([g["clv_odds_pct"] for g in group])),
            "clv_probability_pp": float(np.mean([g["clv_probability_pp"] for g in group])),
            "ev": float(np.mean([g["ev"] for g in group])),
            "hours_before": float(np.mean([g["hours_before"] for g in group])),
        })

    grouped_bins: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped_bins[(row["model_key"], row["horizon_label"])].append(row)

    order = {label: i for i, (label, _, _) in enumerate(HORIZON_BIN_DEFS)}
    result: list[dict[str, Any]] = []
    for (model_key, label), group in grouped_bins.items():
        first = group[0]
        clv_vals = [float(g["clv_odds_pct"]) for g in group]
        clv_pp_vals = [float(g["clv_probability_pp"]) for g in group]
        ev_vals = [float(g["ev"]) for g in group]
        match_ids = {int(g["canonical_match_id"]) for g in group}
        entry_count = sum(int(g.get("entries", 1)) for g in group)
        result.append({
            "model_key": model_key,
            "model_label": first["model_label"],
            "label": label,
            "hours_start": first["hours_start"],
            "hours_end": first["hours_end"],
            "entry_count": entry_count,
            "match_count": len(match_ids),
            "observation_count": len(group),
            "avg_hours_before": _mean([float(g["hours_before"]) for g in group]),
            "avg_clv_odds_pct": _mean(clv_vals),
            "median_clv_odds_pct": _median(clv_vals),
            "avg_clv_probability_pp": _mean(clv_pp_vals),
            "median_clv_probability_pp": _median(clv_pp_vals),
            "positive_clv_rate": round(sum(1 for v in clv_vals if v > 0) / len(clv_vals), 4) if clv_vals else None,
            "avg_ev": _mean(ev_vals),
            "aggregation_level": "model_match_horizon",
        })

    return sorted(result, key=lambda b: (b["model_key"], order.get(b["label"], 999)))


def _empty_clv_result(max_days_back: int, max_odds_age_hours: float, tax_rate: float, min_ev: float) -> dict:
    return {
        "metadata": {
            "max_days_back": max_days_back,
            "max_odds_age_hours": max_odds_age_hours,
            "tax_rate": tax_rate,
            "min_ev": min_ev,
            "aggregation_level": "model_match_horizon",
        },
        "total_predictions_scanned": 0,
        "total_entries": 0,
        "models": [],
        "bins": [],
        "skips": {},
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


def _compute_model_reference_metrics(db, cutoff: str, min_matches: int = 10) -> tuple[list[dict], list[dict]]:
    """Compute overall LogLoss & AUC for each registered prediction model.

    For pure models (thesis, operational): returns single LogLoss/AUC values.
    For hybrid models: returns per-bin metrics computed dynamically using
    thesis_prob + market_prob from each time bin.

    Returns:
        tuple of (pure_model_refs, hybrid_model_bins)
    """
    refs: list[dict] = []
    hybrid_bins: list[dict] = []

    # Bin definitions (interval, same as in horizon_accuracy)
    BIN_DEFS = [
        ("0-2h",     0,   2),
        ("2-6h",     2,   6),
        ("6-12h",    6,  12),
        ("12-24h",  12,  24),
        ("24-48h",  24,  48),
        ("48h+",    48, 9999),
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
                db, cutoff, model_name, model_version, BIN_DEFS, min_matches
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
    db, cutoff: str, model_name: str, model_version: str, bin_defs: list, min_matches: int = 10
) -> list[dict]:
    """Compute hybrid model metrics per time bin dynamically.
    
    For each bin:
    1. Get thesis model predictions for finished matches
    2. Get average market probabilities from odds_snapshots in that bin
    3. Compute hybrid_prob exactly like production:
       alpha * temperature(thesis_prob) + (1-alpha) * market_prob
    4. Calculate LogLoss/AUC for that bin
    
    Returns list of bin dicts with metrics.
    """
    # Extract alpha and temperature from model_version (format: "a0.05-t0.80")
    alpha = THESIS_HYBRID_ALPHA  # default
    temperature = THESIS_HYBRID_TEMPERATURE  # default
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
        
        # Get thesis probability and apply temperature to the model side.
        # This mirrors generate_thesis_hybrid_predictions(); temperature is
        # not applied to the market probability.
        thesis_prob_a = match_thesis[mid]
        thesis_prob_a_t = apply_temperature_probability(thesis_prob_a, temperature)
        
        # Compute hybrid probability
        hybrid_prob_a = alpha * thesis_prob_a_t + (1 - alpha) * market_prob_a
        
        # Ground truth
        winner_side = str(meta.get("winner_side") or "")
        if winner_side not in ("team_a", "team_b"):
            continue
        
        y_true = 1 if winner_side == "team_a" else 0
        y_score = hybrid_prob_a
        
        # Find bin — interval: snapshot counts only in its exact time window.
        for label, hmin, hmax in bin_defs:
            if hmin <= hours_before < hmax:
                bd = bin_data[label]
                md = bd["per_match"][mid]
                bookmaker_key = snap.get("bookmaker_id") or "unknown"
                md["y_true"] = y_true
                md["bookmaker_scores"][bookmaker_key].append(y_score)
                bd["snapshot_count"] += 1
                break
    
    # Compute metrics per bin
    result_bins = []
    for label, hmin, hmax in bin_defs:
        bd = bin_data[label]
        per_match = bd["per_match"]
        n_matches = len(per_match)
        n_snapshots = bd["snapshot_count"]
        
        if n_matches < min_matches:
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


def _metric_summary(y_true: list[int], y_prob: list[float]) -> dict:
    """Shared compact metric payload for model/market comparisons."""
    return {
        "n_matches": len(y_true),
        "avg_logloss": _compute_logloss(y_true, y_prob),
        "avg_auc": _compute_auc(y_true, y_prob),
        "avg_brier": _compute_brier(y_true, y_prob),
        "accuracy": _compute_accuracy(y_true, y_prob),
    }


def _compute_market_close_comparison(db, cutoff: str, min_matches: int) -> dict:
    """Compare thesis/hybrid against collected bookmaker closing odds.

    This is the headline production-health check for the Horizon page. It uses
    a strict market-close sample: for every finished match, take each
    bookmaker's latest non-live snapshot with scraped_at <= match start, align
    it to canonical sides, remove margin, then average bookmaker probabilities
    per match. Model, market, and hybrid metrics are computed on exactly the
    same match set.
    """
    preds = query_df(
        db,
        """
        WITH ranked AS (
            SELECT cp.canonical_match_id, cp.prob_a AS thesis_prob_a,
                   cm.winner_side, cm.start_time_normalized,
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
              AND cm.start_time_normalized IS NOT NULL
              AND cm.start_time_normalized > :cutoff
        )
        SELECT canonical_match_id, thesis_prob_a, winner_side,
               start_time_normalized, normalized_team_a, normalized_team_b
        FROM ranked
        WHERE rn = 1
        """,
        {"mname": THESIS_MODEL_NAME, "mver": THESIS_MODEL_VERSION, "cutoff": cutoff},
    )
    pred_map = {
        p["canonical_match_id"]: p
        for p in preds
        if p.get("thesis_prob_a") is not None
        and 0 < float(p.get("thesis_prob_a")) < 1
        and str(p.get("winner_side") or "") in ("team_a", "team_b")
    }
    if not pred_map:
        return _empty_market_close_comparison()

    match_ids = list(pred_map.keys())
    placeholders = ",".join(f":mid{i}" for i in range(len(match_ids)))
    params = {f"mid{i}": mid for i, mid in enumerate(match_ids)}

    snapshots = query_df(
        db,
        f"""
        SELECT os.canonical_match_id, os.scraped_at, os.bookmaker_id,
               b.name AS bookmaker_name,
               os.odds_a, os.odds_b, os.raw_team_a, os.raw_team_b
        FROM odds_snapshots os
        JOIN bookmakers b ON b.id = os.bookmaker_id
        WHERE os.canonical_match_id IN ({placeholders})
          AND os.market_type = 'match_winner'
          AND COALESCE(os.is_live, 0) = 0
          AND os.odds_a IS NOT NULL
          AND os.odds_b IS NOT NULL
        ORDER BY os.canonical_match_id, os.bookmaker_id, os.scraped_at DESC
        """,
        params,
    )

    # Keep only one latest pre-match snapshot per match/bookmaker.
    close_by_match_book: dict[int, dict[Any, dict]] = defaultdict(dict)
    for snap in snapshots:
        mid = snap["canonical_match_id"]
        meta = pred_map.get(mid)
        if not meta:
            continue
        match_start = _parse_dt(meta.get("start_time_normalized"))
        scraped = _parse_dt(snap.get("scraped_at"))
        if not match_start or not scraped or scraped > match_start:
            continue
        bookmaker_key = snap.get("bookmaker_id") or "unknown"
        prev = close_by_match_book[mid].get(bookmaker_key)
        prev_dt = _parse_dt(prev.get("scraped_at")) if prev else None
        if prev is None or (prev_dt is not None and scraped > prev_dt):
            close_by_match_book[mid][bookmaker_key] = snap

    rows: list[dict] = []
    bookmaker_probs: dict[int, dict[str, Any]] = defaultdict(lambda: {
        "bookmaker_name": None,
        "y_true": [],
        "y_prob": [],
    })
    alpha = THESIS_HYBRID_ALPHA
    temperature = THESIS_HYBRID_TEMPERATURE

    for mid, meta in pred_map.items():
        per_book_probs: list[float] = []
        for bk_id, snap in close_by_match_book.get(mid, {}).items():
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
            market_prob_a, _ = _remove_margin(_implied_prob(odds_a), _implied_prob(odds_b))
            per_book_probs.append(market_prob_a)
            if isinstance(bk_id, int):
                y_true_bk = 1 if str(meta.get("winner_side") or "") == "team_a" else 0
                bookmaker_probs[bk_id]["bookmaker_name"] = snap.get("bookmaker_name")
                bookmaker_probs[bk_id]["y_true"].append(y_true_bk)
                bookmaker_probs[bk_id]["y_prob"].append(market_prob_a)

        if not per_book_probs:
            continue

        y_true = 1 if str(meta.get("winner_side") or "") == "team_a" else 0
        thesis_prob = float(meta["thesis_prob_a"])
        market_prob = float(np.mean(per_book_probs))
        thesis_prob_t = apply_temperature_probability(thesis_prob, temperature)
        hybrid_prob = alpha * thesis_prob_t + (1.0 - alpha) * market_prob
        rows.append({
            "match_id": mid,
            "y_true": y_true,
            "thesis_prob": thesis_prob,
            "market_prob": market_prob,
            "hybrid_prob": hybrid_prob,
            "bookmaker_count": len(per_book_probs),
        })

    if not rows:
        return _empty_market_close_comparison()

    y_true = [int(r["y_true"]) for r in rows]
    thesis = [float(r["thesis_prob"]) for r in rows]
    market = [float(r["market_prob"]) for r in rows]
    hybrid = [float(r["hybrid_prob"]) for r in rows]

    competitors = [
        {"name": "MODEL", "display_name": "Thesis model", **_metric_summary(y_true, thesis)},
        {"name": "MARKET_CLOSE", "display_name": "Bookmaker consensus close", **_metric_summary(y_true, market)},
        {"name": "HYBRID", "display_name": "Hybrid thesis+market", **_metric_summary(y_true, hybrid)},
    ]
    competitors.sort(key=lambda r: r["avg_logloss"] if r["avg_logloss"] is not None else 999.0)
    for i, row in enumerate(competitors, start=1):
        row["rank"] = i

    model_ll = next((r["avg_logloss"] for r in competitors if r["name"] == "MODEL"), None)
    market_ll = next((r["avg_logloss"] for r in competitors if r["name"] == "MARKET_CLOSE"), None)
    hybrid_ll = next((r["avg_logloss"] for r in competitors if r["name"] == "HYBRID"), None)
    delta_vs_market = None if model_ll is None or market_ll is None else round(float(model_ll - market_ll), 4)

    bookmaker_rows = []
    for bk_id, data in bookmaker_probs.items():
        bk_y = data["y_true"]
        bk_p = data["y_prob"]
        if len(bk_y) < min_matches:
            continue
        bookmaker_rows.append({
            "bookmaker_id": bk_id,
            "bookmaker_name": data.get("bookmaker_name") or f"bookmaker_{bk_id}",
            **_metric_summary(bk_y, bk_p),
        })
    bookmaker_rows.sort(key=lambda r: r["avg_logloss"] if r["avg_logloss"] is not None else 999.0)
    for i, row in enumerate(bookmaker_rows, start=1):
        row["rank"] = i

    status = "unknown"
    if delta_vs_market is not None:
        if delta_vs_market <= -0.01:
            status = "model_better"
        elif delta_vs_market <= 0.01:
            status = "model_on_market_level"
        else:
            status = "model_worse"

    return {
        "sample_definition": "latest non-live pre-match snapshot per bookmaker; averaged per match; identical match sample for model/market/hybrid",
        "n_matches": len(rows),
        "min_matches": min_matches,
        "avg_bookmakers_per_match": round(float(np.mean([r["bookmaker_count"] for r in rows])), 2),
        "model_delta_logloss_vs_market": delta_vs_market,
        "hybrid_delta_logloss_vs_market": None if hybrid_ll is None or market_ll is None else round(float(hybrid_ll - market_ll), 4),
        "status": status,
        "competitors": competitors,
        "bookmakers": bookmaker_rows,
    }


def _empty_market_close_comparison() -> dict:
    return {
        "sample_definition": "latest non-live pre-match snapshot per bookmaker; averaged per match; identical match sample for model/market/hybrid",
        "n_matches": 0,
        "min_matches": 0,
        "avg_bookmakers_per_match": None,
        "model_delta_logloss_vs_market": None,
        "hybrid_delta_logloss_vs_market": None,
        "status": "no_data",
        "competitors": [],
        "bookmakers": [],
    }


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
        "model_vs_bookmaker_tests": [],
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
