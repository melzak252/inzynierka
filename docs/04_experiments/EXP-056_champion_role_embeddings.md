# EXP-056 — Champion-role embedding pipeline

> [!abstract]
> Goal: create leakage-safe champion-role embeddings from GOL.GG completed games, prioritising current meta data from the last 90 days and falling back to older windows for sparse champions. This experiment prepares input features for the next context-aware PlayerGameEncoder.

## Metadata

- **Experiment ID:** EXP-056
- **Tags:** #champion-embeddings #golgg #context-aware-embeddings #meta #leakage-safe
- **Script:** `betting_app/scripts/build_champion_role_embeddings.py`
- **Primary artifact target:** `betting_app/models/ml/champion_role_embeddings/exp-056/`

## Objective

Build reusable champion-role embeddings that encode champion strength/style in the current meta while avoiding missing vectors for rarely played champions.

## Hypothesis

A champion-role representation based on recent GOL.GG games, with fallback to older history, will provide a better context signal for PlayerGameEncoder than raw champion IDs alone.

## Design

For each `champion_id + role`, compute aggregate statistics using the first sufficient pre-reference-date window:

1. 90 days;
2. 180 days;
3. 365 days;
4. all history before reference date.

If no champion-role examples exist, use role/global defaults.

The initial implementation stores standardised aggregate feature vectors. A later version can train a neural embedding/autoencoder on these aggregates.

## Success criteria

- Pipeline runs on production GOL.GG PostgreSQL data.
- Output covers most champion-role pairs with explicit fallback metadata.
- Artifact is deterministic and reusable by future player/match pipelines.
- Diagnostics identify sparse champions and the percentage of embeddings using each fallback level.

## Next steps after artifact

- Add champion-role vector lookup to PlayerGameEncoder dataset.
- Add player champion-pool summary features for pre-match prediction.
- Compare context-aware embeddings against EXP-054 and EXP-055.

## Results — initial artifact build

> [!check]
> Full production DB run succeeded on recovered GOL.GG PostgreSQL data. The artifact was written on the server under `betting_app/models/ml/champion_role_embeddings/exp-056/`.

- **Reference date:** `2026-07-30T00:00:00+00:00`.
- **Source rows:** `506,730` player-game rows after filtering from `2020-01-03T00:00:00+00:00` to `2026-07-29T00:00:00+00:00`.
- **Champion-role rows:** `612`.
- **Distinct champions:** `173`.
- **Roles:** `ADC, JUNGLE, MID, SUPPORT, TOP`.
- **Feature/vector dimension:** `46` aggregate features → `46` standardised embedding dimensions.
- **Fallback counts:** `{'180d': 34, '365d': 21, '90d': 125, 'all_history_decay': 432}`.
- **Median games per champion-role:** `26.0`.
- **Sparse pairs below min recent games:** `258`.
- **Shrinkage prior:** `20.0` role-default games; mean observed weight `0.517`.
- **Parquet:** `False`; CSV/JSON artifacts were written successfully.

### Artifact files

- `champion_role_embeddings.csv` — champion-role metadata, aggregate features, and `emb_000...` vectors.
- `metadata.json` — reproducibility metadata and diagnostics.
- `feature_fill_values.json` — median fill values used before standardisation.

### Interpretation

The fallback distribution confirms that many champion-role pairs are sparse in the current meta window: only 125 pairs had enough 90-day data, while 432 required all-history fallback. Because of this, the implementation applies empirical-Bayes shrinkage toward the role default so one-off off-role picks such as rare ADC versions of non-ADC champions do not produce extreme standalone vectors.

### Next implementation step

Add a lookup layer that joins `champion_id + role` vectors into the PlayerGameEncoder dataset. For pre-match use, aggregate each player’s recent champion pool into a player-level champion-style vector; for post-draft use, consume exact champion-role vectors for the selected draft.

