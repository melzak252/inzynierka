"""Bookmaker account wallets and manual bet history."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from betting_app.core.db import query_df, transaction


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def bookmaker_options() -> pd.DataFrame:
    return query_df("SELECT id, name FROM bookmakers WHERE is_active = 1 ORDER BY name")


def accounts(active_only: bool = True) -> pd.DataFrame:
    where = "WHERE ba.is_active = 1" if active_only else ""
    return query_df(
        f"""
        SELECT ba.*, b.name AS bookmaker
        FROM bookmaker_accounts ba
        JOIN bookmakers b ON b.id = ba.bookmaker_id
        {where}
        ORDER BY b.name, ba.account_name
        """
    )


def create_account(bookmaker_id: int, account_name: str, opening_balance: float = 0.0, currency: str = "PLN") -> int:
    clean_name = account_name.strip()
    with transaction() as connection:
        existing = connection.execute(
            "SELECT id FROM bookmaker_accounts WHERE bookmaker_id = ? AND account_name = ?",
            (int(bookmaker_id), clean_name),
        ).fetchone()
        cursor = connection.execute(
            """
            INSERT INTO bookmaker_accounts(bookmaker_id, account_name, currency, opening_balance, current_balance)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(bookmaker_id, account_name) DO UPDATE SET
                currency = excluded.currency,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(bookmaker_id), clean_name, currency, float(opening_balance), float(opening_balance)),
        )
        account_id = int(existing["id"] if existing else cursor.lastrowid)
        if opening_balance and existing is None:
            add_wallet_transaction(account_id, "initial", float(opening_balance), note="Initial wallet balance", connection=connection)
        return account_id


