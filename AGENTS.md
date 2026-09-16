# Repository instructions

Scope: the entire EnsembleLegends repository. Updated: 2026-09-15.

This project predicts League of Legends match outcomes and simulates tournament probability distributions. It also contains an application for collecting odds, betting research, and recording manual bets. The application does not place bets automatically.

## 1. Start with the current state

1. Check the current branch and uncommitted changes. Do not reset, overwrite, or move someone else's work.
2. For modeling, read `docs/RESEARCH.md` and `conf/base/research_benchmark.json`. These are the current entry points; do not select the leading model by folder name or modification date.
3. For application work, read `betting_app/README.md` and the relevant service code. Configuration, the loaded artifact, and the actual inference path determine the running model; a Markdown description alone does not establish this.
4. Before a new experiment, check previous results and rejected hypotheses referenced in `docs/RESEARCH.md`.
5. Execute the agreed scope. The user's current request can authorize a previously deferred idea; do not ask for the same authorization again.

The handoff snapshot below is dated. It explains the current research state, not the live server state. Verify manifests and artifacts before updating results, and keep this handoff current when the direction or canonical inputs change.

## Current research handoff — read before starting work

### What we are trying to achieve

The user wants a strong pre-match probability model that can also produce trustworthy tournament distributions: wins, qualification, placements, and tournament winners. Matching or beating bookmakers' opening probabilities is a research objective, not an achieved production claim. Tournament forecasts must remain usable for new rosters and national teams without shared organization history. W20 is optional. Announced rosters may be known at tournament start; future draft and blue/red side generally are not.

The immediate priority is to stop repeating small, unsuccessful corrections and use one reproducible benchmark. The user explicitly requested repository cleanup and a handoff that another agent can understand without reading the conversation. Do not launch another architecture search before understanding the experiments below.

### What is complete, and what is not (Updated: 2026-09-16)

- **Current research reference:** causal A0, a mixture of rating experts and neural player-history experts.
- **Active operational model:** `Hybrid-Bayesian-Shrunk-A0-Market` (version `hybrid-a0-mkt-v1-a0.50`), combining A0 with opening bookmaker consensus in logit space. Standalone EXP-081 is retired from live inference.
- **Completed:** Canonical match benchmark run under `data/08_reporting/benchmark/run_001/` ($N = 11{,}550$).
- **Completed:** Bet qualification risk hardening in `betting_app/services/bet_qualification_service.py` (Rule A: EV ceiling cap $\le 0.25$ on odds $> 3.50$; Rule B: Bo1 discrepancy quarantine $|\Delta p| \ge 0.12$; Rule C: negative CLV drift quarantine $\le -0.015$). Yield after 12% Polish tax reaches $+32.35\%$ with $4.91\%$ max drawdown.
- **Completed:** Regional rating discount factor ($\gamma = 0.70$) and Best-of series projection in `src/ratings/family_calibrated_glicko2.py`, cutting cross-regional Log Loss by $-0.0409$.
- **Completed:** Production tournament simulation engine in `src/models/calibrated_tournament_model.py` with composite bracket calibration ($T = 1.12, \beta = 0.08, P_{\text{max}} = 0.88$), eliminating multi-round compounding and calibrating finals reach to $68.4\%$.
- **Completed:** Pre-match confirmed lineup ingestion in `betting_app/scrapers/lineup_scraper.py` (30–45 min prior).
- **Completed:** Full regression test suite passing: 303 tests in 9.49s.
- **Remaining/Diagnostic:** Tournament phase simulator remains in diagnostic mode for commercial futures betting until independent point-in-time publication verification of historical rulebooks is completed across all legacy tiers.
### Current numbers and why the cohorts differ

The frozen source contains **41915 series and69370 maps**. The corrected feature bank has **40636 target rows**. Annual test forecasts cover **11550 matches in2024–2026**, including **2673 matches with verified archival OPEN odds**. These are match counts, not independent tournament editions.

Original039 cannot predict every target because its native inputs require historical support and usable W20. On the **9907 common eligible test matches**, the latest rebuilt comparison is:

| Model | Log loss | Losses with LL≥2.5 |
|---|---:|---:|
| Calibrated Elo players |0.591198|29|
| Calibrated Glicko players |0.577998|36|
| Annual039 research derivative |0.567337|16|
| Causal A0 |0.559920|30|

