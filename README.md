---
type: project-readme
tags: [engineering-thesis, ensemblelegends, repository, python]
project: EnsembleLegends
date: 2026-05-07
---

# EnsembleLegends — repozytorium pracy inżynierskiej

To repozytorium zawiera kod, skrypty eksperymentalne i strukturę roboczą mojej pracy inżynierskiej. Projekt dotyczy predykcji wyników profesjonalnych meczów League of Legends oraz analizy, czy model probabilistyczny połączony z rynkiem kursów bukmacherskich może wskazywać historyczne sytuacje o dodatniej wartości oczekiwanej.

Repozytorium jest traktowane przede wszystkim jako **techniczne zaplecze pracy inżynierskiej**: miejsce na kod źródłowy, pipeline danych, eksperymenty modelowe, symulacje finansowe i narzędzia pomocnicze.

## Zakres projektu

Projekt obejmuje:

- przygotowanie i kontrolę jakości danych meczowych oraz kursowych,
- eksploracyjną analizę danych League of Legends i rynku bukmacherskiego,
- systemy ratingowe graczy i drużyn,
- metamodel sportowy oparty o cechy historyczne,
- model hybrydowy łączący prawdopodobieństwo modelu z prawdopodobieństwem rynku,
- symulacje EV, stakingu, bankrolla i robustness,
- generowanie wyników, wykresów i tabel pomocniczych.

## Struktura repozytorium

| Ścieżka | Rola |
|---|---|
| `src/` | Kod wielokrotnego użytku: moduły danych, ratingów, modeli, metryk, symulacji i wizualizacji. |
| `scripts/` | Numerowane skrypty pipeline'u pogrupowane według rozdziałów/etapów pracy. Szczegóły są w `scripts/README.md`. |
| `artifacts/` | Lokalne artefakty robocze, cache eksperymentów i pliki tymczasowe. |
| `notebooks/` | Notatniki eksploracyjne. |

## Dane

Repozytorium nie zawiera danych wejściowych, ponieważ są zbyt duże na obecny etap wersjonowania. Przed uruchomieniem pipeline'u należy lokalnie utworzyć katalog `data/` i umieścić w nim wymagane pliki.

Minimalny oczekiwany zestaw danych:

```text
data/golgg_matches.json
data/odds.csv
data/oddsportal_matches.csv
data/golgg_y_predicts.csv
data/golgg_stacking_results.csv
```

Na razie dane nie mają publicznego linku pobierania. Katalog `data/` jest ignorowany przez Git.

## Uruchamianie

Projekt powinien być uruchamiany z aktywnego środowiska wirtualnego i z katalogu głównego repozytorium:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\03_dane_pipeline\00_profile_datasets_for_whitepaper.py
```

## Benchmarki diagnostyczne i symulacje bukmacherskie

Repozytorium udostępnia dwa dedykowane narzędzia CLI w katalogu `scripts/` do diagnozowania słabości modeli probabilistycznych, jakości kalibracji w koszykach kursowych oraz oceny wykonywalności strategii bukmacherskich pod 12% polskim podatkiem obrotowym.

### 1. Benchmark kalibracji w koszykach kursowych (`run_odds_bracket_benchmark.py`)

Dzieli przestrzeń kursową na 7 rozłącznych koszyków (od ciężkich faworytów $<1.40$ po wysokie underdogi $>3.50$) i ewaluuje błąd kalibracji ($\text{Model P} - \text{Observed Win Rate}$), Brier Score, LogLoss modelu oraz LogLoss rynku no-vig:

```bash
.venv/bin/python scripts/run_odds_bracket_benchmark.py \
  --data reports/exp039_db_market_backtest_v3_corrected/exp039_market_common.csv \
  --model-col exp039_parity_v2_prob_team_a \
  --target-col y_team_a \
  --market-col market_open_p_a_novig \
  --dataset-name "EXP-039 Parity v2"
```

### 2. Standalone Benchmark Finansowy (`run_financial_benchmark.py`)

Symuluje wykonywalną strategię typowania opartej na czystym kryterium wartości oczekiwanej:
$$\text{EV}_{\text{net}} = p_{\text{model}} \times \text{odds} \times (1 - \tau) - 1.0 \ge 0.05 \quad (\tau = 0.12)$$

Ocenia portfel w 3 przekrojach analitycznych:
1. **Przedział kursowy** (gdzie model generuje zysk, a gdzie traci kapitał),
2. **Wielkość przewagi EV** (umiarkowane $5-8\%$, średnie $8-15\%$, wysokie $>15\%$),
3. **Closing Line Value (CLV)** (czy kurs zagrany bije kurs zamknięcia).

```bash
.venv/bin/python scripts/run_financial_benchmark.py \
  --data reports/exp039_db_market_backtest_v3_corrected/exp039_market_common.csv \
  --candidate-col exp039_parity_v2_prob_team_a \
  --target-col y_team_a \
  --odds-a-col odds_a \
  --odds-b-col odds_b \
  --close-odds-a-col close_odds_a \
  --close-odds-b-col close_odds_b \
  --min-ev 0.05 \
  --tax-rate 0.12 \
  --staking flat_100 \
  --output-md reports/benchmark_model.md
```

### 3. Jak porównywać modele (Czysty model vs Hybryda)

Podczas porównywania modeli (np. czystego metamodelu sportowego z hybrydą rynkową $p_{\text{hybrid}} = \alpha \cdot p_{\text{model}} + (1-\alpha) \cdot p_{\text{market}}$) należy analizować łącznie:

1. **Skuteczność i Yield Netto** (`Yield % = Total Profit / Total Staked * 100`):
   - Czysty model generuje duży wolumen typów (np. 111 zakładów), ale często cierpi na nadmierną wariancję i niski yield (+0.4%).
   - Hybryda filtruje szum rynkowy (20–40 zakładów), stabilizując yield w przedziale +5% do +10%.
2. **Maksymalne obsunięcie kapitału (Max Drawdown)**:
   - Kluczowy wskaźnik ryzyka portfela. Hybryda rynkowa drastycznie redukuje drawdown (np. z 12.1% w czystym modelu do 2.8% w operacyjnej hybrydzie $\alpha=0.35, T=0.80$).
3. **Kalibracja w koszyku wysokich underdogów [3.50 – 5.00]**:
   - Sprawdź `Gap Kalibracji` ($\bar{p}_{\text{model}} - \text{Win Rate}$). Jeśli gap przekracza $+15\%$, model cierpi na overconfidence na underdogach (np. przez zniekształcenia ratingowe "Veteran in Exile").
   - Porównaj stratę nominalną w tym koszyku: czysty model traci w nim często cały zysk wypracowany na faworytach. Hybryda ściąga prawdopodobieństwa do rynku, ograniczając liczbę fałszywych typów.
4. **Wskaźnik CLV (Closing Line Value)**:
   - Średni CLV $> 0\%$ i Beat Close Rate $> 50\%$ dowodzi, że model jest "ostry" (sharp) i bukmacherzy korygują linię w kierunku wskazanym przez model przed startem meczu.

## Uwagi organizacyjne

- Nowy kod wielokrotnego użytku powinien trafiać do `src/`.
- Jednorazowe eksperymenty i generatory artefaktów powinny trafiać do odpowiedniego folderu w `scripts/`.
- Dane powinny pozostawać lokalnie w `data/`, a nie w katalogu głównym projektu.
