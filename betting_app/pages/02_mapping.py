"""Streamlit page: raw bookmaker team-name mapping."""

from __future__ import annotations

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install streamlit to run the app: pip install streamlit") from exc

from betting_app.core.database import init_db, query_df
from betting_app.services.mapping_service import known_golgg_teams, suggest_mapping, sync_golgg_teams, unmapped_raw_teams, upsert_alias


st.set_page_config(page_title="Team Mapping", layout="wide")
init_db()
st.title("Mapowanie drużyn")

if st.button("Synchronizuj drużyny z data/golgg_matches.json"):
    count = sync_golgg_teams()
    st.success(f"Zsynchronizowano kandydatów: {count}")

teams_df = known_golgg_teams()
team_names = teams_df["team_name"].tolist() if not teams_df.empty else []
unmapped = unmapped_raw_teams()

st.subheader("Niepotwierdzone nazwy z bukmacherów")
if unmapped.empty:
    st.info("Brak niepotwierdzonych nazw.")
else:
    raw_name = st.selectbox("Raw name", options=unmapped["raw_name"].tolist())
    suggestion, confidence = suggest_mapping(raw_name)
    default_idx = team_names.index(suggestion) if suggestion in team_names else 0 if team_names else None
    if not team_names:
        canonical = st.text_input("GOL.GG team name", value=suggestion or raw_name)
    else:
        canonical = st.selectbox("GOL.GG team", options=team_names, index=default_idx)
    st.write(f"Sugestia: `{suggestion}` confidence={confidence:.3f}")
    if st.button("Zatwierdź alias"):
        alias_id = upsert_alias(raw_name, canonical, source="bookmaker", confirmed=True)
        st.success(f"Zapisano alias #{alias_id}: {raw_name} -> {canonical}")

st.subheader("Alias table")
st.dataframe(query_df("SELECT * FROM team_aliases ORDER BY updated_at DESC"), use_container_width=True)
