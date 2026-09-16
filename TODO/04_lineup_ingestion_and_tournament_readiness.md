# TODO 04: Lineup Ingestion & Tournament Readiness

**Priority:** P2 (Medium Operational & Research Impact)  
**Target Files:**
- `betting_app/scrapers/`
- `src/models/tournament_*.py`
- `scripts/simulate_tournament.py`
- `conf/base/tournament_formats.json`

---

## 1. Problem Statement
Two external structural gaps limit production automation:
1. **Lineup Uncertainty:** Pre-match models currently rely on a `previous_observed_roster` proxy. In high-stakes matches or regional playoffs, last-minute substitutions (e.g. academy subs, illness) cause severe market line shifts against the model.
2. **Tournament Quarantine:** While the tournament engine possesses 91 profiles across 227 phases, **zero phases currently hold verified point-in-time rulebook and draw certification**. Per `AGENTS.md`, match-level Log Loss alone cannot validate multi-round Joint RPS or tournament placement accuracy.

---

## 2. Specification & Implementation

### A. Lineup Ingestion Scraper (30–45 Minutes Prior):
1. Implement a lightweight scraper/listener for official lineup releases:
   - Riot Lolesports official match API / official team Twitter feeds.
   - Run $45$ and $30$ minutes prior to scheduled match start.
2. Update `team_current_roster_players` in the database with verified starters.
3. Trigger instant re-inference if any of the starting five differs from the default `previous_observed_roster`.

### B. Tournament Certification Audit:
1. Audit historical rulebooks and bracket draws in `data/artifacts/leaguepedia-tournament-rules-20260908`.
2. Implement independent point-in-time publication verification:
   - Prove that tournament rules, tiebreak formats, and Swiss draw mechanics were publicly released before the tournament start timestamp.
3. Compute Joint RPS (Ranked Probability Score) for official placements and win counts across complete tournament editions, rather than relying solely on match Log Loss.

---

## 3. Verification & Acceptance Criteria
1. Scraper test:
   - Verify that an announced substitution updates the starting lineup in `canonical_matches` before match start.
   - Prove that re-inference fires and updates the probability before the betting deadline.
2. Tournament certification test:
   - Progressively transition tournament phases from `DIAGNOSTIC` to `CERTIFIED` in `conf/base/tournament_formats.json` as independent rulebook digests are verified.
   - Run `scripts/simulate_tournament.py` on certified editions and verify joint outcome probability conservation ($\sum P = 1.0$).