On the complete11550 cohort, A0 has LL0.551246 and calibrated Glicko0.575888.039 has1643 missing forecasts. Never compare039's9907-row metric with A0's11550-row metric as if they used the same matches. A0 improves average loss;039 has fewer deep losses. Neither observation alone selects a production model.

### Where the actual research artifacts live

Reusable work now belongs in this repository. Much of the earlier research code and data lives in a separate local research archive. Resolve its root from `data/research_root.txt`, `ENSEMBLE_RESEARCH_ROOT`, or `--research-root`; do not search the whole filesystem or hardcode a personal home directory.

The following paths are **relative to that research root**, unless explicitly marked repository-relative:

| Need | Location |
|---|---|
| Current ready-to-score joined cohort | `rating-foundation-20260915/data/08_reporting/paired.parquet` |
| Current baseline report and audited metrics | `rating-foundation-20260915/RAPORT.md`, `data/08_reporting/metrics.json`, `data/08_reporting/numeric_audit.json` within that directory |
| Rebuilt native039/rating features and eligibility reasons | `rating-foundation-20260915/data/04_feature/legacy.parquet` and `legacy_completed.json` |
| Annual039 checkpoints and calibration records | `rating-foundation-20260915/data/06_models/` |
| Annual baseline prediction output | `rating-foundation-20260915/data/07_model_output/predictions.parquet` |
| Corrected canonical feature bank | `a0-phase-walkforward-20260914/data/04_feature/release_corrected_bank/` |
| Bank contents | `metadata.parquet`, `arrays.npz`, `history.npy`, `mask.npy`, `champions.npy`, `release_days.json`, `completed.json` inside that bank |
| Causal A0 checkpoints | `a0-phase-walkforward-20260914/data/06_models/causal_a0/` |
| Causal inference adapter | `a0-phase-walkforward-20260914/code/causal_predictor.py` |
| A0/player-history implementation used by the research runs | `nonlinear-history-20260912/code/src/models/` and `nonlinear-history-20260912/code/scripts/temporal_player_features.py` |
| Rebuilt baseline training/replay recipe | `rating-foundation-20260915/code/baselines.py` and `code/build_legacy_features.py` |
| Detailed next regional experiment audit | `rating-foundation-20260915/REGION_PLAN.md` |
| Latest failed form/roster corrections | `roster-form-20260915/RAPORT.md` and `architecture-audit.md` |
| Tournament coverage and limitations | `a0-phase-walkforward-20260914/RAPORT.md` |
| Original frozen GOLGG source, repository-relative | `data/artifacts/golgg-database-recovery-20260909/matches.json` |

The benchmark manifest pins the current scoring input and evidence hashes. Its joined table is the convenient scoring input, not a replacement for the feature bank or original source. Do not retrain from it as though its probabilities and labels were raw causal features.

### What the model already knows

A0 already receives player ratings, experience/inactivity information, roster coplay, optional organization/W20 context, and an attention representation of the last16 maps per player. Historical tokens include age, role, statistics, and opponent rating. Adding another feature with one of those names is not automatically new information.

A specific limitation remains: historical W20 averages organization maps; it does not individually weight every historical map by similarity to the current five. However, a later correction to the final probability using roster-weighted form did not improve overall results. That failure does not prove a redesigned history encoder cannot help.

### Experiments not to repeat blindly

- `roster-form-20260915`: organization form, roster-overlap weighting, inactivity correction, and opponent-adjusted form on6908 matches across21 monthly windows. No overall improvement over A0; retain the negative result.
- `unified-ratings-20260911/WYNIKI.md`: combining player ratings with an organization correction preserved much of the quality, but did not establish a general improvement over attention. Neural aggregation/performance improved its own new Glicko filter but still lost to the existing Glicko baseline.
- `opponent-history-20260912/WYNIKI.md`: opponent-conditioned history retrieval was trained; results were not consistently better across full-history and timestamped market cohorts. Do not propose it as wholly untested.
- Earlier pair effects, lineup smoothing, and local player GNN were tested. They did not establish a robust improvement. References are in `research-ratings-20260910/raport.md`; implementations also exist in repository `scripts/experiment_graph_relations.py` and `scripts/experiment_full_graph_glicko2.py`.
- Repeated temperature/profile corrections and lower tail counts did not reliably improve total probabilistic error. Do not equate crossing the LL2.5 threshold with solving the underlying error.

