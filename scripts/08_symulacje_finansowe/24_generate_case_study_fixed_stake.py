"""Generate fixed-stake comparison artifacts for case study chapter 7.

This script recalculates the educational fixed-stake section using the frozen
static alpha/temperature family defined in Chapter 6. It intentionally uses a
simple stake of 5 units to isolate bet-selection quality before bankroll-scaled
staking policies are introduced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "docs" / "assets" / "hybrid_point7" / "hybrid_model_input_predictions.csv"
OUTPUT_DIR = ROOT / "docs" / "assets" / "financial_point8"

TAX_FACTOR = 0.88
EV_THRESHOLD = 0.05
START_BANKROLL = 100.0
FIXED_STAKE = 5.0
START_DATE = "2024-01-01"


@dataclass(frozen=True)
class Candidate:
    """Static candidate configuration for fixed-stake simulation.

    Attributes:
        name: Human-readable candidate name.
        alpha: Hybrid alpha value. ``None`` for Market Avg Close.
        temperature: Temperature applied to the sport model probability.
        market: Market probability source: ``open`` or ``close``.
        execution: Odds execution source: ``best_open`` or ``avg_close``.
    """

    name: str
    alpha: float | None
    temperature: float
    market: str
    execution: str


def apply_temperature(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    """Apply binary temperature scaling to probabilities.

    Args:
        probabilities: Raw probability values.
        temperature: Temperature value.

    Returns:
        Temperature-scaled probabilities.
    """

    clipped = np.clip(probabilities.astype(float), 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped))
    return 1.0 / (1.0 + np.exp(-logits / temperature))


def load_dataset() -> pd.DataFrame:
    """Load and prepare the 2024+ operational dataset.

    Returns:
        Filtered match-level DataFrame.
    """

    df = pd.read_csv(INPUT_PATH, parse_dates=["date"])
    required = ["prob_model", "prob_market_open", "best_open_t1", "best_open_t2", "t1_win"]
    df = df.dropna(subset=required).copy()
    return df[df["date"] >= pd.Timestamp(START_DATE)].sort_values("date").reset_index(drop=True)


def candidate_probability(df: pd.DataFrame, candidate: Candidate) -> np.ndarray:
    """Build team-1 win probability for a candidate.

    Args:
        df: Input data.
        candidate: Candidate configuration.

    Returns:
        Probability vector for team 1.
    """

    if candidate.market == "close":
        return df["prob_market_close"].to_numpy(dtype=float)

    market = df["prob_market_open"].to_numpy(dtype=float)
    if candidate.alpha == 0.0:
        return market
    model = apply_temperature(df["prob_model"].to_numpy(dtype=float), candidate.temperature)
    if candidate.alpha == 1.0:
        return model
    return candidate.alpha * model + (1.0 - candidate.alpha) * market


def execution_odds(row: pd.Series, execution: str) -> tuple[float, float]:
    """Return team-1 and team-2 execution odds.

    Args:
        row: Match row.
        execution: Execution source name.

    Returns:
        Tuple of odds for team 1 and team 2.
    """

    if execution == "avg_close":
        return float(row["avg_odds_home"]), float(row["avg_odds_away"])
    return float(row["best_open_t1"]), float(row["best_open_t2"])


def simulate_fixed_stake(
    df: pd.DataFrame,
    probabilities: np.ndarray,
    candidate: Candidate,
) -> tuple[dict[str, float | str], pd.DataFrame]:
    """Simulate fixed stake bankroll for one candidate.

    Args:
        df: Input match data.
        probabilities: Team-1 probabilities aligned to ``df``.
        candidate: Candidate configuration.

    Returns:
        Summary row and bankroll history.
    """

    bankroll = START_BANKROLL
    peak = START_BANKROLL
    max_drawdown = 0.0
    total_staked = 0.0
    profit = 0.0
    bets = 0
    wins = 0
    history: list[dict[str, float | str]] = []

    for probability, (_, row) in zip(probabilities, df.iterrows()):
        odds_t1, odds_t2 = execution_odds(row, candidate.execution)
        if pd.isna(probability) or pd.isna(odds_t1) or pd.isna(odds_t2):
            history.append({"date": row["date"], "bankroll": bankroll, "variant": candidate.name})
            continue
        if bankroll < FIXED_STAKE:
            history.append({"date": row["date"], "bankroll": bankroll, "variant": candidate.name})
            continue

        ev_t1 = float(probability) * odds_t1 * TAX_FACTOR - 1.0
        ev_t2 = (1.0 - float(probability)) * odds_t2 * TAX_FACTOR - 1.0
        if max(ev_t1, ev_t2) <= EV_THRESHOLD:
            history.append({"date": row["date"], "bankroll": bankroll, "variant": candidate.name})
            continue

        if ev_t1 >= ev_t2:
            odds = odds_t1
            won = int(row["t1_win"]) == 1
        else:
            odds = odds_t2
            won = int(row["t1_win"]) == 0

        pnl = FIXED_STAKE * (odds * TAX_FACTOR - 1.0) if won else -FIXED_STAKE
        bankroll += pnl
        total_staked += FIXED_STAKE
        profit += pnl
        bets += 1
        wins += int(won)
        peak = max(peak, bankroll)
        max_drawdown = max(max_drawdown, (peak - bankroll) / peak * 100.0)
        history.append({"date": row["date"], "bankroll": bankroll, "variant": candidate.name})

    return {
        "variant": candidate.name,
        "final_bankroll": bankroll,
        "yield_pct": profit / total_staked * 100.0 if total_staked else 0.0,
        "maxdd_pct": max_drawdown,
        "bets": float(bets),
        "win_rate_pct": wins / bets * 100.0 if bets else 0.0,
    }, pd.DataFrame(history)


def save_plot(history: pd.DataFrame, summary: pd.DataFrame) -> None:
    """Save bankroll comparison plot.

    Args:
        history: Bankroll history for all variants.
        summary: Summary metrics for all variants.
    """

    colors = {
        "Market Avg Open": "#6B7280",
        "Market Avg Close": "#111827",
        "Hybrid Defensive α=0.30 T=0.60": "#60A5FA",
        "Hybrid Financial α=0.48 T=0.60": "#10B981",
        "Hybrid Probabilistic α=0.62 T=0.80": "#F59E0B",
        "Model Only α=1.00 T=1.00": "#EF4444",
    }
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axis = plt.subplots(figsize=(12.5, 6.4))
    for variant, group in history.groupby("variant", sort=False):
        axis.plot(
            pd.to_datetime(group["date"]),
            group["bankroll"],
            label=variant,
            linewidth=2.2,
            color=colors.get(variant),
        )

    axis.set_title("Fixed stake 5: bankroll dla stałych kandydatów", weight="bold", pad=16)
    axis.set_ylabel("Bankroll")
    axis.set_xlabel("Data")
    axis.spines[["top", "right"]].set_visible(False)
    axis.grid(alpha=0.25)
    axis.legend(loc="upper left", frameon=True, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "case_study_fixed_stake_comparison.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """Generate fixed-stake artifacts."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_dataset()
    candidates = [
        Candidate("Market Avg Open", 0.0, 1.0, "open", "best_open"),
        Candidate("Market Avg Close", None, 1.0, "close", "avg_close"),
        Candidate("Hybrid Defensive α=0.30 T=0.60", 0.30, 0.60, "open", "best_open"),
        Candidate("Hybrid Financial α=0.48 T=0.60", 0.48, 0.60, "open", "best_open"),
        Candidate("Hybrid Probabilistic α=0.62 T=0.80", 0.62, 0.80, "open", "best_open"),
        Candidate("Model Only α=1.00 T=1.00", 1.0, 1.0, "open", "best_open"),
    ]

    summaries = []
    histories = []
    for candidate in candidates:
        probability = candidate_probability(df, candidate)
        summary, history = simulate_fixed_stake(df, probability, candidate)
        summaries.append(summary)
        histories.append(history)

    summary_df = pd.DataFrame(summaries)
    history_df = pd.concat(histories, ignore_index=True)
    summary_df.to_csv(OUTPUT_DIR / "case_study_fixed_stake_table.csv", index=False)
    history_df.to_csv(OUTPUT_DIR / "case_study_fixed_stake_history.csv", index=False)
    save_plot(history_df, summary_df)

    printable = summary_df.copy()
    printable["variant"] = printable["variant"].str.replace("α", "alpha", regex=False)
    print(printable.to_string(index=False))


if __name__ == "__main__":
    main()
