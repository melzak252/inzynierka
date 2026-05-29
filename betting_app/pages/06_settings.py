"""Streamlit page: app settings and database info."""

from __future__ import annotations

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install streamlit to run the app: pip install streamlit") from exc

from betting_app.core.config import load_config
from betting_app.core.database import init_db


st.set_page_config(page_title="Settings", layout="wide")
path = init_db()
cfg = load_config()
st.title("Settings")
st.write("Database", str(path))
st.write("Debug dir", str(cfg.debug_dir))
st.write("Tax rate", cfg.tax_rate)
st.write("Default min EV", cfg.min_ev)
st.write("Headless scraping", cfg.scraper_headless)
