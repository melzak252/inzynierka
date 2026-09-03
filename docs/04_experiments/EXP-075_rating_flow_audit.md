---
type: experiment-report
experiment_id: EXP-075
status: completed-audit
model_family: Player Glicko-2 successor diagnostic
related: [EXP-039, EXP-069, EXP-070, EXP-073, EXP-074]
---

# EXP-075 — Player-rating flow across competition ecosystems

## Decision

**Do not patch the current Player Glicko-2 ratings with an ad hoc regional multiplier, and do not replace the frozen EXP-039 artifact.** The audit finds a real cross-ecosystem location problem, but not enough clean major-versus-lower evidence to identify a safe correction.

Build a versioned successor with two explicit layers:

1. an owned, mathematically corrected, daily-batched Glicko-2 implementation for player skill and uncertainty; and
2. a partially pooled, time-varying competition-family offset learned from cross-family matches, with player transfers carrying player state but never creating synthetic results.

The current `gl` stream remains a frozen comparison baseline. The successor must receive a new feature/version name and must pass chronological comparison before any production or EXP-039 integration.

## What EXP-075 implemented

The audit added infrastructure, not a new production rating:

- `src/models/competition_tiers.py`: canonical, date-aware tournament classification into `international`, `major`, `minor_top_level`, `regional`, `development`, and `unknown`, independently of `domestic` versus `cross_league` scope;
- `scripts/05_ratingi_baseline/05i_rating_flow_audit.py`: strict prior-date affiliation reconstruction, direct-match and player-transfer flow graphs, Player Glicko replay diagnostics, cohort calibration, symmetric correction probes, and paired block bootstrap comparisons;
- `betting_app/tests/test_competition_tiers.py`: precedence, historical alias, date-transition, punctuation, missing-value, and cross-league regression cases.

The final taxonomy classifies all 1,182 tournament labels in the current 40,159-match non-draw corpus. Classification is explicit and reviewable; unmatched future names remain `unknown` rather than silently becoming regional evidence.

## Reproduction

```bash
/home/melzak/dev/inzynierka/.venv/bin/python \
  scripts/05_ratingi_baseline/05i_rating_flow_audit.py
```

Evidence:

```text
reports/experiments/exp075_rating_flow_audit/summary.json
SHA256 3cad75e82ea4771faeffa6cb87485a0ab09505b0632e2706511a83a94b31e482
```

Generated tables:

- `competition_coverage.csv`: 1,182 competition labels plus header;
- `unknown_competitions.csv`: header only; no current unmatched label;
- `flow_nodes.csv`: 50 domestic competition families plus header;
- `flow_edges.csv`: 1,205 aggregated direct/transfer edges plus header;
- `bridge_predictions.csv`: 2,725 strictly prior-affiliated cross-league predictions plus header;
- `diagnostic_model_results.csv`: 48 model/split/cohort metrics plus header;
- `diagnostic_model_comparisons.csv`: 18 paired holdout comparisons plus header;
- `player_rating_distribution.csv`: 57 active-player distribution groups plus header;
- `current_top_players.csv`: top 100 active players plus header.

No odds values are features or targets. `data/odds.csv` contributes match-ID membership only.

## Temporal contract

The audit replays 40,159 non-draw matches from 2013-09-16 through 2026-05-28.

For every calendar date:

1. team and player affiliations are read only from earlier dates;
2. every match on the date is observed before any affiliation update from that date;
3. domestic competitions update the last known domestic family only after the whole date is observed;
4. international, cross-league, and unknown competitions never overwrite domestic affiliation;
5. conflicting same-day player destinations remain unresolved.

Measured exclusions and ambiguities:

- 498 draws excluded;
- 4 matches excluded from the fresh current-player replay for incomplete or ambiguous five-player rosters;
- 57 same-day player-affiliation conflicts left unresolved;
- 713 cross-league matches lacked a strictly earlier affiliation for at least one team;
- 129 cross-league matches had both teams from the same domestic family;
- 2,596 matches formed direct cross-family bridges.

Historical rosters have no independent `available_at` timestamp. Attaching a roster to its match date is necessary but does not prove source-time availability within that date.

