"""Backfill historical and upcoming predictions for EXP-081 Siamese Series model.

Evaluates Symmetrized-Siamese-Series-EXP081 and its operational hybrid on canonical
matches with existing precomputed features in upcoming_match_features.

Temporal contract:
    data_cutoff_at <= predicted_at < start_time_normalized

Usage:
    # Dry run
    python -m betting_app.scripts.backfill_exp081_predictions

    # Apply backfill to database
    python -m betting_app.scripts.backfill_exp081_predictions --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import text

from betting_app.core.db import get_session, query_df
from betting_app.core.models import (
    EXP081_SIAMESE,
    ModelSpec,
    get_active_hybrid,
    get_model,
)
from betting_app.core.models.engine import PredictionEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _parse_iso(val: Any) -> datetime | None:
    if val is None or val == "":
        return None
    try:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def ensure_model_artifact_registered(session, spec: ModelSpec) -> int:
    """Ensure ModelSpec is registered in model_artifacts and return its id."""
    row = session.execute(
        text(
            """
            SELECT id FROM model_artifacts
            WHERE model_name = :name AND model_version = :version
            LIMIT 1
            """
        ),
        {"name": spec.name, "version": spec.version},
    ).fetchone()

    if row:
        return int(row[0])

    feature_schema = json.dumps(
        {
            "feature_version": spec.feature_version,
            "ratings_version": spec.ratings_version,
            "w20_version": spec.w20_version,
            "family": spec.family,
            "target": spec.target,
        },
        sort_keys=True,
    )
    model_params = json.dumps(
        {
            "family": spec.family,
            "has_epistemic_uncertainty": spec.has_epistemic_uncertainty,
            "prediction_target": spec.prediction_target,
        },
        sort_keys=True,
    )

    cursor = session.execute(
        text(
            """
            INSERT INTO model_artifacts (
                model_name, model_version, feature_schema_json,
                model_params_json, status
            ) VALUES (
                :name, :version, :schema, :params, 'active'
            )
            RETURNING id
            """
        ),
        {
            "name": spec.name,
            "version": spec.version,
            "schema": feature_schema,
            "params": model_params,
        },
    )
    new_id = cursor.scalar()
    return int(new_id)


def load_market_prob_for_match(session, canonical_match_id: int) -> float | None:
    """Load latest pre-match consensus market probability for Team A if available."""
    row = session.execute(
        text(
            """
            SELECT odds_a, odds_b
            FROM odds_snapshots
            WHERE canonical_match_id = :match_id
              AND odds_a > 1.0 AND odds_b > 1.0
            ORDER BY scraped_at DESC
            LIMIT 1
            """
        ),
        {"match_id": canonical_match_id},
    ).fetchone()

    if row and row[0] and row[1]:
        inv_a = 1.0 / float(row[0])
        inv_b = 1.0 / float(row[1])
        book_sum = inv_a + inv_b
        if book_sum > 0:
            return inv_a / book_sum

    return None


def backfill_predictions(
    *,
    apply: bool = False,
    overwrite: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Evaluate and backfill EXP-081 predictions across historical and upcoming matches."""
    active_model = EXP081_SIAMESE
    active_hybrid = get_active_hybrid()

    query = """
        SELECT
            umf.id AS feature_row_id,
            umf.canonical_match_id,
            umf.feature_version,
            umf.ratings_version,
            umf.data_cutoff_at,
            umf.feature_status,
            umf.features_json,
            cm.start_time_normalized,
            cm.status AS match_status,
            cm.team_a_name,
            cm.team_b_name,
            cm.winner_side,
            cm.best_of
        FROM upcoming_match_features umf
        JOIN canonical_matches cm ON cm.id = umf.canonical_match_id
        WHERE umf.feature_status IN ('ready_player', 'partial')
        ORDER BY cm.start_time_normalized ASC NULLS LAST, umf.id ASC
    """
    df = query_df(query)
    total_candidates = len(df)
    logger.info("Found %d candidate feature rows in upcoming_match_features", total_candidates)

    if limit:
        df = df.head(limit)
        logger.info("Limited to %d rows for execution", len(df))

    # Deduplicate by canonical_match_id (prefer latest feature row)
    df = df.drop_duplicates(subset=["canonical_match_id"], keep="last")
    logger.info("Unique canonical matches to process: %d", len(df))

    records = df.to_dict("records")
    eval_stats = {
        "processed": 0,
        "pure_predictions": 0,
        "hybrid_predictions": 0,
        "skipped_existing": 0,
        "errors": 0,
        "finished_evaluated": 0,
        "log_loss_sum": 0.0,
        "brier_sum": 0.0,
        "correct_picks": 0,
    }

    with get_session() as session:
        pure_artifact_id = ensure_model_artifact_registered(session, active_model)
        hybrid_artifact_id = ensure_model_artifact_registered(
            session,
            ModelSpec(
                name=active_hybrid.hybrid_model_name,
                version=active_hybrid.hybrid_model_version,
                family="hybrid_blend",
                feature_version=active_model.feature_version,
                ratings_version=active_model.ratings_version,
                w20_version=active_model.w20_version,
                prediction_target=active_model.prediction_target,
            ),
        )
        if apply:
            session.commit()

        # Check existing predictions if not overwrite
        existing_preds: set[tuple[int, str, str]] = set()
        if not overwrite:
            existing_rows = session.execute(
                text(
                    """
                    SELECT canonical_match_id, model_name, model_version
                    FROM canonical_predictions
                    WHERE model_name IN (:pure_name, :hybrid_name)
                    """
                ),
                {
                    "pure_name": active_model.name,
                    "hybrid_name": active_hybrid.hybrid_model_name,
                },
            ).fetchall()
            for er in existing_rows:
                existing_preds.add((int(er[0]), str(er[1]), str(er[2])))

        for rec in records:
            match_id = int(rec["canonical_match_id"])
            eval_stats["processed"] += 1

            already_pure = (match_id, active_model.name, active_model.version) in existing_preds
            already_hybrid = (
                match_id,
                active_hybrid.hybrid_model_name,
                active_hybrid.hybrid_model_version,
            ) in existing_preds

            if already_pure and already_hybrid and not overwrite:
                eval_stats["skipped_existing"] += 1
                continue

            try:
                features = json.loads(rec["features_json"] or "{}")
            except Exception as e:
                logger.warning("Could not parse features_json for match %d: %s", match_id, e)
                eval_stats["errors"] += 1
                continue

            # Ensure canonical match info in features
            if "canonical" not in features:
                features["canonical"] = {}
            if rec.get("best_of") is not None and "best_of" not in features["canonical"]:
                features["canonical"]["best_of"] = rec["best_of"]
            if rec.get("start_time_normalized") and "start_time_normalized" not in features["canonical"]:
                features["canonical"]["start_time_normalized"] = rec["start_time_normalized"]

            try:
                res = PredictionEngine.predict_from_features(features, model_spec=active_model)
            except Exception as e:
                logger.warning("Inference failed for match %d: %s", match_id, e)
                eval_stats["errors"] += 1
                continue

            prob_a = res.prob_a
            prob_b = res.prob_b

            # Temporal timestamp determination
            start_dt = _parse_iso(rec.get("start_time_normalized"))
            cutoff_iso = rec.get("data_cutoff_at")
            cutoff_dt = _parse_iso(cutoff_iso)

            if start_dt is not None:
                predicted_at_dt = start_dt - timedelta(minutes=1)
                # Ensure cutoff <= predicted_at
                if cutoff_dt and cutoff_dt > predicted_at_dt:
                    predicted_at_dt = cutoff_dt
            elif cutoff_dt is not None:
                predicted_at_dt = cutoff_dt
            else:
                predicted_at_dt = datetime.now(UTC)

            predicted_at_iso = predicted_at_dt.isoformat()

            # Record metrics if match outcome is known
            winner_side = rec.get("winner_side")
            if winner_side in ("team_a", "team_b"):
                y_true = 1.0 if winner_side == "team_a" else 0.0
                clipped_p = max(1e-6, min(1.0 - 1e-6, prob_a))
                ll = -(y_true * math.log(clipped_p) + (1.0 - y_true) * math.log(1.0 - clipped_p))
                brier = (prob_a - y_true) ** 2
                correct = (prob_a >= 0.5 and y_true == 1.0) or (prob_a < 0.5 and y_true == 0.0)

                eval_stats["finished_evaluated"] += 1
                eval_stats["log_loss_sum"] += ll
                eval_stats["brier_sum"] += brier
                if correct:
                    eval_stats["correct_picks"] += 1

            diagnostics = {
                "source": "EXP-081 Siamese series backfill",
                "map_prob_a": res.map_prob_a,
                "best_of": res.best_of,
                "epistemic_sigma_z": res.epistemic_sigma_z,
                "prob_risk_adjusted_p_low_a": res.p_low_a,
                "prob_risk_adjusted_p_low_b": res.p_low_b,
                "winner_side": winner_side,
                **res.diagnostics,
            }

            if apply and (overwrite or not already_pure):
                session.execute(
                    text(
                        """
                        INSERT INTO canonical_predictions (
                            canonical_match_id, model_artifact_id, model_name,
                            model_version, predicted_at, prob_a, prob_b,
                            features_version, ratings_version, data_cutoff_at,
                            prediction_status, diagnostics_json
                        ) VALUES (
                            :match_id, :artifact_id, :name, :version,
                            :predicted_at, :prob_a, :prob_b, :f_ver, :r_ver,
                            :cutoff, 'active', :diagnostics
                        )
                        """
                    ),
                    {
                        "match_id": match_id,
                        "artifact_id": pure_artifact_id,
                        "name": active_model.name,
                        "version": active_model.version,
                        "predicted_at": predicted_at_dt,
                        "prob_a": prob_a,
                        "prob_b": prob_b,
                        "f_ver": active_model.feature_version,
                        "r_ver": active_model.ratings_version,
                        "cutoff": cutoff_iso,
                        "diagnostics": json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
                    },
                )
                eval_stats["pure_predictions"] += 1
            elif not apply and not already_pure:
                eval_stats["pure_predictions"] += 1

            # Hybrid generation if market odds are available
            market_prob_a = load_market_prob_for_match(session, match_id)
            if market_prob_a is not None:
                try:
                    hybrid_prob_a = PredictionEngine.blend_with_market(
                        prob_a,
                        market_prob_a,
                        hybrid_spec=active_hybrid,
                    )
                    hybrid_prob_b = 1.0 - hybrid_prob_a

                    hybrid_diag = {
                        "source": "EXP-081 Siamese operational hybrid backfill",
                        "base_model": active_model.name,
                        "base_model_version": active_model.version,
                        "market_prob_a": market_prob_a,
                        "alpha": active_hybrid.alpha,
                        "temperature": active_hybrid.temperature,
                        "blending_mode": active_hybrid.blending_mode,
                    }

                    if apply and (overwrite or not already_hybrid):
                        session.execute(
                            text(
                                """
                                INSERT INTO canonical_predictions (
                                    canonical_match_id, model_artifact_id, model_name,
                                    model_version, predicted_at, prob_a, prob_b,
                                    features_version, ratings_version, data_cutoff_at,
                                    prediction_status, diagnostics_json
                                ) VALUES (
                                    :match_id, :artifact_id, :name, :version,
                                    :predicted_at, :prob_a, :prob_b, :f_ver, :r_ver,
                                    :cutoff, 'active', :diagnostics
                                )
                                """
                            ),
                            {
                                "match_id": match_id,
                                "artifact_id": hybrid_artifact_id,
                                "name": active_hybrid.hybrid_model_name,
                                "version": active_hybrid.hybrid_model_version,
                                "predicted_at": predicted_at_dt,
                                "prob_a": hybrid_prob_a,
                                "prob_b": hybrid_prob_b,
                                "f_ver": active_model.feature_version,
                                "r_ver": active_model.ratings_version,
                                "cutoff": cutoff_iso,
                                "diagnostics": json.dumps(hybrid_diag, ensure_ascii=False, sort_keys=True),
                            },
                        )
                        eval_stats["hybrid_predictions"] += 1
                    elif not apply and not already_hybrid:
                        eval_stats["hybrid_predictions"] += 1
                except Exception as e:
                    logger.debug("Could not blend hybrid for match %d: %s", match_id, e)

        if apply:
            session.commit()
            logger.info("Successfully committed backfill predictions to database.")

    # Calculate retrospective evaluation metrics
    n_finished = eval_stats["finished_evaluated"]
    if n_finished > 0:
        mean_log_loss = eval_stats["log_loss_sum"] / n_finished
        mean_brier = eval_stats["brier_sum"] / n_finished
        accuracy = eval_stats["correct_picks"] / n_finished
        eval_stats["metrics"] = {
            "n_matches": n_finished,
            "log_loss": round(mean_log_loss, 5),
            "brier_score": round(mean_brier, 5),
            "accuracy": round(accuracy, 5),
        }

    return eval_stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist predictions to database (dry-run default).")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing EXP-081 predictions if present.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of candidate matches to process.")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("Starting EXP-081 backfill in %s mode (overwrite=%s)", mode, args.overwrite)
    stats = backfill_predictions(apply=args.apply, overwrite=args.overwrite, limit=args.limit)

    print("\n" + "=" * 60)
    print(f"EXP-081 Backfill Summary ({mode})")
    print("=" * 60)
    print(f"Total matches processed:  {stats['processed']}")
    print(f"Pure predictions ready:   {stats['pure_predictions']}")
    print(f"Hybrid predictions ready: {stats['hybrid_predictions']}")
    print(f"Skipped existing:         {stats['skipped_existing']}")
    print(f"Errors encountered:       {stats['errors']}")
    if "metrics" in stats:
        m = stats["metrics"]
        print("-" * 60)
        print(f"Retrospective Evaluation on Finished Matches (N = {m['n_matches']}):")
        print(f"  Log Loss:    {m['log_loss']:.5f}")
        print(f"  Brier Score: {m['brier_score']:.5f}")
        print(f"  Accuracy:    {m['accuracy'] * 100:.2f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
