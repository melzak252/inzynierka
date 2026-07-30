# EXP-062 — Corrected EXP-039 Canonical Prediction Backfill

> [!abstract]
> This maintenance experiment replaces stale/mismatched historical `canonical_predictions` rows for `Sym-Cal LR-ElasticNet-W20-Binomial/exp-039` with corrected probabilities generated in EXP-060. The objective is to make the `Model Analysis` page use the same corrected EXP-039 predictions as the DB backtest.

## Metadata

- **Date:** 2026-07-30
- **Tags:** #exp039 #canonical-predictions #model-analysis #backfill
- **Script:** `betting_app/scripts/backfill_exp039_canonical_predictions.py`
- **Input:** `reports/exp039_db_market_backtest_v2/exp039_market_common.csv`
- **Report:** `reports/exp039_canonical_backfill/backfill_apply_report.json`
- **Model:** `Sym-Cal LR-ElasticNet-W20-Binomial / exp-039`
- **Features version inserted:** `exp060-db-backfill-v1`
- **Ratings version inserted:** `latest-full`

## Objective

The `Model Analysis` page was showing weak pure EXP-039 metrics because its historical canonical prediction rows were stale/mismatched. EXP-060 regenerated corrected point-in-time EXP-039 probabilities from the production DB. This backfill writes those corrected values into `canonical_predictions` for mapped historical canonical matches.

## Procedure

1. Load corrected market-common EXP-039 rows from `reports/exp039_db_market_backtest_v2/exp039_market_common.csv`.
2. For each row, use `canonical_match_id` and corrected `exp039_prob_team_a`.
3. Set:
   - `model_name = Sym-Cal LR-ElasticNet-W20-Binomial`
   - `model_version = exp-039`
   - `prob_a = exp039_prob_team_a`
   - `prob_b = 1 - prob_a`
   - `predicted_at = canonical_start_time - 1 minute`
   - `features_version = exp060-db-backfill-v1`
   - `ratings_version = latest-full`
4. Before writing, create backup table with all old target rows.
5. Delete old EXP-039 rows for target canonical match IDs.
6. Insert one corrected EXP-039 row per target match.
7. Refresh Model Analysis cache with `betting_app.scripts.refresh_model_analysis_cache`.

## Database Write Summary

| Field | Value |
|---|---:|
| Candidate matches | 408 |
| Old rows deleted | 14,120 |
| Corrected rows inserted | 408 |
| Old target matches before | 371 |
| Corrected target matches after | 408 |
| Backup table | `canonical_predictions_exp039_backup_20260730_150304` |

> [!bug]
> The old data had many duplicate/stale EXP-039 prediction rows per historical canonical match. Since `Model Analysis` selects the newest row per model and match, stale values could dominate the page metrics.

## Verification After Cache Refresh

`Model Analysis` reference for pure EXP-039 after the backfill:

| Metric | Value |
|---|---:|
| N matches | 412 |
| LogLoss | 0.5819 |
| AUC | 0.7633 |

Per-horizon EXP-039 metrics after refresh:

| Horizon | LogLoss | AUC |
|---|---:|---:|
| 0-2h | 0.5816 | 0.7664 |
| 2-6h | 0.5815 | 0.7638 |
| 6-12h | 0.5793 | 0.7659 |
| 12-24h | 0.5764 | 0.7699 |
| 24-48h | 0.5554 | 0.7886 |
| 48h+ | 0.5346 | 0.8061 |

> [!check]
> The page no longer shows the earlier weak EXP-039 values around LL `0.63–0.68`; corrected values now align with EXP-060 expectations.

## Rollback

If needed, restore from backup table `canonical_predictions_exp039_backup_20260730_150304`. The backfill did not touch EV-linked hybrid predictions (`Hybrid-Thesis-Market/a0.50-t0.80`) and did not modify `model_ev_signals`.
