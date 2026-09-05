# Plan Architektury i Modelowania Zakładów Pobocznych (In-Game Props: Zabójstwa, Czas Gry, Handicapy)

> **Dokumentacja techniczna i badawcza dla projektu EnsembleLegends**  
> **Powiązanie z katalogiem propozycji:** `IDEA-018` w `docs/future_ideas.md`  
> **Stan:** Plan gotowy do wdrożenia operacyjnego  
> **Data:** 2026-09-05  

---

## 1. Cel, Motywacja i Uzasadnienie Rynkowe

### 1.1. Dlaczego rynki poboczne (Props), a nie tylko zwycięzca meczu (1X2 / Moneyline)?
W dotychczasowej architekturze modelowano wyłącznie prawdopodobieństwo zwycięstwa w meczu ($P(\text{Win})$). Rynek 1X2 w League of Legends jest jednak rynkiem globalnie wysoce płynnym, silnie arbitrażowanym przez międzynarodowych bukmacherów (Pinnacle, Betfair, Bet365) i charakteryzującym się niskimi marżami bukmacherskimi. W warunkach polskich, gdzie obowiązuje **12% podatek od stawki**, znalezienie trwałego i wysokiego $\text{EV}$ (Expected Value) na rynku zwycięzcy meczu jest wyzwaniem.

W przeciwieństwie do tego, **zakłady poboczne (props)** na:
1. Łączną sumę zabójstw na mapie (*Over/Under Total Kills*),
2. Indywidualną liczbę zabójstw drużyny (*Team Total Kills*),
3. Handicapy zabójstw (*Kill Handicap Spreads*),
4. Czas trwania mapy (*Map Duration*),

są wyceniane przez bukmacherów (STS, Betclic, Superbet) głównie za pomocą **uproszczonych średnich ligowych lub heurystyk dostawców danych**. Bukmacherzy rzadko modelują pełne rozkłady dwumianowe ujemne z uwzględnieniem dynamicznej dyspersji, asymetrii siły drużyn czy mikro-stylu wczesnej gry. Skutkuje to występowaniem znacznie większych anomalii cenowych (*mispricings*).

### 1.2. Bariera rentowności pod polskim podatkiem obrotowym (12%)
Przy standardowych kursach na linie dwudrogowe ($1.85 / 1.85$):
$$\text{Kurs efektywny} = 1.85 \times (1 - 0.12) = 1.628$$
Próg rentowności (*break-even hit rate*) wynosi:
$$P_{\text{break-even}} = \frac{1}{1.628} \approx 61.43\%$$
Oznacza to, że model musi trafiać z precyzją wyższą niż $61.5\%$ lub typować selektywnie (tylko zakłady z $\text{EV} \ge +5\%$).

---

## 2. Które Rodzaje Kursów i Rynków Nas Interesują?

Przegląd oferty trzech głównych legalnych bukmacherów w Polsce: **STS**, **Betclic** oraz **Superbet**.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   GŁÓWNE RYNKI PROPOZYCJI NA ZABÓJSTWA                           │
├──────────────────────────────────────────────────────────────────────────────────┤
│ 1. Suma zabójstw na 1. mapie (Over/Under)                                        │
│    ├── Linia główna (np. 26.5 lub 28.5)                                          │
│    └── Linie alternatywne (np. 22.5, 24.5, 30.5, 32.5, 34.5)                     │
│ 2. Liczba zabójstw danej drużyny (Team Totals Over/Under)                         │
│    ├── Drużyna 1 (np. Over/Under 12.5, 14.5, 16.5)                               │
│    └── Drużyna 2 (np. Over/Under 10.5, 12.5, 14.5)                               │
│ 3. Handicap zabójstw na 1. mapie (Kill Spread)                                   │
│    └── Pary symetryczne: Faworyt (-4.5, -6.5) / Underdog (+4.5, +6.5)            │
│ 4. Przedziały zabójstw (Kill Ranges)                                             │
│    ├── Mecz: np. <20, 20-24, 25-29, 30-34, 35+                                   │
│    └── Drużyna: np. <10, 10-14, 15-19, 20-24, 25+                                │
│ 5. Czas trwania mapy (Game Duration)                                             │
│    └── Linie: np. Over/Under 29.5 min, 31.5 min, 33.5 min                        │
│ 6. Rynki wyścigu i pierwsze zdarzenia (Race / Firsts)                             │
│    ├── Pierwsza krew (First Blood)                                               │
│    └── Kto pierwszy zdobędzie 5 / 10 / 15 zabójstw                               │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1. Szczegółowy opis poszczególnych rynków:

