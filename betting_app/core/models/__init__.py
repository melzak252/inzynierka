"""Unified Model Registry and Prediction Engine package."""

from betting_app.core.models.contract import HybridSpec, ModelSpec, UnifiedPredictionResult
from betting_app.core.models.engine import PredictionEngine
from betting_app.core.models.registry import (
    EXP039_THESIS,
    EXP078_LINEAR,
    EXP081_SIAMESE,
    REGISTERED_MODELS,
    THESIS_HYBRID,
    get_active_hybrid,
    get_active_model,
    get_active_prediction_db_params,
    get_model,
    get_thesis_hybrid,
    get_thesis_model,
    list_registered_models,
    set_active_hybrid,
    set_active_model,
)

__all__ = [
    "EXP039_THESIS",
    "EXP078_LINEAR",
    "EXP081_SIAMESE",
    "HybridSpec",
    "ModelSpec",
    "PredictionEngine",
    "REGISTERED_MODELS",
    "THESIS_HYBRID",
    "UnifiedPredictionResult",
    "get_active_hybrid",
    "get_active_model",
    "get_active_prediction_db_params",
    "get_model",
    "get_thesis_hybrid",
    "get_thesis_model",
    "list_registered_models",
    "set_active_hybrid",
    "set_active_model",
]
