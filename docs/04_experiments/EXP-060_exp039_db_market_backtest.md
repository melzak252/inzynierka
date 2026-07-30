# EXP-060 — EXP-039 DB History Backtest vs Opening/Mid/Close Market

> [!abstract]
> Recomputed point-in-time features for all eligible GOL.GG matches currently in the production database and applied the serialized EXP-039 model (`Sym-Cal LR-ElasticNet-W20-Binomial/exp-039`). Separately evaluated bookmaker market quality using opening, mid, and closing pre-match odds from `odds_snapshots` on mapped canonical matches.

## 1. Metadata & Context

- **Experiment ID**: EXP-060
- **Date & Time**: 2026-07-30 14:04 UTC
- **Tags**: #exp039 #market-evaluation #opening-odds #closing-odds #database-backtest
- **Environment**: Production Docker stack on `/data/inzynierka/app`, scheduler container; Python 3.12; scikit-learn artifacts loaded from `betting_app/models/`.
- **Reproducibility**: Deterministic chronological pass; no stochastic training. Script: `betting_app/scripts/backtest_exp039_db_market.py`.

## 2. Objective & Hypothesis

- **Problem Statement**: Recompute EXP-039 predictions for the updated production DB history and quantify market strength at three timing points: opening, mid, and close odds.
- **Hypothesis**: Closing odds should outperform opening odds; EXP-039 should remain competitive but may not beat market on recent production canonical matches.
- **Rationale**: Previous EXP-039 historical thesis evaluation was strong, but recent live app analyses showed market was hard to beat.

## 3. Experimental Setup

### Data Configuration

- GOL.GG prediction universe: `41067` eligible matches, date range `2013-09-16` → `2026-07-29`.
- Market universe: mapped `canonical_matches` joined to `golgg_match_mappings` / `result_source_match_id`, with non-live `odds_snapshots` before canonical start time.
- Common model+market sample: `408` matches, date range `2026-05-29` → `2026-07-29`.
- Market aggregation: per bookmaker, select earliest pre-match snapshot = opening, middle chronological snapshot = mid, latest pre-match snapshot = close; average no-vig probabilities across bookmakers.
- Orientation: canonical team A vs GOL.GG team1 inferred from finished result orientation for mapped historical rows.

### Model Details

- Model: `Sym-Cal LR-ElasticNet-W20-Binomial/exp-039` final serialized artifacts.
- Features: 46 total — rating/uncertainty features, W20 rolling features, and binomial series-probability features.
- Prediction: point-in-time chronological DB features; final pipeline + Platt calibrator; symmetric order correction.


### Exact Calculation Procedure

1. **Load historical GOL.GG matches from the production DB**
   - Source tables: `golgg_matches`, `golgg_games`, `golgg_game_players`.
   - Matches are processed chronologically by `(date, match_id)`.
   - Draws, matches without games, and matches without a usable first-game roster are skipped.
   - Team/player orientation is taken from the first game: `golgg_games.team1_id/team2_id` and `golgg_game_players.side IN ('t1','t2')`.

2. **Generate point-in-time EXP-039 features**
   - Before each match, call the same rating stack used by the thesis pipeline to obtain pre-match rating features.
   - W20 features are computed only from prior matches already seen in the chronological pass.
   - Binomial series features are derived from the pre-match base probability and `best_of`/series format.
   - After prediction features are stored, the rating and rolling-history state is updated with the observed games from that match.
   - This prevents feature leakage from future matches into earlier predictions.

3. **Apply the fixed final EXP-039 artifact**
   - Load `sym_cal_lr_elasticnet_w20_binomial_pipeline.joblib` and `sym_cal_lr_elasticnet_w20_binomial_calibrator.joblib`.
   - Compute original-side probability from the pipeline.
   - Build a swapped team-order feature vector and compute swapped-side probability.
   - Apply symmetry correction: `p_sym = 0.5 * (p_original + (1 - p_swapped))`.
   - Apply Platt calibration on `logit(p_sym)` to obtain final `p_team1`.

4. **Join model predictions to canonical market data**
   - Direct market comparison uses only matches mapped between GOL.GG and canonical DB rows via `golgg_match_mappings` or `canonical_matches.result_source_match_id`.
   - Canonical ground truth is `canonical_matches.winner_side`; model probability is inverted when canonical team A corresponds to GOL.GG team2.
   - This produces the common model+market sample used for market timing comparison.