#### A. Suma zabójstw na mapie (Over/Under Total Kills)
* **Nazewnictwo bukmacherskie:**
  * **STS:** *„1. mapa - suma zabójstw (z dogrywką)”*
  * **Betclic:** *„Łączna liczba zabójstw na 1. mapie”*
  * **Superbet:** *„Suma zabójstw - Mapa 1 (Powyżej/Poniżej)”*
* **Typowe linie:** $22.5, 24.5, 26.5, 28.5, 30.5, 32.5, 34.5$.
* **Format:** Linie połówkowe (wykluczające zwrot/remis).
* **Zastosowanie:** Główny i najbardziej płynny rynek propsów.

#### B. Liczba zabójstw drużyny 1 / 2 (Team Totals)
* **Nazewnictwo bukmacherskie:**
  * **STS:** *„1. mapa - liczba zabójstw drużyny 1 / 2”*
  * **Betclic:** *„Liczba zabójstw drużyny 1 / 2”*
  * **Superbet:** *„Drużyna 1 / 2 - suma zabójstw”*
* **Typowe linie:**
  * Dla faworyta: $14.5, 16.5, 18.5, 20.5$.
  * Dla underdoga: $8.5, 10.5, 12.5, 14.5$.
* **Zastosowanie:** Bardzo wysokie value, gdy bukmacher nie doszacuje dominacji faworyta lub underdoga grającego ultra-pasywnie.

#### C. Handicap zabójstw na mapie (Kill Handicap)
* **Nazewnictwo bukmacherskie:**
  * **STS:** *„1. mapa - handicap zabójstw”*
  * **Betclic:** *„Handicap zabójstw (z dogrywką)”*
  * **Superbet:** *„Handicap zabójstw na mapie”*
* **Typowe linie:** Faworyt $-2.5, -4.5, -6.5, -8.5$; Underdog $+2.5, +4.5, +6.5, +8.5$.
* **Warunek rozliczenia:** Faworyt z handicapem $-5.5$ wygrywa zakład, jeśli różnica $(K_{\text{fav}} - K_{\text{und}}) \ge 6$.

#### D. Przedziały zabójstw (Kill Ranges)
* **Nazewnictwo w STS/Superbet:** *„1. mapa - przedziały zabójstw”*.
* **Typowe koszyki:**
  * Koszyki meczowe: $0-20, 21-25, 26-30, 31-35, 36+$.
  * Koszyki drużynowe: $<10, 10-14, 15-19, 20-24, 25+$.
* **Charakterystyka:** Rynki wielodrogowe z wysokimi kursami (od 2.20 do 6.50), pozwalające na polowanie na rzadkie stany ekstremalne.

#### E. Czas trwania mapy (Game Duration)
* **Nazewnictwo:** *„1. mapa - czas trwania (minuty)”*.
* **Typowe linie:** $28.5, 30.5, 32.5, 34.5$ minut.
* **Rozliczanie:** Czas w grze w sekundach przeliczany na minuty (np. 32:45 to ponad 32.5 minuty).

---

## 3. Architektura i Specyfikacja Danych

### 3.1. Zestawienie Inputów (Cechy Wejściowe do Modeli)

Inputy dzielą się na cztery komplementarne warstwy, generowane ściśle przedmeczowo bez wycieku w przód (*zero lookahead*):

