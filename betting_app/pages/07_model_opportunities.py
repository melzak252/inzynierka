"""Streamlit page for pricing upcoming matches with model/hybrid probabilities."""

from __future__ import annotations

import subprocess
import sys

import pandas as pd

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install streamlit to run the app: pip install streamlit") from exc

from betting_app.core.database import init_db, query_df
from betting_app.services.canonical_match_service import align_snapshot_odds


DEFAULT_HYBRID_LABEL_PREFIX = "Hybrid-PlayerTeam-W20-Market"


def main() -> None:
    st.set_page_config(page_title="Wycena upcoming LoL", layout="wide")
    db_path = init_db()
    st.title("Wycena upcoming meczów LoL")
    st.caption(f"Baza: `{db_path}` · model, rynek, hybryda, EV po podatku 12%, źródła rosterów i linki do ofert.")

    render_pipeline_controls()
    render_readiness_cards()

    model_options = load_model_options()
    if model_options.empty:
        st.warning("Brak aktywnych predykcji. Uruchom pipeline w panelu powyżej.")
        return

    default_index = default_model_index(model_options)
    col_a, col_b, col_c, col_d = st.columns([3, 1, 1, 1])
    with col_a:
        label = st.selectbox("Model do wyceny", model_options["label"].tolist(), index=default_index)
    with col_b:
        min_ev = st.number_input("Min EV", value=0.05, step=0.01, format="%.2f")
    with col_c:
        min_books = st.number_input("Min bukmacherów", min_value=1, value=1, step=1)
    with col_d:
        show_all = st.checkbox("Pokaż też EV < próg", value=False)

    selected = model_options.loc[model_options["label"] == label].iloc[0]
    rows = load_opportunities(
        str(selected["model_name"]),
        str(selected["model_version"]),
        min_ev if not show_all else -999.0,
        int(min_books),
    )
    if rows.empty:
        st.info("Brak opportunities dla aktualnych filtrów.")
        return

    render_opportunities(rows)
    render_match_details(rows)


def render_pipeline_controls() -> None:
    with st.expander("Sterowanie pipeline", expanded=False):
        st.write("Najczęściej używaj lekkiego trybu: scrape bukmacherów → canonical matching → features → model → hybryda → EV.")
        col1, col2, col3 = st.columns(3)
        with col1:
            min_ev = st.number_input("EV threshold dla pipeline", value=0.05, step=0.01, format="%.2f", key="pipeline_min_ev")
        with col2:
            skip_scrape = st.checkbox("Nie scrape'uj kursów", value=True)
        with col3:
            heavy = st.checkbox("Ciężki rebuild GOL.GG/ratingów/W20", value=False)
        if st.button("Uruchom pipeline hybrydowy", type="primary"):
            command = [sys.executable, "-m", "betting_app.scripts.run_daily_automation", "--hybrid", "--min-ev", str(min_ev)]
            if skip_scrape:
                command.append("--skip-scrape")
            if heavy:
                command.extend(["--refresh-golgg", "--reimport-golgg", "--rebuild-ratings", "--rebuild-w20"])
            with st.spinner("Pipeline działa..."):
                result = subprocess.run(command, cwd=str(db_project_root()), text=True, capture_output=True, timeout=1800)
            st.code("$ " + " ".join(command))
            if result.returncode == 0:
                st.success("Pipeline zakończony.")
                st.code(result.stdout[-5000:] or "OK")
            else:
                st.error("Pipeline zwrócił błąd.")
                st.code((result.stdout + "\n" + result.stderr)[-8000:])


def render_readiness_cards() -> None:
    counts = load_readiness_counts()
    cols = st.columns(6)
    labels = [
        ("Canonical", "canonical_matches"),
        ("Odds", "odds_snapshots"),
        ("Features", "ready_features"),
        ("Predictions", "active_predictions"),
        ("EV signals", "new_ev_signals"),
        ("Bookmakers", "bookmakers_latest"),
    ]
    for col, (label, key) in zip(cols, labels, strict=False):
        col.metric(label, int(counts.get(key, 0)))
    stale = load_staleness()
    if stale:
        st.caption(" · ".join(stale))


