"""Router: /api/matches — upcoming match board and detail.

Uses SQLAlchemy text() with named parameters (:style).
Compatible with SQLite and PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from fastapi import APIRouter, Depends, HTTPException

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
    PredictResponse,
    PredictionHistoryPoint,
    PredictionRow,
    RosterInfo,
    RosterPlayer,
    OddsHistoryPoint,
    TeamComparisonInfo,
    TeamMappingInfo,
    UnmappedMatchItem,
    UnmappedMatchesResponse,
    GolggMatchCandidate,
    GolggMatchCandidatesResponse,
    MatchMappingRequest,
    MappingCheckResponse,
)
from betting_app.services.canonical_match_service import align_snapshot_odds
from betting_app.core.ev import fair_market_probabilities
from betting_app.services.market_service import (
    enrich_arbitrage,
    expected_value,
    kelly_fraction,
    none_or_float,
    safe_json_get,
)
from betting_app.services.mapping_service import suggest_mapping
from betting_app.services.thesis_inference_service import (
    build_thesis_features_for_match,
    generate_thesis_hybrid_predictions,
    _load_model,
    _swap_feature_vector,
    _symmetrize,
    _logit,
    _register_thesis_model,
    THESIS_MODEL_NAME,
    THESIS_MODEL_VERSION,
    THESIS_HYBRID_MODEL_NAME,
    THESIS_HYBRID_ALPHA,
    THESIS_HYBRID_TEMPERATURE,
    EPSILON,
)

router = APIRouter(prefix="/matches", tags=["matches"])


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
        result[bk_name] = {
            "side_a": {"ev": none_or_float(side_a.get("ev")), "odds": none_or_float(side_a.get("odds"))},
            "side_b": {"ev": none_or_float(side_b.get("ev")), "odds": none_or_float(side_b.get("odds"))},
        }
    return result

TAX_RATE = 0.12
HYBRID_MODEL_NAME = "Hybrid-Fusion-SymAug-Market"
HYBRID_MODEL_VERSION = "a0.60-t0.80"
SPORT_MODEL_NAME = "Sym-Cal LR-ElasticNet-W20-Binomial"
SPORT_MODEL_VERSION = "v0.2"
FUSION_SYMAUG_MODEL_NAME = "Fusion-v2-SymAug"
FUSION_SYMAUG_MODEL_VERSION = "v1.0"


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
    db=Depends(get_db),
):
    now = datetime.now(UTC)
    max_dt = (now + timedelta(days=days_ahead)).isoformat(timespec="seconds")
    now_iso = now.isoformat(timespec="seconds")
    stale_cutoff = now - timedelta(hours=stale_hours)

    odds = query_df(
        db,
        """
        WITH seen_matches AS (
            SELECT DISTINCT canonical_match_id
            FROM upcoming_matches
            WHERE canonical_match_id IS NOT NULL
              AND (last_seen_at IS NULL OR last_seen_at > :stale_cutoff)
        ),
        latest AS (
            SELECT os.*
            FROM odds_snapshots os
            JOIN (
                SELECT canonical_match_id, bookmaker_id, MAX(scraped_at) AS scraped_at
                FROM odds_snapshots
                WHERE market_type='match_winner' AND COALESCE(is_live,0)=0
                  AND canonical_match_id IS NOT NULL
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
               um.offer_url
        FROM latest l
        JOIN canonical_matches cm ON cm.id=l.canonical_match_id
        JOIN seen_matches sm ON sm.canonical_match_id=cm.id
        JOIN bookmakers b ON b.id=l.bookmaker_id
        LEFT JOIN LATERAL (
            SELECT offer_url FROM upcoming_matches
            WHERE canonical_match_id=l.canonical_match_id AND bookmaker_id=l.bookmaker_id
            LIMIT 1
        ) um ON true
        WHERE cm.start_time_normalized IS NOT NULL
          AND cm.status = 'upcoming'
          AND REPLACE(cm.start_time_normalized, 'T', ' ') > REPLACE(:now, 'T', ' ')
          AND REPLACE(cm.start_time_normalized, 'T', ' ') <= REPLACE(:max_dt, 'T', ' ')
        ORDER BY cm.start_time_normalized, cm.id
        """,
        {"now": now_iso, "max_dt": max_dt, "stale_cutoff": stale_cutoff},
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
              AND ((model_name=:hn AND model_version=:hv) OR (model_name=:sn AND model_version=:sv) OR (model_name=:fn AND model_version=:fv))
            GROUP BY canonical_match_id, model_name, model_version
        ) latest ON latest.canonical_match_id=p.canonical_match_id
                 AND latest.model_name=p.model_name
                 AND latest.model_version=p.model_version
                 AND latest.predicted_at=p.predicted_at
        """,
        {"hn": HYBRID_MODEL_NAME, "hv": HYBRID_MODEL_VERSION, "sn": SPORT_MODEL_NAME, "sv": SPORT_MODEL_VERSION, "fn": FUSION_SYMAUG_MODEL_NAME, "fv": FUSION_SYMAUG_MODEL_VERSION},
    )
    pred_map: dict[int, dict] = {}
    for p in preds:
        mid = p["canonical_match_id"]
        item = pred_map.setdefault(mid, {})
        if p["model_name"] == HYBRID_MODEL_NAME:
            item["hybrid_prob_a"] = none_or_float(p.get("prob_a"))
            item["hybrid_prob_b"] = none_or_float(p.get("prob_b"))
        elif p["model_name"] == SPORT_MODEL_NAME:
            item["model_prob_a"] = none_or_float(p.get("prob_a"))
            item["model_prob_b"] = none_or_float(p.get("prob_b"))
        elif p["model_name"] == FUSION_SYMAUG_MODEL_NAME:
            item["fusion_symaug_prob_a"] = none_or_float(p.get("prob_a"))
            item["fusion_symaug_prob_b"] = none_or_float(p.get("prob_b"))

    items: list[MatchBoardItem] = []
    for mid, group in groups.items():
        group = [g for g in group if g.get("_odds_a") is not None and g.get("_odds_b") is not None]
        if not group:
            continue
        books = len({g["bookmaker"] for g in group})
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
        team_a_golgg, _team_a_conf, team_a_source = suggest_mapping(str(team_a_name)) if team_a_name else (None, 0.0, None)
        team_b_golgg, _team_b_conf, team_b_source = suggest_mapping(str(team_b_name)) if team_b_name else (None, 0.0, None)
        has_unmapped_teams = not team_a_golgg or not team_b_golgg

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
    db=Depends(get_db),
):
    """Return finished matches with results (scores from golgg_matches)."""
    now = datetime.now(UTC)
    min_dt = (now - timedelta(days=days_back)).isoformat(timespec="seconds")

    rows = query_df(
        db,
        """
        SELECT cm.id AS canonical_match_id,
               cm.team_a_name, cm.team_b_name,
               cm.league, cm.start_time_normalized,
               cm.best_of, cm.status,
               cm.winner_name, cm.loser_name, cm.winner_side,
               cm.result_source, cm.result_recorded_at,
               gm.team1_score, gm.team2_score,
               ev.best_ev_a, ev.best_ev_b,
               ev.best_odds_a, ev.best_odds_b,
               ev.bookmakers_with_ev,
               ev.bookmaker_ev_json
        FROM canonical_matches cm
        LEFT JOIN golgg_match_mappings gmm ON gmm.canonical_match_id = cm.id
        LEFT JOIN golgg_matches gm ON gm.match_id = gmm.golgg_match_id
        LEFT JOIN LATERAL (
            SELECT MAX(CASE WHEN es.side = 'a' THEN es.ev END) AS best_ev_a,
                   MAX(CASE WHEN es.side = 'b' THEN es.ev END) AS best_ev_b,
                   MAX(CASE WHEN es.side = 'a' THEN es.odds END) AS best_odds_a,
                   MAX(CASE WHEN es.side = 'b' THEN es.odds END) AS best_odds_b,
                   array_agg(DISTINCT b.name) FILTER (WHERE es.ev > 0) AS bookmakers_with_ev,
                   COALESCE(
                       (SELECT json_object_agg(bk_name, bk_data)
                        FROM (
                            SELECT b2.name AS bk_name,
                                   jsonb_build_object(
                                       'side_a', jsonb_build_object('ev', MAX(CASE WHEN es2.side = 'a' THEN es2.ev END), 'odds', MAX(CASE WHEN es2.side = 'a' THEN es2.odds END)),
                                       'side_b', jsonb_build_object('ev', MAX(CASE WHEN es2.side = 'b' THEN es2.ev END), 'odds', MAX(CASE WHEN es2.side = 'b' THEN es2.odds END))
                                   ) AS bk_data
                            FROM model_ev_signals es2
                            JOIN bookmakers b2 ON b2.id = es2.bookmaker_id
                            WHERE es2.canonical_match_id = cm.id
                            GROUP BY b2.name
                        ) sub
                       ),
                       '{}'::json
                   ) AS bookmaker_ev_json
            FROM model_ev_signals es
            JOIN bookmakers b ON b.id = es.bookmaker_id
            WHERE es.canonical_match_id = cm.id
        ) ev ON true
        WHERE cm.status = 'finished'
          AND REPLACE(cm.start_time_normalized, 'T', ' ') >= REPLACE(:min_dt, 'T', ' ')
        ORDER BY cm.start_time_normalized DESC, cm.id DESC
        """,
        {"min_dt": min_dt},
    )

    if not rows:
        return MatchResultsResponse(total=0, results=[])

    items: list[MatchResultItem] = []
    for r in rows:
        # bookmakers_with_ev comes as a string like "{betclic,totalbet}" from PostgreSQL
        bookmakers_raw = r.get("bookmakers_with_ev")
        if isinstance(bookmakers_raw, str):
            # Strip curly braces and split
            bookmakers_list = [b.strip() for b in bookmakers_raw.strip("{}").split(",") if b.strip()]
        elif isinstance(bookmakers_raw, list):
            bookmakers_list = bookmakers_raw
        else:
            bookmakers_list = []

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
            best_ev_a=none_or_float(r.get("best_ev_a")),
            best_ev_b=none_or_float(r.get("best_ev_b")),
            best_odds_a=none_or_float(r.get("best_odds_a")),
            best_odds_b=none_or_float(r.get("best_odds_b")),
            bookmakers_with_ev=bookmakers_list,
            bookmaker_ev_details=_parse_bookmaker_ev_json(r.get("bookmaker_ev_json")),
        ))

    return MatchResultsResponse(total=len(items), results=items)


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
               cm.status
        FROM canonical_matches cm
        LEFT JOIN golgg_match_mappings gmm ON gmm.canonical_match_id = cm.id
        WHERE gmm.canonical_match_id IS NULL
          AND cm.status = :status
        ORDER BY cm.start_time_normalized DESC
        LIMIT :limit
        """,
        {"status": status, "limit": limit},
    )

    items = [UnmappedMatchItem(**r) for r in rows]
    return UnmappedMatchesResponse(total=len(items), matches=items)


# ── GET /matches/{id}/mapping-candidates ────────────────────────────────────


@router.get("/mapping-check/{golgg_id}", response_model=MappingCheckResponse)
def check_golgg_mapping(golgg_id: int, db=Depends(get_db)):
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
    # 1. Insert mapping
    db.execute(
        text("""
            INSERT INTO golgg_match_mappings (canonical_match_id, golgg_match_id)
            VALUES (:c_id, :g_id)
            ON CONFLICT (canonical_match_id) DO UPDATE SET golgg_match_id = EXCLUDED.golgg_match_id
        """),
        {"c_id": body.canonical_match_id, "g_id": body.golgg_match_id},
    )

    # 2. Update status to finished if it was expired/upcoming
    db.execute(
        text("UPDATE canonical_matches SET status = 'finished' WHERE id = :id AND status IN ('expired', 'upcoming')"),
        {"id": body.canonical_match_id},
    )

    db.commit()
    return {"ok": True}


# ── POST /matches/alias — create team alias mapping ──────────────────────────


@router.post("/alias", response_model=AliasCreateResponse)
def create_alias(body: AliasCreateRequest, db=Depends(get_db)):
    """Create a manual team alias mapping (raw_name → golgg_team_name)."""
    from betting_app.services.mapping_service import upsert_alias, normalize_team_name

    normalized = normalize_team_name(body.raw_name)
    if not normalized:
        raise HTTPException(status_code=400, detail="Normalized name is empty")

    alias_id = upsert_alias(body.raw_name, body.golgg_team_name, source="manual", confirmed=True)

    return AliasCreateResponse(
        id=alias_id,
        normalized_name=normalized,
        alias=body.golgg_team_name,
        source="manual",
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
def match_detail(match_id: int, stale_hours: float = 72, db=Depends(get_db)):
    meta = query_df(db, "SELECT * FROM canonical_matches WHERE id=:id", {"id": match_id})
    if not meta:
        raise HTTPException(status_code=404, detail="Match not found")
    m = meta[0]

    live_team_a = suggest_mapping(str(m.get("team_a_name"))) if m.get("team_a_name") else (None, 0.0, None)
    live_team_b = suggest_mapping(str(m.get("team_b_name"))) if m.get("team_b_name") else (None, 0.0, None)
    has_unmapped_teams = not live_team_a[0] or not live_team_b[0]

    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(hours=stale_hours)

    odds = query_df(
        db,
        """
        WITH seen_matches AS (
            SELECT DISTINCT canonical_match_id
            FROM upcoming_matches
            WHERE canonical_match_id IS NOT NULL
              AND (last_seen_at IS NULL OR last_seen_at > :stale_cutoff)
        ),
        latest AS (
            SELECT os.*
            FROM odds_snapshots os
            JOIN (
                SELECT canonical_match_id, bookmaker_id, MAX(scraped_at) AS scraped_at
                FROM odds_snapshots
                WHERE canonical_match_id=:mid AND market_type='match_winner'
                  AND COALESCE(is_live,0)=0
                GROUP BY canonical_match_id, bookmaker_id
            ) lo ON lo.canonical_match_id=os.canonical_match_id
                 AND lo.bookmaker_id=os.bookmaker_id
                 AND lo.scraped_at=os.scraped_at
        )
        SELECT b.name AS bookmaker,
               l.raw_team_a, l.raw_team_b,
               l.odds_a, l.odds_b,
               l.scraped_at, l.source_url,
               um.offer_url
        FROM latest l
        JOIN seen_matches sm ON sm.canonical_match_id=l.canonical_match_id
        JOIN bookmakers b ON b.id=l.bookmaker_id
        LEFT JOIN LATERAL (
            SELECT offer_url FROM upcoming_matches
            WHERE canonical_match_id=l.canonical_match_id AND bookmaker_id=l.bookmaker_id
            LIMIT 1
        ) um ON true
        ORDER BY b.name
        """,
        {"mid": match_id, "stale_cutoff": stale_cutoff},
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
        SELECT *
        FROM canonical_predictions
        WHERE canonical_match_id=:mid AND prediction_status='active'
        ORDER BY CASE WHEN model_name LIKE 'Hybrid%' THEN 0 ELSE 1 END, model_name
        """,
        {"mid": match_id},
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
    team_comparison: TeamComparisonInfo | None = None
    
    feat = query_df(
        db,
        """
        SELECT features_json FROM upcoming_match_features
        WHERE canonical_match_id=:mid ORDER BY id DESC LIMIT 1
        """,
        {"mid": match_id},
    )
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
            
            if isinstance(ratings, dict):
                team_a_ratings = ratings.get("team_a", {})
                team_b_ratings = ratings.get("team_b", {})
                
                # Prefer Glicko rating system
                if "gl" in team_a_ratings and "gl" in team_b_ratings:
                    team_a_rating = none_or_float(team_a_ratings["gl"].get("rating_value"))
                    team_b_rating = none_or_float(team_b_ratings["gl"].get("rating_value"))
                    rating_system = "Glicko"
                elif "elo" in team_a_ratings and "elo" in team_b_ratings:
                    team_a_rating = none_or_float(team_a_ratings["elo"].get("rating_value"))
                    team_b_rating = none_or_float(team_b_ratings["elo"].get("rating_value"))
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
            )

        for side_key, side_label, out in [
            ("team_a_roster", m.get("team_a_name", "Team A"), "a"),
            ("team_b_roster", m.get("team_b_name", "Team B"), "b"),
        ]:
            players: list[RosterPlayer] = []
            raw_pl = safe_json_get(f, ["player_ratings", side_key])
            if isinstance(raw_pl, list):
                for pl in raw_pl:
                    players.append(RosterPlayer(
                        player_name=pl.get("player_name"),
                        role=pl.get("role"),
                        champion_name=pl.get("champion_name"),
                        glicko_rating=none_or_float(safe_json_get(pl, ["ratings", "gl", "rating_value"])),
                        glicko_rd=none_or_float(safe_json_get(pl, ["ratings", "gl", "rd"])),
                        games_played=none_or_float(safe_json_get(pl, ["ratings", "gl", "games_played"])),
                    ))
            ri = RosterInfo(
                team_name=side_label,
                source_match_id=str(safe_json_get(raw_pl, ["source_match_id"])) if isinstance(raw_pl, dict) and raw_pl.get("source_match_id") else None,
                source_date=str(safe_json_get(raw_pl, ["source_date"])) if isinstance(raw_pl, dict) and raw_pl.get("source_date") else None,
                players=players,
            )
            if out == "a":
                roster_a = ri
            else:
                roster_b = ri

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


