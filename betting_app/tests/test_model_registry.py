"""Unit tests for the unified model registry and prediction engine."""

import pytest

from betting_app.core.models import (
    EXP039_THESIS,
    EXP078_LINEAR,
    EXP081_SIAMESE,
    HybridSpec,
    ModelSpec,
    PredictionEngine,
    UnifiedPredictionResult,
    get_active_hybrid,
    get_active_model,
    get_active_prediction_db_params,
    get_model,
    list_registered_models,
    set_active_model,
)


def test_registry_defaults():
    """Verify default active operational model and hybrid."""
    active = get_active_model()
    assert active.name == "Symmetrized-Siamese-Series-EXP081"
    assert active.version == "exp081-siamese-series-v1"
    assert active.has_uncertainty is True

    hybrid = get_active_hybrid()
    assert hybrid.base_model.name == active.name
    assert hybrid.hybrid_model_name == "Hybrid-Operational-Market"
    assert "exp081-siamese-series-v1" in hybrid.hybrid_model_version


def test_registry_lookups():
    """Verify model lookup by exact name and aliases."""
    assert get_model("Symmetrized-Siamese-Series-EXP081") is EXP081_SIAMESE
    assert get_model("exp081") is EXP081_SIAMESE
    assert get_model("Operational-PlayerTeamRatings-W20") is EXP078_LINEAR
    assert get_model("exp078") is EXP078_LINEAR
    assert get_model("Sym-Cal LR-ElasticNet-W20-Binomial") is EXP039_THESIS
    assert get_model("exp039") is EXP039_THESIS
    assert get_model("non_existent") is None


def test_registry_switching():
    """Verify switching active operational model updates hybrid automatically."""
    try:
        set_active_model("exp078")
        current = get_active_model()
        assert current is EXP078_LINEAR
        hybrid = get_active_hybrid()
        assert hybrid.base_model is EXP078_LINEAR
        assert "exp078" in hybrid.hybrid_model_version

        # Switch back
        set_active_model(EXP081_SIAMESE)
        assert get_active_model() is EXP081_SIAMESE
    finally:
        set_active_model(EXP081_SIAMESE)


def test_database_params():
    """Verify database filter parameters for SQL queries."""
    params = get_active_prediction_db_params()
    assert params["sn"] == "Symmetrized-Siamese-Series-EXP081"
    assert params["sv"] == "exp081-siamese-series-v1"
    assert params["hn"] == "Hybrid-Operational-Market"
    assert "exp081" in params["hv"]
    assert params["operational_name"] == params["sn"]
    assert params["hybrid_name"] == params["hn"]


def test_list_registered_models():
    """Verify serialized model list for API consumption."""
    models = list_registered_models()
    assert len(models) == 3
    names = [m["name"] for m in models]
    assert "Symmetrized-Siamese-Series-EXP081" in names
    assert "Operational-PlayerTeamRatings-W20" in names
    assert "Sym-Cal LR-ElasticNet-W20-Binomial" in names

    active_items = [m for m in models if m["is_active_operational"]]
    assert len(active_items) == 1
    assert active_items[0]["name"] == "Symmetrized-Siamese-Series-EXP081"


def test_unified_prediction_result_validation():
    """Verify invariant validation in UnifiedPredictionResult."""
    valid = UnifiedPredictionResult(
        canonical_match_id=1,
        prob_a=0.65,
        prob_b=0.35,
        model_name="test",
        model_version="v1",
    )
    assert valid.prob_a == 0.65
    assert valid.prob_b == 0.35

    with pytest.raises(ValueError, match="prob_a must be in"):
        UnifiedPredictionResult(canonical_match_id=1, prob_a=1.2, prob_b=-0.2)

    with pytest.raises(ValueError, match="prob_a \\+ prob_b must equal 1.0"):
        UnifiedPredictionResult(canonical_match_id=1, prob_a=0.6, prob_b=0.6)


def test_blend_with_market():
    """Verify market blending using both logit shrinkage and linear modes."""
    # Equal 50-50
    p_blend = PredictionEngine.blend_with_market(0.50, 0.50)
    assert p_blend == pytest.approx(0.50, abs=1e-3)

    # Model says 0.70, market says 0.60
    p_blend_shrink = PredictionEngine.blend_with_market(0.70, 0.60)
    assert 0.50 < p_blend_shrink < 0.70

    # Linear blending test
    lin_spec = HybridSpec(
        base_model=EXP081_SIAMESE,
        alpha=0.40,
        temperature=1.0,
        blending_mode="linear",
    )
    p_linear = PredictionEngine.blend_with_market(0.80, 0.50, hybrid_spec=lin_spec)
    assert p_linear == pytest.approx(0.40 * 0.80 + 0.60 * 0.50, abs=1e-3)


def test_model_alias_normalization():
    """Verify case-insensitive and dash/underscore-insensitive alias lookups."""
    assert get_model("EXP-081") is not None
    assert get_model("exp-081") is not None
    assert get_model("EXP081") is not None
    assert get_model("EXP-078") is not None
    assert get_model("exp078") is not None
    assert get_model("EXP-039") is not None
    assert get_model("nonexistent-model") is None


def test_blend_with_market_rejects_non_finite():
    """Verify blend_with_market raises ValueError on NaN or Inf."""
    import math
    with pytest.raises(ValueError, match="finite"):
        PredictionEngine.blend_with_market(float("nan"), 0.50)
    with pytest.raises(ValueError, match="finite"):
        PredictionEngine.blend_with_market(0.50, float("inf"))


def test_conservative_p_low_b_bound():
    """Verify that both p_low_a and p_low_b are conservative lower bounds."""
    from betting_app.tests.test_siamese_series import _generate_synthetic_snapshots
    from src.models.siamese_series import SiameseSeriesModel
    import math

    snapshot_a, _ = _generate_synthetic_snapshots()
    model = SiameseSeriesModel.load_default()
    p_mean, sigma_z, p_low_a = model.predict_with_uncertainty(snapshot_a, best_of=3)
    k = model.risk_kappa
    z_mean = math.log(p_mean / (1.0 - p_mean))
    p_low_b = 1.0 / (1.0 + math.exp(z_mean + k * sigma_z))

    assert p_low_a < p_mean, f"p_low_a ({p_low_a}) should be < p_mean ({p_mean})"
    assert p_low_b < (1.0 - p_mean), f"p_low_b ({p_low_b}) should be < p_b ({1.0 - p_mean})"
    assert p_low_a + p_low_b < 1.0, "Sum of conservative lower bounds should be < 1.0"