def render_opportunities(rows: pd.DataFrame) -> None:
    view = rows.copy()
    view["side_team"] = view.apply(lambda row: row["team_a_name"] if row["side"] == "a" else row["team_b_name"], axis=1)
    view["EV %"] = view["ev"] * 100
    view["Model %"] = view["model_prob"] * 100
    view["Market %"] = view["market_prob"] * 100
    view["start"] = pd.to_datetime(view["start_time_normalized"], errors="coerce")
    display = view[
        [
            "canonical_match_id",
            "start",
            "league",
            "match",
            "best_odds_a",
            "best_bookmaker_a",
            "avg_odds_a",
            "best_odds_b",
            "best_bookmaker_b",
            "avg_odds_b",
            "side_team",
            "bookmaker",
            "odds",
            "Model %",
            "Market %",
            "EV %",
            "stake_suggestion",
            "bookmaker_count",
            "a_roster_match_id",
            "b_roster_match_id",
            "offer_url",
        ]
    ].rename(
        columns={
            "canonical_match_id": "ID",
            "best_odds_a": "Best A",
            "best_bookmaker_a": "Book A",
            "avg_odds_a": "Avg A",
            "best_odds_b": "Best B",
            "best_bookmaker_b": "Book B",
            "avg_odds_b": "Avg B",
            "side_team": "Bet side",
            "bookmaker_count": "Books",
            "a_roster_match_id": "Roster A match",
            "b_roster_match_id": "Roster B match",
        }
    )
    st.subheader("Najlepsze opportunities")
    st.dataframe(display, use_container_width=True, hide_index=True)


def render_match_details(rows: pd.DataFrame) -> None:
    st.subheader("Szczegóły meczu")
    match_labels = [f"#{int(row.canonical_match_id)} {row.match}" for row in rows.itertuples()]
    selected = st.selectbox("Wybierz mecz", sorted(set(match_labels)))
    match_id = int(selected.split()[0].replace("#", ""))
    col1, col2 = st.columns(2)
    with col1:
        st.write("**Kursy bukmacherów**")
        st.dataframe(load_match_odds(match_id), use_container_width=True, hide_index=True)
    with col2:
        st.write("**Feature / roster diagnostics**")
        diag = load_match_diagnostics(match_id)
        if diag.empty:
            st.info("Brak feature diagnostics.")
        else:
            st.json(diag.iloc[0].to_dict())


def load_model_options() -> pd.DataFrame:
    return query_df(
        """
        SELECT DISTINCT model_name || ' / ' || model_version AS label, model_name, model_version
        FROM canonical_predictions
        WHERE prediction_status = 'active'
        ORDER BY CASE WHEN model_name LIKE 'Hybrid%' THEN 0 ELSE 1 END, model_name, model_version
        """
    )


def default_model_index(options: pd.DataFrame) -> int:
    for idx, row in enumerate(options.to_dict("records")):
        if str(row["model_name"]).startswith(DEFAULT_HYBRID_LABEL_PREFIX):
            return idx
    return 0


