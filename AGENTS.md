# AGENTS.md

## Scope

This file applies to the entire repository.

EnsembleLegends is both:

1. an engineering-thesis research codebase for predicting professional League of Legends match outcomes; and
2. a local betting-research application for collecting odds, comparing model probabilities with the market, and recording manual bets.

The application does **not** place bets automatically. Preserve that boundary.

Correctness and temporal integrity matter more than making an existing test pass. Do not hide data, migration, or model errors with fallbacks or special cases.

## Project map

| Path | Purpose |
|---|---|
| `src/ratings/` | Elo, Glicko-2, TrueSkill, OpenSkill, Plackett–Luce, and Thurstone–Mosteller rating systems. |
| `src/models/` | Shared model, symmetry, and feature utilities. |
| `src/analysis/`, `src/simulations/` | Research metrics and simulations. |
| `scripts/` | Historical thesis experiments, backtests, imports, and report generators. Many are one-off research scripts. |
| `betting_app/api/` | FastAPI backend and REST routers. |
| `betting_app/services/` | Canonical matching, odds persistence, mappings, inference, and automation logic. |
| `betting_app/scrapers/` | GOL.GG and bookmaker scrapers. |
| `betting_app/scheduler/` | APScheduler registry, task wrappers, and maintenance jobs. |
| `betting_app/ml/` | Retraining, inference, evaluation, backtesting, model registry, and promotion gates. |
| `betting_app/models/` | SQLAlchemy models and checked-in model artifacts. |
| `betting_app/alembic/` | Alembic migrations. The current chain is not safely replayable; see Known hazards. |
| `docker/timescale/init.sql` | A separate hand-written Timescale schema. It currently diverges from models and migrations. |
| `client/` | React 18 + TypeScript + Vite frontend. |
| `conf/base/` | Kedro and ML pipeline parameters. |
| `docs/` | Thesis plan, methodology, data contract, and experiment notes. |
| `docs/future_ideas.md` | Durable catalog of deferred proposals and their evidence, constraints, and promotion criteria. |
| `reports/` | Generated or curated evaluation outputs. |
| `data/` | Large local datasets and databases; normally ignored. Never commit them without explicit instruction. |

Primary operational entry points:

```text
uvicorn betting_app.api.main:app
python -m betting_app.scheduler
python -m betting_app.scripts.run_upcoming_prediction_pipeline --include-partial --operational-hybrid
python -m betting_app.scripts.rebuild_regional_ratings
python -m betting_app.ml.pipelines.exp040_retrain_pipeline
```

## Model architecture & active contracts

1. **Active operational prediction engine**:
   - **Pure model**: `Operational-PlayerTeamRatings-W20` (`v0.4-binom-series`).
     - Combines $70\%$ player rating consensus (Elo, Glicko-2 regional, TrueSkill, OpenSkill, Plackett–Luce, Thurstone–Mosteller for each 5-man roster), $20\%$ team rating consensus, and $10\%$ W20 rolling stats from GOL.GG.
     - Evaluates map probabilities and computes series outcomes using binomial series simulation (`series_probability`).
   - **Active betting hybrid**: `Hybrid-Operational-Market` (`v0.4-binom-series-a0.35-t0.80`).
     - Blends operational model probabilities ($T=0.80, \alpha=0.35$) with consensus no-vig market closing line ($1-\alpha=0.65$).
     - Powers the betting recommendations, EV signals, and live match boards.
   - **Rating contract**: `ratings-v2` (`family-calibrated-glicko2-v1`), featuring regional offset projection and Bayesian shrinkage across international and regional leagues.

2. **Historical thesis model (frozen baseline)**:
   - `Sym-Cal LR-ElasticNet-W20-Binomial / exp-039`
   - `exp-039` is frozen. Retained exclusively for retrospective, cohort-matched academic comparisons. Never overwrite or retrain this artifact.

