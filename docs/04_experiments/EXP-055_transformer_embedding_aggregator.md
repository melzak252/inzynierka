# EXP-055 — Transformer aggregator for PlayerGameEncoder histories

> [!abstract]
> Tested a small leakage-safe transformer over recent player-game embeddings as a replacement for the EXP-054 mean/std team aggregation. On the recovered live DB subset, the transformer underperformed both the simple embedding baselines and bookmaker no-vig market, so it is **not recommended for deployment** in this form.

## Metadata
- **Date:** 2026-07-30
- **Tags:** #player-embeddings #transformer #sequence-model #live-db #market-comparison
- **Environment:** `ensemblelegends-betting-scheduler`, `torch==2.13.0+cu130`
- **Device actually used:** CPU
- **Random seed:** PyTorch/sklearn defaults in script are deterministic only at split level; follow-up should add explicit seeds.
- **Script:** `betting_app/scripts/evaluate_transformer_embeddings_live_db.py`
- **Artifacts:**
  - `reports/exp055_transformer_recent.json`
  - `reports/exp055_transformer_recent_min40.json`

> [!bug]
> CUDA was not usable despite CUDA-enabled PyTorch. Host `nvidia-smi` failed with `Driver/library version mismatch`, and the scheduler container had no GPU device request (`DeviceRequests=null`, runtime `runc`). `torch.cuda.is_available()` returned `False`, so EXP-055 ran on CPU.

## Objective & hypothesis
- **Problem:** Mean/std aggregation of player-game embeddings may discard useful temporal and roster interaction information.
- **Hypothesis:** A small transformer over recent team player-game embedding sequences can learn recency/interaction patterns and improve match prediction compared with simple embedding aggregation.
- **Leakage rule:** for match date `T`, histories use only player-game embeddings observed before `T`; histories are updated after all matches on the same date.

## Setup
- Encoder artifact: `/app/betting_app/models/ml/PlayerGameEncoder/exp-049-recovered-20260729`
- Sequence representation: each team receives the last `seq_len=40` player-game latent vectors (`embedding_dim=64`). A shared `TransformerEncoder` encodes each side; head uses `[team1, team2, team1-team2, event-count features]`.
- Model: 1 transformer layer, `d_model=64`, `nhead=4`, dropout `0.15`, AdamW `lr=1e-3`, weight decay `1e-4`.
- Walk-forward evaluation; probabilities are raw neural probabilities, not Platt-calibrated.

## Results

### Recent run, `min_prior_events=20`
- Window: 2025-01-20 → 2026-07-29
- Rows built: 5,144; OOF rows: 2,144; folds: 2
- OOF metrics: LogLoss `0.6417`, Brier `0.2252`, AUC `0.6870`, Accuracy `0.6353`
- Live mapped subset, N=110:
  - Transformer: LogLoss `0.6589`, Brier `0.2325`, AUC `0.6451`, Accuracy `0.6182`
  - Market no-vig: LogLoss `0.4934`, Brier `0.1625`, AUC `0.8303`, Accuracy `0.7143`
  - EXP-039: LogLoss `0.5272`, AUC `0.8135`, Accuracy `0.7813`
  - Old stored hybrid a0.50: LogLoss `0.4973`, AUC `0.8380`, Accuracy `0.7813`

### Recent run, `min_prior_events=40` (no padding)
- Window: 2025-01-24 → 2026-07-29
- Rows built: 4,388; OOF rows: 1,588; folds: 2
- OOF metrics: LogLoss `0.6375`, Brier `0.2238`, AUC `0.6875`, Accuracy `0.6285`
- Live mapped subset, N=108:
  - Transformer: LogLoss `0.6681`, Brier `0.2346`, AUC `0.6623`, Accuracy `0.5833`
  - Market no-vig: LogLoss `0.4913`, Brier `0.1616`, AUC `0.8341`, Accuracy `0.7216`
  - EXP-039: LogLoss `0.5260`, AUC `0.8165`, Accuracy `0.7789`
  - Old stored hybrid a0.50: LogLoss `0.4956`, AUC `0.8412`, Accuracy `0.7789`

## Analysis
- The transformer learned some signal historically (`AUC≈0.69` OOF), but its rank quality and calibration are far below market and below previous simple embedding+strength results from EXP-054 (`LL≈0.5865`, AUC≈0.7531 full OOF).
- Removing padding did not improve results; the model still underperformed.
- Likely causes:
  - Too little recent labeled data for neural sequence training.
  - Recovered PlayerGameEncoder validation accuracy was weak, so latent histories may be noisy.
  - Model has no explicit roster/champion/role/time-decay tokens beyond latent order.
  - No calibration layer yet, but AUC gap shows calibration alone will not close the market gap.

## Conclusion
> [!check]
> The idea was tested end-to-end on the server. Current transformer aggregation is negative: do **not** deploy it and do not replace the market-shrink hybrid with this model.

## Next steps
- Fix CUDA first if further neural experiments are desired: resolve host `nvidia-smi` driver/library mismatch and add GPU device requests to the training container.
- If revisiting sequence modeling, test a simpler regularized temporal attention/GRU with explicit recency, roster, role, and champion tokens, plus calibration and nested validation.
- For production accuracy, continue prioritizing market-shrink/residual approaches over standalone neural models.
