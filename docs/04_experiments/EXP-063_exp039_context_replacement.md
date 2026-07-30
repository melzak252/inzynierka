# EXP-063 — EXP-039 z embeddingowym kontekstem zamiast W20

> [!abstract]
> Celem było sprawdzenie, czy model podobny do EXP-039, ale używający leakage-safe embeddingów kontekstu drużyny/champion-pool zamiast prostych średnich W20, poprawia wynik predykcji. Wynik: nie poprawia; najlepszy na tym samym OOF okazał się wariant rating+binomial bez W20, a embedding-context był słabszy w LogLoss i AUC.

## Metadata
- **Experiment ID**: EXP-063
- **Date**: 2026-07-30
- **Tags**: #exp039 #embeddings #team-context #champion-pool #walk-forward
- **Report**: `reports/exp063_context_replacement/summary.json`
- **Script**: `betting_app/scripts/evaluate_exp039_context_replacement.py`
- **Reproducibility**: Logistic regression random seed 42; chronological walk-forward; context snapshots constrained by `reference_date <= match_date`.

## Objective
Sprawdzić wariant podobny do `Sym-Cal LR-ElasticNet-W20-Binomial/exp-039`, ale zastępujący ręczne średnie `t1_rolling_*`/`t2_rolling_*` embeddingowym opisem formy graczy i drużyny.

## Setup
- Dataset bazowy EXP-039 DB: `30970` rows; po filtrze snapshotów kontekstu: `2688` rows od `2026-01-08 00:00:00` do `2026-07-29 00:00:00`.
- OOF cutoff: `2026-03-01`; update interval: `500`.
- Team context dim: `52`; champion-pool dim: `48`.
- Coverage: `{'team1_champion_pool': 0.7790178571428571, 'team1_team': 0.7797619047619048, 'team2_champion_pool': 0.7760416666666666, 'team2_team': 0.7779017857142857}`.

Porównane modele:
- `exp039_w20`: pełne 46 cech EXP-039.
- `ratings_binomial`: tylko rating probabilities + binomial series, bez W20.
- `ratings_context`: rating probabilities + binomial series + team/champion embedding context.

## Results
| Model | Features | OOF N | LogLoss | Brier | AUC | Accuracy |
|---|---:|---:|---:|---:|---:|---:|
| `exp039_w20` | 46 | 1905 | 0.553173 | 0.186959 | 0.789310 | 0.713386 |
| `ratings_binomial` | 26 | 1905 | 0.551893 | 0.186355 | 0.790500 | 0.711811 |
| `ratings_context` | 230 | 1905 | 0.556183 | 0.187941 | 0.787185 | 0.710236 |

Market-common mapped subset:
| Model | N | LogLoss | Brier | AUC | Accuracy |
|---|---:|---:|---:|---:|---:|
| `exp039_w20` | 412 | 0.591055 | 0.202221 | 0.754948 | 0.674757 |
| `ratings_binomial` | 412 | 0.586202 | 0.200378 | 0.758157 | 0.674757 |
| `ratings_context` | 412 | 0.590457 | 0.201902 | 0.754901 | 0.674757 |

## Analysis
- `ratings_context` nie przebił prostszego baseline’u. Pełny OOF: LogLoss `0.55618`, AUC `0.78719`; pełny EXP-039 W20: LogLoss `0.55317`, AUC `0.78931`; rating+binomial: LogLoss `0.55189`, AUC `0.79050`.
- Na subsetcie z mapowaniem do canonical/market różnice są podobne: context LogLoss `0.59046`, W20 `0.59106`, rating+binomial `0.58620`. Context minimalnie poprawia względem W20 w LogLoss na tym subsetcie, ale nadal przegrywa z prostszym rating+binomial.
- Pokrycie embeddingów dla team/champion-pool jest tylko około 77–78%, więc część sygnału jest imputowana/missing. To ogranicza korzyść z embeddingów.
- Wniosek metodologiczny: obecne statystyczne embeddingi team/champion-pool nie są jeszcze lepszym zamiennikiem W20. Sam “kontekst embeddingowy” jako płaski diff/absdiff w LR nie wystarcza.

## Conclusion & next steps
> [!check]
> EXP-063 został uruchomiony i nie kwalifikuje się do produkcji jako zamiennik EXP-039/W20.

Następny sensowny krok: nie wrzucać tych embeddingów jako płaskich średnich do LR, tylko trenować encoder gracz+champion+team-context na poziomie gry lub roli, a potem oceniać go jako residual do rynku/hybridu.
