"""Router: /api/wallets, /api/bets — wallet management and bet tracking."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection, IntegrityError

from betting_app.api.deps import get_db, query_df, query_one
from betting_app.api.schemas import (
    BetCreate,
    BetResponse,
    BetSettle,
    WalletResponse,
)
from betting_app.services.market_service import none_or_float

router = APIRouter(tags=["wallets"])


# ── GET /api/wallets ────────────────────────────────────────────────────────


@router.get("/wallets", response_model=list[WalletResponse])
def list_wallets(db: Connection = Depends(get_db)):
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
    db: Connection = Depends(get_db),
):
    try:
        cur = db.execute(
            """
            INSERT INTO bookmaker_accounts (bookmaker_id, account_name, currency, opening_balance, current_balance)
            VALUES (?, ?, 'PLN', ?, ?)
            """,
            (bookmaker_id, account_name, opening_balance, opening_balance),
        )
        db.commit()
        return WalletResponse(
            id=cur.lastrowid,
            bookmaker=None,
            account_name=account_name,
            currency="PLN",
            current_balance=opening_balance,
            is_active=True,
        )
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Wallet already exists")


# ── GET /api/bets ───────────────────────────────────────────────────────────


@router.get("/bets", response_model=list[BetResponse])
def list_bets(status: str | None = None, limit: int = 50, db: Connection = Depends(get_db)):
    where = ""
    params: list = []
    if status:
        where = "WHERE b.status=?"
        params.append(status)
    rows = query_df(
        db,
        f"""
        SELECT b.*
        FROM bets b
        {where}
        ORDER BY b.placed_at DESC
        LIMIT ?
        """,
        tuple(params + [limit]),
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
def place_bet(body: BetCreate, db: Connection = Depends(get_db)):
    # Validate wallet exists and has sufficient balance
    wallet = query_one(db, "SELECT * FROM bookmaker_accounts WHERE id=?", (body.bookmaker_account_id,))
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    if float(wallet["current_balance"]) < body.stake:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    now = datetime.now(UTC).isoformat(timespec="seconds")
    cur = db.execute(
        """
        INSERT INTO bets (bookmaker_account_id, canonical_match_id, team_a, team_b, league,
                          match_start_time, side, stake, taken_odds, model_prob, ev, tax_rate, note,
                          status, placed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
        """,
        (
            body.bookmaker_account_id,
            body.canonical_match_id,
            body.team_a,
            body.team_b,
            body.league,
            body.match_start_time,
            body.side,
            body.stake,
            body.odds,
            body.model_prob,
            body.ev,
            body.tax_rate,
            body.note,
            now,
        ),
    )

    # Deduct from wallet
    new_balance = float(wallet["current_balance"]) - body.stake
    db.execute(
        "UPDATE bookmaker_accounts SET current_balance=? WHERE id=?",
        (new_balance, body.bookmaker_account_id),
    )
    db.execute(
        """
        INSERT INTO bookmaker_wallet_transactions
            (bookmaker_account_id, bet_id, transaction_time, transaction_type, amount, balance_after, note)
        VALUES (?, ?, ?, 'bet_placed', ?, ?, ?)
        """,
        (body.bookmaker_account_id, cur.lastrowid, now, -body.stake, new_balance, body.note),
    )
    db.commit()

    return _bet_from_row(query_one(db, "SELECT * FROM bets WHERE id=?", (cur.lastrowid,)))


@router.post("/bets/{bet_id}/settle", response_model=BetResponse)
def settle_bet(bet_id: int, body: BetSettle, db: Connection = Depends(get_db)):
    bet = query_one(db, "SELECT * FROM bets WHERE id=?", (bet_id,))
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
    else:  # void / cancelled
        profit = 0.0
        payout = stake

    db.execute(
        "UPDATE bets SET status=?, profit=?, settled_at=? WHERE id=?",
        (body.result, round(profit, 2), now, bet_id),
    )

    # Update wallet balance
    wallet = query_one(db, "SELECT * FROM bookmaker_accounts WHERE id=?", (wallet_id,))
    new_balance = float(wallet["current_balance"]) + payout
    db.execute("UPDATE bookmaker_accounts SET current_balance=? WHERE id=?", (new_balance, wallet_id))
    db.execute(
        """
        INSERT INTO bookmaker_wallet_transactions
            (bookmaker_account_id, bet_id, transaction_time, transaction_type, amount, balance_after, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (wallet_id, bet_id, now, f"settled_{body.result}", round(payout, 2), new_balance, None),
    )
    db.commit()

    return _bet_from_row(query_one(db, "SELECT * FROM bets WHERE id=?", (bet_id,)))


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
