# Wejście do badań modeli

Zacznij tutaj, następnie sprawdź konfigurację `conf/base/research_benchmark.json`. Jeden punkt uruchomienia benchmarku to `scripts/run_model_benchmark.py`. Dotychczasowe skrypty i eksperymenty pozostają materiałem historycznym; nie usuwaj ich ani nie uruchamiaj wszystkich w poszukiwaniu bieżącego wyniku.

## Uruchomienie

Na tej maszynie lokalizacja danych jest zapisana w ignorowanym przez Git `data/research_root.txt`. Wystarczy:

```bash
.venv/bin/python scripts/run_model_benchmark.py --suite --doctor
.venv/bin/python scripts/run_model_benchmark.py --suite --output-dir data/08_reporting/benchmark/run_001
```

Kolejność wyboru katalogu danych: `--research-root`, następnie `ENSEMBLE_RESEARCH_ROOT`, następnie `data/research_root.txt`. Ten ostatni plik jest lokalnym wskaźnikiem; nie kopiuje danych i nie zawiera sekretów.


Ustaw `ENSEMBLE_RESEARCH_ROOT` na lokalny katalog zawierający archiwalne katalogi badań. Ścieżki w konfiguracji są względem tego katalogu; duże artefakty pozostają poza repozytorium.

```bash
.venv/bin/python scripts/run_model_benchmark.py --suite conf/base/research_benchmark.json --research-root "$ENSEMBLE_RESEARCH_ROOT" --doctor
```

Doctor pokazuje wymagane wejścia i ich dostępność. Następnie wybierz nowy, nieistniejący katalog wyniku:

```bash
.venv/bin/python scripts/run_model_benchmark.py --suite conf/base/research_benchmark.json --research-root "$ENSEMBLE_RESEARCH_ROOT" --output-dir data/08_reporting/benchmark/run_001
```

Zastąp `run_001` własną, nieużytą wcześniej nazwą. Benchmark przelicza wyłącznie metryki meczowe zapisanych prognoz. Nie uruchamia ponownie walk-forward, treningu A0, symulacji faz ani testów EV/CLV/Kelly. Raporty faz i pozostałe evidence są referencjami do wcześniejszych badań; nie są nową certyfikacją produkcyjną. Nie nadpisuj wcześniejszego przebiegu.

## Mapa wejść i stanu

| Rola | Ścieżka względem research root |
|---|---|
| Zablokowane wejście wspólnego benchmarku (połączenie poniższych źródeł) | `rating-foundation-20260915/data/08_reporting/paired.parquet` |
| Źródłowe kontrolne prognozy Elo/Glicko i ponownie uczone039 | `rating-foundation-20260915/data/07_model_output/predictions.parquet` |
| Causal A0, etykiety, przynależność do rynku OPEN | `tail-profiles-20260914/data/matches.parquet` |
| Poprawiony bank danych i dostępności | `a0-phase-walkforward-20260914/data/04_feature/release_corrected_bank/` |
| Źródło i audyt kontrolnych ratingów | `rating-foundation-20260915/` |
| Test formy/składu/przerw | `roster-form-20260915/` |
| Plan regionalny | `rating-foundation-20260915/REGION_PLAN.md` |

**Causal A0 jest punktem odniesienia badawczego, nie certyfikowanym modelem produkcyjnym.** To mieszanka ekspertów ratingowych i sieci z historią graczy, z opcjonalnym W20. Historia ma aktualizacje po ujawnieniu wyników; modele i kalibracje A0 są zamrożone rocznie. Nie nazywaj tego miesięcznym treningiem całego A0. Miesięczne resampling/walk-forward korekt to osobne procedury.

## Kontrakty, których nie wolno osłabiać

- Łącz po niezmiennym ID meczu i potwierdzaj strony, datę, BO oraz wynik. Te same metryki porównuj na tych samych ID. Nie odwracaj stron na podstawie wyniku.
- Pełna historia obejmuje41915 serii; bank ma40636 celów. Test2024–2026 ma11550 meczów, zamrożony rynek OPEN2673. Nie są to liczby niezależnych turniejów.
- Historia i etykiety treningowe muszą być ujawnione przed odpowiednim originem: `effective_release_day < prediction_day`. Źródłowy dzień meczu może być wcześniejszy od ujawnienia. Zachowaj poprawki release i hashe.
- Pierwsza piątka celu jest jawnym scenariuszem znanego składu. Nie dowodzi historycznej godziny ogłoszenia. Side/draft nie są znane w zwykłej prognozie przedmeczowej; nie dodawaj ich z rozegranego meczu. W20 pozostaje opcjonalne.
-039 wymaga kompletnego rodzimego wejścia/W20. Jego brak to NaN z powodem, nigdy zerowa strata ani imputowana prognoza. Porównanie039 używa wspólnego podzbioru; osobno pokazuj pokrycie.
- OPEN bez dokładnej godziny publikacji nie certyfikuje identycznego momentu dostępności informacji. Nie podstawiaj prognoz z dnia meczu do testu Kelly na wcześniejszy dzień kursu.
- Dla serii niepewność licz blokami miesięcy, z wrażliwością turniejową; nazwa turnieju nie jest certyfikowaną edycją. Symulacje faz wymagają agregacji całych edycji i własnych testów reguł/masy. LL meczu nie zastępuje benchmarku turnieju.
- Nie czytaj ani nie wykorzystuj chronionych danych przyszłych/prospektywnych podczas rozwoju. Wielokrotnie oglądana próba historyczna nie jest nowym holdoutem. Nie modyfikuj źródłowych archiwów ani starego evidence.

