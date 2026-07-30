# Champion/team/player embedding plan

> [!abstract]
> This note records the modelling direction after EXP-054/EXP-055: improve the semantic input embeddings before training larger sequence models. The next implementation focus is a **champion-role embedding pipeline** that represents current meta strength from recent GOL.GG games with principled fallback to older history.

## Motivation

Recent experiments showed that learned player-game embeddings contain signal, but the current representation is too context-poor:

- player performances are not sufficiently adjusted for **opponent strength**;
- champion identity is treated as a sparse/category field, not as a current-meta object;
- transformer aggregation over weak player-game embeddings underperformed market and simpler baselines;
- bookmaker market remains the strongest live baseline, so model signal should become a residual/context correction rather than a direct market replacement.

## Target architecture

```text
GOL.GG player/game rows
        |
        +--> champion-role embedding pipeline
        |
        +--> team/opponent embedding pipeline
        |
        +--> context-aware PlayerGameEncoder
                   |
                   v
          roster/team history aggregator
                   |
                   v
             match-level model
                   |
                   v
        market probability + model correction
```

## Champion embeddings

Champion embeddings should encode how a champion behaves **in a role and current meta**, not just champion ID.

Per `champion_id + role`, compute recent/context features such as:

- game count and recency span;
- win rate, side-adjusted win rate;
- KDA, CS/min, gold/min, damage/min, damage share, kill participation;
- vision/control-ward profile where relevant;
- team-level context: team kills/gold/objectives and opponent kills/gold/objectives;
- opponent-adjusted proxies: gold diff, kill diff, team strength/opponent strength when available;
- patch/league/time metadata.

### Recency and fallback rule

For a reference date `T`:

1. Use games in the last **90 days** if there are at least `min_recent_games` examples.
2. Otherwise extend to **180 days**.
3. Otherwise extend to **365 days**.
4. Otherwise use all historical games before `T` with exponential time decay.
5. If still too sparse, fall back to role-level/global default embedding.

This keeps the embedding focused on current meta while avoiding missing vectors for rare champions.

## Team/opponent embeddings

Team embeddings should be used both:

1. as context inside PlayerGameEncoder;
2. as match-level features.

They should represent recent form, roster, region/league, opponent-adjusted results, W20/rating features, and stylistic tendencies. Player stat lines should always be interpreted with `own_team_embedding` and `opponent_team_embedding`, so a good game against T1/GEN/BLG is not equivalent to the same stat line against a weak league opponent.

## Player-game embeddings

A future context-aware PlayerGameEncoder should consume:

```text
player stats
+ role/side/patch/league
+ champion-role embedding
+ own team embedding
+ opponent team embedding
+ match/game result context
```

The goal is to learn opponent-adjusted, champion-aware player form.

## Pre-match vs post-draft

Pre-match model usually does not know the draft. It should use:

- champion pool embeddings;
- comfort/meta-fit summaries;
- player/team style and recent form.

Post-draft/live-draft model can additionally use:

- exact picked champions;
- champion matchup/team-composition embeddings;
- player champion comfort on selected picks.

## Immediate experiment

**EXP-056 — Champion-role embeddings**

1. Build a leakage-safe champion-role embedding table from GOL.GG completed games.
2. Use 90/180/365/all-history fallback by reference date.
3. Save vectors + metadata as reusable artifacts.
4. Evaluate quality with descriptive diagnostics first: coverage, sparse champions, role defaults, recent-vs-fallback distribution.
5. Next: plug champion embeddings into PlayerGameEncoder and compare against EXP-054/055.
