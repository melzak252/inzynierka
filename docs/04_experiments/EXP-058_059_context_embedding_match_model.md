# EXP-058/059 — Walk-forward Context Embedding Match Model

> [!abstract]
> Objective: test whether the newly built walk-forward `TeamContextEmbeddings` (EXP-057) and `ChampionRoleEmbeddings` (EXP-056) add measurable predictive value at match level before investing in a larger context-aware neural player encoder.

## Metadata
- **Date:** 2026-07-30
- **Tags:** #champion-embeddings #team-context #walk-forward #match-model #market-comparison
- **Environment:** production server `/data/inzynierka/app`, scheduler container, PostgreSQL/TimescaleDB live database.
- **Reproducibility:** random seed `42`; walk-forward snapshots `2026-01-01` → `2026-07-30`.

## Objective & Hypothesis
- **Problem:** Determine whether champion-pool + team/opponent context embeddings improve match prediction quality.
- **Hypothesis:** Context embeddings should improve calibration/log loss versus the leakage-safe strength baseline by capturing current team style, roster/champion-pool tendencies, and opponent-adjusted context.
- **Rationale:** Champion-role UMAP/cluster diagnostics looked coherent; team embeddings encode recent form/style. A match-level LR is a cheap signal test before training a more expensive neural encoder.

## Setup
- Script: `betting_app/scripts/evaluate_context_embedding_model.py`.
- Dataset: GOL.GG completed series from `2026-01-01` onward.
- Leakage control: for each match at date `T`, use latest snapshot with `reference_date <= T`; every snapshot was built with source rows `date < reference_date`.
- Features:
  - EXP-046 leakage-safe strength features.
  - Team/opponent context embedding deltas and absolute deltas (`52` team embedding dimensions).
  - Recent champion-pool embedding deltas and absolute deltas (`48` champion-role dimensions averaged over team champion usage in previous 90 days).
- Model: ElasticNet LogisticRegression with order augmentation and OOF calibration.
- Best diagnostic config: `C=0.005`, `l1_ratio=0.7`, `initial_train_size=300`, `test_size=100`, `step_size=100`.

## Results
| Model | OOF N | LogLoss | Brier | AUC | Accuracy |
|---|---:|---:|---:|---:|---:|
| Strength baseline | 2388 | 0.6378 | 0.2228 | 0.6937 | 0.6369 |
| Strength + context embeddings | 2388 | **0.6341** | **0.2215** | 0.6931 | 0.6315 |

Live mapped common subset (`N=412`, date range 2026-05-29 → 2026-07-29):
| Model/source | N | LogLoss | AUC | Accuracy |
|---|---:|---:|---:|---:|
| Context model calibrated | 412 | 0.6691 | 0.6525 | 0.5947 |
| Strength baseline calibrated | 412 | 0.6820 | 0.6513 | 0.6019 |
| Market no-vig | 250 | **0.5732** | **0.7674** | **0.7080** |
| Hybrid old `a0.50-t0.80` | 231 | 0.6008 | 0.7385 | 0.6883 |
| EXP-039 | 232 | 0.6292 | 0.7136 | 0.6940 |

Coverage:
- Rows: `2688`; features: `252`.
- Team embedding coverage: ~65% per side.
- Champion-pool coverage: ~65% per side.
- Snapshots: 8 monthly/current snapshots.

## Interpretation
> [!check]
> Context embeddings have **some signal**: under strong regularization they improve OOF LogLoss/Brier slightly versus the strength baseline.

> [!bug]
> The signal is not yet strong enough for deployment. On live mapped matches the context model is far behind market no-vig and behind existing EXP-039 / old hybrid comparisons.

Main likely causes:
1. Coverage is only ~65% because many teams are new/sparse in 2026 snapshots.
2. The current match-level LR uses aggregate deltas only; it does not yet learn player-specific interactions.
3. Champion-pool context is pre-match historical usage, not draft-aware exact champion picks.
4. The live mapped subset is recent and market is very strong; standalone model should be treated as residual information, not replacement.

## Conclusion & Next Steps
- Do **not** deploy the context embedding model directly.
- Keep EXP-056/057 artifacts; they are useful features.
- Next experiment should train the real `ContextAwarePlayerGameEncoder` where each player-game vector receives champion-role, own-team, and opponent-team context, then aggregate player embeddings at match level.
- Final production candidate should be evaluated as a **market residual/shrink model**, not as a pure standalone probability model.
