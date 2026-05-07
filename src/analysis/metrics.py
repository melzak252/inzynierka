from typing import Dict

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)


def calculate_basic_metrics(
    y_true: pd.Series,
    y_prob: pd.Series,
    label: str = "Model",
) -> Dict[str, float]:
    """Calculate basic binary classification metrics.

    Args:
        y_true: Binary target values.
        y_prob: Predicted probability for the positive class.
        label: Human-readable label printed with the metric summary.

    Returns:
        Dictionary with LogLoss, AUC, accuracy, and Brier score.
    """
    y_prob_clipped = y_prob.clip(1e-15, 1 - 1e-15)

    metrics = {
        "log_loss": log_loss(y_true, y_prob_clipped),
        "auc": roc_auc_score(y_true, y_prob),
        "accuracy": accuracy_score(y_true, (y_prob >= 0.5).astype(int)),
        "brier_score": brier_score_loss(y_true, y_prob),
    }

    print(f"\n--- {label} Metrics ---")
    for name, value in metrics.items():
        print(f"{name.replace('_', ' ').title():<15}: {value:.5f}")

    return metrics


def shannon_entropy(p: float) -> float:
    """Calculate binary Shannon entropy in bits.

    Args:
        p: Probability of the positive class.

    Returns:
        Binary entropy in bits. Boundary probabilities return `0.0`.
    """
    if p <= 0 or p >= 1:
        return 0.0
    return -(p * np.log2(p) + (1 - p) * np.log2(1 - p))


def mean_prediction_entropy(y_prob: pd.Series) -> float:
    """Calculate average entropy of predicted probabilities.

    Args:
        y_prob: Predicted probability for the positive class.

    Returns:
        Mean binary entropy in bits.
    """
    entropies = [shannon_entropy(p) for p in y_prob]
    return float(np.mean(entropies))


def brier_decomposition(
    y_true: pd.Series,
    y_prob: pd.Series,
    n_bins: int = 10,
) -> Dict[str, float]:
    """Compute binned Brier score decomposition.

    Args:
        y_true: Binary target values.
        y_prob: Predicted probability for the positive class.
        n_bins: Number of equal-width probability bins.

    Returns:
        Dictionary with reliability, resolution, and uncertainty components.
    """
    y_true_arr = np.asarray(y_true, dtype=float)
    y_prob_arr = np.asarray(y_prob, dtype=float)
    n_samples = len(y_true_arr)

    if n_samples == 0:
        return {
            "brier_reliability": 0.0,
            "brier_resolution": 0.0,
            "brier_uncertainty": 0.0,
        }

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_ids = np.clip(np.digitize(y_prob_arr, bins) - 1, 0, n_bins - 1)
    base_rate = float(np.mean(y_true_arr))

    reliability = 0.0
    resolution = 0.0
    for bin_id in range(n_bins):
        mask = bin_ids == bin_id
        if not np.any(mask):
            continue

        weight = float(np.mean(mask))
        observed_rate = float(np.mean(y_true_arr[mask]))
        predicted_rate = float(np.mean(y_prob_arr[mask]))
        reliability += weight * (predicted_rate - observed_rate) ** 2
        resolution += weight * (observed_rate - base_rate) ** 2

    uncertainty = base_rate * (1.0 - base_rate)
    return {
        "brier_reliability": reliability,
        "brier_resolution": resolution,
        "brier_uncertainty": uncertainty,
    }


def calculate_detailed_metrics(
    y_true: pd.Series,
    y_prob: pd.Series,
    n_bins: int = 10,
) -> Dict[str, float]:
    """Calculate classification, calibration, and information metrics.

    Args:
        y_true: Binary target values.
        y_prob: Predicted probability for the positive class.
        n_bins: Number of bins used for binned calibration estimates.

    Returns:
        Dictionary with base metrics, Brier decomposition, entropy metrics,
        mutual information estimate, and sample count.
    """
    y_true_arr = np.array(y_true)
    y_prob_arr = np.array(y_prob)
    n_samples = len(y_true_arr)

    basic = calculate_basic_metrics(y_true, y_prob)
    brier_decomp = brier_decomposition(y_true, y_prob, n_bins=n_bins)

    o_bar = np.mean(y_true_arr)
    h_out = shannon_entropy(o_bar)
    h_pred = mean_prediction_entropy(y_prob)

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    binids = np.clip(np.digitize(y_prob_arr, bins) - 1, 0, n_bins - 1)

    bin_sums = np.bincount(binids, weights=y_true_arr, minlength=n_bins)
    bin_counts = np.bincount(binids, minlength=n_bins)

    mask = bin_counts > 0
    n_k = bin_counts[mask]
    o_bar_k = bin_sums[mask] / n_k

    h_cond = 0.0
    for index, count in enumerate(n_k):
        h_cond += (count / n_samples) * shannon_entropy(o_bar_k[index])

    mi = h_out - h_cond

    metrics = {
        **basic,
        **brier_decomp,
        "outcome_entropy": h_out,
        "prediction_entropy": h_pred,
        "mutual_info": mi,
        "count": float(n_samples),
    }

    return metrics
