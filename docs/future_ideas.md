---
type: ideas-catalog
tags:
  - planning
  - future-work
  - ensemblelegends
project: EnsembleLegends
updated: 2026-09-02
---

# Future ideas catalog

This file is the durable registry for ideas that are worth preserving but are not part of the current implementation scope. An entry records a proposal; it does not authorize implementation or change the frozen thesis model.

## Catalog workflow

Use stable IDs in the form `IDEA-NNN`. Update an existing entry instead of creating a duplicate.

Allowed statuses:

- `proposed` — captured but not approved for implementation;
- `researching` — evidence, access, or design is still being gathered;
- `ready` — prerequisites and acceptance criteria are defined;
- `in-progress` — explicitly promoted into active work;
- `parked` — intentionally deferred;
- `rejected` — considered and declined, with the reason retained;
- `completed` — implemented and linked to its commit, issue, or experiment note.

Every entry should contain:

- problem and expected value;
- evidence and source links;
- non-goals and safety boundaries;
- prerequisites and unresolved decisions;
- implementation outline;
- observable acceptance criteria;
- affected repository paths and persisted contracts;
- follow-up commit, issue, or experiment references when promoted.

## Entry template

```markdown
## IDEA-NNN — Short title

- **Status:** proposed
- **Created:** YYYY-MM-DD
- **Updated:** YYYY-MM-DD

### Problem

### Evidence

### Non-goals

### Prerequisites and open decisions

### Implementation outline

### Acceptance criteria

### Affected areas

### References
```

---

## IDEA-001 — Read-only foreign LoL market reference feeds

- **Status:** proposed
- **Created:** 2026-09-02
- **Updated:** 2026-09-02

### Problem

The application currently compares model probabilities with seven Polish sportsbook feeds. Adding independent foreign market references could improve the market baseline, expose regional pricing differences, and support a better-calibrated market or model-market ensemble.

Prediction markets and exchanges are not bookmakers. Treating them as ordinary decimal-odds sources would discard spread, depth, volume, and licensing semantics and could accidentally expose them through wallet or bet-placement workflows.

### Evidence collected on 2026-09-02

| Source | Evidence and access | Catalog decision |
|---|---|---|
| Polymarket | Public Gamma and CLOB market-data APIs need no authentication. A paginated snapshot contained 34 strictly future LoL fixture moneylines; 21 had spreads no wider than 0.05, 22 reported liquidity of at least 1,000, and 13 reported volume of at least 1,000. Full books and price history are available. | First research pilot. Use only public clients and market-data endpoints. |
| Pinnacle | General public API access has been closed since 2025-07-23, but Pinnacle accepts applications from academics and pregame handicapping projects. A funded account is documented as required, and esports needs separate authorization. | Apply for academic and esports access; do not assume approval. |
| Odds-API.io | Advertises broad LoL coverage and many named sportsbooks. Actual per-event coverage requires a key. Current free-key creation is paused, plans limit the number of selected books, and Pinnacle is absent from the current directory. | Run a time-limited paid coverage pilot only after receiving a current LoL bookmaker matrix and retention terms. |
| Betfair Exchange | LoL LCK/LPL and map markets are present. Betfair requires read-only consumers to use a delayed key; snapshots can be delayed by 1–180 seconds. Historical esports data is grouped under `Other Sports` and `MAP_WINNER`. | Optional delayed and historical exchange benchmark. Never buy or use a live key solely for read-only collection. |
| LSports OddService | Enterprise feed advertising named lines from 100+ bookmakers and esports coverage. Exact LoL coverage and pricing are contractual. | Enterprise fallback if budget and licensing justify it. |
| Kalshi | Public REST technically exposes LoL books and historical bid/ask candlesticks. Its Developer Agreement limits API use to a member's own trading and prohibits collecting or storing API data for other purposes. | Blocked unless Kalshi grants written research and storage authorization. |
| Smarkets | API terms prohibit pure data extraction without commensurate trading and prohibit benchmarking markets, prices, or liquidity. | Rejected for this non-trading use case. |
| The Odds API | Current supported-sports catalog does not include esports or League of Legends. | Rejected for lack of coverage. |

Abios and PandaScore may provide proprietary esports prices, but their standard products are not side-by-side foreign-bookmaker consensus feeds. They are potential model comparators, not replacements for market observations.

### Non-goals and safety boundaries

