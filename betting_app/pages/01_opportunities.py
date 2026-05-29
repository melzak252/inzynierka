"""Streamlit page: odds, predictions and EV signals."""

from __future__ import annotations

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install streamlit to run the app: pip install streamlit") from exc

from betting_app.core.database import init_db, query_df
from betting_app.services.betting_service import generate_signals, place_bet, signals
from betting_app.services.odds_service import insert_odds_snapshot, latest_odds
from betting_app.services.prediction_service import add_prediction


st.set_page_config(page_title="Opportunities", layout="wide")
init_db()
st.title("Opportunities / EV+")

with st.expander("Dodaj ręcznie snapshot kursów", expanded=False):
    with st.form("manual_odds"):
        bookmaker = st.text_input("Bukmacher", value="manual")
        raw_team_a = st.text_input("Team A")
        raw_team_b = st.text_input("Team B")
        odds_a = st.number_input("Kurs A", min_value=1.01, value=2.00, step=0.01)
        odds_b = st.number_input("Kurs B", min_value=1.01, value=1.80, step=0.01)
        league = st.text_input("Liga/turniej", value="")
        start_time = st.text_input("Start time ISO/opis", value="")
        submitted = st.form_submit_button("Zapisz snapshot")
    if submitted:
        snapshot_id = insert_odds_snapshot(
            {
                "bookmaker": bookmaker,
                "raw_team_a": raw_team_a,
                "raw_team_b": raw_team_b,
                "odds_a": odds_a,
                "odds_b": odds_b,
                "raw_league": league or None,
                "match_start_time": start_time or None,
                "scraper_name": "manual_streamlit",
            }
        )
        st.success(f"Zapisano snapshot #{snapshot_id}")

with st.expander("Dodaj ręcznie predykcję do meczu", expanded=False):
    matches = query_df("SELECT id, raw_team_a, raw_team_b, match_start_time FROM upcoming_matches ORDER BY id DESC")
    if matches.empty:
        st.info("Najpierw dodaj snapshot kursów.")
    else:
        with st.form("manual_prediction"):
            labels = {
                int(row.id): f"#{int(row.id)} {row.raw_team_a} vs {row.raw_team_b} ({row.match_start_time or 'brak daty'})"
                for _, row in matches.iterrows()
            }
            match_id = st.selectbox("Mecz", options=list(labels), format_func=lambda value: labels[value])
            prob_a = st.slider("P(Team A wins)", min_value=0.01, max_value=0.99, value=0.50, step=0.01)
            submitted = st.form_submit_button("Zapisz predykcję")
        if submitted:
            prediction_id = add_prediction(match_id=int(match_id), prob_a=float(prob_a))
            st.success(f"Zapisano predykcję #{prediction_id}")

col1, col2 = st.columns(2)
with col1:
    min_ev = st.number_input("Minimalne EV", min_value=0.0, max_value=1.0, value=0.05, step=0.01)
with col2:
    if st.button("Przelicz sygnały EV+"):
        created = generate_signals(min_ev=min_ev)
        st.success(f"Nowe sygnały: {created}")

st.subheader("Nowe sygnały")
df = signals("new")
if df.empty:
    st.info("Brak sygnałów EV+.")
else:
    display = df.copy()
    display["ev_pct"] = display["ev"] * 100
    display["model_prob_pct"] = display["model_prob"] * 100
    st.dataframe(display, use_container_width=True)
    with st.form("place_bet"):
        signal_id = st.selectbox("Signal ID", options=display["id"].astype(int).tolist())
        stake = st.number_input("Stawka", min_value=0.01, value=2.0, step=1.0)
        taken_odds = st.number_input("Kurs faktycznie zagrany", min_value=1.01, value=float(display.iloc[0]["odds"]), step=0.01)
        note = st.text_input("Notatka", value="")
        submitted = st.form_submit_button("Oznacz jako postawione")
    if submitted:
        bet_id = place_bet(signal_id=int(signal_id), stake=float(stake), taken_odds=float(taken_odds), note=note or None)
        st.success(f"Dodano bet #{bet_id}")

st.subheader("Najnowsze snapshoty kursów")
st.dataframe(latest_odds(200), use_container_width=True)
