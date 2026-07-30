# EXP-061 — EXP-039 Hybrid Alpha Sweep vs Opening/Mid/Close Market

> [!abstract]
> This experiment sweeps the production thesis hybrid weight `alpha` on the EXP-060 mapped market sample. The formula is `p_hybrid = alpha * temperature(EXP-039, T=0.80) + (1-alpha) * market_probability`, where `alpha=0` is market-only and `alpha=1` is temperature-scaled EXP-039-only.

## Metadata

- **Date:** 2026-07-30
- **Tags:** #exp039 #market #hybrid #alpha-sweep #logloss
- **Input:** `reports/exp039_db_market_backtest_v2/exp039_market_common.csv`
- **Output:**
  - `reports/exp039_alpha_sweep/summary.json`
  - `reports/exp039_alpha_sweep/alpha_sweep.csv`
- **Script:** `betting_app/scripts/sweep_exp039_hybrid_alpha.py`
- **Sample:** 408 canonical/GOL.GG mapped matches with EXP-039 prediction and opening/mid/close no-vig market probabilities.
- **Temperature:** `T=0.80`, matching the current thesis-hybrid production temperature.

## Objective

Test how much weight should be assigned to the fixed EXP-039 model versus bookmaker market probabilities at three market timestamps:

1. opening odds,
2. mid odds,
3. close odds.

## Method

For each market reference `m ∈ {open, mid, close}` and each alpha from `0.00` to `1.00` in `0.01` increments:

```text
p_model_t = sigmoid(logit(p_exp039) / 0.80)
p_hybrid = alpha * p_model_t + (1 - alpha) * p_market_m
```

Metrics: LogLoss, Brier score, ROC-AUC, accuracy at threshold `0.5`.

> [!bug]
> This is a small recent market-common sample (`N=408`). The sweep is useful for choosing a production prior, but should not be interpreted as a fully independent OOF estimate. The EXP-039 probabilities come from the regenerated EXP-060 DB backtest, while market probabilities come from mapped canonical odds snapshots.

## Results

### Best alpha by LogLoss

| Market Reference | Market-only LL | Best alpha | Best LL | Best Brier | Best AUC | Accuracy |
|---|---:|---:|---:|---:|---:|---:|
| Opening | 0.5830 | 0.48 | 0.5607 | 0.1907 | 0.7802 | 0.6936 |
| Mid | 0.5768 | 0.44 | 0.5585 | 0.1899 | 0.7813 | 0.6838 |
| Close | 0.5659 | 0.36 | 0.5546 | 0.1881 | 0.7862 | 0.6863 |

### Selected alpha values

#### Opening market reference

| Alpha | LogLoss | Brier | AUC | Accuracy |
|---:|---:|---:|---:|---:|
| 0.00 | 0.5830 | 0.1994 | 0.7590 | 0.6961 |
| 0.05 | 0.5781 | 0.1977 | 0.7626 | 0.6912 |
| 0.10 | 0.5741 | 0.1961 | 0.7665 | 0.6887 |
| 0.20 | 0.5678 | 0.1936 | 0.7717 | 0.6961 |
| 0.30 | 0.5636 | 0.1919 | 0.7761 | 0.6887 |
| 0.40 | 0.5612 | 0.1909 | 0.7797 | 0.6912 |
| 0.50 | 0.5607 | 0.1907 | 0.7799 | 0.6912 |
| 1.00 | 0.5969 | 0.2015 | 0.7654 | 0.6887 |

#### Mid market reference

| Alpha | LogLoss | Brier | AUC | Accuracy |
|---:|---:|---:|---:|---:|
| 0.00 | 0.5768 | 0.1968 | 0.7653 | 0.6912 |
| 0.05 | 0.5725 | 0.1953 | 0.7687 | 0.6985 |
| 0.10 | 0.5689 | 0.1940 | 0.7712 | 0.6985 |
| 0.20 | 0.5636 | 0.1919 | 0.7763 | 0.6936 |
| 0.30 | 0.5602 | 0.1906 | 0.7804 | 0.6887 |
| 0.40 | 0.5586 | 0.1899 | 0.7819 | 0.6838 |
| 0.50 | 0.5588 | 0.1900 | 0.7819 | 0.6887 |
| 1.00 | 0.5969 | 0.2015 | 0.7654 | 0.6887 |

#### Close market reference

| Alpha | LogLoss | Brier | AUC | Accuracy |
|---:|---:|---:|---:|---:|
| 0.00 | 0.5659 | 0.1920 | 0.7771 | 0.7132 |
| 0.05 | 0.5627 | 0.1910 | 0.7790 | 0.7059 |
| 0.10 | 0.5601 | 0.1901 | 0.7812 | 0.7034 |
| 0.20 | 0.5566 | 0.1888 | 0.7846 | 0.6961 |
| 0.30 | 0.5549 | 0.1882 | 0.7861 | 0.6961 |
| 0.35 | 0.5546 | 0.1881 | 0.7861 | 0.6887 |
| 0.40 | 0.5547 | 0.1882 | 0.7861 | 0.6863 |
| 0.50 | 0.5561 | 0.1888 | 0.7860 | 0.6863 |
| 1.00 | 0.5969 | 0.2015 | 0.7654 | 0.6887 |

## Interpretation

> [!check]
> The regenerated EXP-039 signal adds value to the market on this sample when used as a residual component. The optimal `alpha` is not near zero; it is approximately `0.35–0.50`, depending on whether the reference market is close, mid, or opening.

Key observations:

- Market-only is strong, but every market reference improves when blended with EXP-039.
- The optimal model weight decreases as the market gets closer to match start:
  - opening: `alpha≈0.48`,
  - mid: `alpha≈0.44`,
  - close: `alpha≈0.36`.
- Pure temperature-scaled EXP-039 (`alpha=1`) is worse than market-only by LogLoss, so EXP-039 should not replace the market directly.
- Current production `alpha=0.05` is very conservative. It improves slightly over market-only, but leaves much of the apparent residual value unused on this sample.

## Conclusion

Recommended next production candidate for testing:

```text
alpha = 0.35
temperature = 0.80
```

Rationale: `alpha=0.35` is near-optimal for close market, still strong for mid/open, and less aggressive than the exact open/mid optima around `0.44–0.48`. This is a safer deployment candidate than `0.50`, while materially stronger than current `0.05`.

## Next Steps

1. Validate `alpha=0.35` in `Model Analysis` cache/backtest using the current production prediction flow.
2. If stable, update `THESIS_HYBRID_ALPHA` from `0.05` to `0.35` and regenerate upcoming predictions.
3. Keep `alpha=0.05` as a conservative fallback if live CLV or recent rolling LogLoss worsens.
