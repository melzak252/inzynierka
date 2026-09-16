# Implementation Roadmap & TODOs

**Updated:** 2026-09-16  
**Context:** Resulting from the comprehensive benchmark and diagnostic audit (`reports/production_readiness_and_market_benchmark_report_2026.md`).

---

## Action Items Overview

| Action Item | Target Subsystem | Priority | Expected Impact | Status |
|---|---|:---:|---|:---:|
| [01. Bet Qualification Hardening](./01_bet_qualification_hardening.md) | `betting_app/services/bet_qualification_service.py` | **P0 (Immediate)** | Reduces max drawdown from $14.0\% \to 4.91\%$, boosts after-tax yield to $+32.35\%$ | **COMPLETED & VERIFIED** |
| [02. Regional Family Rating Engine](./02_regional_family_ratings.md) | `src/ratings/family_calibrated_glicko2.py` | **P1 (High)** | Fixes $-13.7\%$ regional deficit, drops cross-regional Log Loss by $-0.0409$ | **COMPLETED & VERIFIED** |
| [03. Live Operational Pipeline Cutover](./03_operational_pipeline_cutover.md) | `betting_app/core/models/registry.py` | **P1 (High)** | Upgrades active inference from EXP-081 to Shrunk Hybrid ($\alpha = 0.50$) | **COMPLETED & VERIFIED** |
| [04. Lineup Ingestion & Tournament Readiness](./04_lineup_ingestion_and_tournament_readiness.md) | `betting_app/scrapers/`, `src/models/tournament_*.py` | **P2 (Medium)** | 30-min confirmed lineups; point-in-time tournament certification | **COMPLETED & VERIFIED** |
## Execution Order

1. **Step 1:** Implement **Action 01** in `bet_qualification_service.py` and verify via `test_bet_qualification.py`. This immediately protects betting bankroll with zero training risk.
2. **Step 2:** Implement **Action 03** in model registry to cut over live upcoming predictions from EXP-081 to the Shrunk Hybrid.
3. **Step 3:** Implement **Action 02** for the research rating engine to incorporate competition family scaling ($\gamma = 0.70$) into the canonical benchmark.
4. **Step 4:** Implement **Action 04** to automate pre-match confirmed lineup ingestion and audit tournament rulebooks.
