"""Regression tests for model hybrid contracts and blending weights."""

from betting_app.core.models.engine import bayesian_logit_shrinkage




def test_bayesian_logit_shrinkage_weight_direction() -> None:
    """An explicit 75% model weight must favor model log odds over market log odds."""
    p_model = 0.80  # logit ~ 1.386
    p_market = 0.50  # logit = 0.0

    # With model_weight = 0.75, logit_blend = 0.75 * 1.386 + 0.25 * 0 = 1.0395 -> p ~ 0.7388
    blended = bayesian_logit_shrinkage(p_model, p_market, model_weight=0.75)
    assert 0.70 < blended < 0.76
    assert abs(blended - p_model) < abs(blended - p_market)