```
┌────────────────────────────────────────────────────────────────────────┐
│                        WARSTWY INPUTÓW                                 │
├────────────────────────────────────────────────────────────────────────┤
│ 1. HISTORIA I ROZKŁAD DRUŻYNY (Team Style & Empirical Distribution)    │
│    ├── Średnie kroczące W20/W5: Kills, Deaths, Total Kills, Duration    │
│    ├── Wskaźniki zmienności: Odchylenie std (σ_kills), Min/Max kills   │
│    ├── Koszyki empiryczne (kill_brackets): <10, 10-14, 15-19, 20-24, 25+│
│    └── Metryki tempa: CKPM (Combined Kills Per Minute), KPM, DPM       │
│                                                                        │
│ 2. ASYMETRIA SIŁY MECZOWEJ (Matchup Spread & Disparity)               │
│    ├── Ratingi Elo drużyn i różnica: ΔElo = R_A - R_B, |ΔElo|          │
│    ├── Prawdopodobieństwo wygranej faworyta: P(Fav) = max(p_A, p_B)    │
│    └── Wskaźnik stompu (wpływający na poszerzenie ogonów dyspersji α)  │
│                                                                        │
│ 3. BENCHMARK LIGOWY (Regional League Context)                          │
│    ├── Średnia killi ligi, średni czas gry, CKPM ligi                   │
│    ├── Kwantyle ligowe: Percentyl 25, Mediana, Percentyl 75            │
│    ├── Kategoria stylu: wolne makro / zrównoważone / dynamiczne / fiesta│
│    └── Odchylenie meczu od ligi: Δ_vs_league (np. +3.8 killa vs LCK)   │
│                                                                        │
│ 4. DANE RYNKOWE (Market Odds Input)                                    │
│    ├── Kursy bukmacherskie Over/Under dla poszczególnych linii         │
│    └── Kursy handicapowe wystawione przez operatorów (STS, Betclic itp)│
└────────────────────────────────────────────────────────────────────────┘
```

#### Szczegółowe struktury danych w kodzie (`betting_app/ml/props/schemas.py`):
1. **`RecentGameSummary`**:
   * `opponent: str`, `kills_for: int`, `kills_against: int`, `total_kills: int`, `duration_minutes: float`, `won: bool`, `date: str`.
2. **`TeamRecentForm`**:
   * `team_name: str`, `sample_size: int`, `avg_kills: float`, `avg_deaths: float`, `avg_total_kills: float`, `avg_duration_minutes: float`, `min_kills: int`, `max_kills: int`, `std_kills: float`, `kill_brackets: dict[str, int]`, `recent_games: list[RecentGameSummary]`.
3. **`LeaguePaceContext`**:
   * `league_name: str`, `league_key: str`, `avg_kills: float`, `avg_duration_minutes: float`, `ckpm: float`, `pace_category: str`, `p25_kills: float`, `median_kills: float`, `p75_kills: float`.
4. **`MatchPropContext`**:
   * `team_a_form: TeamRecentForm`, `team_b_form: TeamRecentForm`, `league_context: LeaguePaceContext`, `expected_pace_kills: float`, `delta_vs_league_avg: float`, `summary_narrative: str`.

---

### 3.2. Zestawienie Outputów (Co Zwraca Silnik Prognostyczny)

Output modelu to nie tylko punktowa średnia, ale **pełny obiekt analityczny**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        WARSTWY OUTPUTÓW                                │
├────────────────────────────────────────────────────────────────────────┤
│ 1. PARAMETRY ROZKŁADU PRAWDOPODOBIEŃSTWA                               │
│    ├── Średnia oczekiwana E[Total Kills] = μ_total                     │
│    ├── Parametr nadmiernej dyspersji α (heteroscedastyczny)            │
│    └── Wariancja Var[Y] = μ + α·μ² oraz odchylenie standardowe σ       │
│                                                                        │
│ 2. KWANTYLE I PRZEDZIAŁY UFNOŚCI                                       │
│    └── P10, P25, Mediana (P50), P75, P90                               │
│                                                                        │
│ 3. DYSKRETNA KRZYWA GĘSTOŚCI (PMF Curve)                               │
│    └── Dokładne P(Kills = k) dla każdego k ∈ [5, 75] do wizualizacji  │
│                                                                        │
│ 4. ROZKŁAD ZABÓJSTW PER DRUŻYNA (Team A / Team B)                      │
│    ├── μ_A, σ_A oraz μ_B, σ_B                                          │
│    └── Wycena linii Over/Under dla Drużyny 1 oraz Drużyny 2            │
│                                                                        │
│ 5. ANALITYCZNA WYCENA LINII BUKMACHERSKICH                             │
│    ├── P(Over), P(Under)                                               │
│    ├── Kursy sprawiedliwe: Fair Odds Over / Under                      │
│    ├── Wartość oczekiwana: EV brutto oraz EV netto (po 12% podatku)    │
│    └── Splot różnicowy handicapów: P((K_A - K_B) > H)                  │
│                                                                        │
│ 6. SYNTEZA DLA UŻYTKOWNIKA (Narrative & UI)                            │
│    └── Gotowy opis słowny tempa meczu, flagi value i rekomendacje      │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Matematyka Modeli

