---
type: future-idea
id: IDEA-018
category: prop-market-modeling
status: researched
created: 2026-09-05
updated: 2026-09-05
tags: [planning, prop-bets, in-game-stats, kills, duration, count-models, glm]
---

# IDEA-018 — In-game prop prediction models (total kills, game duration, objectives)

- **Status:** researched / ready for implementation
- **Created:** 2026-09-05
- **Updated:** 2026-09-05
- **Empirical Report:** `reports/eda_prop_markets_idea018.md`

## Problem & Motivation

The application currently models pre-match winner probabilities (moneyline) for professional League of Legends. Match-winner markets are heavily arbitraged by bookmakers against global liquid exchanges (e.g. Pinnacle, Betfair), leaving narrow margins and requiring high precision to overcome the 12% Polish turnover tax.

In contrast, secondary in-game prop markets—such as **Over/Under Total Kills**, **Over/Under Game Duration**, and **First Objective (Dragon/Baron/Tower/Blood)**—are frequently priced by sportsbooks using simplified league-wide averages or static provider heuristics. These markets exhibit higher variance but also substantially wider model-vs-market mispricings (edge).


### Empirical Evidence & Distribution Analysis (n = 38,804 games 2022–2026)

- **Overdispersion Proven:** Mean kills = 29.60, Variance = 89.44, Dispersion index $\text{Var}/\mathbb{E} = 3.02$. Standard Poisson model is rejected in favor of Negative Binomial ($\Delta\text{AIC} = -9,018.3$).
- **Regional Divergence:** LCK averages 25.73 kills (CKPM 0.804) vs VCS 30.89 kills (CKPM 1.004) and Regional ERLs 31.11 kills (CKPM 0.999). Static league-wide lines create massive structural edge.
- **Strong Feature Predictive Signal (n = 64,663 games):** Pre-game rolling pace correlation with actual kills is $r = +0.4006$ ($p < 10^{-50}$); duration correlation is $r = +0.2878$.
- **Out-of-Time Model Accuracy (2024–2026 test, n = 21,535):** Negative Binomial GLM achieves LogLoss 0.6350 vs Naive 0.7217 ($\Delta = -0.0867$).
- **Simulated Betting ROI under 12% Polish Tax:** Backtesting on synthetic lines (1.85 / 1.85) yields 75.19% to 82.44% win rate and **+22.4% to +34.2% ROI**.
## Modeling Methodology & Statistical Framework

Standard linear regression (OLS / MSE) fails for in-game statistics due to boundaries, skewness, and variance structures:

1. **Total Kills (Map Kill Totals):**
   * **Distribution:** Count data ($y \in \mathbb{N}_0$). Poisson regression assumes $\mathbb{E}[Y] = \text{Var}(Y)$, but LoL matches exhibit pronounced overdispersion ($\text{Var}(Y) > \mathbb{E}[Y]$) due to differing game states (stomp vs clown-fiesta).
   * **Model:** **Negative Binomial regression (NegBin)** or **Bivariate Poisson** to independently estimate Team A kills and Team B kills, accounting for team-level interaction.
   * **Target probability:** For a bookmaker line $L$ (e.g. 26.5 kills):
     $$P(\text{Kills} > L) = 1 - F_{\text{NegBin}}(L; \mu, \alpha)$$

2. **Game Duration (Map Length in Seconds/Minutes):**
   * **Distribution:** Strictly positive, continuous, right-skewed ($y \in \mathbb{R}^+$).
   * **Model:** **Generalized Linear Model (GLM) with Gamma family (log link)**, or **Log-Normal / Weibull survival/duration models**.
   * **Target probability:** For a bookmaker duration line $D$ (e.g. 31.5 minutes):
     $$P(\text{Duration} > D) = 1 - F_{\text{Gamma}}(D; k, \theta)$$

3. **Binary First Objectives (First Blood, First Dragon, First Tower):**
   * **Model:** Calibrated Logistic Regression / Platt Scaling using early-game metrics (`FB%`, `FT%`, `FDTD%`, `GD@15`).

