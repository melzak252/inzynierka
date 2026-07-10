"""Historical model evaluation pipeline.

This pipeline evaluates existing predictions from `canonical_predictions`
against historical match results and collected bookmaker odds. It is the first
production-oriented building block for regular model testing and future model
promotion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from betting_app.core.db import get_session
from betting_app.ml.backtesting.comparison import compare_predictions_to_market
from betting_app.ml.backtesting.engine import run_backtest
from betting_app.ml.backtesting.loaders import load_finished_match_labels, load_odds_quotes, load_predictions
from betting_app.ml.config import BacktestConfig
from betting_app.ml.registry.gates import PromotionDecision, PromotionGateConfig, evaluate_market_baseline_gate
from betting_app.ml.registry.repository import (
    EvaluationRunRecord,
    ModelVersionRecord,
    record_evaluation_run,
    register_model_version,
)


@dataclass(frozen=True)
class EvaluationPipelineConfig:
    model_name: str
    model_version: str
    days_back: int | None = 365
    include_stale: bool = True
    latest_per_match: bool = True
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    promotion_gate: PromotionGateConfig = field(default_factory=PromotionGateConfig)
    register_candidate: bool = True
    run_type: str = "historical_backtest"


@dataclass(frozen=True)
class EvaluationPipelineResult:
    metrics: dict[str, Any]
    decision: PromotionDecision
    evaluation_run_id: str


def run_evaluation_pipeline(
    config: EvaluationPipelineConfig,
    session: Session | None = None,
) -> EvaluationPipelineResult:
    """Run historical backtest + market comparison + registry logging."""
    own_session = session is None
    sess = session or get_session()
    try:
        labels = load_finished_match_labels(days_back=config.days_back, session=sess)
        label_ids = {label.canonical_match_id for label in labels}
        predictions = [
            prediction
            for prediction in load_predictions(
                model_name=config.model_name,
                model_version=config.model_version,
                only_active=not config.include_stale,
                latest_per_match=config.latest_per_match,
                session=sess,
            )
            if prediction.canonical_match_id in label_ids
        ]
        odds = load_odds_quotes(canonical_match_ids=label_ids, session=sess)

        backtest = run_backtest(predictions, labels, odds, config.backtest)
        comparison = compare_predictions_to_market(predictions, labels, odds, config.backtest)

        metrics: dict[str, Any] = {
            "predictions_loaded": len(predictions),
            "labels_loaded": len(labels),
            "odds_quotes_loaded": len(odds),
            "matches_seen": backtest.matches_seen,
            "matches_bet": backtest.matches_bet,
            "bets": len(backtest.bets),
            "bankroll_start": round(backtest.bankroll_start, 2),
            "bankroll_end": round(backtest.bankroll_end, 2),
            "total_staked": round(backtest.total_staked, 2),
            "total_profit": round(backtest.total_profit, 2),
            "roi": round(backtest.roi, 6),
            "hit_rate": round(backtest.hit_rate, 6),
            "max_drawdown": round(backtest.max_drawdown, 2),
            "comparison_observations": comparison.observations,
            "model_log_loss": round(comparison.model_log_loss, 6),
            "market_log_loss": round(comparison.market_log_loss, 6),
            "model_brier": round(comparison.model_brier, 6),
            "market_brier": round(comparison.market_brier, 6),
            "model_accuracy": round(comparison.model_accuracy, 6),
            "market_accuracy": round(comparison.market_accuracy, 6),
        }

        decision = evaluate_market_baseline_gate(metrics, config.promotion_gate)
        if config.register_candidate:
            register_model_version(
                ModelVersionRecord(
                    model_name=config.model_name,
                    model_version=config.model_version,
                    status="shadow" if decision.passed else "candidate",
                    metrics=metrics,
                    notes="Auto-registered by historical evaluation pipeline",
                ),
                session=sess,
            )

        run = record_evaluation_run(
            EvaluationRunRecord(
                model_name=config.model_name,
                model_version=config.model_version,
                run_type=config.run_type,
                status="completed",
                config=asdict(config),
                metrics={**metrics, "promotion_gate_passed": decision.passed, "promotion_gate_reasons": decision.reasons},
                notes="Historical model-vs-bookmaker evaluation",
            ),
            session=sess,
        )
        return EvaluationPipelineResult(metrics=metrics, decision=decision, evaluation_run_id=run.id)
    finally:
        if own_session:
            sess.close()