def load_opportunities(model_name: str, model_version: str, min_ev: float, min_books: int) -> pd.DataFrame:
    frame = query_df(
        """
        WITH latest_pred AS (
            SELECT p.*
            FROM canonical_predictions p
            JOIN (
                SELECT canonical_match_id, model_name, model_version, MAX(predicted_at) AS predicted_at
                FROM canonical_predictions
                WHERE prediction_status='active' AND model_name=? AND model_version=?
                GROUP BY canonical_match_id, model_name, model_version
            ) lp ON lp.canonical_match_id=p.canonical_match_id
                AND lp.model_name=p.model_name
                AND lp.model_version=p.model_version
                AND lp.predicted_at=p.predicted_at
        ), book_counts AS (
            SELECT canonical_match_id, COUNT(DISTINCT bookmaker_id) AS bookmaker_count
            FROM odds_snapshots
            GROUP BY canonical_match_id
        ), ranked_signals AS (
            SELECT mes.*, ROW_NUMBER() OVER (PARTITION BY canonical_prediction_id ORDER BY ev DESC, id DESC) AS rn
            FROM model_ev_signals mes
            WHERE status='new' AND ev >= ?
        )
        SELECT cm.id AS canonical_match_id,
               cm.team_a_name,
               cm.team_b_name,
               cm.team_a_name || ' vs ' || cm.team_b_name AS "match",
               cm.start_time_normalized,
               cm.league,
               COALESCE(bc.bookmaker_count, 0) AS bookmaker_count,
               b.name AS bookmaker,
               rs.side,
               rs.odds,
               rs.model_prob,
               rs.market_prob,
               rs.ev,
               rs.stake_suggestion,
               os.offer_url,
               json_extract(umf.features_json, '$.player_ratings.team_a_roster.source_match_id') AS a_roster_match_id,
               json_extract(umf.features_json, '$.player_ratings.team_b_roster.source_match_id') AS b_roster_match_id
        FROM latest_pred lp
        JOIN canonical_matches cm ON cm.id=lp.canonical_match_id
        JOIN ranked_signals rs ON rs.canonical_prediction_id=lp.id AND rs.rn=1
        JOIN bookmakers b ON b.id=rs.bookmaker_id
        JOIN odds_snapshots os ON os.id=rs.odds_snapshot_id
        LEFT JOIN book_counts bc ON bc.canonical_match_id=cm.id
        LEFT JOIN upcoming_match_features umf
          ON umf.canonical_match_id=cm.id
         AND umf.feature_version=lp.features_version
         AND umf.ratings_version=lp.ratings_version
        WHERE COALESCE(bc.bookmaker_count, 0) >= ?
        ORDER BY rs.ev DESC, cm.start_time_normalized ASC
        """,
        (model_name, model_version, min_ev, min_books),
    )
    if frame.empty:
        return frame
    summary = load_odds_summary(frame["canonical_match_id"].dropna().astype(int).unique().tolist())
    if not summary.empty:
        frame = frame.merge(summary, on="canonical_match_id", how="left")
    return frame


def load_odds_summary(canonical_match_ids: list[int]) -> pd.DataFrame:
    """Return aligned best/average odds per canonical side for selected matches."""

    if not canonical_match_ids:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in canonical_match_ids)
    odds = query_df(
        f"""
        WITH latest AS (
            SELECT os.*
            FROM odds_snapshots os
            JOIN (
                SELECT canonical_match_id, bookmaker_id, MAX(scraped_at) AS scraped_at
                FROM odds_snapshots
                WHERE canonical_match_id IN ({placeholders})
                  AND market_type='match_winner'
                  AND COALESCE(is_live, 0)=0
                GROUP BY canonical_match_id, bookmaker_id
            ) lo ON lo.canonical_match_id=os.canonical_match_id
                 AND lo.bookmaker_id=os.bookmaker_id
                 AND lo.scraped_at=os.scraped_at
        )
        SELECT cm.id AS canonical_match_id,
               cm.normalized_team_a,
               cm.normalized_team_b,
               b.name AS bookmaker,
               l.raw_team_a,
               l.raw_team_b,
               l.odds_a,
               l.odds_b
        FROM latest l
        JOIN canonical_matches cm ON cm.id=l.canonical_match_id
        JOIN bookmakers b ON b.id=l.bookmaker_id
        """,
        tuple(canonical_match_ids),
    )
    records: list[dict[str, object]] = []
    for match_id, group in odds.groupby("canonical_match_id"):
        aligned_rows = []
        for row in group.to_dict("records"):
            aligned = align_snapshot_odds(
                str(row.get("normalized_team_a") or ""),
                str(row.get("normalized_team_b") or ""),
                str(row.get("raw_team_a") or ""),
                str(row.get("raw_team_b") or ""),
                row.get("odds_a"),
                row.get("odds_b"),
            )
            if aligned is None:
                continue
            aligned_rows.append((str(row.get("bookmaker") or ""), float(aligned[0]), float(aligned[1])))
        if not aligned_rows:
            continue
        best_a = max(aligned_rows, key=lambda item: item[1])
        best_b = max(aligned_rows, key=lambda item: item[2])
        records.append(
            {
                "canonical_match_id": int(match_id),
                "best_odds_a": round(best_a[1], 3),
                "best_bookmaker_a": best_a[0],
                "avg_odds_a": round(sum(item[1] for item in aligned_rows) / len(aligned_rows), 3),
                "best_odds_b": round(best_b[2], 3),
                "best_bookmaker_b": best_b[0],
                "avg_odds_b": round(sum(item[2] for item in aligned_rows) / len(aligned_rows), 3),
            }
        )
    return pd.DataFrame(records)


