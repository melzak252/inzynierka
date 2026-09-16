# TODO 02: Regional Family Rating Engine (`REGION_PLAN.md`)

**Priority:** P1 (High Modeling Impact)  
**Target Files:**
- `src/ratings/family_calibrated_glicko2.py`
- `src/ratings/glicko2_core.py`
- `rating-foundation-20260915/REGION_PLAN.md`

---

## 1. Problem Statement
The diagnostic audit demonstrated a systemic failure mode in international/inter-regional tournaments (MSI, Worlds, EMEA Masters, EWC):
- Baseline Causal A0 predicted a **$59.28\%$ win rate** for major region teams facing regional/lower-tier teams.
- The actual observed win rate was **$72.94\%$** (a $-13.66\%$ structural deficit).
- Cause: Player and team ratings calibrated on domestic leagues carry inflated point pools ("regional rating bubble"). Dominant players in ERLs or minor regions do not scale 1:1 against major regions.

---

## 2. Specification & Implementation

### A. Resolve Best-of Likelihood Mismatch
In `family_calibrated_glicko2.py`, ensure map-level latent probabilities ($p_{\text{map}}$) are mapped to series probabilities ($P_{\text{series}}$) via the exact independent series projection:
$$P_{\text{Bo3}}(p) = p^2 (3 - 2p), \quad P_{\text{Bo5}}(p) = p^3 (10 - 15p + 6p^2)$$
Never train map likelihood directly against a multi-game series outcome without series combinatorics.

### B. Regional Tier Discounting Factor ($\gamma = 0.70$)
When a team from a lower-tier/regional competition family faces a team from a major competition family (LCK, LPL, LEC, LCS):
1. Apply the verified discount factor $\gamma = 0.70$ to the lower-tier team's effective rating differential:
   $$\Delta r_{\text{effective}} = r_{\text{major}} - \gamma \cdot r_{\text{regional}}$$
2. In logit space, this corresponds to an offset of $\approx +0.65$ in favor of the major-region team.

### C. Explicit Rules for Transfers, Substitutes, and Decay:
1. **Historical Substitutes:** Explicit player ID matching; do not inherit the starter's rating for an academy call-up.
2. **Cross-Region Transfers:** When a player transfers between regions, decay prior rating variance (increase Glicko-2 $\text{RD}$) toward the destination family mean.
3. **Inactivity Decay:** Increase rating deviation ($\text{RD}$) according to elapsed calendar time between tournaments without mutating history.

---

## 3. Verification & Acceptance Criteria
1. Re-evaluate on international and cross-tier matches ($N = 85$ major-vs-lower, $N = 282$ international):
   - Major region win rate prediction shifts from $59.3\% \to \approx 72.0\%$ (matching actual $72.9\%$).
   - Log Loss drops by at least **$-0.035$** (verified target: $0.5637 \to \mathbf{0.5227}$).
   - Brier score drops from $0.1904 \to \mathbf{0.1733}$.
2. Benchmark against bookmaker opening lines on cross-tier fixtures ($N = 36$):
   - Model Log Loss must beat Market OPEN ($< 0.5108$).
3. Integration with benchmark:
   - Must run within `scripts/run_model_benchmark.py --suite` as a versioned candidate without cohort reduction.