## Feature Engineering Contract (Pre-Match)

Because champion draft is unavailable prior to match start, pre-match prop models must rely on:

1. **Matchup Disparity ($\Delta \text{Rating}$, Win Probability):**
   * Heavy favorite vs underdog ($\Delta \text{Rating} \gg 0$) strongly correlates with short duration (22–27 min) and low underdog kills.
   * Evenly matched teams correlate with extended macro play, 4th dragon / Elder contests, and higher game duration.
2. **Team Pace & Style Vectors ($W20$ Rolling Window from GOL.GG):**
   * `CKPM` (Combined Kills Per Minute): sum of kills and deaths per minute.
   * `AGD` (Average Game Duration in seconds).
   * `KPM` (Kills Per Minute) and `DPM` (Deaths Per Minute).
   * Early aggression indicators: `GD@15`, `CSD@15`, `First Tower %`.
3. **Regional & League Baselines:**
   * High-pace regions (e.g. LPL, VCS) vs controlled macro regions (e.g. LCK).
4. **Patch & Meta Temporal Tracking:**
   * Patch-level game pace shifts (durability patches, tower plate gold adjustments, voidgrub spawn timings).

## Non-Goals & Safety Boundaries

- **Frozen Thesis Protection:** No modification or replacement of the frozen thesis model (`Sym-Cal LR-ElasticNet-W20-Binomial` / `exp-039`). Prop models form an independent secondary service.
- **Strict Temporal Integrity:** Pre-match prop predictions must strictly use data from completed matches with `end_time < match_start_at`. Completed game statistics for the target match must never enter feature generation.
- **No Automatic Betting:** Preserves the application's manual research and analysis boundary.

## Prerequisites & Scraper Roadmap

1. **Bookmaker Line Collection:**
   * Existing scrapers only collect 1-2 moneyline odds. Scrapers (starting with STS and Betclic) must be extended to navigate map-specific tabs and parse `total_kills` and `game_duration` lines and odds.
2. **Break-Even Hurdle:**
   * At standard lines of 1.85 / 1.85 with 12% Polish tax ($\text{effective odds} = 1.85 \times 0.88 = 1.628$), break-even requires $\approx 61.4\%$ accuracy:
     $$p_{\text{break-even}} = \frac{1}{1.85 \times 0.88} \approx 0.614$$
   * Selective EV filtering is mandatory (only betting when predicted edge exceeds threshold $\approx 5\%$).

## Implementation Outline

1. **Phase 1 (EDA & Data Validation):**
   * Extract historical GOL.GG games (`game_duration`, `kills_blue`, `kills_red`, `league`, `patch`).
   * Analyze correlation between $W20$ team pace and final game duration / total kills.
2. **Phase 2 (Offline Model Prototyping):**
   * Train Gamma GLM for duration and Negative Binomial for total kills.
   * Chronological out-of-time evaluation on 2024–2026 matches against synthetic lines.
3. **Phase 3 (Scraper Expansion):**
   * Add map prop parser to `STS` and `Betclic` scrapers in `betting_app/scrapers/`.
4. **Phase 4 (UI Integration):**
   * Expose in-game prop predictions on the match detail view (`MatchDetail.tsx`).

## References & Detailed Architecture

- Detailed Technical & Testing Plan: [`docs/plan_modelowania_props_zabojstwa_i_kursy.md`](../docs/plan_modelowania_props_zabojstwa_i_kursy.md)
- Empirical EDA Report: [`reports/eda_prop_markets_idea018.md`](../reports/eda_prop_markets_idea018.md)
- Walk-Forward Cross-Validation Engine: [`betting_app/ml/props/walk_forward.py`](../betting_app/ml/props/walk_forward.py)
- Core Distribution Engines: [`betting_app/ml/props/kill_distribution_model.py`](../betting_app/ml/props/kill_distribution_model.py) and [`betting_app/ml/props/team_spread_model.py`](../betting_app/ml/props/team_spread_model.py)
