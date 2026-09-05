---
type: future-idea
id: IDEA-019
category: betting-strategy
status: completed
created: 2026-09-05
updated: 2026-09-05
tags: [planning, parlays, ako, tax-amortization, favorite-combos, financial-optimization, portfolio]
---

# IDEA-019 - Tax-amortized two-leg favorite parlay recommender (Safe Dubel)

- **Status:** completed
- **Created:** 2026-09-05
- **Updated:** 2026-09-05
- **Delivered:** `betting_app/services/parlay_service.py`, `betting_app/api/routers/matches.py`, `client/src/pages/MatchList.tsx`, `betting_app/tests/test_parlay_recommendations.py`

## Problem

In the Polish regulated sports betting environment, bookmakers are legally obligated to deduct a **12% turnover tax on stakes** upfront (`effective_payout = stake * 0.88 * odds`).
For single bets on favorites (odds $1.35 - 2.10$), this tax creates a severe friction hurdle:
- A single bet requires a pre-tax gross model edge of at least $+13.64\%$ ($\frac{1}{0.88} - 1$) simply to break even ($EV = 0$).
- When placing two separate single bets, the 12% tax is paid twice (once on each stake), reducing compound bankroll efficiency.
- In historical backtests on 201 verified opening lines (`reports/exp039_db_market_backtest_v3_corrected/roi_benchmark_ev5/ledger_open_poland_tax_12.csv`), single bets on favorites ($\le 2.20$) achieved an outstanding empirical hit rate of **73.9%**, but net ROI was throttled to **+11.01%** due to tax friction.

## Opportunity: Accumulator (AKO) Tax Amortization

In a parlay (kupon akumulowany / AKO), the 12% tax is deducted **only once from the initial coupon stake**, and odds multiply across legs without intermediate tax deductions:
$$\text{Payout} = \text{Stake} \times 0.88 \times (\text{Odds}_1 \times \text{Odds}_2)$$

This structure dramatically reduces the required pre-tax gross edge per leg:
- **Single (1 leg):** required edge $\ge +13.64\%$
- **Double (2 legs):** required edge $\ge +6.60\%$ per match ($\sqrt{\frac{1}{0.88}} - 1$)
- **Treble (3 legs):** required edge $\ge +4.35\%$ per match

When two high-confidence, positive-EV favorite selections are combined into a 2-leg parlay, the compound return grows faster than the tax drag, unlocking substantially higher capital efficiency.

## Empirical Evidence from Historical Ledger Backtest

Tested on 201 chronological opening-line bets from `exp039_db_market_backtest_v3_corrected` with 12% tax:

| Strategy | Coupons | Win Rate | Avg Odds | Total Staked | Net Profit (after 12% tax) | **ROI (%)** | Max Drawdown | Max Loss Streak |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Single Bets (All)** | 201 | 44.8% | 4.14 | 2,010 PLN | +75.51 PLN | **+3.76%** | -259.85 PLN | 11 |
| **Single Favorites ($\le 2.20$)** | 69 | 73.9% | 1.73 | 690 PLN | +75.95 PLN | **+11.01%** | -60.00 PLN | 4 |
| **2-Leg Parlay: Favorites ($\le 2.20$)** | **34** | **52.9%** | **3.01** | **340 PLN** | **+122.29 PLN** | **+35.97%** | **-30.00 PLN** | **3** |
| **2-Leg Parlay: Same-Day Top-2 EV** | 50 | 16.0% | 26.43 | 500 PLN | +250.86 PLN | **+50.17%** | -188.04 PLN | 12 |
| **2-Leg Parlay: Consecutive All** | 100 | 24.0% | 19.17 | 1,000 PLN | +277.58 PLN | **+27.76%** | -271.51 PLN | 10 |
| **2-Leg Parlay: Underdogs ($> 2.20$)** | 66 | 10.6% | 29.81 | 660 PLN | +89.68 PLN | **+13.59%** | -160.00 PLN | 14 |

### Critical Findings:
1. **Favorite Duble ROI Surge:** Pairing favorites ($\le 2.20$) increased net ROI from **+11.01% to +35.97%** while doubling total net profit (+122.29 PLN vs +75.95 PLN) on **half the capital risked** (340 PLN vs 690 PLN).
2. **Minimal Drawdown:** 2-leg favorite parlays experienced a maximum drawdown of only **-30.00 PLN** (3 bets) with a **52.9%** hit rate, making the strategy psychologically executable.
3. **Underdog Parlay Hazard:** Pairing underdogs or unconditional top-EV picks created unacceptable variance (84% loss rate, avg odds 26.43, 12 consecutive losses, max drawdown -188 PLN). Parlays must be strictly bounded to high-probability favorites.

## Non-goals and Safety Boundaries

- **Never automate bet placement:** Preserve the research-only application boundary.
- **Never recommend 3+ leg parlays ("taśmy"):** Multi-leg parlays exponentially compound model estimation errors and correlation hazards. Strictly limit to 2 legs (duble).
- **Never include underdogs in parlays:** Selections must satisfy `entry_odds <= 2.20` and `model_probability >= 0.55`.
- **Same-bookmaker constraint:** Both selections must be available at the same bookmaker to be placeable on a single accumulator slip.
- **Schedule independence:** Exclude selections from the same series or interdependent group-stage matches to prevent correlation leakage.

## Implementation Outline

1. **Parlay Pairing Engine (`betting_app/services/parlay_service.py`):**
   - Find all active upcoming matches with $EV_{\text{single}} > 0$.
   - Filter candidates: `odds <= 2.20`, `model_probability >= 0.55`, same bookmaker availability.
   - Pair candidate selections occurring on the same day or weekend gameweek.
   - Calculate joint probability $P(A \cap B) = P(A) \times P(B)$, combined odds $O_{\text{comb}} = O_1 \times O_2$, combined $EV$:
     $$EV_{\text{parlay}} = P(A) \cdot P(B) \cdot (O_1 \cdot O_2) \cdot 0.88 - 1$$
   - Rank parlays by expected value and reliability score.

2. **API Endpoint (`betting_app/api/routers/matches.py`):**
   - Expose `GET /matches/recommendations/parlays` returning qualified 2-leg combinations with combined odds, bookmaker, joint EV, and suggested quarter-Kelly stake.

3. **Frontend Integration (`client/src/pages/MatchList.tsx`):**
   - Add a dedicated banner / card: *"Rekomendowany Dubel Dnia (Safe Parlay)"* displaying the two legs, bookmaker, combined odds (e.g. 2.95), and tax-amortized EV boost.

## Acceptance Criteria

- [ ] Same-bookmaker constraint is strictly enforced (legs cannot be from different sportsbooks).
- [ ] Legs are guaranteed temporally non-overlapping or mutually independent.
- [ ] Max odds per leg $\le 2.20$, joint odds between $2.00$ and $3.80$.
- [ ] Joint EV calculation explicitly includes the 12% Polish turnover tax.
- [ ] Unit tests verify independence assumptions, odds compounding, and Kelly fraction scaling.

## References

- `reports/exp039_db_market_backtest_v3_corrected/roi_benchmark_ev5/ledger_open_poland_tax_12.csv`
- `docs/future_ideas.md` (IDEA-016, IDEA-018)
