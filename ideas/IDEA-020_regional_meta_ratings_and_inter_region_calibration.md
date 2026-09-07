---
type: future-idea
id: IDEA-020
category: model-architecture
status: proposed
created: 2026-09-05
updated: 2026-09-05
tags: [planning, ratings, openskill, pandaskill, regional-meta, inter-region, worlds, msi, calibration]
---

# IDEA-020 - Regional Meta-Ratings and Cross-Regional Strength Calibration (Meta-OpenSkill)

- **Status:** proposed
- **Created:** 2026-09-05
- **Updated:** 2026-09-05
- **Related:** `docs/future_ideas.md` (IDEA-002, IDEA-011, IDEA-016), `docs/04_experiments/EXP-068_pandaskill_history.md`, `docs/04_experiments/EXP-071_tuned_openskill_pandaskill.md`

## Problem

In professional League of Legends, over 95% of matches occur within isolated regional ecosystems (LCK, LPL, LEC, LCS, VCS, PCS, CBLOL, LLA, etc.). Standard Bayesian rating systems (Glicko-2, TrueSkill, OpenSkill, Plackett–Luce) treat all games identically on a single global rating scale without regional context:
1. **Regional Rating Inflation / Isolation:** Teams dominating weaker or minor regional leagues (e.g. CBLOL or historical PCS/LCL) accumulate high $\mu$ values equivalent to top LCK/LPL teams simply by racking up wins against weak domestic opposition.
2. **International Miscalibration at MSI and Worlds:** When cross-regional matches occur, standard ratings fail because a 1600 Elo in LCK is vastly stronger than a 1600 Elo in a minor region. The model overestimates minor-region champions and underestimates major-region seeds.
3. **Absence of Effective-Dated Region Mapping in Data Contracts:** In local experiments `EXP-068` and `EXP-071`, Meta-OpenSkill was explicitly ablated/disabled because the local repository lacked an authoritative, point-in-time point-of-truth mapping teams and tournaments to stable regional tiers without temporal leakage.

## Opportunity: PandaSkill Regional Meta-Rating Architecture

In PandaScore's research (*PandaSkill: Player Performance and Skill Rating in Esports: Application to League of Legends*, arXiv:2501.10049), De Bois et al. proposed a two-level hierarchical Bayesian rating framework:
- **Intra-Region Ratings:** Each player/team maintains a domestic skill rating $\theta_i \sim \mathcal{N}(\mu_i, \sigma_i^2)$ updated during regular season domestic play.
- **Regional Meta-Ratings:** Each region $r$ maintains a Meta-Rating $\mathcal{M}_r \sim \mathcal{N}(\mu_r^{\text{meta}}, (\sigma_r^{\text{meta}})^2)$ reflecting the global strength of that region relative to other regions.
- **Effective Cross-Regional Skill:** When competing internationally, effective player/team rating is the sum of domestic rating and regional offset:
  $$\theta_{i, \text{global}} = \theta_{i, \text{local}} + \mu_{\text{meta}}(r)$$
- **Dual Update Rule:**
  - In domestic matches (team A and B from same region $r$): only individual ratings $\theta$ update; $\mathcal{M}_r$ remains unchanged.
  - In cross-regional matches (team A from region $r_1$, team B from region $r_2$): **both** individual ratings and regional meta-ratings $\mathcal{M}_{r_1}, \mathcal{M}_{r_2}$ update based on the match outcome!

### Empirical Evidence from Published PandaScore Research:
- On inter-region international matches (MSI and Worlds), **PScore + Meta FFA OpenSkill reached 70.07% accuracy** (compared to 64.79% for standard OpenSkill without meta-ratings).
- Expected Calibration Error (ECE) on inter-region matches improved from **1.77% to 1.01%**.
- Agreement with expert consensus rankings surged from **74.33% to 80.63%** majority concordance, and up to **88.98%** average unanimity concordance.

## Local Research Evidence (EXP-068 and EXP-071)

Local standalone PandaSkill experiments (`/tmp/pandaskill-exp068/summary.json` and `/tmp/pandaskill-exp071/summary.json`) proved:
- Standalone standard OpenSkill achieved LogLoss `0.6762` on 31,009 chronological matches (2020–2026).
- Tuned Thurstone–Mosteller OpenSkill (`EXP-071`) significantly improved FFA LogLoss from `0.6437` to `0.6387` ($p < 0.001$, CI $[-0.0078, -0.0016]$).
- However, adding PandaSkill directly to the `EXP-039` metamodel yielded zero incremental improvement ($\Delta \text{LogLoss} = +0.000063$, CI includes zero) because the existing model already captures team-level rolling stats and domestic ratings.
- **Crucial conclusion:** Standalone ratings without regional meta-calibration hit a hard ceiling. The only untested component of the PandaSkill paper that showed massive gains ($+5.28\%$ accuracy on international matches) is **Regional Meta OpenSkill**.

## Non-goals and Safety Boundaries

- **No manual arbitrary multipliers:** Regional offsets must be inferred dynamically through Bayesian updates on inter-region match results, not hardcoded static multipliers (e.g. "LCK = 1.2x").
- **Strict point-in-time regional mapping:** Team region memberships must reflect the exact league played in at match time (e.g. imports, franchise relocations, academy leagues). Never infer historical region from contemporary 2026 status.
- **Preserve EXP-039 thesis freeze:** This is an exploration for candidate successors (post-EXP-039); it must never overwrite frozen production artifacts.

## Implementation Outline

1. **Data Contract: Effective-Dated League-to-Region Hierarchy:**
   - Create `src/ratings/regional_context.py` mapping tournament leagues (from GOL.GG and bookmaker sources) to canonical competition tiers and regional clusters (`LCK`, `LPL`, `LEC`, `LCS`, `APAC`, `CBLOL`, etc.).
   - Define point-in-time regional identity for each match.
2. **Hierarchical Meta-Rating Engine:**
   - Implement `RegionalMetaRating` extending `PandaSkillRating` or `OpenSkillRating`:
     - Maintain state vector of `region_mu` and `region_sigma` initialized at prior ($\mu_0 = 25.0, \sigma_0 = 8.333$).
     - Intra-region matches: update teams/players, freeze region meta.
     - Inter-region matches: composite team rating = $\text{team\_rating} + \text{region\_meta}$; backpropagate OpenSkill update to both team and region entities.
3. **Ablation & Evaluation Framework:**
   - Backtest on 2020–2026 international matches (MSI, Worlds, Rift Rivals, First Stand).
   - Evaluate against:
     - Baseline Glicko-2 / OpenSkill (uncalibrated single scale).
     - Static Tier Adjustments (`betting_app/services/competition_service.py`).
     - Dynamic Meta-OpenSkill.
   - Metrics: LogLoss, Brier score, ECE on international matches, and cross-league ranking concordance.

## Acceptance Criteria

1. Dynamic regional meta-ratings update strictly after inter-region games without lookahead leakage.
2. Inter-region LogLoss and Brier score strictly outperform uncalibrated OpenSkill and Glicko-2 baselines.
3. Domestic ratings remain stable and are not disrupted or artificially inflated by domestic stomps.
4. Deterministic test suite verifying invariance to team order and identical updates under side reversal.

## References

- De Bois, M., et al. (2025). *PandaSkill: Player Performance and Skill Rating in Esports: Application to League of Legends*. arXiv:2501.10049.
- Repository implementation: `src/ratings/pandaskill_rating.py` (`use_meta` flag).
- `docs/04_experiments/EXP-068_pandaskill_history.md`
- `docs/04_experiments/EXP-071_tuned_openskill_pandaskill.md`
