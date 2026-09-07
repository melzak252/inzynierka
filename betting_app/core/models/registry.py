"""Central model registry providing the Single Source of Truth for models."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from betting_app.core.models.contract import HybridSpec, ModelSpec

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# -----------------------------------------------------------------------------
# Known Model Specifications
# -----------------------------------------------------------------------------

EXP081_SIAMESE = ModelSpec(
    name="Symmetrized-Siamese-Series-EXP081",
    version="exp081-siamese-series-v1",
    feature_version="ratings-w20-symmetric-series-v1",
    ratings_version="latest-full",
    w20_version="w20-latest",
    prediction_target="series",
    has_uncertainty=True,
    family="siamese_mlp",
    artifact_path=PROJECT_ROOT / "betting_app" / "models" / "exp081_siamese_series_v1.json",
    description="Anti-symmetric Siamese MLP ensemble with Focal Loss (gamma=1.0) and epistemic uncertainty gating.",
    metadata={
        "risk_kappa": 0.75,
        "n_members": 5,
        "symmetric": True,
    },
)

EXP078_LINEAR = ModelSpec(
    name="Operational-PlayerTeamRatings-W20",
    version="exp078-symmetric-series-v1",
    feature_version="ratings-w20-symmetric-series-v1",
    ratings_version="latest-full",
    w20_version="w20-latest",
    prediction_target="series",
    has_uncertainty=False,
    family="linear_symmetric",
    artifact_path=PROJECT_ROOT / "betting_app" / "models" / "exp078_symmetric_series_v1.json",
    description="Symmetric series-level linear regression on ratings-w20-symmetric-series-v1 features.",
    metadata={"symmetric": True},
)

EXP039_THESIS = ModelSpec(
    name="Sym-Cal LR-ElasticNet-W20-Binomial",
    version="exp-039",
    feature_version="thesis-exp039",
    ratings_version="latest-full",
    w20_version="w20-latest",
    prediction_target="map",
    has_uncertainty=False,
    family="elastic_net",
    artifact_path=PROJECT_ROOT / "betting_app" / "models" / "sym_cal_lr_elasticnet_w20_binomial_pipeline.joblib",
    description="Frozen thesis reference model: symmetric calibrated ElasticNet with binomial series simulation.",
    metadata={"frozen": True, "academic_baseline": True},
)

REGISTERED_MODELS: dict[str, ModelSpec] = {
    EXP081_SIAMESE.name: EXP081_SIAMESE,
    EXP078_LINEAR.name: EXP078_LINEAR,
    EXP039_THESIS.name: EXP039_THESIS,
    # Shorthand aliases
    "exp081": EXP081_SIAMESE,
    "exp078": EXP078_LINEAR,
    "exp039": EXP039_THESIS,
}

# -----------------------------------------------------------------------------
# Active Model and Hybrid State
# -----------------------------------------------------------------------------

# Default active operational model: EXP-081
_ACTIVE_MODEL: ModelSpec = EXP081_SIAMESE

# Default active operational hybrid
_ACTIVE_HYBRID: HybridSpec = HybridSpec(
    base_model=_ACTIVE_MODEL,
    hybrid_model_name="Hybrid-Operational-Market",
    alpha=0.50,
    temperature=0.80,
    blending_mode="logit_shrinkage",
)

# Thesis hybrid reference
THESIS_HYBRID: HybridSpec = HybridSpec(
    base_model=EXP039_THESIS,
    hybrid_model_name="Hybrid-Thesis-Market",
    alpha=0.35,
    temperature=0.80,
    blending_mode="linear",
    custom_version="a0.35-t0.80",
)


def get_active_model() -> ModelSpec:
    """Return the currently configured operational model."""
    global _ACTIVE_MODEL
    # Allow overriding via environment variable
    override = os.getenv("ACTIVE_PREDICTION_MODEL")
    if override:
        model_from_env = get_model(override)
        if model_from_env:
            return model_from_env
    return _ACTIVE_MODEL


def set_active_model(model_or_name: ModelSpec | str) -> None:
    """Switch the active operational model."""
    global _ACTIVE_MODEL, _ACTIVE_HYBRID
    if isinstance(model_or_name, str):
        spec = get_model(model_or_name)
        if spec is None:
            raise KeyError(f"Unknown model: {model_or_name}. Registered: {list(REGISTERED_MODELS.keys())}")
        _ACTIVE_MODEL = spec
    else:
        _ACTIVE_MODEL = model_or_name
    # Update base model in hybrid, preserving custom_version if set
    _ACTIVE_HYBRID = HybridSpec(
        base_model=_ACTIVE_MODEL,
        hybrid_model_name=_ACTIVE_HYBRID.hybrid_model_name,
        alpha=_ACTIVE_HYBRID.alpha,
        temperature=_ACTIVE_HYBRID.temperature,
        blending_mode=_ACTIVE_HYBRID.blending_mode,
        custom_version=_ACTIVE_HYBRID.custom_version,
    )


def get_active_hybrid() -> HybridSpec:
    """Return the active operational hybrid specification, synchronized with active model."""
    current_active = get_active_model()
    if _ACTIVE_HYBRID.base_model != current_active:
        return HybridSpec(
            base_model=current_active,
            hybrid_model_name=_ACTIVE_HYBRID.hybrid_model_name,
            alpha=_ACTIVE_HYBRID.alpha,
            temperature=_ACTIVE_HYBRID.temperature,
            blending_mode=_ACTIVE_HYBRID.blending_mode,
            custom_version=_ACTIVE_HYBRID.custom_version,
        )
    return _ACTIVE_HYBRID


def set_active_hybrid(hybrid_spec: HybridSpec) -> None:
    """Switch or update the active hybrid specification."""
    global _ACTIVE_HYBRID
    _ACTIVE_HYBRID = hybrid_spec

def get_thesis_model() -> ModelSpec:
    """Return the frozen thesis baseline model specification."""
    return EXP039_THESIS


def get_thesis_hybrid() -> HybridSpec:
    """Return the frozen thesis hybrid specification."""
    return THESIS_HYBRID


def get_model(name_or_alias: str) -> ModelSpec | None:
    """Retrieve a model by key, alias, name, or version (case/dash insensitive)."""
    if name_or_alias in REGISTERED_MODELS:
        return REGISTERED_MODELS[name_or_alias]
    # Normalize: e.g. "EXP-081", "exp-081", "exp_081" -> "exp081"
    normalized = name_or_alias.lower().replace("-", "").replace("_", "").strip()
    for key, spec in REGISTERED_MODELS.items():
        key_norm = key.lower().replace("-", "").replace("_", "")
        name_norm = spec.name.lower().replace("-", "").replace("_", "")
        ver_norm = spec.version.lower().replace("-", "").replace("_", "")
        if normalized in (key_norm, name_norm, ver_norm):
            return spec
    return None


def list_registered_models() -> list[dict[str, Any]]:
    """List all registered models with their metadata for API responses."""
    active = get_active_model()
    seen = set()
    result = []
    for model in (EXP081_SIAMESE, EXP078_LINEAR, EXP039_THESIS):
        if model.name in seen:
            continue
        seen.add(model.name)
        result.append({
            "name": model.name,
            "version": model.version,
            "feature_version": model.feature_version,
            "ratings_version": model.ratings_version,
            "w20_version": model.w20_version,
            "prediction_target": model.prediction_target,
            "target": model.prediction_target,
            "has_uncertainty": model.has_uncertainty,
            "has_epistemic_uncertainty": model.has_uncertainty,
            "family": model.family,
            "is_active_operational": model.name == active.name and model.version == active.version,
            "description": model.description,
            "metadata": model.metadata,
        })
    return result

def get_active_prediction_db_params() -> dict[str, str]:
    """Return SQL bind params for filtering active operational & hybrid predictions."""
    active = get_active_model()
    hybrid = get_active_hybrid()
    return {
        "sn": active.name,
        "sv": active.version,
        "hn": hybrid.hybrid_model_name,
        "hv": hybrid.hybrid_model_version,
        "operational_name": active.name,
        "operational_version": active.version,
        "hybrid_name": hybrid.hybrid_model_name,
        "hybrid_version": hybrid.hybrid_model_version,
    }