3. **Candidate successor architecture (EXP-040)**:
   - `Hierarchical-Markov-VennAbers-EXP040` (`exp040-markov-va-v1`).
   - Combines Venn–Abers conformal multi-probability calibration, hierarchical Markov series simulation with side rotation, and Conformal Risk Control ($P_{\text{low}}$ lower-bound gating under the $12\%$ Polish turnover tax).
## Read before editing

Choose the relevant context rather than reading the entire repository:

- Project intent: `README.md`
- Operational application: `betting_app/README.md`
- Thesis scope: `docs/00_index.md`
- Deferred ideas and future work: `docs/future_ideas.md`
- Temporal data contract: `docs/02_data/01_data_sources_and_contract.md`
- Research design: `docs/03_methodology/01_research_design.md`
- Database layer: `betting_app/core/db.py`, SQLAlchemy models, Alembic revisions, and `docker/timescale/init.sql`
- Model evaluation: `betting_app/ml/pipelines/evaluation.py` and `betting_app/ml/backtesting/`
- EXP-039 retraining: `betting_app/ml/pipelines/exp039_weekly_retrain.py`

Trace every caller before modifying an exported service, model field, schema, feature definition, side convention, or timestamp contract.

## Future ideas catalog

`docs/future_ideas.md` is the single durable registry for proposals that are worth preserving but are not part of the current task.

- When the user asks to save, defer, catalog, or revisit an idea, add or update an entry there.
- Use stable `IDEA-NNN` identifiers and the catalog's status vocabulary.
- Record the problem, evidence, non-goals, prerequisites, affected contracts, implementation outline, acceptance criteria, and source links.
- An idea entry does not expand the current task, approve implementation, or change the frozen thesis scope or model.
- Update an existing entry rather than creating a competing note for the same proposal.
- Before implementation, confirm that the idea was explicitly promoted, then trace current callers and contracts again because catalog evidence may be stale.
- When work completes or is rejected, update the entry status and add the relevant commit, issue, or experiment reference.

## Safety rules

### Live database and secrets

- `.env` is currently tracked and contains a database URL and machine-specific paths. Treat it as sensitive. Never print its contents or credentials.
- Never use the configured database for tests, migration experiments, destructive scripts, or `init_db()`.
- Do not run Alembic against the configured/live database without explicit user instruction and a reviewed backup/rollback plan.
- Read-only inspection is acceptable only when the task requires it. Do not expose row payloads or secrets in reports.
- Use a temporary SQLite database for isolated unit tests and an ephemeral PostgreSQL/Timescale instance for migration and dialect verification.
- Local database dumps exist under `backups/`. Do not inspect, copy, commit, or include them in images unless explicitly required.
- Do not add datasets, database files, dumps, credentials, browser profiles, or generated experiment artifacts to Git.

### Network and automation

- Do not trigger real bookmaker or GOL.GG scraping unless the user explicitly asks for it. Scraping can cause external requests, bans, and browser processes.
- Do not start the scheduler for a test. Call the specific task or subprocess with a temporary database.
- The API currently has no authentication. Never expose it beyond loopback during development.
- Do not add another unauthenticated mutating or administrative endpoint.
- `betting_app/utils/browser_cleanup.py` can kill unrelated Chromium/Playwright processes when run directly on a host. Do not execute it outside an isolated container.

### Docker

- `docker-compose.yml` currently requires `gpus: all` for the scheduler and the Python requirements select CUDA PyTorch. This does not work on CPU-only or non-Nvidia hosts.
- Compose initializes Timescale with `docker/timescale/init.sql`; it does not run Alembic.
- `.dockerignore` does not currently exclude every sensitive/local artifact. Review the build context before building or publishing an image.

### Local-first deployment workflow

The always-on application host is reachable as `melzak@192.168.1.17` with the default SSH identity under `~/.ssh/`.

Verified server layout:

```text
/data/inzynierka/       operational data, backups, logs, and PostgreSQL storage
/data/inzynierka/app/   Git checkout and Docker Compose project
```

