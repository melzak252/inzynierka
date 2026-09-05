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

## IDEA-015 — Adaptive horizon market blending (alpha(t) calibration)

- **Status:** in-progress
- **Created:** 2026-09-04
- **Updated:** 2026-09-04

### Problem

The current hybrid model applies a fixed model weight (e.g. $\alpha = 0.50$ or $\alpha = 0.35$) regardless of market timing. Early opening odds (>24h before match) are soft and set with wide spreads and lower liquidity, offering substantial model edge. Closing odds (<2h before match) incorporate sharp crowd information, lineup announcements, and heavy volume, making the pure market much harder to beat.

### Evidence

- Evaluated on $N = 4,528$ matches from the 2024–2026 test cohort using pre-match metamodel forecasts and opening vs closing market odds:
  - **Opening lines (>24h):** Higher model weight ($\alpha = 0.55$) achieves superior LogLoss (`0.605859` vs `0.610785` for static 0.50, and `0.7113` for pure market), ROC AUC (`0.7255` vs `0.7140`), and ECE (`0.0227`). It generates $1,941.82$ units of profit at $+5\%$ min EV with $+7.69\%$ average CLV.
  - **Closing lines (<2h):** The market becomes significantly sharper. However, over-shrinking $\alpha$ to $0.25$ degrades LogLoss from `0.6086` (at $\alpha=0.50$) to `0.6422`, because esports opening-to-closing lines retain persistent inefficiencies on non-major leagues.
  - Static $\alpha = 0.50$ serves as a balanced compromise across all horizons, but an adaptive schedule $\alpha(t) = 0.55$ (for $t > 24\text{h}$) decaying to $\alpha(t) = 0.45$ (for $t < 2\text{h}$) strictly optimizes opening-line EV capture without destabilizing late calibration.

### Non-goals

- Do not use closing odds as features for match outcome models (temporal leakage).
- Do not allow market probabilities to feed back into pure sports rating updates.
- Do not bet automatically or bypass wallet risk bounds.

### Implementation outline

1. Formalize $\alpha(t)$ in `betting_app/services/upcoming_inference_service.py` as a function of `hours_before_start = (match_start - snapshot_time).total_seconds() / 3600`:
   $$\alpha(t) = \text{clip}(0.40 + 0.15 \cdot \sigma((t - 12) / 6), 0.40, 0.55)$$
2. When generating hybrid predictions, calculate the median age of the active odds snapshots relative to match kickoff and parameterize $\alpha$.
3. Record $\alpha(t)$ and `hours_before_start` in `canonical_predictions.diagnostics_json`.

### References

- `reports/exp039_alpha_sweep/summary.json`
- `scripts/benchmark_adaptive_hybrid_alpha.py`

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

---

## IDEA-016 — Horizon-gated and Tier-calibrated EV Signal Filtering

- **Status:** proposed
- **Created:** 2026-09-04
- **Updated:** 2026-09-04

### Problem

The betting application currently evaluates and presents EV+ signals regardless of time-to-match and competition tier. Empirical analysis of the historical betting ledger with Poland's mandatory 12% turnover tax demonstrates that:
1. CLV is highly positive (>+20%) only at long horizons (>24-48h before start), while bets placed <2-6h before match yield zero CLV and negative net ROI (-4.36%) due to tax friction on efficient closing lines.
2. Signals on Tier 1 (LPL, LEC, LCK) and Offseason/Cup tournaments (KeSPA Cup) deliver positive net ROI (+6.5% to +71.7%), whereas ERL / Tier 2 regional leagues exhibit high variance and negative net returns (-23.8% ROI) at the baseline +5% EV threshold.

Displaying unsegmented EV signals creates a hazard where users act on late, low-CLV bets or high-variance regional matches that cannot overcome the 12% tax hurdle.

### Evidence

- Ledger analysis of 201 qualified historical bets on opening lines with 12% tax:
  - **48h+ horizon:** average CLV +20.32%, 68.4% beating closing line, positive yield.
  - **<2h horizon:** average CLV 0.00%, negative yield (-4.36%).
  - **Tier 1 (Major):** N=76, average CLV +21.53%, +6.5% ROI.
  - **Offseason/Cups:** N=32, average CLV +9.86%, 78.1% win rate, +71.7% ROI.
  - **Regional (ERL):** N=76, average CLV +13.46%, 35.5% win rate, -23.8% ROI.

### Non-goals

- Do not automate bet placement.
- Do not hide raw odds or model probabilities; only modulate the derived EV/recommendation signal.
- Do not bypass the 12% turnover tax calculation in any financial metric.

### Prerequisites and open decisions

- Decide whether late signals (<6h) should be hidden entirely, grayed out, or marked with a "Low CLV expected" badge.
- Establish tier-dependent EV thresholds: e.g. +5% EV for Tier 1 / Cups, +10% EV for ERL / Tier 2.

### Implementation outline

