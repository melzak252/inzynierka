"""Prediction Engine providing a unified inference interface across all models."""

from __future__ import annotations

import json
import math
from typing import Any, Mapping

from betting_app.core.models.contract import HybridSpec, ModelSpec, UnifiedPredictionResult
from betting_app.core.models.registry import get_active_hybrid, get_active_model


def _series_probability_binomial(map_prob: float, best_of: int) -> float:
    """Convert a per-map probability to a BoN series probability using binomial expansion."""
    if best_of <= 1:
        return map_prob
    wins_required = (best_of // 2) + 1
    total = sum(
        math.comb(best_of, wins)
        * (map_prob**wins)
        * ((1.0 - map_prob) ** (best_of - wins))
        for wins in range(wins_required, best_of + 1)
    )
    return max(0.0, min(1.0, float(total)))


def bayesian_logit_shrinkage(
    prob_model: float,
    prob_market: float,
    model_weight: float = 0.50,
    eps: float = 1e-6,
) -> float:
    """Blend model and market probabilities using Bayesian logit shrinkage."""
    if not (math.isfinite(prob_model) and math.isfinite(prob_market)):
        raise ValueError(f"Probabilities must be finite, got model={prob_model}, market={prob_market}")
    if not (0.0 <= prob_model <= 1.0 and 0.0 <= prob_market <= 1.0):
        raise ValueError(f"Probabilities must be in [0, 1], got model={prob_model}, market={prob_market}")
    p_m = max(eps, min(1.0 - eps, prob_model))
    p_k = max(eps, min(1.0 - eps, prob_market))
    logit_m = math.log(p_m / (1.0 - p_m))
    logit_k = math.log(p_k / (1.0 - p_k))
    logit_blend = model_weight * logit_m + (1.0 - model_weight) * logit_k
    p_hybrid = 1.0 / (1.0 + math.exp(-logit_blend))
    return max(eps, min(1.0 - eps, p_hybrid))


def apply_temperature_scaling(prob: float, temperature: float = 0.80, eps: float = 1e-6) -> float:
    """Calibrate overconfidence via temperature scaling on logits."""
    if not math.isfinite(prob):
        raise ValueError(f"Probability must be finite, got {prob}")
    if not (0.0 <= prob <= 1.0):
        raise ValueError(f"Probability must be in [0, 1], got {prob}")
    p = max(eps, min(1.0 - eps, prob))
    logit = math.log(p / (1.0 - p))
    scaled_logit = logit / max(1e-4, temperature)
    return 1.0 / (1.0 + math.exp(-scaled_logit))


class PredictionEngine:
    """Unified engine to run inference across registered model families."""

    @staticmethod
    def predict_from_features(
        features: dict[str, Any],
        model_spec: ModelSpec | None = None,
    ) -> UnifiedPredictionResult:
        """Evaluate a model on an extracted feature payload and return a UnifiedPredictionResult."""
        spec = model_spec or get_active_model()
        canonical_match_id = features.get("canonical", {}).get("id")

        if spec.family == "siamese_mlp":
            from src.models.siamese_series import SiameseSeriesModel
            from betting_app.services.upcoming_inference_service import _exp078_snapshot_from_features

            try:
                snapshot, best_of = _exp078_snapshot_from_features(features)
                model = SiameseSeriesModel.load_default()
                p_mean, sigma_z, p_low = model.predict_with_uncertainty(snapshot, best_of=best_of)
                if best_of > 1:
                    map_p_mean, _, _ = model.predict_with_uncertainty(snapshot, best_of=1)
                else:
                    map_p_mean = p_mean
                # Conservative lower bound for Side B: p_low_b = sigmoid(-z_mean - k * sigma_z)
                k = getattr(model, "risk_kappa", 0.75)
                z_mean = math.log(max(1e-6, min(1.0 - 1e-6, p_mean)) / max(1e-6, min(1.0 - 1e-6, 1.0 - p_mean)))
                p_low_b = 1.0 / (1.0 + math.exp(z_mean + k * sigma_z))
            except Exception:
                # Consensus fallback for partial/mock feature sets
                p_player = features.get("player_ratings", {}).get("probabilities", {}).get("consensus")
                p_team = features.get("ratings", {}).get("probabilities", {}).get("consensus")
                p_w20 = features.get("w20", {}).get("probability")
                weights = []
                if p_player is not None:
                    weights.append((0.70, float(p_player)))
                if p_team is not None:
                    weights.append((0.20, float(p_team)))
                if p_w20 is not None:
                    weights.append((0.10, float(p_w20)))
                if weights:
                    tot = sum(w for w, _ in weights)
                    raw = sum((w / tot) * v for w, v in weights)
                    map_p_mean = max(0.01, min(0.99, raw))
                else:
                    map_p_mean = 0.50
                best_of = int(features.get("canonical", {}).get("best_of") or 1)
                p_mean = _series_probability_binomial(map_p_mean, best_of)
                sigma_z = None
                p_low = None
                p_low_b = None

            return UnifiedPredictionResult(
                canonical_match_id=canonical_match_id,
                prob_a=p_mean,
                prob_b=1.0 - p_mean,
                map_prob_a=map_p_mean,
                map_prob_b=1.0 - map_p_mean,
                p_low_a=p_low,
                p_low_b=p_low_b,
                epistemic_sigma_z=sigma_z,
                model_name=spec.name,
                model_version=spec.version,
                feature_version=spec.feature_version,
                best_of=best_of,
                diagnostics={
                    "family": spec.family,
                    "side_symmetric": True,
                    "market_features_used": False,
                    "epistemic_sigma_z": sigma_z,
                    "prob_risk_adjusted_p_low": p_low,
                },
            )

        elif spec.family == "linear_symmetric":
            from src.models.symmetric_series import SymmetricSeriesModel
            from betting_app.services.upcoming_inference_service import _exp078_snapshot_from_features

            try:
                snapshot, best_of = _exp078_snapshot_from_features(features)
                model = SymmetricSeriesModel.load_default()
                prob_a = model.predict(snapshot, best_of=best_of)
                map_prob_a = model.predict(snapshot, best_of=1) if best_of > 1 else prob_a
            except Exception:
                p_player = features.get("player_ratings", {}).get("probabilities", {}).get("consensus")
                p_team = features.get("ratings", {}).get("probabilities", {}).get("consensus")
                p_w20 = features.get("w20", {}).get("probability")
                weights = []
                if p_player is not None:
                    weights.append((0.70, float(p_player)))
                if p_team is not None:
                    weights.append((0.20, float(p_team)))
                if p_w20 is not None:
                    weights.append((0.10, float(p_w20)))
                if weights:
                    tot = sum(w for w, _ in weights)
                    raw = sum((w / tot) * v for w, v in weights)
                    map_prob_a = max(0.01, min(0.99, raw))
                else:
                    map_prob_a = 0.50
                best_of = int(features.get("canonical", {}).get("best_of") or 1)
                prob_a = _series_probability_binomial(map_prob_a, best_of)

            return UnifiedPredictionResult(
                canonical_match_id=canonical_match_id,
                prob_a=prob_a,
                prob_b=1.0 - prob_a,
                map_prob_a=map_prob_a,
                map_prob_b=1.0 - map_prob_a,
                p_low_a=None,
                p_low_b=None,
                epistemic_sigma_z=None,
                model_name=spec.name,
                model_version=spec.version,
                feature_version=spec.feature_version,
                best_of=best_of,
                diagnostics={
                    "family": spec.family,
                    "side_symmetric": True,
                    "market_features_used": False,
                },
            )

        elif spec.family == "elastic_net":
            # EXP-039 thesis baseline
            from betting_app.services.thesis_inference_service import (
                _load_model as load_thesis_model,
                _extract_raw_thesis_features,
            )
            pipeline, calibrator = load_thesis_model()
            best_of_raw = features.get("canonical", {}).get("best_of", 1)
            best_of = int(best_of_raw) if best_of_raw else 1

            # Prepare raw features
            feat_vector = _extract_raw_thesis_features(features)
            raw_prob = float(pipeline.predict_proba([feat_vector])[0, 1])
            calibrated_map_prob = float(calibrator.predict_proba([[raw_prob]])[0, 1])
            series_prob_a = _series_probability_binomial(calibrated_map_prob, best_of)

            return UnifiedPredictionResult(
                canonical_match_id=canonical_match_id,
                prob_a=series_prob_a,
                prob_b=1.0 - series_prob_a,
                map_prob_a=calibrated_map_prob,
                map_prob_b=1.0 - calibrated_map_prob,
                p_low_a=None,
                p_low_b=None,
                epistemic_sigma_z=None,
                model_name=spec.name,
                model_version=spec.version,
                feature_version=spec.feature_version,
                best_of=best_of,
                diagnostics={
                    "family": spec.family,
                    "map_prob_a": calibrated_map_prob,
                    "academic_baseline": True,
                },
            )

        else:
            raise NotImplementedError(f"Unsupported model family: {spec.family}")

    @staticmethod
    def blend_with_market(
        model_prob_a: float,
        market_prob_a: float,
        hybrid_spec: HybridSpec | None = None,
    ) -> float:
        """Blend model probability with consensus fair market probability according to hybrid spec."""
        spec = hybrid_spec or get_active_hybrid()
        scaled_model_prob = apply_temperature_scaling(model_prob_a, spec.temperature)

        if spec.blending_mode == "logit_shrinkage":
            return bayesian_logit_shrinkage(scaled_model_prob, market_prob_a, spec.alpha)
        else:
            # Linear blending
            return spec.alpha * scaled_model_prob + (1.0 - spec.alpha) * market_prob_a
