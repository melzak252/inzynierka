"""Embedding diagnostics API.

Serves lightweight 2D projections of generated ML embedding artifacts for the
React dashboard.  The endpoint is read-only and intentionally recomputes the
projection from the stored CSV artifact so it can be used after every embedding
rebuild without adding a database table.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE


router = APIRouter(prefix="/embeddings", tags=["embeddings"])

DEFAULT_ARTIFACT_DIR = Path("/app/betting_app/models/ml/champion_role_embeddings/exp-056")
LOCAL_ARTIFACT_DIR = Path("betting_app/models/ml/champion_role_embeddings/exp-056")


def _artifact_dir() -> Path:
    if DEFAULT_ARTIFACT_DIR.exists():
        return DEFAULT_ARTIFACT_DIR
    return LOCAL_ARTIFACT_DIR


def _artifact_paths() -> tuple[Path, Path]:
    artifact_dir = _artifact_dir()
    return artifact_dir / "champion_role_embeddings.csv", artifact_dir / "metadata.json"


def _json_safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return numeric


def _mtime_key() -> tuple[str, float, str, float]:
    csv_path, metadata_path = _artifact_paths()
    if not csv_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Champion embedding artifact not found. Run "
                "betting_app.scripts.build_champion_role_embeddings first."
            ),
        )
    metadata_mtime = metadata_path.stat().st_mtime if metadata_path.exists() else 0.0
    return str(csv_path), csv_path.stat().st_mtime, str(metadata_path), metadata_mtime


@lru_cache(maxsize=32)
def _project_champion_embeddings(
    csv_path_str: str,
    csv_mtime: float,
    metadata_path_str: str,
    metadata_mtime: float,
    method: str,
    role: str,
    min_games: int,
    max_points: int,
) -> dict:
    del csv_mtime, metadata_mtime  # cache-busting keys; values are not used directly

    csv_path = Path(csv_path_str)
    metadata_path = Path(metadata_path_str)
    df = pd.read_csv(csv_path)
    metadata = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metadata = {}

    vector_cols = [c for c in df.columns if c.startswith("emb_")]
    if len(vector_cols) < 2:
        raise HTTPException(status_code=422, detail="Embedding artifact does not contain emb_* vector columns.")

    available_roles = sorted(str(r) for r in df["role"].dropna().unique()) if "role" in df.columns else []
    filtered = df.copy()
    if role != "ALL":
        filtered = filtered[filtered["role"].astype(str) == role]
    if "n_games" in filtered.columns:
        filtered = filtered[pd.to_numeric(filtered["n_games"], errors="coerce").fillna(0) >= min_games]

    if filtered.empty:
        raise HTTPException(status_code=404, detail="No champion-role embeddings match the selected filters.")

    filtered = filtered.sort_values(["role", "champion_name", "champion_id"], na_position="last").head(max_points)
    matrix = filtered[vector_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy(dtype=float)

    actual_method = method
    if method == "tsne" and len(filtered) < 4:
        actual_method = "pca"

    if actual_method == "pca":
        projection = PCA(n_components=2, random_state=42).fit_transform(matrix)
    elif actual_method == "tsne":
        perplexity = max(2, min(30, (len(filtered) - 1) // 3))
        projection = TSNE(
            n_components=2,
            init="pca",
            learning_rate="auto",
            perplexity=perplexity,
            random_state=42,
            max_iter=1200,
        ).fit_transform(matrix)
    else:
        raise HTTPException(status_code=400, detail="Unsupported projection method.")

    x = projection[:, 0]
    y = projection[:, 1]
    span_x = float(np.ptp(x)) or 1.0
    span_y = float(np.ptp(y)) or 1.0
    points = []
    for idx, row in enumerate(filtered.to_dict(orient="records")):
        points.append(
            {
                "champion_id": str(row.get("champion_id", "")),
                "champion_name": row.get("champion_name") or str(row.get("champion_id", "UNKNOWN")),
                "role": row.get("role"),
                "x": float(x[idx]),
                "y": float(y[idx]),
                "x_norm": float((x[idx] - x.min()) / span_x),
                "y_norm": float((y[idx] - y.min()) / span_y),
                "n_games": _json_safe_float(row.get("n_games")),
                "win_rate": _json_safe_float(row.get("win_rate")),
                "fallback_level": row.get("fallback_level"),
                "window_days": _json_safe_float(row.get("window_days")),
                "shrinkage_weight_observed": _json_safe_float(row.get("shrinkage_weight_observed")),
                "age_days_mean": _json_safe_float(row.get("age_days_mean")),
                "kda": _json_safe_float(row.get("mean_kda")),
                "damage_share": _json_safe_float(row.get("mean_damage_share")),
                "gold_share": _json_safe_float(row.get("mean_gold_share")),
                "kill_participation": _json_safe_float(row.get("mean_kill_participation")),
            }
        )

    return {
        "metadata": {
            "artifact_path": str(csv_path),
            "method": actual_method,
            "requested_method": method,
            "role": role,
            "min_games": min_games,
            "total_points": int(len(points)),
            "available_roles": available_roles,
            "source_rows": metadata.get("source_rows"),
            "reference_date": metadata.get("reference_date"),
            "embedding_dim": metadata.get("embedding_dim", len(vector_cols)),
            "model_name": metadata.get("model_name", "ChampionRoleEmbeddings"),
            "model_version": metadata.get("model_version", "exp-056"),
            "fallback_counts": metadata.get("fallback_counts", {}),
        },
        "points": points,
    }


@router.get("/champions")
def champion_embedding_projection(
    method: Literal["tsne", "pca"] = Query("tsne", description="2D projection method."),
    role: str = Query("ALL", description="Role filter: ALL, TOP, JUNGLE, MID, ADC, SUPPORT."),
    min_games: int = Query(0, ge=0, le=1000),
    max_points: int = Query(800, ge=10, le=2000),
):
    """Return a 2D projection of champion-role embeddings.

    UMAP is intentionally not required in production dependencies; t-SNE is the
    primary nonlinear view and PCA is available as a deterministic fast fallback.
    """
    key = _mtime_key()
    role_norm = role.upper()
    return _project_champion_embeddings(*key, method, role_norm, int(min_games), int(max_points))
