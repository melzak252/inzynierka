---
type: scripts-index
tags: [scripts, reproducibility, thesis, project-structure]
project: EnsembleLegends
date: 2026-05-07
---

# Indeks skryptów

> [!abstract]
> Katalog `scripts/` jest pogrupowany według numerowanych rozdziałów pracy. Numer folderu odpowiada głównemu etapowi analizy: od przygotowania danych, przez EDA i modele, po symulacje finansowe, robustness oraz generowanie wizualizacji raportowych.

## Aktualny punkt wejścia do badań

**`run_model_benchmark.py --suite conf/base/research_benchmark.json`** (ścieżka manifestu z katalogu głównego: `conf/base/research_benchmark.json`). Uruchamiaj z głównego katalogu repo według [instrukcji badań](../docs/RESEARCH.md).

- `--doctor`: sprawdzenie źródeł i hashy, bez liczenia i treningu.
- `--suite ... --output-dir data/08_reporting/benchmark/<nowy-run>`: wspólne metryki A0, ratingów,039 i OPEN z pokryciem.
- `--candidate-data ... --candidate-col p`: dołączenie kompletnego kandydata do tej samej próby.
- Dawny tryb `--data ... --candidate-col ...` pozostaje kompatybilnym narzędziem pojedynczej kolumny; jego automatyczne bramki nie zastępują pełnego dopuszczenia produkcyjnego.

Poniższa numeracja opisuje historyczne narzędzia i wyspecjalizowane potoki, nie kilka konkurujących standardów benchmarku. Nowe eksperymenty powinny eksportować prognozy do jednego benchmarku.

## Aplikacja — natywne C0 i kolektory

Kod aplikacji używa `C0_NATIVE` (`Causal-C0`,
`c0-native-2026-w32-e12-v1`) oraz osobno zidentyfikowanej hybrydy rynkowej C0.
Konfiguracja natywnej inferencji: `conf/base/c0_serving.json`.
Model jest zamrożonym artefaktem historycznym, nie nową certyfikacją prognoz
przyszłych, turniejów lub rentowności. Dawne selektory operacyjnego EXP081/A1
nie są zamiennikami C0.

Wagi, surowa historia i zewnętrzne archiwum badawcze nie są częścią tego commitu.
Przed uruchomieniem trzeba dostarczyć zasoby wskazane przez konfigurację,
z zachowaniem hashy. Archiwum rozwiązuje istniejący `ENSEMBLE_RESEARCH_ROOT`
lub lokalny `data/research_root.txt`; brak zasobów nie uruchamia pobierania
ani zastępczego modelu. Publikacja kodu nie jest wdrożeniem na serwer.

`betting_app/scripts/backfill_operational_predictions.py` pozostaje odtworzeniem
historycznej regionalnej receptury 70% player ratings / 20% team ratings / 10% W20,
z pojedynczą projekcją BO. Nie korzysta z aktywnego C0 i nie zapisuje wyników
pod jego identyfikatorem.

### Ograniczanie żądań Liquipedia

- `GET /api/tournaments/{id}`, `/simulate` i `/recalculate` korzystają wyłącznie
  z lokalnej drabinki oraz modelu C0. Brak lub wygaśnięcie cache nie uruchamia
  pobierania źródła. Przeliczana jest żądana liczba symulacji, nie cztery głębokości.
- Pobieranie drabinki wymaga jawnego `/sync`; domyślne `force=false` zachowuje
  cache. `force=true` nie omija budżetu żądań Liquipedia. Import wikitext/HTML
  pozostaje offline także przy pustym lub błędnym wejściu. Udana synchronizacja
  unieważnia poprzednią symulację, a nieudana zachowuje oryginalny czas snapshotu.
- `betting_app/services/liquipedia_transport.py` jest wspólnym transportem
  klienta meczów/składów i drabinek. Cache domyślnie znajduje się w
  `data/cache/liquipedia`; `LIQUIPEDIA_CACHE_DIR` pozwala wskazać wspólny katalog.
  API i scheduler muszą współdzielić ten trwały katalog. Budżet nie jest
  globalny między maszynami z osobnymi katalogami.
- Poprawne odpowiedzi klienta są przechowywane przez 6 godzin, a żądania
  drabinki przez 30 minut. Blokada per host zapobiega równoległemu pobraniu
  tego samego zapytania między procesami. Minimalne odstępy wynoszą 2 sekundy
  dla żądań i 30 sekund dla `parse`/`expandtemplates`.
- HTTP 403 wstrzymuje nowe żądania do hosta na 24 godziny. HTTP 429 wstrzymuje
  je na co najmniej godzinę lub dłuższy poprawny `Retry-After`. Błędy zapytania
  są zapamiętywane przez 5 minut; odpowiedzi API `ratelimited`/`maxlag` również
  wstrzymują host. Uszkodzony stan blokuje pobieranie zamiast zerować budżet.
- Zwykli klienci nie czekają na odstęp ani nie ponawiają błędu. Jawne CLI i API
  weryfikacji składów czekają na odstęp do 30 sekund dla kolejnego nowego zapytania,
  lecz nie na cooldown; większa partia może więc potrwać wiele minut. Wyszukiwanie
  alternatywnego tytułu następuje tylko po błędzie brakującej strony, nie po
  timeout, 403, 429 ani ogólnym błędzie API.
- Dzienny job 05:00 aktualizuje tylko ticker/BO. Osobny job 05:15 weryfikuje
  składy raz, z limitem 50 unikalnych zespołów i timeoutem 7200 sekund.
  Jawne listy zespołów są przycinane i deduplikowane. Interfejs turniejów nie
  ponawia automatycznie nieudanego ENC; ponowienie wymaga działania użytkownika.

Bezpieczne sprawdzenie interfejsów CLI z katalogu głównego, bez pobierania:

```bash
.venv/bin/python -m betting_app.scripts.sync_liquipedia_bon --help
.venv/bin/python -m betting_app.scripts.verify_and_sync_team_rosters --help
```

To konserwatywna polityka lokalna, nie dowód uprawnień do źródła ani gwarancja
braku blokady po stronie Liquipedia. Rzeczywiste uruchomienie zbierania wymaga
osobnej autoryzacji; nie należy usuwać cache/cooldown w celu wymuszenia żądań.

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

---

## Narzędzia benchmarkowe (w katalogu głównym `scripts/`)

W katalogu `scripts/` znajdują się bezpośrednie CLI do diagnostyki i ewaluacji modeli:

1. **`scripts/run_odds_bracket_benchmark.py`**:
   - Dzieli przestrzeń na 7 koszyków kursowych (od ciężkich faworytów $<1.40$ po wysokie underdogi $>3.50$).
   - Mierzy błąd kalibracji, Brier score, LogLoss modelu vs rynkowy LogLoss no-vig oraz identyfikuje koszyki z overconfidence.

2. **`scripts/run_financial_benchmark.py`**:
   - Kompleksowy benchmark finansowy symulujący zakłady o $\text{EV}_{\text{net}} \ge 5\%$ z uwzględnieniem 12% polskiego podatku obrotowego.
   - Segmentuje wyniki według przedziałów kursowych, poziomów EV oraz wskaźnika CLV (Closing Line Value).
   - Szczegółowe przykłady użycia i instrukcja porównywania modeli (czysty model vs hybryda) znajdują się w głównym `README.md`.

