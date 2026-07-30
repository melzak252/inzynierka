# EXP-057 — Team/Opponent Context Embeddings

> [!abstract]
> Goal: create leakage-safe walk-forward team context embeddings from completed GOL.GG games.  The vectors summarise recent form, playstyle, roster/champion-pool proxies, and opponent-adjusted team performance.  They will be used both as match-level features and as `own_team_embedding` / `opponent_team_embedding` context for the next PlayerGameEncoder.

## Metadata

- **Experiment ID:** EXP-057
- **Date:** 2026-07-30
- **Tags:** #team-embeddings #opponent-context #golgg #walk-forward #leakage-safe
- **Script:** `betting_app/scripts/build_team_context_embeddings.py`
- **Report:** `reports/exp057_team_context_embeddings.json`
- **Server artifact target:** `betting_app/models/ml/team_context_embeddings/exp-057/`
- **Reproducibility:** deterministic aggregates; `StandardScaler`; no stochastic model training.

## Objective & Hypothesis

The current player/champion representations do not sufficiently encode team context.  A player stat line should be interpreted differently depending on team form and opponent strength.  This experiment creates the first reusable statistical team context embedding baseline.

**Hypothesis:** leakage-safe team embeddings based on recent GOL.GG games will provide useful context for future player-game encoders and match-level models, especially as `own_team` and `opponent_team` vectors.

## Experimental Setup

For each team at reference date `T`, the pipeline uses only games with `date < T`.

Window fallback rule:

1. use 90 days if at least `min_recent_games=10` team-games exist;
2. otherwise 180 days;
3. otherwise 365 days;
4. otherwise all history before `T` with exponential decay (`half_life=180d`).

Sparse team aggregates are shrunk toward a global team default with prior strength `12` games.

Feature groups:

- recent form: win rate, side rate, game duration;
- team output: kills, gold, towers, dragons, nashors;
- opponent-adjusted deltas: kill/gold/tower/dragon/nashor diff;
- pace: kills/min, deaths/min, gold/min, diff/min;
- player composition proxies: average KDA/KP/damage share/gold share/CSM/DPM/vision;
- roster/champion-pool proxies: team-game player/champion counts;
- recency and sample metadata.

## Results

> [!check]
> Full production DB run succeeded on recovered GOL.GG PostgreSQL data.  The artifact was written on the server under `betting_app/models/ml/team_context_embeddings/exp-057/`.

- **Reference date:** `2026-07-30T00:00:00+00:00`.
- **Source player-game rows:** `506,730`.
- **Source team-games:** `101,346`.
- **Team rows:** `2,092`.
- **Feature/vector dimension:** `52` aggregate features → `52` standardised embedding dimensions.
- **Fallback counts:** `{'90d': 192, '180d': 51, '365d': 180, 'all_history_decay': 1669}`.
- **Median games per team:** `36.0`.
- **Recent window:** `90` days.
- **Median recent games per team:** `0.0`.
- **Stale teams with no recent games:** `1,830`.
- **Sparse teams below `min_recent_games`:** `1,900`.
- **Walk-forward snapshots:** `8` monthly/current snapshots: `2026-01-01` through `2026-07-30`.
- **Parquet:** skipped due missing optional `pyarrow/fastparquet`; CSV/JSON artifacts were written successfully.

## Interpretation

The latest artifact intentionally includes all historical teams for lookup coverage, but most teams are inactive in the last 90 days.  Downstream pre-match pipelines should filter or prioritise teams with adequate `recent_games`, while still retaining fallback vectors for rare cases and historical backtests.

The high `all_history_decay` count is expected in esports data because many short-lived/renamed teams appear historically.  For active teams, the 90/180/365 fallback metadata should be used as a confidence indicator.

## Next Steps

1. Add lookup helpers that join `team_id` and `opponent_team_id` to the correct snapshot before match date.
2. Build EXP-058 context dataset joining player rows with champion-role, own-team, and opponent-team vectors.
3. Audit coverage for current live matches and historical OOF folds.
4. Train EXP-059 ContextAwarePlayerGameEncoder only after coverage/leakage checks pass.