# ── POST /matches/{id}/predict — run prediction for single match ────────────


@router.post("/{match_id}/predict", response_model=PredictResponse)
def predict_match(match_id: int, db=Depends(get_db)):
    """Run thesis model prediction for a single match.

    Builds features, runs inference with order symmetry + Platt calibration,
    stores the prediction, then generates hybrid + EV signals.
    """
    import numpy as np
    import json as _json

    # 1. Load match from DB
    meta = query_df(db, "SELECT * FROM canonical_matches WHERE id=:id", {"id": match_id})
    if not meta:
        raise HTTPException(status_code=404, detail="Match not found")
    m = meta[0]

    team_a = m.get("team_a_name")
    team_b = m.get("team_b_name")
    if not team_a or not team_b:
        return PredictResponse(
            status="error",
            message="Match missing team names — cannot predict",
        )

    best_of = m.get("best_of") or 1

    # 2. Build features
    feature_vector, diagnostics = build_thesis_features_for_match(
        team_a, team_b, best_of=best_of,
    )
    if feature_vector is None:
        return PredictResponse(
            status="error",
            message=f"Cannot build features for {team_a} vs {team_b} — missing data",
            diagnostics=diagnostics,
        )

    # 3. Load model and run inference
    pipeline, calibrator = _load_model()
    fv = np.array(feature_vector, dtype=float).reshape(1, -1)

    # Original order
    original_prob = float(pipeline.predict_proba(fv)[0, 1])
    original_prob = max(EPSILON, min(1 - EPSILON, original_prob))

    # Swapped order (order symmetry)
    swapped_vec = _swap_feature_vector(fv)
    sv = np.array(swapped_vec, dtype=float).reshape(1, -1)
    swapped_prob = float(pipeline.predict_proba(sv)[0, 1])
    swapped_prob = max(EPSILON, min(1 - EPSILON, swapped_prob))

    # Symmetrize
    sym_prob = _symmetrize(original_prob, swapped_prob)

    # Platt calibration
    calibrated_prob = float(calibrator.predict_proba(_logit([sym_prob]))[0, 1])
    calibrated_prob = max(EPSILON, min(1 - EPSILON, calibrated_prob))

    prob_a = round(calibrated_prob, 6)
    prob_b = round(1 - calibrated_prob, 6)

    # 4. Register model artifact and store prediction
    now_iso = datetime.now(UTC).isoformat(timespec="seconds")

    # Mark old thesis predictions as stale for this match
    db.execute(
        text(
            "UPDATE canonical_predictions SET prediction_status = 'stale' "
            "WHERE prediction_status = 'active' AND model_name = :mn AND model_version = :mv "
            "AND canonical_match_id = :mid"
        ),
        {"mn": THESIS_MODEL_NAME, "mv": THESIS_MODEL_VERSION, "mid": match_id},
    )

    # Register model artifact (get or create)
    model_artifact_id = _register_thesis_model()

    # Insert new prediction
    db.execute(
        text(
            "INSERT INTO canonical_predictions "
            "(canonical_match_id, model_artifact_id, model_name, model_version, "
            " predicted_at, prob_a, prob_b, prediction_status, features_version, "
            " ratings_version, data_cutoff_at, diagnostics_json) "
            "VALUES (:mid, :maid, :mn, :mv, :pat, :pa, :pb, 'active', :fv, :rv, :dca, :dj)"
        ),
        {
            "mid": match_id,
            "maid": model_artifact_id,
            "mn": THESIS_MODEL_NAME,
            "mv": THESIS_MODEL_VERSION,
            "pat": now_iso,
            "pa": prob_a,
            "pb": prob_b,
            "fv": diagnostics.get("features_version", "46f-v1") if isinstance(diagnostics, dict) else "46f-v1",
            "rv": diagnostics.get("ratings_version", "latest-full") if isinstance(diagnostics, dict) else "latest-full",
            "dca": now_iso,
            "dj": _json.dumps(diagnostics) if isinstance(diagnostics, dict) else None,
        },
    )
    db.commit()

    # 5. Generate hybrid predictions (runs for all matches but picks up the new thesis prediction)
    try:
        generate_thesis_hybrid_predictions(
            alpha=THESIS_HYBRID_ALPHA,
            temperature=THESIS_HYBRID_TEMPERATURE,
            hybrid_model_name=THESIS_HYBRID_MODEL_NAME,
            hybrid_model_version=HYBRID_MODEL_VERSION,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Hybrid prediction failed for match {match_id}: {e}")

    # 6. Fetch the hybrid prediction we just generated
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
        {"mid": match_id, "hn": THESIS_HYBRID_MODEL_NAME, "hv": HYBRID_MODEL_VERSION},
    )
    hybrid_prob_a = none_or_float(hybrid_pred[0].get("prob_a")) if hybrid_pred else None
    hybrid_prob_b = none_or_float(hybrid_pred[0].get("prob_b")) if hybrid_pred else None

    return PredictResponse(
        status="ok",
        message=f"Predicted {team_a} vs {team_b}: {prob_a:.1%} / {prob_b:.1%}",
        prob_a=prob_a,
        prob_b=prob_b,
        hybrid_prob_a=hybrid_prob_a,
        hybrid_prob_b=hybrid_prob_b,
        model_name=THESIS_MODEL_NAME,
        model_version=THESIS_MODEL_VERSION,
        diagnostics=diagnostics if isinstance(diagnostics, dict) else None,
    )
