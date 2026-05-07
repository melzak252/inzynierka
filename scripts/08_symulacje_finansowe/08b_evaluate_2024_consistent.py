import os
from dataclasses import dataclass
from datetime import datetime

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score


BOOKMAKERS = ["betclic", "betfan", "efortuna", "lv_bet", "sts", "superbet"]


@dataclass(frozen=True)
class SimulationConfig:
    """Configuration for deterministic financial backtesting."""

    initial_bankroll: float = 100.0
    kelly_fraction: float = 0.25
    stake_cap: float = 100.0
    min_stake: float = 2.0
    tax_rate: float = 0.12
    slippage: float = 0.01
    ev_threshold: float = 0.05


def calculate_ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """Calculate Expected Calibration Error for binary probabilities.

    Args:
        y_true: Binary ground-truth labels.
        y_prob: Predicted probabilities for the positive class.
        n_bins: Number of probability bins.

    Returns:
        Weighted absolute calibration error.
    """
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    ece = 0.0

    for bin_lower, bin_upper in zip(bin_boundaries[:-1], bin_boundaries[1:]):
        in_bin = (y_prob > bin_lower) & (y_prob <= bin_upper)
        prop_in_bin = np.mean(in_bin)
        if prop_in_bin > 0:
            accuracy_in_bin = np.mean(y_true[in_bin])
            confidence_in_bin = np.mean(y_prob[in_bin])
            ece += np.abs(accuracy_in_bin - confidence_in_bin) * prop_in_bin

    return float(ece)


def kelly_fraction(probability: float, net_decimal_odds: float) -> float:
    """Calculate full Kelly fraction for a binary bet.

    Args:
        probability: Estimated win probability.
        net_decimal_odds: Decimal odds after tax multiplier.

    Returns:
        Non-negative full Kelly stake fraction.
    """
    b = net_decimal_odds - 1
    if b <= 0 or probability <= 0 or probability >= 1:
        return 0.0

    q = 1 - probability
    return float(max(0.0, (b * probability - q) / b))


def is_tier1(tournament: str) -> bool:
    """Classify tournament as Tier 1 using project-specific keyword rules.

    Args:
        tournament: Tournament name.

    Returns:
        True for Tier 1 competitions, otherwise False.
    """
    tier1_keywords = [
        "LEC",
        "LCS",
        "LTA",
        "LCK",
        "LPL",
        "European Championship",
        "Championship Series",
        "Champions Korea",
        "Pro League",
        "Mid-Season Invitational",
        "Mid Season Invitational",
        "First Stand",
        "World Championship",
        "Mistrzostwa Świata",
    ]
    text = str(tournament)
    if "Pro League" in text and "Oceanic" not in text and "Continental" not in text:
        return True
    return any(keyword in text for keyword in tier1_keywords)


def add_best_open_odds(df: pd.DataFrame) -> pd.DataFrame:
    """Add best available opening odds and corresponding bookmaker names.

    Args:
        df: Match-level dataframe with bookmaker opening odds columns.

    Returns:
        Dataframe with max opening odds and best bookmaker columns.
    """
    result = df.copy()
    odds1_cols = [f"odds1_{bookmaker}_open" for bookmaker in BOOKMAKERS]
    odds2_cols = [f"odds2_{bookmaker}_open" for bookmaker in BOOKMAKERS]

    result["max_open_t1"] = result[odds1_cols].max(axis=1)
    result["max_open_t2"] = result[odds2_cols].max(axis=1)
    result["best_bookie_t1"] = result[odds1_cols].idxmax(axis=1).str.replace("odds1_", "", regex=False).str.replace("_open", "", regex=False).str.upper()
    result["best_bookie_t2"] = result[odds2_cols].idxmax(axis=1).str.replace("odds2_", "", regex=False).str.replace("_open", "", regex=False).str.upper()
    return result