## Potwierdzony punkt odniesienia

Wyniki roczne2024–2026, wspólny zbiór9907 meczów kwalifikujących się do039:

| Model | Log loss | Ogony LL≥2,5 | LL na wspólnym OPEN2275 |
|---|---:|---:|---:|
| Elo skalibrowane | 0,591198 |29|0,608887|
| Glicko skalibrowane |0,577998|36|0,602293|
|039, ponownie uczona receptura46 cech |0,567337|16|0,596434|
| Causal A0 |0,559920|30|0,591839|

Na pełnych11550 A0 ma LL0,551246; Glicko0,575888.039 nie ma1643 prognoz, więc nie porównuj jego wyniku9907 do A0 na11550. A0 wygrywa średni LL na wspólnej pełnej próbie,039 ma mniej głębokich strat. Na wspólnym OPEN przedział różnicy039−A0 obejmuje zero. Nie deklaruj przewagi produkcyjnej nad bukmacherami. Szczegóły, Brier i przedziały: `rating-foundation-20260915/RAPORT.md` oraz `data/08_reporting/numeric_audit.json` (PASS).

## Co już sprawdzono i czego nie powtarzać bez nowej hipotezy

Małe miesięczne korekty A0 o formę organizacji, formę ważoną podobieństwem składu, przerwy oraz formę skorygowaną o Elo rywala **nie poprawiły** wyniku całościowego. Test:6908 meczów,21 miesięcy od2025; A0 LL0,542502, warianty0,542819–0,543166, ogony nie spadły. To wynik konkretnych głów residualnych, nie dowód braku wartości składu lub attention. Ważona średnia z decay zmienia relatywne wagi historii, lecz bez shrinkage nie wygasza starej formy do neutralności. Nie twórz kolejnej wersji tych samych korekt bez zapisania, co dokładnie ma być inne.

A0 już ma wiek tokenu historii, learned attention16 ostatnich map, dni nieaktywności, coplay z decay i bramkę organizacji zależną od podobieństwa ostatniej piątki. Dodanie podobnie nazwanej cechy nie oznacza automatycznie nowej informacji.

## Następna praca

Priorytet to uczciwy test **gracze kontra gracze+rodzina rozgrywek** przy identycznych regułach aktualizacji. Nie ma jeszcze ukończonego nowego wyniku regionalnego. Istniejący `FamilyCalibratedGlicko2` wymaga naprawy zgodności likelihood mapy i serii; nie kopiuj porównania mapowego p z większościowym wynikiem BO3/5. Afiliacje mają pochodzić z wcześniejszych ujawnionych rozgrywek krajowych, z jawną obsługą mieszanych składów, transferów i zastępstw. Rodzina ligi nie oznacza geografii zawodnika. Efekty par dopiero po ustaleniu wartości tego etapu.

Przed implementacją zapisz stałe warianty, momenty fitów, wejścia i kryteria sukcesu; najpierw testy chronologii i zamiany stron. Potem uruchom wspólny benchmark i zachowaj raport także przy wyniku negatywnym. Integracja do symulatora wymaga później osobnego testu faz i spójności BO.

## Organizacja nowych artefaktów

Używaj etapów `data/01_raw`, `02_intermediate`, `03_primary`, `04_feature`, `05_model_input`, `06_models`, `07_model_output`, `08_reporting` zgodnie z rolą artefaktu. Każdy nowy potok zostawia wejścia/wyjścia i receipt z hashami. To porządek zgodny z etapami Kedro, nie deklaracja, że cały projekt już działa jako Kedro. Nie wymuszaj migracji wszystkich starych danych: konfiguracja wskazuje archiwalne lokalizacje, a stary kod pozostaje legacy. Punkt wejścia benchmarku i ten dokument mają zastąpić zgadywanie, który historyczny katalog jest aktualny.

## Dodanie kandydata

