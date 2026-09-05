"""Run the versioned upcoming prediction pipeline.

The operational baseline uses the immutable ``ratings-v2`` regional contract
and never places bets. EXP-039 remains a separately callable frozen thesis
model.
"""

from __future__ import annotations

import argparse
from collections import Counter

from betting_app.core.db import init_db, query_df
from betting_app.services.thesis_inference_service import (
    THESIS_HYBRID_ALPHA,
    THESIS_HYBRID_MODEL_NAME,
    THESIS_HYBRID_TEMPERATURE,
    generate_thesis_hybrid_predictions,
    predict_upcoming_with_thesis_model,
)
from betting_app.services.upcoming_inference_service import (
    DEFAULT_FEATURE_VERSION,
    DEFAULT_HYBRID_ALPHA,
    DEFAULT_HYBRID_MODEL_NAME,
    DEFAULT_HYBRID_TEMPERATURE,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_VERSION,
    DEFAULT_RATINGS_VERSION,
    DEFAULT_W20_VERSION,
    build_all_upcoming_features,
    generate_hybrid_predictions,
    generate_model_ev_signals,
    predict_all_upcoming,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-version", default=DEFAULT_FEATURE_VERSION)
    parser.add_argument("--ratings-version", default=DEFAULT_RATINGS_VERSION)
    parser.add_argument("--w20-version", default=DEFAULT_W20_VERSION)
    parser.add_argument(
        "--operational-hybrid",
        action="store_true",
        help="Generate the ratings-v2 operational+market hybrid.",
    )
    parser.add_argument(
        "--thesis",
        action="store_true",
        help="Run the frozen Sym-Cal LR-ElasticNet-W20-Binomial model.",
    )
    parser.add_argument(
        "--thesis-hybrid",
        action="store_true",
        help="Generate thesis+market hybrid predictions.",
    )
    parser.add_argument(
        "--thesis-hybrid-alpha", type=float, default=THESIS_HYBRID_ALPHA
    )
    parser.add_argument(
        "--thesis-hybrid-temperature", type=float, default=THESIS_HYBRID_TEMPERATURE
    )
    parser.add_argument("--tax-rate", type=float, default=0.12)
    parser.add_argument("--min-ev", type=float, default=0.0)
    parser.add_argument("--bankroll", type=float, default=100.0)
    parser.add_argument("--include-past", action="store_true")
    parser.add_argument(
        "--include-partial",
        action="store_true",
        help="Also predict matches with missing ratings/W20.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--signals-limit", type=int, default=15)
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Scan and dispatch Value Bet alerts via Discord/Telegram if new EV signals exist.",
    )
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

    operational_preds = predict_all_upcoming(
        feature_version=args.feature_version,
        ratings_version=args.ratings_version,
        include_partial=args.include_partial,
    )
    print(f"Operational predictions: {len(operational_preds)}")

    ev_model_name = DEFAULT_MODEL_NAME
    ev_model_version = DEFAULT_MODEL_VERSION
    if args.operational_hybrid:
        operational_hybrid_version = (
            f"{DEFAULT_MODEL_VERSION}-a{DEFAULT_HYBRID_ALPHA:.2f}"
            f"-t{DEFAULT_HYBRID_TEMPERATURE:.2f}"
        )
        operational_hybrid_preds = generate_hybrid_predictions(
            alpha=DEFAULT_HYBRID_ALPHA,
            temperature=DEFAULT_HYBRID_TEMPERATURE,
            hybrid_model_version=operational_hybrid_version,
        )
        print(
            "Operational hybrid predictions: "
            f"{len(operational_hybrid_preds)} | "
            f"alpha={DEFAULT_HYBRID_ALPHA:.2f} T={DEFAULT_HYBRID_TEMPERATURE:.2f}"
        )
        ev_model_name = DEFAULT_HYBRID_MODEL_NAME
        ev_model_version = operational_hybrid_version

    if args.thesis:
        thesis_preds = predict_upcoming_with_thesis_model(
            ratings_version=args.ratings_version,
            w20_version=args.w20_version,
            include_past=args.include_past,
            limit=args.limit,
        )
        print(f"Thesis predictions: {len(thesis_preds)}")

    if args.thesis_hybrid:
        thesis_hybrid_version = (
            f"a{args.thesis_hybrid_alpha:.2f}"
            f"-t{args.thesis_hybrid_temperature:.2f}"
        )
        thesis_hybrid_preds = generate_thesis_hybrid_predictions(
            alpha=args.thesis_hybrid_alpha,
            temperature=args.thesis_hybrid_temperature,
            hybrid_model_version=thesis_hybrid_version,
        )
        print(
            f"Thesis hybrid predictions: {len(thesis_hybrid_preds)} | "
            f"alpha={args.thesis_hybrid_alpha:.2f} "
            f"T={args.thesis_hybrid_temperature:.2f}"
        )
        ev_model_name = THESIS_HYBRID_MODEL_NAME
        ev_model_version = thesis_hybrid_version

    signals = generate_model_ev_signals(
        model_name=ev_model_name,
        model_version=ev_model_version,
        tax_rate=args.tax_rate,
        min_ev=args.min_ev,
        bankroll=args.bankroll,
    )
    print(
        f"EV signals: {len(signals)} | tax={args.tax_rate:.2%} | "
        f"min_ev={args.min_ev:.2%}"
    )
    for row in signals[: args.signals_limit]:
        side = "A" if row["side"] == "a" else "B"
        print(
            f"#{row['canonical_match_id']} {row['match']} | side={side} | "
            f"{row['bookmaker']} odds={row['odds']:.2f} "
            f"p={row['model_prob']:.3f} EV={row['ev']:.2%} "
            f"stake={row['stake_suggestion']:.2f}"
        )


    if args.notify:
        from betting_app.core.db import get_session
        from betting_app.services.alert_service import scan_and_dispatch_ev_alerts
        print("\nScanning and dispatching Value Bet alerts...")
        with get_session() as session:
            alert_res = scan_and_dispatch_ev_alerts(session)
            print(f"Alerts summary: {alert_res.get('message')}")
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
