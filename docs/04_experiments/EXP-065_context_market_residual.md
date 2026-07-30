# EXP-065 — Context-aware encoder jako residual do rynku/EXP-039

> [!abstract]
> Po EXP-064 sprawdzono, czy context-aware player encoder dodaje wartość jako residual/blend względem rynku, EXP-039 albo starego hybridu. Wniosek: względem rynku nie dodaje — najlepsza waga modelu to `0.0`. Jest bardzo mały dodatni sygnał względem pure EXP-039: `10% context + 90% EXP-039` poprawia LogLoss z `0.54256` do `0.54174` na N=99, ale to za mało i za mały sample do wdrożenia.

## Metadata
- **Experiment ID**: EXP-065
- **Date**: 2026-07-30
- **Input**: EXP-064 OOF predictions from `reports/exp064_context_aware_player_encoder/oof/`.
- **Report**: `reports/exp065_context_market_residual/sweep.json`
- **Method**: grid sweep `p = alpha * p_context_or_plain + (1-alpha) * p_reference`, alpha in `[0, 1]` step `0.02`.

## Context-aware residual results
| Reference | N | Reference LL | Model LL | Best alpha model | Best LL | Best AUC | Best Acc |
|---|---:|---:|---:|---:|---:|---:|---:|
| market no-vig | 97 | 0.491271 | 0.580626 | 0.00 | 0.491271 | 0.834077 | 0.721649 |
| EXP-039 | 99 | 0.542562 | 0.584419 | 0.10 | 0.541744 | 0.785043 | 0.696970 |
| Hybrid a0.50 | 95 | 0.495614 | 0.581562 | 0.00 | 0.495614 | 0.841182 | 0.778947 |

## Plain encoder residual sanity check
| Reference | N | Reference LL | Model LL | Best alpha model | Best LL |
|---|---:|---:|---:|---:|---:|
| market no-vig | 97 | 0.491271 | 0.602937 | 0.00 | 0.491271 |
| EXP-039 | 99 | 0.542562 | 0.609782 | 0.00 | 0.542562 |
| Hybrid a0.50 | 95 | 0.495614 | 0.601431 | 0.00 | 0.495614 |

## Analysis
- Market no-vig is much stronger than EXP-064 context OOF on mapped subset: market LL `0.49127`, context LL `0.58063`; best blend keeps alpha_model `0.0`.
- Old hybrid a0.50 also beats context on the available historical subset: LL `0.49561`; best blend again alpha_model `0.0`.
- Against pure EXP-039 there is a tiny residual: context alpha `0.10` improves LL from `0.54256` to `0.54174`, and AUC from `0.78248` to `0.78504`. This is promising directionally but not robust enough for production.
- Plain encoder never improves the references; the residual signal comes specifically from context-aware training, but is very weak.

## Conclusion
> [!check]
> Nie wdrażamy EXP-064/065 do produkcji. Context-aware encoder ma mały ranking/residual signal, ale bookmaker market nadal dominuje, a przewaga względem EXP-039 jest marginalna na małym N.

## Next steps
1. Jeśli kontynuować embeddingi: poprawić encoder/calibration, nie blendować go bezpośrednio z marketem.
2. Skupić się na lepszym EXP-039/retrained + alpha do rynku, bo to daje aktualnie największy zwrot praktyczny.
3. Potencjalny kolejny eksperyment: wykorzystać context-aware encoder tylko jako dodatkową cechę w EXP-039 weekly retrain, z silnym L1/ElasticNet i walk-forward OOF.