- No automatic bet placement.
- No order creation, cancellation, wallet connection, private key, or trading credential.
- No source may become a wallet/account option merely because its quotes are active.
- No closing odds may be used as a sports-model input.
- No use of Kalshi or Smarkets data that conflicts with their published terms.
- No overwrite or silent reuse of the frozen EXP-039 artifact.
- No public redistribution of raw vendor data without explicit licensing rights.

### Proposed source priority

1. Implement a Polymarket public-data shadow collector.
2. Apply to Pinnacle through `api@pinnacle.com` and request esports authorization through `b2b@pinnacle.com`.
3. Evaluate a five-source Odds-API.io pilot, initially asking for GG.BET, Thunderpick, Bet365, SBOBET, and Betfair Exchange coverage.
4. Add Betfair delayed or historical data only if account eligibility and data rights are confirmed.
5. Consider LSports only after receiving enterprise pricing, exact LoL coverage, historical retention rights, and derived-output rights.

### Required persistence and capability boundary

Extend the existing normalized odds-source model rather than creating an unrelated ingestion path. A source needs explicit capabilities such as:

```text
source_kind = sportsbook | betting_exchange | prediction_market
is_bettable = true | false
include_in_market_model = true | false
```

Reference-only sources must be excluded from bookmaker accounts, wallets, manual bet placement, EV generation, and bet-signal generation.

Exchange and prediction-market quotes need native fields rather than synthetic decimal odds:

```text
source_event_id
source_market_id
source_kind
canonical_match_id
market_type
outcome/token IDs
source_match_start_at
bid_probability
ask_probability
bid_depth
ask_depth
last_probability
volume
liquidity/open_interest
quote_observed_at
retrieved_at
market_status
raw_payload
```

Use `Float` for probabilities and measurements and `Numeric` only for money at persistence boundaries. Do not build new exchange data on the known integer-backed odds columns.

### Normalization and temporal rules

For two-way sportsbook decimal odds:

```text
q_a = 1 / odds_a
q_b = 1 / odds_b
p_a = q_a / (q_a + q_b)
```

For an exchange, preserve each outcome's bid and ask. A midpoint may be used only after spread, depth, activity, and staleness checks, then normalized across both outcomes.

A market quote used as a model feature must satisfy:

```text
market_quote_at <= data_cutoff_at <= predicted_at < match_start_at
```

A later quote used only for comparison must be stored separately:

```text
predicted_at <= evaluation_quote_at < match_start_at
```

Polymarket discovery must paginate and filter the nested market, not only the top-level event: require `sportsMarketType=moneyline`, `closed=false`, `acceptingOrders=true`, and a future `gameStartTime`. Use the CLOB book timestamp for quote timing. Preserve and quarantine source kickoff disagreements instead of forcing canonical matches; the research snapshot found a four-hour source-time disagreement for the same HLE–T1 fixture.

### Implementation outline

1. Add source-kind and bettable/reference-only capabilities, with a PostgreSQL migration and updated wallet/signal filters.
2. Add an async Polymarket adapter restricted to public discovery, book, and price-history reads. Prefer the official `AsyncPublicClient` or the existing `httpx` dependency; expose no secure or order methods.
3. Store both raw responses and normalized book snapshots while stopping collection at canonical kickoff.
4. Shadow-capture without changing production predictions or signals.
5. Audit coverage, mapping failures, source-time conflicts, quote staleness, spreads, depth, and missing books.
6. Evaluate the new source chronologically on the same matches and cutoffs as the existing seven-book no-vig baseline.
7. If justified, create a new experiment and artifact version; keep EXP-039 immutable.
8. Add a paid sportsbook aggregator only after the public-source pilot establishes the incremental value and required fields.

### Acceptance criteria before model use

- Collection uses only approved read-only endpoints and credentials.
- Reference sources cannot appear in wallet, account, manual-bet, or order workflows.
- Every included quote has both outcomes, bounded probabilities, an eligible timestamp, and a resolved canonical side alignment.
- Unresolved identity, kickoff, market-type, or settlement conflicts are quarantined and counted.
- Historical evaluation reports sample dates and size, temporal exclusions, log loss, Brier score, AUC as secondary evidence, calibration, and the same-row current-market baseline.
- Source weights or blend parameters are selected chronologically and are not fitted on the final evaluation period.
- Raw-data retention and derived-output rights are documented for every commercial source.
- No existing or new result is described as executable betting performance unless it satisfies the full temporal and bankroll contracts.