Never develop or make ad hoc source edits in the server checkout. Use this promotion sequence:

1. Make the change in the local checkout.
2. Verify the exact behavior locally, including targeted backend checks and browser interaction for UI changes.
3. Review the local diff, then commit and push through Git only after the local result is accepted.
4. Before deployment, inspect the server branch, commit, working tree, containers, and database health. Preserve unexpected server changes; never reset or overwrite them.
5. Update `/data/inzynierka/app` with a fast-forward Git pull.
6. Rebuild or restart only the affected Compose services.
7. Verify API health, frontend behavior, scheduler/container state, and relevant logs on the server.

Do not use `git reset --hard`, `git clean`, direct file copying, or direct remote edits as a deployment shortcut. Do not pull or restart the server merely because local files changed; local verification and an intentional Git promotion happen first.

### Branch workflow

`dev` is the integration branch for all development work. Create working branches
from `dev`, validate locally, then commit and push changes to `dev` or a branch
that will merge into `dev`. Do not push new development commits directly to
`main`.

Promote `dev` to `main` only as an explicit, reviewed release step after the
same local verification has passed. Keep `main` and `dev` intentionally
synchronized through that promotion; do not treat a successful push to one
branch as a push to the other.

## Known hazards as of 2026-09-02

Treat these as known defects, not intended behavior. If a change touches one, fix the source problem and add a regression check.

### Schema divergence

There are three incompatible schema definitions: SQLAlchemy models, Alembic, and `docker/timescale/init.sql`.

- Many `Mapped[float]` fields are incorrectly declared with `mapped_column(Integer)`, including odds, probabilities, ratings, rolling statistics, EV, tax, and confidence.
- `ModelEvSignal.tax_rate` has an incorrect model default of `12` rather than `0.12`.
- Several string defaults include embedded SQL quotes and create literal values such as `"'upcoming'"` under SQLite.
- Fresh `alembic upgrade head` currently fails in `6ff3a3de9d63_server_defaults.py` because it drops legacy tables absent from the initial revision.
- That migration also attempts to convert continuous `REAL` fields to `INTEGER`.
- The Timescale init schema has nullable `BIGINT` identifiers without identity/default generation for several tables.
- The configured live schema has historically been advanced through a mixture of init SQL, `create_all`, migrations, and manual fixes. Never infer live structure solely from `alembic_version`.

Desired direction: PostgreSQL/TimescaleDB as the authoritative operational schema, represented by one clean Alembic chain. Do not create a fourth schema path.

### SQLite compatibility

The README advertises SQLite, but important paths are not SQLite-safe:

- the compatibility wrapper returns no SQLite `lastrowid`;
- canonical matching uses PostgreSQL `GREATEST()`;
- several API queries use PostgreSQL casts, `EXTRACT`, arrays, or lateral joins;
- the documented dry-run scraper uses bookmaker `manual`, which the whitelist rejects.

For a focused fix, either make the touched path genuinely cross-dialect and test both databases, or explicitly standardize it on PostgreSQL. Do not claim SQLite support based only on `Base.metadata.create_all()`.

### Temporal leakage

Current historical evaluation defaults include stale predictions, select the latest prediction per match, and do not require the prediction to precede the selected odds. Live data has contained post-start predictions and missing `data_cutoff_at` values.

Every production or evaluation row must satisfy:

```text
feature/source time <= data_cutoff_at <= predicted_at <= quote_at < match_start_at
```

If no post-prediction quote is required by the experiment, document that exception and never call it executable/live betting performance. Missing timestamps make a row ineligible.

Do not use closing odds as a sports-model input. They are a diagnostic market benchmark only.

### Bankroll simulation

The current backtest and financial API settle each bet immediately in iteration order. This can use outcomes before their real settlement time and reuse capital committed to overlapping matches.

A valid ledger must:

