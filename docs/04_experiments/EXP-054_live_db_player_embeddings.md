# EXP-054 — Live DB evaluation of PlayerGameEncoder embeddings

> [!abstract]
> Recovered/retrained the missing PlayerGameEncoder artifact on the production PostgreSQL/GOL.GG data and evaluated embedding-only and embedding+strength match models in chronological OOF mode. The embedding+strength model is usable historically (`OOF LogLoss=0.586530`, `AUC=0.753059`), but it does **not** beat the bookmaker no-vig market on the recovered live canonical/odds subset (`LogLoss=0.531786` market vs `0.625052` embedding+strength). Do not deploy it over the current market-shrink hybrid without further calibration/selection.

## Metadata

- **Experiment ID:** EXP-054
- **Date:** 2026-07-29T22:52:54.293964+00:00
- **Tags:** #player-embeddings #golgg #market-comparison #walk-forward #live-db
- **Environment:** server container `ensemblelegends-betting-scheduler`; Python `3.12.3` locally for logging; server run used `torch==2.13.0+cu130`, `scikit-learn==1.9.0`, CPU execution.
- **Random seed:** `42` via `StrengthModelConfig.random_state`.
- **Artifacts:**
  - Encoder: `/data/inzynierka/app/betting_app/models/ml/PlayerGameEncoder/exp-049-recovered-20260729`
  - JSON: `reports/exp054_embedding_live_db.json`
  - Script: `betting_app/scripts/evaluate_embedding_live_db.py`

## Objective & hypothesis

- **Problem:** Check whether the historical embedding approach (EXP-049/EXP-051 family) can improve current production predictions after recovering the correct DB volume.
- **Hypothesis:** PlayerGameEncoder embeddings plus leakage-safe strength features may outperform the deployed tabular thesis model and approach or beat the market on finished live matches.
- **Rationale:** Historical EXP-051 reported strong OOF metrics (`LogLoss≈0.5757`, `AUC≈0.7649`) and had beaten bookmaker no-vig on a historical odds subset. Production DB had lost the encoder artifact, so it had to be retrained from current recovered GOL.GG rows.

## Setup

### Data

- Player-game dataset: `506240` rows from `2020-01-03T00:00:00` to `2026-07-29T00:00:00`, `31200` matches, `5842` players.
- Embedding match dataset: `21848` rows, skipped `9095` due to `min_prior_player_games`.
- Strength dataset: `30943` rows, `47` leakage-safe features, date `2020-01-03T00:00:00+00:00` to `2026-07-29T00:00:00+00:00`.
- Hybrid dataset: `21848` rows, `434` features.

### Models

- `PlayerEmbedding-Match-LR/live-db-oof` — embeddings only, ElasticNet logistic regression with calibration and order augmentation.
- `Embedding-Strength-Hybrid-LR/live-db-oof` — embeddings plus DB-native strength features.
- Config: `initial_train_size=8000`, `test_size=3000`, `step_size=3000`, `logistic_c=0.05`, `l1_ratio=0.5`, `calibrate=True`, `collect_oof=True`.

> [!bug]
> The historical EXP-051 artifact `PlayerGameEncoder/exp-049-full` was missing from the server, so the encoder was retrained as `exp-049-recovered-20260729`. Also, exact EXP-051 parity is impossible here because legacy July `golgg_y_predicts.csv`/`odds.csv` feature inputs were not available on the server; this run uses DB-native leakage-safe strength features instead.

## Results

### Full chronological OOF

| Model | N | LogLoss | Brier | AUC | Accuracy |
|---|---:|---:|---:|---:|---:|
| Embedding-only calibrated | 13848 | 0.597594 | 0.205575 | 0.740768 | 0.681542 |
| Embedding+strength calibrated | 13848 | 0.586530 | 0.200931 | 0.753059 | 0.686742 |
| ELO baseline inside strength run | 13848 | 0.601163 | 0.207431 | 0.736115 | 0.672805 |

### Live canonical/market subset

| Predictor | N | LogLoss | Brier | AUC | Accuracy |
|---|---:|---:|---:|---:|---:|
| Market no-vig | 161 | 0.531786 | 0.178298 | 0.810705 | 0.714286 |
| Embedding+strength OOF calibrated | 180 | 0.625052 | 0.216360 | 0.709598 | 0.638889 |
| Embedding-only OOF calibrated | 180 | 0.641341 | 0.221876 | 0.700805 | 0.650000 |
| Old stored hybrid a0.50 | 157 | 0.547851 | 0.185850 | 0.801961 | 0.719745 |
| EXP-039 | 157 | 0.604305 | 0.203712 | 0.742810 | 0.719745 |

## Analysis

- Embedding+strength improves over embedding-only on full OOF (`0.5865` vs `0.5976` LogLoss), so the embeddings carry useful signal.
- On the smaller production market-aligned subset, market no-vig is much stronger (`0.5318` LL) than both embedding-only (`0.6413`) and embedding+strength (`0.6251`).
- The gap indicates domain/calibration mismatch: historical GOL.GG OOF signal is not enough to beat contemporaneous bookmaker prices on the recovered live slice.
- Because EXP-053 also found market-only or near-market blends best, this supports keeping production as a market-shrunk hybrid rather than replacing it with the embedding model.

## Conclusion & next steps

> [!check]
> Embedding pipeline was recovered and evaluated end-to-end on the restored production DB.

- **Do not deploy embedding model directly** as production predictor yet.
- Use it only as a candidate weak signal in a future meta-model with strict walk-forward calibration and market disagreement filters.
- Next experiment: calibrate EXP-039/embedding signals with softer temperatures (`T≈1.5–2.0`) and test a constrained market residual model that can abstain when model-market disagreement is high.
