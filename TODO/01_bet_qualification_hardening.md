# TODO 01: Bet Qualification Hardening & Risk Gating

**Priority:** P0 (Immediate Production Impact)  
**Target Files:**
- `betting_app/services/bet_qualification_service.py`
- `betting_app/tests/test_bet_qualification.py`

---

## 1. Problem Statement
Diagnostic audit on 510 scraped matches proved that standalone model EV produces severe overconfidence in three distinct scenarios:
1. **Odds-Multiplier Trap:** On odds $> 3.00$, small probability errors multiply into artificial $> 25\%$ EV, creating volatile longshot drawdowns.
2. **Bo1 Single-Game Variance:** On Best-of-1 matches where the model strongly disagrees with market consensus ($|\Delta p| \ge 0.12$), the model suffers a $-21.5\%$ win rate deficit.
3. **Negative CLV Drift:** When market closing lines drift negatively away from opening lines ($\Delta_{\text{drift}} \le -0.015$), actual win rate drops to $25.0\%$, indicating adverse market information (unannounced substitutes, player illness, scrim leaks).

---

## 2. Specification & Implementation

### Constants to Add:
```python
DEFAULT_MAX_EV_LONGSHOT: float = 0.25
DEFAULT_LONGSHOT_ODDS_THRESHOLD: float = 3.00
DEFAULT_MAX_BO1_MARKET_GAP: float = 0.12
DEFAULT_MAX_NEGATIVE_CLV_DRIFT: float = -0.015
```

### Changes in `is_bet_eligible(...)`:
1. **Rule A (EV Ceiling on Longshots):**
   ```python
   if odds > longshot_odds_threshold and ev_net > max_ev_longshot:
       diag["quarantine"] = True
       diag["quarantine_reason"] = "extreme_ev_longshot_cap"
       return False, "extreme_ev_longshot_cap", diag
   ```
2. **Rule B (Bo1 Market Gap Quarantine):**
   ```python
   if best_of == 1 and prob_market_novig is not None:
       market_gap = abs(prob_model - prob_market_novig)
       if market_gap >= max_bo1_market_gap:
           diag["quarantine"] = True
           diag["quarantine_reason"] = "bo1_extreme_market_divergence"
           return False, "bo1_extreme_market_divergence", diag
   ```
3. **Rule C (Negative CLV Drift Quarantine):**
   ```python
   if prob_market_close_novig is not None and prob_market_open_novig is not None:
       clv_drift = prob_market_close_novig - prob_market_open_novig
       if clv_drift <= max_negative_clv_drift:
           diag["quarantine"] = True
           diag["quarantine_reason"] = "negative_market_drift_clv"
           return False, "negative_market_drift_clv", diag
   ```

---

## 3. Verification & Acceptance Criteria
1. Run pytest suite:
   ```bash
   .venv/bin/python -m pytest -q betting_app/tests/test_bet_qualification.py
   ```
2. Add unit tests covering:
   - Longshot bet (odds $4.50$, EV $0.35$) $\implies$ rejected (`extreme_ev_longshot_cap`).
   - Moderate bet (odds $1.80$, EV $0.30$) $\implies$ accepted (odds $\le 3.00$).
   - Bo1 bet with $|\Delta p| = 0.15 \ge 0.12 \implies$ rejected (`bo1_extreme_market_divergence`).
   - Bo3 bet with $|\Delta p| = 0.15 \implies$ accepted (not Bo1).
   - Bet with negative drift $\Delta_{\text{drift}} = -0.020 \le -0.015 \implies$ rejected (`negative_market_drift_clv`).
3. Empirical performance check on scraped cohort:
   - Max drawdown compressed to $\le 5.0\%$.
   - Net after-tax yield reaches $\ge +30.0\%$.
