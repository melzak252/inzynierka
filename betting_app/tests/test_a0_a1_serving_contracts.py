"""Serving contracts at the controlled C0 boundary."""

from dataclasses import replace
import math

import pytest

from betting_app.core.models import BAYESIAN_SHRUNK_HYBRID, C0_NATIVE, PredictionEngine
from betting_app.core.models.contract import UnifiedPredictionResult
from betting_app.services import c0_inference
from betting_app.services import upcoming_inference_service as service


def _features(market=0.55):
    return {
        "canonical_match_id": 17,
        "canonical": {
            "id": 17,
            "best_of": 3,
            "team_a_name": "Alpha",
            "team_b_name": "Beta",
        },
        "c0_request": {"team1_id": "1", "team2_id": "2"},
        "market_novig_prob_a": market,
    }


def _install_c0_boundary(monkeypatch, probability=0.72):
    calls = []

    def predict(features):
        calls.append(features)
        return UnifiedPredictionResult(
            canonical_match_id=features["canonical_match_id"],
            prob_a=probability,
            prob_b=1.0 - probability,
            model_name=C0_NATIVE.name,
            model_version=C0_NATIVE.version,
            feature_version=C0_NATIVE.feature_version,
            best_of=features["canonical"]["best_of"],
        )

    monkeypatch.setattr(c0_inference, "predict_c0", predict)
    return calls


def test_native_c0_boundary_error_does_not_become_a_ratings_fallback(monkeypatch):
    def unavailable(_features):
        raise FileNotFoundError("native history/artifact unavailable")

    monkeypatch.setattr(c0_inference, "predict_c0", unavailable)
    with pytest.raises(FileNotFoundError, match="native history"):
        PredictionEngine.predict_from_features(_features(), C0_NATIVE)


def test_market_hybrid_shrinks_native_c0_mean_without_uncertainty(monkeypatch):
    calls = _install_c0_boundary(monkeypatch, probability=0.72)
    spec = replace(
        BAYESIAN_SHRUNK_HYBRID,
        metadata={**BAYESIAN_SHRUNK_HYBRID.metadata, "alpha": 0.25, "temperature": 1.4},
    )

    result = service.evaluate_bayesian_market_hybrid(_features(0.55), spec)

    expected_logit = (
        0.25 * math.log(0.72 / 0.28) / 1.4
        + 0.75 * math.log(0.55 / 0.45)
    )
    assert result.prob_a == pytest.approx(1.0 / (1.0 + math.exp(-expected_logit)))
    assert result.prob_a + result.prob_b == pytest.approx(1.0)
    assert result.p_low_a is result.p_low_b is result.epistemic_sigma_z is None
    assert len(calls) == 1


def test_native_c0_series_probability_is_market_independent_but_hybrid_is_not(monkeypatch):
    calls = _install_c0_boundary(monkeypatch, probability=0.68)
    first_features, second_features = _features(0.2), _features(0.8)

    first = PredictionEngine.predict_from_features(first_features, C0_NATIVE)
    second = PredictionEngine.predict_from_features(second_features, C0_NATIVE)
    first_hybrid = service.evaluate_bayesian_market_hybrid(first_features, BAYESIAN_SHRUNK_HYBRID)
    second_hybrid = service.evaluate_bayesian_market_hybrid(second_features, BAYESIAN_SHRUNK_HYBRID)

    assert first.prob_a == second.prob_a == 0.68
    assert first.map_prob_a is second.map_prob_a is None
    assert first_hybrid.prob_a != pytest.approx(second_hybrid.prob_a)
    assert len(calls) == 4
