"""Router: /api/wallets, /api/bets."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from betting_app.api.deps import get_db, query_df, query_one
from betting_app.api.schemas import BetCreate, BetResponse, BetSettle, WalletResponse
from betting_app.services.wallet_service import (
    BetAlreadySettledError,
    BetNotFoundError,
    InsufficientWalletBalanceError,
    WalletNotFoundError,
    place_wallet_bet,
    settle_wallet_bet_atomic,
)

router = APIRouter(tags=["wallets"])


# ── GET /api/wallets ────────────────────────────────────────────────────────


@router.get("/wallets", response_model=list[WalletResponse])
def list_wallets(db=Depends(get_db)):
    rows = query_df(
        db,
        """
        SELECT ba.*, b.name AS bookmaker_name
        FROM bookmaker_accounts ba
        LEFT JOIN bookmakers b ON b.id=ba.bookmaker_id
        WHERE ba.is_active=1
        ORDER BY ba.account_name
        """,
    )
    return [
        WalletResponse(
            id=r["id"],
            bookmaker=r.get("bookmaker_name"),
            account_name=r["account_name"],
            currency=r.get("currency", "PLN"),
            current_balance=float(r.get("current_balance", 0)),
            is_active=bool(r["is_active"]),
        )
        for r in rows
    ]


@router.post("/wallets", response_model=WalletResponse, status_code=201)
def create_wallet(
    bookmaker_id: int | None = None,
    account_name: str = "Default",
    opening_balance: float = 100.0,
    db=Depends(get_db),
):
    now = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        db.execute(
            text("""
            INSERT INTO bookmaker_accounts (bookmaker_id, account_name, currency, opening_balance, current_balance, is_active, created_at, updated_at)
            VALUES (:bid, :name, 'PLN', :bal, :bal, 1, :now, :now)
            """),
            {"bid": bookmaker_id, "name": account_name, "bal": opening_balance, "now": now},
        )
        db.commit()
        # fetch the inserted row
        rows = query_df(
            db,
            "SELECT ba.*, b.name AS bookmaker_name FROM bookmaker_accounts ba "
            "LEFT JOIN bookmakers b ON b.id=ba.bookmaker_id "
            "WHERE ba.account_name=:name "
            "AND (ba.bookmaker_id=:bid OR (ba.bookmaker_id IS NULL AND :bid IS NULL)) "
            "ORDER BY ba.id DESC LIMIT 1",
            {"name": account_name, "bid": bookmaker_id},
        )
        if not rows:
            raise HTTPException(status_code=500, detail="Failed to create wallet")
        r = rows[0]
        return WalletResponse(
            id=r["id"],
            bookmaker=r.get("bookmaker_name"),
            account_name=r["account_name"],
            currency=r.get("currency", "PLN"),
            current_balance=float(r.get("current_balance", 0)),
            is_active=True,
        )
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Wallet already exists")


# ── GET /api/bets ───────────────────────────────────────────────────────────


@router.get("/bets", response_model=list[BetResponse])
def list_bets(status: str | None = None, limit: int = 50, db=Depends(get_db)):
    where = ""
    params: dict = {"lim": limit}
    if status:
        where = "WHERE b.status=:status"
        params["status"] = status
    rows = query_df(
        db,
        f"""
        SELECT b.*
        FROM bets b
        {where}
        ORDER BY b.placed_at DESC
        LIMIT :lim
        """,
        params,
    )
    return [
        BetResponse(
            id=r["id"],
            bookmaker_account_id=r["bookmaker_account_id"],
            canonical_match_id=r.get("canonical_match_id"),
            team_a=r.get("team_a"),
            team_b=r.get("team_b"),
            stake=float(r["stake"]),
            odds=float(r["taken_odds"]),
            side=r["side"],
            status=r["status"],
            profit=float(r["profit"]) if r.get("profit") is not None else None,
            placed_at=r.get("placed_at"),
            settled_at=r.get("settled_at"),
            note=r.get("note"),
        )
        for r in rows
    ]

@router.post("/bets", response_model=BetResponse, status_code=201)
def place_bet(body: BetCreate, db=Depends(get_db)):
    try:
        bet_id = place_wallet_bet(
            db,
            bookmaker_account_id=body.bookmaker_account_id,
            canonical_match_id=body.canonical_match_id,
            team_a=body.team_a,
            team_b=body.team_b,
            league=body.league,
            match_start_time=body.match_start_time,
            side=body.side,
            stake=body.stake,
            odds=body.odds,
            model_prob=body.model_prob,
            ev=body.ev,
            tax_rate=body.tax_rate,
            note=body.note,
        )
        db.commit()
    except WalletNotFoundError:
        db.rollback()
        raise HTTPException(status_code=404, detail="Wallet not found")
    except InsufficientWalletBalanceError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Insufficient balance")
    except Exception:
        db.rollback()
        raise
    return _bet_from_row(
        query_one(db, "SELECT * FROM bets WHERE id=:id", {"id": bet_id})
    )


@router.post("/bets/{bet_id}/settle", response_model=BetResponse)
def settle_bet(bet_id: int, body: BetSettle, db=Depends(get_db)):
    try:
        settle_wallet_bet_atomic(
            db,
            bet_id=bet_id,
            result=body.result,
            settlement_odds=body.settlement_odds,
        )
        db.commit()
    except BetNotFoundError:
        db.rollback()
        raise HTTPException(status_code=404, detail="Bet not found")
    except BetAlreadySettledError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Bet already settled")
    except Exception:
        db.rollback()
        raise
    return _bet_from_row(
        query_one(db, "SELECT * FROM bets WHERE id=:id", {"id": bet_id})
    )


def _bet_from_row(r: dict) -> BetResponse:
    return BetResponse(
        id=r["id"],
        bookmaker_account_id=r["bookmaker_account_id"],
        canonical_match_id=r.get("canonical_match_id"),
        team_a=r.get("team_a"),
        team_b=r.get("team_b"),
        stake=float(r["stake"]),
        odds=float(r["taken_odds"]),
        side=r["side"],
        status=r["status"],
        profit=float(r["profit"]) if r.get("profit") is not None else None,
        placed_at=r.get("placed_at"),
        settled_at=r.get("settled_at"),
        note=r.get("note"),
    )


from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
