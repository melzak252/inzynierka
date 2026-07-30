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

## Roadmap after champion-role embeddings

### EXP-057 — Team/opponent statistical embeddings

Build leakage-safe walk-forward team embeddings.  For a team at reference date `T`, use only games with `date < T` and summarise:

- recent form: win rate, side profile, game duration, team kills/gold/objectives when available;
- style: kill pace, gold pace, early-game diffs, vision/ward profile aggregated from players;
- opponent-adjusted proxies: gold diff, kill diff, relative performance against recent opponents;
- roster/player composition proxies: distinct players, role coverage, champion pool size;
- recency: 90/180/365 day fallback, then all-history exponential decay.

The artifact is intentionally statistical/interpretable first.  It becomes both a match-level feature source and context for the next PlayerGameEncoder.

### EXP-058 — Champion + team context dataset

Join every player-game row with:

```text
champion-role embedding at T
own-team embedding at T
opponent-team embedding at T
role/side/patch/league metadata
raw player stats
```

This step is primarily a data/coverage/leakage audit before neural training.

### EXP-059 — ContextAwarePlayerGameEncoder

Train a small neural encoder that consumes player stats plus champion/team/opponent context and emits a player-game latent vector.  Candidate objectives:

- supervised win/loss and match outcome heads;
- auxiliary role-specific targets such as gold diff @15, damage share, KP, deaths/min;
- denoising/reconstruction of stat profile;
- later contrastive objectives for similar performances in similar context.

### EXP-060 — Contextual match model

Aggregate context-aware player-game embeddings into team/match features, then compare against:

- bookmaker no-vig market;
- EXP-039 symmetric calibrated LR;
- current market-shrink hybrid;
- EXP-054/055 embedding baselines.

Deployment rule remains conservative: if learned signal does not beat market reliably, use it only as a small residual correction to market probability.
