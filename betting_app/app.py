"""Main Streamlit dashboard for LoL odds aggregation and match intelligence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pandas as pd

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover - user-facing runtime guard
    raise SystemExit("Install streamlit to run the app: pip install streamlit") from exc

from betting_app.core.config import load_config
from betting_app.core.database import init_db, query_df
from betting_app.services.canonical_match_service import align_snapshot_odds, parse_iso


DEFAULT_TAX_RATE = 0.12
HYBRID_MODEL_NAME = "Hybrid-PlayerTeam-W20-Market"
HYBRID_MODEL_VERSION = "a0.50-t0.80"
SPORT_MODEL_NAME = "Operational-PlayerTeamRatings-W20"
SPORT_MODEL_VERSION = "v0.2"


def main() -> None:
    st.set_page_config(page_title="LoL Odds Hub", page_icon="🎯", layout="wide")
    db_path = init_db()
    config = load_config()
    tax_rate = float(config.tax_rate or DEFAULT_TAX_RATE)

    st.title("🎯 LoL Odds Hub")
    st.caption(
        "Agregator kursów i sytuacji meczowej: najbliższe mecze, max/średnie kursy, arbitraż, "
        "model, hybryda i składy z ostatniego meczu GOL.GG."
    )

    render_top_status(db_path)
    st.info(
        "Hybryda używa temperatury zgodnie z eksperymentami finansowymi: "
        "**p_hyb = α · temp(p_model, T=0.80) + (1-α) · p_market**, domyślnie **α=0.50**. "
        "W docs/04_experiments EXP-033/034 wskazywały `Hybrid a=0.50 T=0.80` jako praktyczny kompromis."
    )

    filters = render_filters(tax_rate)
    board = load_match_board(
        min_books=int(filters["min_books"]),
        hours_back=int(filters["hours_back"]),
        days_ahead=int(filters["days_ahead"]),
        tax_rate=tax_rate,
    )
    if board.empty:
        st.warning("Brak nadchodzących meczów z kursami dla aktualnych filtrów.")
        return

    render_board_metrics(board)
    clicked_match_id = render_match_table(board)

    selected_match_id = clicked_match_id or render_match_selector(board)
    if selected_match_id is not None:
        render_match_card(int(selected_match_id), tax_rate=tax_rate)


def render_top_status(db_path: str) -> None:
    counts = load_counts()
    cols = st.columns(6)
    cols[0].metric("Mecze", counts.get("canonical_matches", 0))
    cols[1].metric("Snapshoty kursów", counts.get("odds_snapshots", 0))
    cols[2].metric("Bukmacherzy", counts.get("bookmakers_latest", 0))
    cols[3].metric("Predykcje", counts.get("active_predictions", 0))
    cols[4].metric("EV signals", counts.get("new_ev_signals", 0))
    cols[5].metric("Ready features", counts.get("ready_features", 0))
    st.caption(f"Baza: `{db_path}`")


def render_filters(tax_rate: float) -> dict[str, int | float]:
    with st.expander("Filtry", expanded=False):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            min_books = st.number_input("Min bukmacherów", min_value=1, max_value=10, value=1, step=1)
        with col2:
            hours_back = st.number_input("Pokaż zaczęte max X h temu", min_value=0, max_value=48, value=2, step=1)
        with col3:
            days_ahead = st.number_input("Dni do przodu", min_value=1, max_value=30, value=10, step=1)
        with col4:
            st.metric("Podatek w EV", f"{tax_rate:.0%}")
    return {"min_books": int(min_books), "hours_back": int(hours_back), "days_ahead": int(days_ahead)}


def render_board_metrics(board: pd.DataFrame) -> None:
    cols = st.columns(4)
    cols[0].metric("Nadchodzące mecze", len(board))
    cols[1].metric("Arb brutto", int(board["arb_no_tax"].fillna(False).sum()))
    cols[2].metric("Arb po podatku", int(board["arb_after_tax"].fillna(False).sum()))
    best_ev = board[["hybrid_ev_a", "hybrid_ev_b"]].max(axis=1, skipna=True).max()
    cols[3].metric("Najlepsze EV hybrydy", format_pct(best_ev) if pd.notna(best_ev) else "—")


def render_match_table(board: pd.DataFrame) -> int | None:
    st.subheader("Najbliższe mecze")
    display = board.copy()
    display["start"] = pd.to_datetime(display["start_time_normalized"], errors="coerce")
    display["arb"] = display.apply(
        lambda row: "✅ po podatku" if row.get("arb_after_tax") else ("brutto" if row.get("arb_no_tax") else ""),
        axis=1,
    )
    display["hybrid A %"] = display["hybrid_prob_a"].map(format_pct)
    display["hybrid B %"] = display["hybrid_prob_b"].map(format_pct)
    display["EV A %"] = display["hybrid_ev_a"].map(format_pct)
    display["EV B %"] = display["hybrid_ev_b"].map(format_pct)
    columns = [
        "canonical_match_id",
        "start",
        "league",
        "match",
        "bookmaker_count",
        "best_odds_a",
        "best_bookmaker_a",
        "avg_odds_a",
        "best_odds_b",
        "best_bookmaker_b",
        "avg_odds_b",
        "arb",
        "hybrid A %",
        "hybrid B %",
        "EV A %",
        "EV B %",
        "last_scraped_at",
    ]
    rename = {
        "canonical_match_id": "ID",
        "bookmaker_count": "Books",
        "best_odds_a": "Max A",
        "best_bookmaker_a": "Book A",
        "avg_odds_a": "Avg A",
        "best_odds_b": "Max B",
        "best_bookmaker_b": "Book B",
        "avg_odds_b": "Avg B",
        "arb": "Arbitraż",
        "last_scraped_at": "Last scrape",
    }
    table = display[columns].rename(columns=rename)
    event = st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )
    try:
        selected_rows = event.selection.rows
    except Exception:
        selected_rows = []
    if selected_rows:
        return int(table.iloc[int(selected_rows[0])]["ID"])
    return None


def render_match_selector(board: pd.DataFrame) -> int | None:
    labels = [
        f"#{int(row.canonical_match_id)} {row.match} · {row.league or ''} · {row.start_time_normalized or 'brak czasu'}"
        for row in board.itertuples()
    ]
    if not labels:
        return None
    selected = st.selectbox("Albo wybierz mecz z listy", labels)
    return int(selected.split()[0].replace("#", ""))


def render_match_card(canonical_match_id: int, *, tax_rate: float) -> None:
    meta = load_match_meta(canonical_match_id)
    if meta.empty:
        st.warning("Nie znaleziono meczu.")
        return
    row = meta.iloc[0].to_dict()
    team_a = str(row.get("team_a_name") or "Team A")
    team_b = str(row.get("team_b_name") or "Team B")
    st.divider()
    st.header(f"{team_a} vs {team_b}")
    st.caption(f"{row.get('league') or 'brak ligi'} · {row.get('start_time_normalized') or 'brak godziny'}")

    odds = load_aligned_odds(canonical_match_id)
    predictions = load_match_predictions(canonical_match_id)
    features = load_feature_json(canonical_match_id)
    summary = summarize_odds(odds, tax_rate=tax_rate)

    render_match_summary_cards(summary, predictions, team_a, team_b)

    tab1, tab2, tab3, tab4 = st.tabs(["Kursy", "Model", "Składy", "Diagnostyka"])
    with tab1:
        st.subheader("Kursy bukmacherów")
        if odds.empty:
            st.info("Brak kursów.")
        else:
            view = odds.copy()
            view["link"] = view["offer_url"].fillna(view["source_url"])
            st.dataframe(
                view[
                    [
                        "bookmaker",
                        "canonical_odds_a",
                        "canonical_odds_b",
                        "raw_team_a",
                        "raw_team_b",
                        "scraped_at",
                        "link",
                    ]
                ].rename(
                    columns={
                        "canonical_odds_a": f"{team_a}",
                        "canonical_odds_b": f"{team_b}",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
    with tab2:
        st.subheader("Prawdopodobieństwa")
        if predictions.empty:
            st.info("Brak predykcji dla tego meczu.")
        else:
            pred_view = build_prediction_ev_table(predictions, summary, tax_rate=tax_rate)
            st.dataframe(
                pred_view[
                    [
                        "model_name",
                        "model_version",
                        "P(A) %",
                        "P(B) %",
                        "EV A %",
                        "EV B %",
                        "Best A",
                        "Best B",
                        "predicted_at",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )
        hybrid = latest_prediction(predictions, HYBRID_MODEL_NAME, HYBRID_MODEL_VERSION)
        if hybrid:
            ev_a = expected_value(float(hybrid["prob_a"]), float(summary.get("best_odds_a") or 0), tax_rate)
            ev_b = expected_value(float(hybrid["prob_b"]), float(summary.get("best_odds_b") or 0), tax_rate)
            st.write("**EV hybrydy po podatku dla najlepszych kursów**")
            st.write({team_a: format_pct(ev_a), team_b: format_pct(ev_b), "tax": format_pct(tax_rate)})
    with tab3:
        st.subheader("Składy z ostatniego meczu GOL.GG")
        col_a, col_b = st.columns(2)
        with col_a:
            render_roster(team_a, safe_json_get(features, ["player_ratings", "team_a_roster"]))
        with col_b:
            render_roster(team_b, safe_json_get(features, ["player_ratings", "team_b_roster"]))
    with tab4:
        st.subheader("Diagnostyka feature vector")
        if features:
            st.json(
                {
                    "mapping": safe_json_get(features, ["mapping"]),
                    "diagnostics": safe_json_get(features, ["diagnostics"]),
                    "team_rating_prob": safe_json_get(features, ["ratings", "probabilities", "consensus"]),
                    "player_rating_prob": safe_json_get(features, ["player_ratings", "probabilities", "consensus"]),
                    "w20_prob": safe_json_get(features, ["w20", "probability"]),
                }
            )
        else:
            st.info("Brak feature JSON.")


def render_match_summary_cards(summary: dict[str, Any], predictions: pd.DataFrame, team_a: str, team_b: str) -> None:
    hybrid = latest_prediction(predictions, HYBRID_MODEL_NAME, HYBRID_MODEL_VERSION)
    sport = latest_prediction(predictions, SPORT_MODEL_NAME, SPORT_MODEL_VERSION)
    cols = st.columns(6)
    cols[0].metric(f"Max {team_a}", format_odds(summary.get("best_odds_a")), summary.get("best_bookmaker_a") or "")
    cols[1].metric(f"Max {team_b}", format_odds(summary.get("best_odds_b")), summary.get("best_bookmaker_b") or "")
    cols[2].metric("Avg A / B", f"{format_odds(summary.get('avg_odds_a'))} / {format_odds(summary.get('avg_odds_b'))}")
    cols[3].metric("Arbitraż", "TAK" if summary.get("arb_after_tax") else ("brutto" if summary.get("arb_no_tax") else "nie"))
    cols[4].metric("Hybryda P(A)", format_pct(hybrid.get("prob_a") if hybrid else None))
    cols[5].metric("Model P(A)", format_pct(sport.get("prob_a") if sport else None))


def build_prediction_ev_table(predictions: pd.DataFrame, summary: dict[str, Any], *, tax_rate: float) -> pd.DataFrame:
    """Add EV columns for every prediction using best available odds on both sides."""

    frame = predictions.copy()
    best_a = none_or_float(summary.get("best_odds_a"))
    best_b = none_or_float(summary.get("best_odds_b"))
    frame["P(A) %"] = frame["prob_a"].map(format_pct)
    frame["P(B) %"] = frame["prob_b"].map(format_pct)
    frame["Best A"] = format_odds(best_a)
    frame["Best B"] = format_odds(best_b)
    frame["EV A"] = frame["prob_a"].map(lambda probability: expected_value(float(probability), best_a, tax_rate) if best_a else None)
    frame["EV B"] = frame["prob_b"].map(lambda probability: expected_value(float(probability), best_b, tax_rate) if best_b else None)
    frame["EV A %"] = frame["EV A"].map(format_pct)
    frame["EV B %"] = frame["EV B"].map(format_pct)
    return frame


def render_roster(team_name: str, roster: Any) -> None:
    st.write(f"**{team_name}**")
    if not isinstance(roster, dict):
        st.info("Brak rosteru.")
        return
    st.caption(
        f"match_id={roster.get('source_match_id')} · {roster.get('source_match_date')} · {roster.get('source_tournament')}"
    )
    players = roster.get("players") or []
    if not players:
        st.info("Brak graczy.")
        return
    st.dataframe(pd.DataFrame(players), use_container_width=True, hide_index=True)


def load_match_board(*, min_books: int, hours_back: int, days_ahead: int, tax_rate: float) -> pd.DataFrame:
    odds = load_latest_aligned_odds()
    if odds.empty:
        return pd.DataFrame()
    now = datetime.now(UTC)
    max_time = now + pd.Timedelta(days=days_ahead)
    odds["start_dt"] = pd.to_datetime(odds["start_time_normalized"], errors="coerce", utc=True)
    odds = odds[(odds["start_dt"].isna()) | (odds["start_dt"] >= now - pd.Timedelta(hours=hours_back))]
    odds = odds[(odds["start_dt"].isna()) | (odds["start_dt"] <= max_time)]
    records = []
    predictions = load_latest_predictions_for_board()
    for match_id, group in odds.groupby("canonical_match_id"):
        group = group.dropna(subset=["canonical_odds_a", "canonical_odds_b"])
        if group.empty:
            continue
        book_count = int(group["bookmaker"].nunique())
        if book_count < min_books:
            continue
        best_a = group.loc[group["canonical_odds_a"].idxmax()]
        best_b = group.loc[group["canonical_odds_b"].idxmax()]
        record = {
            "canonical_match_id": int(match_id),
            "team_a_name": group.iloc[0]["team_a_name"],
            "team_b_name": group.iloc[0]["team_b_name"],
            "match": f"{group.iloc[0]['team_a_name']} vs {group.iloc[0]['team_b_name']}",
            "league": group.iloc[0]["league"],
            "start_time_normalized": group.iloc[0]["start_time_normalized"],
            "bookmaker_count": book_count,
            "best_odds_a": round(float(best_a["canonical_odds_a"]), 3),
            "best_bookmaker_a": best_a["bookmaker"],
            "avg_odds_a": round(float(group["canonical_odds_a"].mean()), 3),
            "best_odds_b": round(float(best_b["canonical_odds_b"]), 3),
            "best_bookmaker_b": best_b["bookmaker"],
            "avg_odds_b": round(float(group["canonical_odds_b"].mean()), 3),
            "last_scraped_at": group["scraped_at"].max(),
        }
        enrich_arbitrage(record, tax_rate=tax_rate)
        pred = predictions.get(int(match_id), {})
        record.update(pred)
        if pred.get("hybrid_prob_a") is not None:
            record["hybrid_ev_a"] = expected_value(float(pred["hybrid_prob_a"]), float(record["best_odds_a"]), tax_rate)
            record["hybrid_ev_b"] = expected_value(float(pred["hybrid_prob_b"]), float(record["best_odds_b"]), tax_rate)
        else:
            record["hybrid_ev_a"] = None
            record["hybrid_ev_b"] = None
        records.append(record)
    board = pd.DataFrame(records)
    if board.empty:
        return board
    board["start_sort"] = pd.to_datetime(board["start_time_normalized"], errors="coerce", utc=True)
    return board.sort_values(["start_sort", "canonical_match_id"], na_position="last").drop(columns=["start_sort"])


def load_latest_aligned_odds(canonical_match_id: int | None = None) -> pd.DataFrame:
    params: list[Any] = []
    where = "WHERE os.market_type='match_winner' AND COALESCE(os.is_live, 0)=0 AND os.canonical_match_id IS NOT NULL"
    if canonical_match_id is not None:
        where += " AND os.canonical_match_id=?"
        params.append(canonical_match_id)
    frame = query_df(
        f"""
        WITH latest AS (
            SELECT os.*
            FROM odds_snapshots os
            JOIN (
                SELECT canonical_match_id, bookmaker_id, MAX(scraped_at) AS scraped_at
                FROM odds_snapshots os
                {where}
                GROUP BY canonical_match_id, bookmaker_id
            ) lo ON lo.canonical_match_id=os.canonical_match_id
                 AND lo.bookmaker_id=os.bookmaker_id
                 AND lo.scraped_at=os.scraped_at
        )
        SELECT cm.id AS canonical_match_id,
               cm.team_a_name,
               cm.team_b_name,
               cm.normalized_team_a,
               cm.normalized_team_b,
               cm.start_time_normalized,
               cm.league,
               b.name AS bookmaker,
               l.raw_team_a,
               l.raw_team_b,
               l.odds_a,
               l.odds_b,
               l.scraped_at,
               l.source_url,
               l.offer_url
        FROM latest l
        JOIN canonical_matches cm ON cm.id=l.canonical_match_id
        JOIN bookmakers b ON b.id=l.bookmaker_id
        """,
        tuple(params),
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
        aligned_a.append(float(aligned[0]) if aligned else None)
        aligned_b.append(float(aligned[1]) if aligned else None)
    frame["canonical_odds_a"] = aligned_a
    frame["canonical_odds_b"] = aligned_b
    return frame


def load_aligned_odds(canonical_match_id: int) -> pd.DataFrame:
    frame = load_latest_aligned_odds(canonical_match_id)
    if frame.empty:
        return frame
    return frame.sort_values("bookmaker")


def load_match_meta(canonical_match_id: int) -> pd.DataFrame:
    return query_df("SELECT * FROM canonical_matches WHERE id=?", (canonical_match_id,))


def load_match_predictions(canonical_match_id: int) -> pd.DataFrame:
    return query_df(
        """
        SELECT p.*
        FROM canonical_predictions p
        JOIN (
            SELECT model_name, model_version, MAX(predicted_at) AS predicted_at
            FROM canonical_predictions
            WHERE canonical_match_id=? AND prediction_status='active'
            GROUP BY model_name, model_version
        ) latest ON latest.model_name=p.model_name
                 AND latest.model_version=p.model_version
                 AND latest.predicted_at=p.predicted_at
        WHERE p.canonical_match_id=?
        ORDER BY CASE WHEN p.model_name LIKE 'Hybrid%' THEN 0 ELSE 1 END, p.model_name
        """,
        (canonical_match_id, canonical_match_id),
    )


def load_latest_predictions_for_board() -> dict[int, dict[str, Any]]:
    frame = query_df(
        """
        SELECT p.*
        FROM canonical_predictions p
        JOIN (
            SELECT canonical_match_id, model_name, model_version, MAX(predicted_at) AS predicted_at
            FROM canonical_predictions
            WHERE prediction_status='active'
              AND ((model_name=? AND model_version=?) OR (model_name=? AND model_version=?))
            GROUP BY canonical_match_id, model_name, model_version
        ) latest ON latest.canonical_match_id=p.canonical_match_id
                 AND latest.model_name=p.model_name
                 AND latest.model_version=p.model_version
                 AND latest.predicted_at=p.predicted_at
        """,
        (HYBRID_MODEL_NAME, HYBRID_MODEL_VERSION, SPORT_MODEL_NAME, SPORT_MODEL_VERSION),
    )
    result: dict[int, dict[str, Any]] = {}
    for row in frame.to_dict("records"):
        match_id = int(row["canonical_match_id"])
        item = result.setdefault(match_id, {})
        if row["model_name"] == HYBRID_MODEL_NAME:
            item["hybrid_prob_a"] = none_or_float(row.get("prob_a"))
            item["hybrid_prob_b"] = none_or_float(row.get("prob_b"))
        elif row["model_name"] == SPORT_MODEL_NAME:
            item["model_prob_a"] = none_or_float(row.get("prob_a"))
            item["model_prob_b"] = none_or_float(row.get("prob_b"))
    return result


def load_feature_json(canonical_match_id: int) -> dict[str, Any] | None:
    frame = query_df(
        """
        SELECT features_json
        FROM upcoming_match_features
        WHERE canonical_match_id=?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (canonical_match_id,),
    )
    if frame.empty:
        return None
    try:
        return json.loads(str(frame.iloc[0]["features_json"]))
    except Exception:
        return None