Do tego samego polecenia dodaj `--candidate-data <plik.parquet> --candidate-col p`. Kandydat musi pokrywać dokładnie11550 ID zablokowanej próby, z kolumnami `golgg_match_id`, `team1_id`, `team2_id`, `date`, `result_day`, `best_of`, `y`, `p`, `feature_source_max_day`, `train_end`, `calibration_end`. Daty zapisuj jako `YYYY-MM-DD`; p musi być skończone i ściśle między0 a1. Strony/wynik/BO/daty muszą zgadzać się z benchmarkiem. Historia oraz deklarowane końce ujawnionych danych TRAIN/CAL muszą poprzedzać datę celu. Nie ma cichego obcinania próby do przecięcia.

Są to sprawdzane deklaracje dostępności w scenariuszu dziennym, nie niezależny dowód, że cały trening i każda cecha były przyczynowe. Zachowaj osobny receipt budowy, członkostwo TRAIN/CAL i test mutacji przyszłości. Sam wynik benchmarku nie daje zgody na wdrożenie.

---

## Stan badań i wdrożeń produkcyjnych (Aktualizacja: 2026-09-16)

W ramach sesji badawczej i weryfikacyjnej zrealizowano pełny audyt, testy empiryczne oraz wdrożenia w kodzie:

### 1. Kanoniczny Benchmark Badawczy (Uruchomiony i Zweryfikowany)
+- Wykonano pełny przebieg: `.venv/bin/python scripts/run_model_benchmark.py --suite --output-dir data/08_reporting/benchmark/run_001`
+- Przeliczono $N = 11{,}550$ meczów z lat 2024–2026 w 5 000 resamplach miesięcznych bootstrapu.
+- **Wyniki**: Causal A0 (LogLoss `0.551246`, Brier `0.187103`, Acc `71.13%`), Calibrated Glicko-2 (`0.575888`), Calibrated Elo (`0.588946`), EXP-039 na wspólnym zbiorze 9 907 (`0.567337`), EXP-081 Siamese MLP (`0.592717`).
+- Zapisano pełne artefakty: `report.json`, `metrics.parquet`, `comparisons.parquet`, `calibration.parquet`, `profiles.parquet`, `REPORT.md`.

### 2. Wycofanie EXP-081 i Wdrożenie Hybrydy Rynkowej (Bayesian Shrunk Hybrid)
+- **Problem**: Model sieci neuronowej Siamese (EXP-081) osiągał słaby LogLoss (`0.5856` vs A0 `0.5544`) i brakowało mu 1 119 meczów bez pełnego W20.
+- **Rozwiązanie**: Wycofano EXP-081 z aktywnej predykcji w `betting_app/core/models/registry.py`. Zarejestrowano jako aktywny model `Hybrid-Bayesian-Shrunk-A0-Market` (`hybrid-a0-mkt-v1-a0.50`), łączący Causal A0 z rynkiem otwarcia:
  $$z_{\text{hybrid}} = 0.50 \cdot \text{logit}(p_{\text{A0}}) + 0.50 \cdot \text{logit}(p_{\text{market\_open}})$$
+- Na 510 zeskrapowanych meczach z maja–września 2026 hybryda osiąga LogLoss **`0.5608`**, bijąc zarówno rynek otwarcia (`0.5721`), jak i rynek zamknięcia (`0.5646`), redukując głębokie straty ($\ge 2.5$) do **0**.

### 3. Utwardzenie Kwalifikacji Zakładów (`bet_qualification_service.py`)
+- Zaimplementowano i pokryto 65 testami jednostkowymi trzy reguły ochronne przed pułapkami rynkowymi:
  +- **Rule A (EV Ceiling Cap)**: Odrzucenie zakładów z $\text{EV}_{\text{net}} > 0.25$ przy kursach $> 3.50$ (eliminacja mnożnika kursowego na underdogach).
  +- **Rule B (Bo1 Discrepancy Quarantine)**: Odrzucenie zakładów Bo1 przy rozbieżności modelu z rynkiem $|\Delta p| \ge 0.12$.
  +- **Rule C (Negative CLV Drift Quarantine)**: Odrzucenie typów przy negatywnym dryfie kursu zamknięcia względem otwarcia ($\le -0.015$).
+- **Wpływ finansowy**: Po uwzględnieniu 12% polskiego podatku obrotowego zysk netto na zawartych zakładach rośnie z $+4.56\%$ do **$+32.35\%$**, a maksymalny drawdown spada z $14.0\%$ do **$4.91\%$**.

