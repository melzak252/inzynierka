"""Unit tests for EXP-081 Siamese series backfill and feature adapter logic."""

from __future__ import annotations

import pytest

from betting_app.core.models import EXP081_SIAMESE
from betting_app.core.models.engine import PredictionEngine
from betting_app.services.upcoming_inference_service import (
    _days_since_last,
    _exp078_snapshot_from_features,
    _normalized_best_of,
)


def test_normalized_best_of():
    assert _normalized_best_of(None) == 1
    assert _normalized_best_of(1) == 1
    assert _normalized_best_of("3") == 3
    assert _normalized_best_of(5) == 5
    with pytest.raises(ValueError):
        _normalized_best_of(2)


def test_days_since_last_fallbacks():
    # Empty features should default safely without crashing
    features = {"canonical": {}, "ratings": {}}
    days = _days_since_last(features, "team_a")
    assert days == 7.0

    # With valid start and last match
    features = {
        "canonical": {"start_time_normalized": "2026-06-26T13:00:00+00:00"},
        "ratings": {
            "team_a": {
                "elo": {"last_match_at": "2026-06-20T13:00:00+00:00"},
            }
        },
    }
    days = _days_since_last(features, "team_a")
    assert round(days, 1) == 6.0


def test_exp078_snapshot_from_features_complete():
    mock_features = {
        "canonical": {"best_of": 3, "start_time_normalized": "2026-06-26T13:00:00+00:00"},
        "ratings": {
            "probabilities": {
                "elo": 0.55,
                "gl": 0.54,
                "ts": 0.52,
                "os": 0.53,
                "pl": 0.56,
                "tm": 0.54,
                "consensus": 0.54,
            },
            "team_a": {
                "elo": {"rating_value": 1600.0, "last_match_at": "2026-06-20T13:00:00+00:00"},
                "gl": {"rating_value": 1620.0, "rd": 65.0, "sigma": 0.06},
                "ts": {"rating_value": 26.0, "sigma": 3.2},
                "os": {"rating_value": 26.5, "sigma": 3.1},
                "pl": {"rating_value": 0.2, "sigma": 0.4},
                "tm": {"rating_value": 0.15, "sigma": 0.4},
            },
            "team_b": {
                "elo": {"rating_value": 1550.0, "last_match_at": "2026-06-21T13:00:00+00:00"},
                "gl": {"rating_value": 1570.0, "rd": 70.0, "sigma": 0.06},
                "ts": {"rating_value": 24.5, "sigma": 3.4},
                "os": {"rating_value": 25.0, "sigma": 3.3},
                "pl": {"rating_value": -0.1, "sigma": 0.4},
                "tm": {"rating_value": -0.05, "sigma": 0.4},
            },
        },
        "player_ratings": {
            "probabilities": {
                "elo": 0.53,
                "gl": 0.52,
                "ts": 0.51,
                "os": 0.52,
                "pl": 0.54,
                "tm": 0.53,
                "consensus": 0.525,
            },
            "team_a": {
                "elo": {"min_rating_value": 1500.0, "max_rating_value": 1700.0, "players": [{"rating_value": 1600.0}]},
                "gl": {"min_rating_value": 1520.0, "max_rating_value": 1720.0, "players": [{"rating_value": 1620.0, "rd": 60.0}]},
                "ts": {"min_rating_value": 24.0, "max_rating_value": 28.0, "players": [{"rating_value": 26.0, "sigma": 3.0}]},
                "os": {"min_rating_value": 24.5, "max_rating_value": 28.5, "players": [{"rating_value": 26.5, "sigma": 3.0}]},
                "pl": {"min_rating_value": 0.0, "max_rating_value": 0.4, "players": [{"rating_value": 0.2, "sigma": 0.3}]},
                "tm": {"min_rating_value": 0.0, "max_rating_value": 0.3, "players": [{"rating_value": 0.15, "sigma": 0.3}]},
            },
            "team_b": {
                "elo": {"min_rating_value": 1450.0, "max_rating_value": 1650.0, "players": [{"rating_value": 1550.0}]},
                "gl": {"min_rating_value": 1470.0, "max_rating_value": 1670.0, "players": [{"rating_value": 1570.0, "rd": 65.0}]},
                "ts": {"min_rating_value": 22.5, "max_rating_value": 26.5, "players": [{"rating_value": 24.5, "sigma": 3.2}]},
                "os": {"min_rating_value": 23.0, "max_rating_value": 27.0, "players": [{"rating_value": 25.0, "sigma": 3.2}]},
                "pl": {"min_rating_value": -0.3, "max_rating_value": 0.1, "players": [{"rating_value": -0.1, "sigma": 0.35}]},
                "tm": {"min_rating_value": -0.2, "max_rating_value": 0.1, "players": [{"rating_value": -0.05, "sigma": 0.35}]},
            },
        },
        "w20": {
            "team_a": {
                "win_rate": 0.60,
                "avg_kills": 14.0,
                "avg_deaths": 10.0,
                "avg_kpm": 0.8,
                "avg_dpm": 2100.0,
                "avg_gpm": 1850.0,
                "avg_gd15": 450.0,
                "avg_csd15": 12.0,
                "avg_xpd15": 200.0,
                "avg_first_blood_rate": 0.55,
                "avg_first_tower_rate": 0.60,
                "avg_dragons": 2.8,
                "avg_dragons_at_15": 1.2,
                "avg_heralds": 0.9,
                "avg_voidgrubs": 4.5,
                "avg_plates": 7.0,
                "avg_vspm": 8.5,
                "avg_towers": 7.5,
                "avg_nashors": 1.1,
                "avg_gold": 62000.0,
                "avg_game_duration": 1880.0,
            },
            "team_b": {
                "win_rate": 0.45,
                "avg_kills": 11.0,
                "avg_deaths": 13.0,
                "avg_kpm": 0.65,
                "avg_dpm": 1800.0,
                "avg_gpm": 1720.0,
                "avg_gd15": -300.0,
                "avg_csd15": -8.0,
                "avg_xpd15": -150.0,
                "avg_first_blood_rate": 0.40,
                "avg_first_tower_rate": 0.45,
                "avg_dragons": 2.1,
                "avg_dragons_at_15": 0.8,
                "avg_heralds": 0.6,
                "avg_voidgrubs": 3.0,
                "avg_plates": 4.5,
                "avg_vspm": 7.8,
                "avg_towers": 5.0,
                "avg_nashors": 0.7,
                "avg_gold": 57000.0,
                "avg_game_duration": 1920.0,
            },
        },
    }

    snapshot, best_of = _exp078_snapshot_from_features(mock_features)
    assert best_of == 3
    assert "team_elo_r1" in snapshot
    assert "t1_rolling_win_rate" in snapshot
    assert "days_since_last_1" in snapshot

    # Run inference with EXP-081 Siamese model
    res = PredictionEngine.predict_from_features(mock_features, model_spec=EXP081_SIAMESE)
    assert 0.0 < res.prob_a < 1.0
    assert 0.0 < res.prob_b < 1.0
    assert abs((res.prob_a + res.prob_b) - 1.0) < 1e-6
    assert res.map_prob_a is not None
    assert res.epistemic_sigma_z is not None
    assert res.p_low_a is not None
    assert res.p_low_b is not None
    assert res.p_low_a <= res.prob_a
