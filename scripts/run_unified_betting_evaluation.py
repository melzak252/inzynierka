#!/usr/bin/env python3
"""Run unified EV calibration and backtest report using the canonical UnifiedBettingEngine.

Evaluates predictions against bookmaker odds with guaranteed consistency:
- Uses `src/analysis/unified_evaluation_engine.py` (SSOT)
- Adheres to `bet_qualification_service.is_bet_eligible`
- Outputs both per-bet calibration (zł and %) and bankroll portfolio metrics.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from src.analysis.unified_evaluation_engine import (
    EvaluatedBet,
    UnifiedBettingEngine,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified EV Calibration and Betting Backtest Runner."
    )
    parser.add_argument(
        "--data",
        type=Path,
        help="Path to evaluation dataset (Parquet or CSV). Default uses research best_available_odds.",
    )
    parser.add_argument(
        "--tax-rate",
        type=float,
        default=0.12,
        help="Turnover tax rate (default: 0.12 for Poland, 0.0 for Betclic/international).",
    )
    parser.add_argument(
        "--min-ev",
        type=float,
        default=0.03,
        help="Minimum net expected value threshold (default: 0.03 = +3%%).",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.25,
        help="Bayesian shrinkage weight toward consensus market odds (default: 0.25, 0.0 = pure model).",
    )
    parser.add_argument(
        "--max-odds",
        type=float,
        default=3.50,
        help="Hard odds ceiling to eliminate lottery swings and high-kurtosis variance (default: 3.50).",
    )
    parser.add_argument(
        "--strategy",
        choices=["flat", "quarter_kelly", "fixed_fraction"],
        default="quarter_kelly",
        help="Staking strategy to simulate (default: quarter_kelly).",
    )
    parser.add_argument(
        "--flat-stake",
        type=float,
        default=100.0,
        help="Flat stake in PLN (default: 100.0).",
    )
    parser.add_argument(
        "--initial-bankroll",
        type=float,
        default=1000.0,
        help="Initial bankroll in PLN (default: 1000.0).",
    )
    parser.add_argument(
        "--max-coinflip-market-gap",
        type=float,
        default=0.08,
        help="Maximum model-market disagreement in coinflip corridor [1.80, 2.50] (default: 0.08).",
    )
    parser.add_argument(
        "--bo1-max-odds",
        type=float,
        default=3.00,
        help="Hard odds ceiling on Best-of-1 series to prevent high variance (default: 3.00).",
    )
    parser.add_argument(
        "--no-dynamic-hurdle",
        action="store_true",
        help="Disable low-odds dynamic hurdle penalty.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    data_path = args.data
    if data_path is None:
        root_file = PROJECT_ROOT / "data/research_root.txt"
        if root_file.is_file():
            research_root = Path(root_file.read_text().strip())
            candidate = research_root / "individual-bookmakers-20260911/best_available_odds.parquet"
            if candidate.is_file():
                data_path = candidate
        if data_path is None:
            raise FileNotFoundError("Could not resolve default best_available_odds.parquet. Specify via --data.")

    print(f"Loading data from: {data_path}")
    df = pd.read_parquet(data_path) if data_path.suffix == ".parquet" else pd.read_csv(data_path)

    engine = UnifiedBettingEngine(
        tax_rate=args.tax_rate,
        min_ev_net=args.min_ev,
        dynamic_hurdle=not args.no_dynamic_hurdle,
        max_ev_longshot=0.20,
        longshot_odds_threshold=3.50,
        bo1_max_odds=args.bo1_max_odds,
        max_coinflip_market_gap=args.max_coinflip_market_gap,
        coinflip_min_odds=1.80,
        coinflip_max_odds=2.50,
        uncertainty_required=True,
    )

    qualified_bets: list[EvaluatedBet] = []

    # Detect format: historical best_available_odds vs database export
    if "best_a_open" in df.columns:
        from scipy.special import expit, logit

        for _, r in df.iterrows():
            mid = r.get("golgg_match_id", r.get("match_id"))
            oa = float(r["best_a_open"])
            ob = float(r["best_b_open"])
            ca = float(r["best_a_close"]) if "best_a_close" in r and pd.notna(r["best_a_close"]) else oa
            cb = float(r["best_b_close"]) if "best_b_close" in r and pd.notna(r["best_b_close"]) else ob
            y = int(r["y"])
            bo = int(r["best_of"]) if "best_of" in r and pd.notna(r["best_of"]) else None

            pa_raw = float(r["p_full"])
            inv_a, inv_b = 1.0 / oa, 1.0 / ob
            mkt_a, mkt_b = inv_a / (inv_a + inv_b), inv_b / (inv_a + inv_b)

            if args.alpha > 0.0:
                z_mod_a, z_mkt_a = logit(np.clip(pa_raw, 0.001, 0.999)), logit(np.clip(mkt_a, 0.001, 0.999))
                pa = float(expit((1.0 - args.alpha) * z_mod_a + args.alpha * z_mkt_a))
            else:
                pa = pa_raw
            pb = 1.0 - pa

            if args.max_odds is None or oa <= args.max_odds:
                el_a, bet_a = engine.qualify_quote(
                    match_id=mid, side="team_a", odds=oa, odds_close=ca, prob_model=pa,
                    won=y == 1, bookmaker=str(r.get("best_a_book_open", "unknown")), prob_market_novig=mkt_a,
                    best_of=bo, flat_stake=args.flat_stake,
                )
                if el_a:
                    qualified_bets.append(bet_a)

            if args.max_odds is None or ob <= args.max_odds:
                el_b, bet_b = engine.qualify_quote(
                    match_id=mid, side="team_b", odds=ob, odds_close=cb, prob_model=pb,
                    won=y == 0, bookmaker=str(r.get("best_b_book_open", "unknown")), prob_market_novig=mkt_b,
                    best_of=bo, flat_stake=args.flat_stake,
                )
                if el_b:
                    qualified_bets.append(bet_b)
    else:
        raise ValueError("Unsupported data format; requires best_available_odds format.")

    # Group by match and side
    best_bets: dict[tuple[Any, str], EvaluatedBet] = {}
    for b in qualified_bets:
        key = (b.match_id, b.side)
        if key not in best_bets or b.odds > best_bets[key].odds:
            best_bets[key] = b

    bets_to_sim = list(best_bets.values())
    print(f"Total matches evaluated: {len(df):,}")
    print(f"Qualified bets passing canonical safety gates: {len(bets_to_sim):,}")

    custom_ev_bins = [
        ("0% - 3% EV", 0.00, 0.03),
        ("3% - 6% EV", 0.03, 0.06),
        ("6% - 10% EV", 0.06, 0.10),
        ("> 10% EV", 0.10, 99.00),
    ]

    summary = engine.run_simulation(
        qualified_bets=bets_to_sim,
        strategy=args.strategy,
        initial_bankroll=args.initial_bankroll,
        flat_stake=args.flat_stake,
        ev_bins=custom_ev_bins,
    )

    print("\n" + "=" * 115)
    print(f"WYNIKI Z KANONICZNEGO SILNIKA (STRATEGIA: {summary.strategy.upper()}, PODATEK: {args.tax_rate*100:.1f}%)")
    print("=" * 115)
    print(f"Liczba zakładów:                  {summary.bets_count}")
    print(f"Skuteczność (Win Rate):           {summary.win_rate_pct:.2f}% ({summary.wins_count}/{summary.bets_count})")
    print(f"Średni kurs:                      {summary.avg_odds:.2f}")
    if summary.raw_ev_pct is not None:
        print(f"Surowe (niekalibrowane) EV / bet: {summary.raw_ev_pct:+.2f}%")
    print(f"Oczekiwane EV / bet (%):          {summary.expected_ev_pct:+.2f}%")
    print(f"Oczekiwany zysk na 1 bet:         {summary.expected_profit_per_bet:+.2f} zł")
    print(f"Rzeczywiste EV / bet (ROI %):     {summary.realized_ev_pct:+.2f}%")
    print(f"Rzeczywisty zysk na 1 bet:        {summary.realized_profit_per_bet:+.2f} zł")
    print(f"Błąd kalibracji na 1 bet:         {summary.calibration_gap_pln:+.2f} zł")
    print(f"Całkowity obrót:                  {summary.total_staked:,.2f} zł")
    print(f"Zysk całkowity:                   {summary.total_pnl:+,.2f} zł")
    print(f"Maksymalny drawdown:              {summary.max_drawdown_pct:.2f}% ({summary.max_drawdown_pln:,.2f} zł)")
    if summary.median_clv_pct is not None:
        print(f"Mediana CLV:                      {summary.median_clv_pct:+.2f}%")

    print("\n" + "-" * 115)
    print("KALIBRACJA WG KOSZYKÓW EV (OCZEKIWANY VS RZECZYWISTY ZYSK NA 1 BET)")
    print("-" * 115)
    rows_ev = []
    for b in summary.bins:
        rows_ev.append({
            "Koszyk EV": b.label,
            "Bety": b.bets_count,
            "Win Rate": f"{b.win_rate_pct:.1f}%",
            "Śr. Kurs": f"{b.avg_odds:.2f}",
            "Oczekiwane EV": f"{b.expected_ev_pct:+.2f}%",
            "Oczekiwany zysk/bet": f"{b.expected_profit_per_bet:+.2f} zł",
            "Rzeczywiste EV": f"{b.realized_ev_pct:+.2f}%",
            "Rzeczywisty zysk/bet": f"{b.realized_profit_per_bet:+.2f} zł",
            "Błąd (zł/bet)": f"{b.calibration_gap_pln:+.2f} zł",
            "Realizacja": f"{b.ev_realization_rate_pct:.1f}%",
        })
    if rows_ev:
        print(pd.DataFrame(rows_ev).to_string(index=False))

    print("\n" + "-" * 115)
    print("ROZBICIE WG PRZEDZIAŁÓW KURSOWYCH")
    print("-" * 115)
    rows_odds = []
    for ob in summary.by_odds_bracket:
        rows_odds.append({
            "Przedział kursowy": ob.label,
            "Bety": ob.bets_count,
            "Win Rate": f"{ob.win_rate_pct:.1f}%",
            "Śr. Kurs": f"{ob.avg_odds:.2f}",
            "Oczekiwane EV": f"{ob.expected_ev_pct:+.2f}%",
            "Oczekiwany zysk/bet": f"{ob.expected_profit_per_bet:+.2f} zł",
            "Rzeczywiste EV": f"{ob.realized_ev_pct:+.2f}%",
            "Rzeczywisty zysk/bet": f"{ob.realized_profit_per_bet:+.2f} zł",
            "Błąd (zł/bet)": f"{ob.calibration_gap_pln:+.2f} zł",
            "Mediana CLV": f"{ob.median_clv_pct:+.2f}%" if ob.median_clv_pct is not None else "N/A",
        })
    if rows_odds:
        print(pd.DataFrame(rows_odds).to_string(index=False))


if __name__ == "__main__":
    main()