### 4.1. Rozkład sumy zabójstw na mapie (Negative Binomial GLM)
Ze względu na nadrzędną dyspersję ($\text{Var}(Y) > \mathbb{E}[Y]$), standardowy model Poissona jest odrzucany. Stosujemy rozkład dwumianowy ujemny z linkiem logarytmicznym:
$$\ln(\mu_{\text{total}}) = \beta_0 + \beta_{\text{pace}} \cdot \text{Pace} + \beta_{\text{spread}} \cdot |\Delta\text{Elo}| + \beta_{\text{inter}} \cdot (\text{Pace} \times |\Delta\text{Elo}|)$$
Dynamiczny parametr dyspersji $\alpha$ rośnie wraz z asymetrią meczu (stompy mają grubsze ogony):
$$\alpha(|\Delta\text{Elo}|) = \alpha_0 + \alpha_{\text{spread}} \cdot |\Delta\text{Elo}|$$
Prawdopodobieństwo linii Over/Under dla linii połówkowej $L$ (np. $28.5$):
$$P(\text{Under } L) = F_{\text{NB}}(\lfloor L \rfloor; r, p) = \sum_{k=0}^{\lfloor L \rfloor} \binom{k + r - 1}{k} (1 - p)^r p^k$$
$$P(\text{Over } L) = 1 - P(\text{Under } L)$$
gdzie $r = \frac{1}{\alpha}$, $p = \frac{1}{1 + \alpha \mu}$.

### 4.2. Rozkład zabójstw per drużyna i splot różnicowy handicapu
Dla drużyn $A$ i $B$:
$$\ln(\mu_A) = \gamma_0 + \gamma_{\text{pace}} \cdot \text{Pace}_A + \gamma_{\text{spread}} \cdot (R_A - R_B)$$
$$\ln(\mu_B) = \gamma_0 + \gamma_{\text{pace}} \cdot \text{Pace}_B + \gamma_{\text{spread}} \cdot (R_B - R_A)$$
Splot dyskretny różnicy zabójstw $D = K_A - K_B$:
$$P(D = d) = \sum_{k} P(K_A = k + d) \cdot P(K_B = k)$$
Prawdopodobieństwo pokrycia handicapu $H$ (np. $-5.5$):
$$P(\text{Cover}_A(H)) = \sum_{d > H} P(D = d)$$

---

## 5. Pomysły na Testy i Metodologia Walidacji

Aby zagwarantować bezwzględną poprawność i chronologiczność, wdrożono zestaw 5 typów testów:

### 5.1. Testy Statystyczne i Probabilistyczne (Jakość Rozkładu)
1. **CRPS (Continuous Ranked Probability Score):**
   Główna miara dopasowania całego rozkładu dyskretnego:
   $$\text{CRPS}(F, y) = \sum_{k=0}^{\infty} \left( F(k) - \mathbf{1}(k \ge y) \right)^2$$
   *Kryterium akceptacji:* Model ze spreadem i dynamiczną dyspersją musi osiągać niższy CRPS niż model z samym tempem we wszystkich foldach walk-forward.
2. **NLL (Negative Log-Likelihood):**
   Średnia wartość $-\ln P(Y = y_{\text{faktyczne}})$. Im niższy NLL, tym wyższe prawdopodobieństwo przypisane rzeczywistym wynikom.
3. **Kalibracja kwantyli (Reliability Diagram / PIT):**
   Sprawdzanie, czy empiryczny odsetek obserwacji wpadających w przedziały predykcyjne zgadza się z założeniami:
   * Przedział P25–P75 $\implies$ cel: **$50.0\%$** (dopuszczalne odchylenie $\pm 5\%$).
   * Przedział P10–P90 $\implies$ cel: **$80.0\%$** (dopuszczalne odchylenie $\pm 5\%$).
4. **LogLoss i Brier Score na liniach bukmacherskich:**
   Testowanie trafności binarnych predykcji Over/Under na kluczowych liniach rynkowych (24.5, 26.5, 28.5, 30.5).

### 5.2. Testy Właściwości i Niezmienników Matematycznych (Property-Based Tests)
1. **Niezmiennik symetrii stron (Team-Order Invariance):**
   $$\mu_{\text{total}}(A \text{ vs } B) = \mu_{\text{total}}(B \text{ vs } A)$$
   $$P(\text{Over } L \mid A \text{ vs } B) = P(\text{Over } L \mid B \text{ vs } A)$$
   $$\mu_A(A \text{ vs } B) = \mu_B(B \text{ vs } A)$$