1. place bets using information available at the placement timestamp;
2. reserve the stake;
3. keep overlapping bets open;
4. settle only after the corresponding match ends; and
5. size later bets from capital actually available at that time.

Do not present current ROI, drawdown, Kelly, or promotion results as financially executable until this is fixed.

### Ratings and calibration

- `src/ratings/glicko.py::GlickoRating.update_team` updates the second team against the already-mutated first team. Snapshot both pre-match states and update simultaneously.
- EXP-039 weekly retraining currently fits the calibrator on all walk-forward predictions and reports calibrated metrics on those same rows. Use a separate chronological calibration/evaluation period or nested walk-forward calibration.
- Any rating or feature fix that changes model inputs requires new artifacts and reevaluation; do not silently reuse old artifacts.

### Financial transactions

`betting_app/api/routers/bets.py` currently commits the bet before deducting the wallet and uses PostgreSQL `lastrowid`, which returns `0` rather than the inserted serial ID. Placement and settlement also lack concurrency guards.

Required invariant:

```text
bet row + wallet balance + wallet transaction commit atomically, or none commit
```

Use `INSERT ... RETURNING id`, row locks or conditional updates, non-negative balance constraints, and idempotent settlement.

### Scheduler

- Scraping and prediction cron expressions are not actually 15 minutes apart despite the comment.
- GOL.GG refresh, ratings rebuild, and feature rebuild are independent six-hour jobs even though they form an ordered dependency chain.
- `_DEFAULT_TASK_TIMEOUT` is declared but not enforced.
- Task failures frequently store an empty `automation_runs.error`; `automation_commands` may contain no diagnostics.
- The API scheduler trigger uses a separate in-process executor and can overlap the real scheduler.

Prefer explicit task dependencies and subprocess timeouts over independent interval jobs.

### Timezones and canonical matches

Unzoned Polish bookmaker labels must be interpreted in `Europe/Warsaw` and converted to UTC. Do not attach UTC directly to strings such as `14.06.2026 22:00`, `dziś 22:00`, or `jutro 18:00`.

Inject a clock into relative-date parsing. Do not hardcode the current year in tests. Preserve academy/main-squad distinctions and side alignment when changing canonical matching.

### Frontend

- `npm run build` passes, but `npm run lint` currently fails.
- `client/src/pages/MatchDetail.tsx` contains a conditional `useMemo` after an early return. Hooks must execute in the same order on every render.
- The frontend has no test script.

Do not treat a successful Vite build as a lint or runtime correctness check.

## Domain invariants

### Match sides

Storage uses both `team_a`/`team_b` and `a`/`b` in different boundaries. Normalize explicitly at the boundary. Never infer side from display order after canonical alignment.

For every probability pair:

```text
0 <= prob_a <= 1
0 <= prob_b <= 1
prob_a + prob_b ~= 1
```

For decimal odds used in analysis:

```text
odds_a > 1
odds_b > 1
```

### Rating updates

- Predict before applying the current game or match result.
- Update opponents from the same pre-match state.
- Apply time decay using the actual match date.
- Do not let iteration order, canonical side, or bookmaker side change a symmetric prediction.

### Model evaluation

Report at least:

- sample size and exact cohort dates;
- log loss and Brier score;
- AUC as secondary discrimination evidence;
- calibration diagnostics;
- no-vig market baseline on the same rows;
- temporal eligibility counts and exclusions;
- uncertainty using an appropriate temporal/block bootstrap.

Never call a point-estimate difference “significant” without naming the test, resampling unit, confidence interval, and preselected decision rule.

### Financial calculations

- Tax is a fraction such as `0.12`, never a percentage integer such as `12`.
- Validate tax to `[0,1)`, positive odds, positive stake, and bounded staking multipliers.
- Keep money in `Numeric`/`Decimal` at persistence boundaries.
- Settlement must be idempotent.

### Database changes

