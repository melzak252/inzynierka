"""Streamlit page: CLV diagnostics from odds snapshots."""

from __future__ import annotations

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install streamlit to run the app: pip install streamlit") from exc

from betting_app.core.database import init_db, query_df


st.set_page_config(page_title="CLV", layout="wide")
init_db()
st.title("CLV / historia kursów")

st.info("CLV będzie liczone sensownie, gdy ten sam mecz ma wiele snapshotów kursów z różnych timestampów.")

snapshots = query_df(
    """
    SELECT um.id AS match_id, um.raw_team_a, um.raw_team_b, b.name AS bookmaker,
           os.scraped_at, os.odds_a, os.odds_b
    FROM odds_snapshots os
    JOIN upcoming_matches um ON um.id = os.match_id
    JOIN bookmakers b ON b.id = os.bookmaker_id
    ORDER BY um.id, os.scraped_at
    """
)
st.dataframe(snapshots, use_container_width=True)