## How rating evidence currently flows

`RatingManager` exposes a split lifecycle:

1. `update_before_match()` applies Glicko inactivity inflation and mutates last-seen dates;
2. `predict_match()` reads team and player ratings;
3. callers invoke `update_after_game()` once per game for Elo, TrueSkill, OpenSkill, Plackett--Luce, and Thurstone--Mosteller;
4. callers invoke `update_after_match()`, which loops over the same games and updates Glicko sequentially.

`update_before_match()` mutates rating uncertainty and activity dates before the caller proves that a usable result exists. The historical generator validates rosters first but checks for an empty score list only after this mutation. A malformed/skipped event can therefore advance activity bookkeeping without contributing evidence. The successor must validate the complete typed event before touching state.

The main historical generator batches result application by date, so current stored predictions do not use same-day outcomes. Other callers must reproduce the two update calls in the correct order. The contract is fragile because omitting either method silently updates only part of the rating family.

For Player Glicko, each player receives the team game result against the opponent roster's pre-update aggregate. Player transfers naturally carry that player's state into the destination ecosystem. There is no explicit competition-strength state, so sparse cross-league games must align every ecosystem through individual player ratings alone.

### Connectivity

| Graph | Components | Isolated families | Families without flow in last 365 days |
|---|---:|---:|---:|
| Direct cross-league matches only | 18 | 17 | 29 |
| Direct matches plus inferred player transfers | **1** | **0** | 8 |

The 17 direct-match isolates are development or historical domestic families: CBLOL Academy, Circuito Desafiante, EU Challenger Series, Hitpoint Challengers, LCK CL, LCS Proving Grounds, LJL Academy, LRN, LRS, NA Academy, NA Challenger Series, NACL, Prime League Second Division, REL, SuperLiga Second Division, TCL Div2, and Turkey Academy.

This distinction matters. The system is not mathematically disconnected once transfers are included, but a graph path is not precise calibration. Transfer paths are indirect, delayed, roster-dependent, and can be dominated by a small number of players. Eight historical families have neither a direct bridge nor a transfer in the last year of the corpus.

## Quantitative failure evidence

### Raw Player Glicko cohorts, full history

| Cohort | N | LogLoss | Brier | AUC | Mean P(team 1) minus team-1 win rate |
|---|---:|---:|---:|---:|---:|
| Overall | 40,159 | 0.602104 | 0.207743 | 0.73689 | -0.02163 |
| Major vs major | 10,698 | 0.605456 | 0.208890 | 0.73467 | -0.01883 |
| Regional vs regional | 12,349 | 0.599720 | 0.206607 | 0.74107 | -0.02532 |
| Development-involved | 6,244 | 0.629208 | 0.219939 | 0.69774 | -0.02096 |
| Known cross-league | 2,725 | 0.623964 | 0.217329 | 0.71013 | -0.03339 |
| Major vs lower tier | 483 | 0.550457 | 0.185005 | 0.80698 | side-oriented below |

Side-1 calibration gaps partly reflect side ordering. After orienting every major-versus-lower observation to the major team, Player Glicko predicts a mean major win probability of **61.71%**, while major teams win **75.98%**: underestimation by **14.27 percentage points**.

Of the direct cross-league major-versus-lower rows, 457 are major versus minor-top-level and only 6 are major versus regional. The corresponding full-history major-win rates and predicted means are 77.46% versus 62.74%, and 66.67% versus 50.36%. The six regional rows are not enough to identify a regional correction.

### Current-player scale

Among 1,241 players active within 60 days of the corpus endpoint:

| Affiliation tier | Active players | Median rating | P90 rating | Median RD |
|---|---:|---:|---:|---:|
| Major | 219 | 1789.49 | 1992.91 | 68.76 |
| Minor top-level | 187 | 1610.22 | 1772.82 | 82.92 |
| Regional | 573 | 1490.46 | 1764.62 | 78.86 |
| Development | 262 | 1489.60 | 1665.55 | 82.53 |

