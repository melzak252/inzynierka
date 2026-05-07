---
type: scripts-index
tags: [scripts, reproducibility, thesis, project-structure]
project: EnsembleLegends
date: 2026-05-07
---

# Indeks skryptów

> [!abstract]
> Katalog `scripts/` jest pogrupowany według numerowanych rozdziałów pracy. Numer folderu odpowiada głównemu etapowi analizy: od przygotowania danych, przez EDA i modele, po symulacje finansowe, robustness oraz generowanie wizualizacji raportowych.

## Zasada uruchamiania

Skrypty należy uruchamiać z katalogu głównego projektu, po aktywowaniu środowiska wirtualnego:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\03_dane_pipeline\00_profile_datasets_for_whitepaper.py
```

> [!note]
> Część skryptów wykorzystuje lokalne pliki danych z katalogu `data/`, np. `data/golgg_matches.json`, `data/odds.csv`, `data/golgg_y_predicts.csv` oraz `data/golgg_stacking_results.csv`. Katalog `data/` nie jest wersjonowany, dlatego trzeba go uzupełnić lokalnie przed uruchomieniem pipeline'u.

---

## Numeracja rozdziałów skryptowych

| Folder | Odpowiedni etap / rozdział | Rola |
|---|---|---|
| `03_dane_pipeline/` | Dane, mapowanie i jakość datasetów | Profilowanie danych, mapowanie GOL.GG ↔ OddsPortal, sanity checks. |
| `04_eda_rynek/` | EDA gry i rynku | Analiza rozkładu meczów, formatów BoN, rynku opening/closing, marż, arbitrażu i cech esportowych. |
| `05_ratingi_baseline/` | Ratingi i baseline'y | Generowanie ratingów, burn-in, porównanie player/team ratings, Market Open/Close i strojenie TrueSkill/OpenSkill. |
| `06_metamodel/` | Metamodel sportowy | Trening, diagnostyka, ablation studies, Optuna/walk-forward i wykresy metamodelu. |
| `07_model_hybrydowy/` | Hybryda model + rynek | Alpha sweep, temperature scaling, dynamic alpha, odds shopping i diagnostyki hybrydy. |
| `08_symulacje_finansowe/` | EV, staking i bankroll | Kelly, fixed stake, symulacje bankrolla, yield, ROI i wykresy finansowe. |
| `09_robustness_walidacja/` | Robustness i walidacja | Stress testy, CLV, segmentacja zysku, bootstrap i stabilność wyników. |
| `10_wizualizacje_raportowe/` | Materiały końcowe | Statyczne i prezentacyjne wizualizacje generowane z wyników eksperymentów. |

---

## Kolejność odtwarzania pipeline'u

Minimalna kolejność odtwarzania wyników wygląda następująco:

1. `03_dane_pipeline/` — przygotowanie i profil danych.
2. `04_eda_rynek/` — opis gry, rynku i jakości cen.
3. `05_ratingi_baseline/` — ratingi i baseline'y.
4. `06_metamodel/` — finalny model sportowy.
5. `07_model_hybrydowy/` — połączenie modelu z rynkiem.
6. `08_symulacje_finansowe/` — przejście od prawdopodobieństwa do decyzji bettingowej.
7. `09_robustness_walidacja/` — stress testy i sanity checks.
8. `10_wizualizacje_raportowe/` — figury końcowe do dokumentów.

> [!check]
> Taki układ utrzymuje zgodność między kodem a kolejnością etapów pracy: czytelnik może przejść od etapu pipeline'u do odpowiadającego mu folderu skryptów.
