"""Router: /api/predictions — EV+ signals."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from betting_app.api.deps import get_db, query_df
from betting_app.api.schemas import EVSignal, EVSignalResponse
from betting_app.services.market_service import expected_value, kelly_fraction, none_or_float

router = APIRouter(prefix="/predictions", tags=["predictions"])

TAX_RATE = 0.12


@router.get("", response_model=EVSignalResponse)
def list_predictions(
    min_ev: float = Query(0.0),
    min_books: int = Query(1),
    limit: int = Query(50, le=200),
    db=Depends(get_db),
):
    rows = query_df(
        db,
        """
        SELECT
            mes.*,
            cm.team_a_name, cm.team_b_name,
            cm.league, cm.start_time_normalized,
            b.name AS bookmaker_name
        FROM model_ev_signals mes
        JOIN canonical_matches cm ON cm.id=mes.canonical_match_id
        JOIN bookmakers b ON b.id=mes.bookmaker_id
        WHERE mes.status='new'
          AND mes.ev >= :min_ev
          AND mes.side IN ('a', 'b')
        ORDER BY ev DESC
        LIMIT :lim
        """,
        {"min_ev": min_ev, "lim": limit},
    )

    signals: list[EVSignal] = []
    for row in rows:
        prob = none_or_float(row.get("model_prob"))
        odds = none_or_float(row.get("odds"))
        ev = none_or_float(row.get("ev"))
        if prob is None or odds is None or ev is None:
            continue
        signals.append(EVSignal(
            canonical_match_id=row["canonical_match_id"],
            match=f"{row.get('team_a_name','?')} vs {row.get('team_b_name','?')}",
            league=row.get("league"),
            start_time_normalized=row.get("start_time_normalized"),
            model_name=row.get("model_name", "?"),
            model_version=row.get("model_version", "?"),
            side=row["side"],
            odds=odds,
            bookmaker=row.get("bookmaker_name", "?"),
            model_prob=prob,
            market_prob=none_or_float(row.get("market_prob")),
            ev=ev,
            kelly=kelly_fraction(prob, odds, TAX_RATE),
            offer_url=row.get("offer_url"),
        ))

    return EVSignalResponse(total=len(signals), signals=signals)