def evaluate_statistical_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Evaluate all main models on the same 2024+ sample.

    Args:
        df: Modern-era dataframe.

    Returns:
        Model metric table.
    """
    models = {
        "Hybrid Model": "final_hybrid_prob",
        "Metamodel (Stage 2)": "metamodel_lgbm_calibrated",
        "Metamodel Platt": "metamodel_lgbm_platt",
        "Rating Ensemble (Stage 1)": "s1_prob",
        "Player Glicko2 (Baseline)": "player_gl",
        "Market Avg (Open)": "prob_avg_open",
    }
    rows = []

    for model_name, column in models.items():
        subset = df.dropna(subset=["y_true", column])
        y_true = subset["y_true"].to_numpy()
        y_prob = subset[column].to_numpy()
        y_pred = (y_prob > 0.5).astype(int)
        rows.append(
            {
                "Model": model_name,
                "AUC": roc_auc_score(y_true, y_prob),
                "LogLoss": log_loss(y_true, y_prob),
                "Brier": brier_score_loss(y_true, y_prob),
                "ECE": calculate_ece(y_true, y_prob),
                "ACC (%)": accuracy_score(y_true, y_pred) * 100,
                "Sample Size": len(subset),
            }
        )

    return pd.DataFrame(rows).sort_values("LogLoss")


def simulate_financial_model(
    df: pd.DataFrame,
    model_name: str,
    probability_column: str,
    config: SimulationConfig,
) -> tuple[dict[str, float | int | str], pd.DataFrame, list[float]]:
    """Run deterministic 2024+ opening-odds financial simulation.

    Args:
        df: Chronologically sorted modern-era dataframe.
        model_name: Human-readable model name.
        probability_column: Probability column used for EV decisions.
        config: Simulation configuration.

    Returns:
        Summary row, individual bet log, and bankroll history.
    """
    bankroll = config.initial_bankroll
    bankroll_history = [bankroll]
    total_staked = 0.0
    wins = 0
    bet_rows = []
    net_multiplier = 1 - config.tax_rate

    for _, row in df.iterrows():
        p_t1 = row[probability_column]
        if pd.isnull(p_t1):
            bankroll_history.append(bankroll)
            continue

        ev_t1 = row["max_open_t1"] * net_multiplier * p_t1 - 1
        ev_t2 = row["max_open_t2"] * net_multiplier * (1 - p_t1) - 1

        if ev_t1 > ev_t2 and ev_t1 > config.ev_threshold:
            side = "T1"
            raw_odds = row["max_open_t1"]
            probability = p_t1
            is_win = int(row["y_true"] == 1)
            bookmaker = row["best_bookie_t1"]
            edge = ev_t1
        elif ev_t2 > config.ev_threshold:
            side = "T2"
            raw_odds = row["max_open_t2"]
            probability = 1 - p_t1
            is_win = int(row["y_true"] == 0)
            bookmaker = row["best_bookie_t2"]
            edge = ev_t2
        else:
            bankroll_history.append(bankroll)
            continue

        execution_odds = max(1.01, raw_odds * (1 - config.slippage))
        net_decimal_odds = raw_odds * net_multiplier
        stake_fraction = kelly_fraction(probability, net_decimal_odds) * config.kelly_fraction
        stake = min(bankroll * stake_fraction, config.stake_cap)

        if stake < config.min_stake or stake > bankroll:
            bankroll_history.append(bankroll)
            continue

        profit = stake * execution_odds * net_multiplier - stake if is_win else -stake
        bankroll += profit
        total_staked += stake
        wins += is_win

        bet_rows.append(
            {
                "Model": model_name,
                "golgg_match_id": row["golgg_match_id"],
                "date": row["date"],
                "Tournament": row["tournament"],
                "Tier": "Tier 1" if row["is_tier1"] else "ERL/Regional",
                "BoN": f"Bo{int(row['BoN'])}",
                "Bookmaker": bookmaker,
                "Side": side,
                "Probability": probability,
                "Raw Odds": raw_odds,
                "Execution Odds": execution_odds,
                "Edge": edge,
                "Stake": stake,
                "Profit": profit,
                "Bankroll": bankroll,
                "Win": is_win,
            }
        )
        bankroll_history.append(bankroll)

    bets_df = pd.DataFrame(bet_rows)
    bankroll_array = np.array(bankroll_history)
    peaks = np.maximum.accumulate(bankroll_array)
    drawdowns = (peaks - bankroll_array) / (peaks + 1e-9)
    total_profit = bankroll - config.initial_bankroll
    total_bets = len(bets_df)

    summary = {
        "Model": model_name,
        "Final Bankroll": bankroll,
        "Total Profit": total_profit,
        "ROI (%)": total_profit / config.initial_bankroll * 100,
        "Yield (%)": total_profit / total_staked * 100 if total_staked > 0 else 0.0,
        "Max Drawdown (%)": float(np.max(drawdowns) * 100),
        "Min Bankroll": float(np.min(bankroll_array)),
        "Total Staked": total_staked,
        "Bets": total_bets,
        "Win Rate (%)": wins / total_bets * 100 if total_bets > 0 else 0.0,
    }

    return summary, bets_df, bankroll_history


def calculate_clv(bets_df: pd.DataFrame, source_df: pd.DataFrame) -> dict[str, float]:
    """Calculate CLV for the final hybrid bets.

    Args:
        bets_df: Bet log for the hybrid model.
        source_df: Match dataframe containing closing market probabilities.

    Returns:
        Average CLV and percentage of bets beating the closing line.
    """
    if bets_df.empty:
        return {"Average CLV (%)": 0.0, "Bets Beating Closing Line (%)": 0.0}

    lookup = source_df.set_index("golgg_match_id")
    clv_values = []

    for _, bet in bets_df.iterrows():
        match_id = bet["golgg_match_id"]
        if match_id not in lookup.index:
            continue

        match = lookup.loc[match_id]

        close_prob_t1 = match["prob_avg_close"]
        fair_close_odds = 1 / close_prob_t1 if bet["Side"] == "T1" else 1 / (1 - close_prob_t1)
        clv_values.append(bet["Raw Odds"] / fair_close_odds - 1)

    if not clv_values:
        return {"Average CLV (%)": 0.0, "Bets Beating Closing Line (%)": 0.0}

    clv_array = np.array(clv_values)
    return {
        "Average CLV (%)": float(np.mean(clv_array) * 100),
        "Bets Beating Closing Line (%)": float(np.mean(clv_array > 0) * 100),
    }


def save_plots(financial_results: dict[str, list[float]], df: pd.DataFrame, hybrid_bets: pd.DataFrame) -> None:
    """Save bankroll and breakdown plots for the 2024+ report.

    Args:
        financial_results: Mapping from model name to bankroll history.
        df: Modern-era match dataframe.
        hybrid_bets: Bet log for the hybrid model.
    """
    sns.set_style("whitegrid")
    plt.figure(figsize=(12, 7))
    for model_name, history in financial_results.items():
        plt.plot(df["date"], history[1:], label=model_name, linewidth=2 if model_name == "Hybrid Model" else 1.5)
    plt.title("Final Comparison: Bankroll Growth (2024+, Kelly f=0.25, Opening Odds)")
    plt.ylabel("Bankroll ($)")
    plt.xlabel("Date")
    plt.axhline(100, color="black", linestyle="--", alpha=0.6)
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig("docs/assets/final_bankroll_comparison_kelly.png", dpi=300, bbox_inches="tight")

    if not hybrid_bets.empty:
        plt.figure(figsize=(10, 6))
        hybrid_bets.groupby("Tier")["Profit"].sum().plot(kind="bar", color=["orange", "blue"])
        plt.title("Hybrid Model Profit by League Tier (2024+)")
        plt.ylabel("Profit ($)")
        plt.xticks(rotation=0)
        plt.tight_layout()
        plt.savefig("docs/assets/final_profit_by_tier.png", dpi=300, bbox_inches="tight")

        plt.figure(figsize=(10, 6))
        hybrid_bets.groupby("BoN")["Profit"].sum().plot(kind="bar", color="green")
        plt.title("Hybrid Model Profit by Match Format (2024+)")
        plt.ylabel("Profit ($)")
        plt.xticks(rotation=0)
        plt.tight_layout()
        plt.savefig("docs/assets/final_profit_by_bon.png", dpi=300, bbox_inches="tight")


def main() -> None:
    """Calculate consistent 2024+ statistical and financial report metrics."""
    print("Running 08b_evaluate_2024_consistent.py...")
    os.makedirs("docs/assets", exist_ok=True)

    df = pd.read_csv("data/golgg_final_hybrid_results.csv")
    df["date"] = pd.to_datetime(df["date"])
    df = add_best_open_odds(df)
    df["prob_avg_close"] = 1 / df["avg_odds_home"] / ((1 / df["avg_odds_home"]) + (1 / df["avg_odds_away"]))
    df["is_tier1"] = df["tournament"].apply(is_tier1)
    df_modern = df[df["date"] >= datetime(2024, 1, 1)].sort_values("date").reset_index(drop=True)

    stats_df = evaluate_statistical_metrics(df_modern)
    stats_df.to_csv("docs/assets/consistent_metrics_2024.csv", index=False)
    print("\n=== CONSISTENT STATISTICAL METRICS (2024+) ===")
    print(stats_df.to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    config = SimulationConfig()
    financial_models = {
        "Hybrid Model": "final_hybrid_prob",
        "Metamodel (Stage 2)": "metamodel_lgbm_calibrated",
        "Rating Ensemble (Stage 1)": "s1_prob",
        "Player Glicko2 (Baseline)": "player_gl",
        "Market Avg (Open)": "prob_avg_open",
    }

    summaries = []
    all_bets = []
    bankroll_histories = {}
    hybrid_bets = pd.DataFrame()

    for model_name, probability_column in financial_models.items():
        summary, bets_df, history = simulate_financial_model(df_modern, model_name, probability_column, config)
        summaries.append(summary)
        all_bets.append(bets_df)
        bankroll_histories[model_name] = history
        if model_name == "Hybrid Model":
            hybrid_bets = bets_df

    financial_df = pd.DataFrame(summaries).sort_values("Final Bankroll", ascending=False)
    financial_df.to_csv("docs/assets/consistent_financial_2024.csv", index=False)
    pd.concat(all_bets, ignore_index=True).to_csv("docs/assets/consistent_bets_2024.csv", index=False)

    print("\n=== CONSISTENT FINANCIAL SIMULATION (2024+) ===")
    print(financial_df.to_string(index=False, float_format=lambda value: f"{value:.2f}"))

    clv_stats = calculate_clv(hybrid_bets, df_modern)
    with open("docs/assets/consistent_clv_2024.txt", "w", encoding="utf-8") as file:
        for key, value in clv_stats.items():
            file.write(f"{key}: {value:.2f}\n")
    print("\n=== HYBRID CLV (2024+) ===")
    for key, value in clv_stats.items():
        print(f"{key}: {value:.2f}")

    if not hybrid_bets.empty:
        top_tournaments = (
            hybrid_bets.groupby("Tournament")
            .agg(Profit=("Profit", "sum"), Bets=("Profit", "count"), Staked=("Stake", "sum"))
            .assign(Yield=lambda table: table["Profit"] / table["Staked"] * 100)
            .sort_values("Profit", ascending=False)
            .head(10)
        )
        top_tournaments.to_csv("docs/assets/consistent_top_tournaments_2024.csv")

        bookmaker_breakdown = (
            hybrid_bets.groupby("Bookmaker")
            .agg(Profit=("Profit", "sum"), Bets=("Profit", "count"), Staked=("Stake", "sum"))
            .assign(Yield=lambda table: table["Profit"] / table["Staked"] * 100)
            .sort_values("Profit", ascending=False)
        )
        bookmaker_breakdown.to_csv("docs/assets/consistent_bookmakers_2024.csv")

        print("\n=== HYBRID TOP TOURNAMENTS (2024+) ===")
        print(top_tournaments.to_string(float_format=lambda value: f"{value:.2f}"))
        print("\n=== HYBRID BOOKMAKER BREAKDOWN (2024+) ===")
        print(bookmaker_breakdown.to_string(float_format=lambda value: f"{value:.2f}"))

    save_plots(bankroll_histories, df_modern, hybrid_bets)
    print("\n08b_evaluate_2024_consistent.py completed successfully.")


if __name__ == "__main__":
    main()
