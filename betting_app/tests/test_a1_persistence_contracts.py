"""PostgreSQL regressions for persisted model identity and as-of odds selection."""

from datetime import UTC, datetime, timedelta
import json

import pytest
from sqlalchemy import select

from betting_app.core.db import get_session
from betting_app.core.models import BAYESIAN_SHRUNK_HYBRID, C0_NATIVE
from betting_app.core.models import PredictionEngine, get_active_hybrid
from betting_app.models.match import CanonicalMatch
from betting_app.models.odds import OddsSnapshot
from betting_app.models.prediction import CanonicalPrediction, ModelArtifact, UpcomingMatchFeature
from betting_app.models.golgg import GolggTeam
from betting_app.services import mapping_service
from betting_app.services import upcoming_inference_service as service
# Native C0 request fixture; persistence tests do not depend on GL/W20 features.
def _native_features(match_id=0, *, start=None, team_a="Alpha", team_b="Beta"):
    start = start or (datetime.now(UTC) + timedelta(days=1)).isoformat()
    return {
        "canonical": {
            "id": match_id, "team_a_name": team_a, "team_b_name": team_b,
            "start_time_normalized": start, "best_of": 3, "league": "Test",
        },
        "c0_request": {
            "team1_id": "team-a", "team2_id": "team-b",
            "roster_a": [f"a{i}" for i in range(5)],
            "roster_b": [f"b{i}" for i in range(5)],
            "best_of": 3, "decision_at": datetime.now(UTC).isoformat(),
            "competition_context": "Test", "start_at": start, "mode": "full",
        },
    }


def _match(session, start):
    match = CanonicalMatch(
        canonical_key=f"audit-alpha-beta-{start.isoformat()}",
        team_a_name="Alpha", team_b_name="Beta",
        normalized_team_a="alpha", normalized_team_b="beta",
        start_time_normalized=start.isoformat(), best_of=3,
    )
    session.add(match)
    session.flush()
    return match



def test_resolve_exact_canonical_ids_aligns_reversed_linked_offer(monkeypatch):
    import pandas as pd

    match = {
        "id": 812, "team_a_name": "Alpha", "team_b_name": "Beta",
        "league": "LCK", "start_time_normalized": "2026-10-10T12:00:00+00:00",
    }
    offers = pd.DataFrame([{
        "raw_team_a": "Beta", "raw_team_b": "Alpha", "league": "LCK",
        "team_a_golgg_id": 22, "team_b_golgg_id": 11,
    }])
    monkeypatch.setattr(service, "query_df", lambda *args, **kwargs: offers)
    monkeypatch.setattr(
        service,
        "native_golgg_team_id",
        lambda internal_id, **kwargs: f"provider-{internal_id}" if internal_id is not None else None,
    )
    resolved = service.resolve_exact_canonical_team_ids(match)
    assert (resolved["native_team_a_id"], resolved["native_team_b_id"]) == ("provider-11", "provider-22")
    assert (resolved["team_a_golgg_id"], resolved["team_b_golgg_id"]) == (11, 22)

    monkeypatch.setattr(service, "query_df", lambda *args, **kwargs: pd.DataFrame())
    unresolved = service.resolve_exact_canonical_team_ids(match)
    assert unresolved["team_a_golgg_id"] is None
    assert unresolved["team_b_golgg_id"] is None

def test_db_team_row_id_resolves_to_provider_id_without_namespace_leak(monkeypatch):
    from contextlib import nullcontext

    class Result:
        def fetchone(self):
            return {"team_name": "Exact Main", "team_id": 2817}

    class Connection:
        def execute(self, sql, params):
            assert "WHERE id = ?" in sql
            assert params == (1,)
            return Result()

    monkeypatch.setattr(mapping_service, "transaction", lambda: nullcontext(Connection()))
    assert mapping_service.native_golgg_team_id(1, team_name="Exact Main") == "2817"
    assert mapping_service.native_golgg_team_id(1, team_name="Exact Main") != "1"
    with pytest.raises(ValueError, match="does not identify"):
        mapping_service.native_golgg_team_id(1, team_name="Different Main")


