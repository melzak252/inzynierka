"""Streamlit page: bankroll and result analytics."""

from __future__ import annotations

import pandas as pd

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install streamlit to run the app: pip install streamlit") from exc

from betting_app.core.database import init_db
from betting_app.services.betting_service import bankroll_history, bets, current_bankroll, initialize_bankroll
from betting_app.services.wallet_service import accounts, tracked_bets, wallet_transactions


st.set_page_config(page_title="Bankroll", layout="wide")
init_db()
st.title("Bankroll / wyniki")

with st.expander("Inicjalizacja bankrolla", expanded=False):
    amount = st.number_input("Initial bankroll", min_value=1.0, value=100.0, step=10.0)
    if st.button("Ustaw jeśli baza jest pusta"):
        initialize_bankroll(float(amount))
        st.success("OK")

st.metric("Current bankroll", f"{current_bankroll():.2f}")

st.subheader("Portfele bukmacherów")
wallets = accounts(active_only=True)
if wallets.empty:
    st.info("Brak portfeli bukmacherów. Dodaj je w zakładce Bets / portfele.")
else:
    total_wallet = wallets["current_balance"].sum()
    st.metric("Suma portfeli bukmacherów", f"{total_wallet:.2f}")
    st.dataframe(wallets, use_container_width=True, hide_index=True)

history = bankroll_history()
if not history.empty:
    chart = history.copy()
    chart["event_time"] = pd.to_datetime(chart["event_time"])
    st.line_chart(chart, x="event_time", y="bankroll_after")
    st.dataframe(history, use_container_width=True)

bet_df = bets()
if not bet_df.empty:
    settled = bet_df[bet_df["status"].isin(["won", "lost", "void", "cancelled"])]
    total_profit = settled["profit"].sum() if not settled.empty else 0.0
    total_staked = settled["stake"].sum() if not settled.empty else 0.0
    col1, col2, col3 = st.columns(3)
    col1.metric("Profit", f"{total_profit:.2f}")
    col2.metric("Yield", f"{(total_profit / total_staked * 100) if total_staked else 0:.2f}%")
    col3.metric("Settled bets", len(settled))

st.subheader("Historia zakładów z portfeli")
wallet_bets = tracked_bets()
if not wallet_bets.empty:
    settled_wallet = wallet_bets[wallet_bets["status"].isin(["won", "lost", "void", "cancelled"])]
    total_profit_wallet = settled_wallet["profit"].sum() if not settled_wallet.empty else 0.0
    total_staked_wallet = settled_wallet["stake"].sum() if not settled_wallet.empty else 0.0
    c1, c2, c3 = st.columns(3)
    c1.metric("Wallet profit", f"{total_profit_wallet:.2f}")
    c2.metric("Wallet yield", f"{(total_profit_wallet / total_staked_wallet * 100) if total_staked_wallet else 0:.2f}%")
    c3.metric("Wallet bets", len(wallet_bets))
    st.dataframe(wallet_bets, use_container_width=True, hide_index=True)

st.subheader("Transakcje portfeli")
tx = wallet_transactions(limit=300)
if not tx.empty:
    st.dataframe(tx, use_container_width=True, hide_index=True)