def summarize_odds(odds: pd.DataFrame, *, tax_rate: float) -> dict[str, Any]:
    if odds.empty:
        return {}
    best_a = odds.loc[odds["canonical_odds_a"].idxmax()]
    best_b = odds.loc[odds["canonical_odds_b"].idxmax()]
    summary = {
        "best_odds_a": float(best_a["canonical_odds_a"]),
        "best_bookmaker_a": best_a["bookmaker"],
        "avg_odds_a": float(odds["canonical_odds_a"].mean()),
        "best_odds_b": float(best_b["canonical_odds_b"]),
        "best_bookmaker_b": best_b["bookmaker"],
        "avg_odds_b": float(odds["canonical_odds_b"].mean()),
    }
    enrich_arbitrage(summary, tax_rate=tax_rate)
    return summary


def enrich_arbitrage(record: dict[str, Any], *, tax_rate: float) -> None:
    odds_a = none_or_float(record.get("best_odds_a"))
    odds_b = none_or_float(record.get("best_odds_b"))
    if not odds_a or not odds_b or odds_a <= 1 or odds_b <= 1:
        record["arb_no_tax"] = False
        record["arb_after_tax"] = False
        record["arb_margin_no_tax"] = None
        record["arb_margin_after_tax"] = None
        return
    inv = 1 / odds_a + 1 / odds_b
    inv_tax = 1 / (odds_a * (1 - tax_rate)) + 1 / (odds_b * (1 - tax_rate))
    record["arb_no_tax"] = inv < 1
    record["arb_after_tax"] = inv_tax < 1
    record["arb_margin_no_tax"] = 1 - inv
    record["arb_margin_after_tax"] = 1 - inv_tax