@pytest.mark.parametrize("known_side", [None, "a", "b"])
def test_unknown_provider_ids_use_explicit_no_organization_targets(monkeypatch, known_side):
    monkeypatch.setattr(service, "native_golgg_team_id", lambda *args, **kwargs: None)
    roster_a = {"players": [{"player_id": f"a{i}"} for i in range(5)]}
    roster_b = {"players": [{"player_id": f"b{i}"} for i in range(5)]}
    now = datetime.now(UTC)
    request, missing = service._native_c0_request(
        {
            "id": 7, "team_a_name": "Main Team", "team_b_name": "Main Team Academy",
            "team_a_golgg_id": 1, "team_b_golgg_id": 2,
            "native_team_a_id": "2817" if known_side == "a" else None,
            "native_team_b_id": "2818" if known_side == "b" else None,
            "best_of": 3, "_c0_decision_at": now.isoformat(),
            "start_time_normalized": (now + timedelta(hours=1)).isoformat(),
        },
        roster_a,
        roster_b,
    )
    assert request["mode"] == "no_organization"
    assert request["team1_id"] == "no_organization:target:Main%20Team"
    assert request["team2_id"] == "no_organization:target:Main%20Team%20Academy"
    assert "1" not in {request["team1_id"], request["team2_id"]}
    assert missing == []


def test_partial_native_input_never_substitutes_bo1_for_unsupported_format():
    from betting_app.core.models.native_c0 import NativeC0Adapter

    now = datetime.now(UTC)
    request, missing = service._native_c0_request(
        {
            "id": 88, "team_a_name": "Alpha", "team_b_name": "Beta",
            "best_of": 7, "_c0_decision_at": now.isoformat(),
            "start_time_normalized": (now + timedelta(hours=1)).isoformat(),
        },
        {"team_id": "native-a", "players": [{"player_id": f"a{i}"} for i in range(5)]},
        {"team_id": "native-b", "players": [{"player_id": f"b{i}"} for i in range(5)]},
    )
    assert "c0_unsupported_best_of:7" in missing
    with pytest.raises(ValueError, match="best_of"):
        NativeC0Adapter.__new__(NativeC0Adapter)._validate_request(request)



def test_matchup_rejects_database_id_name_mismatch_before_feature_inference(client, monkeypatch):
    with get_session() as session:
        team = GolggTeam(
            team_name="Exact DB Team", team_id=9182738, normalized_name="exact db team",
        )
        session.add(team)
        session.commit()
        row_id = team.id

    def forbidden_inference(*args, **kwargs):
        raise AssertionError("mismatched team identity reached feature inference")

    monkeypatch.setattr(
        "betting_app.services.upcoming_inference_service.build_features_for_match",
        forbidden_inference,
    )
    response = client.post(
        "/matches/matchup",
        json={
            "team_a_name": "Different Team", "team_b_name": "Opponent",
            "team_a_team_row_id": row_id,
        },
    )
    assert response.status_code == 422
    assert "does not identify" in response.json()["detail"]

def test_single_match_inference_resolves_missing_team_ids_before_feature_build(monkeypatch):
    observed = {}
    monkeypatch.setattr(
        service, "resolve_exact_canonical_team_ids",
        lambda match: {**match, "team_a_golgg_id": 11, "team_b_golgg_id": 22},
    )

    def build(match, **kwargs):
        observed.update(team_a_id=match["team_a_golgg_id"], team_b_id=match["team_b_golgg_id"])
        return {
            "status": "ready_player", "missing": [],
            "features": {"c0_request": {}, "canonical": match},
            "data_cutoff_at": None,
        }

    monkeypatch.setattr(service, "build_features_for_match", build)
    monkeypatch.setattr(service, "predict_probability_from_features", lambda *args, **kwargs: (
        0.6, {"data_cutoff_at": "2026-10-05T00:00:00+00:00"},
    ))
    service.predict_operational_match(
        {"id": 42, "team_a_name": "Alpha", "team_b_name": "Beta"},
        model_name=C0_NATIVE.name, model_version=C0_NATIVE.version, persist=False,
    )
    assert observed == {"team_a_id": 11, "team_b_id": 22}