### Next concrete research task

Continue with a controlled **player-only versus player-plus-competition-family** rating comparison using the corrected release policy, same target roster scenario, and identical player-update semantics.

First read `rating-foundation-20260915/REGION_PLAN.md` and repository `src/ratings/family_calibrated_glicko2.py`, `src/ratings/glicko2_core.py`. The existing family bridge compares a map-level probability with a majority-series outcome; resolve this BO likelihood mismatch before claiming a coherent regional model. Also handle historical substitutes, mixed affiliations, inactivity queries, and transfers explicitly. A competition family is not a player's nationality.

Freeze the control and regional variant before scoring. Test chronology, side symmetry, missing affiliations, and absence of future information first. Then generate forecasts and feed them into the canonical benchmark. Add roster/pair effects only after this comparison establishes what the regional component contributes. Integrating a candidate into tournament simulation requires a separate phase evaluation.

## 2. Project map and sources of truth

| Path | Purpose |
|---|---|
| `docs/RESEARCH.md` | Research status, current artifacts, limitations, completed experiments, and next steps. |
| `conf/base/research_benchmark.json` | Versioned benchmark manifest: sources, hashes, models, and cohorts. |
| `scripts/run_model_benchmark.py` | Main entry point for model comparisons. |
| `src/analysis/` | Shared metric and evaluation definitions; extend these instead of copying them. |
| `src/ratings/`, `src/models/` | Ratings, models, features, and prediction contracts. |
| `src/models/tournament_*.py`, `scripts/simulate_tournament.py` | Tournament models and tools; inspect the scope of each module. |
| `scripts/` | Pipelines and historical experiments, indexed in `scripts/README.md`. |
| `betting_app/api/`, `betting_app/services/` | API and application logic. |
| `betting_app/scrapers/`, `betting_app/scheduler/` | Data collection and operational jobs. |
| `betting_app/ml/` | Application training, inference, and evaluation pipelines. |
| `betting_app/models/`, `betting_app/alembic/` | Data models, artifacts, and migrations; inspect the specific file. |
| `client/` | React/TypeScript frontend. |
| `data/` | Local, usually ignored datasets and outputs. |
| `docs/future_ideas.md` | Deferred ideas catalog, when relevant to the task. |

### Distinguish model identities

- **Causal A0**: the research reference model, not necessarily the model deployed in the application.
- **Frozen EXP-039**: an immutable historical artifact. Never overwrite it through training.
- **Annual039 derivative**: a retrained research recipe, separate from frozen039.
- **Operational model and market hybrid**: identify them from current configuration, code, and artifacts. Do not attribute A0 results to them.
- The label “Glicko” in older results may refer to a Glicko-2 implementation. Specify the engine version, update rules, roster aggregation, and calibration.

## 3. One benchmark

Run from the repository root:

```bash
.venv/bin/python scripts/run_model_benchmark.py --suite --doctor
.venv/bin/python scripts/run_model_benchmark.py --suite --output-dir data/08_reporting/benchmark/run_001
```

Replace `run_001` with a new, nonexistent run name. The research archive location is resolved from `--research-root`, then `ENSEMBLE_RESEARCH_ROOT`, then the ignored file `data/research_root.txt`.

- Extend the existing runner, modules, manifest, and tests. Do not create another competing benchmark script inside a dated experiment directory.
- Suite mode rescores stored match predictions. It does not train models or rerun walk-forward prediction generation.
- Tournament phases, EV/CLV/Kelly, and prospective confirmation are currently `NOT_RUN`. A reference to an earlier report is not a new execution of that evaluation.
- Neither a `DEVELOPMENT_ONLY` report nor an older automatic gate result authorizes production use.
- A custom candidate must satisfy the contract and coverage described in `docs/RESEARCH.md`; do not silently reduce the cohort to a convenient intersection.
- Do not change the manifest or hashes merely to pass validation. Changed data requires an explicit new version and an impact assessment.

## 4. Running experiments

Before training, record the hypothesis, control, fixed variants, budget, TRAIN/CAL/TEST partitions, and success criterion. Isolate changes sufficiently to attribute their effects; do not introduce a graph, a new rating engine, and new calibration simultaneously.