5. **Construct opening/mid/closing market probabilities**
   - Source table: `odds_snapshots` where `market_type='match_winner'`, `is_live=0`, odds are valid, and `scraped_at <= match_start`.
   - For each match/bookmaker pair:
     - **Opening** = earliest valid pre-match snapshot.
     - **Mid** = middle chronological valid pre-match snapshot.
     - **Close** = latest valid pre-match snapshot before match start.
   - Convert odds to no-vig probabilities: `p_a = (1/odds_a) / ((1/odds_a) + (1/odds_b))`.
   - Average no-vig probabilities across bookmakers to get one market probability per match/timing point.
   - Raw implied probabilities are also saved for diagnostics, but no-vig metrics are treated as headline results.

6. **Compute metrics**
   - EXP-039 full-history metrics use target `team1_win` on all eligible GOL.GG matches.
   - Common market metrics use target `canonical team_a won` on the mapped canonical sample.
   - Metrics: LogLoss, Brier, ROC-AUC, and accuracy at threshold `0.5`.
   - All probabilities are clipped to a safe `(0,1)` interval before LogLoss.

> [!bug]
> This is not an out-of-fold retraining backtest. The final serialized EXP-039 model/calibrator is applied to recomputed historical DB features. Use OOF thesis results for strict training-period claims.

> [!bug]
> The first implementation used `rebuild_ratings.load_matches()` and only joined 109 market matches because recent GOL.GG rows often had missing/alias `golgg_matches.team*_id`. The final script uses first-game `golgg_games.team*_id` and first-game `golgg_game_players.side=t1/t2` rosters, producing 408 common market matches.

## 4. Results & Metrics

### EXP-039 on all DB GOL.GG matches

| Slice | N | LogLoss | Brier | AUC | Accuracy |
|---|---:|---:|---:|---:|---:|
| All history | 41067 | 0.5880 | 0.2016 | 0.7535 | 0.6871 |
| Since 2020 | 30970 | 0.5826 | 0.1996 | 0.7581 | 0.6891 |
| Since 2021 | 26843 | 0.5793 | 0.1982 | 0.7614 | 0.6916 |
| Since 2024 | 11260 | 0.5570 | 0.1891 | 0.7833 | 0.7062 |
| Since 2026 | 2688 | 0.5492 | 0.1859 | 0.7926 | 0.7065 |

### Market timing vs EXP-039 on common mapped sample

| Predictor | N | LogLoss | Brier | AUC | Accuracy | Avg books | Avg margin |
|---|---:|---:|---:|---:|---:|---:|---:|
| EXP-039 | 408 | 0.5792 | 0.1971 | 0.7654 | 0.6887 | — | — |
| Market open no-vig | 408 | 0.5830 | 0.1994 | 0.7590 | 0.6961 | 3.72 | 0.0874 |
| Market mid no-vig | 408 | 0.5768 | 0.1968 | 0.7653 | 0.6912 | 3.72 | 0.0874 |
| Market close no-vig | 408 | 0.5659 | 0.1920 | 0.7771 | 0.7132 | 3.72 | 0.0873 |

Raw implied probabilities were also computed in `reports/exp039_db_market_backtest_v2/summary.json`; they are included for diagnostics but no-vig is the cleaner probability metric.

## 5. Analysis & Discussion

- EXP-039 remains strong on the full DB history: all-history LL `0.5880`, since-2026 LL `0.5492`.
- On the recent mapped canonical market sample, closing market is best: close no-vig LL `0.5659` vs open no-vig LL `0.5830`.
- EXP-039 on the same common sample has LL `0.5792`, worse than close no-vig but roughly comparable to open/mid market in ranking strength.
- The market improves monotonically from open → mid → close in LogLoss/Brier/AUC, supporting the hypothesis that information accumulates into close odds.

## 6. Conclusion & Next Steps

> [!check]
> The updated DB backtest now covers `41067` EXP-039 predictions and `408` common model+market matches.

- For live product, continue treating market close/no-vig as a very strong baseline.
- If using EXP-039 with odds, use it as a residual/early-market feature rather than replacing market probabilities.
- Next experiment: evaluate whether EXP-039 adds value specifically over **opening** odds via calibrated residual blend, because close odds already dominate on recent mapped data.

## Artifacts

- Script: `betting_app/scripts/backtest_exp039_db_market.py`
- Summary JSON: `reports/exp039_db_market_backtest_v2/summary.json`
- Common-sample CSV: `reports/exp039_db_market_backtest_v2/exp039_market_common.csv`
- Market timing CSV: `reports/exp039_db_market_backtest_v2/market_open_mid_close.csv`
