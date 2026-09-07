#!/usr/bin/env python3
"""CLI runner for the standard walk-forward model benchmark.

Evaluates a candidate prediction column against ground truth and an optional
comparative baseline according to the AGENTS.md promotion benchmark.

Example:
    .venv/bin/python scripts/run_model_benchmark.py \
      --data data/golgg_y_predicts.csv \
      --candidate-col player_elo \
      --target-col y_true \
      --date-col date \
      --min-date 2024-01-01 \
      --model-name "Player-Elo" \
      --model-version "v1.0"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.analysis.model_benchmark import run_model_benchmark

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run unified model evaluation and promotion benchmark."
    )
    parser.add_argument("--data", required=True, help="Path to CSV or Parquet evaluation dataset.")
    parser.add_argument("--candidate-col", required=True, help="Candidate model prediction column.")
    parser.add_argument("--baseline-col", default=None, help="Comparative baseline prediction column.")
    parser.add_argument("--target-col", default="y_true", help="Ground truth binary label column (default: y_true).")
    parser.add_argument("--date-col", default="date", help="Match date column for temporal blocks (default: date).")
    parser.add_argument("--min-date", default="2024-01-01", help="Start date for the evaluation cohort (default: 2024-01-01).")
    parser.add_argument("--max-date", default=None, help="End date for the evaluation cohort.")
    parser.add_argument("--model-name", default="Candidate Model", help="Human-readable model name.")
    parser.add_argument("--model-version", default="v1.0", help="Model version string.")
    parser.add_argument("--baseline-name", default="Frozen Baseline", help="Baseline name.")
    parser.add_argument("--bon-col", default=None, help="Series format column (Bo1/Bo3/Bo5).")
    parser.add_argument("--tier-col", default=None, help="League/tournament tier column.")
    parser.add_argument("--odds-col", default=None, help="Bookmaker odds column.")
    parser.add_argument("--disagreement-col", default=None, help="Internal disagreement column.")
    parser.add_argument("--bootstraps", type=int, default=5000, help="Number of monthly bootstrap resamples (default: 5000).")
    parser.add_argument("--output-json", default=None, help="Optional path to save JSON benchmark output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_path = Path(args.data)
    if not data_path.exists():
        sys.exit(f"Error: Data file not found at {data_path}")

    if data_path.suffix == ".parquet":
        df = pd.read_parquet(data_path)
    else:
        df = pd.read_csv(data_path)

    if args.min_date and args.date_col in df.columns:
        df = df[df[args.date_col].astype(str) >= args.min_date]
    if args.max_date and args.date_col in df.columns:
        df = df[df[args.date_col].astype(str) <= args.max_date]

    print(f"Loaded {len(df):,} evaluation rows from {data_path} (filtered to >= {args.min_date})")

    report = run_model_benchmark(
        data=df,
        candidate_prob_col=args.candidate_col,
        baseline_prob_col=args.baseline_col,
        target_col=args.target_col,
        date_col=args.date_col,
        model_name=args.model_name,
        model_version=args.model_version,
        baseline_name=args.baseline_name,
        bon_col=args.bon_col,
        tier_col=args.tier_col,
        odds_col=args.odds_col,
        disagreement_col=args.disagreement_col,
        n_bootstraps=args.bootstraps,
    )

    markdown = report.format_markdown()
    print("\n" + markdown)

    if args.output_json:
        import json
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"\nSaved benchmark JSON to {out_path}")


if __name__ == "__main__":
    main()
