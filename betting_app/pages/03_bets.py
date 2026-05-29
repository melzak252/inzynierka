"""Streamlit page: bookmaker wallets, manual bet logging and settlement."""

from __future__ import annotations

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install streamlit to run the app: pip install streamlit") from exc

from betting_app.core.config import load_config
from betting_app.core.database import init_db
from betting_app.services.wallet_service import (
    accounts,
    add_wallet_transaction,
    bookmaker_options,
    create_account,
    latest_model_ev_signals,
    record_manual_bet,
    settle_wallet_bet,
    tracked_bets,
    wallet_transactions,
)


st.set_page_config(page_title="Bets / Wallets", layout="wide")
init_db()
cfg = load_config()

st.title("Bets / portfele bukmacherów")
st.caption("Każdy bukmacher może mieć osobny portfel. Zakłady wpisujesz ręcznie: strona, stake, kurs, konto.")


def make_account_options(frame):
    return {
        f"{row['bookmaker']} / {row['account_name']} — {float(row['current_balance']):.2f} {row['currency']}": int(row["id"])
        for _, row in frame.iterrows()
    }


tab_wallets, tab_log_bet, tab_settle, tab_history = st.tabs(
    ["Portfele", "Dodaj zakład", "Rozlicz", "Historia"]
)


with tab_wallets:
    st.subheader("Portfele")
    current_accounts = accounts(active_only=False)
    if current_accounts.empty:
        st.info("Nie masz jeszcze kont/portfeli. Dodaj pierwszy poniżej.")
    else:
        st.dataframe(current_accounts, use_container_width=True, hide_index=True)

    with st.form("create_wallet"):
        bookmakers = bookmaker_options()
        bookmaker_label_to_id = {row["name"]: int(row["id"]) for _, row in bookmakers.iterrows()}
        bookmaker_name = st.selectbox("Bukmacher", options=list(bookmaker_label_to_id.keys()))
        account_name = st.text_input("Nazwa konta/portfela", value="main")
        opening_balance = st.number_input("Saldo startowe", min_value=0.0, value=0.0, step=10.0)
        currency = st.text_input("Waluta", value="PLN")
        submitted = st.form_submit_button("Dodaj / zaktualizuj portfel")
    if submitted:
        create_account(bookmaker_label_to_id[bookmaker_name], account_name, opening_balance, currency)
        st.success("Portfel zapisany")
        st.rerun()

    st.subheader("Wpłata / wypłata / korekta")
    active_accounts = accounts(active_only=True)
    if not active_accounts.empty:
        account_options = make_account_options(active_accounts)
        with st.form("wallet_tx"):
            selected = st.selectbox("Portfel", options=list(account_options.keys()), key="wallet_tx_account")
            tx_type = st.selectbox("Typ", options=["deposit", "withdrawal", "adjustment"])
            amount_abs = st.number_input("Kwota", min_value=0.0, value=0.0, step=10.0)
            note = st.text_input("Notatka")
            tx_submit = st.form_submit_button("Zapisz transakcję")
        if tx_submit:
            amount = float(amount_abs)
            if tx_type == "withdrawal":
                amount = -amount
            add_wallet_transaction(account_options[selected], tx_type, amount, note=note)
            st.success("Transakcja zapisana")
            st.rerun()


with tab_log_bet:
    st.subheader("Dodaj ręcznie postawiony zakład")
    active_accounts = accounts(active_only=True)
    if active_accounts.empty:
        st.warning("Najpierw dodaj portfel bukmachera.")
    else:
        signals = latest_model_ev_signals(limit=200, min_ev=None)
        signal_options = {"brak — ręczny zakład spoza sygnału": None}
        for _, row in signals.iterrows():
            label = (
                f"#{int(row['id'])} {row['bookmaker']} | {row['team_a_name']} vs {row['team_b_name']} "
                f"| side {row['side']} @ {float(row['odds']):.2f} | EV {float(row['ev']) * 100:.1f}%"
            )
            signal_options[label] = int(row["id"])

        account_options = make_account_options(active_accounts)
        with st.form("manual_bet"):
            selected_account = st.selectbox("Portfel", options=list(account_options.keys()))
            selected_signal = st.selectbox("Opcjonalnie sygnał modelu/EV", options=list(signal_options.keys()))
            chosen_signal_id = signal_options[selected_signal]
            signal_row = signals[signals["id"].eq(chosen_signal_id)].iloc[0] if chosen_signal_id else None

            col1, col2 = st.columns(2)
            with col1:
                team_a = st.text_input("Team A", value="" if signal_row is None else str(signal_row["team_a_name"]))
                team_b = st.text_input("Team B", value="" if signal_row is None else str(signal_row["team_b_name"]))
                league = st.text_input("Liga", value="" if signal_row is None else str(signal_row["league"] or ""))
                match_start = st.text_input(
                    "Start",
                    value="" if signal_row is None else str(signal_row["start_time_normalized"] or ""),
                )
            with col2:
                side = st.selectbox("Postawiona strona", options=["a", "b"], index=0 if signal_row is None or signal_row["side"] == "a" else 1)
                stake = st.number_input("Stake", min_value=0.0, value=10.0, step=1.0)
                odds = st.number_input("Kurs", min_value=1.01, value=float(signal_row["odds"]) if signal_row is not None else 2.0, step=0.01)
                note = st.text_input("Notatka")

            submitted = st.form_submit_button("Zapisz zakład i odejmij stake z portfela")
        if submitted:
            account_id = account_options[selected_account]
            record_manual_bet(
                bookmaker_account_id=account_id,
                model_ev_signal_id=chosen_signal_id,
                canonical_match_id=None if signal_row is None else int(signal_row["canonical_match_id"]),
                bookmaker_id=None if signal_row is None else int(signal_row["bookmaker_id"]),
                side=side,
                stake=float(stake),
                taken_odds=float(odds),
                team_a=team_a,
                team_b=team_b,
                league=league,
                match_start_time=match_start,
                model_prob=None if signal_row is None else float(signal_row["model_prob"]),
                ev=None if signal_row is None else float(signal_row["ev"]),
                tax_rate=cfg.tax_rate,
                note=note,
            )
            st.success("Zakład zapisany")
            st.rerun()


with tab_settle:
    st.subheader("Rozlicz otwarty zakład")
    bet_df = tracked_bets()
    open_df = bet_df[bet_df["status"].eq("open")] if not bet_df.empty else bet_df
    if open_df.empty:
        st.info("Brak otwartych zakładów.")
    else:
        st.dataframe(open_df, use_container_width=True, hide_index=True)
        with st.form("settle_bet"):
            bet_id = st.selectbox("Bet ID", options=open_df["id"].astype(int).tolist())
            result = st.selectbox("Wynik", options=["won", "lost", "void", "cancelled"])
            submitted = st.form_submit_button("Rozlicz")
        if submitted:
            profit = settle_wallet_bet(int(bet_id), result, tax_rate=cfg.tax_rate)
            st.success(f"Rozliczono bet #{bet_id}, profit={profit:.2f}")
            st.rerun()


with tab_history:
    st.subheader("Historia zakładów")
    all_bets = tracked_bets()
    if all_bets.empty:
        st.info("Brak zakładów.")
    else:
        st.dataframe(all_bets, use_container_width=True, hide_index=True)

    st.subheader("Historia portfeli")
    st.dataframe(wallet_transactions(limit=500), use_container_width=True, hide_index=True)