def test_upcoming_batch_skips_closed_fixtures_and_isolates_invalid_rows(client, monkeypatch):
    now = datetime.now(UTC)
    with get_session() as session:
        expired = _match(session, now - timedelta(minutes=1))
        finished = _match(session, now + timedelta(hours=2))
        finished.status = "completed"
        bad = _match(session, now + timedelta(hours=3))
        good = _match(session, now + timedelta(hours=4))
        matches = {"expired": expired, "finished": finished, "bad": bad, "good": good}
        ids = {key: match.id for key, match in matches.items()}
        for match in matches.values():
            feature_data = _native_features(match.id, start=match.start_time_normalized)
            session.add(UpcomingMatchFeature(
                canonical_match_id=match.id, feature_version=C0_NATIVE.feature_version,
                ratings_version=C0_NATIVE.ratings_version, feature_status="ready_player",
                features_json=json.dumps(feature_data),
            ))
        session.commit()
    inferred = []

    def predict(features, **kwargs):
        match_id = features["canonical"]["id"]
        inferred.append(match_id)
        if match_id == ids["bad"]:
            raise ValueError("invalid exact roster")
        return 0.63, {"model_name": C0_NATIVE.name, "model_version": C0_NATIVE.version}

    monkeypatch.setattr(service, "predict_probability_from_features", predict)
    result = service.predict_all_upcoming()
    assert inferred == [ids["bad"], ids["good"]]
    assert [row["canonical_match_id"] for row in result if row.get("prediction_status") == "skipped"] == [
        ids["expired"], ids["finished"], ids["bad"],
    ]
    with get_session() as session:
        predictions = session.scalars(select(CanonicalPrediction).where(
            CanonicalPrediction.canonical_match_id.in_(ids.values()),
        )).all()
        assert [row.canonical_match_id for row in predictions] == [ids["good"]]

def test_native_c0_prediction_records_exact_model_artifact_and_history_cutoff(client, monkeypatch):
    cutoff = "2026-10-05T00:00:00+00:00"
    monkeypatch.setattr(
        service,
        "predict_probability_from_features",
        lambda *args, **kwargs: (0.61, {
            "model_name": C0_NATIVE.name,
            "model_version": C0_NATIVE.version,
            "feature_version": C0_NATIVE.feature_version,
            "data_cutoff_at": cutoff,
            "market_features_used": False,
            "epistemic_sigma_z": None,
            "p_low_a": None,
            "p_low_b": None,
        }),
    )
    with get_session() as session:
        match = _match(session, datetime.now(UTC) + timedelta(days=1))
        c0_features = _native_features(match.id, start=match.start_time_normalized)
        session.add(UpcomingMatchFeature(
            canonical_match_id=match.id, feature_version=C0_NATIVE.feature_version,
            ratings_version=C0_NATIVE.ratings_version, feature_status="ready_player",
            features_json=json.dumps(c0_features),
        ))
        session.commit()
    generated = service.predict_all_upcoming()
    assert len(generated) == 1
    with get_session() as session:
        prediction, artifact = session.execute(select(CanonicalPrediction, ModelArtifact).join(
            ModelArtifact, CanonicalPrediction.model_artifact_id == ModelArtifact.id,
        )).one()
        feature_schema = json.loads(artifact.feature_schema_json)
        model_params = json.loads(artifact.model_params_json)
        diagnostics = json.loads(prediction.diagnostics_json)
        assert (artifact.model_name, artifact.model_version) == (C0_NATIVE.name, C0_NATIVE.version)
        assert feature_schema["input_contract"] == "native-c0-request-v1"
        assert feature_schema["has_uncertainty"] is False
        assert model_params["model_identity"]["name"] == C0_NATIVE.name
        assert model_params["model_identity"]["artifact_hashes"]
        assert prediction.data_cutoff_at == cutoff
        assert diagnostics["market_features_used"] is False
        assert diagnostics["epistemic_sigma_z"] is None


