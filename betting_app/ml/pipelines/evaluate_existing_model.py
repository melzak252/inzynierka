"""CLI entrypoint for the historical evaluation pipeline.

Docker-friendly example:

    python -m betting_app.ml.pipelines.evaluate_existing_model \
      --model-name Sym-Cal LR-ElasticNet-W20-Binomial \
      --model-version exp-039 \
      --json
"""

from __future__ import annotations

import argparse
import json

from betting_app.ml.config import BacktestConfig, StakingConfig
from betting_app.ml.pipelines.evaluation import EvaluationPipelineConfig, run_evaluation_pipeline
from betting_app.ml.registry.gates import PromotionGateConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run model-vs-bookmaker historical evaluation and log it to ML registry")
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--days-back", type=int, default=365)
    parser.add_argument("--active-only", action="store_true", help="Use only active predictions instead of stale historical predictions")
    parser.add_argument("--all-predictions-per-match", action="store_true")
    parser.add_argument("--bankroll", type=float, default=1_000.0)
    parser.add_argument("--min-ev", type=float, default=0.0)
    parser.add_argument("--staking", choices=["fixed", "percent", "fractional_kelly"], default="fractional_kelly")
    parser.add_argument("--kelly-fraction", type=float, default=0.25)
    parser.add_argument("--fixed-stake", type=float, default=10.0)
    parser.add_argument("--max-bets-per-match", type=int, default=1)
    parser.add_argument("--min-gate-bets", type=int, default=50)
    parser.add_argument("--min-gate-observations", type=int, default=50)
    parser.add_argument("--min-gate-roi", type=float, default=None)
    parser.add_argument("--no-register", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_evaluation_pipeline(
        EvaluationPipelineConfig(
            model_name=args.model_name,
            model_version=args.model_version,
            days_back=args.days_back,
            include_stale=not args.active_only,
            latest_per_match=not args.all_predictions_per_match,
            backtest=BacktestConfig(
                bankroll_start=args.bankroll,
                min_ev=args.min_ev,
                staking=StakingConfig(
                    strategy=args.staking,
                    fixed_stake=args.fixed_stake,
                    kelly_fraction=args.kelly_fraction,
                ),
                max_bets_per_match=args.max_bets_per_match,
            ),
            promotion_gate=PromotionGateConfig(
                min_bets=args.min_gate_bets,
                min_comparison_observations=args.min_gate_observations,
                min_roi=args.min_gate_roi,
            ),
            register_candidate=not args.no_register,
        )
    )
    payload = {
        **result.metrics,
        "evaluation_run_id": result.evaluation_run_id,
        "promotion_gate_passed": result.decision.passed,
        "promotion_gate_reasons": result.decision.reasons,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("Historical evaluation pipeline")
        for key, value in payload.items():
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