def add_wallet_transaction(
    account_id: int,
    transaction_type: str,
    amount: float,
    *,
    bet_id: int | None = None,
    note: str | None = None,
    connection=None,
) -> float:
    """Add wallet transaction and return new account balance."""

    if connection is None:
        with transaction() as owned_connection:
            return add_wallet_transaction(
                account_id,
                transaction_type,
                amount,
                bet_id=bet_id,
                note=note,
                connection=owned_connection,
            )
    else:
        row = connection.execute("SELECT current_balance FROM bookmaker_accounts WHERE id = ?", (int(account_id),)).fetchone()
        if not row:
            raise ValueError(f"Bookmaker account {account_id} does not exist")
        balance_after = float(row["current_balance"]) + float(amount)
        connection.execute(
            """
            INSERT INTO bookmaker_wallet_transactions(
                bookmaker_account_id, bet_id, transaction_time, transaction_type, amount, balance_after, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (int(account_id), bet_id, utc_now_iso(), transaction_type, float(amount), balance_after, note),
        )
        connection.execute(
            "UPDATE bookmaker_accounts SET current_balance = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (balance_after, int(account_id)),
        )
        return balance_after


def wallet_transactions(account_id: int | None = None, limit: int = 200) -> pd.DataFrame:
    if account_id:
        return query_df(
            """
            SELECT wt.*, ba.account_name, b.name AS bookmaker
            FROM bookmaker_wallet_transactions wt
            JOIN bookmaker_accounts ba ON ba.id = wt.bookmaker_account_id
            JOIN bookmakers b ON b.id = ba.bookmaker_id
            WHERE wt.bookmaker_account_id = ?
            ORDER BY wt.transaction_time DESC, wt.id DESC
            LIMIT ?
            """,
            (int(account_id), int(limit)),
        )
    return query_df(
        """
        SELECT wt.*, ba.account_name, b.name AS bookmaker
        FROM bookmaker_wallet_transactions wt
        JOIN bookmaker_accounts ba ON ba.id = wt.bookmaker_account_id
        JOIN bookmakers b ON b.id = ba.bookmaker_id
        ORDER BY wt.transaction_time DESC, wt.id DESC
        LIMIT ?
        """,
        (int(limit),),
    )


def latest_model_ev_signals(limit: int = 200, min_ev: float | None = None) -> pd.DataFrame:
    where = "WHERE mes.status = 'new'"
    params: list[float | int] = []
    if min_ev is not None:
        where += " AND mes.ev >= ?"
        params.append(float(min_ev))
    params.append(int(limit))
    return query_df(
        f"""
        SELECT mes.id, mes.side, mes.odds, mes.model_prob, mes.market_prob, mes.ev, mes.tax_rate,
               mes.stake_suggestion, mes.created_at, b.name AS bookmaker,
               os.bookmaker_id, os.offer_url, os.scraped_at,
               cm.id AS canonical_match_id, cm.team_a_name, cm.team_b_name,
               cm.league, cm.start_time_normalized,
               cp.model_name, cp.model_version
        FROM model_ev_signals mes
        JOIN odds_snapshots os ON os.id = mes.odds_snapshot_id
        JOIN bookmakers b ON b.id = mes.bookmaker_id
        JOIN canonical_matches cm ON cm.id = mes.canonical_match_id
        JOIN canonical_predictions cp ON cp.id = mes.canonical_prediction_id
        {where}
        ORDER BY mes.ev DESC, mes.created_at DESC
        LIMIT ?
        """,
        tuple(params),
    )


def record_manual_bet(
    *,
    bookmaker_account_id: int,
    side: str,
    stake: float,
    taken_odds: float,
    bookmaker_id: int | None = None,
    canonical_match_id: int | None = None,
    model_ev_signal_id: int | None = None,
    team_a: str | None = None,
    team_b: str | None = None,
    league: str | None = None,
    match_start_time: str | None = None,
    model_prob: float | None = None,
    ev: float | None = None,
    tax_rate: float = 0.12,
    note: str | None = None,
) -> int:
    if side not in {"a", "b"}:
        raise ValueError("side must be 'a' or 'b'")
    account_row = query_df("SELECT bookmaker_id FROM bookmaker_accounts WHERE id = ?", (int(bookmaker_account_id),))
    if account_row.empty:
        raise ValueError(f"Bookmaker account {bookmaker_account_id} does not exist")
    bookmaker_id = int(bookmaker_id or account_row.iloc[0]["bookmaker_id"])

    with transaction() as connection:
        cursor = connection.execute(
            """
            INSERT INTO bets(
                model_ev_signal_id, bookmaker_account_id, canonical_match_id,
                bookmaker_id, side, stake, taken_odds, team_a, team_b, league,
                match_start_time, model_prob, ev, tax_rate, source, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?)
            """,
            (
                model_ev_signal_id,
                int(bookmaker_account_id),
                canonical_match_id,
                bookmaker_id,
                side,
                float(stake),
                float(taken_odds),
                team_a,
                team_b,
                league,
                match_start_time,
                model_prob,
                ev,
                float(tax_rate),
                note,
            ),
        )
        bet_id = int(cursor.lastrowid)
        add_wallet_transaction(
            int(bookmaker_account_id),
            "bet_placed",
            -float(stake),
            bet_id=bet_id,
            note=f"Bet placed #{bet_id}",
            connection=connection,
        )
        if model_ev_signal_id:
            connection.execute("UPDATE model_ev_signals SET status = 'placed' WHERE id = ?", (int(model_ev_signal_id),))
        return bet_id


def settle_wallet_bet(bet_id: int, result: str, tax_rate: float | None = None) -> float:
    if result not in {"won", "lost", "void", "cancelled"}:
        raise ValueError("result must be won/lost/void/cancelled")
    bet_df = query_df("SELECT * FROM bets WHERE id = ?", (int(bet_id),))
    if bet_df.empty:
        raise ValueError(f"Bet {bet_id} does not exist")
    bet = bet_df.iloc[0]
    stake = float(bet["stake"])
    tax_rate = float(bet["tax_rate"] if tax_rate is None and bet["tax_rate"] is not None else (tax_rate or 0.12))
    if result == "won":
        payout = stake * float(bet["taken_odds"]) * (1.0 - tax_rate)
        profit = payout - stake
    elif result == "lost":
        payout = 0.0
        profit = -stake
    else:
        payout = stake
        profit = 0.0
    with transaction() as connection:
        connection.execute(
            "UPDATE bets SET status = ?, result = ?, profit = ?, settled_at = ? WHERE id = ?",
            (result, result, profit, utc_now_iso(), int(bet_id)),
        )
        account_id = bet.get("bookmaker_account_id")
        if account_id and payout:
            add_wallet_transaction(
                int(account_id),
                f"bet_{result}",
                payout,
                bet_id=int(bet_id),
                note=f"Bet settlement #{bet_id}",
                connection=connection,
            )
    return profit


def tracked_bets() -> pd.DataFrame:
    return query_df(
        """
        SELECT bets.*, b.name AS bookmaker, ba.account_name, ba.currency,
               cm.team_a_name AS canonical_team_a, cm.team_b_name AS canonical_team_b,
               cm.start_time_normalized AS canonical_start_time
        FROM bets
        LEFT JOIN bookmakers b ON b.id = bets.bookmaker_id
        LEFT JOIN bookmaker_accounts ba ON ba.id = bets.bookmaker_account_id
        LEFT JOIN canonical_matches cm ON cm.id = bets.canonical_match_id
        ORDER BY bets.placed_at DESC, bets.id DESC
        """
    )