def test_market_consensus_uses_one_available_prematch_quote_per_book(client):
    now = datetime.now(UTC)
    with get_session() as session:
        match = _match(session, now + timedelta(hours=1))
        match_id = match.id
        quotes = [
            (1, now - timedelta(hours=2), "Alpha", "Beta", 1.5, 3.0),
            (1, now - timedelta(hours=1), "Beta", "Alpha", 4.0, 4.0 / 3),
            (2, now - timedelta(hours=1), "Alpha", "Beta", 2.0, 2.0),
            (1, now + timedelta(minutes=30), "Alpha", "Beta", 9.0, 1.125),
            (3, now + timedelta(hours=2), "Alpha", "Beta", 9.0, 1.125),
        ]
        for bookmaker, timestamp, a, b, oa, ob in quotes:
            session.add(OddsSnapshot(
                bookmaker_id=bookmaker, canonical_match_id=match_id, market_type="match_winner",
                raw_team_a=a, raw_team_b=b, odds_a=oa, odds_b=ob, is_live=0, scraped_at=timestamp,
            ))
        session.commit()
    probability = service.fetch_latest_pre_match_market_prob(match_id)
    assert probability == pytest.approx((0.75 + 0.5) / 2)


def test_prediction_history_preserves_recorded_model_identity(client):
    now = datetime.now(UTC)
    with get_session() as session:
        match = _match(session, now + timedelta(days=1))
        match_id = match.id
        session.add(CanonicalPrediction(
            canonical_match_id=match_id, model_name="Hybrid-Operational-Market",
            model_version="exp081-siamese-series-v1-a0.50-t1.00",
            predicted_at=now.isoformat(), prob_a=0.6, prob_b=0.4,
            diagnostics_json=json.dumps({"p_sports": 0.7}),
        ))
        session.commit()
    response = client.get(f"/matches/{match_id}/prediction-history")
    assert response.status_code == 200
    points = response.json()
    assert [(p["model_name"], p["model_version"]) for p in points] == [
        ("Hybrid-Operational-Market", "exp081-siamese-series-v1-a0.50-t1.00")
    ]


def test_batch_hybrid_shrinks_saved_c0_against_available_market_once(client, monkeypatch):
    now = datetime.now(UTC).replace(microsecond=900000)

    class IssuanceClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(service, "datetime", IssuanceClock)
    base_probability = 0.68
    base_identity = {"name": C0_NATIVE.name, "artifact_hashes": {"checkpoint": "native"}}
    base_cutoff = (now - timedelta(days=1)).isoformat()
    base_diagnostics = {
        "model_name": C0_NATIVE.name,
        "model_version": C0_NATIVE.version,
        "feature_version": C0_NATIVE.feature_version,
        "model_identity": base_identity,
        "feature_provenance": {"history_cutoff": base_cutoff},
        "data_cutoff_at": base_cutoff,
        "market_features_used": False,
        "epistemic_sigma_z": None,
        "p_low_a": None,
        "p_low_b": None,
    }
    with get_session() as session:
        match = _match(session, now + timedelta(hours=1))
        match_id = match.id
        session.add(CanonicalPrediction(
            canonical_match_id=match_id, model_name=C0_NATIVE.name, model_version=C0_NATIVE.version,
            predicted_at=(now - timedelta(minutes=5)).isoformat(),
            data_cutoff_at=(now - timedelta(days=1)).isoformat(),
            prob_a=base_probability, prob_b=1.0 - base_probability,
            diagnostics_json=json.dumps(base_diagnostics),
        ))
        for timestamp, oa, ob in [
            (now - timedelta(hours=1), 4 / 3, 4.0),
            (now + timedelta(minutes=30), 9.0, 1.125),
        ]:
            session.add(OddsSnapshot(
                bookmaker_id=1, canonical_match_id=match_id, market_type="match_winner",
                raw_team_a="Alpha", raw_team_b="Beta", odds_a=oa, odds_b=ob,
                is_live=0, scraped_at=timestamp,
            ))
        session.commit()
    expected_probability = PredictionEngine.blend_with_market(
        base_probability, 0.75, get_active_hybrid(),
    )
    batch = service.generate_hybrid_predictions()
    assert len(batch) == 1
    assert batch[0]["prob_a"] == pytest.approx(expected_probability)
    assert batch[0]["diagnostics"]["model_prob_a"] == pytest.approx(base_probability)
    assert batch[0]["diagnostics"]["market_prob_a_avg_no_vig"] == pytest.approx(0.75)
    with get_session() as session:
        row = session.get(CanonicalPrediction, batch[0]["prediction_id"])
        assert row.model_version == get_active_hybrid().hybrid_model_version
        assert datetime.fromisoformat(row.data_cutoff_at) >= now - timedelta(hours=1)
        assert datetime.fromisoformat(row.data_cutoff_at) <= datetime.fromisoformat(row.predicted_at)
        hybrid_diagnostics = json.loads(row.diagnostics_json)
        assert hybrid_diagnostics["model_identity"] == base_identity
        assert hybrid_diagnostics["base_diagnostics"]["data_cutoff_at"] == base_cutoff
        assert hybrid_diagnostics["base_data_cutoff_at"] == base_cutoff