- Evaluate chronologically using expanding or rolling walk-forward windows. State the rating-update, model-training, and calibration schedules separately.
- Shuffling examples **within an already closed TRAIN partition** is allowed for a static model. Never introduce future information into TRAIN or reorder events that update rating state.
- Use all valid, available historical matches; odds availability must not determine the training history.
- Evaluate on identical populations and side orientations. Missing forecasts require explicit reasons and counts; they are not zero loss. Clearly label comparisons across different populations.
- Select hyperparameters, calibration, and hybrid weights before the evaluated window. Parameters fitted diagnostically on TEST must not improve forecasts scored on that same TEST.
- Individual failures are diagnostic examples. Do not create exceptions for team names, known outcomes, or a few selected tail losses.
- Report negative results too. Update research status instead of repeating a rejected experiment under a new name.
- Do not inspect protected prospective outcomes during development. Repeatedly examined historical years remain development data even when the split is chronological.

### Metrics and uncertainty

Use log loss and Brier as the primary metrics, supplemented by AUC, accuracy, calibration, sample counts, and tail losses. Apply the same explicit probability policy to headline metrics, paired differences, and profiles; do not hide extreme errors by clipping only part of a report.

- Report slices by time, BO, league/family, experience, roster, confidence, and signal disagreement. Unknown profiles remain unknown.
- For matches, use paired monthly-block bootstrap with at least 5000 resamples; report block counts, the match-weighted difference, and the equal-block difference. Check tournament sensitivity and name the actual blocking unit.
- For simulations, aggregate and resample entire tournament editions. Origins, teams, and groups within one edition are not independent tournaments.
- A difference interval containing zero establishes neither improvement nor equivalence. The fraction of resamples with Δ≥0 is not automatically a classical p-value.
- ECE, calibration slope, and tail counts have no standalone universal “production” threshold. Predeclare project criteria and account for sample size and repeated development.
- Negative ΔLL on one cohort does not establish bookmaker-level quality. Adoption also requires information availability, coverage, simulator correctness, and independent confirmation.

## 5. Information availability and sports contracts

For forecasts with actual timestamps, require timezone information and:

```text
source/release time <= data_cutoff_at <= predicted_at < target_start_at
```

TRAIN and CAL labels must be released before their respective origins. The date a match was played is not always the date its result became available. In a daily research scenario, preserve `effective_release_day < prediction_day` and label it as a scenario, without certifying publication times.

- An announced roster may be an input. The actual five players read from a later match are only an explicit scenario unless earlier announcement is evidenced. Otherwise use the previously known roster or a model of roster uncertainty.
- W20 remains optional in the model being developed. New rosters and national teams must work without shared organization history.
- Blue/red side and draft are not known for an ordinary pre-match forecast. Use them only when released before the specific cutoff. A/B is data orientation, not map side.
- Predict before updating from the result. Update opponents from the same prior state. Queries for hypothetical matchups must not mutate history.
- Preserve player identities, academy/main-team distinctions, and symmetry p(A,B)+p(B,A)≈1. Do not reverse odds a second time after side alignment.
- Map probability and series probability are different quantities; do not apply the BO projection twice or train a map likelihood on a whole-series outcome without justification.
- A competition family is not a player's geography. Affiliations in cross-region evaluation must come from previously available information.

### Tournaments

Every declared phase requires an explicit format, target and origin lists, legal matchups, and reasons for missing coverage. Swiss, GSL, opponent selection, tiebreaks, and transitions require their own rules and oracles; do not substitute actual future opponents from history.

Preserve probability mass and joint outcome constraints. Distinguish phases, components, editions, and states. RPS for win counts, series length, and official placements are not interchangeable. Do not assess a whole tournament from match LL alone. Test that modifying future results, drafts, and rosters leaves earlier inputs and forecasts unchanged.

### Odds and finance

- OPEN is the primary market research reference; report CLOSE separately. Archived odds without timestamps do not establish equal-time information availability.
- The sports model does not use odds as inputs. A hybrid may use only odds available at its cutoff and has a separate identity. Later CLOSE may be used for CLV, not for an earlier decision.
- At a betting decision, both the forecast and selected odds must already be available, and the match must not have started. Their arrival order depends on the explicit execution policy; do not impose one ordering on every analysis.
- Do not alter a forecast merely because it disagrees with an underdog price. Bet qualification limits are a separate, explicit policy, not a rule for “correcting” probabilities.
- The ledger reserves stakes, keeps overlapping bets open, and settles only after result availability. Kelly uses free capital; state the assumed settlement times.
- Distinguish historical reconstruction, simulated execution, and recorded production decisions.
- Tax is a fraction, such as 0.12. Persist money as Decimal/Numeric; settlement must be idempotent. Bet, balance, and wallet transaction changes commit atomically.

