# Betting app ML layer

This package is the production-facing ML/data-science layer for the betting
application. It is deliberately kept outside `scripts/`, because those scripts
are thesis/research artefacts and should not be reorganized in-place.

Initial responsibilities:

- deterministic historical backtests against collected bookmaker odds,
- shared metrics for model-vs-market evaluation,
- explicit staking and odds-selection policies,
- future model registry, retraining, shadow prediction and promotion workflows.

Current first slice:

- `backtesting.engine`: evaluates existing model probabilities against historical
  odds and settled match results,
- `backtesting.loaders`: read-only loaders from current application tables
  (`canonical_predictions`, `canonical_matches`, `odds_snapshots`),
- `backtesting.comparison`: model-vs-market probability metrics using no-vig
  bookmaker probabilities,
- `backtesting.odds_selection`: decides **when** a simulated bet would have been
  placed from available snapshots,
- `backtesting.staking`: fixed / bankroll-percent / fractional Kelly stake sizing,
- `metrics`: probability and betting summary metrics.

CLI example:

```bash
python -m betting_app.ml.backtesting.cli \
  --model-name 'Sym-Cal LR-ElasticNet-W20-Binomial' \
  --model-version exp-039 \
  --include-stale \
  --days-back 365 \
  --min-ev 0.0 \
  --staking fractional_kelly \
  --json
```

The backtest output includes betting metrics (`bets`, `total_staked`, `roi`,
`hit_rate`, `max_drawdown`) and model-vs-market probability metrics
(`model_log_loss`, `market_log_loss`, `model_brier`, `market_brier`,
`model_accuracy`, `market_accuracy`).

Default anti-leakage assumptions:

- use finished matches only,
- use only odds snapshots mapped to the same `canonical_match_id`,
- ignore invalid odds (`<= 1.0`),
- by default take the latest pre-match quote per bookmaker,
- by default deduplicate predictions to the latest prediction per
  `(canonical_match_id, model_name, model_version)`, so stale prediction history
  does not simulate repeatedly betting the same match.

Next production slices should add:

1. model registry tables and artifact metadata,
2. weekly retraining runner with walk-forward validation,
3. shadow predictions for candidate models,
4. promotion gates comparing candidate vs production and market baselines,
5. API/UI reports for historical model-vs-bookmaker performance.

Design rule: add new production abstractions here first, then gradually make old
services delegate to them. Do not break scheduler/API flows while migrating.
