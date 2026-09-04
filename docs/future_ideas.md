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

## IDEA-011 — Calibrated player-contribution rating updates

- **Status:** in-progress
- **Created:** 2026-09-04
- **Updated:** 2026-09-04

### Problem

Team-outcome rating updates give every player on the winning side the same directional credit and every player on the losing side the same debit. Test whether role-normalized post-game contribution estimates can distribute bounded extra player-rating credit more faithfully while preserving an auditable team-outcome signal.

### Evidence

- EXP-043 already tested a local PandaSkill-like branch: role-specific post-game performance models produced a role-normalized PScore, ranked the ten players in a map, and updated OpenSkill as a free-for-all.
- On its 2024+ map test, calibrated PandaSkill-like ratings had LogLoss `0.6171`, close to player Glicko `0.6163` and better than player Elo `0.6226`. Raw FFA OpenSkill probabilities were severely uncalibrated (`2.2550` LogLoss).
- On 2026-09-04, a bounded zero-sum contribution prototype was benchmarked on `20,200` post-2024 maps against standard Glicko-2. The candidate degraded LogLoss (`0.615081` -> `0.615761`, delta `+0.000680`, t-stat `16.812`, with larger delta scale worsening to `0.617194`). ROC AUC dropped (`0.7186` -> `0.7179`), and ECE worsened (`0.0238` -> `0.0247`).
- Cause: In League of Legends, high individual boxscore stats (KDA, gold share, DPM) in winning games often correlate with resource funnelling or stomps rather than sustainable independent player skill; rewarding them directly distorts rating equilibrium compared to pure team victory outcomes.

### Decision & Next steps

- Do NOT replace the pure team-outcome Glicko-2 update with direct boxscore contribution adjustments.
- Keep standard Glicko-2 as the authoritative rating engine.
- If player contribution is revisited, test it exclusively as a downstream feature in meta-models or draft profiles (IDEA-010), not as an in-place modification of rating likelihood updates.

### Non-goals

- Do not feed post-game player performance into the prediction for that same game.
- Do not overwrite EXP-039 or any existing rating snapshot.
- Do not award unrestricted points to high-stat players; player statistics are role-, champion-, game-length-, and team-context-dependent.
- Do not replace team ratings with a player contribution score before a new artifact passes chronological evaluation.

### Affected areas

- `src/ratings/`
- `betting_app/scripts/` rating rebuild and backtest runners
- `scripts/benchmark_player_contribution_rating.py`

### References

- `docs/04_experiments/EXP-043_pandaskill_like_backtest.md`
- `scripts/benchmark_player_contribution_rating.py`
