"""Prepare and inspect SQLite tables required for upcoming-match model inference."""

from __future__ import annotations

import argparse
import json

from betting_app.core.database import init_db, query_df, transaction


DEFAULT_MODEL_NAME = "Sym-Cal LR-ElasticNet-W20-Binomial"
DEFAULT_MODEL_VERSION = "exp-039"


def main() -> None:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register-default-model", action="store_true", help="Insert/update the EXP-039 model registry row.")
    args = parser.parse_args()

    db_path = init_db()
    print(f"DB ready: {db_path}")
    if args.register_default_model:
        register_default_model()
    print_counts()


def register_default_model() -> int:
    """Register the final thesis model as the default upcoming-inference target."""

    feature_schema = {
        "rating_signals": ["player_elo", "player_gl", "player_ts", "player_os", "player_pl", "player_tm"],
        "context_window": 20,
        "series_adjustment": "binomial_bo1_bo3_bo5",
        "postprocessing": ["order_symmetry", "expanding_platt"],
    }
    params = {
        "estimator": "LogisticRegression",
        "penalty": "elasticnet",
        "C": 0.033,
        "l1_ratio": 0.944,
        "probability_clip": [0.001, 0.999],
    }
    metrics = {
        "sample": 11609,
        "auc": 0.755055,
        "logloss": 0.585376,
        "brier": 0.200659,
        "ece": 0.010042,
    }
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO model_artifacts(
                model_name, model_version, artifact_path, feature_schema_json,
                model_params_json, training_cutoff_at, metrics_json, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)
            ON CONFLICT(model_name, model_version) DO UPDATE SET
                artifact_path = excluded.artifact_path,
                feature_schema_json = excluded.feature_schema_json,
                model_params_json = excluded.model_params_json,
                training_cutoff_at = excluded.training_cutoff_at,
                metrics_json = excluded.metrics_json,
                status = 'active',
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                DEFAULT_MODEL_NAME,
                DEFAULT_MODEL_VERSION,
                "docs/assets/final_symmetric_calibrated_market_comparison/",
                json.dumps(feature_schema, ensure_ascii=False, sort_keys=True),
                json.dumps(params, ensure_ascii=False, sort_keys=True),
                None,
                json.dumps(metrics, ensure_ascii=False, sort_keys=True),
            ),
        )
        row = connection.execute(
            "SELECT id FROM model_artifacts WHERE model_name = ? AND model_version = ?",
            (DEFAULT_MODEL_NAME, DEFAULT_MODEL_VERSION),
        ).fetchone()
    model_id = int(row["id"])
    print(f"Registered model artifact #{model_id}: {DEFAULT_MODEL_NAME} / {DEFAULT_MODEL_VERSION}")
    return model_id


def print_counts() -> None:
    """Print operational readiness counts."""

    counts = query_df(
        """
        SELECT 'golgg_matches' AS table_name, COUNT(*) AS rows FROM golgg_matches
        UNION ALL SELECT 'golgg_games', COUNT(*) FROM golgg_games
        UNION ALL SELECT 'golgg_game_players', COUNT(*) FROM golgg_game_players
        UNION ALL SELECT 'golgg_teams', COUNT(*) FROM golgg_teams
        UNION ALL SELECT 'canonical_matches', COUNT(*) FROM canonical_matches
        UNION ALL SELECT 'odds_snapshots', COUNT(*) FROM odds_snapshots
        UNION ALL SELECT 'rating_runs', COUNT(*) FROM rating_runs
        UNION ALL SELECT 'entity_ratings', COUNT(*) FROM entity_ratings
        UNION ALL SELECT 'team_rolling_features', COUNT(*) FROM team_rolling_features
        UNION ALL SELECT 'upcoming_match_features', COUNT(*) FROM upcoming_match_features
        UNION ALL SELECT 'model_artifacts', COUNT(*) FROM model_artifacts
        UNION ALL SELECT 'canonical_predictions', COUNT(*) FROM canonical_predictions
        UNION ALL SELECT 'model_ev_signals', COUNT(*) FROM model_ev_signals
        """
    )
    print(counts.to_string(index=False))
    latest = query_df(
        """
        SELECT cm.id, cm.team_a_name || ' vs ' || cm.team_b_name AS match,
               cm.start_time_normalized, COUNT(DISTINCT b.name) AS bookmakers
        FROM canonical_matches cm
        LEFT JOIN odds_snapshots os ON os.canonical_match_id = cm.id
        LEFT JOIN bookmakers b ON b.id = os.bookmaker_id
        WHERE cm.status = 'upcoming'
        GROUP BY cm.id
        ORDER BY cm.start_time_normalized ASC
        LIMIT 10
        """
    )
    if not latest.empty:
        print("\nUpcoming canonical matches sample:")
        print(latest.to_string(index=False))


if __name__ == "__main__":
    main()