1. Add `clv_confidence_tier` to `MatchBoardItem` schema in `betting_app/api/schemas.py`.
2. In `betting_app/api/routers/matches.py`, compute `hours_before_start`:
   - If `hours_before_start < 6.0`: flag signal as `stale_horizon` and suppress positive EV badge.
   - Classify tournament tier using existing `competition_tiers` taxonomy.
   - For ERLs, enforce a stricter EV threshold (e.g. +10%) before emitting an active EV signal.
3. Update frontend `MatchBoardItem` and `MatchDetail` to display tier and horizon confidence chips.

### Affected areas

- `betting_app/api/schemas.py`
- `betting_app/api/routers/matches.py`
- `client/src/pages/MatchList.tsx`
- `client/src/pages/MatchDetail.tsx`

### References

- `reports/exp039_db_market_backtest_v3_corrected/roi_benchmark_ev5/ledger_open_poland_tax_12.csv`
- `reports/exp039_db_market_backtest_v3_corrected/roi_benchmark_ev5/roi_summary.json`

---

## IDEA-017 — Dynamic Blue/Red Side-Selection Advantage by Patch and League

- **Status:** proposed
- **Created:** 2026-09-04
- **Updated:** 2026-09-04

### Problem

Professional League of Legends games exhibit an asymmetry in win rates between Blue and Red sides, historically ranging from 51% to over 57% depending on the meta patch (first pick priority vs counterpick/flex draft power) and specific league.
Currently, the pre-match operational baseline treats match sides symmetrically without incorporating the rolling side win rate of the active patch or tournament.
Furthermore, in Bo3/Bo5 series, Team A (the canonical home team / higher seed) receives side selection for Game 1, and the loser of each game typically chooses side for the subsequent game. Modeling this dynamic can improve both single-map probability and BoN series correlation.

### Evidence

- Patch-level GOL.GG data shows significant drift in Blue side advantage across seasons and tournament patches (e.g. MSI/Worlds patches frequently spike Blue side win rate to 56%+).
- In Bo3 series, winning Game 1 on Blue side creates a strong structural advantage because the losing team must play Game 2 on Blue, altering the series state transitions.

### Non-goals

- Do not violate order symmetry in baseline team ratings: rating updates must remain side-invariant. Side advantage is an additive matchup-level feature, not a distortion of intrinsic team/player skill.
- Do not use in-game draft information before it is timestamped and verified prior to kickoff.

### Prerequisites and open decisions

- Extract and verify which team holds Game 1 side selection from canonical fixtures.
- Materialize a leakage-safe, walk-forward feature: `rolling_blue_winrate_patch` and `rolling_blue_winrate_league` computed strictly from games completed before the match cutoff.

### Implementation outline

1. Create a side-advantage feature builder in `betting_app/ml/features/`.
2. Define a zero-sum logit adjustment:
   $$\Delta \text{logit}_{\text{side}} = \beta_{\text{side}} \cdot (\text{WR}_{\text{blue, patch}} - 0.50)$$
   allocated positively to the team with Game 1 side selection.
3. Test as an ablation on the chronological walk-forward benchmark against the current `v0.4-binom-series` baseline.

### Affected areas

- `betting_app/services/upcoming_inference_service.py`
- `betting_app/ml/features/`
- `betting_app/models/canonical.py`

### References

- `data/golgg_matches.json`
- `docs/03_methodology/01_research_design.md`

---

## IDEA-018 — In-game prop prediction models (total kills, game duration, objectives)

- **Status:** proposed
- **Created:** 2026-09-05
- **Updated:** 2026-09-05

### Problem

The application currently models pre-match winner probabilities (moneyline) for professional League of Legends. Match-winner markets are heavily arbitraged by bookmakers against global liquid exchanges (e.g. Pinnacle, Betfair), leaving narrow margins and requiring high precision to overcome the 12% Polish turnover tax.

In contrast, secondary in-game prop markets—such as **Over/Under Total Kills**, **Over/Under Game Duration**, and **First Objective (Dragon/Baron/Tower/Blood)**—are frequently priced by sportsbooks using simplified league-wide averages or static provider heuristics. These markets exhibit higher variance but also substantially wider model-vs-market mispricings (edge).

### Evidence

- GOL.GG exports contain granular match records with exact `gameDuration`, team kills, deaths, gold differentials at 15m (`GD@15`), and first objective flags.
- Bookmaker analysis shows Polish bookmakers (STS, Fortuna, Betclic, Superbet) offer lines on map totals (e.g. 26.5 kills, 31.5 min duration) with wider pricing variance across books than moneyline markets.

### Non-goals

- Do not modify or replace the frozen thesis model (`Sym-Cal LR-ElasticNet-W20-Binomial` / `exp-039`).
- Do not use in-game or live statistics to generate pre-match predictions; temporal integrity strictly requires using data completed before kickoff.
- Do not place bets automatically; the application remains an analytical intelligence tool.

### Modeling methodology

1. **Total Kills (Map Kill Totals):**
   - Target: Count data ($y \in \mathbb{N}_0$) with overdispersion ($\text{Var}(Y) > \mathbb{E}[Y]$).
   - Model: **Negative Binomial regression (NegBin)** or **Bivariate Poisson** to independently estimate Team A and Team B kill distributions and compute $P(\text{Kills} > L)$.
