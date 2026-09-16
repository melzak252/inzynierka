"""Unit tests for the unified model registry and prediction engine."""

import pytest

from betting_app.core.models import (
    ACTIVE_MODEL_FAMILY,
    ACTIVE_MODEL_NAME,
    ACTIVE_MODEL_VERSION,
    BAYESIAN_SHRUNK_HYBRID,
    EXP039_THESIS,
    EXP078_LINEAR,
    EXP081_SIAMESE,
    HybridSpec,
    ModelSpec,
    PredictionEngine,
    UnifiedPredictionResult,
    get_active_hybrid,
    get_active_model,
    get_active_model_spec,
    get_active_prediction_db_params,
    get_model,
    list_registered_models,
    set_active_model,
)


def test_registry_defaults():
    """Verify default active operational model and hybrid."""
    active = get_active_model()
    assert active.name == ACTIVE_MODEL_NAME
    assert active.version == ACTIVE_MODEL_VERSION
    assert active.family == ACTIVE_MODEL_FAMILY
    assert active.has_uncertainty is True
    assert get_active_model_spec() is active

    hybrid = get_active_hybrid()
    assert hybrid.base_model.name == active.name
    assert hybrid.hybrid_model_name == ACTIVE_MODEL_NAME
    assert hybrid.alpha == 0.50
    assert hybrid.temperature == 1.0

def test_registry_lookups():
    """Verify model lookup by exact name and aliases."""
    assert get_model(ACTIVE_MODEL_NAME) is BAYESIAN_SHRUNK_HYBRID
    assert get_model("shrunk_hybrid") is BAYESIAN_SHRUNK_HYBRID
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
        set_active_model(BAYESIAN_SHRUNK_HYBRID)
        assert get_active_model() is BAYESIAN_SHRUNK_HYBRID
    finally:
        set_active_model(BAYESIAN_SHRUNK_HYBRID)


def test_database_params():
    """Verify database filter parameters for SQL queries."""
    params = get_active_prediction_db_params()
    assert params["sn"] == ACTIVE_MODEL_NAME
    assert params["sv"] == ACTIVE_MODEL_VERSION
    assert params["hn"] == ACTIVE_MODEL_NAME
    assert ACTIVE_MODEL_VERSION in params["hv"]
    assert params["operational_name"] == params["sn"]
    assert params["hybrid_name"] == params["hn"]
def test_list_registered_models():
    """Verify serialized model list for API consumption."""
    models = list_registered_models()
    assert len(models) == 4
    names = [m["name"] for m in models]
    assert ACTIVE_MODEL_NAME in names
    assert "Symmetrized-Siamese-Series-EXP081" in names
    assert "Operational-PlayerTeamRatings-W20" in names
    assert "Sym-Cal LR-ElasticNet-W20-Binomial" in names

    active_items = [m for m in models if m["is_active_operational"]]
    assert len(active_items) == 1
    assert active_items[0]["name"] == ACTIVE_MODEL_NAME
    assert active_items[0]["family"] == ACTIVE_MODEL_FAMILY

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


def test_engine_preserves_both_uncertainty_sides(monkeypatch):
    from betting_app.services import upcoming_inference_service as service
    from betting_app.tests.test_siamese_series import _generate_synthetic_snapshots

    snapshot_a, snapshot_b = _generate_synthetic_snapshots()
    monkeypatch.setattr(service, "_exp078_snapshot_from_features", lambda features: (features, 3))
    a = PredictionEngine.predict_from_features(snapshot_a, EXP081_SIAMESE)
    b = PredictionEngine.predict_from_features(snapshot_b, EXP081_SIAMESE)
    assert a.prob_a + b.prob_a == pytest.approx(1.0)
    assert a.p_low_a == pytest.approx(b.p_low_b)
    assert a.p_low_b == pytest.approx(b.p_low_a)
    assert a.p_low_a < a.prob_a
    assert a.p_low_b < a.prob_b
    assert a.p_low_a + a.p_low_b < 1.0


def test_engine_does_not_disguise_incomplete_features_as_siamese_prediction():
    with pytest.raises(ValueError):
        PredictionEngine.predict_from_features({}, EXP081_SIAMESE)


@pytest.mark.parametrize("mode", ["linear", "logit_shrinkage"])
@pytest.mark.parametrize(
    "parameter,value",
    [("alpha", float("nan")), ("alpha", 1.1), ("temperature", float("inf")),
     ("temperature", 0.0), ("temperature", -1.0)],
)
def test_hybrid_rejects_invalid_transform_parameters(mode, parameter, value):
    spec = HybridSpec(base_model=EXP081_SIAMESE, blending_mode=mode, **{parameter: value})
    with pytest.raises(ValueError):
        PredictionEngine.blend_with_market(0.7, 0.6, spec)


def test_bayesian_shrunk_hybrid_inference_valid_probabilities():
    """Verify PredictionEngine produces valid finite probabilities for bayesian_market_hybrid."""
    mock_features = {
        "canonical_match_id": 9999,
        "canonical": {
            "id": 9999,
            "team_a_name": "Team Liquid",
            "team_b_name": "FlyQuest",
            "best_of": 3,
        },
        "ratings": {
            "probabilities": {
                "consensus": 0.55,
                "elo": 0.55,
                "gl": 0.56,
                "ts": 0.54,
                "os": 0.55,
                "pl": 0.55,
                "tm": 0.55,
            },
        },
        "player_ratings": {
            "probabilities": {
                "consensus": 0.58,
                "elo": 0.58,
                "gl": 0.59,
                "ts": 0.57,
                "os": 0.58,
                "pl": 0.58,
                "tm": 0.58,
            },
        },
        "w20": {"probability": 0.60},
        "market_novig_prob_a": 0.52,
    }

    result = PredictionEngine.predict_from_features(mock_features, BAYESIAN_SHRUNK_HYBRID)
    assert 0.0 < result.prob_a < 1.0
    assert 0.0 < result.prob_b < 1.0
    assert result.prob_a + result.prob_b == pytest.approx(1.0, abs=1e-6)
    assert result.model_name == ACTIVE_MODEL_NAME
    assert result.model_version == ACTIVE_MODEL_VERSION
    assert result.diagnostics["market_features_used"] is True
    assert result.diagnostics["p_market_novig"] == 0.52


def test_bayesian_shrunk_hybrid_fallback_without_market():
    """Verify bayesian_market_hybrid falls back gracefully to p_sports when no market odds exist."""
    mock_features_no_market = {
        "canonical_match_id": 9998,
        "canonical": {
            "id": 9998,
            "team_a_name": "G2 Esports",
            "team_b_name": "Fnatic",
            "best_of": 1,
        },
        "ratings": {
            "probabilities": {"consensus": 0.65},
        },
        "player_ratings": {
            "probabilities": {"consensus": 0.65},
        },
        "w20": {"probability": 0.65},
    }

    result = PredictionEngine.predict_from_features(mock_features_no_market, BAYESIAN_SHRUNK_HYBRID)
    assert 0.0 < result.prob_a < 1.0
    assert 0.0 < result.prob_b < 1.0
    assert result.prob_a + result.prob_b == pytest.approx(1.0, abs=1e-6)
    assert result.diagnostics["market_features_used"] is False
    assert result.diagnostics["p_market_novig"] is None
    assert result.prob_a == pytest.approx(result.diagnostics["p_sports"], abs=1e-6)
