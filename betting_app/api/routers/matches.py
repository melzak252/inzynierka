"""Router: /api/matches — upcoming match board and detail.

Uses SQLAlchemy text() with named parameters (:style).
Compatible with SQLite and PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import math
import os
import re
import secrets
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi import APIRouter, Depends, Header, HTTPException

from betting_app.api.deps import get_db, query_df, query_one
from betting_app.api.schemas import (
    AliasCreateRequest,
    AliasBlockRequest,
    AliasCreateResponse,
    AliasDeleteRequest,
    BookmakerOddsRow,
    GolggTeamsResponse,
    MatchBestOfUpdate,
    MatchBoardItem,
    MatchBoardResponse,
    MatchDetailResponse,
    MatchResultItem,
    MatchResultsResponse,
    MatchupSimulationRequest,
    MatchupSimulationResponse,
    PredictResponse,
    PredictionHistoryPoint,
    PredictionRow,
    RosterInfo,
    RosterPlayer,
    OddsHistoryPoint,
    TeamComparisonInfo,
    TeamMappingInfo,
    TeamRecentStats,
    UnmappedMatchItem,
    UnmappedMatchesResponse,
    GolggMatchCandidate,
    GolggMatchCandidatesResponse,
    MatchMappingRequest,
    MappingCheckResponse,
    MappingReviewDecisionRequest,
    MappingReviewDecisionResponse,
    MappingReviewItem,
    MappingReviewResponse,
    MatchRosterOverrideRequest,
    MatchRosterOverrideResponse,
)
from betting_app.services.canonical_match_service import align_snapshot_odds, competition_family
from betting_app.core.ev import fair_market_probabilities
from betting_app.services.market_service import (
    enrich_arbitrage,
    expected_value,
    kelly_fraction,
    none_or_float,
    safe_json_get,
)
from betting_app.services.mapping_service import suggest_mapping
from betting_app.services.current_roster_service import upsert_current_roster
from betting_app.core.db import is_sqlite
from betting_app.services.thesis_inference_service import EPSILON, _load_roster_overrides
from betting_app.services.upcoming_inference_service import (
    DEFAULT_HYBRID_ALPHA,
    DEFAULT_HYBRID_MODEL_NAME,
    DEFAULT_HYBRID_TEMPERATURE,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_VERSION,
    generate_hybrid_predictions,
    predict_operational_match,
)

router = APIRouter(prefix="/matches", tags=["matches"])


def _identity_review_token() -> str | None:
    environment_token = os.getenv("IDENTITY_REVIEW_TOKEN")
    if environment_token:
        return environment_token
    token_file = os.getenv("IDENTITY_REVIEW_TOKEN_FILE")
    if not token_file:
        return None
    try:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail="Identity review token file is unreadable",
        ) from exc
    return token or None


def _parse_bookmaker_ev_json(raw: Any) -> dict[str, Any]:
    """Parse bookmaker_ev_json from SQL into dict[str, BookmakerEvDetail]."""
    if not raw or not isinstance(raw, dict):
        return {}
    result: dict[str, Any] = {}
    for bk_name, bk_data in raw.items():
        if not isinstance(bk_data, dict):
            continue
        side_a = bk_data.get("side_a", {})
        side_b = bk_data.get("side_b", {})
        ev_a = none_or_float(side_a.get("ev"))
        odds_a = none_or_float(side_a.get("odds"))
        prob_a = none_or_float(side_a.get("model_prob"))
        ev_b = none_or_float(side_b.get("ev"))
        odds_b = none_or_float(side_b.get("odds"))
        prob_b = none_or_float(side_b.get("model_prob"))
        result[bk_name] = {
            "side_a": {
                "ev": ev_a, "odds": odds_a, "model_prob": prob_a,
                "kelly": kelly_fraction(prob_a, odds_a) if prob_a is not None and odds_a else None,
            },
            "side_b": {
                "ev": ev_b, "odds": odds_b, "model_prob": prob_b,
                "kelly": kelly_fraction(prob_b, odds_b) if prob_b is not None and odds_b else None,
            },
        }
    return result

TAX_RATE = 0.12
DEFAULT_MAX_ODDS_AGE_HOURS = 24.0
HYBRID_MODEL_NAME = DEFAULT_HYBRID_MODEL_NAME
HYBRID_MODEL_VERSION = (
    f"{DEFAULT_MODEL_VERSION}-a{DEFAULT_HYBRID_ALPHA:.2f}-t{DEFAULT_HYBRID_TEMPERATURE:.2f}"
)


def _parse_hybrid_version(version: str) -> tuple[float, float]:
    match = re.search(
        r"(?:^|-)a([0-9]+(?:\.[0-9]+)?)-t([0-9]+(?:\.[0-9]+)?)$",
        version,
    )
    if not match:
        return DEFAULT_HYBRID_ALPHA, DEFAULT_HYBRID_TEMPERATURE
    return float(match.group(1)), float(match.group(2))


def _temperature_probability(prob: float, temperature: float) -> float:
    p = min(max(float(prob), EPSILON), 1.0 - EPSILON)
    temp = max(float(temperature), 1e-6)
    z = math.log(p / (1.0 - p)) / temp
    return 1.0 / (1.0 + math.exp(-z))


def _finite_float(value: Any) -> float | None:
    number = none_or_float(value)
    if number is None or not math.isfinite(number):
        return None
    return number


def _pick_snapshot(rows: list[dict[str, Any]], odds_mode: str) -> dict[str, Any] | None:
    if not rows:
        return None
    ordered = sorted(rows, key=lambda r: str(r.get("scraped_at") or ""))
    mode = odds_mode.lower()
    if mode == "open":
        return ordered[0]
    if mode == "mid":
        return ordered[(len(ordered) - 1) // 2]
    # `close` and `latest` are the last non-live pre-match quote.
    return ordered[-1]


def _align(row: dict, n_a: str, n_b: str) -> tuple[float | None, float | None]:
    return align_snapshot_odds(
        n_a, n_b,
        str(row.get("raw_team_a") or ""),
        str(row.get("raw_team_b") or ""),
        row.get("odds_a"),
        row.get("odds_b"),
    )


# ── GET /matches ────────────────────────────────────────────────────────────


@router.get("", response_model=MatchBoardResponse)
def list_matches(
    min_books: int = 1,
    days_ahead: int = 14,
    tax_rate: float = TAX_RATE,
    stale_hours: float = 6,
    max_odds_age_hours: float = DEFAULT_MAX_ODDS_AGE_HOURS,
    bookmaker: str | None = None,
    db=Depends(get_db),
):
    now = datetime.now(UTC)
    max_dt = (now + timedelta(days=days_ahead)).isoformat(timespec="seconds")
    now_iso = now.isoformat(timespec="seconds")
    stale_cutoff = now - timedelta(hours=stale_hours)
    odds_cutoff = now - timedelta(hours=max_odds_age_hours)

    seen_cte = "" if is_sqlite() else """
        WITH seen_matches AS (
            SELECT DISTINCT canonical_match_id
            FROM upcoming_matches
            WHERE canonical_match_id IS NOT NULL
              AND (last_seen_at IS NULL OR last_seen_at > :stale_cutoff)
        ),
        """
    if is_sqlite():
        seen_cte = "WITH "
        seen_join = ""
    else:
        seen_join = "JOIN seen_matches sm ON sm.canonical_match_id=cm.id"

    odds = query_df(
        db,
        f"""
        {seen_cte}
        latest AS (
            SELECT os.*
            FROM odds_snapshots os
            JOIN (
                SELECT canonical_match_id, bookmaker_id, MAX(scraped_at) AS scraped_at
                FROM odds_snapshots
                WHERE market_type='match_winner' AND COALESCE(is_live,0)=0
                  AND canonical_match_id IS NOT NULL
                  AND scraped_at >= :odds_cutoff
                GROUP BY canonical_match_id, bookmaker_id
            ) lo ON lo.canonical_match_id=os.canonical_match_id
                 AND lo.bookmaker_id=os.bookmaker_id
                 AND lo.scraped_at=os.scraped_at
        )
        SELECT cm.id AS canonical_match_id,
               cm.team_a_name, cm.team_b_name,
               cm.normalized_team_a, cm.normalized_team_b,
               cm.start_time_normalized, cm.league, cm.best_of,
               b.name AS bookmaker,
               l.raw_team_a, l.raw_team_b,
               l.odds_a, l.odds_b,
               l.scraped_at, l.source_url,
               (
                   SELECT offer_url FROM upcoming_matches
                   WHERE canonical_match_id=l.canonical_match_id AND bookmaker_id=l.bookmaker_id
                   LIMIT 1
               ) AS offer_url
        FROM latest l
        JOIN canonical_matches cm ON cm.id=l.canonical_match_id
        {seen_join}
        JOIN bookmakers b ON b.id=l.bookmaker_id
        WHERE cm.start_time_normalized IS NOT NULL
          AND cm.status = 'upcoming'
          AND REPLACE(cm.start_time_normalized, 'T', ' ') > REPLACE(:now, 'T', ' ')
          AND REPLACE(cm.start_time_normalized, 'T', ' ') <= REPLACE(:max_dt, 'T', ' ')
        ORDER BY cm.start_time_normalized, cm.id
        """,
        {"now": now_iso, "max_dt": max_dt, "stale_cutoff": stale_cutoff, "odds_cutoff": odds_cutoff},
    )

    if not odds:
        return MatchBoardResponse(total=0, matches=[])

    # Align odds
    for row in odds:
        aligned = _align(row, str(row.get("normalized_team_a") or ""), str(row.get("normalized_team_b") or ""))
        row["_odds_a"] = aligned[0]
        row["_odds_b"] = aligned[1]

    # Group by match
    groups: dict[int, list[dict]] = {}
    for row in odds:
        groups.setdefault(row["canonical_match_id"], []).append(row)

    # Load predictions
    preds = query_df(
        db,
        """
        SELECT p.*
        FROM canonical_predictions p
        JOIN (
            SELECT canonical_match_id, model_name, model_version, MAX(predicted_at) AS predicted_at
            FROM canonical_predictions
            WHERE prediction_status='active'
              AND ((model_name=:hn AND model_version=:hv) OR (model_name=:sn AND model_version=:sv))
            GROUP BY canonical_match_id, model_name, model_version
        ) latest ON latest.canonical_match_id=p.canonical_match_id
                 AND latest.model_name=p.model_name
                 AND latest.model_version=p.model_version
                 AND latest.predicted_at=p.predicted_at
        """,
        {"hn": HYBRID_MODEL_NAME, "hv": HYBRID_MODEL_VERSION, "sn": DEFAULT_MODEL_NAME, "sv": DEFAULT_MODEL_VERSION},
    )
    pred_map: dict[int, dict] = {}
    for p in preds:
        mid = p["canonical_match_id"]
        item = pred_map.setdefault(mid, {})
        if p["model_name"] == HYBRID_MODEL_NAME:
            item["hybrid_prob_a"] = none_or_float(p.get("prob_a"))
            item["hybrid_prob_b"] = none_or_float(p.get("prob_b"))
        elif p["model_name"] == DEFAULT_MODEL_NAME:
            item["model_prob_a"] = none_or_float(p.get("prob_a"))
            item["model_prob_b"] = none_or_float(p.get("prob_b"))

    items: list[MatchBoardItem] = []
    for mid, group in groups.items():
        group = [g for g in group if g.get("_odds_a") is not None and g.get("_odds_b") is not None]
        if not group:
            continue
        books = len({g["bookmaker"] for g in group})

        # Filter by specific bookmaker if requested
        if bookmaker:
            bookmaker_group = [g for g in group if g["bookmaker"] == bookmaker]
            if not bookmaker_group:
                continue
            group = bookmaker_group
            books = 1  # only one bookmaker in view

        if books < min_books:
            continue

        best_a = max(group, key=lambda g: g["_odds_a"])
        best_b = max(group, key=lambda g: g["_odds_b"])
        avg_a = round(sum(g["_odds_a"] for g in group) / len(group), 3)
        avg_b = round(sum(g["_odds_b"] for g in group) / len(group), 3)

        record = {
            "best_odds_a": round(float(best_a["_odds_a"]), 3),
            "best_bookmaker_a": best_a["bookmaker"],
            "best_offer_url_a": best_a.get("offer_url"),
            "avg_odds_a": avg_a,
            "best_odds_b": round(float(best_b["_odds_b"]), 3),
            "best_bookmaker_b": best_b["bookmaker"],
            "best_offer_url_b": best_b.get("offer_url"),
            "avg_odds_b": avg_b,
        }
        enrich_arbitrage(record, tax_rate=tax_rate)

        team_a_name = group[0].get("team_a_name")
        team_b_name = group[0].get("team_b_name")
        team_a_golgg, team_a_conf, team_a_source = suggest_mapping(str(team_a_name)) if team_a_name else (None, 0.0, None)
        team_b_golgg, team_b_conf, team_b_source = suggest_mapping(str(team_b_name)) if team_b_name else (None, 0.0, None)
        has_unmapped_teams = not team_a_golgg or not team_b_golgg
        # Match confidence = min of both team mapping confidences (0-1 scale)
        match_confidence = min(team_a_conf, team_b_conf) if team_a_golgg and team_b_golgg else 0.0

        # Do not surface stale model probabilities/EV when either side is not
        # mapped to a GOL.GG team. Those predictions may have been computed
        # before mapping changed and would be misleading.
        p = {} if has_unmapped_teams else pred_map.get(mid, {})
        hybrid_ev_a = (
            expected_value(float(p["hybrid_prob_a"]), float(record["best_odds_a"]), tax_rate)
            if p.get("hybrid_prob_a") is not None else None
        )
        hybrid_ev_b = (
            expected_value(float(p["hybrid_prob_b"]), float(record["best_odds_b"]), tax_rate)
            if p.get("hybrid_prob_b") is not None else None
        )
        fusion_symaug_ev_a = (
            expected_value(float(p["fusion_symaug_prob_a"]), float(record["best_odds_a"]), tax_rate)
            if p.get("fusion_symaug_prob_a") is not None else None
        )
        fusion_symaug_ev_b = (
            expected_value(float(p["fusion_symaug_prob_b"]), float(record["best_odds_b"]), tax_rate)
            if p.get("fusion_symaug_prob_b") is not None else None
        )

        items.append(MatchBoardItem(
            canonical_match_id=mid,
            match=f"{team_a_name or '?'} vs {team_b_name or '?'}",
            league=group[0].get("league"),
            start_time_normalized=group[0].get("start_time_normalized"),
            best_of=group[0].get("best_of"),
            team_a_name=team_a_name,
            team_b_name=team_b_name,
            team_a_golgg_name=team_a_golgg,
            team_b_golgg_name=team_b_golgg,
            team_a_mapping_source=team_a_source,
            team_b_mapping_source=team_b_source,
            has_unmapped_teams=has_unmapped_teams,
            match_confidence=round(match_confidence, 4) if match_confidence < 1.0 else None,
            bookmaker_count=books,
            best_odds_a=record["best_odds_a"],
            best_bookmaker_a=record["best_bookmaker_a"],
            best_offer_url_a=record["best_offer_url_a"],
            avg_odds_a=record["avg_odds_a"],
            best_odds_b=record["best_odds_b"],
            best_bookmaker_b=record["best_bookmaker_b"],
            best_offer_url_b=record["best_offer_url_b"],
            avg_odds_b=record["avg_odds_b"],
            arb_no_tax=record.get("arb_no_tax", False),
            arb_after_tax=record.get("arb_after_tax", False),
            arb_margin_no_tax=record.get("arb_margin_no_tax"),
            arb_margin_after_tax=record.get("arb_margin_after_tax"),
            model_prob_a=p.get("model_prob_a"),
            model_prob_b=p.get("model_prob_b"),
            hybrid_prob_a=p.get("hybrid_prob_a"),
            hybrid_prob_b=p.get("hybrid_prob_b"),
            hybrid_ev_a=hybrid_ev_a,
            hybrid_ev_b=hybrid_ev_b,
            fusion_symaug_prob_a=p.get("fusion_symaug_prob_a"),
            fusion_symaug_prob_b=p.get("fusion_symaug_prob_b"),
            fusion_symaug_ev_a=fusion_symaug_ev_a,
            fusion_symaug_ev_b=fusion_symaug_ev_b,
            last_scraped_at=str(max(g["scraped_at"] for g in group if g.get("scraped_at"))),
        ))

    items.sort(key=lambda x: (x.start_time_normalized or "", x.canonical_match_id))
    return MatchBoardResponse(total=len(items), matches=items)


# ── GET /matches/results ────────────────────────────────────────────────────


@router.get("/results", response_model=MatchResultsResponse)
def list_results(
    days_back: int = 30,
    model_name: str = HYBRID_MODEL_NAME,
    model_version: str = HYBRID_MODEL_VERSION,
    odds_mode: str = "close",
    db=Depends(get_db),
):
    """Return finished matches with auditable EV results.

    Unlike the legacy implementation, this does not read precomputed
    model_ev_signals.  It recomputes EV from the requested model/version and a
    deterministic bookmaker quote selection: open/mid/close/latest.
    """
    odds_mode = odds_mode.lower().strip()
    if odds_mode not in {"open", "mid", "close", "latest"}:
        raise HTTPException(status_code=400, detail="odds_mode must be one of: open, mid, close, latest")

    now = datetime.now(UTC)
    min_dt = (now - timedelta(days=days_back)).isoformat(timespec="seconds")

    use_hybrid = model_name == HYBRID_MODEL_NAME
    prediction_model_name = DEFAULT_MODEL_NAME if use_hybrid else model_name
    prediction_model_version = DEFAULT_MODEL_VERSION if use_hybrid else model_version
    hybrid_alpha, hybrid_temperature = _parse_hybrid_version(model_version)

    match_rows = query_df(
        db,
        """
        SELECT cm.id AS canonical_match_id,
               cm.team_a_name, cm.team_b_name,
               cm.league, cm.start_time_normalized,
               cm.best_of, cm.status,
               cm.winner_name, cm.loser_name, cm.winner_side,
               cm.result_source, cm.result_recorded_at,
               gm.team1_score, gm.team2_score,
               p.id AS prediction_id, p.model_name AS prediction_model_name,
               p.model_version AS prediction_model_version,
               p.prob_a, p.prob_b
        FROM canonical_matches cm
        LEFT JOIN golgg_match_mappings gmm ON gmm.canonical_match_id = cm.id
        LEFT JOIN golgg_matches gm ON gm.match_id = gmm.golgg_match_id
        LEFT JOIN LATERAL (
            SELECT p1.*
            FROM canonical_predictions p1
            WHERE p1.canonical_match_id = cm.id
              AND p1.model_name = :prediction_model_name
              AND p1.model_version = :prediction_model_version
            ORDER BY CASE WHEN p1.prediction_status = 'active' THEN 0 ELSE 1 END,
                     p1.predicted_at DESC NULLS LAST,
                     p1.id DESC
            LIMIT 1
        ) p ON true
        WHERE cm.status = 'finished'
          AND REPLACE(cm.start_time_normalized, 'T', ' ') >= REPLACE(:min_dt, 'T', ' ')
        ORDER BY cm.start_time_normalized DESC, cm.id DESC
        """,
        {
            "min_dt": min_dt,
            "prediction_model_name": prediction_model_name,
            "prediction_model_version": prediction_model_version,
        },
    )

    if not match_rows:
        return MatchResultsResponse(
            total=0,
            days_back=days_back,
            model_name=model_name,
            model_version=model_version,
            odds_mode=odds_mode,
            results=[],
        )

    match_ids = [int(r["canonical_match_id"]) for r in match_rows]
    odds_rows: list[dict[str, Any]] = []
    # Avoid relying on array parameter support across drivers.
    for start in range(0, len(match_ids), 500):
        chunk = match_ids[start : start + 500]
        placeholders = ",".join(f":id_{i}" for i in range(len(chunk)))
        params = {f"id_{i}": mid for i, mid in enumerate(chunk)}
        odds_rows.extend(query_df(
            db,
            f"""
            SELECT os.id AS odds_snapshot_id, os.canonical_match_id, os.bookmaker_id,
                   b.name AS bookmaker, os.raw_team_a, os.raw_team_b,
                   os.odds_a, os.odds_b, os.scraped_at, os.offer_url
            FROM odds_snapshots os
            JOIN bookmakers b ON b.id = os.bookmaker_id
            JOIN canonical_matches cm ON cm.id = os.canonical_match_id
            WHERE os.canonical_match_id IN ({placeholders})
              AND os.market_type = 'match_winner'
              AND COALESCE(os.is_live, 0) = 0
              AND os.odds_a IS NOT NULL AND os.odds_b IS NOT NULL
              AND os.scraped_at IS NOT NULL
              AND REPLACE(CAST(os.scraped_at AS TEXT), 'T', ' ') <= REPLACE(CAST(cm.start_time_normalized AS TEXT), 'T', ' ')
            ORDER BY os.canonical_match_id, os.bookmaker_id, os.scraped_at
            """,
            params,
        ))

    odds_by_match_bookmaker: dict[tuple[int, int], list[dict[str, Any]]] = {}
    odds_by_match: dict[int, list[list[dict[str, Any]]]] = {}
    for row in odds_rows:
        key = (int(row["canonical_match_id"]), int(row["bookmaker_id"]))
        odds_by_match_bookmaker.setdefault(key, []).append(row)
    for (match_id, _bookmaker_id), snapshots in odds_by_match_bookmaker.items():
        odds_by_match.setdefault(match_id, []).append(snapshots)

    items: list[MatchResultItem] = []
    for r in match_rows:
        match_id = int(r["canonical_match_id"])
        base_prob_a = none_or_float(r.get("prob_a"))
        base_prob_b = none_or_float(r.get("prob_b"))

        bookmaker_ev_details: dict[str, Any] = {}
        bookmakers_with_ev: list[str] = []
        best_ev_a: float | None = None
        best_ev_b: float | None = None
        best_odds_a: float | None = None
        best_odds_b: float | None = None
        best_model_prob_a: float | None = None
        best_model_prob_b: float | None = None

        for snapshots in odds_by_match.get(match_id, []):
            selected = _pick_snapshot(snapshots, odds_mode)
            if selected is None:
                continue
            aligned = align_snapshot_odds(
                str(r.get("team_a_name") or ""),
                str(r.get("team_b_name") or ""),
                str(selected.get("raw_team_a") or ""),
                str(selected.get("raw_team_b") or ""),
                selected.get("odds_a"),
                selected.get("odds_b"),
            )
            if aligned is None:
                continue
            odds_a, odds_b = aligned
            odds_a = none_or_float(odds_a)
            odds_b = none_or_float(odds_b)
            if odds_a is None or odds_b is None or odds_a <= 1.0 or odds_b <= 1.0:
                continue
            market_prob_a, market_prob_b = fair_market_probabilities(odds_a, odds_b)

            if base_prob_a is None or base_prob_b is None:
                model_prob_a = None
                model_prob_b = None
            elif use_hybrid:
                thesis_prob_a = _temperature_probability(base_prob_a, hybrid_temperature)
                thesis_prob_b = 1.0 - thesis_prob_a
                model_prob_a = hybrid_alpha * thesis_prob_a + (1.0 - hybrid_alpha) * market_prob_a
                model_prob_b = hybrid_alpha * thesis_prob_b + (1.0 - hybrid_alpha) * market_prob_b
            else:
                model_prob_a = base_prob_a
                model_prob_b = base_prob_b

            ev_a = expected_value(model_prob_a, odds_a, TAX_RATE) if model_prob_a is not None else None
            ev_b = expected_value(model_prob_b, odds_b, TAX_RATE) if model_prob_b is not None else None
            bk_name = str(selected.get("bookmaker") or "?")
            if (ev_a is not None and ev_a > 0) or (ev_b is not None and ev_b > 0):
                bookmakers_with_ev.append(bk_name)
            if ev_a is not None and (best_ev_a is None or ev_a > best_ev_a):
                best_ev_a = ev_a
                best_odds_a = odds_a
                best_model_prob_a = model_prob_a
            if ev_b is not None and (best_ev_b is None or ev_b > best_ev_b):
                best_ev_b = ev_b
                best_odds_b = odds_b
                best_model_prob_b = model_prob_b
            bookmaker_ev_details[bk_name] = {
                "side_a": {
                    "ev": ev_a,
                    "odds": odds_a,
                    "model_prob": model_prob_a,
                    "market_prob": market_prob_a,
                    "kelly": kelly_fraction(model_prob_a, odds_a, TAX_RATE) if model_prob_a is not None else None,
                    "odds_snapshot_id": int(selected["odds_snapshot_id"]),
                    "scraped_at": selected.get("scraped_at"),
                },
                "side_b": {
                    "ev": ev_b,
                    "odds": odds_b,
                    "model_prob": model_prob_b,
                    "market_prob": market_prob_b,
                    "kelly": kelly_fraction(model_prob_b, odds_b, TAX_RATE) if model_prob_b is not None else None,
                    "odds_snapshot_id": int(selected["odds_snapshot_id"]),
                    "scraped_at": selected.get("scraped_at"),
                },
            }

        items.append(MatchResultItem(
            canonical_match_id=r["canonical_match_id"],
            team_a_name=r.get("team_a_name"),
            team_b_name=r.get("team_b_name"),
            league=r.get("league"),
            start_time_normalized=r.get("start_time_normalized"),
            best_of=r.get("best_of"),
            status=r.get("status"),
            winner_name=r.get("winner_name"),
            loser_name=r.get("loser_name"),
            winner_side=r.get("winner_side"),
            team_a_score=r.get("team1_score"),
            team_b_score=r.get("team2_score"),
            result_source=r.get("result_source"),
            result_recorded_at=str(r["result_recorded_at"]) if r.get("result_recorded_at") else None,
            best_ev_a=best_ev_a,
            best_ev_b=best_ev_b,
            best_odds_a=best_odds_a,
            best_odds_b=best_odds_b,
            model_prob_a=best_model_prob_a,
            model_prob_b=best_model_prob_b,
            kelly_a=kelly_fraction(best_model_prob_a, best_odds_a, TAX_RATE) if best_model_prob_a is not None and best_odds_a else None,
            kelly_b=kelly_fraction(best_model_prob_b, best_odds_b, TAX_RATE) if best_model_prob_b is not None and best_odds_b else None,
            bookmakers_with_ev=sorted(set(bookmakers_with_ev)),
            bookmaker_ev_details=bookmaker_ev_details,
            model_name=model_name,
            model_version=model_version,
            odds_mode=odds_mode,
        ))

    return MatchResultsResponse(
        total=len(items),
        days_back=days_back,
        model_name=model_name,
        model_version=model_version,
        odds_mode=odds_mode,
        results=items,
    )


# ── GET /matches/unmapped ───────────────────────────────────────────────────


@router.get("/unmapped", response_model=UnmappedMatchesResponse)
def list_unmapped_matches(
    status: str = "expired",
    limit: int = 100,
    db=Depends(get_db),
):
    """Return matches that are not yet mapped to GOL.GG."""
    rows = query_df(
        db,
        """
        SELECT cm.id AS canonical_match_id,
               cm.team_a_name, cm.team_b_name,
               cm.league, cm.start_time_normalized,
               cm.status,
               (
                   SELECT array_agg(DISTINCT b.name)
                   FROM odds_snapshots os
                   JOIN bookmakers b ON b.id = os.bookmaker_id
                   WHERE os.canonical_match_id = cm.id
               ) as bookmakers
        FROM canonical_matches cm
        LEFT JOIN golgg_match_mappings gmm ON gmm.canonical_match_id = cm.id
        WHERE gmm.canonical_match_id IS NULL
          AND cm.status = :status
        ORDER BY cm.start_time_normalized DESC
        LIMIT :limit
        """,
        {"status": status, "limit": limit},
    )

    items = []
    for r in rows:
        # PostgreSQL array_agg returns a string like "{sts,betclic}" or a list
        bks = r.get("bookmakers")
        if isinstance(bks, str):
            bks = [b.strip() for b in bks.strip("{}").split(",") if b.strip()]
        elif bks is None:
            bks = []

        mapping_context = {
            "source_system": "bookmaker",
            "league": r.get("league"),
            "match_date": r.get("start_time_normalized"),
        }
        team_a_golgg, team_a_confidence, team_a_source = suggest_mapping(
            r["team_a_name"],
            **mapping_context,
        )
        team_b_golgg, team_b_confidence, team_b_source = suggest_mapping(
            r["team_b_name"],
            **mapping_context,
        )
        
        items.append(UnmappedMatchItem(
            canonical_match_id=r["canonical_match_id"],
            team_a_name=r["team_a_name"],
            team_b_name=r["team_b_name"],
            team_a_mapping={
                "canonical_name": r["team_a_name"],
                "golgg_name": team_a_golgg,
                "confidence": team_a_confidence,
                "source": team_a_source,
            },
            team_b_mapping={
                "canonical_name": r["team_b_name"],
                "golgg_name": team_b_golgg,
                "confidence": team_b_confidence,
                "source": team_b_source,
            },
            league=r.get("league"),
            start_time_normalized=r.get("start_time_normalized"),
            status=r["status"],
            bookmakers=bks
        ))
    
    return UnmappedMatchesResponse(total=len(items), matches=items)


# ── GET/POST /matches/mapping-review ───────────────────────────────────────


@router.get("/mapping-review", response_model=MappingReviewResponse)
def list_mapping_review_items(limit: int = 100, db=Depends(get_db)):
    """Return existing result links that fail the conservative identity gate."""
    rows = query_df(
        db,
        """
        SELECT gmm.id AS mapping_id, gmm.canonical_match_id, gmm.golgg_match_id,
               gmm.confidence, gmm.mapped_by,
               cm.team_a_name AS canonical_team_a,
               cm.team_b_name AS canonical_team_b,
               cm.start_time_normalized, cm.league,
               gm.team1_name AS golgg_team_a, gm.team2_name AS golgg_team_b,
               gm.date AS golgg_date, gm.tournament_name AS golgg_competition,
               (SELECT COUNT(*) FROM canonical_predictions p
                WHERE p.canonical_match_id = cm.id) AS prediction_count,
               (SELECT COUNT(*) FROM upcoming_match_features f
                WHERE f.canonical_match_id = cm.id) AS feature_count,
               (SELECT COUNT(*) FROM model_ev_signals s
                WHERE s.canonical_match_id = cm.id) AS signal_count,
               (SELECT COUNT(*) FROM bets b
                WHERE b.canonical_match_id = cm.id) AS bet_count
        FROM golgg_match_mappings gmm
        JOIN canonical_matches cm ON cm.id = gmm.canonical_match_id
        JOIN golgg_matches gm ON gm.match_id = gmm.golgg_match_id
        ORDER BY cm.start_time_normalized DESC, cm.id DESC
        """,
    )
    items: list[MappingReviewItem] = []
    for row in rows:
        canonical_date = str(row.get("start_time_normalized") or "")[:10] or None
        golgg_date = str(row.get("golgg_date") or "")[:10] or None
        canonical_family = competition_family(row.get("league"))
        golgg_family = competition_family(row.get("golgg_competition"))
        confidence = float(row.get("confidence") or 0.0)
        reasons: list[str] = []
        if confidence < 0.95:
            reasons.append("confidence_below_0_95")
        if not canonical_date or not golgg_date:
            reasons.append("missing_date")
        elif canonical_date != golgg_date:
            reasons.append("date_mismatch")
        if canonical_family is None or golgg_family is None:
            reasons.append("unknown_competition_family")
        elif canonical_family != golgg_family:
            reasons.append("competition_conflict")
        if not reasons:
            continue
        items.append(
            MappingReviewItem(
                canonical_match_id=int(row["canonical_match_id"]),
                mapping_id=int(row["mapping_id"]),
                golgg_match_id=str(row["golgg_match_id"]),
                confidence=confidence,
                mapped_by=row.get("mapped_by"),
                canonical_team_a=row["canonical_team_a"],
                canonical_team_b=row["canonical_team_b"],
                canonical_date=canonical_date,
                canonical_competition=row.get("league"),
                golgg_team_a=row.get("golgg_team_a"),
                golgg_team_b=row.get("golgg_team_b"),
                golgg_date=golgg_date,
                golgg_competition=row.get("golgg_competition"),
                reasons=reasons,
                prediction_count=int(row.get("prediction_count") or 0),
                feature_count=int(row.get("feature_count") or 0),
                signal_count=int(row.get("signal_count") or 0),
                bet_count=int(row.get("bet_count") or 0),
            )
        )
        if len(items) >= limit:
            break
    return MappingReviewResponse(total=len(items), items=items)


@router.post("/mapping-review/decision", response_model=MappingReviewDecisionResponse)
def decide_mapping_review(
    body: MappingReviewDecisionRequest,
    review_token: str | None = Header(default=None, alias="X-Identity-Review-Token"),
    db=Depends(get_db),
):
    """Apply one operator-reviewed result-link decision atomically."""
    expected_token = _identity_review_token()
    if not expected_token:
        raise HTTPException(status_code=503, detail="Identity review mutations are disabled")
    if review_token is None or not secrets.compare_digest(review_token, expected_token):
        raise HTTPException(status_code=401, detail="Invalid identity review token")
    lock_suffix = "" if is_sqlite() else " FOR UPDATE OF cm"
    current = db.execute(
        text(
            """
            SELECT gmm.id AS mapping_id, gmm.golgg_match_id,
                   cm.team_a_name, cm.team_b_name, cm.start_time_normalized,
                   cm.league,
                   (SELECT COUNT(*) FROM bets b
                    WHERE b.canonical_match_id = cm.id) AS bet_count
            FROM canonical_matches cm
            LEFT JOIN golgg_match_mappings gmm ON gmm.canonical_match_id = cm.id
            WHERE cm.id = :canonical_match_id
            """
            + lock_suffix
        ),
        {"canonical_match_id": body.canonical_match_id},
    ).mappings().first()
    if current is None:
        raise HTTPException(status_code=404, detail="Canonical match not found")
    old_id = str(current["golgg_match_id"]) if current["golgg_match_id"] is not None else None
    new_id = body.new_golgg_match_id.strip() if body.new_golgg_match_id else None
    if body.decision == "replace" and not new_id:
        raise HTTPException(status_code=400, detail="replace requires new_golgg_match_id")
    if body.decision != "replace" and new_id:
        raise HTTPException(status_code=400, detail="new_golgg_match_id is only valid for replace")
    if body.decision in {"replace", "invalidate"} and int(current["bet_count"] or 0) > 0:
        raise HTTPException(
            status_code=409,
            detail="Mappings with recorded bets require a separate settlement review",
        )
    if body.decision == "replace":
        exists = db.execute(
            text("SELECT 1 FROM golgg_matches WHERE match_id = :match_id"),
            {"match_id": new_id},
        ).first()
        if exists is None:
            raise HTTPException(status_code=404, detail="Replacement GOL.GG match not found")

    evidence = json.dumps(dict(current), default=str, sort_keys=True)
    try:
        if body.decision == "retain":
            if old_id is None:
                raise HTTPException(status_code=409, detail="No mapping exists to retain")
            db.execute(
                text(
                    """
                    UPDATE golgg_match_mappings
                    SET confidence = 1.0, mapped_by = 'manual-reviewed-v1',
                        mapped_at = CURRENT_TIMESTAMP
                    WHERE canonical_match_id = :canonical_match_id
                    """
                ),
                {"canonical_match_id": body.canonical_match_id},
            )
            new_id = old_id
        elif body.decision == "replace":
            if old_id is None:
                db.execute(
                    text(
                        """
                        INSERT INTO golgg_match_mappings (
                            canonical_match_id, golgg_match_id, confidence,
                            mapped_by, mapped_at
                        ) VALUES (
                            :canonical_match_id, :golgg_match_id, 1.0,
                            'manual-reviewed-v1', CURRENT_TIMESTAMP
                        )
                        """
                    ),
                    {"canonical_match_id": body.canonical_match_id, "golgg_match_id": new_id},
                )
            else:
                db.execute(
                    text(
                        """
                        UPDATE golgg_match_mappings
                        SET golgg_match_id = :golgg_match_id, confidence = 1.0,
                            mapped_by = 'manual-reviewed-v1',
                            mapped_at = CURRENT_TIMESTAMP
                        WHERE canonical_match_id = :canonical_match_id
                        """
                    ),
                    {"canonical_match_id": body.canonical_match_id, "golgg_match_id": new_id},
                )
        else:
            db.execute(
                text("DELETE FROM golgg_match_mappings WHERE canonical_match_id = :canonical_match_id"),
                {"canonical_match_id": body.canonical_match_id},
            )
            new_id = None

        if body.decision in {"replace", "invalidate"}:
            db.execute(
                text(
                    """
                    UPDATE canonical_matches
                    SET status = 'expired', winner_name = NULL, loser_name = NULL,
                        winner_normalized = NULL, winner_side = NULL,
                        result_source = NULL, result_source_match_id = NULL,
                        result_recorded_at = NULL
                    WHERE id = :canonical_match_id
                    """
                ),
                {"canonical_match_id": body.canonical_match_id},
            )
        decision_id = db.execute(
            text(
                """
                INSERT INTO mapping_review_decisions (
                    canonical_match_id, old_golgg_match_id, new_golgg_match_id,
                    decision, reason, operator, evidence_json, decided_at
                ) VALUES (
                    :canonical_match_id, :old_golgg_match_id, :new_golgg_match_id,
                    :decision, :reason, :operator, :evidence_json, CURRENT_TIMESTAMP
                )
                RETURNING id
                """
            ),
            {
                "canonical_match_id": body.canonical_match_id,
                "old_golgg_match_id": old_id,
                "new_golgg_match_id": new_id,
                "decision": body.decision,
                "reason": body.reason.strip(),
                "operator": body.operator.strip(),
                "evidence_json": evidence,
            },
        ).scalar_one()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Replacement mapping conflicts with an existing reviewed link",
        ) from exc
    return MappingReviewDecisionResponse(
        decision_id=int(decision_id),
        canonical_match_id=body.canonical_match_id,
        decision=body.decision,
        old_golgg_match_id=old_id,
        new_golgg_match_id=new_id,
    )


# ── GET /matches/{id}/mapping-candidates ────────────────────────────────────


@router.get("/mapping-check/{golgg_id}", response_model=MappingCheckResponse)
def check_golgg_mapping(golgg_id: str, db=Depends(get_db)):
    """Check if a GOL.GG match ID is already mapped to any canonical match."""
    row = query_one(
        db,
        """
        SELECT cm.id, cm.team_a_name, cm.team_b_name, cm.start_time_normalized
        FROM golgg_match_mappings gmm
        JOIN canonical_matches cm ON cm.id = gmm.canonical_match_id
        WHERE gmm.golgg_match_id = :g_id
        """,
        {"g_id": golgg_id},
    )
    if row:
        return MappingCheckResponse(
            is_mapped=True,
            canonical_match_id=row["id"],
            team_a=row["team_a_name"],
            team_b=row["team_b_name"],
            start_time=row["start_time_normalized"],
        )
    return MappingCheckResponse(is_mapped=False)


@router.get("/{match_id}/mapping-candidates", response_model=GolggMatchCandidatesResponse)
def list_mapping_candidates(
    match_id: int,
    days_window: int = 3,
    db=Depends(get_db),
):
    """Suggest GOL.GG matches for a specific canonical match based on date and names."""
    meta = query_one(db, "SELECT start_time_normalized, team_a_name, team_b_name FROM canonical_matches WHERE id=:id", {"id": match_id})
    if not meta:
        raise HTTPException(status_code=404, detail="Match not found")

    start_time = meta["start_time_normalized"]
    if not start_time:
        return GolggMatchCandidatesResponse(candidates=[])

    # Search window
    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    min_date = (dt - timedelta(days=days_window)).date().isoformat()
    max_date = (dt + timedelta(days=days_window)).date().isoformat()

    # Get all GOL.GG matches in window
    candidates = query_df(
        db,
        """
        SELECT match_id, team1_name, team2_name, date, team1_win, team2_win
        FROM golgg_matches
        WHERE date >= :min_date AND date <= :max_date
        ORDER BY date DESC
        """,
        {"min_date": min_date, "max_date": max_date},
    )

    # Simple scoring/filtering could be added here, but for now return all in window
    items = [GolggMatchCandidate(**c) for c in candidates]
    return GolggMatchCandidatesResponse(candidates=items)


# ── POST /matches/map ───────────────────────────────────────────────────────


@router.post("/map")
def map_match_manually(body: MatchMappingRequest, db=Depends(get_db)):
    """Create a manual mapping between a canonical match and a GOL.GG match."""
    # 1. Fetch GOL.GG match info to sync best_of
    golgg_match = query_one(
        db,
        "SELECT best_of FROM golgg_matches WHERE match_id = :g_id",
        {"g_id": body.golgg_match_id}
    )
    best_of = golgg_match.get("best_of") if golgg_match else None

    # 2. Insert mapping
    db.execute(
        text("""
            INSERT INTO golgg_match_mappings (canonical_match_id, golgg_match_id)
            VALUES (:c_id, :g_id)
            ON CONFLICT (canonical_match_id) DO UPDATE SET golgg_match_id = EXCLUDED.golgg_match_id
        """),
        {"c_id": body.canonical_match_id, "g_id": body.golgg_match_id},
    )

    # 3. Update status and best_of
    db.execute(
        text("""
            UPDATE canonical_matches 
            SET status = 'finished',
                best_of = COALESCE(:best_of, best_of)
            WHERE id = :id AND status IN ('expired', 'upcoming')
        """),
        {"id": body.canonical_match_id, "best_of": best_of},
    )

    db.commit()
    return {"ok": True}


# ── POST /matches/alias — create team alias mapping ──────────────────────────


@router.post("/alias", response_model=AliasCreateResponse)
def create_alias(body: AliasCreateRequest, db=Depends(get_db)):
    """Create a context-scoped manual team alias."""
    from betting_app.services.mapping_service import upsert_alias, normalize_team_name
    from betting_app.services.team_alias_service import is_short_alias

    normalized = normalize_team_name(body.raw_name)
    if not normalized:
        raise HTTPException(status_code=400, detail="Normalized name is empty")
    if is_short_alias(body.raw_name) and not (
        body.league_pattern or body.valid_from or body.valid_to
    ):
        raise HTTPException(
            status_code=400,
            detail="Short aliases require a league or validity scope",
        )

    scoped = bool(
        body.source_system
        or body.league_pattern
        or body.valid_from
        or body.valid_to
    )
    alias_id = upsert_alias(
        body.raw_name,
        body.golgg_team_name,
        source="manual",
        confirmed=True,
        source_system=body.source_system,
        league_pattern=body.league_pattern,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        notes="Created through the operator mapping workflow",
    )

    return AliasCreateResponse(
        id=alias_id,
        normalized_name=normalized,
        alias=body.golgg_team_name,
        source="manual-scoped" if scoped else "manual",
    )


# ── GET /matches/golgg-teams — list/search GolGG teams ──────────────────────


@router.get("/golgg-teams", response_model=GolggTeamsResponse)
def list_golgg_teams(q: str = "", limit: int = 50, db=Depends(get_db)):
    """Return GolGG team names, optionally filtered by query string."""
    from betting_app.services.mapping_service import load_golgg_team_candidates

    all_teams = load_golgg_team_candidates()
    if q:
        q_lower = q.lower()
        filtered = [t for t in all_teams if q_lower in t.lower()]
    else:
        filtered = all_teams

    return GolggTeamsResponse(teams=filtered[:limit])


# ── DELETE /matches/alias — remove team alias mapping ───────────────────────


@router.delete("/alias")
def delete_alias_endpoint(body: AliasDeleteRequest, db=Depends(get_db)):
    """Delete a manual team alias mapping for the given raw_name."""
    from betting_app.services.mapping_service import delete_alias

    deleted = delete_alias(body.raw_name, source="manual")
    if not deleted:
        raise HTTPException(status_code=404, detail="No manual alias found for that team")
    return {"ok": True, "deleted": True}

# ── GET /matches/active-teams — list current active teams with rosters ────────


@router.get("/active-teams")
def get_active_teams(db=Depends(get_db)):
    """Return a curated list of active professional teams with recent matches."""
    from betting_app.services.rating_contract import OPERATIONAL_RATINGS_VERSION

    # Load teams with recent activity from entity_ratings
    rows = query_df(
        db,
        """
        SELECT entity_name, normalized_entity_name, rating_value, games_played, last_match_at
        FROM entity_ratings
        WHERE ratings_version = :version
          AND entity_type = 'team'
          AND rating_system = 'gl'
          AND games_played >= 5
          AND last_match_at IS NOT NULL
          AND SUBSTR(last_match_at, 1, 4) >= '2024'
        ORDER BY rating_value DESC
        LIMIT 150
        """,
        {"version": OPERATIONAL_RATINGS_VERSION},
    )
    if not rows:
        # Fallback to golgg_teams if entity_ratings is empty in dev.
        fallback_rows = query_df(
            db,
            """
            SELECT team_name AS entity_name, 1500.0 AS rating_value
            FROM golgg_teams
            LIMIT 100
            """,
        )
        teams = [
            {"name": str(row["entity_name"]), "rating": round(float(row["rating_value"]), 0)}
            for row in fallback_rows
        ]
        return {"teams": teams}

    teams = [
        {
            "name": str(row["entity_name"]),
            "rating": round(float(row["rating_value"]), 0)
            if row.get("rating_value") is not None
            else None,
            "games": int(row.get("games_played", 0)),
            "last_active": str(row.get("last_match_at") or "")[:10],
        }
        for row in rows
    ]
    return {"teams": teams}


# ── POST /matches/matchup — custom team vs team simulation ──────────────────


@router.post("/matchup", response_model=MatchupSimulationResponse)
def simulate_matchup(body: MatchupSimulationRequest, db=Depends(get_db)):
    """Simulate a hypothetical head-to-head matchup between any two teams."""
    from betting_app.services.upcoming_inference_service import (
        DEFAULT_FEATURE_VERSION,
        DEFAULT_MODEL_NAME,
        DEFAULT_MODEL_VERSION,
        DEFAULT_RATINGS_VERSION,
        DEFAULT_W20_VERSION,
        _normalized_best_of,
        build_features_for_match,
        predict_probability_from_features,
        series_probability,
    )

    best_of = _normalized_best_of(body.best_of)
    synthetic_match = {
        "id": 0,
        "team_a_name": body.team_a_name,
        "team_b_name": body.team_b_name,
        "league": body.league or "Custom Matchup",
        "start_time_normalized": datetime.now(UTC).isoformat(),
        "best_of": best_of,
    }

    feature_result = build_features_for_match(
        synthetic_match,
        feature_version=DEFAULT_FEATURE_VERSION,
        ratings_version=DEFAULT_RATINGS_VERSION,
        w20_version=DEFAULT_W20_VERSION,
        min_mapping_confidence=0.50,
        team_a_roster_override=body.team_a_roster_override,
        team_b_roster_override=body.team_b_roster_override,
        persist=False,
    )

    features = feature_result.get("features") or {}
    map_prob_a, components = predict_probability_from_features(features)
    series_prob_a = series_probability(map_prob_a, best_of)

    # Extract rosters and comparison info
    team_comparison = None
    recent_stats_a = None
    recent_stats_b = None
    roster_a_info = None
    roster_b_info = None

    ratings = features.get("ratings")
    mapping = features.get("mapping")
    if isinstance(ratings, dict):
        team_a_info = TeamMappingInfo(
            canonical_name=body.team_a_name,
            golgg_name=mapping.get("team_a_golgg_name") if isinstance(mapping, dict) else None,
            confidence=_finite_float(mapping.get("team_a_confidence")) if isinstance(mapping, dict) else None,
            source=mapping.get("team_a_source") if isinstance(mapping, dict) else None,
        )
        team_b_info = TeamMappingInfo(
            canonical_name=body.team_b_name,
            golgg_name=mapping.get("team_b_golgg_name") if isinstance(mapping, dict) else None,
            confidence=_finite_float(mapping.get("team_b_confidence")) if isinstance(mapping, dict) else None,
            source=mapping.get("team_b_source") if isinstance(mapping, dict) else None,
        )
        team_a_ratings = ratings.get("team_a") or {}
        team_b_ratings = ratings.get("team_b") or {}
        team_comparison = TeamComparisonInfo(
            team_a=team_a_info,
            team_b=team_b_info,
            team_a_rating=_finite_float(team_a_ratings.get("gl", {}).get("rating_value")),
            team_b_rating=_finite_float(team_b_ratings.get("gl", {}).get("rating_value")),
            rating_system="Glicko",
            team_a_elo=_finite_float(team_a_ratings.get("elo", {}).get("rating_value")),
            team_b_elo=_finite_float(team_b_ratings.get("elo", {}).get("rating_value")),
            team_a_glicko=_finite_float(team_a_ratings.get("gl", {}).get("rating_value")),
            team_b_glicko=_finite_float(team_b_ratings.get("gl", {}).get("rating_value")),
            team_a_glicko_rd=_finite_float(team_a_ratings.get("gl", {}).get("rd")),
            team_b_glicko_rd=_finite_float(team_b_ratings.get("gl", {}).get("rd")),
            rating_probabilities=features.get("ratings", {}).get("probabilities"),
        )

    w20 = features.get("w20")
    if isinstance(w20, dict):
        def make_stats(raw: Any) -> TeamRecentStats | None:
            if not isinstance(raw, dict):
                return None
            return TeamRecentStats(
                team_name=raw.get("team_name"),
                matches_count=int(raw.get("matches_count", 0)) if raw.get("matches_count") is not None else None,
                games_count=int(raw.get("games_count", 0)) if raw.get("games_count") is not None else None,
                win_rate=_finite_float(raw.get("win_rate")),
                avg_kills=_finite_float(raw.get("avg_kills")),
                avg_deaths=_finite_float(raw.get("avg_deaths")),
                avg_gd15=_finite_float(raw.get("avg_gd15")),
                avg_dragons=_finite_float(raw.get("avg_dragons")),
                avg_nashors=_finite_float(raw.get("avg_nashors")),
                avg_towers=_finite_float(raw.get("avg_towers")),
                avg_game_duration=_finite_float(raw.get("avg_game_duration")),
                last_match_at=raw.get("last_match_at"),
            )
        recent_stats_a = make_stats(w20.get("team_a"))
        recent_stats_b = make_stats(w20.get("team_b"))

    player_ratings = features.get("player_ratings")
    if isinstance(player_ratings, dict):
        def build_roster(side_key: str, name: str) -> RosterInfo:
            roster = player_ratings.get(f"{side_key}_roster") or {}
            roster_players = roster.get("players") or []
            side_dict = player_ratings.get(side_key) or {}
            gl_dict = side_dict.get("gl") or {}
            ratings_by_player_id = {
                str(player.get("player_id") or player.get("normalized_entity_name")): player
                for player in gl_dict.get("players") or []
                if player.get("player_id") or player.get("normalized_entity_name")
            }
            raw_players = roster_players or gl_dict.get("players") or []
            p_objs = []
            for player in raw_players:
                player_id = str(player.get("player_id") or player.get("normalized_entity_name") or "")
                rating = ratings_by_player_id.get(player_id, {})
                rating_value = rating.get("rating_value")
                if rating_value is None:
                    rating_value = player.get("rating_value")
                rating_rd = rating.get("rd")
                if rating_rd is None:
                    rating_rd = player.get("rd")
                games_played = rating.get("games_played")
                if games_played is None:
                    games_played = player.get("games_played")
                p_objs.append(
                    RosterPlayer(
                        player_id=player_id,
                        player_name=player.get("player_name")
                        or player.get("entity_name")
                        or rating.get("player_name")
                        or rating.get("entity_name"),
                        role=player.get("role") or rating.get("role"),
                        glicko_rating=_finite_float(rating_value),
                        glicko_rd=_finite_float(rating_rd),
                        games_played=int(games_played) if games_played is not None else None,
                    )
                )
            return RosterInfo(
                team_name=roster.get("team_name") or name,
                source_match_id=roster.get("source_match_id"),
                source_date=roster.get("source_match_date"),
                source_tournament=roster.get("source_tournament"),
                roster_source=roster.get("source"),
                avg_glicko=_finite_float(gl_dict.get("avg_rating_value")),
                avg_glicko_rd=_finite_float(gl_dict.get("avg_rd")),
                players_with_rating=(
                    int(gl_dict["players_with_rating"])
                    if gl_dict.get("players_with_rating") is not None
                    else None
                ),
                players=p_objs,
            )

        roster_a_info = build_roster("team_a", body.team_a_name)
        roster_b_info = build_roster("team_b", body.team_b_name)

    return MatchupSimulationResponse(
        team_a_name=body.team_a_name,
        team_b_name=body.team_b_name,
        best_of=best_of,
        map_prob_a=round(map_prob_a, 4),
        map_prob_b=round(1.0 - map_prob_a, 4),
        series_prob_a=round(series_prob_a, 4),
        series_prob_b=round(1.0 - series_prob_a, 4),
        model_name=DEFAULT_MODEL_NAME,
        model_version=DEFAULT_MODEL_VERSION,
        roster_a=roster_a_info,
        roster_b=roster_b_info,
        recent_stats_a=recent_stats_a,
        recent_stats_b=recent_stats_b,
        team_comparison=team_comparison,
        components=components,
    )


# ── POST /matches/alias/block — mark a team as blocked/unmapped ─────────────


@router.post("/alias/block")
def block_alias_endpoint(body: AliasBlockRequest, db=Depends(get_db)):
    """Mark a team name as blocked/unmapped."""
    from betting_app.services.mapping_service import block_alias

    block_alias(body.raw_name)
    return {"ok": True, "blocked": True}


# ── DELETE /matches/alias/block — unblock a team mapping marker ──────────────


@router.delete("/alias/block")
def unblock_alias_endpoint(body: AliasBlockRequest, db=Depends(get_db)):
    """Remove a blocked/unmapped marker for a team name."""
    from betting_app.services.mapping_service import unblock_alias

    unblocked = unblock_alias(body.raw_name)
    if not unblocked:
        raise HTTPException(status_code=404, detail="No block found for that team")
    return {"ok": True, "unblocked": True}


# ── GET /matches/{id} ───────────────────────────────────────────────────────


@router.get("/{match_id}", response_model=MatchDetailResponse)
def match_detail(
    match_id: int,
    stale_hours: float = 72,
    max_odds_age_hours: float = DEFAULT_MAX_ODDS_AGE_HOURS,
    db=Depends(get_db),
):
    meta = query_df(db, "SELECT * FROM canonical_matches WHERE id=:id", {"id": match_id})
    if not meta:
        raise HTTPException(status_code=404, detail="Match not found")
    m = meta[0]

    live_team_a = suggest_mapping(str(m.get("team_a_name"))) if m.get("team_a_name") else (None, 0.0, None)
    live_team_b = suggest_mapping(str(m.get("team_b_name"))) if m.get("team_b_name") else (None, 0.0, None)
    has_unmapped_teams = not live_team_a[0] or not live_team_b[0]

    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(hours=stale_hours)
    odds_cutoff = now - timedelta(hours=max_odds_age_hours)

    seen_cte = """WITH seen_matches AS (
            SELECT DISTINCT canonical_match_id
            FROM upcoming_matches
            WHERE canonical_match_id IS NOT NULL
              AND (last_seen_at IS NULL OR last_seen_at > :stale_cutoff)
        ),
        """
    seen_join = "JOIN seen_matches sm ON sm.canonical_match_id=l.canonical_match_id"
    if is_sqlite():
        seen_cte = "WITH "
        seen_join = ""

    odds = query_df(
        db,
        f"""
        {seen_cte}
        latest AS (
            SELECT os.*
            FROM odds_snapshots os
            JOIN (
                SELECT canonical_match_id, bookmaker_id, MAX(scraped_at) AS scraped_at
                FROM odds_snapshots
                WHERE canonical_match_id=:mid AND market_type='match_winner'
                  AND COALESCE(is_live,0)=0
                  AND scraped_at >= :odds_cutoff
                GROUP BY canonical_match_id, bookmaker_id
            ) lo ON lo.canonical_match_id=os.canonical_match_id
                 AND lo.bookmaker_id=os.bookmaker_id
                 AND lo.scraped_at=os.scraped_at
        )
        SELECT b.name AS bookmaker,
               l.raw_team_a, l.raw_team_b,
               l.odds_a, l.odds_b,
               l.scraped_at, l.source_url,
               (
                   SELECT offer_url FROM upcoming_matches
                   WHERE canonical_match_id=l.canonical_match_id AND bookmaker_id=l.bookmaker_id
                   LIMIT 1
               ) AS offer_url
        FROM latest l
        {seen_join}
        JOIN bookmakers b ON b.id=l.bookmaker_id
        ORDER BY b.name
        """,
        {"mid": match_id, "stale_cutoff": stale_cutoff, "odds_cutoff": odds_cutoff},
    )

    n_a = m.get("normalized_team_a") or ""
    n_b = m.get("normalized_team_b") or ""
    
    # Get hybrid prediction for EV/Kelly calculation
    hybrid_pred = query_df(
        db,
        """
        SELECT prob_a, prob_b
        FROM canonical_predictions
        WHERE canonical_match_id=:mid AND prediction_status='active'
          AND model_name=:hn AND model_version=:hv
        ORDER BY predicted_at DESC
        LIMIT 1
        """,
        {"mid": match_id, "hn": HYBRID_MODEL_NAME, "hv": HYBRID_MODEL_VERSION},
    )
    hybrid_prob_a = none_or_float(hybrid_pred[0].get("prob_a")) if hybrid_pred and not has_unmapped_teams else None
    hybrid_prob_b = none_or_float(hybrid_pred[0].get("prob_b")) if hybrid_pred and not has_unmapped_teams else None
    
    odds_rows: list[BookmakerOddsRow] = []
    for row in odds:
        aligned = _align(row, n_a, n_b)
        odds_a = aligned[0]
        odds_b = aligned[1]
        
        # Calculate EV and Kelly per bookmaker
        ev_a = expected_value(hybrid_prob_a, odds_a, TAX_RATE) if hybrid_prob_a is not None and odds_a else None
        ev_b = expected_value(hybrid_prob_b, odds_b, TAX_RATE) if hybrid_prob_b is not None and odds_b else None
        kelly_a = kelly_fraction(hybrid_prob_a, odds_a, TAX_RATE) if hybrid_prob_a is not None and odds_a else None
        kelly_b = kelly_fraction(hybrid_prob_b, odds_b, TAX_RATE) if hybrid_prob_b is not None and odds_b else None
        
        odds_rows.append(BookmakerOddsRow(
            bookmaker=row["bookmaker"],
            raw_team_a=row.get("raw_team_a"),
            raw_team_b=row.get("raw_team_b"),
            canonical_odds_a=odds_a,
            canonical_odds_b=odds_b,
            scraped_at=row.get("scraped_at"),
            source_url=row.get("source_url"),
            offer_url=row.get("offer_url"),
            ev_a=ev_a,
            ev_b=ev_b,
            kelly_a=kelly_a,
            kelly_b=kelly_b,
        ))

    preds = [] if has_unmapped_teams else query_df(
        db,
        """
        SELECT * FROM (
            SELECT DISTINCT ON (model_name, model_version) *
            FROM canonical_predictions
            WHERE canonical_match_id=:mid AND prediction_status='active'
              AND (
                  (model_name=:operational_name AND model_version=:operational_version)
                  OR (model_name=:hybrid_name AND model_version=:hybrid_version)
              )
            ORDER BY model_name, model_version, predicted_at DESC
        ) sub
        ORDER BY CASE WHEN model_name LIKE 'Hybrid%' THEN 0 ELSE 1 END, model_name
        """,
        {
            "mid": match_id,
            "operational_name": DEFAULT_MODEL_NAME,
            "operational_version": DEFAULT_MODEL_VERSION,
            "hybrid_name": HYBRID_MODEL_NAME,
            "hybrid_version": HYBRID_MODEL_VERSION,
        },
    )

    best_a = max((o.canonical_odds_a or 1) for o in odds_rows) if odds_rows else None
    best_b = max((o.canonical_odds_b or 1) for o in odds_rows) if odds_rows else None
    pred_rows: list[PredictionRow] = []
    for p in preds:
        pa = none_or_float(p.get("prob_a"))
        pb = none_or_float(p.get("prob_b"))
        pred_rows.append(PredictionRow(
            model_name=p.get("model_name", ""),
            model_version=p.get("model_version", ""),
            prob_a=pa,
            prob_b=pb,
            predicted_at=p.get("predicted_at"),
            ev_a=expected_value(pa, best_a, TAX_RATE) if pa is not None and best_a else None,
            ev_b=expected_value(pb, best_b, TAX_RATE) if pb is not None and best_b else None,
            kelly_a=kelly_fraction(pa, best_a, TAX_RATE) if pa is not None and best_a else None,
            kelly_b=kelly_fraction(pb, best_b, TAX_RATE) if pb is not None and best_b else None,
        ))

    # Rosters from features_json
    roster_a: RosterInfo | None = None
    roster_b: RosterInfo | None = None
    roster_a_is_manual = False
    roster_b_is_manual = False
    recent_stats_a: TeamRecentStats | None = None
    recent_stats_b: TeamRecentStats | None = None
    team_comparison: TeamComparisonInfo | None = None
    
    feat = query_df(
        db,
        """
        SELECT features_json FROM upcoming_match_features
        WHERE canonical_match_id=:mid ORDER BY id DESC LIMIT 1
        """,
        {"mid": match_id},
    )
    manual_rosters = _load_roster_overrides(match_id)
    roster_a_is_manual = "a" in manual_rosters
    roster_b_is_manual = "b" in manual_rosters
    if feat:
        f = feat[0].get("features_json")
        if isinstance(f, str):
            import json
            try:
                f = json.loads(f)
            except Exception:
                f = {}

        # Extract team mapping info
        mapping = safe_json_get(f, ["mapping"])
        if isinstance(mapping, dict):
            team_a_conf = none_or_float(mapping.get("team_a_confidence"))
            team_a_golgg = mapping.get("team_a_golgg_name")
            team_b_conf = none_or_float(mapping.get("team_b_confidence"))
            team_b_golgg = mapping.get("team_b_golgg_name")

            live_a = live_team_a
            live_b = live_team_b

            # Always trust live mapping status over stored features_json. Stored
            # features may contain stale fuzzy mappings produced before aliases
            # changed or fuzzy auto-mapping was disabled.
            if live_a[0]:
                team_a_golgg, team_a_conf, team_a_source = live_a
            elif live_a[2] == "blocked":
                team_a_golgg, team_a_conf = None, None
                team_a_source = "blocked"
            else:
                team_a_golgg, team_a_conf, team_a_source = None, None, None

            if live_b[0]:
                team_b_golgg, team_b_conf, team_b_source = live_b
            elif live_b[2] == "blocked":
                team_b_golgg, team_b_conf = None, None
                team_b_source = "blocked"
            else:
                team_b_golgg, team_b_conf, team_b_source = None, None, None

            team_a_info = TeamMappingInfo(
                canonical_name=m.get("team_a_name"),
                golgg_name=team_a_golgg,
                confidence=team_a_conf,
                source=team_a_source,
            )
            team_b_info = TeamMappingInfo(
                canonical_name=m.get("team_b_name"),
                golgg_name=team_b_golgg,
                confidence=team_b_conf,
                source=team_b_source,
            )
            
            # Get team ratings for comparison
            ratings = safe_json_get(f, ["ratings"])
            team_a_rating = None
            team_b_rating = None
            rating_system = None
            team_a_elo = team_b_elo = None
            team_a_glicko = team_b_glicko = None
            team_a_glicko_rd = team_b_glicko_rd = None
            team_a_games_played = team_b_games_played = None
            rating_probabilities: dict[str, float] = {}
            
            if isinstance(ratings, dict):
                team_a_ratings = ratings.get("team_a", {})
                team_b_ratings = ratings.get("team_b", {})
                probs = ratings.get("probabilities", {})
                if isinstance(probs, dict):
                    rating_probabilities = {
                        str(k): parsed
                        for k, v in probs.items()
                        if (parsed := _finite_float(v)) is not None
                    }

                if isinstance(team_a_ratings, dict) and isinstance(team_b_ratings, dict):
                    team_a_elo = _finite_float(safe_json_get(team_a_ratings, ["elo", "rating_value"]))
                    team_b_elo = _finite_float(safe_json_get(team_b_ratings, ["elo", "rating_value"]))
                    team_a_glicko = _finite_float(safe_json_get(team_a_ratings, ["gl", "rating_value"]))
                    team_b_glicko = _finite_float(safe_json_get(team_b_ratings, ["gl", "rating_value"]))
                    team_a_glicko_rd = _finite_float(safe_json_get(team_a_ratings, ["gl", "rd"]))
                    team_b_glicko_rd = _finite_float(safe_json_get(team_b_ratings, ["gl", "rd"]))
                    gp_a = none_or_float(safe_json_get(team_a_ratings, ["gl", "games_played"]))
                    gp_b = none_or_float(safe_json_get(team_b_ratings, ["gl", "games_played"]))
                    team_a_games_played = int(gp_a) if gp_a is not None else None
                    team_b_games_played = int(gp_b) if gp_b is not None else None
                
                # Prefer Glicko rating system
                if "gl" in team_a_ratings and "gl" in team_b_ratings:
                    team_a_rating = _finite_float(team_a_ratings["gl"].get("rating_value"))
                    team_b_rating = _finite_float(team_b_ratings["gl"].get("rating_value"))
                    rating_system = "Glicko"
                elif "elo" in team_a_ratings and "elo" in team_b_ratings:
                    team_a_rating = _finite_float(team_a_ratings["elo"].get("rating_value"))
                    team_b_rating = _finite_float(team_b_ratings["elo"].get("rating_value"))
                    rating_system = "Elo"
            
            # Don't show ratings for unmapped/blocked teams
            if team_a_golgg is None:
                team_a_rating = None
            if team_b_golgg is None:
                team_b_rating = None
            
            team_comparison = TeamComparisonInfo(
                team_a=team_a_info,
                team_b=team_b_info,
                team_a_rating=team_a_rating,
                team_b_rating=team_b_rating,
                rating_system=rating_system,
                team_a_elo=team_a_elo,
                team_b_elo=team_b_elo,
                team_a_glicko=team_a_glicko,
                team_b_glicko=team_b_glicko,
                team_a_glicko_rd=team_a_glicko_rd,
                team_b_glicko_rd=team_b_glicko_rd,
                team_a_games_played=team_a_games_played,
                team_b_games_played=team_b_games_played,
                rating_probabilities=rating_probabilities,
            )

        def build_recent_stats(raw: Any) -> TeamRecentStats | None:
            if not isinstance(raw, dict):
                return None
            games = none_or_float(raw.get("games_count"))
            matches = none_or_float(raw.get("matches_count"))
            return TeamRecentStats(
                team_name=raw.get("team_name"),
                matches_count=int(matches) if matches is not None else None,
                games_count=int(games) if games is not None else None,
                win_rate=_finite_float(raw.get("win_rate")),
                avg_kills=_finite_float(raw.get("avg_kills")),
                avg_deaths=_finite_float(raw.get("avg_deaths")),
                avg_gd15=_finite_float(raw.get("avg_gd15")),
                avg_dragons=_finite_float(raw.get("avg_dragons")),
                avg_nashors=_finite_float(raw.get("avg_nashors")),
                avg_towers=_finite_float(raw.get("avg_towers")),
                avg_game_duration=_finite_float(raw.get("avg_game_duration")),
                last_match_at=raw.get("last_match_at"),
            )

        w20 = safe_json_get(f, ["w20"])
        if isinstance(w20, dict):
            recent_stats_a = build_recent_stats(w20.get("team_a"))
            recent_stats_b = build_recent_stats(w20.get("team_b"))

        player_ratings = safe_json_get(f, ["player_ratings"])
        roster_source = safe_json_get(player_ratings, ["roster_source"]) if isinstance(player_ratings, dict) else None

        def players_by_id(side_key: str, system: str) -> dict[str, dict[str, Any]]:
            raw_players = safe_json_get(player_ratings, [side_key, system, "players"])
            out: dict[str, dict[str, Any]] = {}
            if isinstance(raw_players, list):
                for player in raw_players:
                    if not isinstance(player, dict):
                        continue
                    pid = str(player.get("normalized_entity_name") or player.get("player_id") or player.get("entity_name") or "")
                    if pid:
                        out[pid] = player
            return out

        for side_key, side_label, out in [
            ("team_a_roster", m.get("team_a_name", "Team A"), "a"),
            ("team_b_roster", m.get("team_b_name", "Team B"), "b"),
        ]:
            players: list[RosterPlayer] = []
            manual_roster = manual_rosters.get(out)
            raw_roster = manual_roster or (safe_json_get(player_ratings, [side_key]) if isinstance(player_ratings, dict) else None)
            rating_side_key = "team_a" if side_key.startswith("team_a") else "team_b"
            gl_by_id = players_by_id(rating_side_key, "gl")
            elo_by_id = players_by_id(rating_side_key, "elo")
            ts_by_id = players_by_id(rating_side_key, "ts")
            gl_summary = safe_json_get(player_ratings, [rating_side_key, "gl"]) if isinstance(player_ratings, dict) else {}
            elo_summary = safe_json_get(player_ratings, [rating_side_key, "elo"]) if isinstance(player_ratings, dict) else {}

            if isinstance(raw_roster, dict) and isinstance(raw_roster.get("players"), list):
                for pl in raw_roster["players"]:
                    if not isinstance(pl, dict):
                        continue
                    pid = str(pl.get("player_id") or pl.get("normalized_entity_name") or pl.get("player_name") or "")
                    gl = gl_by_id.get(pid) or gl_by_id.get(str(pl.get("player_name") or "")) or {}
                    elo = elo_by_id.get(pid) or elo_by_id.get(str(pl.get("player_name") or "")) or {}
                    ts = ts_by_id.get(pid) or ts_by_id.get(str(pl.get("player_name") or "")) or {}
                    gp = none_or_float(gl.get("games_played") or elo.get("games_played"))
                    players.append(RosterPlayer(
                        player_id=pid or None,
                        player_name=pl.get("player_name") or gl.get("entity_name") or elo.get("entity_name"),
                        role=pl.get("role"),
                        champion_name=pl.get("champion_name"),
                        elo_rating=_finite_float(elo.get("rating_value")),
                        glicko_rating=_finite_float(gl.get("rating_value")),
                        glicko_rd=_finite_float(gl.get("rd")),
                        trueskill_rating=_finite_float(ts.get("rating_value")),
                        rating_uncertainty=_finite_float(ts.get("sigma")),
                        games_played=int(gp) if gp is not None else None,
                    ))
            ri = RosterInfo(
                team_name=(raw_roster.get("team_name") if isinstance(raw_roster, dict) else None) or side_label,
                source_match_id=str(raw_roster.get("source_match_id")) if isinstance(raw_roster, dict) and raw_roster.get("source_match_id") else None,
                source_date=str(raw_roster.get("source_match_date")) if isinstance(raw_roster, dict) and raw_roster.get("source_match_date") else None,
                source_tournament=str(raw_roster.get("source_tournament")) if isinstance(raw_roster, dict) and raw_roster.get("source_tournament") else None,
                roster_source="manual_override" if manual_roster else (str(roster_source) if roster_source else None),
                avg_elo=_finite_float(safe_json_get(elo_summary, ["avg_rating_value"])),
                avg_glicko=_finite_float(safe_json_get(gl_summary, ["avg_rating_value"])),
                avg_glicko_rd=_finite_float(safe_json_get(gl_summary, ["avg_rd"])),
                players_with_rating=int(none_or_float(safe_json_get(gl_summary, ["players_with_rating"])) or 0) if isinstance(gl_summary, dict) else None,
                players=players,
            )
            if out == "a":
                roster_a = ri
            else:
                roster_b = ri

    # A confirmed manual roster is valid even when feature generation is not
    # available (for example when a duplicated canonical match was repaired
    # after kickoff). Do not hide the user's confirmed lineup merely because
    # there is no current upcoming_match_features row to enrich it with.
    def manual_roster_info(side: str, fallback_team_name: Any) -> RosterInfo | None:
        raw_roster = manual_rosters.get(side)
        if not isinstance(raw_roster, dict):
            return None
        raw_players = raw_roster.get("players")
        if not isinstance(raw_players, list):
            raw_players = []
        return RosterInfo(
            team_name=raw_roster.get("team_name") or fallback_team_name,
            source_match_id=str(raw_roster.get("source_match_id")) if raw_roster.get("source_match_id") else None,
            source_date=str(raw_roster.get("source_match_date")) if raw_roster.get("source_match_date") else None,
            source_tournament=str(raw_roster.get("source_tournament")) if raw_roster.get("source_tournament") else None,
            roster_source="manual_override",
            players=[
                RosterPlayer(
                    player_id=str(player.get("player_id")) if player.get("player_id") else None,
                    player_name=player.get("player_name"),
                    role=player.get("role"),
                )
                for player in raw_players if isinstance(player, dict)
            ],
        )

    if roster_a is None and roster_a_is_manual:
        roster_a = manual_roster_info("a", m.get("team_a_name"))
    if roster_b is None and roster_b_is_manual:
        roster_b = manual_roster_info("b", m.get("team_b_name"))

    return MatchDetailResponse(
        canonical_match_id=match_id,
        team_a_name=m.get("team_a_name"),
        team_b_name=m.get("team_b_name"),
        league=m.get("league"),
        start_time_normalized=m.get("start_time_normalized"),
        status=m.get("status"),
        best_of=m.get("best_of"),
        odds=odds_rows,
        predictions=pred_rows,
        roster_a=roster_a,
        roster_b=roster_b,
        roster_a_is_manual=roster_a_is_manual,
        roster_b_is_manual=roster_b_is_manual,
        recent_stats_a=recent_stats_a,
        recent_stats_b=recent_stats_b,
        team_comparison=team_comparison,
    )


# ── GET /matches/{id}/odds-history ──────────────────────────────────────────


@router.get("/{match_id}/odds-history", response_model=list[OddsHistoryPoint])
def odds_history(match_id: int, db=Depends(get_db)):
    meta = query_df(db, "SELECT id FROM canonical_matches WHERE id=:id", {"id": match_id})
    if not meta:
        raise HTTPException(status_code=404, detail="Match not found")

    rows = query_df(
        db,
        """
        SELECT b.name AS bookmaker,
               os.scraped_at,
               os.odds_a, os.odds_b,
               os.raw_team_a, os.raw_team_b
        FROM odds_snapshots os
        JOIN bookmakers b ON b.id=os.bookmaker_id
        WHERE os.canonical_match_id=:mid AND os.market_type='match_winner'
          AND COALESCE(os.is_live,0)=0
          AND os.odds_a IS NOT NULL AND os.odds_b IS NOT NULL
        ORDER BY os.scraped_at
        """,
        {"mid": match_id},
    )

    mm = query_df(db, "SELECT normalized_team_a, normalized_team_b FROM canonical_matches WHERE id=:id", {"id": match_id})
    n_a = mm[0].get("normalized_team_a", "") if mm else ""
    n_b = mm[0].get("normalized_team_b", "") if mm else ""

    history: list[OddsHistoryPoint] = []
    for row in rows:
        aligned = _align(row, n_a, n_b)
        history.append(OddsHistoryPoint(
            bookmaker=row["bookmaker"],
            scraped_at=row.get("scraped_at", ""),
            odds_a=row.get("odds_a"),
            odds_b=row.get("odds_b"),
            canonical_odds_a=aligned[0],
            canonical_odds_b=aligned[1],
        ))
    return history


# ── GET /matches/{id}/prediction-history ────────────────────────────────────


@router.get("/{match_id}/prediction-history", response_model=list[PredictionHistoryPoint])
def prediction_history(match_id: int, db=Depends(get_db)):
    """Return prediction & EV timeline for a match.

    For each (predicted_at, model) point, compute the average market odds
    at the closest scrape time, derive fair market probabilities, and
    calculate EV using the hybrid model's probabilities.
    """
    meta = query_df(db, "SELECT id FROM canonical_matches WHERE id=:id", {"id": match_id})
    if not meta:
        raise HTTPException(status_code=404, detail="Match not found")

    # Fetch all predictions for this match (both models, all time points, any status)
    preds = query_df(
        db,
        """
        SELECT predicted_at, model_name, model_version, prob_a, prob_b
        FROM canonical_predictions
        WHERE canonical_match_id=:mid
          AND prob_a IS NOT NULL AND prob_b IS NOT NULL
        ORDER BY predicted_at
        """,
        {"mid": match_id},
    )

    if not preds:
        return []

    # Fetch all odds snapshots for this match (aligned)
    mm = query_df(db, "SELECT normalized_team_a, normalized_team_b FROM canonical_matches WHERE id=:id", {"id": match_id})
    n_a = mm[0].get("normalized_team_a", "") if mm else ""
    n_b = mm[0].get("normalized_team_b", "") if mm else ""

    odds_rows = query_df(
        db,
        """
        SELECT os.scraped_at, os.odds_a, os.odds_b,
               os.raw_team_a, os.raw_team_b,
               b.name AS bookmaker
        FROM odds_snapshots os
        JOIN bookmakers b ON b.id=os.bookmaker_id
        WHERE os.canonical_match_id=:mid AND os.market_type='match_winner'
          AND COALESCE(os.is_live,0)=0
          AND os.odds_a IS NOT NULL AND os.odds_b IS NOT NULL
        ORDER BY os.scraped_at
        """,
        {"mid": match_id},
    )

    # Align odds and group by scraped_at bucket (truncate to minute)
    from collections import defaultdict
    odds_by_time: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in odds_rows:
        aligned = _align(row, n_a, n_b)
        if aligned[0] is not None and aligned[1] is not None:
            sa = str(row.get("scraped_at", ""))
            # Truncate to minute for grouping
            bucket = sa[:16] if len(sa) >= 16 else sa
            odds_by_time[bucket].append((float(aligned[0]), float(aligned[1])))

    # Build sorted time buckets with average odds
    sorted_buckets = sorted(odds_by_time.items())
    bucket_times: list[str] = []
    bucket_avg_a: list[float] = []
    bucket_avg_b: list[float] = []
    for bt, odds_list in sorted_buckets:
        avg_a = sum(o[0] for o in odds_list) / len(odds_list)
        avg_b = sum(o[1] for o in odds_list) / len(odds_list)
        bucket_times.append(bt)
        bucket_avg_a.append(round(avg_a, 4))
        bucket_avg_b.append(round(avg_b, 4))

    # For each prediction point, find the closest odds bucket
    result: list[PredictionHistoryPoint] = []
    for p in preds:
        pred_time = str(p.get("predicted_at", ""))[:16]  # truncate to minute
        avg_a: float | None = None
        avg_b: float | None = None

        if bucket_times:
            # Find closest bucket by string comparison (ISO format sorts lexicographically)
            best_idx = 0
            best_diff = abs(ord(pred_time[0]) - ord(bucket_times[0][0])) if pred_time and bucket_times[0] else 999
            for i, bt in enumerate(bucket_times):
                # Simple string distance — find closest time
                diff = 0
                min_len = min(len(pred_time), len(bt))
                for c in range(min_len):
                    if pred_time[c] != bt[c]:
                        # Approximate distance based on position
                        diff = abs(i - len(bucket_times) // 2)  # fallback
                        break
                if pred_time <= bt:
                    best_idx = i
                    break
            else:
                best_idx = len(bucket_times) - 1

            # Refine: check neighbours for actual closest
            candidates = [best_idx]
            if best_idx > 0:
                candidates.append(best_idx - 1)
            if best_idx < len(bucket_times) - 1:
                candidates.append(best_idx + 1)

            min_dist = float('inf')
            for ci in candidates:
                try:
                    t1 = pred_time.replace('T', ' ') if 'T' in pred_time else pred_time
                    t2 = bucket_times[ci].replace('T', ' ') if 'T' in bucket_times[ci] else bucket_times[ci]
                    from datetime import datetime as dt
                    d1 = dt.fromisoformat(t1)
                    d2 = dt.fromisoformat(t2)
                    dist = abs((d1 - d2).total_seconds())
                except Exception:
                    dist = float('inf')
                if dist < min_dist:
                    min_dist = dist
                    best_idx = ci

            avg_a = bucket_avg_a[best_idx]
            avg_b = bucket_avg_b[best_idx]

        # Compute market probabilities and EV
        market_prob_a: float | None = None
        market_prob_b: float | None = None
        ev_a: float | None = None
        ev_b: float | None = None

        if avg_a is not None and avg_b is not None and avg_a > 1 and avg_b > 1:
            try:
                market_prob_a, market_prob_b = fair_market_probabilities(avg_a, avg_b)
            except Exception:
                pass

        prob_a = none_or_float(p.get("prob_a"))
        prob_b = none_or_float(p.get("prob_b"))

        if prob_a is not None and avg_a is not None and avg_a > 1:
            ev_a = expected_value(prob_a, avg_a, TAX_RATE)
        if prob_b is not None and avg_b is not None and avg_b > 1:
            ev_b = expected_value(prob_b, avg_b, TAX_RATE)

        # Truncate timestamp to minute precision so models in the same
        # time bucket share the same label (avoids zigzag lines in chart)
        raw_ts = p.get("predicted_at", "")
        if raw_ts:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(str(raw_ts))
                ts_str = dt.strftime("%Y-%m-%dT%H:%M:00+00:00")
            except Exception:
                ts_str = str(raw_ts)
        else:
            ts_str = ""

        result.append(PredictionHistoryPoint(
            timestamp=ts_str,
            model_name=p.get("model_name", ""),
            model_version=p.get("model_version", ""),
            prob_a=prob_a,
            prob_b=prob_b,
            avg_odds_a=avg_a,
            avg_odds_b=avg_b,
            market_prob_a=round(market_prob_a, 4) if market_prob_a is not None else None,
            market_prob_b=round(market_prob_b, 4) if market_prob_b is not None else None,
            ev_a=round(ev_a, 4) if ev_a is not None else None,
            ev_b=round(ev_b, 4) if ev_b is not None else None,
        ))

    return result


# ── PATCH /matches/{id} — update best_of ────────────────────────────────────


@router.patch("/{match_id}", response_model=MatchBestOfUpdate)
def update_match_best_of(match_id: int, body: MatchBestOfUpdate, db=Depends(get_db)):
    meta = query_df(db, "SELECT id FROM canonical_matches WHERE id=:id", {"id": match_id})
    if not meta:
        raise HTTPException(status_code=404, detail="Match not found")
    db.execute(
        text("UPDATE canonical_matches SET best_of = :best_of WHERE id = :id"),
        {"best_of": body.best_of, "id": match_id},
    )
    db.commit()
    return body


# ── PUT /matches/{id}/roster — manually confirm an upcoming roster ─────────


def _resolve_roster_player(
    db,
    player_id: str | None,
    player_name: str,
    role: str | None = None,
    expected_team: str | None = None,
) -> dict[str, str]:
    """Resolve a UI player entry to a stable GOL.GG player id.

    Keeping the id is essential: the rating pipeline is keyed by
    ``normalized_entity_name``/player id, while names can change in feeds.
    """
    if player_id:
        row = query_one(
            db,
            """
            SELECT player_id, player_name
            FROM golgg_game_players
            WHERE CAST(player_id AS TEXT)=:player_id
            ORDER BY match_id DESC, game_id DESC
            LIMIT 1
            """,
            {"player_id": str(player_id)},
        )
        if row:
            return {"player_id": str(row["player_id"]), "player_name": str(row.get("player_name") or player_name)}

    candidates = query_df(
        db,
        """
        SELECT DISTINCT ON (player_id) player_id, player_name, role, team_name
        FROM golgg_game_players
        WHERE LOWER(player_name)=LOWER(:player_name)
          AND (:role IS NULL OR UPPER(COALESCE(role, ''))=UPPER(:role))
        ORDER BY player_id,
            CASE WHEN LOWER(COALESCE(team_name, ''))=LOWER(COALESCE(:expected_team, '')) THEN 0 ELSE 1 END,
            match_id DESC, game_id DESC
        """,
        {"player_name": player_name.strip(), "role": str(role or "").strip() or None, "expected_team": expected_team},
    )
    if not candidates:
        raise HTTPException(
            status_code=422,
            detail=f"Nie znaleziono zawodnika GOL.GG: {player_name}. Wybierz istniejącą nazwę lub popraw ID.",
        )
    if len(candidates) > 1:
        options = "; ".join(
            f"{row.get('player_name')} (ID {row.get('player_id')}, {row.get('team_name') or 'brak drużyny'})"
            for row in candidates[:5]
        )
        raise HTTPException(
            status_code=422,
            detail=f"Niejednoznaczny zawodnik GOL.GG: {player_name}. Wybierz go z wyszukiwarki. Kandydaci: {options}",
        )
    row = candidates[0]
    return {"player_id": str(row["player_id"]), "player_name": str(row.get("player_name") or player_name)}


@router.get("/{match_id}/roster/players")
def search_roster_players(
    match_id: int,
    query: str,
    team_side: str,
    role: str | None = None,
    db=Depends(get_db),
):
    """Search and explicitly select a stable GOL.GG player ID for a manual roster."""
    if team_side not in {"a", "b"}:
        raise HTTPException(status_code=422, detail="team_side must be 'a' or 'b'")
    query = query.strip()
    if len(query) < 2:
        return {"players": []}
    feature = query_one(
        db,
        "SELECT team_a_golgg_name, team_b_golgg_name FROM upcoming_match_features WHERE canonical_match_id=:match_id",
        {"match_id": match_id},
    ) or {}
    expected_team = feature.get("team_a_golgg_name") if team_side == "a" else feature.get("team_b_golgg_name")
    rows = query_df(
        db,
        """
        SELECT DISTINCT ON (player_id) player_id, player_name, role, team_name
        FROM golgg_game_players
        WHERE player_id IS NOT NULL AND player_name IS NOT NULL
          AND LOWER(player_name) LIKE LOWER(:pattern)
          AND (:role IS NULL OR UPPER(COALESCE(role, ''))=UPPER(:role))
        ORDER BY player_id,
            CASE WHEN LOWER(COALESCE(team_name, ''))=LOWER(COALESCE(:expected_team, '')) THEN 0 ELSE 1 END,
            match_id DESC, game_id DESC
        LIMIT 12
        """,
        {"pattern": f"%{query}%", "role": str(role or "").strip() or None, "expected_team": expected_team},
    )
    return {"players": [
        {
            "player_id": str(row["player_id"]), "player_name": str(row.get("player_name") or ""),
            "role": row.get("role"), "team_name": row.get("team_name"),
            "is_expected_team": bool(expected_team and str(row.get("team_name") or "").lower() == str(expected_team).lower()),
        }
        for row in rows
    ]}


@router.put("/{match_id}/roster", response_model=MatchRosterOverrideResponse)
def update_match_roster(match_id: int, body: MatchRosterOverrideRequest, db=Depends(get_db)):
    """Store a confirmed five-player roster for manual prediction.

    The override survives normal feature refreshes and is consumed by both the
    single-match Predict button and the scheduled thesis prediction pipeline.
    It does not fabricate player ratings: each input is resolved to an actual
    GOL.GG player id and uses that player's existing historical rating.
    """
    meta = query_one(
        db,
        "SELECT id, team_a_name, team_b_name, status FROM canonical_matches WHERE id=:id",
        {"id": match_id},
    )
    if not meta:
        raise HTTPException(status_code=404, detail="Match not found")
    if str(meta.get("status") or "") in {"finished", "completed"}:
        raise HTTPException(status_code=409, detail="Nie można zmienić składu zakończonego meczu")

    roles = [str(p.role or "").upper() for p in body.players]
    if any(role and role not in {"TOP", "JUNGLE", "MID", "ADC", "SUPPORT"} for role in roles):
        raise HTTPException(status_code=422, detail="Dozwolone role: TOP, JUNGLE, MID, ADC, SUPPORT")
    nonempty_roles = [role for role in roles if role]
    if len(nonempty_roles) != len(set(nonempty_roles)):
        raise HTTPException(status_code=422, detail="Każda rola może wystąpić tylko raz")

    feature = query_one(
        db,
        "SELECT team_a_golgg_name, team_b_golgg_name FROM upcoming_match_features WHERE canonical_match_id=:match_id",
        {"match_id": match_id},
    ) or {}
    expected_golgg_team = feature.get("team_a_golgg_name") if body.team_side == "a" else feature.get("team_b_golgg_name")
    resolved_players: list[dict[str, str | None]] = []
    seen_ids: set[str] = set()
    for player in body.players:
        resolved = _resolve_roster_player(
            db,
            player.player_id,
            player.player_name,
            player.role,
            expected_golgg_team,
        )
        if resolved["player_id"] in seen_ids:
            raise HTTPException(status_code=422, detail="Zawodnik nie może wystąpić dwa razy w tym samym składzie")
        seen_ids.add(resolved["player_id"])
        resolved_players.append({
            "player_id": resolved["player_id"],
            "player_name": resolved["player_name"],
            "role": str(player.role or "").upper() or None,
        })

    team_name = meta.get("team_a_name") if body.team_side == "a" else meta.get("team_b_name")
    now_iso = datetime.now(UTC).isoformat()
    roster = {
        "team_name": team_name,
        "source_match_id": None,
        "source_match_date": now_iso,
        "source_tournament": "manual confirmation",
        "players": resolved_players,
    }
    db.execute(
        text(
            """
            INSERT INTO match_roster_overrides(canonical_match_id, team_side, roster_json, updated_at)
            VALUES (:match_id, :team_side, :roster_json, :updated_at)
            ON CONFLICT (canonical_match_id, team_side)
            DO UPDATE SET roster_json=EXCLUDED.roster_json, updated_at=EXCLUDED.updated_at
            """
        ),
        {
            "match_id": match_id,
            "team_side": body.team_side,
            "roster_json": json.dumps(roster),
            "updated_at": now_iso,
        },
    )
    # Promote a confirmed lineup to the team's durable current roster as well.
    # The per-match override remains the hard guarantee for this exact match;
    # the team roster is the automatic fallback for subsequent fixtures.
    upsert_current_roster(
        db,
        team_name=str(expected_golgg_team or team_name),
        players=resolved_players,
        source="manual",
        source_match_date=now_iso,
    )
    db.commit()

    return MatchRosterOverrideResponse(
        canonical_match_id=match_id,
        team_side=body.team_side,
        roster=RosterInfo(
            team_name=str(team_name) if team_name else None,
            source_date=now_iso,
            source_tournament="manual confirmation",
            roster_source="manual_override",
            players=[RosterPlayer(**player) for player in resolved_players],
        ),
        message="Skład zapisany jako ręcznie potwierdzony.",
    )


@router.delete("/{match_id}/roster/{team_side}")
def delete_match_roster_override(match_id: int, team_side: str, db=Depends(get_db)):
    """Remove only the match-specific override.

    The selected side then uses the durable current team roster, which may be
    an automatic GOL.GG roster or a newer manual team confirmation.
    """
    if team_side not in {"a", "b"}:
        raise HTTPException(status_code=422, detail="team_side must be 'a' or 'b'")
    result = db.execute(
        text("DELETE FROM match_roster_overrides WHERE canonical_match_id=:match_id AND team_side=:team_side"),
        {"match_id": match_id, "team_side": team_side},
    )
    db.commit()
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="Brak ręcznego składu do przywrócenia")
    return {"ok": True, "message": "Usunięto override tego meczu; używany jest aktualny skład drużyny."}


# ── POST /matches/{id}/predict — run prediction for single match ────────────


@router.post("/{match_id}/predict", response_model=PredictResponse)
def predict_match(match_id: int, db=Depends(get_db)):
    """Build and store one regional operational prediction for a match.

    The new operational model is the only interactive prediction path. EXP-039
    remains stored for retrospective, cohort-matched comparison only.
    """
    meta = query_df(db, "SELECT * FROM canonical_matches WHERE id=:id", {"id": match_id})
    if not meta:
        raise HTTPException(status_code=404, detail="Match not found")
    match = meta[0]
    team_a = match.get("team_a_name")
    team_b = match.get("team_b_name")
    if not team_a or not team_b:
        return PredictResponse(
            status="error",
            message="Match missing team names — cannot predict",
        )

    roster_overrides = _load_roster_overrides(match_id)
    try:
        prediction = predict_operational_match(
            match,
            team_a_roster_override=roster_overrides.get("a"),
            team_b_roster_override=roster_overrides.get("b"),
        )
    except ValueError as error:
        return PredictResponse(status="error", message=str(error))

    try:
        generate_hybrid_predictions()
    except Exception as error:
        import logging

        logging.getLogger(__name__).warning(
            "Operational hybrid generation failed for match %s: %s", match_id, error
        )

    hybrid_pred = query_df(
        db,
        """
        SELECT prob_a, prob_b
        FROM canonical_predictions
        WHERE canonical_match_id=:mid AND prediction_status='active'
          AND model_name=:hn AND model_version=:hv
        ORDER BY predicted_at DESC
        LIMIT 1
        """,
        {"mid": match_id, "hn": HYBRID_MODEL_NAME, "hv": HYBRID_MODEL_VERSION},
    )
    hybrid_prob_a = none_or_float(hybrid_pred[0].get("prob_a")) if hybrid_pred else None
    hybrid_prob_b = none_or_float(hybrid_pred[0].get("prob_b")) if hybrid_pred else None
    return PredictResponse(
        status="ok",
        message=f"Predicted {team_a} vs {team_b}: {prediction['prob_a']:.1%} / {prediction['prob_b']:.1%}",
        prob_a=prediction["prob_a"],
        prob_b=prediction["prob_b"],
        hybrid_prob_a=hybrid_prob_a,
        hybrid_prob_b=hybrid_prob_b,
        model_name=DEFAULT_MODEL_NAME,
        model_version=DEFAULT_MODEL_VERSION,
        diagnostics=prediction["diagnostics"],
    )
