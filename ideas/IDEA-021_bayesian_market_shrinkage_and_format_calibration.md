# IDEA-021 — Bayesian Market Shrinkage and Tail Gating (Successor to Operational Hybrid)

- **Status:** researched
- **Created:** 2026-09-06
- **Updated:** 2026-09-06
- **Driver:** ISSUE-001 Underdog Overconfidence and Operational Fusion Instability

## Problem

The operational model (`Operational-PlayerTeamRatings-W20`) lacks an output calibration stage, combining heuristic rating probabilities linearly ($0.70 \cdot P_{\text{player}} + 0.20 \cdot P_{\text{team}} + 0.10 \cdot P_{\text{w20}}$). This produces severe overconfidence (calibration slope 0.88), inflating win probabilities on high underdogs (odds 3.50–5.00) from an empirical 20.4% to >42.7%, causing rapid capital loss (-26.9% ROI under 12% Polish turnover tax).

Attempts to fix this solely via global temperature scaling ($T=1.13$) improve ECE but fail to repair thick tail distortions. Ad-hoc format-specific scaling ($T_{\text{Bo1}}=1.36$) over-flattens single-map predictions (degrading Bo1 LogLoss from 0.589 to 0.620).

## Opportunity & Solution (Occam's Razor)

1. **Pure Logit Bayesian Market Shrinkage**:
   Combine the model's pre-match log-odds ($z_{\text{model}} = \text{logit}(P_{\text{model}})$) with the bookmaker consensus no-vig market log-odds ($z_{\text{market}} = \text{logit}(P_{\text{market}})$):
   $$z_{\text{shrunk}} = (1 - \alpha) \cdot z_{\text{model}} + \alpha \cdot z_{\text{market}}, \quad \alpha = 0.35 - 0.40$$
   This treats the market as an informative Bayesian prior, preserving 60–65% of the model's predictive edge while damping extreme estimation variance in the tails.

2. **Hard Underdog Quarantine Gate**:
   Rather than introducing unstable non-linear alpha thresholds that still leave residual losses (-41% ROI on 12 residual bets), enforce a deterministic capital filter: zero bets allowed on odds bracket $[3.50 - 5.00]$.

## Empirical Evidence (5-Fold CV on 483 Canonical Matches)

- **Predictive Quality**:
  - Uncalibrated Model: LogLoss `0.5657`, Brier `0.1924`, Slope `0.881`
  - Market Alone (No-Vig): LogLoss `0.5838`, Brier `0.1982`, Slope `0.785`
  - **Bayesian Market Shrinkage ($\alpha=0.40$)**: **LogLoss `0.5500`**, **Brier `0.1864`**, **Slope `1.002`** (near-perfect calibration).
  - Outperforms both the pure model and the market alone, proving orthogonal information aggregation.

- **Financial Yield (12% Tax, Flat 1u Staking)**:
  - Total bets placed (edge > 5%): 124 bets.
  - Net Profit: **+123.40 units** (vs +106.84 units baseline).
  - Net ROI: **+99.51%** (vs +57.75% baseline).
  - With hard quarantine on $[3.50 - 5.00]$: Underdog drag reduced to 0 units.

- **Cold-Start / Two-Stage Architecture**:
  - Stage 1 (Before market quotes open): Model operates in autonomous mode using global temperature calibration ($T=1.13$).
  - Stage 2 (When quotes are scraped): Transactional mode applies Bayesian Market Shrinkage ($\alpha=0.38$) before computing EV signals.

## Non-goals and Boundaries

- Do not use closing odds (temporal leakage hazard); use only verified pre-match quotes strictly before `match_start_at`.
- Do not apply piecewise step functions to $\alpha$ that disrupt probability monotonicity and inflate Bo1 LogLoss.
- Preserve the frozen thesis EXP-039 artifact.

## Affected Areas

- `betting_app/services/upcoming_inference_service.py` (`generate_hybrid_predictions`)
- `betting_app/ml/calibration/candidate_calibration.py` (`UncertaintyGatedCalibrator`)
- `betting_app/api/routers/timing.py` (`model_profitability_audit`)
- `issues/ISSUE-001_miscalibration_underdogs_3.5_to_5.0.md`
