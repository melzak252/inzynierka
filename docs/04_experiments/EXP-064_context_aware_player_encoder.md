# EXP-064 — Context-aware PlayerGameEncoder

> [!abstract]
> Testowano encoder gracz+champion+team-context, czyli wariant, w którym embeddingi kontekstu trafiają do modelu na poziomie player-game, a nie jako płaskie średnie/diffy w regresji. Wynik jest mieszany: context-aware encoder poprawia ranking i accuracy względem plain encoder, szczególnie w późniejszych foldach, ale po kalibracji ma gorszy pełny LogLoss. Nie wdrażamy jako model probability, ale traktujemy jako obiecujący kierunek do residual/ranking/market-aware dalszych testów.

## Metadata
- **Experiment ID**: EXP-064
- **Date**: 2026-07-30
- **Tags**: #player-game-encoder #embeddings #team-context #champion-context #walk-forward
- **Script**: `betting_app/scripts/evaluate_context_aware_player_encoder.py`
- **Report**: `reports/exp064_context_aware_player_encoder/summary.json`
- **Commit**: `e1fe45b Add EXP-064 context-aware player encoder evaluation`

## Objective
Sprawdzić, czy kontekst embeddingowy o formie gracza/championa/drużyny działa lepiej, jeśli trafi do encoder-a player-game, zamiast zastępować W20 jako płaskie cechy LR.

## Setup
- Dane player-game: `57500` rows, `2708` matches, `5750` games, `2041` players, zakres `2026-01-08T00:00:00` → `2026-07-29T00:00:00`.
- Context coverage: `{'champion_role': 0.9972, 'opponent_team': 0.8146086956521739, 'own_team': 0.8146086956521739, 'snapshot': 1.0}`.
- Match dataset: plain `1338` rows, context `1338` rows; embedding dim `64`; skipped by min-prior-player-games `{'min_prior_player_games': 1350}`.
- Encoder: epochs `8`, batch `2048`, latent dim `64`, device `auto`.
- OOF match model: initial train `120`, test size `60`, step `60`.

## Encoder training tail
| Encoder | train loss | train match acc | val loss | val match acc |
|---|---:|---:|---:|---:|
| plain | 0.705702 | 0.659130 | 0.783085 | 0.570667 |
| context-aware | 0.724506 | 0.702138 | 0.898024 | 0.563826 |

## Match OOF results
| Encoder | N | LogLoss cal | Brier cal | AUC | Accuracy | LogLoss raw |
|---|---:|---:|---:|---:|---:|---:|
| plain | 1218 | 0.604635 | 0.208030 | 0.734102 | 0.674877 | 0.607219 |
| context-aware | 1218 | 0.606717 | 0.207190 | 0.742046 | 0.690476 | 0.610428 |

Recent fold aggregates:
| Slice | Encoder | N | weighted LogLoss raw | weighted AUC | weighted Accuracy |
|---|---|---:|---:|---:|---:|
| last 10 folds | plain | 558 | 0.591082 | 0.759143 | 0.693548 |
| last 10 folds | context-aware | 558 | 0.580811 | 0.787197 | 0.720430 |
| last 5 folds | plain | 258 | 0.643934 | 0.698563 | 0.643411 |
| last 5 folds | context-aware | 258 | 0.629408 | 0.767279 | 0.713178 |

## Analysis
- Context-aware encoder zwiększył AUC z `0.7341` do `0.7420` i accuracy z `0.6749` do `0.6905`, więc dodany kontekst ma sygnał rankingowy.
- Pełny skalibrowany LogLoss pogorszył się z `0.6046` do `0.6067`; raw LogLoss też jest gorszy (`0.6104` vs `0.6072`). To oznacza, że model jest mniej stabilny jako probability model.
- W późniejszych foldach context-aware wygląda lepiej: last10 raw weighted LogLoss `0.5808` vs `0.5911`, AUC `0.7872` vs `0.7591`, accuracy `0.7204` vs `0.6935`. Sygnał pojawia się szczególnie po zwiększeniu train history.
- Encoder context ma wyższy train match accuracy (`0.7021` vs `0.6591`), ale gorszą walidację (`0.5638` vs `0.5707`) i wyższy val loss, więc jest ryzyko overfittingu / złej kalibracji.
- Pokrycie contextu jest dużo lepsze niż w smoke: champion-role `99.7%`, team context `81.5%`, ale dalej brakujące team embeddingi mogą destabilizować wynik.

## Conclusion
> [!check]
> EXP-064 potwierdza, że kontekst embeddingowy ma sygnał, jeśli trafia do encoder-a player-game. Nie jest jednak gotowy do produkcji jako samodzielny probability model, bo pełny LogLoss jest słabszy od plain encoder.

## Next steps
1. Potraktować context-aware encoder jako generator ranking/residual features, nie jako bezpośredni probability model.
2. Następny eksperyment: połączyć context-aware embeddingi z EXP-039/market jako residual, z mocną kalibracją i shrinkiem do rynku.
3. Zmniejszyć overfitting encoder-a: dropout/weight decay/early stopping albo mniejszy latent/context projection.