- Use timezone-aware timestamps for real event times; avoid new timestamps stored as arbitrary strings.
- Use `Float` for model measurements and `Numeric` for money.
- Give every addressable row a real primary key/default.
- Add foreign keys where the relationship is part of the audit trail.
- Index actual filter/order patterns, especially match start, model/version/prediction time, and canonical match IDs.
- Migration tests must begin from an empty PostgreSQL/Timescale database and reach head.

## Coding conventions

- Python target: 3.12.
- Backend: FastAPI and SQLAlchemy 2.x.
- Frontend: React 18, TypeScript, Vite.
- Prefer SQLAlchemy `text()` with named parameters over new positional-`?` compatibility SQL.
- Keep transactions in the service layer and make their boundaries explicit.
- Do not catch broad exceptions merely to return success or an empty result.
- Preserve raw external payloads for diagnostics, but never return secrets through API errors.
- Reuse existing normalization and side-alignment helpers; do not add parallel implementations.
- Keep frozen experiment/model versions immutable. New behavior gets a new version and metadata.
- Avoid new top-level scratch scripts named `test_*.py`; pytest collects them.
- Update existing documentation when behavior changes instead of creating a competing README.

## Verification commands

The system shell may not provide `python`; use the repository virtual environment explicitly.

### Backend

Default application tests:

```bash
.venv/bin/python -m pytest -q betting_app/tests
```

Run relevant root regression tests explicitly, for example:

```bash
.venv/bin/python -m pytest -q test_canonical_match_resolution.py test_lyon_academy_mapping.py
```

Known test limitations at the audit date:

- full root collection is blocked by `test_models.py` importing unavailable Torch;
- the Polish month/year test is date-dependent;
- `test_thesis_features.py` assumes a populated local database;
- most API tests use SQLite and cannot validate PostgreSQL migrations or concurrency.

Do not suppress these failures. Fix or isolate their real prerequisites when the task touches them.

Dependency consistency:

```bash
.venv/bin/python -m pip check
```

`pip install -e . --dry-run` currently fails because `pyproject.toml` lacks complete project metadata.

### Frontend

```bash
cd client
npm run build
npm run lint
```

Run both. Build success does not excuse lint failure. For UI behavior changes, launch the actual app and exercise the changed route in a browser.

### Docker

Syntax-only validation:

```bash
docker compose config --quiet
```

Do not treat this as proof that the scheduler can start; GPU/runtime and schema initialization remain separate concerns.

### Migrations

When working on schema code, verify against a disposable PostgreSQL/Timescale database. Never point migration commands at `.env` by accident. A valid schema change must prove:

```text
empty database -> alembic upgrade head -> application smoke path
```

SQLite-only migration success is insufficient.

## Verification by change type

| Change | Minimum proof |
|---|---|
| API/service bug | Reproduce, fix, exercise the endpoint/service, run targeted tests. |
| Schema/migration | Fresh ephemeral PostgreSQL upgrade to head plus affected API/script smoke path. |
| ML feature/rating | Chronological regression test, symmetry/leakage assertions, reevaluation under a new artifact version. |
| Backtest/financial | Event-time scenario with overlapping matches and deterministic bankroll assertions. |
| Scheduler | Assert actual next fire times and dependency order; exercise timeout/failure recording. |
| Scraper/parser | Parser fixture or dry-run with a temporary database; no live request unless explicitly requested. |
| React UI | `npm run build`, `npm run lint`, then browser interaction on the changed route. |
| Documentation only | Re-read rendered structure and verify every command/path against the repository. |

## Definition of done

Before reporting completion:

- all affected call sites and persisted contracts are updated;
- tests use temporary data and do not mutate the configured database;
- temporal and side-alignment invariants are explicit;
- PostgreSQL behavior is verified when SQL or schema changed;
- frontend build, lint, and browser behavior are checked when UI changed;
- frozen artifacts were not overwritten;
- generated datasets, dumps, secrets, and scratch files were not added;
- documentation states limitations honestly and does not present retrospective ROI as live performance.