The broad ordering is plausible, but the upper tail overlaps heavily. The top 100 contains 73 major, 6 minor-top-level, and 21 regional players. LFL's active median is 1687.03 and its maximum is 2008.60, close to or above parts of the major-league distributions. These values explain the EXP-074 regional-team anomalies; they do not by themselves prove which individual is misrated.

## Diagnostic corrections

Three symmetric probes were fit on 2021-01-01 through 2023-12-31 and evaluated on identical eligible rows from 2024-01-01 onward:

- global logit slope only;
- global slope plus broad tier offsets;
- tier offsets plus context-specific slopes.

All models have no intercept. Tier features are side-A minus side-B, and context features multiply the signed baseline logit, so swapping sides negates the feature vector and complements the probability.

The 2024+ period is untouched by this fit but has been inspected by prior repository experiments. Results are diagnostic, not a new final holdout.

### 2024+ overall

| Candidate | N | LogLoss | Delta vs raw Player Glicko | 95% paired block CI |
|---|---:|---:|---:|---:|
| Raw Player Glicko | 9,796 | 0.578645 | — | — |
| Global slope | 9,796 | 0.576014 | -0.002631 | [-0.003265, -0.002120] |
| Tier offset | 9,796 | **0.575944** | **-0.002700** | [-0.003809, -0.001781] |
| Tier + context slopes | 9,796 | 0.576206 | -0.002438 | [-0.003782, -0.001275] |

The tier model's overall gain is real relative to the raw baseline, but almost all of it is already obtained by the global slope (`1.0850`). Its advantage over the global-slope probe is only `0.000070` LogLoss and was not the preselected paired comparison.

### 2024+ bridge cohorts

| Candidate | Known cross-league N=709 | 95% CI | Major-vs-lower N=67 | 95% CI |
|---|---:|---:|---:|---:|
| Global slope delta | -0.003370 | [-0.004871, -0.002433] | -0.006151 | [-0.010465, -0.002192] |
| Tier offset delta | -0.005443 | **[-0.021432, +0.005986]** | -0.032946 | **[-0.128540, +0.087699]** |
| Tier + context delta | -0.011076 | **[-0.025111, +0.000544]** | -0.027620 | **[-0.123309, +0.092293]** |

Bootstrap units are competition-family/year for cross-league events and calendar month otherwise; 5,000 paired replicates, seed 75. The known cross-league holdout has 12 event blocks. The major-versus-lower holdout has only 67 rows over 10 blocks.

**Interpretation:** global underconfidence is established. A broad tier/location correction is plausible, but its bridge-specific effect is not established; both tier-aware intervals cross zero and the major-versus-lower intervals are extremely wide. The overall tier win cannot justify hard-coded tier weights.

The context-slope model also worsens the 2024+ development cohort by `+0.002576` LogLoss, 95% CI `[+0.000130, +0.005212]`. More parameters are already overfitting a sparse boundary.

## Mathematical defects to fix before flow tuning

The installed `glicko2==2.1.0` package must not be the implementation base for the successor:

1. its volatility objective uses internal rating squared where the official Glicko-2 equation requires internal deviation $\phi^2$;
2. its rounded worked-example test does not expose this defect;
3. it has no evidence-weight API or input-domain validation;
4. project prediction truncates roster-average rating and RD to integers;
5. a best-of-series is processed as sequential single-game rating periods, making results dependent on game order and changing volatility/RD;
6. private package fields (`_tau` and name-mangled state) are treated as an extension API;
7. the prediction equation is a separate symmetric heuristic using both sides' RD, not the update likelihood.

The team wrapper now snapshots both teams before updating, which is correct and must be preserved. With unequal uncertainty, rating changes need not be zero-sum; swap/complement equivariance, not point conservation, is the invariant.

## Required successor design

### 1. Own the corrected Glicko-2 equations

Use internal scale

$$
\mu=(r-1500)/173.7178,\qquad \phi=RD/173.7178.
$$

For observations $(\mu_j,\phi_j,s_j,w_j)$, implement power-likelihood evidence weighting:

