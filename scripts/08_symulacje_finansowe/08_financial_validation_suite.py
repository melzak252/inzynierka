"""Financial validation suite for Chapter 8 of the whitepaper.

The script evaluates candidate probability models selected in Chapter 7 under
several staking policies. It intentionally uses only opening odds as executable
prices. Closing odds are used only for CLV diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score


ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "docs" / "assets" / "hybrid_point7" / "hybrid_model_input_predictions.csv"
OUTPUT_DIR = ROOT / "docs" / "assets" / "financial_point8"

INITIAL_BANKROLL = 100.0
TAX_RATE = 0.12
SLIPPAGE = 0.01
EV_THRESHOLD = 0.05
MIN_STAKE = 2.0
MAX_STAKE = 100.0
FIXED_STAKE = 10.0


@dataclass(frozen=True)
class Candidate:
    """Probability candidate evaluated in the financial suite.

    Attributes:
        name: Human-readable model name.
        alpha: Optional hybrid alpha. If None, raw model probability is used.
        temperature: Temperature applied to metamodel probabilities.
        source: Candidate family: market, metamodel, or hybrid.
    """

    name: str
    alpha: float | None
    temperature: float
    source: str


@dataclass(frozen=True)
class StakingPolicy:
    """Staking policy configuration.

    Attributes:
        name: Policy name for reporting.
        kind: fixed, percent, or kelly.
        fixed_stake: Fixed stake for flat staking.
        fraction: Bankroll fraction or Kelly multiplier.
    """

    name: str
    kind: str
    fixed_stake: float | None = None
    fraction: float | None = None


def configure_style() -> None:
    """Configure a thesis-friendly plotting style."""
    sns.set_theme(style="whitegrid", context="talk")
    plt.rcParams.update(
        {
            "figure.dpi": 120,
            "savefig.dpi": 300,
            "axes.titleweight": "bold",
            "axes.titlesize": 15,
            "axes.labelsize": 12,
        }
    )


def safe_logit(probability: pd.Series | np.ndarray) -> np.ndarray:
    """Calculate a clipped logit transform.

    Args:
        probability: Probability vector.

    Returns:
        Logit-transformed probabilities.
    """
    clipped = np.clip(np.asarray(probability, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(clipped / (1 - clipped))


def sigmoid(value: np.ndarray) -> np.ndarray:
    """Calculate sigmoid for an array."""
    return 1 / (1 + np.exp(-value))


def apply_temperature(probability: pd.Series | np.ndarray, temperature: float) -> np.ndarray:
    """Apply temperature scaling to binary probabilities.

    Args:
        probability: Base probabilities.
        temperature: Temperature parameter. Values below one sharpen probabilities.

    Returns:
        Temperature-scaled probabilities.
    """
    return sigmoid(safe_logit(probability) / temperature)


def calculate_ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """Calculate Expected Calibration Error.

    Args:
        y_true: Binary labels.
        y_prob: Predicted probabilities.
        n_bins: Number of calibration bins.

    Returns:
        ECE value.
    """
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for lower, upper in zip(bins[:-1], bins[1:]):
        mask = (y_prob > lower) & (y_prob <= upper)
        if mask.mean() > 0:
            ece += abs(y_prob[mask].mean() - y_true[mask].mean()) * mask.mean()
    return float(ece)


def model_probability(data: pd.DataFrame, candidate: Candidate) -> np.ndarray:
    """Build candidate probability vector.

    Args:
        data: Input data with market and metamodel probabilities.
        candidate: Candidate definition.

    Returns:
        Probability for team 1.
    """
    if candidate.source == "market":
        return data["prob_market_open"].to_numpy(dtype=float)

    model_prob = apply_temperature(data["prob_model"], candidate.temperature)
    if candidate.source == "metamodel":
        return model_prob

    if candidate.alpha is None:
        raise ValueError("Hybrid candidate requires alpha.")
    market_prob = data["prob_market_open"].to_numpy(dtype=float)
    return candidate.alpha * model_prob + (1 - candidate.alpha) * market_prob


def choose_bet(row: pd.Series, probability: float) -> tuple[str | None, float, float, float]:
    """Choose a bet side if EV threshold is exceeded.

    Args:
        row: Match row with best opening odds.
        probability: Probability for team 1.

    Returns:
        Tuple of selected side, selected probability, raw odds, selected EV.
    """
    odds_t1 = row["best_open_t1"]
    odds_t2 = row["best_open_t2"]
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


def calculate_stake(
    bankroll: float,
    policy: StakingPolicy,
    probability: float,
    raw_odds: float,
) -> float:
    """Calculate stake for the selected policy.

    Args:
        bankroll: Current bankroll.
        policy: Staking policy.
        probability: Probability of selected side.
        raw_odds: Raw selected opening odds before execution slippage.

    Returns:
        Stake amount or zero if no stake should be placed.
    """
    if bankroll <= 0:
        return 0.0

    if policy.kind == "fixed":
        stake = float(policy.fixed_stake or 0.0)
    elif policy.kind == "percent":
        stake = bankroll * float(policy.fraction or 0.0)
        stake = min(max(stake, MIN_STAKE), MAX_STAKE)
    elif policy.kind == "kelly":
        execution_odds = raw_odds * (1 - SLIPPAGE)
        net_decimal = execution_odds * (1 - TAX_RATE)
        b = net_decimal - 1
        if b <= 0:
            return 0.0
        full_kelly = ((b * probability) - (1 - probability)) / b
        if full_kelly <= 0:
            return 0.0
        stake = bankroll * full_kelly * float(policy.fraction or 0.0)
        stake = min(max(stake, MIN_STAKE), MAX_STAKE)
    else:
        raise ValueError(f"Unknown staking policy: {policy.kind}")

    if stake > bankroll:
        return 0.0
    return float(stake)


def simulate_strategy(
    data: pd.DataFrame,
    probabilities: np.ndarray,
    candidate_name: str,
    policy: StakingPolicy,
    scope_name: str,
) -> tuple[dict[str, float | int | str], pd.DataFrame]:
    """Simulate a strategy under one staking policy.

    Args:
        data: Match data sorted chronologically.
        probabilities: Probability for team 1.
        candidate_name: Model candidate label.
        policy: Staking policy.
        scope_name: Evaluation scope label.

    Returns:
        Summary dictionary and bankroll history frame.
    """
    bankroll = INITIAL_BANKROLL
    peak = INITIAL_BANKROLL
    max_drawdown = 0.0
    total_staked = 0.0
    total_profit = 0.0
    bets = 0
    wins = 0
    clv_values: list[float] = []
    rows: list[dict[str, float | int | str]] = []

    for idx, (_, row) in enumerate(data.iterrows()):
        side, selected_prob, raw_odds, selected_ev = choose_bet(row, probabilities[idx])
        profit = 0.0
        stake = 0.0
        is_win = False

        if side is not None:
            stake = calculate_stake(bankroll, policy, selected_prob, raw_odds)
            if stake > 0:
                execution_odds = raw_odds * (1 - SLIPPAGE)
                if side == "t1":
                    is_win = bool(row["y_true"] == 1)
                    close_odds = row.get("best_close_t1", np.nan)
                else:
                    is_win = bool(row["y_true"] == 0)
                    close_odds = row.get("best_close_t2", np.nan)

                if is_win:
                    profit = stake * (execution_odds * (1 - TAX_RATE) - 1)
                    wins += 1
                else:
                    profit = -stake

                bankroll += profit
                total_staked += stake
                total_profit += profit
                bets += 1

                if pd.notna(close_odds) and close_odds > 0:
                    clv_values.append((raw_odds - close_odds) / close_odds)

        peak = max(peak, bankroll)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - bankroll) / peak)

        rows.append(
            {
                "scope": scope_name,
                "candidate": candidate_name,
                "staking_policy": policy.name,
                "date": row["date"],
                "match_index": idx,
                "bankroll": bankroll,
                "stake": stake,
                "profit": profit,
                "selected_ev": selected_ev,
                "bet_placed": int(stake > 0),
                "win": int(is_win),
            }
        )

    summary = {
        "scope": scope_name,
        "candidate": candidate_name,
        "staking_policy": policy.name,
        "final_bankroll": bankroll,
        "profit": total_profit,
        "roi_pct": (bankroll / INITIAL_BANKROLL - 1) * 100,
        "yield_pct": (total_profit / total_staked * 100) if total_staked else 0.0,
        "max_drawdown_pct": max_drawdown * 100,
        "total_staked": total_staked,
        "bets": bets,
        "win_rate_pct": (wins / bets * 100) if bets else 0.0,
        "avg_stake": (total_staked / bets) if bets else 0.0,
        "avg_clv_pct": (np.mean(clv_values) * 100) if clv_values else 0.0,
    }
    return summary, pd.DataFrame(rows)


def evaluate_probability_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
) -> dict[str, float]:
    """Evaluate probabilistic metrics.

    Args:
        y_true: Binary labels.
        y_prob: Predicted probabilities.

    Returns:
        Dictionary with AUC, LogLoss, Brier, and ECE.
    """
    clipped = np.clip(y_prob, 1e-6, 1 - 1e-6)
    return {
        "auc": roc_auc_score(y_true, clipped),
        "logloss": log_loss(y_true, clipped),
        "brier": brier_score_loss(y_true, clipped),
        "ece": calculate_ece(y_true, clipped),
    }


def save_top_bankroll_plot(history: pd.DataFrame, summary: pd.DataFrame, scope: str) -> None:
    """Save bankroll plot for selected top candidates.

    Args:
        history: Full simulation history.
        summary: Simulation summary.
        scope: Scope label to plot.
    """
    fixed_percent = summary[
        (summary["scope"] == scope)
        & (summary["staking_policy"] == "Fixed percent 2% min2 max100")
    ].sort_values("final_bankroll", ascending=False)
    selected = fixed_percent.head(5)[["candidate", "staking_policy"]]
    plot_data = history.merge(selected, on=["candidate", "staking_policy"])
    plot_data = plot_data[plot_data["scope"] == scope].copy()

    if plot_data.empty:
        return

    plt.figure(figsize=(12, 6))
    sns.lineplot(data=plot_data, x="date", y="bankroll", hue="candidate", linewidth=2.0)
    plt.title(f"Financial validation — bankroll over time ({scope})")
    plt.xlabel("Date")
    plt.ylabel("Bankroll")
    plt.legend(title="Candidate", fontsize=9)
    plt.tight_layout()
    filename = f"financial_bankroll_{scope.lower().replace('+', 'plus')}.png"
    plt.savefig(OUTPUT_DIR / filename, bbox_inches="tight")
    plt.close()


def save_kelly_sensitivity(summary: pd.DataFrame) -> None:
    """Save Kelly multiplier sensitivity plot for hybrid candidates.

    Args:
        summary: Simulation summary frame.
    """
    data = summary[
        summary["staking_policy"].str.startswith("Kelly")
        & summary["candidate"].str.contains("Hybrid")
        & (summary["scope"] == "2024+")
    ].copy()
    if data.empty:
        return
    data["kelly_multiplier"] = data["staking_policy"].str.extract(r"Kelly ([0-9.]+)").astype(float)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    sns.lineplot(data=data, x="kelly_multiplier", y="roi_pct", hue="candidate", marker="o", ax=axes[0])
    axes[0].set_title("Kelly multiplier vs ROI — 2024+")
    axes[0].set_xlabel("Kelly multiplier")
    axes[0].set_ylabel("ROI [%]")

    sns.lineplot(
        data=data,
        x="kelly_multiplier",
        y="max_drawdown_pct",
        hue="candidate",
        marker="o",
        ax=axes[1],
        legend=False,
    )
    axes[1].set_title("Kelly multiplier vs Max Drawdown — 2024+")
    axes[1].set_xlabel("Kelly multiplier")
    axes[1].set_ylabel("Max Drawdown [%]")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "financial_kelly_sensitivity_2024.png", bbox_inches="tight")
    plt.close()


def main() -> None:
    """Run the Chapter 8 financial validation suite."""
    configure_style()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data = pd.read_csv(INPUT_PATH)
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values("date").reset_index(drop=True)

    candidates = [
        Candidate("Market Avg Open", None, 1.0, "market"),
        Candidate("Metamodel T=1.00", None, 1.0, "metamodel"),
        Candidate("Metamodel T=0.60", None, 0.6, "metamodel"),
        Candidate("Hybrid a=0.62 T=1.00", 0.62, 1.0, "hybrid"),
        Candidate("Hybrid a=0.48 T=1.00", 0.48, 1.0, "hybrid"),
        Candidate("Hybrid a=0.48 T=0.70", 0.48, 0.7, "hybrid"),
        Candidate("Hybrid a=0.48 T=0.60", 0.48, 0.6, "hybrid"),
        Candidate("Hybrid a=0.62 T=0.80", 0.62, 0.8, "hybrid"),
    ]

    policies = [
        StakingPolicy("Fixed stake 10", "fixed", fixed_stake=FIXED_STAKE),
        StakingPolicy("Fixed percent 2% min2 max100", "percent", fraction=0.02),
        StakingPolicy("Kelly 0.10 min2 max100", "kelly", fraction=0.10),
        StakingPolicy("Kelly 0.25 min2 max100", "kelly", fraction=0.25),
        StakingPolicy("Kelly 0.50 min2 max100", "kelly", fraction=0.50),
    ]

    scopes = {
        "2021+": data[data["date"] >= pd.Timestamp("2021-01-01")].copy(),
        "2024+": data[data["date"] >= pd.Timestamp("2024-01-01")].copy(),
    }

    summaries: list[dict[str, float | int | str]] = []
    histories: list[pd.DataFrame] = []
    metric_rows: list[dict[str, float | int | str]] = []

    for scope_name, scope_data in scopes.items():
        y_true = scope_data["y_true"].to_numpy(dtype=int)
        for candidate in candidates:
            probabilities = model_probability(scope_data, candidate)
            metric_row = {
                "scope": scope_name,
                "candidate": candidate.name,
                **evaluate_probability_metrics(y_true, probabilities),
                "n_matches": len(scope_data),
            }
            metric_rows.append(metric_row)

            for policy in policies:
                summary, history = simulate_strategy(
                    scope_data,
                    probabilities,
                    candidate.name,
                    policy,
                    scope_name,
                )
                summary.update(metric_row)
                summaries.append(summary)
                histories.append(history)

    summary_df = pd.DataFrame(summaries)
    history_df = pd.concat(histories, ignore_index=True)
    metrics_df = pd.DataFrame(metric_rows)

    summary_df.to_csv(OUTPUT_DIR / "financial_validation_summary.csv", index=False)
    history_df.to_csv(OUTPUT_DIR / "financial_validation_bankroll_history.csv", index=False)
    metrics_df.to_csv(OUTPUT_DIR / "financial_validation_probability_metrics.csv", index=False)

    save_top_bankroll_plot(history_df, summary_df, "2021+")
    save_top_bankroll_plot(history_df, summary_df, "2024+")
    save_kelly_sensitivity(summary_df)

    top_2024 = summary_df[summary_df["scope"] == "2024+"].sort_values(
        "final_bankroll", ascending=False
    ).head(10)
    print("\nTop 2024+ financial configurations:")
    print(
        top_2024[
            [
                "candidate",
                "staking_policy",
                "final_bankroll",
                "roi_pct",
                "yield_pct",
                "max_drawdown_pct",
                "bets",
                "avg_stake",
                "logloss",
            ]
        ].to_string(index=False)
    )
    print(f"\nSaved outputs to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
