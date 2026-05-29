"""Streamlit page: unattended laptop system status and controls."""

from __future__ import annotations

import subprocess
import sys

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install streamlit to run the app: pip install streamlit") from exc

from betting_app.core.config import load_config
from betting_app.core.database import init_db
from betting_app.services.automation_service import latest_commands, latest_runs, latest_scrape_status, system_counts


st.set_page_config(page_title="System status", layout="wide")
db_path = init_db()
cfg = load_config()


def run_command(module_args: list[str], timeout: int = 600) -> None:
    """Run a Python module command and display its output."""

    command = [sys.executable, "-m", *module_args]
    with st.spinner("Uruchamiam: " + " ".join(command)):
        result = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    if result.returncode == 0:
        st.success("OK")
    else:
        st.error(f"Command failed rc={result.returncode}")
    if result.stdout:
        st.code(result.stdout[-6000:], language="text")
    if result.stderr:
        st.code(result.stderr[-6000:], language="text")


st.title("System status / laptop 24/7")
st.caption("Panel do patrzenia czy automat żyje, bez SSH do laptopa.")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("SQLite DB", str(db_path.name))
with col2:
    st.metric("Domyślny min EV", f"{cfg.min_ev:.1%}")
with col3:
    st.metric("Debug dir", str(cfg.debug_dir.name))


st.subheader("Szybkie akcje")
st.caption("Te akcje odpalają proces w kontenerze/aplikacji. Scheduler w tle i tak działa sam przez docker-compose.")

actions = st.columns(4)
with actions[0]:
    if st.button("Przelicz predykcje/EV", use_container_width=True):
        run_command(["betting_app.scripts.run_upcoming_prediction_pipeline", "--hybrid", "--min-ev", str(cfg.min_ev)])
with actions[1]:
    if st.button("Backup SQLite", use_container_width=True):
        run_command(["betting_app.scripts.backup_sqlite"])
with actions[2]:
    scrape_confirm = st.checkbox("Potwierdzam scrape", help="Odpali lekki cykl, czyli requesty do bukmacherów.")
    if st.button("Lekki cykl teraz", use_container_width=True, disabled=not scrape_confirm):
        run_command(["betting_app.scripts.scheduler", "--mode", "light-once", "--min-ev", str(cfg.min_ev)], timeout=1800)
with actions[3]:
    st.write("Autostart")
    st.success("Docker: restart unless-stopped")


st.subheader("Ostatnie cykle automatyzacji")
runs = latest_runs(20)
if runs.empty:
    st.info("Brak zapisanych cykli automatyzacji. Scheduler zapisze je po następnym uruchomieniu.")
else:
    st.dataframe(runs, use_container_width=True, hide_index=True)

    selected_run = st.selectbox(
        "Pokaż komendy dla run_id",
        options=[None, *runs["id"].tolist()],
        format_func=lambda value: "ostatnie wszystkie" if value is None else str(value),
    )
    st.dataframe(latest_commands(80, run_id=selected_run), use_container_width=True, hide_index=True)


left, right = st.columns(2)
with left:
    st.subheader("Ostatni scrape per bookmaker")
    scrape_status = latest_scrape_status()
    if scrape_status.empty:
        st.info("Brak scrape_runs.")
    else:
        st.dataframe(scrape_status, use_container_width=True, hide_index=True)

with right:
    st.subheader("Stan tabel")
    st.dataframe(system_counts(), use_container_width=True, hide_index=True)


st.subheader("Tryb bez SSH — checklist")
st.markdown(
    """
    1. Uruchom na laptopie: `docker compose up --build -d betting-app betting-scheduler`.
    2. Otwórz panel z drugiego urządzenia w LAN: `http://IP_LAPTOPA:8501`.
    3. Scheduler sam robi lekki cykl co 2h i zapisuje status tutaj.
    4. Do ciężkiego refreshu GOL.GG używaj profilu maintenance co 2–3 dni albo zostaw to na ręczny przycisk/komendę.
    5. Backup SQLite możesz kliknąć z UI; pliki trafiają do `data/backups/`.
    """
)