def load_match_odds(canonical_match_id: int) -> pd.DataFrame:
    frame = query_df(
        """
        WITH latest AS (
            SELECT os.*
            FROM odds_snapshots os
            JOIN (
                SELECT bookmaker_id, MAX(scraped_at) AS scraped_at
                FROM odds_snapshots
                WHERE canonical_match_id=?
                GROUP BY bookmaker_id
            ) lo ON lo.bookmaker_id=os.bookmaker_id AND lo.scraped_at=os.scraped_at
            WHERE os.canonical_match_id=?
        )
        SELECT cm.normalized_team_a,
               cm.normalized_team_b,
               b.name AS bookmaker, raw_team_a, odds_a, raw_team_b, odds_b, scraped_at, offer_url
        FROM latest l
        JOIN canonical_matches cm ON cm.id=l.canonical_match_id
        JOIN bookmakers b ON b.id=l.bookmaker_id
        ORDER BY b.name
        """,
        (canonical_match_id, canonical_match_id),
    )
    if frame.empty:
        return frame
    aligned_a: list[float | None] = []
    aligned_b: list[float | None] = []
    for row in frame.to_dict("records"):
        aligned = align_snapshot_odds(
            str(row.get("normalized_team_a") or ""),
            str(row.get("normalized_team_b") or ""),
            str(row.get("raw_team_a") or ""),
            str(row.get("raw_team_b") or ""),
            row.get("odds_a"),
            row.get("odds_b"),
        )
        aligned_a.append(round(aligned[0], 3) if aligned else None)
        aligned_b.append(round(aligned[1], 3) if aligned else None)
    frame["canonical_odds_a"] = aligned_a
    frame["canonical_odds_b"] = aligned_b
    return frame


def load_match_diagnostics(canonical_match_id: int) -> pd.DataFrame:
    return query_df(
        """
        SELECT feature_status,
               missing_reason,
               team_a_golgg_name,
               team_b_golgg_name,
               json_extract(features_json, '$.player_ratings.team_a_roster.source_match_id') AS a_roster_match_id,
               json_extract(features_json, '$.player_ratings.team_a_roster.source_match_date') AS a_roster_date,
               json_extract(features_json, '$.player_ratings.team_b_roster.source_match_id') AS b_roster_match_id,
               json_extract(features_json, '$.player_ratings.team_b_roster.source_match_date') AS b_roster_date,
               json_extract(features_json, '$.player_ratings.probabilities.consensus') AS player_rating_prob,
               json_extract(features_json, '$.ratings.probabilities.consensus') AS team_rating_prob,
               json_extract(features_json, '$.w20.probability') AS w20_prob
        FROM upcoming_match_features
        WHERE canonical_match_id=?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (canonical_match_id,),
    )


def load_readiness_counts() -> dict[str, int]:
    frame = query_df(
        """
        SELECT 'canonical_matches' AS key, COUNT(*) AS value FROM canonical_matches
        UNION ALL SELECT 'odds_snapshots', COUNT(*) FROM odds_snapshots
        UNION ALL SELECT 'ready_features', COUNT(*) FROM upcoming_match_features WHERE feature_status LIKE 'ready%'
        UNION ALL SELECT 'active_predictions', COUNT(*) FROM canonical_predictions WHERE prediction_status='active'
        UNION ALL SELECT 'new_ev_signals', COUNT(*) FROM model_ev_signals WHERE status='new'
        UNION ALL SELECT 'bookmakers_latest', COUNT(DISTINCT bookmaker_id) FROM odds_snapshots
        """
    )
    return {str(row["key"]): int(row["value"]) for row in frame.to_dict("records")}


def load_staleness() -> list[str]:
    frame = query_df(
        """
        SELECT b.name AS bookmaker, MAX(os.scraped_at) AS last_scraped_at, COUNT(*) AS rows
        FROM odds_snapshots os
        JOIN bookmakers b ON b.id=os.bookmaker_id
        GROUP BY b.name
        ORDER BY b.name
        """
    )
    return [f"{row.bookmaker}: {row.last_scraped_at}" for row in frame.itertuples()]


def db_project_root():
    from betting_app.core.config import PROJECT_ROOT

    return PROJECT_ROOT


if __name__ == "__main__":
    main()
