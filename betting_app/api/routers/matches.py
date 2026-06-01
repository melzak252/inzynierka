"""Router: /api/matches — upcoming match board and detail.

Uses SQLAlchemy text() with named parameters (:style).
Compatible with SQLite and PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from betting_app.api.deps import get_db, query_df, query_one
from betting_app.api.schemas import (
    BookmakerOddsRow,
    MatchBoardItem,
    MatchBoardResponse,
    MatchDetailResponse,
    PredictionRow,
    RosterInfo,
    RosterPlayer,
    OddsHistoryPoint,
)
from betting_app.services.canonical_match_service import align_snapshot_odds
from betting_app.services.market_service import (
    enrich_arbitrage,
    expected_value,
    kelly_fraction,
    none_or_float,
    safe_json_get,
)

router = APIRouter(prefix="/matches", tags=["matches"])

TAX_RATE = 0.12
HYBRID_MODEL_NAME = "Hybrid-PlayerTeam-W20-Market"
HYBRID_MODEL_VERSION = "a0.50-t0.80"
SPORT_MODEL_NAME = "Operational-PlayerTeamRatings-W20"
SPORT_MODEL_VERSION = "v0.2"


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
    db=Depends(get_db),
):
    now = datetime.now(UTC)
    max_dt = (now + timedelta(days=days_ahead)).isoformat(timespec="seconds")
    now_iso = now.isoformat(timespec="seconds")

    odds = query_df(
        db,
        """
        WITH latest AS (
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
               cm.start_time_normalized, cm.league,
               b.name AS bookmaker,
               l.raw_team_a, l.raw_team_b,
               l.odds_a, l.odds_b,
               l.scraped_at, l.source_url,
               um.offer_url
        FROM latest l
        JOIN canonical_matches cm ON cm.id=l.canonical_match_id
        JOIN bookmakers b ON b.id=l.bookmaker_id
        LEFT JOIN upcoming_matches um ON um.canonical_match_id=l.canonical_match_id
          AND um.bookmaker_id=l.bookmaker_id
        WHERE cm.start_time_normalized IS NOT NULL
          AND REPLACE(cm.start_time_normalized, 'T', ' ') > REPLACE(:now, 'T', ' ')
          AND REPLACE(cm.start_time_normalized, 'T', ' ') <= REPLACE(:max_dt, 'T', ' ')
        ORDER BY cm.start_time_normalized, cm.id
        """,
        {"now": now_iso, "max_dt": max_dt},
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
        {"hn": HYBRID_MODEL_NAME, "hv": HYBRID_MODEL_VERSION, "sn": SPORT_MODEL_NAME, "sv": SPORT_MODEL_VERSION},
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

        p = pred_map.get(mid, {})
        hybrid_ev_a = (
            expected_value(float(p["hybrid_prob_a"]), float(record["best_odds_a"]), tax_rate)
            if p.get("hybrid_prob_a") is not None else None
        )
        hybrid_ev_b = (
            expected_value(float(p["hybrid_prob_b"]), float(record["best_odds_b"]), tax_rate)
            if p.get("hybrid_prob_b") is not None else None
        )

        items.append(MatchBoardItem(
            canonical_match_id=mid,
            match=f"{group[0].get('team_a_name','?')} vs {group[0].get('team_b_name','?')}",
            league=group[0].get("league"),
            start_time_normalized=group[0].get("start_time_normalized"),
            team_a_name=group[0].get("team_a_name"),
            team_b_name=group[0].get("team_b_name"),
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
            last_scraped_at=str(max(g["scraped_at"] for g in group if g.get("scraped_at"))),
        ))

    items.sort(key=lambda x: (x.start_time_normalized or "", x.canonical_match_id))
    return MatchBoardResponse(total=len(items), matches=items)


# ── GET /matches/{id} ───────────────────────────────────────────────────────


@router.get("/{match_id}", response_model=MatchDetailResponse)
def match_detail(match_id: int, db=Depends(get_db)):
    meta = query_df(db, "SELECT * FROM canonical_matches WHERE id=:id", {"id": match_id})
    if not meta:
        raise HTTPException(status_code=404, detail="Match not found")
    m = meta[0]

    odds = query_df(
        db,
        """
        WITH latest AS (
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
        JOIN bookmakers b ON b.id=l.bookmaker_id
        LEFT JOIN upcoming_matches um ON um.canonical_match_id=l.canonical_match_id
                                        AND um.bookmaker_id=l.bookmaker_id
        ORDER BY b.name
        """,
        {"mid": match_id},
    )

    n_a = m.get("normalized_team_a") or ""
    n_b = m.get("normalized_team_b") or ""
    odds_rows: list[BookmakerOddsRow] = []
    for row in odds:
        aligned = _align(row, n_a, n_b)
        odds_rows.append(BookmakerOddsRow(
            bookmaker=row["bookmaker"],
            raw_team_a=row.get("raw_team_a"),
            raw_team_b=row.get("raw_team_b"),
            canonical_odds_a=aligned[0],
            canonical_odds_b=aligned[1],
            scraped_at=row.get("scraped_at"),
            source_url=row.get("source_url"),
            offer_url=row.get("offer_url"),
        ))

    preds = query_df(
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
        odds=odds_rows,
        predictions=pred_rows,
        roster_a=roster_a,
        roster_b=roster_b,
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
