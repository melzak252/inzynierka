"""Prediction Engine providing a unified inference interface across all models."""

from __future__ import annotations

import json
import math
from typing import Any, Mapping

from betting_app.core.models.contract import HybridSpec, ModelSpec, UnifiedPredictionResult
from betting_app.core.models.registry import get_active_hybrid, get_active_model


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


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
    if not math.isfinite(model_weight) or not 0.0 <= model_weight <= 1.0:
        raise ValueError("model_weight must be finite and in [0, 1]")
    if not math.isfinite(eps) or not 0.0 < eps < 0.5:
        raise ValueError("eps must be finite and in (0, 0.5)")
    p_m = max(eps, min(1.0 - eps, prob_model))
    p_k = max(eps, min(1.0 - eps, prob_market))
    logit_m = math.log(p_m / (1.0 - p_m))
    logit_k = math.log(p_k / (1.0 - p_k))
    logit_blend = model_weight * logit_m + (1.0 - model_weight) * logit_k
    p_hybrid = _sigmoid(logit_blend)
    return max(eps, min(1.0 - eps, p_hybrid))


def apply_temperature_scaling(prob: float, temperature: float = 0.80, eps: float = 1e-6) -> float:
    """Scale logit(prob) by 1/T: T>1 softens; T<1 (including 0.80) sharpens.

    This transformation alone does not establish calibration, especially after
    selecting bets using their disagreement with market prices.
    """
    if not math.isfinite(prob):
        raise ValueError(f"Probability must be finite, got {prob}")
    if not (0.0 <= prob <= 1.0):
        raise ValueError(f"Probability must be in [0, 1], got {prob}")
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    if not math.isfinite(eps) or not 0.0 < eps < 0.5:
        raise ValueError("eps must be finite and in (0, 0.5)")
    p = max(eps, min(1.0 - eps, prob))
    logit = math.log(p / (1.0 - p))
    scaled_logit = logit / temperature
    return _sigmoid(scaled_logit)


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

            snapshot, best_of = _exp078_snapshot_from_features(features)
            model = SiameseSeriesModel.load_default()
            p_mean, sigma_z, p_low, p_low_b = model.predict_with_uncertainty(snapshot, best_of=best_of)
            map_p_mean = model.predict(snapshot, best_of=1) if best_of > 1 else p_mean

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
                    "p_low_a": p_low,
                    "p_low_b": p_low_b,
                    "uncertainty_required": True,
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

        elif spec.family == "bayesian_market_hybrid":
            from betting_app.services.upcoming_inference_service import evaluate_bayesian_market_hybrid
            return evaluate_bayesian_market_hybrid(features, spec)

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
        if not math.isfinite(spec.alpha) or not 0.0 <= spec.alpha <= 1.0:
            raise ValueError("alpha must be finite and in [0, 1]")
        if not math.isfinite(market_prob_a) or not 0.0 <= market_prob_a <= 1.0:
            raise ValueError("market probability must be finite and in [0, 1]")
        scaled_model_prob = apply_temperature_scaling(model_prob_a, spec.temperature)

        if spec.blending_mode == "logit_shrinkage":
            return bayesian_logit_shrinkage(scaled_model_prob, market_prob_a, spec.alpha)
        elif spec.blending_mode == "linear":
            return spec.alpha * scaled_model_prob + (1.0 - spec.alpha) * market_prob_a
        raise ValueError(f"Unsupported blending mode: {spec.blending_mode}")
