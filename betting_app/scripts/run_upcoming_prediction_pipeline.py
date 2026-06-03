"""Run the full automatic upcoming prediction pipeline.

This assumes odds/canonical matches, GOL.GG SQLite, ratings (`latest-full`) and
W20 (`w20-latest`) are already refreshed.  It builds upcoming features, predicts
probabilities and generates EV signals with Polish 12% betting tax by default.
"""

from __future__ import annotations

import argparse
from collections import Counter

from betting_app.core.db import init_db, query_df
from betting_app.services.upcoming_inference_service import (
    DEFAULT_FEATURE_VERSION,
    DEFAULT_RATINGS_VERSION,
    DEFAULT_W20_VERSION,
    build_all_upcoming_features,
    generate_model_ev_signals,
)
from betting_app.services.thesis_inference_service import (
    THESIS_HYBRID_ALPHA,
    THESIS_HYBRID_MODEL_NAME,
    THESIS_HYBRID_TEMPERATURE,
    generate_thesis_hybrid_predictions,
    predict_upcoming_with_thesis_model,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-version", default=DEFAULT_FEATURE_VERSION)
    parser.add_argument("--ratings-version", default=DEFAULT_RATINGS_VERSION)
    parser.add_argument("--w20-version", default=DEFAULT_W20_VERSION)
    parser.add_argument("--thesis", action="store_true", help="Run thesis model (Sym-Cal LR-ElasticNet-W20-Binomial).")
    parser.add_argument("--thesis-hybrid", action="store_true", help="Generate thesis+market hybrid predictions.")
    parser.add_argument("--thesis-hybrid-alpha", type=float, default=THESIS_HYBRID_ALPHA)
    parser.add_argument("--thesis-hybrid-temperature", type=float, default=THESIS_HYBRID_TEMPERATURE)
    parser.add_argument("--tax-rate", type=float, default=0.12)
    parser.add_argument("--min-ev", type=float, default=0.0)
    parser.add_argument("--bankroll", type=float, default=100.0)
    parser.add_argument("--include-past", action="store_true")
    parser.add_argument("--include-partial", action="store_true", help="Also predict matches with missing ratings/W20.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--signals-limit", type=int, default=15)
    args = parser.parse_args()

    init_db()
    features = build_all_upcoming_features(
        feature_version=args.feature_version,
        ratings_version=args.ratings_version,
        w20_version=args.w20_version,
        include_past=args.include_past,
        limit=args.limit,
    )
    feature_counts = Counter(row["status"] for row in features)
    print(f"Features: {len(features)} | {dict(feature_counts)}")

    if args.thesis:
        thesis_preds = predict_upcoming_with_thesis_model(
            ratings_version=args.ratings_version,
            w20_version=args.w20_version,
            include_past=args.include_past,
            limit=args.limit,
        )
        print(f"Thesis predictions: {len(thesis_preds)}")

    if args.thesis_hybrid:
        thesis_hybrid_version = f"a{args.thesis_hybrid_alpha:.2f}-t{args.thesis_hybrid_temperature:.2f}"
        thesis_hybrid_preds = generate_thesis_hybrid_predictions(
            alpha=args.thesis_hybrid_alpha,
            temperature=args.thesis_hybrid_temperature,
            hybrid_model_version=thesis_hybrid_version,
        )
        print(f"Thesis hybrid predictions: {len(thesis_hybrid_preds)} | alpha={args.thesis_hybrid_alpha:.2f} T={args.thesis_hybrid_temperature:.2f}")

    ev_model_name = THESIS_HYBRID_MODEL_NAME
    ev_model_version = f"a{args.thesis_hybrid_alpha:.2f}-t{args.thesis_hybrid_temperature:.2f}"

    signals = generate_model_ev_signals(
        model_name=ev_model_name,
        model_version=ev_model_version,
        tax_rate=args.tax_rate,
        min_ev=args.min_ev,
        bankroll=args.bankroll,
    )
    print(f"EV signals: {len(signals)} | tax={args.tax_rate:.2%} | min_ev={args.min_ev:.2%}")
    for row in signals[: args.signals_limit]:
        side = "A" if row["side"] == "a" else "B"
        print(
            f"#{row['canonical_match_id']} {row['match']} | side={side} | {row['bookmaker']} "
            f"odds={row['odds']:.2f} p={row['model_prob']:.3f} EV={row['ev']:.2%} stake={row['stake_suggestion']:.2f}"
        )

    print_readiness_counts()


def print_readiness_counts() -> None:
    counts = query_df(
        """
        SELECT 'canonical_matches' AS table_name, COUNT(*) AS rows FROM canonical_matches
        UNION ALL SELECT 'upcoming_match_features', COUNT(*) FROM upcoming_match_features
        UNION ALL SELECT 'canonical_predictions', COUNT(*) FROM canonical_predictions
        UNION ALL SELECT 'model_ev_signals', COUNT(*) FROM model_ev_signals
        """
    )
    print("\nDB counts:")
    print(counts.to_string(index=False))


if __name__ == "__main__":
    main()