2. **Dopełnienie prawdopodobieństw linii połówkowych:**
   $$P(\text{Over } L) + P(\text{Under } L) = 1.0 \pm 10^{-6}$$
3. **Ścisła monotoniczność linii Over/Under:**
   $$\forall L_1 < L_2: \quad P(\text{Over } L_1) > P(\text{Over } L_2)$$
4. **Pokrycie masy dyskretnego splotu:**
   $$\sum_{d=-40}^{40} P(K_A - K_B = d) > 0.9999$$

### 5.3. Walidacja Krocząca (Expanding Walk-Forward Cross-Validation)
* **Zbiór uczący:** Rozszerzające się okno chronologiczne (początek od lat 2022–2023, 15 651 gier).
* **Zbiór testowy:** 9 kwartalnych foldów *out-of-fold* (od 2024-Q1 do 2026-YTD, łącznie 21 539 gier).
* **Zasada:** Zero wycieku danych – ani jeden mecz z przyszłości nie może wpłynąć na estymację parametrów w danym kwartale.

### 5.4. Backtesting Finansowy i Symulacja Bankrolla (EV & Kelly Criterion)
* **Uwzględnienie polskiego podatku obrotowego (12%):**
  $$\text{Zysk netto} = \text{Stawka} \times (\text{Kurs} \times 0.88 - 1)$$
* **Zarządzanie kapitałem (Staking):**
  * Ułamkowe kryterium Kelly'ego (Fractional Kelly, $f^* = 0.25$).
  * Ograniczenie maksymalnej stawki do $3\%$ bieżącego bankrolla.
* **Filtry selektywności:**
  * Testowanie progów rentowności: obstawianie wyłącznie przy $\text{Edge} \ge 3\%$, $\ge 5\%$, $\ge 8\%$.
  * Śledzenie wskaźnika Sharpe'a, ROI oraz Maximum Drawdown (MDD).

### 5.5. Testy Jednostkowe Parserów Bukmacherskich (Mock HTML/JSON)
* Weryfikacja scraperów na zapisanych plikach HTML/JSON z ofertami STS, Betclic i Superbet bez wysyłania zapytań live.
* Testowanie prawidłowego wyciągania linii połówkowych i kursów.

---

## 6. Harmonogram i Kamienie Milowe

| Faza | Zadanie | Status | Kluczowy artefakt |
|---|---|---|---|
| **Faza 1** | Badanie rozkładów empirycznych i dyspersji ($n = 38\ 804$) | Ukończona | `reports/eda_prop_markets_idea018.md` |
| **Faza 2** | Silnik rozkładu sumy zabójstw z interakcją tempa i spreadu | Ukończona | `betting_app/ml/props/kill_distribution_model.py` |
| **Faza 3** | Silnik rozkładu drużynowego i splotu handicapów | Ukończona | `betting_app/ml/props/team_spread_model.py` |
| **Faza 4** | Walidacja krocząca Walk-Forward (9 foldów, 2024–2026) | Ukończona | `betting_app/ml/props/walk_forward.py` |
| **Faza 5** | Przedmeczowy kontekst historyczny (ostatnie mecze, benchmark ligi) | Ukończona | `betting_app/ml/props/feature_extractor.py` |
| **Faza 6** | Rozszerzenie parserów STS, Betclic, Superbet o pobieranie linii props | Planowana | `betting_app/scrapers/` |
| **Faza 7** | Integracja z widokiem szczegółów meczu na frontendzie | Planowana | `client/src/pages/MatchDetail.tsx` |

---

## 7. Powiązania w Repozytorium

* Główny rejestr pomysłów: [`docs/future_ideas.md`](../docs/future_ideas.md) (wpis `IDEA-018`)
* Karta badawcza pomysłu: [`ideas/IDEA-018_in_game_prop_prediction_models.md`](IDEA-018_in_game_prop_prediction_models.md)
* Raport z badań eksploracyjnych (EDA): [`reports/eda_prop_markets_idea018.md`](../reports/eda_prop_markets_idea018.md)
* Kod modułu props: [`betting_app/ml/props/`](../betting_app/ml/props/)
* Testy jednostkowe: [`betting_app/tests/test_kill_distribution_model.py`](../betting_app/tests/test_kill_distribution_model.py) oraz [`betting_app/tests/test_team_spread_model.py`](../betting_app/tests/test_team_spread_model.py)