$$
I=\sum_j w_j g_j^2 E_j(1-E_j),\quad v=I^{-1},\quad
S=\sum_j w_j g_j(s_j-E_j),\quad \Delta=vS.
$$

Use weighted $v$ and $\Delta$ in the official volatility root solve, then

$$
\phi' = \left(\phi_*^{-2}+v^{-1}\right)^{-1/2},\qquad
\mu'=\mu+\phi'^2S.
$$

Contract:

- `w=1` equals the corrected unweighted implementation;
- all-zero or empty evidence is an exact state no-op;
- zero-weight observations equal removing those observations;
- both sides are computed from immutable pre-period snapshots and committed together;
- observations in one rating period are permutation invariant;
- negative, non-finite, or misaligned weights and invalid outcomes fail loudly.

Do not interpolate post-update ratings. It has no coherent RD/volatility update and breaks batch composition.

### 2. Make rating periods explicit

Use one daily rating period because source timestamps are calendar dates. For every date:

1. inflate uncertainty once from the previous active period;
2. freeze the complete pre-date state;
3. predict every eligible match on that date;
4. collect all game observations from all series on that date;
5. update each player once from the full frozen observation batch;
6. commit all states together.

Repeated games against one opponent may appear as repeated observations in the same batch. Any series-level cap must be an explicit selected hyperparameter, not an accidental consequence of sequential mutation.

Replace the fragile `update_after_game()` plus `update_after_match()` protocol with one typed event/batch API. Migrate every caller together: historical generation, EXP-039 successor retraining, DB backtests, `rebuild_ratings.py`, rating sweeps, and evaluation scripts.

### 3. Separate player skill from ecosystem location

Use a versioned candidate state such as

$$
S_{T,t}=\frac{1}{|R_T|}\sum_{p\in R_T}\mu_{p,t}+\alpha_{f(T),t},
$$

where $\alpha_{f,t}$ is a competition-family offset with tier-level partial pooling and uncertainty that grows when cross-family evidence is stale.

Rules:

- same-family domestic matches update player differences but contain no direct information about the common family offset;
- cross-family matches update player states and the relevant family contrast from one frozen pre-match state;
- transferred players retain their player state; transfers are not synthetic wins/losses;
- constrain the weighted mean of family offsets to zero, or use another explicit invariant anchor, to make location identifiable;
- use family-level state rather than only `major/regional/development`; the tier probe is too coarse and regional ecosystems differ materially;
- keep uncertainty and recency visible in predictions and persisted metadata.

Do not globally downweight all regional games merely because they are regional. Those games contain the strongest information about within-region player ordering. A lower observation weight reduces both information and rating movement but does not identify the region's location relative to another ecosystem.

### 4. Use weights only for evidence quality

If weighting is introduced, select it for observable reliability: incomplete/substitute rosters, uncertain identity resolution, abnormal formats, or an empirically selected series-correlation cap. Default complete, aligned observations to weight one. Competition prestige is not evidence quality.

## Verification matrix

### Mathematical unit tests

1. Official Glicko-2 worked example at tight tolerances for rating, RD, and volatility.
2. A high-precision case that distinguishes $\phi^2$ from rating-squared in the volatility objective.
3. Weight-one equality with the corrected unweighted path.
4. Exact zero-weight/empty-evidence no-op.
5. Mixed zero weights equal observation removal.
6. Integer batch replication equivalence.
7. Side swap plus complemented result swaps posterior states.
8. Same-period observation permutation invariance.
9. Reversing player/side iteration does not change results.
10. Input validation for domains, finiteness, and list lengths.
11. Prediction complementarity without integer truncation.
12. Inactivity inflation tested separately from match evidence.

### Chronological model evaluation

- warm up on pre-2021 history;
- fit/calibrate on 2021--2022;
- select parameters on 2023 only;
- refit through 2023 after selection;
- use 2024+ only as the already-reused diagnostic cohort;
- reserve data after the 2026-09-03 design freeze for prospective promotion evidence.

Compare every candidate and baseline on identical rows. Primary metric: paired LogLoss. Also report Brier, AUC, calibration slope/intercept or reliability bins, exact dates, exclusions, and sample counts.

