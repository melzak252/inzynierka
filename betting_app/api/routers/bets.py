"""Router: /api/wallets, /api/bets."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from betting_app.api.deps import get_db, query_df, query_one
from betting_app.api.schemas import BetCreate, BetResponse, BetSettle, WalletResponse

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
    try:
        db.execute(
            text("""
            INSERT INTO bookmaker_accounts (bookmaker_id, account_name, currency, opening_balance, current_balance, is_active, created_at, updated_at)
            VALUES (:bid, :name, 'PLN', :bal, :bal, 1, NOW(), NOW())
            """),
            {"bid": bookmaker_id, "name": account_name, "bal": opening_balance},
        )
        db.commit()
        # fetch the inserted row
        rows = query_df(
            db,
            "SELECT ba.*, b.name AS bookmaker_name FROM bookmaker_accounts ba "
            "LEFT JOIN bookmakers b ON b.id=ba.bookmaker_id "
            "WHERE ba.account_name=:name AND ba.bookmaker_id IS NOT DISTINCT FROM :bid "
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
    wallet = query_one(db, "SELECT * FROM bookmaker_accounts WHERE id=:id", {"id": body.bookmaker_account_id})
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    if float(wallet["current_balance"]) < body.stake:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    now = datetime.now(UTC).isoformat(timespec="seconds")
    import json as _json
    result = db.execute(
        text("""
        INSERT INTO bets (bookmaker_account_id, canonical_match_id, team_a, team_b, league,
                          match_start_time, side, stake, taken_odds, model_prob, ev, tax_rate, note,
                          status, placed_at, profit)
        VALUES (:baid, :cmid, :ta, :tb, :lg, :mst, :sd, :st, :od, :mp, :evv, :tx, :nt, 'open', :now, 0)
        """),
        {
            "baid": body.bookmaker_account_id,
            "cmid": body.canonical_match_id,
            "ta": body.team_a,
            "tb": body.team_b,
            "lg": body.league,
            "mst": body.match_start_time,
            "sd": body.side,
            "st": body.stake,
            "od": body.odds,
            "mp": body.model_prob,
            "evv": body.ev,
            "tx": body.tax_rate,
            "nt": body.note,
            "now": now,
        },
    )
    db.commit()
    bet_id = result.lastrowid

    # Deduct from wallet
    new_balance = float(wallet["current_balance"]) - body.stake
    db.execute(
        text("UPDATE bookmaker_accounts SET current_balance=:bal WHERE id=:id"),
        {"bal": new_balance, "id": body.bookmaker_account_id},
    )
    db.execute(
        text("""
        INSERT INTO bookmaker_wallet_transactions
            (bookmaker_account_id, bet_id, transaction_time, transaction_type, amount, balance_after, note)
        VALUES (:baid, :bid, :now, 'bet_placed', :amt, :bal, :nt)
        """),
        {"baid": body.bookmaker_account_id, "bid": bet_id, "now": now,
         "amt": -body.stake, "bal": new_balance, "nt": body.note},
    )
    db.commit()

    return _bet_from_row(query_one(db, "SELECT * FROM bets WHERE id=:id", {"id": bet_id}))


@router.post("/bets/{bet_id}/settle", response_model=BetResponse)
def settle_bet(bet_id: int, body: BetSettle, db=Depends(get_db)):
    bet = query_one(db, "SELECT * FROM bets WHERE id=:id", {"id": bet_id})
    if not bet:
        raise HTTPException(status_code=404, detail="Bet not found")
    if bet["status"] != "open":
        raise HTTPException(status_code=400, detail="Bet already settled")

    now = datetime.now(UTC).isoformat(timespec="seconds")
    stake = float(bet["stake"])
    odds = float(body.settlement_odds or bet["taken_odds"])
    tax_rate = float(bet.get("tax_rate", 0.12))
    wallet_id = bet["bookmaker_account_id"]

    if body.result == "won":
        profit = stake * odds * (1.0 - tax_rate) - stake
        payout = stake + profit
    elif body.result == "lost":
        profit = -stake
        payout = 0.0
    else:
        profit = 0.0
        payout = stake

    db.execute(
        text("UPDATE bets SET status=:st, profit=:pr, settled_at=:now WHERE id=:id"),
        {"st": body.result, "pr": round(profit, 2), "now": now, "id": bet_id},
    )

    wallet = query_one(db, "SELECT * FROM bookmaker_accounts WHERE id=:id", {"id": wallet_id})
    new_balance = float(wallet["current_balance"]) + payout
    db.execute(
        text("UPDATE bookmaker_accounts SET current_balance=:bal WHERE id=:id"),
        {"bal": new_balance, "id": wallet_id},
    )
    db.execute(
        text("""
        INSERT INTO bookmaker_wallet_transactions
            (bookmaker_account_id, bet_id, transaction_time, transaction_type, amount, balance_after, note)
        VALUES (:baid, :bid, :now, :tt, :amt, :bal, NULL)
        """),
        {"baid": wallet_id, "bid": bet_id, "now": now,
         "tt": f"settled_{body.result}", "amt": round(payout, 2), "bal": new_balance},
    )
    db.commit()

    return _bet_from_row(query_one(db, "SELECT * FROM bets WHERE id=:id", {"id": bet_id}))


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
