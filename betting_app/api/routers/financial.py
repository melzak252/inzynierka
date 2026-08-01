"""Auditable financial simulation based on the strict EXP-060 backtest source."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from betting_app.api.deps import get_db, query_df
from betting_app.api.schemas import FinancialAnalysisResponse, FinancialBucket, FinancialLedgerEntry
from betting_app.core.ev import expected_value, fair_market_probabilities
from betting_app.services.canonical_match_service import align_snapshot_odds
from betting_app.services.market_service import kelly_fraction, none_or_float


router = APIRouter(prefix="/financial", tags=["financial"])

TAX_RATE = 0.12
BACKTEST_FEATURES_VERSION = "exp060-db-backfill-v1"
THESIS_MODEL_NAME = "Sym-Cal LR-ElasticNet-W20-Binomial"
THESIS_MODEL_VERSION = "exp-039"
HYBRID_MODEL_NAME = "Hybrid-Thesis-Market"
HORIZONS: list[tuple[str, str, float, float | None]] = [
    ("0-2", "0–2 h", 0, 2),
    ("2-6", "2–6 h", 2, 6),
    ("6-12", "6–12 h", 6, 12),
    ("12-24", "12–24 h", 12, 24),
    ("24-48", "24–48 h", 24, 48),
    ("48+", "48 h+", 48, None),
]


def _parse_hybrid_version(version: str) -> tuple[float, float]:
    match = re.fullmatch(r"a([0-9.]+)-t([0-9.]+)", version or "")
    if not match:
        return 0.35, 0.80
    return float(match.group(1)), float(match.group(2))


def _temperature_probability(probability: float, temperature: float) -> float:
    probability = min(max(probability, 1e-6), 1 - 1e-6)
    logit = math.log(probability / (1 - probability))
    return 1 / (1 + math.exp(-logit / temperature))


def _pick_snapshot(rows: list[dict[str, Any]], odds_mode: str) -> dict[str, Any] | None:
    if not rows:
        return None
    if odds_mode == "open":
        return rows[0]
    if odds_mode == "mid":
        return rows[(len(rows) - 1) // 2]
    return rows[-1]


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _horizon(hours_before: float) -> tuple[str, str]:
    for key, label, low, high in HORIZONS:
        if hours_before >= low and (high is None or hours_before < high):
            return key, label
    return "unknown", "Brak czasu"


def _bucket(key: str, label: str, rows: list[dict[str, Any]]) -> FinancialBucket:
    staked = sum(float(row["stake"]) for row in rows)
    profit = sum(float(row["profit"]) for row in rows)
    clv = [float(row["clv_odds_pct"]) for row in rows if row["clv_odds_pct"] is not None]
    return FinancialBucket(
        key=key,
        label=label,
        bets=len(rows),
        staked=staked,
        profit=profit,
        roi=profit / staked if staked else None,
        hit_rate=sum(bool(row["won"]) for row in rows) / len(rows) if rows else None,
        avg_ev=sum(float(row["ev"]) for row in rows) / len(rows) if rows else None,
        avg_clv_odds_pct=sum(clv) / len(clv) if clv else None,
        median_clv_odds_pct=median(clv) if clv else None,
    )


@router.get("/analysis", response_model=FinancialAnalysisResponse)
def financial_analysis(
    days_back: int = 90,
    odds_mode: str = "close",
    model_name: str = HYBRID_MODEL_NAME,
    model_version: str = "a0.35-t0.80",
    min_ev: float = 0.0,
    staking_mode: str = "kelly",
    initial_bankroll: float = 1000.0,
    fixed_stake: float = 10.0,
    kelly_fraction_multiplier: float = 0.25,
    max_stake_pct: float = 0.05,
    data_scope: str = "live",
    db=Depends(get_db),
):
    """Simulate one highest-EV positive side per bookmaker/match.

    ``live`` uses only actual scheduled predictions and quotes observed after the
    prediction timestamp. ``retrospective`` is a research-only EXP-060 view.
    """
    odds_mode = odds_mode.lower().strip()
    if odds_mode not in {"open", "mid", "close"}:
        raise HTTPException(400, "odds_mode must be one of: open, mid, close")
    if staking_mode not in {"fixed", "kelly"}:
        raise HTTPException(400, "staking_mode must be fixed or kelly")
    if data_scope not in {"live", "retrospective"}:
        raise HTTPException(400, "data_scope must be live or retrospective")
    if not (0 <= min_ev < 2 and initial_bankroll > 0 and fixed_stake > 0):
        raise HTTPException(400, "Invalid financial simulation parameters")

    use_hybrid = model_name == HYBRID_MODEL_NAME
    if not use_hybrid and (model_name != THESIS_MODEL_NAME or model_version != THESIS_MODEL_VERSION):
        raise HTTPException(400, "Supported models are Hybrid-Thesis-Market/a*.t* and EXP-039")
    alpha, temperature = _parse_hybrid_version(model_version)
    min_dt = (datetime.now(UTC) - timedelta(days=min(days_back, 730))).isoformat(timespec="seconds")

    features_version = "thesis-exp039" if data_scope == "live" else BACKTEST_FEATURES_VERSION
    matches = query_df(db, """
        SELECT cm.id AS canonical_match_id, cm.team_a_name, cm.team_b_name, cm.league,
               cm.start_time_normalized, cm.winner_side, p.prob_a, p.prob_b, p.predicted_at
        FROM canonical_matches cm
        JOIN LATERAL (
          SELECT p1.prob_a, p1.prob_b, p1.predicted_at
          FROM canonical_predictions p1
          WHERE p1.canonical_match_id = cm.id
            AND p1.model_name = :thesis_name AND p1.model_version = :thesis_version
            AND p1.features_version = :features_version
            AND CAST(p1.predicted_at AS TEXT) <= REPLACE(cm.start_time_normalized, 'T', ' ')
          ORDER BY p1.predicted_at DESC NULLS LAST, p1.id DESC LIMIT 1
        ) p ON true
        WHERE cm.status = 'finished'
          AND REPLACE(cm.start_time_normalized, 'T', ' ') >= REPLACE(:min_dt, 'T', ' ')
          AND cm.winner_side IN ('team_a', 'team_b')
        ORDER BY cm.start_time_normalized, cm.id
    """, {
        "thesis_name": THESIS_MODEL_NAME, "thesis_version": THESIS_MODEL_VERSION,
        "features_version": features_version, "min_dt": min_dt,
    })
    if not matches:
        return FinancialAnalysisResponse(
            methodology="Brak meczów dla wybranego zakresu predykcji.", data_scope=data_scope, days_back=days_back,
            odds_mode=odds_mode, model_name=model_name, model_version=model_version,
            staking_mode=staking_mode, min_ev=min_ev, initial_bankroll=initial_bankroll,
            final_bankroll=initial_bankroll, total_bets=0, total_staked=0, total_profit=0,
        )

    ids = [int(row["canonical_match_id"]) for row in matches]
    odds_rows: list[dict[str, Any]] = []
    for offset in range(0, len(ids), 500):
        chunk = ids[offset:offset + 500]
        params = {f"id_{i}": value for i, value in enumerate(chunk)}
        placeholders = ",".join(f":id_{i}" for i in range(len(chunk)))
        odds_rows.extend(query_df(db, f"""
            SELECT os.canonical_match_id, os.bookmaker_id, b.name AS bookmaker,
                   os.raw_team_a, os.raw_team_b, os.odds_a, os.odds_b, os.scraped_at
            FROM odds_snapshots os JOIN bookmakers b ON b.id = os.bookmaker_id
            JOIN canonical_matches cm ON cm.id = os.canonical_match_id
            WHERE os.canonical_match_id IN ({placeholders})
              AND os.market_type = 'match_winner' AND COALESCE(os.is_live, 0) = 0
              AND os.odds_a IS NOT NULL AND os.odds_b IS NOT NULL AND os.scraped_at IS NOT NULL
              AND REPLACE(CAST(os.scraped_at AS TEXT), 'T', ' ') <= REPLACE(CAST(cm.start_time_normalized AS TEXT), 'T', ' ')
            ORDER BY os.canonical_match_id, os.bookmaker_id, os.scraped_at
        """, params))

    odds_by_key: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in odds_rows:
        odds_by_key[(int(row["canonical_match_id"]), int(row["bookmaker_id"]))].append(row)
    match_by_id = {int(row["canonical_match_id"]): row for row in matches}
    candidates: list[dict[str, Any]] = []
    for (match_id, _bookmaker_id), snapshots in odds_by_key.items():
        match = match_by_id[match_id]
        # A live backtest may only enter after this exact model prediction was
        # available. EXP-060 rows are intentionally left as research-only: they
        # were generated one minute before kick-off after the historical run.
        available = snapshots
        if data_scope == "live":
            predicted_at = _parse_time(match.get("predicted_at"))
            available = [row for row in snapshots if predicted_at is not None and (_parse_time(row.get("scraped_at")) or predicted_at) >= predicted_at]
        entry = _pick_snapshot(available, odds_mode)
        close = _pick_snapshot(available, "close")
        if not entry:
            continue
        aligned = align_snapshot_odds(match["team_a_name"] or "", match["team_b_name"] or "", entry["raw_team_a"] or "", entry["raw_team_b"] or "", entry["odds_a"], entry["odds_b"])
        close_aligned = align_snapshot_odds(match["team_a_name"] or "", match["team_b_name"] or "", close["raw_team_a"] or "", close["raw_team_b"] or "", close["odds_a"], close["odds_b"]) if close else None
        if not aligned:
            continue
        odds_a, odds_b = (none_or_float(aligned[0]), none_or_float(aligned[1]))
        if odds_a is None or odds_b is None or odds_a <= 1 or odds_b <= 1:
            continue
        base_a = none_or_float(match["prob_a"])
        if base_a is None:
            continue
        market_a, market_b = fair_market_probabilities(odds_a, odds_b)
        model_a = alpha * _temperature_probability(base_a, temperature) + (1 - alpha) * market_a if use_hybrid else base_a
        model_b = 1 - model_a
        ev_a, ev_b = expected_value(model_a, odds_a, TAX_RATE), expected_value(model_b, odds_b, TAX_RATE)
        if max(ev_a, ev_b) <= min_ev:
            continue
        side = "a" if ev_a >= ev_b else "b"
        entry_odds, model_prob, market_prob, ev = (odds_a, model_a, market_a, ev_a) if side == "a" else (odds_b, model_b, market_b, ev_b)
        close_odds = None
        if close_aligned:
            close_odds = none_or_float(close_aligned[0] if side == "a" else close_aligned[1])
        start_at, entry_at = _parse_time(match["start_time_normalized"]), _parse_time(entry["scraped_at"])
        hours_before = (start_at - entry_at).total_seconds() / 3600 if start_at and entry_at else None
        key, label = _horizon(hours_before) if hours_before is not None else ("unknown", "Brak czasu")
        candidates.append({
            "canonical_match_id": match_id, "start_time": match["start_time_normalized"], "league": match.get("league") or "Nieznana liga",
            "team_a_name": match.get("team_a_name"), "team_b_name": match.get("team_b_name"), "bookmaker": entry["bookmaker"],
            "side": side, "entry_odds": entry_odds, "close_odds": close_odds, "hours_before": hours_before,
            "horizon": key, "horizon_label": label, "model_prob": model_prob, "market_prob": market_prob, "ev": ev,
            "won": match["winner_side"] == ("team_a" if side == "a" else "team_b"), "entry_scraped_at": entry.get("scraped_at"),
            "close_scraped_at": close.get("scraped_at") if close else None,
            "clv_odds_pct": (entry_odds / close_odds - 1) if close_odds and close_odds > 0 else None,
        })

    candidates.sort(key=lambda row: (str(row["start_time"]), int(row["canonical_match_id"]), str(row["bookmaker"])))
    bankroll = initial_bankroll
    peak = bankroll
    max_drawdown = 0.0
    curve: list[dict[str, float | str | int | None]] = [{"index": 0, "bankroll": bankroll, "profit": 0.0, "start_time": None}]
    for index, row in enumerate(candidates, start=1):
        if staking_mode == "fixed":
            stake = min(fixed_stake, bankroll)
        else:
            full_kelly = kelly_fraction(float(row["model_prob"]), float(row["entry_odds"]), TAX_RATE)
            stake = min(bankroll * max_stake_pct, bankroll * full_kelly * kelly_fraction_multiplier)
        profit = stake * (float(row["entry_odds"]) * (1 - TAX_RATE) - 1) if row["won"] else -stake
        bankroll += profit
        peak = max(peak, bankroll)
        max_drawdown = max(max_drawdown, (peak - bankroll) / peak if peak else 0.0)
        row.update({"stake": stake, "profit": profit, "bankroll_after": bankroll})
        curve.append({"index": index, "bankroll": bankroll, "profit": profit, "start_time": row["start_time"], "canonical_match_id": row["canonical_match_id"]})

    groups: dict[str, dict[str, list[dict[str, Any]]]] = {"horizon": defaultdict(list), "bookmaker": defaultdict(list), "league": defaultdict(list)}
    labels: dict[str, str] = {}
    for row in candidates:
        groups["horizon"][str(row["horizon"])].append(row); labels[str(row["horizon"])] = str(row["horizon_label"])
        groups["bookmaker"][str(row["bookmaker"])].append(row)
        groups["league"][str(row["league"])].append(row)
    horizon_buckets = [_bucket(key, label, groups["horizon"].get(key, [])) for key, label, *_ in HORIZONS]
    horizon_buckets += [_bucket("unknown", "Brak czasu", groups["horizon"]["unknown"])] if groups["horizon"].get("unknown") else []
    bookmaker_buckets = sorted((_bucket(key, key, rows) for key, rows in groups["bookmaker"].items()), key=lambda item: item.roi or -999, reverse=True)
    league_buckets = sorted((_bucket(key, key, rows) for key, rows in groups["league"].items()), key=lambda item: item.bets, reverse=True)
    clv = [float(row["clv_odds_pct"]) for row in candidates if row["clv_odds_pct"] is not None]
    ledger = [FinancialLedgerEntry(**row) for row in candidates]
    total_staked = sum(float(row["stake"]) for row in candidates)
    total_profit = bankroll - initial_bankroll
    return FinancialAnalysisResponse(
        methodology=(
            "Zweryfikowany live ledger: wyłącznie predykcje thesis-exp039 zapisane przed meczem, a kurs wejścia musi być zebrany po czasie predykcji. "
            "CLV porównuje kurs wejścia z ostatnim kursem tego samego bukmachera przed startem."
            if data_scope == "live" else
            "ANALIZA BADAWCZA EXP-060: finalny model został przeliczony na historii. Nie jest to wykonalny backtest live i nie wolno interpretować ROI jako oczekiwanego zysku."
        ),
        data_scope=data_scope,
        days_back=days_back, odds_mode=odds_mode, model_name=model_name, model_version=model_version,
        staking_mode=staking_mode, min_ev=min_ev, initial_bankroll=initial_bankroll, final_bankroll=bankroll,
        total_bets=len(candidates), total_staked=total_staked, total_profit=total_profit,
        roi=total_profit / total_staked if total_staked else None,
        hit_rate=sum(bool(row["won"]) for row in candidates) / len(candidates) if candidates else None,
        max_drawdown_pct=max_drawdown, avg_clv_odds_pct=sum(clv) / len(clv) if clv else None,
        positive_clv_rate=sum(value > 0 for value in clv) / len(clv) if clv else None,
        horizon_buckets=horizon_buckets, bookmaker_buckets=bookmaker_buckets, league_buckets=league_buckets,
        bankroll_curve=curve, ledger=ledger,
    )
