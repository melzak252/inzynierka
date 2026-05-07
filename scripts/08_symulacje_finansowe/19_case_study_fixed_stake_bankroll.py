"""Create fixed-stake bankroll chart for the case-study candidates.

The chart is intentionally simpler than the full financial validation suite. It
compares the few variants used in the case-study narrative under the same flat
staking rule, so the reader can compare path shape rather than only final
tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HYBRID_DIR = PROJECT_ROOT / "docs" / "assets" / "hybrid_point7"
FINANCIAL_DIR = PROJECT_ROOT / "docs" / "assets" / "financial_point8"
INPUT_PATH = HYBRID_DIR / "hybrid_model_input_predictions.csv"
ELO_ALPHA_PATH = HYBRID_DIR / "hybrid_elo_alpha_predictions.csv"

OUTPUT_HISTORY = FINANCIAL_DIR / "case_study_fixed_stake_bankroll_history.csv"
OUTPUT_SUMMARY = FINANCIAL_DIR / "case_study_fixed_stake_bankroll_summary.csv"
OUTPUT_FIGURE = FINANCIAL_DIR / "case_study_fixed_stake_bankroll_2024.png"

INITIAL_BANKROLL = 100.0
FIXED_STAKE = 10.0
TAX_RATE = 0.12
SLIPPAGE = 0.00
EV_THRESHOLD = 0.05
SCOPE_START_DATE = "2024-01-01"


@dataclass(frozen=True)
class Candidate:
    """Definition of a probability candidate for the chart.

    Attributes:
        name: Human-readable variant name.
        probability: Team 1 win probability array.
        odds_t1_column: Column used as executable odds for team 1.
        odds_t2_column: Column used as executable odds for team 2.
    """

    name: str
    probability: np.ndarray
    odds_t1_column: str = "best_open_t1"
    odds_t2_column: str = "best_open_t2"


def logit(probability: np.ndarray) -> np.ndarray:
    """Convert probabilities to logits.

    Args:
        probability: Probability values.

    Returns:
        Logit values after numerical clipping.
    """

    clipped = np.clip(probability, 1e-6, 1 - 1e-6)
    return np.log(clipped / (1 - clipped))


def sigmoid(value: np.ndarray) -> np.ndarray:
    """Convert logits to probabilities.

    Args:
        value: Logit values.

    Returns:
        Probability values.
    """

    return 1 / (1 + np.exp(-value))


def apply_temperature(probability: np.ndarray, temperature: float) -> np.ndarray:
    """Apply temperature scaling to probabilities.

    Args:
        probability: Base probability values.
        temperature: Temperature value. Values below one sharpen probabilities.

    Returns:
        Temperature-scaled probability values.
    """

    return sigmoid(logit(probability) / temperature)


def choose_bet(
    row: pd.Series,
    probability: float,
    odds_t1_column: str,
    odds_t2_column: str,
) -> tuple[str | None, float, float, float]:
    """Choose a bet side using EV threshold and best opening odds.

    Args:
        row: Match row with odds and result.
        probability: Team 1 win probability.
        odds_t1_column: Column used as executable odds for team 1.
        odds_t2_column: Column used as executable odds for team 2.

    Returns:
        Tuple with side, selected probability, raw odds, and selected EV.
    """

    odds_t1 = row[odds_t1_column]
    odds_t2 = row[odds_t2_column]
    if pd.isna(odds_t1) or pd.isna(odds_t2):
        return None, 0.0, 0.0, 0.0

    prob_t1 = float(probability)
    prob_t2 = 1.0 - prob_t1
    ev_t1 = prob_t1 * odds_t1 * (1 - TAX_RATE) - 1
    ev_t2 = prob_t2 * odds_t2 * (1 - TAX_RATE) - 1

    if ev_t1 > ev_t2 and ev_t1 > EV_THRESHOLD:
        return "t1", prob_t1, float(odds_t1), float(ev_t1)
    if ev_t2 > EV_THRESHOLD:
        return "t2", prob_t2, float(odds_t2), float(ev_t2)
    return None, 0.0, 0.0, 0.0


def simulate_fixed_stake(data: pd.DataFrame, candidate: Candidate) -> tuple[pd.DataFrame, dict[str, float | str | int]]:
    """Simulate fixed-stake bankroll path for one candidate.

    Args:
        data: Chronologically sorted match data.
        candidate: Candidate probabilities aligned with ``data``.

    Returns:
        History frame and summary dictionary.
    """

    bankroll = INITIAL_BANKROLL
    peak = INITIAL_BANKROLL
    max_drawdown = 0.0
    total_staked = 0.0
    total_profit = 0.0
    bets = 0
    wins = 0
    rows: list[dict[str, float | str | int | bool]] = []

    for idx, (_, row) in enumerate(data.iterrows()):
        side, selected_prob, raw_odds, selected_ev = choose_bet(
            row,
            float(candidate.probability[idx]),
            candidate.odds_t1_column,
            candidate.odds_t2_column,
        )
        stake = 0.0
        profit = 0.0
        is_win = False

        if side is not None and bankroll >= FIXED_STAKE:
            stake = FIXED_STAKE
            execution_odds = raw_odds * (1 - SLIPPAGE)
            is_win = bool(row["y_true"] == 1) if side == "t1" else bool(row["y_true"] == 0)
            if is_win:
                profit = stake * (execution_odds * (1 - TAX_RATE) - 1)
                wins += 1
            else:
                profit = -stake
            bankroll += profit
            total_staked += stake
            total_profit += profit
            bets += 1

        peak = max(peak, bankroll)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - bankroll) / peak * 100)

        rows.append(
            {
                "date": row["date"],
                "candidate": candidate.name,
                "match_index": idx,
                "bankroll": bankroll,
                "stake": stake,
                "profit": profit,
                "selected_ev": selected_ev,
                "bet_placed": int(stake > 0),
                "win": int(is_win),
            }
        )

    yield_pct = total_profit / total_staked * 100 if total_staked > 0 else 0.0
    summary = {
        "candidate": candidate.name,
        "final_bankroll": bankroll,
        "roi_pct": (bankroll - INITIAL_BANKROLL) / INITIAL_BANKROLL * 100,
        "yield_pct": yield_pct,
        "max_drawdown_pct": max_drawdown,
        "bets": bets,
        "win_rate_pct": wins / bets * 100 if bets else 0.0,
        "total_staked": total_staked,
        "total_profit": total_profit,
    }
    return pd.DataFrame(rows), summary


def load_dynamic_alpha_probability(data: pd.DataFrame, model_t060: np.ndarray) -> np.ndarray:
    """Load Elo-like dynamic alpha and combine it with fixed temperature.

    The case-study chart intentionally isolates one adaptive mechanism:
    alpha changes over time, while the metamodel temperature is fixed at 0.60.

    Args:
        data: Base match data with ``golgg_match_id`` and ``date``.
        model_t060: Temperature-scaled metamodel probabilities.

    Returns:
        Dynamic-alpha hybrid probabilities aligned to ``data``.
    """

    dynamic = pd.read_csv(ELO_ALPHA_PATH, parse_dates=["date"])
    dynamic = dynamic[["date", "golgg_match_id", "elo_alpha"]]
    merged = data[["date", "golgg_match_id"]].merge(
        dynamic,
        on=["date", "golgg_match_id"],
        how="left",
        validate="one_to_one",
    )
    if merged["elo_alpha"].isna().any():
        missing = int(merged["elo_alpha"].isna().sum())
        raise ValueError(f"Missing dynamic alpha values for {missing} rows")

    alpha = merged["elo_alpha"].to_numpy(dtype=float)
    market_open = data["prob_market_open"].to_numpy(dtype=float)
    return alpha * model_t060 + (1 - alpha) * market_open


def build_candidates(data: pd.DataFrame) -> list[Candidate]:
    """Build candidate probabilities used in the case study.

    Args:
        data: Base match data.

    Returns:
        List of candidates.
    """

    market_open = data["prob_market_open"].to_numpy(dtype=float)
    market_close = data["prob_market_close"].to_numpy(dtype=float)
    model = data["prob_model"].to_numpy(dtype=float)
    model_t060 = apply_temperature(model, 0.60)
    hybrid_030_t060 = 0.30 * model_t060 + 0.70 * market_open
    hybrid_048_t060 = 0.48 * model_t060 + 0.52 * market_open
    hybrid_060_t060 = 0.60 * model_t060 + 0.40 * market_open
    dynamic_probability = load_dynamic_alpha_probability(data, model_t060)

    return [
        Candidate("Market Avg Open", market_open),
        Candidate(
            "Market Avg Close",
            market_close,
            odds_t1_column="best_close_t1",
            odds_t2_column="best_close_t2",
        ),
        Candidate("Metamodel T=1.00", model),
        Candidate("Hybrid α=0.30 T=0.60", hybrid_030_t060),
        Candidate("Hybrid α=0.48 T=0.60", hybrid_048_t060),
        Candidate("Hybrid α=0.60 T=0.60", hybrid_060_t060),
        Candidate("Dynamic α, T=0.60", dynamic_probability),
    ]


def save_plot(history: pd.DataFrame) -> None:
    """Save bankroll-over-time plot.

    Args:
        history: Combined bankroll history.
    """

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(12, 7))
    colors = {
        "Market Avg Open": "#6B7280",
        "Market Avg Close": "#111827",
        "Metamodel T=1.00": "#D97706",
        "Hybrid α=0.30 T=0.60": "#2563EB",
        "Hybrid α=0.48 T=0.60": "#7C3AED",
        "Hybrid α=0.60 T=0.60": "#DB2777",
        "Dynamic α, T=0.60": "#059669",
    }
    for candidate, group in history.groupby("candidate", sort=False):
        ax.plot(
            group["date"],
            group["bankroll"],
            label=candidate,
            linewidth=2.4,
            color=colors.get(candidate),
        )

    ax.axhline(INITIAL_BANKROLL, color="#111827", linewidth=1.0, linestyle="--", alpha=0.7)
    ax.set_title("Fixed-stake bankroll over time — idealized no-slippage model comparison (2024+)", fontsize=15, weight="bold")
    ax.set_ylabel("Bankroll")
    ax.set_xlabel("Data")
    ax.legend(loc="upper left", frameon=True)
    ax.grid(True, alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(OUTPUT_FIGURE, dpi=180)
    plt.close(fig)


def main() -> None:
    """Generate fixed-stake bankroll chart and summaries."""

    data = pd.read_csv(INPUT_PATH, parse_dates=["date"])
    data = data[data["date"] >= pd.Timestamp(SCOPE_START_DATE)].copy()
    data = data.sort_values("date").reset_index(drop=True)

    history_frames = []
    summaries = []
    for candidate in build_candidates(data):
        history, summary = simulate_fixed_stake(data, candidate)
        history_frames.append(history)
        summaries.append(summary)

    combined_history = pd.concat(history_frames, ignore_index=True)
    summary = pd.DataFrame(summaries)
    FINANCIAL_DIR.mkdir(parents=True, exist_ok=True)
    combined_history.to_csv(OUTPUT_HISTORY, index=False)
    summary.to_csv(OUTPUT_SUMMARY, index=False)
    save_plot(combined_history)

    print(f"Saved: {OUTPUT_HISTORY}")
    print(f"Saved: {OUTPUT_SUMMARY}")
    print(f"Saved: {OUTPUT_FIGURE}")
    printable = summary.copy()
    printable["candidate"] = printable["candidate"].str.replace("α", "alpha", regex=False)
    print(printable.to_string(index=False))


if __name__ == "__main__":
    main()
