"""Router: /api/predictions — EV+ signals."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from betting_app.api.deps import get_db, query_df
from betting_app.api.schemas import EVSignal, EVSignalResponse
from betting_app.services.market_service import kelly_fraction, none_or_float
from betting_app.core.models import get_active_hybrid, list_registered_models
from betting_app.services.bet_qualification_service import (
    DEFAULT_BASE_MIN_EV,
    DEFAULT_MAX_EV_NET,
    is_bet_eligible,
    model_requires_uncertainty,
    prediction_safety_diagnostics,
    qualification_tier,
)

DEFAULT_HYBRID_MODEL_NAME = get_active_hybrid().hybrid_model_name
from betting_app.ml.model_lifecycle import RETIRED_PUBLIC_MODEL_NAME

router = APIRouter(prefix="/predictions", tags=["predictions"])

TAX_RATE = 0.12


@router.get("", response_model=EVSignalResponse)
def list_predictions(
    min_ev: float = Query(0.0),
    max_ev: float | None = Query(None),
    min_books: int = Query(1),
    model_name: str | None = Query(DEFAULT_HYBRID_MODEL_NAME),
    model_version: str | None = Query(None),
    limit: int = Query(50, le=200),
    db=Depends(get_db),
):
    # Build dynamic WHERE clause for optional model filters
    where_clauses = [
        "mes.status='new'",
        "mes.ev >= :min_ev",
        "mes.side IN ('a', 'b')",
        "cp.model_name <> :retired_model_name",
        "cp.prediction_status='active'",
    ]
    params = {
        "min_ev": min_ev,
        "lim": limit,
        "retired_model_name": RETIRED_PUBLIC_MODEL_NAME,
    }

    if model_name:
        where_clauses.append("cp.model_name = :model_name")
        params["model_name"] = model_name
    if model_version:
        where_clauses.append("cp.model_version = :model_version")
        params["model_version"] = model_version

    where_sql = " AND ".join(where_clauses)

    rows = query_df(
        db,
        f"""
        SELECT
            mes.*,
            cp.model_name, cp.model_version,
            cp.prob_a, cp.prob_b, cp.diagnostics_json,
            cm.team_a_name, cm.team_b_name,
            cm.league, cm.start_time_normalized,
            b.name AS bookmaker_name
        FROM model_ev_signals mes
        JOIN canonical_predictions cp ON cp.id=mes.canonical_prediction_id
        JOIN canonical_matches cm ON cm.id=mes.canonical_match_id
        JOIN bookmakers b ON b.id=mes.bookmaker_id
        WHERE {where_sql}
        ORDER BY ev DESC
        LIMIT :lim
        """,
        params,
    )

    signals: list[EVSignal] = []
    for row in rows:
        odds = none_or_float(row.get("odds"))
        try:
            safety = prediction_safety_diagnostics(
                row.get("diagnostics_json"),
                row["prob_a"],
                row["prob_b"],
                uncertainty_required=model_requires_uncertainty(row["model_name"]),
            )
            side = row["side"]
            prob = row[f"prob_{side}"]
            conservative = (
                safety[f"p_low_{side}"] if safety["uncertainty_required"] else prob
            )
            eligible, _, decision = is_bet_eligible(
                prob_model=prob,
                prob_conservative=conservative,
                odds=odds,
                uncertainty_required=safety["uncertainty_required"],
                prob_market_novig=none_or_float(row.get("market_prob")),
                tax_rate=TAX_RATE,
                min_ev_net=max(DEFAULT_BASE_MIN_EV, min_ev),
                rating_disagreement=safety.get("rating_disagreement"),
                competition_tier=qualification_tier(
                    row.get("league"), row.get("start_time_normalized")
                ),
                max_ev_net=max_ev,
            )
        except (KeyError, TypeError, ValueError):
            continue
        if not eligible:
            continue
        ev = decision["ev_net"]
        signals.append(
            EVSignal(
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
                kelly=kelly_fraction(conservative, odds, TAX_RATE),
                offer_url=row.get("offer_url"),
            )
        )

    return EVSignalResponse(total=len(signals), signals=signals)


@router.get("/models")
def get_ev_models():
    """List models available for EV predictions."""
    return {
        "active_hybrid_model": get_active_hybrid().hybrid_model_name,
        "models": list_registered_models(),
    }