def test_failed_lineup_refresh_preserves_last_published_forecast(client, monkeypatch):
    now = datetime.now(UTC)
    with get_session() as session:
        match = _match(session, now + timedelta(minutes=30))
        match_id = match.id
        match_data = {
            "id": match_id, "start_time_normalized": match.start_time_normalized,
            "previous_roster_a": [], "previous_roster_b": [],
        }
        session.commit()
    c0_features = _native_features(match_id, start=match_data["start_time_normalized"])
    monkeypatch.setattr(service, "check_confirmed_lineup", lambda **kwargs: {"window_valid": True})
    monkeypatch.setattr(service, "build_features_for_match", lambda *args, **kwargs: {
        "features": c0_features, "data_cutoff_at": (now - timedelta(days=1)).isoformat(),
    })
    cutoff = "2026-10-05T00:00:00+00:00"
    monkeypatch.setattr(service, "predict_probability_from_features", lambda *args, **kwargs: (0.61, {
        "model_name": C0_NATIVE.name,
        "model_version": C0_NATIVE.version,
        "feature_version": C0_NATIVE.feature_version,
        "data_cutoff_at": cutoff,
        "model_identity": {"name": C0_NATIVE.name, "artifact_hashes": {"checkpoint": "observed"}},
        "market_features_used": False,
        "epistemic_sigma_z": None,
        "p_low_a": None,
        "p_low_b": None,
    }))
    arguments = {
        "model_name": C0_NATIVE.name,
        "model_version": C0_NATIVE.version,
        "force_re_infer": True,
    }
    result = service.process_confirmed_lineup_update(match_data, **arguments)
    assert result["prediction_id"] is not None
    assert result["prob_a"] == pytest.approx(0.61)
    with get_session() as session:
        prediction = session.get(CanonicalPrediction, result["prediction_id"])
        artifact = session.get(ModelArtifact, prediction.model_artifact_id)
        assert (artifact.model_name, artifact.model_version) == (prediction.model_name, prediction.model_version)

    def missing_artifact(*args, **kwargs):
        raise FileNotFoundError("Unavailable sports checkpoint")

    monkeypatch.setattr(service, "predict_probability_from_features", missing_artifact)
    with pytest.raises(FileNotFoundError):
        service.process_confirmed_lineup_update(match_data, **arguments)
    with get_session() as session:
        active = session.scalars(select(CanonicalPrediction).where(
            CanonicalPrediction.prediction_status == "active",
        )).all()
        assert [row.id for row in active] == [result["prediction_id"]]


def test_ratings_snapshot_cannot_be_mislabeled_as_active_contract(client):
    with pytest.raises(ValueError):
        service.predict_all_upcoming(ratings_version="another-rating-run")




