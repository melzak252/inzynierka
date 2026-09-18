"""Regression tests for model hybrid contracts and blending weights."""

import math
import pytest

from betting_app.core.models.contract import HybridSpec
from betting_app.core.models.engine import PredictionEngine, bayesian_logit_shrinkage
from betting_app.core.models.registry import (
    EXP081_SIAMESE,
    get_active_hybrid,
    get_active_model,
)
from betting_app.services.upcoming_inference_service import evaluate_bayesian_market_hybrid


def test_active_hybrid_base_model_is_not_recursive() -> None:
    """The active hybrid base model must strictly be a pure sports model, never a hybrid."""
    hybrid = get_active_hybrid()
    active_model = get_active_model()

    assert hybrid.base_model.family != "bayesian_market_hybrid"
    assert hybrid.base_model.name == EXP081_SIAMESE.name
    assert hybrid.base_model.family == "siamese_mlp"
    assert hybrid.alpha == 0.50
    assert hybrid.temperature == 1.0
    assert active_model.family == "bayesian_market_hybrid"


def test_bayesian_logit_shrinkage_weight_direction() -> None:
    """Alpha = 0.25 must keep the blended probability closer to model than to market.

    logit_blend = (1 - alpha) * logit_model + alpha * logit_market
    With model_weight = 0.75 (1 - alpha), the blend must be 75% model, 25% market.
    """
    p_model = 0.80  # logit ~ 1.386
    p_market = 0.50  # logit = 0.0

    # With model_weight = 0.75, logit_blend = 0.75 * 1.386 + 0.25 * 0 = 1.0395 -> p ~ 0.7388
    blended = bayesian_logit_shrinkage(p_model, p_market, model_weight=0.75)
    assert 0.70 < blended < 0.76
    assert abs(blended - p_model) < abs(blended - p_market)


def test_evaluate_bayesian_market_hybrid_alpha_direction() -> None:
    """evaluate_bayesian_market_hybrid must apply (1 - alpha) to sports and alpha to market."""
    hybrid = get_active_hybrid()
    # Mock features where sports says 0.80 and market says 0.50
    features = {
        "canonical_match_id": "test_m1",
        "canonical": {"id": "test_m1", "best_of": 1, "team_a_name": "T1", "team_b_name": "GEN"},
        "best_of": 1,
        "market_novig_prob_a": 0.50,
        "ratings": {"probabilities": {"consensus": 0.80}},
        "player_ratings": {"probabilities": {"consensus": 0.80}},
    }

    result = evaluate_bayesian_market_hybrid(features, hybrid.base_model)
    # With alpha=0.25, prob_a must be closer to sports (0.80) than to market (0.50)
    assert abs(result.prob_a - 0.80) < abs(result.prob_a - 0.50)
    assert result.prob_a > 0.65
    assert math.isclose(result.prob_a + result.prob_b, 1.0, abs_tol=1e-5)
