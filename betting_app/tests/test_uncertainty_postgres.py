"""Real PostgreSQL query and public-read safety regressions (isolated client fixture)."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from betting_app.api.routers import matches as matches_router
from betting_app.core.db import get_session
from betting_app.services import upcoming_inference_service as service
from betting_app.services.market_service import kelly_fraction


def seed_prediction(*, hybrid=False):
    now = datetime.now(UTC)
    diagnostics = {
        "uncertainty_required": True,
        "p_low_a": 0.55,
        "p_low_b": 0.35,
        "epistemic_sigma_z": 0.3,
        "rating_disagreement": 0.04,
    }
    name = service.DEFAULT_HYBRID_MODEL_NAME if hybrid else service.DEFAULT_MODEL_NAME
    version = (
        matches_router.HYBRID_MODEL_VERSION if hybrid else service.DEFAULT_MODEL_VERSION
    )
    with get_session() as session:
        session.execute(
            text("""INSERT INTO canonical_matches
            (id, canonical_key, team_a_name, team_b_name, normalized_team_a, normalized_team_b,
             start_time_normalized, league, status, match_confidence)
            VALUES (1, 'uncertainty', 'Alpha', 'Beta', 'alpha', 'beta', :start, 'Unmapped invitational', 'upcoming', 1)
        """),
            {"start": (now + timedelta(days=1)).isoformat()},
        )
        session.execute(
            text("""INSERT INTO odds_snapshots
            (id, canonical_match_id, bookmaker_id, market_type, is_live, raw_team_a, raw_team_b, odds_a, odds_b, scraped_at)
            VALUES (1, 1, 2, 'match_winner', 0, 'Alpha', 'Beta', 3.5, 3.5, :now)
        """),
            {"now": now.isoformat()},
        )
        session.execute(
            text("""INSERT INTO upcoming_matches
            (bookmaker_id, bookmaker_match_key, canonical_match_id, raw_team_a, raw_team_b,
             normalized_team_a, normalized_team_b, last_seen_at)
            VALUES (2, 'uncertainty', 1, 'Alpha', 'Beta', 'alpha', 'beta', :now)
        """),
            {"now": now.isoformat()},
        )
        session.execute(
            text("""INSERT INTO canonical_predictions
            (canonical_match_id, model_name, model_version, predicted_at, data_cutoff_at,
             prob_a, prob_b, diagnostics_json, prediction_status)
            VALUES (1, :name, :version, :predicted, :cutoff, .6, .4, :diag, 'active')
        """),
            {
                "name": name,
                "version": version,
                "predicted": (now - timedelta(minutes=1)).isoformat(),
                "cutoff": (now - timedelta(minutes=2)).isoformat(),
                "diag": json.dumps(diagnostics),
            },
        )
        session.commit()
    return name, version


def replace_diagnostics(diagnostics):
    with get_session() as session:
        session.execute(
            text("UPDATE canonical_predictions SET diagnostics_json=:diag WHERE id=1"),
            {"diag": json.dumps(diagnostics)},
        )
        session.commit()


def test_service_returns_real_ids_and_retires_invalid_signals(client):
    name, version = seed_prediction()
    signals = service.generate_model_ev_signals(model_name=name, model_version=version)
    assert {signal["side"] for signal in signals} == {"a", "b"}
    with get_session() as session:
        persisted = (
            session.execute(
                text("SELECT id, ev FROM model_ev_signals ORDER BY ev DESC")
            )
            .mappings()
            .all()
        )
    assert [s["signal_id"] for s in signals] == [p["id"] for p in persisted]
    assert all(s["signal_id"] > 0 for s in signals)
    assert [p["ev"] for p in persisted] == pytest.approx([s["ev"] for s in signals])
    replace_diagnostics({"p_low_a": 0.55})
    assert (
        service.generate_model_ev_signals(model_name=name, model_version=version) == []
    )
    with get_session() as session:
        assert (
            session.execute(
                text("SELECT COUNT(*) FROM model_ev_signals WHERE status='new'")
            ).scalar()
            == 0
        )


def test_hybrid_rejects_one_sided_input_and_retires_previous_prediction(client):
    seed_prediction()
    hybrids = service.generate_hybrid_predictions()
    assert len(hybrids) == 1
    with get_session() as session:
        diag = json.loads(
            session.execute(
                text(
                    "SELECT diagnostics_json FROM canonical_predictions WHERE model_name=:name"
                ),
                {"name": service.DEFAULT_HYBRID_MODEL_NAME},
            ).scalar_one()
        )
    assert diag["p_low_a"] + diag["p_low_b"] < 1
    replace_diagnostics({"p_low_a": 0.55})
    assert service.generate_hybrid_predictions() == []
    with get_session() as session:
        assert (
            session.execute(
                text(
                    "SELECT COUNT(*) FROM canonical_predictions WHERE model_name=:name AND prediction_status='active'"
                ),
                {"name": service.DEFAULT_HYBRID_MODEL_NAME},
            ).scalar()
            == 0
        )


def test_signal_endpoint_rechecks_bounds_and_uses_conservative_kelly(client):
    name, version = seed_prediction(hybrid=True)
    service.generate_model_ev_signals(model_name=name, model_version=version)
    response = client.get("/predictions")
    assert response.status_code == 200
    signals = response.json()["signals"]
    assert {signal["side"] for signal in signals} == {"a", "b"}
    for signal in signals:
        lower = {"a": 0.55, "b": 0.35}[signal["side"]]
        assert signal["kelly"] == pytest.approx(kelly_fraction(lower, 3.5, 0.12))
    replace_diagnostics({"p_low_a": 0.55})
    assert client.get("/predictions").json()["signals"] == []


def test_board_and_detail_cannot_bypass_conservative_qualification(client, monkeypatch):
    seed_prediction(hybrid=True)
    monkeypatch.setattr(
        matches_router, "suggest_mapping", lambda name: (name, 1.0, "fixture")
    )
    board = client.get("/matches?min_books=1").json()["matches"][0]
    assert board["recommended_side"] == "a"
    detail = client.get("/matches/1")
    assert detail.status_code == 200
    assert detail.json()["recommendation"]["has_value"]
    replace_diagnostics(
        {
            "p_low_a": 0.2,
            "p_low_b": 0.2,
            "epistemic_sigma_z": 1.0,
            "rating_disagreement": 0.04,
        }
    )
    board = client.get("/matches?min_books=1").json()["matches"][0]
    assert board["recommended_side"] is None
    detail = client.get("/matches/1").json()
    assert not detail["recommendation"]["has_value"]
    assert all(
        row["kelly_a"] is None and row["kelly_b"] is None for row in detail["odds"]
    )
