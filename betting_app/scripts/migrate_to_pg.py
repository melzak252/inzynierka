"""
Migrate data from SQLite (BETTING_APP_DB) to PostgreSQL/TimescaleDB (DATABASE_URL).

Usage::

    DATABASE_URL=postgresql+psycopg2://betting:pass@localhost:5432/betting \\
        python -m betting_app.scripts.migrate_to_pg
"""

from __future__ import annotations

import os
import sys
import time

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from betting_app.core.db import get_db_path as sqlite_path
from betting_app.core.db import connect as sqlite_connect


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


TABLES: list[tuple[str, str, str, int]] = [
    ("bookmakers",          "bookmakers",           "(name, base_url)",                       50),
    ("bookmaker_accounts",  "bookmaker_accounts",   "(bookmaker_id, account_name, currency, opening_balance, current_balance, is_active)", 200),
    ("golgg_teams",         "golgg_teams",          "(team_name, normalized_name)",  500),
    ("golgg_matches",       "golgg_matches",        "(match_id, date, tournament_name, patch, team1_name, team2_name, team1_id, team2_id, team1_score, team2_score, team1_win, team2_win, draw, games_played, best_of, winner_name, loser_name, source_link, raw_json)", 500),
    ("golgg_games",         "golgg_games",          "(game_id, match_id, date, tournament_name, patch, team1_name, team2_name, team1_id, team2_id, team1_win, team2_win, draw, team1_side, team2_side, game_duration, team1_stats_json, team2_stats_json, raw_json)", 500),
    ("golgg_game_players",  "golgg_game_players",   "(game_id, match_id, team_id, team_name, side, role, player_id, player_name, champion_id, champion_name, champion_image, stats_json, raw_json)", 500),
    ("team_aliases",        "team_aliases",         "(normalized_name, alias, source)",  200),
    ("canonical_matches",   "canonical_matches",    "(canonical_key, team_a_name, team_b_name, normalized_team_a, normalized_team_b, start_time_normalized, league, status, match_confidence)", 200),
    ("odds_snapshots",      "odds_snapshots",       "(bookmaker_id, canonical_match_id, market_type, raw_team_a, raw_team_b, odds_a, odds_b, is_live, scraped_at, source_url, offer_url)", 1000),
    ("scrape_runs",         "scrape_runs",          "(bookmaker_id, scraper_name, scraper_version, started_at, finished_at, status, source_url, request_url, items_seen, items_inserted, error)", 200),
    ("bookmaker_events",    "bookmaker_events",     "(bookmaker_id, bookmaker_event_id, canonical_match_id, raw_team_a, raw_team_b, match_start_time, sport_id, sport_name, category_id, category_name, league_id, league_name, offer_url)", 200),
    ("entity_ratings",      "entity_ratings",       "(ratings_version, entity_type, entity_name, normalized_entity_name, team_name, role, rating_system, rating_value, rd, sigma, games_played, last_match_at, state_json)", 2000),
    ("team_rolling_features", "team_rolling_features", "(feature_version, team_name, normalized_team_name, window_size, data_cutoff_at, matches_count, games_count, win_rate, avg_kills, avg_deaths, avg_gd15, avg_dpm, avg_vspm, avg_gold, avg_towers, avg_dragons, avg_nashors, avg_game_duration, features_json)", 200),
    ("canonical_predictions", "canonical_predictions", "(canonical_match_id, model_name, model_version, prob_a, prob_b, features_version, ratings_version, data_cutoff_at, prediction_status, diagnostics_json)", 500),
    ("model_ev_signals",    "model_ev_signals",     "(canonical_match_id, bookmaker_id, side, odds, model_prob, market_prob, ev, tax_rate, status)", 500),
    ("automation_runs",     "automation_runs",      "(run_type, trigger_source, status, started_at, finished_at, interval_seconds, commands_total, commands_failed, error)", 100),
]


def migrate_table(pg_session: Session, table: str, pg_table: str, cols: str, batch: int) -> int:
    src = sqlite_connect()
    try:
        # Build SELECT for only the columns we need
        cols_stripped = cols.strip("()")
        select_cols = ", ".join(c.strip().split()[0] for c in cols_stripped.split(","))
        cursor = src.execute(f"SELECT {select_cols} FROM {table}")
        all_rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description]
    except Exception as e:
        log(f"  SKIP {table}: {e}")
        src.close()
        return 0

    if not all_rows:
        src.close()
        return 0

    total = len(all_rows)
    placeholders = ", ".join(f":{c}" for c in col_names)
    insert_sql = f"INSERT INTO {pg_table} {cols} VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    inserted = 0
    for i in range(0, total, batch):
        batch_rows = all_rows[i : i + batch]
        pg_session.begin()
        try:
            for row in batch_rows:
                params = dict(zip(col_names, row))
                for k, v in params.items():
                    if v == "" or v is None:
                        params[k] = None
                pg_session.execute(text(insert_sql), params)
            pg_session.commit()
            inserted += len(batch_rows)
            if (i // batch) % 10 == 0:
                log(f"  {inserted}/{total}")
        except Exception as e:
            pg_session.rollback()
            log(f"  ERROR batch {i}: {e}")
            src.close()
            return inserted

    src.close()
    return inserted


def main() -> None:
    pg_url = os.environ.get("DATABASE_URL", "")
    if not pg_url:
        log("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    log(f"Source SQLite:  {sqlite_path()}")
    log(f"Target PG/TimescaleDB: {pg_url}")
    log("")

    engine = create_engine(pg_url, pool_pre_ping=True)
    with Session(engine) as session:
        # Temporarily disable FK triggers for smoother migration
        session.execute(text("SET session_replication_role = 'replica';"))
        session.commit()

        for table, pg_table, cols, batch_size in TABLES:
            log(f"Migrating {table} -> {pg_table} ...")
            done = migrate_table(session, table, pg_table, cols, batch_size)
            log(f"  done ({done} rows)")

        # Re-enable FK triggers
        session.execute(text("SET session_replication_role = 'origin';"))
        session.commit()

        # Fix null normalized names
        session.execute(text("UPDATE team_rolling_features SET normalized_team_name = LOWER(team_name) WHERE normalized_team_name IS NULL"))
        session.execute(text("UPDATE entity_ratings SET normalized_entity_name = LOWER(entity_name) WHERE normalized_entity_name IS NULL"))
        session.commit()

    log("Migration complete.")
    engine.dispose()


if __name__ == "__main__":
    main()