## 6. File organization and reproducibility

Store new artifacts by stage:

```text
data/01_raw/             immutable sources
data/02_intermediate/    parsing and cleaning
data/03_primary/         canonical data
data/04_feature/         features with cutoff validation
data/05_model_input/     partitions and model inputs
data/06_models/          versioned models and calibrators
data/07_model_output/    stored predictions
data/08_reporting/      benchmarks and reports
```

This is an organizational convention, not a claim that the entire project has migrated to Kedro. Each pipeline records input provenance, hashes, configuration, code version, scope, and validation results. Do not hardcode personal paths in reusable modules.

Do not move historical artifacts in bulk without auditing paths and hashes. Preserve raw data, frozen models, historical evidence, and synced `sources/` unchanged. Develop new experiment code in the repository; do not copy the whole project into another dated directory.

Update existing documentation. Record deferred ideas in `docs/future_ideas.md`, retaining existing identifiers and status; a catalog entry is not an executed experiment.

## 7. Application safety and Git

- Do not expose `.env`, credentials, or dump contents. Do not add datasets, secrets, or generated artifacts to Git.
- Tests must not use the user's configured database. Validate migrations on an empty, isolated PostgreSQL/Timescale database; SQLite does not prove PostgreSQL behavior.
- Inspect current models, migrations, and init SQL before schema changes. Do not assume consistency from an old audit or `alembic_version` alone; do not create another competing schema path.
- Do not run real scraping, the scheduler, live migrations, or server restarts outside the user's authorized scope. Test specific functions in isolation.
- Do not expose an unverified API beyond loopback. Do not run cleanup tools that terminate unrelated browser processes.
- Verify current Docker/GPU configuration and image build context before running or publishing.
- `dev` is the integration branch. Check the actual branch; do not switch or reset a dirty checkout merely to match a branch name. New work may be isolated in a branch/worktree from the appropriate base.
- Do not push development directly to `main`. Commit, push, merge, and deploy within the authorized scope after validation. Do not include someone else's changes in a commit.
- Deployment sequence: local change and tests → review → Git → server-state inspection → fast-forward and only necessary services → health checks. Do not treat a hostname or path once recorded here as current configuration.
- Do not use `git reset --hard`, `git clean`, or ad hoc server edits as deployment shortcuts. Preserve unexpected changes.

## 8. Verification and completion

Run checks appropriate to the change; do not fix unrelated issues merely because an old audit listed them. Reproduce the failure, then fix it and check regressions. Do not hide errors behind broad exception handlers or empty results.

| Change | Required verification |
|---|---|
| Benchmark | Metrics, cohorts, dates, missingness, and extreme-probability tests; agreement with recorded full-cohort results. |
| Rating/features/model | Chronology, symmetry, cold start, reproducibility, and a new versioned benchmark. |
| Simulator | Small independent oracles, probability mass, legal matchups, absence of future state, and edition-level blocking. |
| API/service | A test reproducing the behavior and an exercise of the changed interface. |
| Migrations | Empty isolated database → migrations → test of the affected path. |
| Scheduler/scraper | Dependencies, timeouts, or parser fixtures; no automatic live execution. |
| Finance | Overlapping bets, free capital, idempotency, and atomicity. |
| Frontend | `npm run build`, `npm run lint` in `client/`, and browser verification of the changed behavior. |
| Documentation | Read the complete revised document and verify paths and commands. |

Basic commands:

```bash
.venv/bin/python -m pytest -q betting_app/tests/test_research_benchmark_suite.py betting_app/tests/test_model_benchmark.py
.venv/bin/python -m pytest -q betting_app/tests
```

The first covers the benchmark; the second is broader application regression when justified by the change. Report dependency, database, or environment limitations from current execution, not as permanent exceptions. Do not install dependencies or change the environment unnecessarily.

When finishing, state what changed, what actually ran, the result, material limitations, and remaining work. Update `docs/RESEARCH.md` when research status changes. Do not describe a plan as an executed test or a completed process as work still running in the background.