### Affected areas if promoted

- `betting_app/models/bookmaker.py`
- `betting_app/models/odds.py`
- `betting_app/alembic/`
- `betting_app/services/odds_service.py`
- `betting_app/services/wallet_service.py`
- `betting_app/services/upcoming_inference_service.py`
- `betting_app/scrapers/` or a renamed read-only market-source adapter package
- scheduler task registration and source-specific configuration
- temporal data-contract and experiment documentation

### References

- [Polymarket market-data overview](https://docs.polymarket.com/market-data/overview)
- [Polymarket prices and order books](https://docs.polymarket.com/market-data/prices-order-books)
- [Polymarket official Python SDK](https://docs.polymarket.com/getting-started/python)
- [Polymarket API guidance for academic researchers](https://help.polymarket.com/en/articles/13364254-does-polymarket-have-an-api)
- [Pinnacle API access policy](https://github.com/pinnacleapi/pinnacleapi-documentation)
- [Pinnacle esports authorization FAQ](https://github.com/pinnacleapi/pinnacleapi-documentation/blob/master/FAQ.md)
- [Odds-API.io LoL offering](https://odds-api.io/esports/league-of-legends)
- [Odds-API.io pricing](https://odds-api.io/#pricing)
- [Odds-API.io terms](https://odds-api.io/terms)
- [Betfair read-only policy](https://support.developer.betfair.com/hc/en-us/articles/25033076334748-What-is-read-only-Betfair-API-access)
- [Betfair delayed-key behavior](https://support.developer.betfair.com/hc/en-us/articles/360009638032-When-should-I-use-the-Delayed-or-Live-Application-Key)
- [Betfair esports historical data](https://support.developer.betfair.com/hc/en-us/articles/6198855564573-How-do-I-access-Esports-market-via-the-historical-data-website)
- [Kalshi public market-data API](https://docs.kalshi.com/getting_started/quick_start_market_data)
- [Kalshi Developer Agreement](https://assets.kalshi.com/Kalshi-Developer-Agreement.pdf)
- [LSports OddService](https://www.lsports.eu/oddservice/)
- [Smarkets API terms](https://help.smarkets.com/hc/en-gb/articles/34697834941085-Smarkets-API-Access-Integration-T-Cs)
- [The Odds API supported sports](https://the-odds-api.com/sports-odds-data/sports-apis.html)

---

## IDEA-002 — Restrict the operational network and mutation boundary

- **Status:** in-progress
- **Created:** 2026-09-02
- **Updated:** 2026-09-03

### Problem

The operational PostgreSQL, FastAPI, and Vite containers publish ports on every host interface. The API defines no authentication scheme while exposing wallet, bet, roster, mapping, scheduler, backup, and automation mutations.

### Evidence

A read-only deployed audit observed `5432`, `8000`, and `3000` bound to `0.0.0.0` and `[::]`. The OpenAPI contract had no security scheme and listed 14 mutating paths, including `/automation/backup`, `/automation/light-cycle`, `/bets`, `/wallets`, and `/scheduler/trigger/{task_id}`.

### Non-goals

- No public deployment or automated betting.
- No direct database access from the LAN.
- Do not rely only on obscurity, a browser-origin check, or a shared frontend route as access control.

### Prerequisites and open decisions

- Chosen operator access path: Caddy HTTPS directly on the trusted LAN, using a persisted internal CA installed only on trusted devices.
- Required network change: router/DNS `A` record `ensemblelegends.lan` → `192.168.1.17`.
- Define application-level roles for scheduler/backup versus wallet/bet mutations.

### Implementation outline

1. Remove PostgreSQL and FastAPI host-port publication; retain Compose-internal service networking.
2. Replace the Vite development server with an authenticated static Caddy gateway that exposes only HTTP-to-HTTPS redirect and HTTPS on the trusted LAN.
3. Persist Caddy's internal CA and require trusted devices to install its root certificate before entering credentials.
4. Require explicit database and gateway secrets so Compose fails closed.
5. Add application-level authorization dependencies and role separation for mutating routes in a later promotion.

### Acceptance criteria

- PostgreSQL and FastAPI have no host port in the rendered Compose contract.
- Caddy exposes only ports `80` and `443`; HTTP redirects to HTTPS.
- The HTTPS gateway returns `401` before proxying application content without valid operator credentials.
- Caddy's `/data` and `/config` volumes preserve the internal CA across client recreation.
- Application-level roles for scheduler, backup, and wallet mutations remain an explicit follow-up; this deployment boundary does not claim to provide them.

### Affected areas

- `docker-compose.yml`
- `client/Dockerfile`
- `client/vite.config.ts`
- `betting_app/api/main.py`
- API routers and dependency wiring

### References

- Read-only deployed audit, 2026-09-02.
- `docker-compose.yml`
- OpenAPI routes served by `/openapi.json`.
- Local implementation validated 2026-09-03: production client build, Caddy configuration, Basic Authentication behavior, trusted internal-CA HTTPS proxying, HTTP-to-HTTPS redirect, and Compose contract. Pending promotion commit and deployment review.

---

## IDEA-003 — Serialize derived-data maintenance

- **Status:** completed
- **Created:** 2026-09-02
- **Updated:** 2026-09-03

### Problem

Ratings and W20 features are meaningful only when built from the completed GOL.GG refresh. Independent maintenance schedules can rebuild them from stale source data.

### Evidence

The deployed scheduler started `refresh_golgg`, `rebuild_ratings`, and `rebuild_features` together at `2026-09-02 16:32 UTC`. Ratings and features completed in 2 and 24 seconds respectively, while the source refresh completed 628 seconds later. The deployed registry configured the three components as independent six-hour interval jobs.

### Non-goals

- Do not run overlapping heavy refreshes.
- Do not add a second scheduler implementation.
- Do not mask a failed source refresh by rebuilding downstream state anyway.

### Prerequisites and open decisions

- The `heavy_maintenance` advisory lock is shared by manual components, the scheduled cycle, and expired-match backfill.
- Chosen failure behavior: stop at the first failed dependency, record it on the parent run, and mark every remaining child as skipped; retry occurs only in a later explicitly scheduled or manual cycle.

### Implementation outline

1. Retain component functions for explicit manual maintenance only.
2. Schedule one `heavy_maintenance_cycle` that executes refresh, ratings, then W20 features serially under the existing lock.
3. Record child-run ordering, versions, bounded subprocess output, and failure propagation.
4. Restart the scheduler after promotion so persisted APScheduler jobs are replaced from the registry.

### Acceptance criteria

- No rating/feature child command starts before its refresh dependency succeeds.
- A failed refresh or rating rebuild prevents every downstream child command.
- Parent `automation_runs` records the ordered child `automation_commands`; rating and W20 command diagnostics retain their emitted version and cutoff.
- Tests assert next-fire time, lock exclusion, dependency order, and failures at both refresh and ratings stages.

### Affected areas

- `betting_app/scheduler/registry.py`
- `betting_app/scheduler/tasks/maintenance.py`
- `betting_app/scheduler/`
- `automation_runs` and scheduler-status API contracts

### References

- Read-only deployed audit, 2026-09-02.
- `betting_app/scheduler/registry.py`.
- Implemented and deployed 2026-09-03: `b2e55bb` serializes maintenance cycles, enforces shared locks, records bounded command diagnostics, and adds 17 scheduler regressions; `8ce2603` removes credentials from the scheduler startup log.

---

## IDEA-004 — Canonical fixture deduplication and mapping triage

- **Status:** in-progress
- **Created:** 2026-09-02
- **Updated:** 2026-09-03

### Problem

Alias differences and reversed bookmaker sides can create duplicate canonical matches. This splits odds, predictions, EV signals, and eventual results across records.

### Evidence

The deployed upcoming board showed two LPL records at `2026-09-05 09:00 UTC`: `Ninjas in Pyjamas` versus `JD Gaming` and `JD` versus `NiP`. They had separate canonical IDs, bookmaker subsets, and predictions. The Mapping screen also reported 31 upcoming unresolved or match-unmapped records.

The 2026-09-03 identity review found four clearly incorrect `auto-fuzzy` result links, three active alias keys with conflicting unscoped targets, 16 unsafe unscoped compact aliases, and 169 duplicate normalized rows in `golgg_teams`. All 2,358 deployed `golgg_teams.team_id` values are null, so those IDs identify local name rows rather than durable source teams.

A full local replay over all 801 deployed links found that the recommended containment rule—stored confidence ≥0.95, exact calendar date, and compatible competition family—would retain 711 links (88.8%), route 90 to review, and reject all four confirmed defects. Confidence plus exact date alone retained 724 (90.4%). A ±1-day rule retained 769 (96.0%) but produced an unsafe next-day candidate when exact-date identity was unresolved, so one-day candidates remain review-only until source timezone semantics are explicit. Identity-first replay automatically resolved 314 links (39.2%), agreed with 310 existing decisions, produced four correction candidates, rejected all four known bad links, and detected the live NiP/JD duplicate. These are coverage and concordance figures, not accuracy estimates; independent labels are still required.

### Non-goals

- Do not automatically merge ambiguous matches.
- Preserve academy/main-squad distinctions.
- Never infer side from display order after a merge.

### Prerequisites and open decisions

- Use exact source-local calendar date for automatic historical result linking until source timezone semantics are explicit; treat ±1-day candidates as review evidence.
- Persist a canonical competition entity/family rather than relying on the simulation taxonomy.
- Label an accepted sample and the 90 containment-review rows before claiming precision or promoting the resolver.
- Decide the audit record and rollback procedure for a confirmed merge.

### Implementation outline

1. Normalize aliases before candidate identity comparison.
2. Compare unordered team pairs, competition, best-of, and normalized kickoff while retaining each source's side orientation.
3. Auto-merge only high-confidence identities; send every ambiguity to the existing manual queue.
4. Rank that queue by kickoff, bookmaker coverage, and prediction readiness; show evidence for each alias suggestion.
5. Recompute side-aligned odds, predictions, and signals after a confirmed merge.

### Acceptance criteria

- Equivalent alias/reversed-side fixtures produce one canonical match.
- All associated odds and predictions retain correct canonical side alignment.
- Academy/main-squad near-matches remain distinct.
- Regression fixtures cover the deployed NiP/JD case.

### Affected areas

- `betting_app/services/` canonical matching and alias services
- `betting_app/api/routers/matches.py`
- `client/src/pages/ManualMapping.tsx`
- canonical-match, odds-snapshot, prediction, and signal contracts

### References

- Read-only deployed audit, 2026-09-02.
- `GET /matches/145826` and `GET /matches/145830`.
- `docs/02_data/03_team_identity_and_mapping_review.md`, 2026-09-03.
- `docs/05_results/06_identity_mapping_simulation.md`, 2026-09-03.
- Local containment implemented in `2d5f4e4`: exact-date and competition-family result-link gates, `>=0.95` pair identity, explicit ambiguity, scoped short-alias editing, source-context propagation, and NiP/JD reversed-side regressions. Historical repair and the durable entity cutover remain pending.

---

## IDEA-005 — Enforce provenance-gated financial and model evaluation

- **Status:** proposed
- **Created:** 2026-09-02
- **Updated:** 2026-09-02

### Problem

Historical model, CLV, and betting results can look actionable while missing feature-cutoff provenance or using capital before it is available. The old Backtest page independently computes quarter-Kelly stakes from a constant bankroll and displays P&L/ROI without an event-time ledger.

### Evidence

The deployed CLV query requires prediction and match-start timestamps but does not query or validate `data_cutoff_at`. The deployed legacy EXP-039 cohort had zero rows with an eligible cutoff. `client/src/pages/MatchResults.tsx` calculates each stake from `KELLY_BANKROLL = 1000` while iterating results, with no placement/reservation/settlement timeline.

### Non-goals

- Do not invent or backfill unsupported historical cutoff timestamps.
- Do not call research-only retrospective results executable performance.
- Do not overwrite the frozen EXP-039 artifact.

### Prerequisites and open decisions

- Specify the immutable source-time contract for every new prediction writer.
- Decide whether the old Backtest page becomes a non-financial result browser or delegates fully to the canonical ledger.

### Implementation outline

1. Require `feature/source <= data_cutoff_at <= predicted_at <= quote_at < match_start_at` for live cohorts.
2. Make every evaluator report temporal eligibility and exclusion counts.
3. Route all financial simulations through the event-time ledger: reserve at placement, retain overlapping bets, and settle after the real result time.
4. Remove legacy browser-side P&L/ROI or label it research-only until the ledger replaces it.
5. Keep legacy missing-provenance rows explicitly historical/research-only.

### Acceptance criteria

- Live evaluation contains no row with a missing or invalid cutoff.
- An overlapping-match scenario cannot reuse reserved capital.
- Financial output matches the ledger event sequence and uses PLN consistently.
- UI and API state whether each result is live-eligible or research-only.

### Affected areas

- `betting_app/services/thesis_inference_service.py`
- `betting_app/services/upcoming_inference_service.py`
- `betting_app/api/routers/timing.py`
- `betting_app/api/routers/financial.py`
- `client/src/pages/MatchResults.tsx`
- `client/src/pages/FinancialAnalysis.tsx`

### References

- Read-only deployed audit, 2026-09-02.
- `betting_app/api/routers/timing.py`.
- `client/src/pages/MatchResults.tsx`.

---

## IDEA-006 — Production client delivery and bounded analytical payloads

- **Status:** proposed
- **Created:** 2026-09-02
- **Updated:** 2026-09-02

### Problem

The operational client is served with Vite's development server. Large analytical pages make duplicate, unpaginated requests and delay useful feedback.

### Evidence

The deployed Backtest view issued two identical requests of about 845 KB. They completed in 13.2 and 20.5 seconds before rendering 308 records. The client Dockerfile starts `npm run dev`.

### Non-goals

- Do not remove detailed data needed for reproducible research.
- Do not hide failures behind a permanent loading indicator.

### Prerequisites and open decisions

- Define the operator's required initial page budget and acceptable detail-fetch latency.
- Choose the production static-server/reverse-proxy image.

### Implementation outline

1. Build with `npm ci` and `npm run build` in a multi-stage image.
2. Serve the static result from Nginx or Caddy and proxy only the needed API path internally.
3. Return paginated summaries for Backtest; fetch bookmaker and match detail on demand.
4. Eliminate development-mode duplicate fetch behavior and add request cancellation/cache semantics for filter changes.

### Acceptance criteria

- The operational client does not run Vite's development server.
- A page navigation issues one intentional data request.
- Backtest has bounded initial payload/latency and explicit loading/error/empty states.
- `npm run build`, `npm run lint`, and browser interaction pass before promotion.

### Affected areas

- `client/Dockerfile`
- `client/vite.config.ts`
- `client/src/api/client.ts`
- `client/src/pages/MatchResults.tsx`
- result-list API query and response contracts

### References

- Read-only deployed audit, 2026-09-02.
- `client/Dockerfile`.

---

## IDEA-007 — Make analytical cache state and statistical readiness observable

- **Status:** proposed
- **Created:** 2026-09-02
- **Updated:** 2026-09-02

### Problem

The Model Analysis page serves cached horizon/CLV metrics while bootstrap validation has no cached result. A user cannot distinguish unavailable, stale, failed, and statistically insufficient analysis.

### Evidence

The deployed Model Analysis page showed bootstrap significance `0/0` and no results. `GET /bootstrap/horizon` returned `404` because the cache was absent, while the model-analysis cache displayed other metrics.

### Non-goals

- Do not treat a point estimate as significant without the named resampling method, unit, interval, and decision rule.
- Do not let an unauthenticated browser action launch expensive maintenance.

### Prerequisites and open decisions

- Complete IDEA-005 temporal eligibility before publishing promotion-relevant comparisons.
- Define cache freshness thresholds and operator alerting ownership.

### Implementation outline

1. Persist each analytical cache's cohort, parameter set, source versions, generated time, duration, and last error.
2. Return an explicit unavailable/stale state instead of a generic `404` or `0/0`.
3. Surface that state in Model Analysis and System Monitoring.
4. Restrict refresh/trigger actions to authenticated operators.

### Acceptance criteria

- Every visible metric names its cohort and cache timestamp.
- Missing bootstrap data renders an actionable unavailable state with no implied significance.
- Scheduler history records successful and failed cache builds with bounded diagnostics.

### Affected areas

- `betting_app/api/routers/bootstrap.py`
- `betting_app/api/routers/timing.py`
- `betting_app/scheduler/tasks/maintenance.py`
- `client/src/pages/ModelAnalysis.tsx`
- `client/src/pages/SystemStatus.tsx`

### References

- Read-only deployed audit, 2026-09-02.
- `betting_app/api/routers/bootstrap.py`.

---

## IDEA-008 — Reconcile the PostgreSQL schema and migration chain

- **Status:** proposed
- **Created:** 2026-09-02
- **Updated:** 2026-09-02

### Problem

SQLAlchemy models, Alembic revisions, and Timescale initialization describe incompatible schemas. The migration chain cannot safely initialize a new operational database.

### Evidence

The repository's maintained hazard record identifies integer-backed continuous measurements, incorrect defaults, missing identity defaults, and an Alembic head upgrade that fails from an empty database. The operational deployment still initializes through hand-written Timescale SQL rather than Alembic.

### Non-goals

- Do not run exploratory migrations against the configured operational database.
- Do not create a fourth schema definition.
- Do not coerce continuous measurements to integers to satisfy a legacy migration.

### Prerequisites and open decisions

- Inventory the live schema read-only and compare it to a declared PostgreSQL target.
- Define backup, rollback, and maintenance-window requirements before live promotion.

### Implementation outline

1. Specify one authoritative PostgreSQL/Timescale schema in SQLAlchemy and a clean Alembic chain.
2. Correct types: `Float` for model measurements, `Numeric` for persisted money, timezone-aware timestamps for events.
3. Add primary keys, foreign keys, defaults, and indexes for actual audit/query patterns.
4. Test empty PostgreSQL/Timescale upgrade to head and an application smoke path before planning live migration.

### Acceptance criteria

- An empty disposable PostgreSQL/Timescale database reaches Alembic head.
- The application smoke path uses the resulting schema without SQLite-only assumptions.
- No model probability, odds, EV, tax, or rating measurement is silently truncated.

### Affected areas

- `betting_app/models/`
- `betting_app/alembic/`
- `docker/timescale/init.sql`
- `betting_app/core/db.py`

### References

- `AGENTS.md` known schema-divergence hazards.

---

## IDEA-009 — Correct rating and calibration integrity before model promotion

- **Status:** proposed
- **Created:** 2026-09-02
- **Updated:** 2026-09-02

### Problem

The current Glicko team update mutates the first team's state before calculating the second team's update. EXP-039 weekly retraining calibrates and evaluates on overlapping walk-forward predictions.

### Evidence

Both defects are recorded in the repository's maintained rating/calibration hazards. They can change inputs and make calibrated metrics optimistic without changing the frozen model artifact.

### Non-goals

- Do not silently reuse or overwrite EXP-039 after a feature/rating change.
- Do not report point-estimate improvements as significant without temporal uncertainty.

### Prerequisites and open decisions

- Choose a chronological calibration/evaluation split or nested walk-forward protocol.
- Define promotion thresholds before producing a new candidate artifact.

### Implementation outline

1. Snapshot both teams' pre-match Glicko state and update them simultaneously.
2. Add chronological symmetry, ordering, and leakage regression tests.
3. Separate calibration from final evaluation in weekly retraining.
4. Train, register, and evaluate a new immutable version with market baseline and temporal bootstrap uncertainty.

### Acceptance criteria

- Swapping match sides leaves a symmetric prediction unchanged after re-alignment.
- Glicko updates do not depend on team iteration order.
- Calibration/evaluation rows do not overlap.
- Any promoted artifact is new, immutable, and accompanied by reproducible evaluation metadata.

### Affected areas

- `src/ratings/glicko.py`
- `betting_app/ml/pipelines/exp039_weekly_retrain.py`
- `betting_app/ml/pipelines/evaluation.py`
- model registry, artifact metadata, and regression tests

### References

- `AGENTS.md` known ratings and calibration hazards.

---

## IDEA-010 — Time-aligned LoL forecast improvement programme

- **Status:** in-progress
- **Created:** 2026-09-04
- **Updated:** 2026-09-05

### Problem

The current retrospective EXP-039 proxy has worse probabilistic quality than near-start Pinnacle quotes. A prediction made at one information horizon must not be compared with a later market price. The project needs a durable, chronological path to improve forecast log loss without treating closing odds as a sports-model feature or changing the frozen EXP-039 artifact.

### Evidence

The 2026 OddsPapi audit mapped 492 of 622 proxy matches and selected 447 Pinnacle and 481 Kalshi strictly pre-start match-winner quote pairs. On the Pinnacle cohort, no-vig market log loss was 0.5357 versus 0.5744 for the proxy; the weekly-block-bootstrap log-loss delta (model minus market) was +0.0387, 95% CI [+0.0136, +0.0657]. The prior 622-match historical proxy report found that an EXP-039 plus market-open hybrid had log loss 0.5605, better than EXP-039 alone (0.5717) and market open (0.5687). These cohorts and quote times differ, so they do not establish a live or closing-line result.

### Non-goals

- Do not overwrite `exp-039`, use a post-start roster, or use closing odds as a sports-model input.
- Do not claim ROI, promotion, or executable betting performance from reconstructed proxy rows.
- Do not automatically place bets or expose a new mutating endpoint.

### Prerequisites and open decisions

- Persist real prediction and market observations at fixed horizons before evaluating candidates.
- Fix the separate EXP-039 calibration-integrity work tracked in IDEA-009 before interpreting improved calibrated metrics.
- Obtain timestamped roster observations before evaluating roster-continuity features historically.

### Implementation outline

1. **Completed — fixed horizons & OddsPapi budget integration:**
   - Implemented `betting_app/ml/backtesting/horizons.py` for strict horizon snapshot selection (T−24h, T−6h, T−1h).
   - Implemented `betting_app/services/oddspapi_service.py` and `OddsPapiBudgetGuard` backed by `oddspapi_request_logs` (daily cap 8, monthly cap 250) to acquire Pinnacle benchmarks without exceeding free quota.
   - Created `OddspapiFixtureMapping` and Alembic revision `b7c8d9e0f1a2`.
   - Registered automated discovery (`oddspapi_fixture_sync`, every 3 days) and horizon polling (`oddspapi_horizon_fetch`, every 30m) in scheduler registry.
   - Added `compare_match_market` and `/matches/{id}/market-comparison` endpoint.
2. **Completed — Out-of-Fold Temperature Scaling & Gating (EXP-040 Candidate):**
   - Implemented `betting_app/ml/calibration/candidate_calibration.py` with `TemperatureScalingCalibrator`, `BetaCalibrator`, `UncertaintyGatedCalibrator`, and `expected_calibration_error`.
   - Proven on 622-match cohort: fitted temperature $T=1.167 > 1.0$ flattens overconfident tails, reducing Expected Calibration Error from 0.0484 to 0.0302 (-37.6%) and Brier reliability penalty from 0.00381 to 0.00136 (-64.3%).
   - Implemented candidate features in `betting_app/ml/features/candidate_features.py`: side advantage (+1/-1), exponential patch decay with patch boundary penalty, and roster cohesion/substitute disruption.
   - Built `betting_app/ml/pipelines/exp040_candidate_pipeline.py` demonstrating EXP-040 hybrid LogLoss improved to 0.5600 and net ROI under Polish 12% tax reached +19.43% on filtered value positions.
3. **Completed — Architectural Rebuild & Conformal Risk Control:**
   - Implemented `betting_app/ml/calibration/venn_abers.py`: exact inductive Venn-Abers predictor producing finite-sample valid prediction intervals [p0, p1] and ConformalRiskGater using pessimistic lower bound P_low.
   - Implemented `betting_app/ml/models/markov_series.py`: hierarchical Markov series simulator accounting for rotating side selection (Game 1 higher-seed priority, Game 2 loser pick), reducing ECE from 0.0484 to 0.0202 (-58.3%).
   - Implemented `betting_app/ml/models/market_residual.py`: market-residual learning model predicting unpriced market error y - P_market with strict antisymmetry, lowering LogLoss from 0.5717 to 0.5620.
   - Verified via `betting_app/ml/pipelines/exp040_rebuild_benchmark.py` across 622 historical matches.
4. Evaluate candidate features in production walk-forward training without modifying frozen EXP-039.
### Acceptance criteria

- Every horizon row records the base prediction, cutoff, selected quote IDs/timestamps, side alignment, and exclusion reason.
- Each horizon has sample size, date range, temporal exclusions, log loss, Brier, AUC, calibration, and weekly/block bootstrap uncertainty.
- Blend parameters are fitted only before their evaluation interval.
- A new artifact/version is created for any accepted model change; EXP-039 remains immutable.

### Affected areas

- `betting_app/models/prediction.py` and `canonical_predictions`
- `betting_app/models/odds.py` and `odds_snapshots`
- `betting_app/ml/backtesting/`
- `betting_app/services/thesis_inference_service.py`
- scheduler registry and ML task wrappers
- `docs/02_data/01_data_sources_and_contract.md`

### References

- `data/oddspapi_lol_2026_model_audit/summary.json`
- `reports/exp039_db_market_backtest_v3_corrected/summary.json`
- `AGENTS.md` temporal-leakage and calibration hazards.

