"""Inference service for the thesis model: Sym-Cal LR-ElasticNet-W20-Binomial.

Loads the serialized pipeline and Platt calibrator, builds features for
upcoming matches using the same 46-feature schema as training, applies
order symmetry and Platt calibration, and stores predictions in
canonical_predictions.

Usage:
    from betting_app.services.thesis_inference_service import predict_upcoming_with_thesis_model
    results = predict_upcoming_with_thesis_model()
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from math import comb
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from betting_app.core.db import query_df, transaction
from betting_app.core.matching import normalize_team_name
from betting_app.services.upcoming_inference_service import (
    RATING_SYSTEMS,
    load_team_ratings,
    load_w20,
    rating_probabilities,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
THESIS_MODEL_NAME = "Sym-Cal LR-ElasticNet-W20-Binomial"
THESIS_MODEL_VERSION = "exp-039"
EPSILON = 0.001

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTEFACT_DIR = PROJECT_ROOT / "docs" / "assets" / "final_symmetric_calibrated_market_comparison"
PIPELINE_PATH = ARTEFACT_DIR / "sym_cal_lr_elasticnet_w20_binomial_pipeline.joblib"
CALIBRATOR_PATH = ARTEFACT_DIR / "sym_cal_lr_elasticnet_w20_binomial_calibrator.joblib"
METADATA_PATH = ARTEFACT_DIR / "sym_cal_lr_elasticnet_w20_binomial_metadata.json"

# Feature definitions (must match training exactly)
OPTUNA_BASE_FEATURES = [
    "player_elo",
    "player_gl",
    "player_ts",
    "player_os",
    "player_pl",
    "player_tm",
    "player_elo_min1",
    "player_elo_min2",
    "player_gl_max1",
    "player_gl_max2",
    "player_gl_rd_avg1",
    "player_gl_rd_avg2",
    "player_ts_sigma_avg1",
    "player_ts_sigma_avg2",
    "player_os_sigma_avg1",
    "player_os_sigma_avg2",
    "player_pl_sigma_avg1",
    "player_pl_sigma_avg2",
    "player_tm_sigma_avg1",
    "player_tm_sigma_avg2",
]

ROLLING_FULL_FEATURES = [
    "t1_rolling_win_rate",
    "t2_rolling_win_rate",
    "t1_rolling_kills",
    "t2_rolling_kills",
    "t1_rolling_deaths",
    "t2_rolling_deaths",
    "t1_rolling_gd15",
    "t2_rolling_gd15",
    "t1_rolling_dpm",
    "t2_rolling_dpm",
    "t1_rolling_vspm",
    "t2_rolling_vspm",
    "t1_rolling_towers",
    "t2_rolling_towers",
    "t1_rolling_nashors",
    "t2_rolling_nashors",
    "t1_rolling_gold",
    "t2_rolling_gold",
    "t1_rolling_duration",
    "t2_rolling_duration",
]

RANK_PROB_FEATURES = [
    "player_elo",
    "player_gl",
    "player_ts",
    "player_os",
    "player_pl",
    "player_tm",
]

BINOMIAL_FEATURES = [f"{f}_binom_series" for f in RANK_PROB_FEATURES]

ALL_FEATURES = OPTUNA_BASE_FEATURES + ROLLING_FULL_FEATURES + BINOMIAL_FEATURES

# Default values for missing rolling features
_DEFAULT_ROLLING = {
    "win_rate": 0.5,
    "kills": 12.0,
    "deaths": 12.0,
    "gd15": 0.0,
    "dpm": 1800.0,
    "vspm": 7.0,
    "towers": 5.0,
    "nashors": 0.5,
    "gold": 55000.0,
    "duration": 1800.0,
}


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------
_pipeline = None
_calibrator = None


def _load_model():
    """Lazy-load the pipeline and calibrator."""
    global _pipeline, _calibrator
    if _pipeline is None:
        if not PIPELINE_PATH.exists():
            raise FileNotFoundError(f"Pipeline not found: {PIPELINE_PATH}")
        _pipeline = joblib.load(PIPELINE_PATH)
    if _calibrator is None:
        if not CALIBRATOR_PATH.exists():
            raise FileNotFoundError(f"Calibrator not found: {CALIBRATOR_PATH}")
        _calibrator = joblib.load(CALIBRATOR_PATH)
    return _pipeline, _calibrator


# ---------------------------------------------------------------------------
# Feature building
# ---------------------------------------------------------------------------
def _rating_prob(rating_a: float | None, rating_b: float | None, system: str) -> float:
    """Compute probability from rating difference."""
    if rating_a is None or rating_b is None:
        return 0.5
    diff = float(rating_a) - float(rating_b)
    if system in {"elo", "gl"}:
        return 1.0 / (1.0 + 10 ** (-diff / 400.0))
    elif system == "os":
        return _sigmoid(diff / 5.0)
    else:
        return _sigmoid(diff / 8.333)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, x))))


def _logit(p: np.ndarray) -> np.ndarray:
    """Clipped logit for Platt calibration input."""
    clipped = np.clip(p, EPSILON, 1.0 - EPSILON)
    return np.log(clipped / (1.0 - clipped)).reshape(-1, 1)


def _series_probability(map_prob: np.ndarray, best_of: int) -> np.ndarray:
    """Convert map-win probability to series probability."""
    prob = np.clip(map_prob.astype(float), EPSILON, 1.0 - EPSILON)
    if best_of == 1:
        return prob
    needed = best_of // 2 + 1
    series_prob = np.zeros_like(prob)
    for wins in range(needed, best_of + 1):
        series_prob += comb(best_of, wins) * np.power(prob, wins) * np.power(1.0 - prob, best_of - wins)
    return np.clip(series_prob, EPSILON, 1.0 - EPSILON)


def build_thesis_features_for_match(
    team_a_name: str,
    team_b_name: str,
    *,
    ratings_version: str = "latest-full",
    w20_version: str = "w20-latest",
    best_of: int = 1,
) -> tuple[np.ndarray | None, dict[str, Any]]:
    """Build the 46-feature vector for one upcoming match.

    Returns (feature_vector, diagnostics) where feature_vector is None if
    required data is missing.
    """
    diagnostics: dict[str, Any] = {
        "team_a": team_a_name,
        "team_b": team_b_name,
        "ratings_version": ratings_version,
        "w20_version": w20_version,
        "best_of": best_of,
        "missing": [],
    }

    # Load team ratings
    ratings_a = load_team_ratings(team_a_name, ratings_version)
    ratings_b = load_team_ratings(team_b_name, ratings_version)

    # Check for missing ratings
    for system in RATING_SYSTEMS:
        if system not in ratings_a:
            diagnostics["missing"].append(f"team_a_rating:{system}")
        if system not in ratings_b:
            diagnostics["missing"].append(f"team_b_rating:{system}")

    # Load W20 rolling features
    w20_a = load_w20(team_a_name, w20_version)
    w20_b = load_w20(team_b_name, w20_version)
    if not w20_a:
        diagnostics["missing"].append("team_a_w20")
    if not w20_b:
        diagnostics["missing"].append("team_b_w20")

    # Build feature dict
    features: dict[str, float] = {}

    # 1. Rating probabilities (6 features)
    for system in RATING_SYSTEMS:
        r_a = ratings_a.get(system, {}).get("rating_value")
        r_b = ratings_b.get(system, {}).get("rating_value")
        features[f"player_{system}"] = _rating_prob(r_a, r_b, system)

    # 2. Uncertainty features (14 features)
    # These are derived from rating RD and sigma values
    for system in RATING_SYSTEMS:
        rd_a = ratings_a.get(system, {}).get("rd")
        rd_b = ratings_b.get(system, {}).get("rd")
        sigma_a = ratings_a.get(system, {}).get("sigma")
        sigma_b = ratings_b.get(system, {}).get("sigma")

        # Min/max of RD
        if rd_a is not None and rd_b is not None:
            features[f"player_{system}_min1"] = min(float(rd_a), float(rd_b))
            features[f"player_{system}_min2"] = max(float(rd_a), float(rd_b))
        else:
            features[f"player_{system}_min1"] = 50.0  # default RD
            features[f"player_{system}_min2"] = 50.0

        # Avg sigma
        if sigma_a is not None and sigma_b is not None:
            features[f"player_{system}_sigma_avg1"] = float(sigma_a)
            features[f"player_{system}_sigma_avg2"] = float(sigma_b)
        else:
            features[f"player_{system}_sigma_avg1"] = 0.06
            features[f"player_{system}_sigma_avg2"] = 0.06

    # Fix: use actual feature names from training
    # The training uses specific naming like player_elo_min1, player_gl_rd_avg1, etc.
    # Rebuild with correct names:
    features = {}

    # Rating probs
    for system in RATING_SYSTEMS:
        r_a = ratings_a.get(system, {}).get("rating_value")
        r_b = ratings_b.get(system, {}).get("rating_value")
        features[f"player_{system}"] = _rating_prob(r_a, r_b, system)

    # Uncertainty: min1/min2 are min of the two teams' RD for elo
    elo_rd_a = ratings_a.get("elo", {}).get("rd")
    elo_rd_b = ratings_b.get("elo", {}).get("rd")
    if elo_rd_a is not None and elo_rd_b is not None:
        features["player_elo_min1"] = min(float(elo_rd_a), float(elo_rd_b))
        features["player_elo_min2"] = max(float(elo_rd_a), float(elo_rd_b))
    else:
        features["player_elo_min1"] = 50.0
        features["player_elo_min2"] = 50.0

    # gl: max1/max2 are max of RD
    gl_rd_a = ratings_a.get("gl", {}).get("rd")
    gl_rd_b = ratings_b.get("gl", {}).get("rd")
    if gl_rd_a is not None and gl_rd_b is not None:
        features["player_gl_max1"] = max(float(gl_rd_a), float(gl_rd_b))
        features["player_gl_max2"] = min(float(gl_rd_a), float(gl_rd_b))
    else:
        features["player_gl_max1"] = 0.1
        features["player_gl_max2"] = 0.1

    # gl_rd_avg: average RD for each team
    features["player_gl_rd_avg1"] = float(gl_rd_a) if gl_rd_a is not None else 0.1
    features["player_gl_rd_avg2"] = float(gl_rd_b) if gl_rd_b is not None else 0.1

    # sigma_avg for ts, os, pl, tm
    for system in ["ts", "os", "pl", "tm"]:
        sigma_a = ratings_a.get(system, {}).get("sigma")
        sigma_b = ratings_b.get(system, {}).get("sigma")
        features[f"player_{system}_sigma_avg1"] = float(sigma_a) if sigma_a is not None else 0.06
        features[f"player_{system}_sigma_avg2"] = float(sigma_b) if sigma_b is not None else 0.06

    # 3. Rolling features (20 features)
    for stat, default in _DEFAULT_ROLLING.items():
        val_a = w20_a.get(f"avg_{stat}") if w20_a and f"avg_{stat}" in w20_a else default
        val_b = w20_b.get(f"avg_{stat}") if w20_b and f"avg_{stat}" in w20_b else default
        # Handle special case: win_rate doesn't have avg_ prefix
        if stat == "win_rate":
            val_a = w20_a.get("win_rate", default) if w20_a else default
            val_b = w20_b.get("win_rate", default) if w20_b else default
        features[f"t1_rolling_{stat}"] = float(val_a) if val_a is not None else default
        features[f"t2_rolling_{stat}"] = float(val_b) if val_b is not None else default

    # 4. Binomial features (6 features)
    rating_probs_array = np.array([features[f"player_{s}"] for s in RATING_SYSTEMS])
    series_probs = _series_probability(rating_probs_array, best_of)
    for i, system in enumerate(RATING_SYSTEMS):
        features[f"player_{system}_binom_series"] = float(series_probs[i])

    # Build feature vector in correct order
    feature_vector = np.array([[features.get(f, 0.0) for f in ALL_FEATURES]])

    diagnostics["features_built"] = len(ALL_FEATURES)
    diagnostics["missing_count"] = len(diagnostics["missing"])

    return feature_vector, diagnostics


def _swap_feature_vector(vec: np.ndarray) -> np.ndarray:
    """Swap team orientation in feature vector.

    For rating probs: p -> 1-p
    For rolling features: swap t1 <-> t2
    For binomial: p -> 1-p
    """
    swapped = vec.copy()

    # Rating probs (indices 0-5): p -> 1-p
    for i in range(6):
        swapped[0, i] = 1.0 - vec[0, i]

    # Uncertainty features (indices 6-19): swap team-specific values
    # player_elo_min1/min2: swap min/max
    swapped[0, 6] = vec[0, 7]  # min1 <-> min2
    swapped[0, 7] = vec[0, 6]
    # player_gl_max1/max2: swap
    swapped[0, 8] = vec[0, 9]
    swapped[0, 9] = vec[0, 8]
    # player_gl_rd_avg1/avg2: swap
    swapped[0, 10] = vec[0, 11]
    swapped[0, 11] = vec[0, 10]
    # sigma_avg1/avg2 for ts, os, pl, tm: swap
    for offset in range(4):
        base = 12 + offset * 2
        swapped[0, base] = vec[0, base + 1]
        swapped[0, base + 1] = vec[0, base]

    # Rolling features (indices 20-39): swap t1 <-> t2
    for i in range(10):
        t1_idx = 20 + i * 2
        t2_idx = 20 + i * 2 + 1
        swapped[0, t1_idx] = vec[0, t2_idx]
        swapped[0, t2_idx] = vec[0, t1_idx]

    # Binomial features (indices 40-45): p -> 1-p
    for i in range(6):
        swapped[0, 40 + i] = 1.0 - vec[0, 40 + i]

    return swapped


def _symmetrize(original: float, swapped: float) -> float:
    """Apply order symmetry: average original and (1-swapped)."""
    return 0.5 * (original + (1.0 - swapped))


# ---------------------------------------------------------------------------
# Main prediction function
# ---------------------------------------------------------------------------
def predict_upcoming_with_thesis_model(
    *,
    ratings_version: str = "latest-full",
    w20_version: str = "w20-latest",
    include_past: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Generate predictions for upcoming matches using the thesis model.

    Returns list of prediction results with diagnostics.
    """
    pipeline, calibrator = _load_model()

    # Load upcoming matches
    where = "WHERE cm.status = 'upcoming'"
    params: list[Any] = []
    if not include_past:
        where += " AND (cm.start_time_normalized IS NULL OR cm.start_time_normalized >= ?)"
        params.append(datetime.now(UTC).replace(microsecond=0).isoformat())

    sql = f"""
        SELECT cm.id, cm.team_a_name, cm.team_b_name, cm.start_time_normalized, cm.league
        FROM canonical_matches cm
        JOIN odds_snapshots os ON os.canonical_match_id = cm.id
        {where}
        GROUP BY cm.id
        ORDER BY cm.start_time_normalized ASC
    """
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))

    with transaction() as conn:
        matches = conn.execute(sql, tuple(params)).fetchall()

    if not matches:
        return []

    # Register model artifact
    model_artifact_id = _register_thesis_model()

    results: list[dict[str, Any]] = []

    with transaction() as conn:
        # Mark old predictions as stale
        conn.execute(
            """
            UPDATE canonical_predictions
            SET prediction_status = 'stale'
            WHERE prediction_status = 'active' AND model_name = ? AND model_version = ?
            """,
            (THESIS_MODEL_NAME, THESIS_MODEL_VERSION),
        )

        for match in matches:
            match_id = int(match["id"])
            team_a = str(match["team_a_name"])
            team_b = str(match["team_b_name"])

            # Build features
            feature_vec, diagnostics = build_thesis_features_for_match(
                team_a, team_b,
                ratings_version=ratings_version,
                w20_version=w20_version,
            )

            if feature_vec is None:
                diagnostics["error"] = "Could not build features"
                continue

            # Original prediction
            original_prob = float(np.clip(pipeline.predict_proba(feature_vec)[0, 1], EPSILON, 1.0 - EPSILON))

            # Swapped prediction
            swapped_vec = _swap_feature_vector(feature_vec)
            swapped_prob = float(np.clip(pipeline.predict_proba(swapped_vec)[0, 1], EPSILON, 1.0 - EPSILON))

            # Order symmetry
            sym_prob = _symmetrize(original_prob, swapped_prob)

            # Platt calibration
            calibrated_prob = float(np.clip(
                calibrator.predict_proba(_logit(np.array([sym_prob])))[0, 1],
                EPSILON, 1.0 - EPSILON,
            ))

            diagnostics["original_prob"] = original_prob
            diagnostics["swapped_prob"] = swapped_prob
            diagnostics["symmetric_prob"] = sym_prob
            diagnostics["calibrated_prob"] = calibrated_prob

            # Store prediction
            predicted_at = datetime.now(UTC).replace(microsecond=0).isoformat()
            conn.execute(
                """
                INSERT INTO canonical_predictions(
                    canonical_match_id, model_artifact_id, model_name, model_version, predicted_at,
                    prob_a, prob_b, features_version, ratings_version, data_cutoff_at, diagnostics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    model_artifact_id,
                    THESIS_MODEL_NAME,
                    THESIS_MODEL_VERSION,
                    predicted_at,
                    calibrated_prob,
                    1.0 - calibrated_prob,
                    "thesis-exp039",
                    ratings_version,
                    None,
                    json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
                ),
            )

            # Fetch the inserted prediction_id
            row = conn.execute(
                """
                SELECT id FROM canonical_predictions
                WHERE canonical_match_id = ? AND model_name = ? AND model_version = ?
                ORDER BY predicted_at DESC LIMIT 1
                """,
                (match_id, THESIS_MODEL_NAME, THESIS_MODEL_VERSION),
            ).fetchone()

            results.append({
                "prediction_id": row["id"] if row else None,
                "canonical_match_id": match_id,
                "match": f"{team_a} vs {team_b}",
                "prob_a": calibrated_prob,
                "prob_b": 1.0 - calibrated_prob,
                "diagnostics": diagnostics,
            })

    return results


def _register_thesis_model() -> int:
    """Register the thesis model in model_artifacts."""
    feature_schema = {
        "features": ALL_FEATURES,
        "n_features": len(ALL_FEATURES),
        "source": "thesis EXP-039 Sym-Cal LR-ElasticNet-W20-Binomial",
        "training_matches": 13289,
        "training_logloss": 0.5850,
        "training_auc": 0.7555,
    }
    params = {
        "C": 0.03297234640536737,
        "penalty": "elasticnet",
        "l1_ratio": 0.9439657999531195,
        "solver": "saga",
        "max_iter": 5000,
        "platt_C": 1.0,
        "order_symmetry": True,
    }

    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO model_artifacts(
                model_name, model_version, feature_schema_json, model_params_json, status
            ) VALUES (?, ?, ?, ?, 'active')
            ON CONFLICT(model_name, model_version) DO UPDATE SET
                feature_schema_json = excluded.feature_schema_json,
                model_params_json = excluded.model_params_json,
                status = 'active'
            """,
            (
                THESIS_MODEL_NAME,
                THESIS_MODEL_VERSION,
                json.dumps(feature_schema, ensure_ascii=False, sort_keys=True),
                json.dumps(params, ensure_ascii=False, sort_keys=True),
            ),
        )
        row = conn.execute(
            "SELECT id FROM model_artifacts WHERE model_name = ? AND model_version = ?",
            (THESIS_MODEL_NAME, THESIS_MODEL_VERSION),
        ).fetchone()
        return int(row["id"])