2. **Game Duration (Map Length):**
   - Target: Strictly positive, continuous, right-skewed ($y \in \mathbb{R}^+$).
   - Model: **Generalized Linear Model (GLM) with Gamma family (log link)** or **Weibull duration model** to compute $P(\text{Duration} > D)$.
3. **First Objectives (First Blood, Dragon, Tower):**
   - Target: Binary outcome ($y \in \{0, 1\}$).
   - Model: Calibrated Logistic Regression based on early-game pace features (`GD@15`, `FB%`, `FT%`).

### Feature engineering contract

- Matchup disparity ($\Delta \text{Rating}$ and win probability from existing rating models).
- Team pace and style vectors from GOL.GG $W20$ rolling windows (`CKPM`, `AGD`, `KPM`, `DPM`, `GD@15`).
- Regional and league pace baselines (e.g. LPL aggressive tempo vs LCK macro control).
- Patch and meta pace shifts.

### Prerequisites and open decisions

- Scrapers in `betting_app/scrapers/` currently extract only moneyline (1-2) odds. Scrapers must be extended to parse map-specific tabs and extract lines and odds for Over/Under totals.
- Polish 12% turnover tax requires $\approx 61.4\%$ accuracy on standard 1.85 / 1.85 lines to break even; selective EV thresholds are mandatory.

### Implementation outline

1. Phase 1: Exploratory data analysis (EDA) on historical GOL.GG duration and kill distributions.
2. Phase 2: Offline model training (Gamma GLM for duration, Negative Binomial for kills) and backtesting against synthetic lines.
3. Phase 3: Extension of STS and Betclic scrapers to collect prop lines and odds.
4. Phase 4: Integration into the API and match detail UI (`MatchDetail.tsx`).

### Affected areas

- `ideas/IDEA-018_in_game_prop_prediction_models.md`
- `betting_app/scrapers/`
- `betting_app/ml/`
- `client/src/pages/MatchDetail.tsx`

### References

- `data/golgg_matches.json`
- `ideas/IDEA-018_in_game_prop_prediction_models.md`

---

## IDEA-019 — Tax-amortized two-leg favorite parlay recommender (Safe Dubel)

- **Status:** proposed
- **Created:** 2026-09-05
- **Updated:** 2026-09-05

### Problem

In the Polish regulated market, bookmakers deduct a mandatory 12% turnover tax on stakes. For single bets on favorites (odds 1.35–2.10), this creates a steep hurdle requiring a +13.64% gross model edge to break even. In historical backtests on 201 verified opening lines, single bets on favorites achieved an empirical win rate of 73.9%, but net ROI was throttled to +11.01%.

### Opportunity

In accumulator (AKO) bets, the 12% turnover tax is paid only once on the coupon stake. Compounding gross odds rather than net odds amortizes the tax impact, reducing the required gross edge per leg to +6.60% (for 2 legs) and +4.35% (for 3 legs).

### Empirical evidence

Backtesting 2-leg parlays against single bets on 201 historical matches with 12% tax (`reports/exp039_db_market_backtest_v3_corrected/roi_benchmark_ev5/ledger_open_poland_tax_12.csv`):
- **Single Favorites (odds <= 2.20):** N=69, Win Rate 73.9%, Profit +75.95 PLN, **ROI +11.01%**, Max Drawdown -60 PLN.
- **2-Leg Favorite Parlays (odds <= 2.20):** N=34, Win Rate 52.9%, Avg Odds 3.01, Profit +122.29 PLN, **ROI +35.97%**, Max Drawdown **-30 PLN**, Max Losing Streak 3.
- **Underdog Parlays (odds > 2.20):** Win Rate collapsed to 10.6%–16.0% with severe drawdowns (-188 PLN) and 12 consecutive losses, proving parlays must be strictly limited to favorites.

### Non-goals and boundaries

- Do not automate bet placement.
- Limit strictly to 2-leg parlays (no 3+ leg "taśmy").
- Restrict candidate legs to favorites (`entry_odds <= 2.20` and `model_probability >= 0.55`).
- Ensure both selections are offered by the same bookmaker.

### Implementation outline

1. Engine: `betting_app/services/parlay_service.py` pairing non-overlapping same-bookmaker favorite bets.
2. API: `GET /matches/recommendations/parlays`.
3. UI: Dedicated "Rekomendowany Dubel Dnia" card in `client/src/pages/MatchList.tsx`.

### Affected areas

- `ideas/IDEA-019_tax_amortized_favorite_parlays.md`
- `betting_app/services/`
- `betting_app/api/routers/matches.py`
- `client/src/pages/MatchList.tsx`

### References

- `reports/exp039_db_market_backtest_v3_corrected/roi_benchmark_ev5/ledger_open_poland_tax_12.csv`
- `ideas/IDEA-019_tax_amortized_favorite_parlays.md`
