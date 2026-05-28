"""Reusable bootstrap utilities for probabilistic model comparison."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd


def monthly_block_bootstrap_delta(
    data: pd.DataFrame,
    delta_column: str,
    date_column: str = "date",
    n_bootstraps: int = 10_000,
    random_seed: int = 42,
    random_generator: np.random.Generator | None = None,
) -> tuple[float, float, float, np.ndarray]:
    """Bootstrap the mean of a per-row delta using calendar-month blocks.

    Args:
        data: Data frame containing dates and per-row deltas.
        delta_column: Column with the per-row quantity to average.
        date_column: Date column used to form monthly blocks.
        n_bootstraps: Number of bootstrap resamples.
        random_seed: Seed for deterministic resampling.
        random_generator: Optional shared NumPy generator. When supplied, it is
            advanced in-place and ``random_seed`` is ignored.

    Returns:
        Tuple ``(observed, ci_lower, ci_upper, samples)``.
    """

    working = data[[date_column, delta_column]].dropna().copy()
    working["month"] = pd.to_datetime(working[date_column]).dt.to_period("M").astype(str)
    months = sorted(working["month"].unique())
    if not months:
        raise ValueError("Cannot bootstrap an empty set of monthly blocks.")

    observed = float(working[delta_column].mean())
    month_stats = working.groupby("month")[delta_column].agg(delta_sum="sum", n="size").loc[months]
    delta_sums = month_stats["delta_sum"].to_numpy(dtype=float)
    counts = month_stats["n"].to_numpy(dtype=float)

    rng = random_generator or np.random.default_rng(random_seed)
    samples = np.empty(n_bootstraps, dtype=float)
    for index in range(n_bootstraps):
        sampled_idx = rng.integers(0, len(months), size=len(months))
        samples[index] = float(delta_sums[sampled_idx].sum() / counts[sampled_idx].sum())

    return (
        observed,
        float(np.nanquantile(samples, 0.025)),
        float(np.nanquantile(samples, 0.975)),
        samples,
    )


def bootstrap_probability_column_comparisons(
    data: pd.DataFrame,
    target_column: str,
    reference_column: str,
    comparison_columns: dict[str, str],
    date_column: str = "date",
    n_bootstraps: int = 10_000,
    random_seed: int = 42,
    delta_transform: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
) -> pd.DataFrame:
    """Compare one probability column against several columns with block bootstrap.

    Args:
        data: Common sample containing target, dates and probability columns.
        target_column: Binary target column name.
        reference_column: Probability column for the reference model.
        comparison_columns: Mapping from human-readable comparison label to
            probability column.
        date_column: Date column used to form monthly blocks.
        n_bootstraps: Number of bootstrap resamples.
        random_seed: Seed for deterministic resampling.
        delta_transform: Optional function receiving ``(comparison_loss,
            reference_loss)`` and returning the per-row delta. If omitted, the
            default is ``comparison_loss - reference_loss``.

    Returns:
        Bootstrap summary with one row per compared model.
    """

    from src.analysis.probability_metrics import binary_log_loss_vector

    working = data.copy()
    labels = working[target_column].astype(int).to_numpy()
    reference_loss = binary_log_loss_vector(labels, working[reference_column].to_numpy())
    transform = delta_transform or (lambda comparison_loss, ref_loss: comparison_loss - ref_loss)
    rows: list[dict[str, object]] = []

    rng = np.random.default_rng(random_seed)
    for label, column in comparison_columns.items():
        comparison_loss = binary_log_loss_vector(labels, working[column].to_numpy())
        working["delta"] = transform(comparison_loss, reference_loss)
        observed, lower, upper, samples = monthly_block_bootstrap_delta(
            working,
            delta_column="delta",
            date_column=date_column,
            n_bootstraps=n_bootstraps,
            random_seed=random_seed,
            random_generator=rng,
        )
        rows.append(
            {
                "comparison_label": label,
                "comparison_column": column,
                "observed_delta_logloss": observed,
                "ci_lower_95": lower,
                "ci_upper_95": upper,
                "p_one_sided_delta_leq_zero": float(
                    (np.nansum(samples <= 0.0) + 1) / (np.sum(~np.isnan(samples)) + 1)
                ),
                "ci_excludes_zero_positive": bool(lower > 0.0),
            }
        )
    return pd.DataFrame(rows).sort_values("observed_delta_logloss", ascending=False)


def bootstrap_long_predictions_against_baseline(
    predictions: pd.DataFrame,
    baseline_label: str,
    label_column: str = "model_label",
    probability_column: str = "y_prob",
    target_column: str = "y_true",
    id_column: str = "golgg_match_id",
    date_column: str = "date",
    n_bootstraps: int = 10_000,
    random_seed: int = 42,
) -> pd.DataFrame:
    """Compare long-form prediction streams against one baseline stream.

    Positive deltas mean that the compared variant has higher LogLoss than the
    baseline.

    Args:
        predictions: Long-form prediction table.
        baseline_label: Label of the baseline stream.
        label_column: Column containing stream labels.
        probability_column: Probability column name.
        target_column: Binary target column name.
        id_column: Match identifier used for alignment.
        date_column: Date column used to form monthly blocks.
        n_bootstraps: Number of bootstrap resamples.
        random_seed: Seed for deterministic resampling.

    Returns:
        Bootstrap summary sorted by observed delta.
    """

    from src.analysis.probability_metrics import binary_log_loss_vector

    normalized = predictions.copy()
    normalized[id_column] = normalized[id_column].astype(str)
    normalized[date_column] = pd.to_datetime(normalized[date_column]).dt.strftime("%Y-%m-%d")
    baseline_data = normalized[normalized[label_column] == baseline_label][
        [id_column, date_column, target_column, probability_column]
    ].rename(columns={probability_column: "baseline_prob"})

    rng = np.random.default_rng(random_seed)
    rows: list[dict[str, object]] = []
    for variant in sorted(label for label in normalized[label_column].unique() if label != baseline_label):
        variant_data = normalized[normalized[label_column] == variant][[id_column, probability_column]].rename(
            columns={probability_column: "variant_prob"}
        )
        comparison_data = baseline_data.merge(variant_data, on=id_column, how="inner")
        comparison_data = comparison_data.dropna(subset=[target_column, "baseline_prob", "variant_prob"])
        labels = comparison_data[target_column].astype(int).to_numpy()
        baseline_loss = binary_log_loss_vector(labels, comparison_data["baseline_prob"].to_numpy())
        variant_loss = binary_log_loss_vector(labels, comparison_data["variant_prob"].to_numpy())
        comparison_data["delta"] = variant_loss - baseline_loss
        observed, lower, upper, samples = monthly_block_bootstrap_delta(
            comparison_data,
            delta_column="delta",
            date_column=date_column,
            n_bootstraps=n_bootstraps,
            random_seed=random_seed,
            random_generator=rng,
        )
        rows.append(
            {
                "comparison": f"{variant} vs {baseline_label}",
                "variant": variant,
                "baseline": baseline_label,
                "observed_delta_logloss_variant_minus_baseline": observed,
                "ci_lower_95": lower,
                "ci_upper_95": upper,
                "p_one_sided_variant_worse": float(
                    (np.nansum(samples <= 0.0) + 1) / (np.sum(~np.isnan(samples)) + 1)
                ),
                "significantly_worse": bool(lower > 0.0),
            }
        )
    return pd.DataFrame(rows).sort_values("observed_delta_logloss_variant_minus_baseline")
