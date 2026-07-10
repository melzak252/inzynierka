from __future__ import annotations

from sqlalchemy import text

from betting_app.core.db import get_session, init_db
from betting_app.ml.config import BacktestConfig, StakingConfig
from betting_app.ml.pipelines.evaluation import EvaluationPipelineConfig, run_evaluation_pipeline
from betting_app.ml.registry import (
    ModelVersionRecord,
    get_model_version,
    list_model_versions,
    promote_model_version,
    register_model_version,
)
from betting_app.ml.registry.gates import PromotionGateConfig, evaluate_market_baseline_gate


def test_model_registry_register_and_promote(client):
    del client
    with get_session() as session:
        register_model_version(
            ModelVersionRecord(
                model_name="TestModel",
                model_version="v1",
                status="candidate",
                metrics={"model_log_loss": 0.6},
            ),
            session=session,
        )
        register_model_version(
            ModelVersionRecord(
                model_name="TestModel",
                model_version="v2",
                status="shadow",
                metrics={"model_log_loss": 0.5},
            ),
            session=session,
        )
        promote_model_version("TestModel", "v2", session=session)

        v1 = get_model_version("TestModel", "v1", session=session)
        v2 = get_model_version("TestModel", "v2", session=session)
        production = list_model_versions(status="production", session=session)

    assert v1 is not None
    assert v1["status"] == "candidate"
    assert v2 is not None
    assert v2["status"] == "production"
    assert v2["metrics"] == {"model_log_loss": 0.5}
    assert [row["model_version"] for row in production] == ["v2"]


def test_promotion_gate_compares_model_against_market():
    decision = evaluate_market_baseline_gate(
        {
            "bets": 10,
            "comparison_observations": 10,
            "roi": 0.1,
            "model_log_loss": 0.4,
            "market_log_loss": 0.5,
            "model_brier": 0.15,
            "market_brier": 0.2,
        },
        PromotionGateConfig(min_bets=5, min_comparison_observations=5, min_roi=0.0),
    )
    assert decision.passed
    assert decision.reasons == []

    failed = evaluate_market_baseline_gate(
        {
            "bets": 2,
            "comparison_observations": 2,
            "roi": -0.1,
            "model_log_loss": 0.7,
            "market_log_loss": 0.5,
            "model_brier": 0.3,
            "market_brier": 0.2,
        },
        PromotionGateConfig(min_bets=5, min_comparison_observations=5, min_roi=0.0),
    )
    assert not failed.passed
    assert any("not enough bets" in reason for reason in failed.reasons)
    assert any("logloss worse" in reason for reason in failed.reasons)


def test_evaluation_pipeline_logs_run_and_candidate(client):
    del client
    init_db()
    with get_session() as session:
        session.execute(text("""
            INSERT INTO canonical_matches (
                id, canonical_key, team_a_name, team_b_name, normalized_team_a, normalized_team_b,
                start_time_normalized, league, status, winner_side
            ) VALUES
            (501, 'm501', 'A', 'B', 'a', 'b', '2026-01-10T12:00:00+00:00', 'LCK', 'finished', 'team_a'),
            (502, 'm502', 'C', 'D', 'c', 'd', '2026-01-11T12:00:00+00:00', 'LCK', 'finished', 'team_b')
        """))
        session.execute(text("""
            INSERT INTO canonical_predictions (
                id, canonical_match_id, model_name, model_version, predicted_at,
                prob_a, prob_b, prediction_status
            ) VALUES
            (1001, 501, 'PipelineModel', 'v1', '2026-01-10T09:00:00+00:00', 0.70, 0.30, 'stale'),
            (1002, 502, 'PipelineModel', 'v1', '2026-01-11T09:00:00+00:00', 0.40, 0.60, 'stale')
        """))
        session.execute(text("""
            INSERT INTO odds_snapshots (
                id, bookmaker_id, canonical_match_id, odds_a, odds_b, scraped_at,
                raw_team_a, raw_team_b
            ) VALUES
            (2001, 2, 501, 2.10, 1.80, '2026-01-10T10:00:00+00:00', 'A', 'B'),
            (2002, 2, 502, 1.90, 2.05, '2026-01-11T10:00:00+00:00', 'C', 'D')
        """))
        session.commit()

        result = run_evaluation_pipeline(
            EvaluationPipelineConfig(
                model_name="PipelineModel",
                model_version="v1",
                days_back=None,
                include_stale=True,
                backtest=BacktestConfig(
                    bankroll_start=100.0,
                    min_ev=0.0,
                    staking=StakingConfig(strategy="fixed", fixed_stake=10.0),
                ),
                promotion_gate=PromotionGateConfig(min_bets=1, min_comparison_observations=1),
            ),
            session=session,
        )
        registered = get_model_version("PipelineModel", "v1", session=session)
        rows = session.execute(text("SELECT COUNT(*) FROM ml_evaluation_runs")).scalar_one()

    assert result.metrics["predictions_loaded"] == 2
    assert result.metrics["labels_loaded"] == 2
    assert result.metrics["odds_quotes_loaded"] == 2
    assert result.metrics["comparison_observations"] == 2
    assert result.evaluation_run_id
    assert registered is not None
    assert registered["metrics"]["predictions_loaded"] == 2
    assert rows == 1
