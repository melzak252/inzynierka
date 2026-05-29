"""Streamlit entrypoint for the LoL Betting Manager MVP."""

from __future__ import annotations

import pandas as pd

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover - user-facing runtime guard
    raise SystemExit("Install streamlit to run the app: pip install streamlit") from exc

from betting_app.core.database import init_db
from betting_app.services.betting_service import bankroll_history, current_bankroll, initialize_bankroll, signals
from betting_app.services.odds_service import latest_odds


def main() -> None:
    """Render the main Streamlit dashboard."""

    st.set_page_config(page_title="LoL Betting Manager", layout="wide")
    db_path = init_db()
    initialize_bankroll(100.0)

    st.title("LoL Betting Manager")
    st.caption(f"Lokalna baza: `{db_path}`")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Bankroll", f"{current_bankroll():.2f}")
    with col2:
        open_signals = signals("new")
        st.metric("Nowe sygnały", len(open_signals))
    with col3:
        odds = latest_odds(1000)
        st.metric("Snapshoty kursów", len(odds))

    st.subheader("Najnowsze sygnały EV+")
    if open_signals.empty:
        st.info("Brak nowych sygnałów. Dodaj kurs/predykcję albo uruchom scraper i generate_signals().")
    else:
        view = open_signals.copy()
        view["ev_pct"] = view["ev"] * 100
        view["model_prob_pct"] = view["model_prob"] * 100
        st.dataframe(
            view[
                [
                    "id",
                    "bookmaker",
                    "raw_team_a",
                    "raw_team_b",
                    "side",
                    "odds",
                    "model_prob_pct",
                    "ev_pct",
                    "suggested_stake",
                    "scraped_at",
                ]
            ],
            use_container_width=True,
        )

    st.subheader("Bankroll")
    history = bankroll_history()
    if len(history) > 1:
        chart = history.copy()
        chart["event_time"] = pd.to_datetime(chart["event_time"])
        st.line_chart(chart, x="event_time", y="bankroll_after")
    else:
        st.info("Bankroll chart pojawi się po pierwszych rozliczonych zakładach.")


if __name__ == "__main__":
    main()