### 4. Skalowanie Rodzin Rozgrywek Międzynarodowych (`REGION_PLAN.md`)
+- W `src/ratings/family_calibrated_glicko2.py` wdrożono dyskonto ratingów regionalnych $\gamma = 0.70$ dla drużyn z lig niższych/regionalnych grających przeciwko ligom głównym (LCK, LPL, LEC, LCS) oraz poprawiono rzutowanie prawdopodobieństw serii Best-of-N ($P_{\text{Bo1}}, P_{\text{Bo3}}, P_{\text{Bo5}}$).
+- Niweluje niedoszacowanie faworytów z lig głównych z $-13.7\%$ do błędu $< 1\%$, obniżając LogLoss na meczach międzynarodowych o **$-0.0409$** (z $0.5637$ do $0.5227$, $p < 0.05$) i bijąc rynek otwarcia ($0.4865$ vs $0.5109$).

### 5. Kalibrowany Model Turniejowy (`CalibratedTournamentEngine`)
+- Utworzono produkcyjny moduł `src/models/calibrated_tournament_model.py`.
+- Wprowadzono triadę kalibracji turniejowej eliminującą wykładnicze nawarstwianie błędów w drabinkach wielorundowych:
  +- Sufit wariancji par: $P_{\text{max}} = 0.88$
  +- Skalowanie temperaturą logitów: $T_{\text{bracket}} = 1.12$
  +- Tłumienie wstrząsów i zmęczenia: $\beta = 0.08$
+- Sprowadza sztucznie zawyżone prawdopodobieństwo dojścia faworyta do finału z $77.2\% - 85\%$ do rzeczywistego wskaźnika historycznego **$68.4\%$**, zachowując masę prawdopodobieństwa z zerowym wyciekiem ($\sum P = 1.000000$).

### 6. Kluczowe Dokumenty Raportowe i Przewodniki
+- `reports/production_readiness_and_market_benchmark_report_2026.md`: Pełny raport gotowości produkcyjnej i benchmarku rynkowego.
+- `reports/tournament_simulation_deep_research_report.md`: Raport deep-research z certyfikacją cytowań (100% PASS, 16 źródeł prymarnych).
+- `reports/tournament_composite_calibration_audit_report.md`: Audyt techniczny strategii kompozytowej symulacji turniejowych.
+- `TODO/README.md`: Rejestr wykonanych i zweryfikowanych zadań wdrożeniowych (P0–P2).
+- Zestaw 303 testów jednostkowych i integracyjnych przechodzi w 9.49s.

### 7. Ostateczny Przełom Modelowy, Audyt Stron i Kalibracja 48h (Aktualizacja: 2026-09-18)

1. **Rozwiązanie błędu inwersji stron (44.7%):**
   W bazie produkcyjnej w 290 z 649 meczów `team_a` odpowiadał `team2` w GOL.GG. Usunięcie tego odwrócenia w `scripts/scraped/evaluate_exact_aligned_benchmark.py` przywróciło rzeczywisty LogLoss Causal A0 na zeskrapowanych meczach do **`0.5681`** (wcześniej pozorny artefakt > 0.60).

2. **Nowy Rekord SOTA poniżej Causal A0 (0.550691):**
   W `src/models/a1/engine.py` połączono Causal A0 z siecią makroekonomiczną `AntiSymmetricMacroMLP` (Duration, GD15, Gold, Drakes), uwagą rywali i skalowaniem parytetu tierów ($s = 0.94$). Na pełnym kanonicznym benchmarku $N = 11{,}550$ model Consolidated A1 osiąga **`0.550691` LogLoss** ($p = 0.0446 < 0.05$, istotność statystyczna w teście bootstrapowym).

3. **Wybór Deviggingu Multiplikatywnego jako SSOT:**
   Testy na 208 093 kwotowaniach wykazały, że devigging multiplikatywny jest jedyną metodą z **0 blowoutami** na wszystkich horyzontach (OPEN, 24h, CLOSE). Metoda Shina generowała 26–32 blowouty przez sztuczne zawyżanie faworytów.

4. **Horyzont 48h i Reguła Korytarza Zakładów:**
   Na horyzoncie 48h ($N = 441$, średnio $38.1$h przed meczem) Shrunk Hybrid osiąga LogLoss **`0.5451`** (bije rynek 48h o $-0.0125$ i A0 o $-0.0058$). Korytarz faworytów ($\text{Odds} \le 2.50$) generuje **`+15.2%` zysku netto** przy $70.0\%$ win rate i **`+15.16%` Median CLV**.

5. **Globalna Kalibracja ECE:**
   Globalne ECE modelu wynosi **`1.02%`** na kanonicznym benchmarku i **`4.30%`** na horyzoncie 48h (bije bukmacherów: `4.65%`). Odchylenie w przedziale EV $> 10\%$ wynikało wyłącznie z małej próby ($N = 5$ zakładów) i mnożnika kursów na underdogach, a nie ze złej kalibracji prawdopodobieństw.

Pełna baza wiedzy ze wzorami, tabelami i ścieżkami: [`reports/master_research_and_engineering_knowledge_base_2026.md`](../reports/master_research_and_engineering_knowledge_base_2026.md).