def test_direct_prediction_keeps_native_identity_cutoff_and_other_matches(client, monkeypatch):
    now = datetime.now(UTC)
    cutoff = "2026-10-05T00:00:00+00:00"
    monkeypatch.setattr(
        service,
        "predict_probability_from_features",
        lambda *args, **kwargs: (0.61, {
            "model_name": C0_NATIVE.name,
            "model_version": C0_NATIVE.version,
            "feature_version": C0_NATIVE.feature_version,
            "data_cutoff_at": cutoff,
            "market_features_used": False,
            "model_identity": {"name": C0_NATIVE.name, "artifact_hashes": {"checkpoint": "observed"}},
        }),
    )
    with get_session() as session:
        match = _match(session, now + timedelta(hours=1))
        match_id = match.id
        other = CanonicalMatch(
            canonical_key="audit-gamma-delta", team_a_name="Gamma", team_b_name="Delta",
            normalized_team_a="gamma", normalized_team_b="delta",
            start_time_normalized=(now + timedelta(days=1)).isoformat(), best_of=3,
        )
        session.add(other)
        session.flush()
        other_prediction = CanonicalPrediction(
            canonical_match_id=other.id, model_name=BAYESIAN_SHRUNK_HYBRID.name,
            model_version=BAYESIAN_SHRUNK_HYBRID.version, predicted_at=now.isoformat(),
            data_cutoff_at=cutoff, prob_a=0.6, prob_b=0.4,
        )
        session.add(other_prediction)
        session.flush()
        other_prediction_id = other_prediction.id
        session.commit()
    c0_features = _native_features(
        match_id, start=(now + timedelta(hours=1)).isoformat(),
    )
    monkeypatch.setattr(service, "build_features_for_match", lambda *args, **kwargs: {
        "status": "ready_player", "features": c0_features, "data_cutoff_at": None,
    })
    response = client.post(f"/matches/{match_id}/predict")
    assert response.status_code == 200
    data = response.json()
    assert (data["model_name"], data["model_version"]) == (C0_NATIVE.name, C0_NATIVE.version)
    assert data["prob_a"] == pytest.approx(0.61)
    with get_session() as session:
        row = session.scalars(select(CanonicalPrediction).where(
            CanonicalPrediction.canonical_match_id == match_id,
            CanonicalPrediction.model_name == C0_NATIVE.name,
        )).one()
        artifact = session.get(ModelArtifact, row.model_artifact_id)
        assert artifact is not None
        assert (artifact.model_name, artifact.model_version) == (row.model_name, row.model_version)
        assert row.data_cutoff_at == cutoff
        assert session.get(CanonicalPrediction, other_prediction_id).prediction_status == "active"


def test_direct_prediction_save_failure_rolls_back_request_session(client, monkeypatch):
    from sqlalchemy import event, text
    from betting_app.api.deps import get_db

    now = datetime.now(UTC)
    with get_session() as session:
        match_id = _match(session, now + timedelta(hours=1)).id
        session.commit()
    c0_features = _native_features(match_id, start=(now + timedelta(hours=1)).isoformat())
    monkeypatch.setattr(service, "build_features_for_match", lambda *args, **kwargs: {
        "status": "ready_player", "features": c0_features,
        "data_cutoff_at": (now - timedelta(days=1)).isoformat(),
    })
    monkeypatch.setattr(service, "predict_probability_from_features", lambda *args, **kwargs: (0.61, {
        "model_name": C0_NATIVE.name,
        "model_version": C0_NATIVE.version,
        "feature_version": C0_NATIVE.feature_version,
        "data_cutoff_at": (now - timedelta(days=1)).isoformat(),
        "model_identity": {"name": C0_NATIVE.name, "artifact_hashes": {"checkpoint": "observed"}},
        "market_features_used": False,
    }))
    with get_session() as failing_session:
        def fail_commit(session):
            session.execute(text("SELECT 1 / 0"))

        def request_session():
            yield failing_session

        event.listen(failing_session, "before_commit", fail_commit)
        client.app.dependency_overrides[get_db] = request_session
        try:
            response = client.post(f"/matches/{match_id}/predict")
            assert response.status_code == 503
            assert failing_session.execute(text("SELECT 1")).scalar_one() == 1
        finally:
            client.app.dependency_overrides.pop(get_db, None)
            event.remove(failing_session, "before_commit", fail_commit)