Required cohorts:

- overall;
- major versus major;
- regional versus regional;
- development-involved;
- all known cross-league;
- major versus minor-top-level;
- major versus regional;
- each sufficiently populated competition family;
- cold-start and recent-transfer players;
- high-RD versus established players.

Use at least 5,000 paired block-bootstrap replicates: competition edition for bridge events and calendar month for domestic data. Do not make a bridge promotion claim below 12 event editions, 200 bridge matches, four domestic families, and two seasons.

Predeclare promotion gates:

- overall non-inferiority: upper one-sided 95% CI below `+0.002` LogLoss;
- bridge improvement: upper two-sided 95% CI below zero;
- no sufficiently populated ecosystem worse by `+0.005` LogLoss or more;
- no material calibration regression;
- side symmetry, date-batch invariance, and clean cold-start behavior must hold exactly.

## Risks and rejected shortcuts

- **Hard-coded league bonuses:** fit sparse historical outcomes, drift when formats change, and create discontinuities when a player transfers.
- **Downweight every lower-tier match:** weakens within-tier ordering and uncertainty without solving cross-tier location.
- **Post-update interpolation:** not a Glicko posterior and cannot update RD/volatility coherently.
- **Treat every transfer as a bridge result:** invents competitive evidence and double-counts player state.
- **Fit on closing odds:** leaks a market benchmark into the sports model; odds remain diagnostic only.
- **Promote from current 2024+ results:** this period has already been inspected repeatedly.
- **Modify `gl` or EXP-039 in place:** destroys reproducibility of the frozen thesis model.

## Acceptance criteria for implementation

A successor is ready for consideration only when:

1. the owned implementation passes the mathematical matrix;
2. all callers use one date-batched event API and no dummy player can enter persisted rankings;
3. taxonomy coverage and unknown counts are emitted on every run;
4. family offsets, their uncertainty, and last bridge date are persisted with the rating version;
5. a full rebuild and an incremental rebuild produce identical state at the same cutoff;
6. candidate-versus-baseline predictions use identical temporal rows;
7. the predeclared cohort and uncertainty gates pass on prospective data;
8. a new artifact/version is produced and EXP-039 remains byte-for-byte unchanged.

## Successor implementation status

The side-by-side candidate `player-glicko2-family-v1` implements the owned
corrected equations, complete calendar-date batches, competition-family
location state, strict prior-date affiliations, explicit unknown handling, and
full/incremental persistence under rating-system key `gl2f`. It does not replace
legacy `gl`, `latest-full`, EXP-039, upcoming features, predictions, EV, or
betting behavior.

The fixed 2024+ diagnostic replay aligned 9,822 rows after excluding 526 rows
where the legacy control could depend on an earlier same-day participant result:

- overall LogLoss: `0.582048` candidate versus `0.579696` legacy, delta
  `+0.002353`, one-sided 95% upper bound `+0.004278`; the `+0.002`
  non-inferiority gate did **not** pass;
- known cross-league LogLoss: `0.529776` candidate versus `0.595202` legacy,
  delta `-0.065426`, two-sided 95% interval
  `[-0.087006, -0.044583]`;
- development-involved LogLoss worsened by `+0.003023`, with 95% interval
  `[-0.000176, +0.006192]`.

These results support retaining a server-side research snapshot for ranking
inspection, but not changing any operational default. The cohort was already
used diagnostically, so prospective promotion evidence remains unavailable.

## Sources

- Mark Glickman, [Example of the Glicko-2 system](https://www.glicko.net/glicko/glicko2.pdf).
- LVP, [Iberian Cup 2020 announcement and participating ecosystems](https://iberiancup.lvp.global/noticias/presentacion-iberian-cup-2020/).
- MČR, [2019 Czech championship archive](https://www.mcr.gg/rocniky/2019).
- Leaguepedia, [Trinity Force Puchar Polski](https://lol.fandom.com/wiki/Trinity_Force_Puchar_Polski).
- Games of Legends, [REL Season 2](https://www.gamesoflegends.com/tournament/tournament-stats/REL%20Season%202/).