def expected_value(probability: float, odds: float, tax_rate: float) -> float:
    return probability * odds * (1 - tax_rate) - 1


def latest_prediction(predictions: pd.DataFrame, model_name: str, model_version: str) -> dict[str, Any] | None:
    if predictions.empty:
        return None
    rows = predictions[(predictions["model_name"] == model_name) & (predictions["model_version"] == model_version)]
    if rows.empty:
        return None
    return rows.iloc[0].to_dict()


def load_counts() -> dict[str, int]:
    frame = query_df(
        """
        SELECT 'canonical_matches' AS key, COUNT(*) AS value FROM canonical_matches
        UNION ALL SELECT 'odds_snapshots', COUNT(*) FROM odds_snapshots
        UNION ALL SELECT 'bookmakers_latest', COUNT(DISTINCT bookmaker_id) FROM odds_snapshots
        UNION ALL SELECT 'active_predictions', COUNT(*) FROM canonical_predictions WHERE prediction_status='active'
        UNION ALL SELECT 'new_ev_signals', COUNT(*) FROM model_ev_signals WHERE status='new'
        UNION ALL SELECT 'ready_features', COUNT(*) FROM upcoming_match_features WHERE feature_status LIKE 'ready%'
        """
    )
    return {str(row["key"]): int(row["value"]) for row in frame.to_dict("records")}


def safe_json_get(raw: Any, path: list[str]) -> Any:
    current = raw
    if isinstance(current, str):
        try:
            current = json.loads(current)
        except Exception:
            return None
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def none_or_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_odds(value: Any) -> str:
    number = none_or_float(value)
    return "—" if number is None else f"{number:.2f}"


def format_pct(value: Any) -> str:
    number = none_or_float(value)
    return "—" if number is None or pd.isna(number) else f"{number * 100:.1f}%"


if __name__ == "__main__":
    main()
