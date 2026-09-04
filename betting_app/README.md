# LoL Betting Manager

Lokalna aplikacja do ręcznej bukmacherki/analityki LoL. Aplikacja **nie stawia zakładów automatycznie** — służy do zbierania kursów, mapowania drużyn, liczenia EV, zapisywania decyzji i późniejszej analizy bankrolla/CLV.

## Status

MVP v0.2:

- SQLite schema i lokalna baza `data/betting_app.sqlite3`,
- **FastAPI backend** (`betting_app/api/`) — REST API dla frontendu React,
- **React frontend** (`client/`) — dashboard z listą meczów, rankingami drużyn i zawodników, szczegółami, statusem systemu, schedulerem i analizą timingową,
- nadchodzące mecze, max/średnie kursy A/B, arbitraż, model, hybryda i karta szczegółów meczu,
- generowanie sygnałów EV+ jako diagnostyka,
- manualny bet tracker,
- osobne portfele/konta per bukmacher i historia transakcji,
- rozliczanie zakładów i bankroll events,
- znormalizowany tracking kursów: `scrape_runs` → `bookmaker_events` → `bookmaker_markets` → `odds_outcome_snapshots`,
- scraper STS League of Legends prematch przez `sbk-exporter/v1/sports/ssr`,
- scrapery NoDriver/API dla Betclic, Superbet, eFortuna, Betfan, TOTALbet i Lebull.

## Uruchomienie

### Docker Compose (rekomendowane)

```bash
docker compose up --build -d betting-api betting-scheduler client
```

Frontend będzie dostępny na `http://localhost:3000`, API na `http://localhost:8000`.

### Lokalnie (bez Dockera)

Backend:

```bash
python -m betting_app.scripts.init_db
uvicorn betting_app.api.main:app --reload --port 8000
```

Frontend:

```bash
cd client
npm install
npm run dev
```

Frontend będzie dostępny na `http://localhost:3000`.

Docelowo do scrapowania:

```bash
pip install nodriver
```

## Jak to działa — aktualny obraz systemu

System składa się z pięciu warstw:

1. **Dane GOL.GG**
   - surowy cache: `data/golgg_matches.json`,
   - relacyjna baza SQLite: `golgg_matches`, `golgg_games`, `golgg_game_players`, `golgg_teams`,
   - aktualizacja zakończonych meczów co 2–3 dni przez `refresh_golgg_results`,
   - scraper GOL.GG jest skopiowany do projektu jako `betting_app/scrapers/golgg.py`, więc zwykłe działanie aplikacji nie wymaga zewnętrznego checkoutu `embedded-rift`.

2. **Kursy bukmacherów**
   - scrapery LoL prematch match-winner dla: STS, Betclic, Superbet, eFortuna, Betfan, TOTALbet, Lebull,
   - zapis do `odds_snapshots` oraz znormalizowanych tabel `scrape_runs`, `bookmaker_events`, `bookmaker_markets`, `odds_outcome_snapshots`,
   - każdy snapshot ma `source_url`, a jeśli da się ustalić także `offer_url` do konkretnej oferty.

3. **Mapowanie meczów**
   - `canonical_matches` łączy ten sam mecz między bukmacherami,
   - kursy są wyrównywane do canonical team A/B, więc odwrócone strony u bukmachera nie psują best odds.

4. **Model operacyjny upcoming**
   - `entity_ratings`: Elo/Glicko-2/TrueSkill/OpenSkill/PL/TM dla teamów i graczy,
   - `team_rolling_features`: W20 z GOL.GG,
   - `upcoming_match_features`: feature vector dla przyszłego meczu,
   - roster upcoming = ostatni zaobserwowany roster drużyny w GOL.GG,
   - `canonical_predictions`: predykcje operational model oraz hybrydy model+rynek,
   - `model_ev_signals`: EV po podatku 12%.

5. **UI / operacja**
   - React frontend (`client/`) — lista meczów, szczegóły, status systemu, scheduler, analiza timingowa.
   - FastAPI backend (`betting_app/api/`) — REST API z endpointami dla matches, predictions, bets, system, scheduler, timing.
   - Widok ENC 2027 wybiera najwyżej ocenioną rolę GL wyłącznie z ogłoszonej kadry narodowej i blokuje symulację, gdy roster lub rating nie jest zweryfikowany; nie jest to predykcja modelu EXP-039 ani sygnał bukmacherski.

## Kiedy co uruchamiać

Rekomendowany rytm, żeby ograniczyć ryzyko bana i nie odpytywać stron bez sensu:

| Co | Jak często | Po co |
|---|---:|---|
| Lekki scrape ofert bukmacherów | co 1–2h, domyślnie 2h | aktualna lista upcoming i orientacyjne kursy |
| Pipeline predykcji/EV bez scrapowania | dowolnie często | przeliczenie features/predykcji na istniejących kursach |
| Close odds check | ręcznie / selektywnie 5–15 min przed meczem | ostatni kurs do CLV i decyzji |
| Refresh GOL.GG zakończonych meczów | co 2–3 dni | nowe wyniki i gry |
| Import GOL.GG + rebuild ratingów + W20 | po refreshu GOL.GG | aktualizacja modelu sportowego |

Domyślny scheduler w Dockerze **nie scrapuje co 30 minut**. Ustawiony jest na 2h:

```text
BETTING_SCHEDULER_INTERVAL_SECONDS=7200
```

Jeżeli chcesz ostrożniej:

```bash
BETTING_SCHEDULER_INTERVAL_SECONDS=10800 docker compose up -d betting-scheduler  # 3h
```

Jeżeli chcesz tylko przeliczyć model/EV bez nowych requestów do bukmacherów:

```bash
python -m betting_app.scripts.run_upcoming_prediction_pipeline --operational-hybrid --min-ev 0.05
```

Close odds najlepiej robić selektywnie: najpierw panel wskazuje ciekawe EV+, potem otwierasz `offer_url` albo odpalasz pojedynczy scraper przed startem. Nie ma potrzeby agresywnie odpytywać wszystkich bukmacherów co kilka minut.

## Docker Compose / najprostsze przenoszenie

Dodane są pliki:

- `Dockerfile.betting` — obraz Python 3.12 + Chromium + zależności scraperów/modelu,
- `requirements-betting.txt` — zależności aplikacji bettingowej,
- `docker-compose.yml` — API backend, scheduler, frontend React i opcjonalny heavy maintenance,
- `.dockerignore` — mniejszy kontekst buildu.

Najprostszy start:

```bash
docker compose up --build -d betting-api betting-scheduler client
```

Frontend będzie dostępny na:

```text
http://localhost:3000
```

API backend na:

```text
http://localhost:8000
```

Co robią kontenery:

- `betting-api` — FastAPI backend (REST API),
- `client` — React frontend (Vite dev server),
- `betting-scheduler` — co `BETTING_SCHEDULER_INTERVAL_SECONDS` sekund odpala lekki cykl; domyślnie co 2h, żeby nie spamować bukmacherów:
  1. scrape kursów: STS, Betclic, Superbet, eFortuna, Betfan, TOTALbet, Lebull,
  2. rebuild canonical matches,
  3. build upcoming features,
  4. predict operational model,
  5. generate hybrid model+market,
  6. generate EV signals.
- `betting-maintenance` — profil opcjonalny do cięższego cyklu: GOL.GG refresh, import JSON→SQLite, rebuild ratingów, rebuild W20, potem lekki cykl.

Dane są trzymane w bind-mount:

```text
./data:/app/data
```

czyli SQLite, GOL.GG JSON i debug scraperów zostają lokalnie poza kontenerem.

W `docker-compose.yml` jest też przygotowany serwis `timescaledb` (`timescale/timescaledb:2.17.2-pg16`) jako docelowy backend pod historię kursów/CLV. Na ten moment aplikacja nadal domyślnie działa na SQLite, bo kod ma dużo jawnych zapytań SQLite. Kolejny etap migracji to adapter DB + Alembic i przeniesienie tabel kursów/zakładów do Timescale.

Przydatne komendy:

```bash
# logi schedulerów
docker compose logs -f betting-scheduler

# ręczny lekki cykl jednorazowy
docker compose run --rm betting-scheduler \
  python -m betting_app.scripts.scheduler --mode light-once

# ręczny pipeline bez scrapowania, na istniejących kursach
docker compose run --rm betting-scheduler \
  python -m betting_app.scripts.run_upcoming_prediction_pipeline --operational-hybrid --min-ev 0.05
```

Ciężki maintenance z GOL.GG korzysta teraz z lokalnego scrapera `betting_app/scrapers/golgg.py`:

```bash
docker compose --profile maintenance run --rm betting-maintenance
```

Zmienna `EMBEDDED_RIFT_ESPORT_DIR` może jeszcze występować w starych komendach dla kompatybilności, ale `refresh_golgg_results` jej już nie potrzebuje.

Zmienne środowiskowe:

```text
BETTING_APP_TAX_RATE=0.12
BETTING_APP_MIN_EV=0.05
BETTING_APP_BANKROLL=100.0
BETTING_SCHEDULER_INTERVAL_SECONDS=7200
BETTING_SCHEDULER_BOOKMAKERS=sts,betclic,superbet,efortuna,betfan,totalbet,lebull
```

Możesz skopiować przykład konfiguracji:

```bash
cp .env.betting.example .env
```

### Tryb laptop 24/7 bez SSH

Docelowy tryb użycia:

1. Na laptopie wgrywasz repo i bazowe dane w `data/`.
2. Uruchamiasz raz:

```bash
docker compose up --build -d betting-api betting-scheduler client
```

3. Upewniasz się, że Docker startuje po restarcie systemu:

```bash
sudo systemctl enable docker
```

4. Od tej pory kontenery mają `restart: unless-stopped`, więc po restarcie laptopa Docker powinien sam podnieść API i scheduler.
5. Korzystasz z frontendu React:
   - **Lista meczów** — wyniki, EV, best odds, linki do ofert,
   - **System status** — czy scheduler żyje, ostatnie błędy, ostatnie scrape'y,
   - **Scheduler** — status zadań, ręczne triggery, historia runów,
   - **Timing Analysis** — analiza zmian kursów w czasie, najlepsze okno do obstawiania.

Scheduler zapisuje swoje cykle do tabel:

- `automation_runs`,
- `automation_commands`.

Dzięki temu nie trzeba czytać logów Dockera, żeby zobaczyć czy automat działa. Logi Dockera zostają tylko jako awaryjna diagnostyka.

Backup lokalnej bazy:

```bash
python -m betting_app.scripts.backup_sqlite
```

Backupy trafiają do:

```text
data/backups/
```

Rekomendowany praktyczny model:

- lekki scheduler działa sam co 2h,
- GOL.GG / ratingi / W20 robisz co 2–3 dni przez maintenance,
- close odds odpalasz selektywnie z panelu przy interesujących EV+,
- wyniki oglądasz w React froncie, nie w terminalu.

## Testowy flow bez bukmachera

1. Inicjalizacja bazy:

```bash
python -m betting_app.scripts.init_db
```

2. Wrzucenie przykładowych kursów dry-run:

```bash
python -m betting_app.scripts.scrape_odds --bookmaker dry-run
```

3. Uruchom pipeline predykcji:

```bash
python -m betting_app.scripts.run_upcoming_prediction_pipeline --operational-hybrid --min-ev 0.05
```

4. Sprawdź wyniki w froncie React na `http://localhost:3000`.

## Portfele per bukmacher i ręczne logowanie zakładów

Każdy bukmacher może mieć osobne konto/portfel:

- tabela `bookmaker_accounts` — saldo per bukmacher/konto,
- tabela `bookmaker_wallet_transactions` — wpłaty, wypłaty, stake postawiony, zwrot/wygrana,
- tabela `bets` — historia ręcznie wpisanych zakładów, kurs, stake, strona, wynik, profit.

Workflow przez REST API:

1. Utwórz portfel: `POST /api/wallets`
2. Po faktycznym ręcznym postawieniu kuponu: `POST /api/bets`
3. Rozlicz zakład: `POST /api/bets/{id}/settle`

To pozwala analizować osobno saldo i wyniki na każdym bukmacherze, a nie tylko jeden globalny bankroll.

## Finalny model z pracy inżynierskiej

W bazie rejestrowany jest finalny model pracy:

```text
Sym-Cal LR-ElasticNet-W20-Binomial / exp-039
```

Sprawdzenie artefaktów:

```bash
python -m betting_app.scripts.inspect_final_thesis_model --register
```

Ważne: obecny operacyjny predictor upcoming działa jako `Operational-PlayerTeamRatings-W20` + hybryda z rynkiem. To praktyczny fallback do codziennego użycia. Żeby mieć inference **1:1 finalnego EXP-039**, potrzebny jest jeszcze zapisany artefakt modelu sklearn/calibratora/symetryzacji (`joblib`/`pkl`) albo odtworzenie trenowania i eksport takiego artefaktu. Skrypt `inspect_final_thesis_model` zapisuje w `model_artifacts`, czy taki artefakt jest dostępny.

## Rygorystyczny benchmark modelu względem rynku

```bash
.venv/bin/python -m betting_app.ml.pipelines.evaluate_existing_model \
  --model-name Operational-PlayerTeamRatings-W20 \
  --model-version <wersja> \
  --json
```

Benchmark odrzuca predykcje bez strefy czasowej lub bez pełnego łańcucha:

```text
data_cutoff_at <= predicted_at <= quote_at < match_start_at
```

Wybiera ostatnią kwalifikującą się predykcję przed startem meczu i porównuje ją
z no-vig probability kursu dostępnego po predykcji. Raport zawiera liczność
kohorty, powody wykluczeń, log loss, Brier, AUC i ECE dla modelu oraz rynku.
To benchmark jakości predykcji, nie dowód wykonalnego ROI: symulacja bankrolla
wymaga jeszcze ledgeru rozliczającego nakładające się mecze według czasu wyniku.

## TimescaleDB / Postgres

Dodany jest serwis TimescaleDB:

```bash
docker compose up -d timescaledb
```

Domyślne zmienne w `.env.betting.example`:

```text
POSTGRES_DB=betting
POSTGRES_USER=betting
POSTGRES_PASSWORD=betting_local_password
POSTGRES_PORT=5432
```

Docelowo Timescale powinien przejąć szczególnie:

- `odds_outcome_snapshots`,
- `odds_snapshots`,
- `scrape_runs`,
- `automation_runs`,
- `bets`,
- `bookmaker_wallet_transactions`.

Na teraz traktuj Timescale jako przygotowany fundament. Pełne przełączenie aplikacji wymaga jeszcze adaptera DB i migracji Alembic, żeby nie utracić kompatybilności z istniejącym SQLite MVP.

## STS League of Legends

STS LoL prematch działa przez snapshot SBK używany przez frontend do hydratacji oferty:

```text
https://sbk.sts.pl/sbk-exporter/v1/sports/ssr
```

ID używane przez STS:

- `sport_id=156` — Esport,
- `category_id=992` — League of Legends,
- market `Zwycięzca meczu` — prematch match winner.

Pobranie i zapis do SQLite:

```bash
python -m betting_app.scripts.scrape_odds --bookmaker sts
```

Scraper pobiera pełną listę nadchodzących meczów LoL ze snapshotu i zapisuje rynek `Zwycięzca meczu`. Dla każdego meczu tworzy:

- atomowe ticki w `odds_outcome_snapshots` — do historii kursów i CLV,
- dwustronny snapshot w `odds_snapshots` — dla prostego MVP generowania sygnałów EV.

Endpoint `social-api.sts.pl/api/events` zostaje traktowany tylko jako pomocnicze źródło popularnych typów; nie jest już głównym scraperem STS.

## Model bazy dla kursów

Kanoniczny tracking kursów jest w nowych tabelach:

1. `scrape_runs` — jeden job scrapera: kiedy, z jakiego URL-a, ile rekordów widział i ile zapisał.
2. `bookmaker_events` — wydarzenie u bukmachera: bookmaker event ID, drużyny, liga, start, kategoria.
3. `bookmaker_markets` — rynek w obrębie wydarzenia: zwycięzca meczu, handicap, dokładny wynik, mapa itd.
4. `odds_outcome_snapshots` — pojedynczy tick kursu dla outcome'u z timestampem `scraped_at`.

Stara tabela `odds_snapshots` zostaje dla prostego MVP/UI, gdzie mamy pełny dwustronny rynek match-winner (`odds_a`, `odds_b`). Dla realnych API preferuj `odds_outcome_snapshots`, bo pozwala liczyć line movement i CLV per outcome.

Dla closing odds zapisujemy dwa typy linków:

- `source_url` — URL listy/API/snapshotu użyty przez scraper,
- `offer_url` — bezpośredni link do konkretnego wydarzenia u bukmachera.

Linki do ręcznego odpalenia około 5 minut przed startem:

```bash
python -m betting_app.scripts.list_close_odds_targets --bookmaker sts
python -m betting_app.scripts.list_close_odds_targets --bookmaker betclic
python -m betting_app.scripts.list_close_odds_targets --bookmaker superbet
python -m betting_app.scripts.list_close_odds_targets --bookmaker efortuna
python -m betting_app.scripts.list_close_odds_targets --bookmaker betfan
python -m betting_app.scripts.list_close_odds_targets --bookmaker totalbet
python -m betting_app.scripts.list_close_odds_targets --bookmaker lebull
```

## Superbet, eFortuna, Betfan, TOTALbet i Lebull

Superbet oraz eFortuna są obecnie obsługiwane przez NoDriver i parser widocznej strony:

```bash
python -m betting_app.scripts.scrape_odds --bookmaker superbet --headless
python -m betting_app.scripts.scrape_odds --bookmaker efortuna --headless
python -m betting_app.scripts.scrape_odds --bookmaker betfan --headless
python -m betting_app.scripts.scrape_odds --bookmaker totalbet
python -m betting_app.scripts.scrape_odds --bookmaker lebull
```

Superbet zwraca bezpośrednie linki eventów typu `/kursy/league-of-legends/...`. eFortuna generuje per-event `offer_url` z URL-a ligi i slugów drużyn. Betfan jest renderowany w SPA, więc scraper klika zakładkę `LoL` i parseruje widoczne karty. TOTALbet korzysta z publicznego API `/dealer/bdata/v1/bet/events/esport`. Lebull korzysta z API `betting-platform.prod.sbteam.xyz` z publicznym tenant headerem pobieranym z SSR.

## NoDriver

Scraper STS nie wymaga NoDriver, bo korzysta ze snapshotu SBK. NoDriver zostaje dla Betclic i ewentualnych stron, gdzie trzeba renderować DOM:

```bash
python -m betting_app.scripts.scrape_odds --bookmaker betclic --no-headless
```

Obecnie `BetclicNoDriverScraper`:

- otwiera stronę bukmachera,
- zapisuje HTML/screenshot debug do `data/betting_scraper_debug/`,
- parsuje stronę Betclic LoL i zapisuje dwustronne snapshoty match-winner,
- próbuje przypiąć bezpośredni `offer_url` do każdej oferty na podstawie linków eventów w DOM.

Jeżeli Betclic zmieni HTML, parser zostawi debug `*_body.txt`, HTML i screenshot w katalogu debug.

## GOL.GG refresher

GOL.GG jest osobnym jobem aktualizującym wyniki co 2-3 dni. Scraper jest vendored w projekcie jako
`betting_app/scrapers/golgg.py`, a job domyślnie pobiera tylko brakujące `match_id` i nie refetchuje
meczów, które są już w `data/golgg_matches.json`.

```bash
python -m betting_app.scripts.refresh_golgg_results
```

Przydatny tryb kontrolny bez zapisu:

```bash
python -m betting_app.scripts.refresh_golgg_results --dry-run
```

Domyślny kontrakt:

1. pobierz najnowsze zakończone mecze,
2. porównaj `match_id` z lokalnym `data/golgg_matches.json`,
3. zapisz metadane tylko nowych meczów,
4. pobierz nested games tylko dla nowych meczów,
5. opcjonalnie użyj `--include-incomplete-existing`, żeby uzupełnić stare niekompletne rekordy,
6. potem przelicz ratingi/W20 i zapisz `ratings_version` oraz `data_cutoff_at` dla predykcji.

Wymagane zależności: `httpx`, `parsel`, `tqdm` — są wpisane w `requirements-betting.txt`.

## Relacyjna baza GOL.GG

Duży `data/golgg_matches.json` jest źródłem/cache, ale aplikacja nie powinna go
czytać przy każdym starcie. Import do SQLite:

```bash
python -m betting_app.scripts.import_golgg_to_db
```

Test na próbce:

```bash
python -m betting_app.scripts.import_golgg_to_db --limit 100
```

Importer wypełnia:

- `golgg_matches` — jeden rekord na match,
- `golgg_games` — pojedyncze mapy/gry,
- `golgg_game_players` — występy graczy per gra/rola,
- `golgg_teams` — nazwy drużyn do mapowania bookmakerów.

Po imporcie serwisy mapowania nazw korzystają najpierw z SQLite, a JSON jest
fallbackiem.

## Baza pod inference modelu upcoming

Struktura SQLite jest przygotowana pod uruchamianie modelu dla `canonical_matches`.
Inicjalizacja i kontrola gotowości:

```bash
python -m betting_app.scripts.prepare_model_db --register-default-model
```

Najważniejsze tabele operacyjne:

- `model_artifacts` — rejestr modeli, m.in. finalny `Sym-Cal LR-ElasticNet-W20-Binomial / exp-039`,
- `rating_runs` — metadane przebudowy ratingów po GOL.GG,
- `entity_ratings` — aktualne ratingi team/player dla Elo/Glicko-2/TrueSkill/OpenSkill/etc.,
- `team_rolling_features` — rolling W20 team context z GOL.GG,
- `upcoming_match_features` — gotowy feature vector per `canonical_match_id`,
- `canonical_predictions` — predykcje modelu dla cross-bookmaker canonical match,
- `model_ev_signals` — EV modelowe po zestawieniu predykcji z najlepszymi kursami.

Docelowy workflow:

```bash
python -m betting_app.scripts.refresh_golgg_results
python -m betting_app.scripts.import_golgg_to_db
python -m betting_app.scripts.scrape_odds --bookmaker sts
python -m betting_app.scripts.scrape_odds --bookmaker betclic --headless
python -m betting_app.scripts.scrape_odds --bookmaker superbet --headless
python -m betting_app.scripts.scrape_odds --bookmaker efortuna --headless
python -m betting_app.scripts.scrape_odds --bookmaker betfan --headless
python -m betting_app.scripts.scrape_odds --bookmaker totalbet
python -m betting_app.scripts.scrape_odds --bookmaker lebull
python -m betting_app.scripts.rematch_canonical_matches --rebuild
python -m betting_app.scripts.rebuild_regional_ratings --ratings-version ratings-v2
python -m betting_app.scripts.rebuild_w20_features --feature-version w20-latest --window-size 20
python -m betting_app.scripts.run_upcoming_prediction_pipeline --operational-hybrid --min-ev 0.05
python -m betting_app.scripts.list_upcoming_model_predictions --positive-only
```

### Operacyjny kontrakt regionalny `ratings-v2`

`ratings-v2` jest pełnym, chronologicznym snapshotem sześciu systemów:
`elo`, regionalny `gl`, `ts`, `os`, `pl` i `tm`. `gl` używa
`family-calibrated-glicko2-v1`; jego niepewny offset rodziny/poziomu jest
stosowany dokładnie raz do prawdopodobieństw pięciu pozostałych systemów.
Prawdopodobieństwo `gl` nie dostaje drugiej korekty.

```bash
python -m betting_app.scripts.rebuild_regional_ratings \
  --ratings-version ratings-v2 \
  --source manual-regional-ratings-v2
python -m betting_app.scripts.rebuild_w20_features --feature-version w20-latest
python -m betting_app.scripts.run_upcoming_prediction_pipeline \
  --operational-hybrid --include-partial
```

Rebuild jest zawsze pełny. Nie uruchamiaj `rebuild_ratings` dla `ratings-v2`:
wszystkie systemy muszą odzwierciedlać identyczny kohortowy cutoff i ten sam
stan regionalnego Glicko. Zadanie `heavy_maintenance_cycle` wykonuje kolejno
odświeżenie GOL.GG, `rebuild_regional_ratings` oraz W20; zwykły
`prediction_pipeline` następnie tworzy features, predykcje operacyjne
`Operational-PlayerTeamRatings-W20 / v0.4-binom-series`, hybrydę rynku i
sygnały EV. Najpierw obliczane jest prawdopodobieństwo pojedynczej mapy, a
następnie dla `Bo1`, `Bo3`, `Bo5` i `Bo7` konwertowane binomialnym ogonem do
prawdopodobieństwa całej serii. Przycisk **Predict** w widoku meczu używa tego
samego modelu i respektuje ręcznie zatwierdzony skład.

EXP-039 (`Sym-Cal LR-ElasticNet-W20-Binomial`) pozostaje zamrożonym,
nieoperacyjnym baseline'em wyłącznie do porównań; nie jest już wybierany przez
interaktywną ani schedulerową ścieżkę predykcji. Żaden z tych kroków nie składa
zakładów automatycznie.

### Chronologiczne porównanie modeli

Po przebudowie ratingów i W20 można odtworzyć nowy model dla wszystkich
zmapowanych zakończonych meczów:

```bash
python -m betting_app.scripts.backfill_operational_predictions --apply
```

Backfill zapisuje osobny, niemutowalny wariant
`v0.4-binom-series-chronological-v1`. Każda data jest najpierw przewidywana z
ratingów i W20 z wcześniejszych pełnych dat, a dopiero potem aktualizowana;
wyniki wymagają `data_cutoff_at <= predicted_at < match_start_at`. Widok
**Model Analysis** pokazuje metryki EXP-039 i regionalnego replaya na ich
wspólnej kohorcie. To porównanie jakości modelu na etykietach historycznych,
nie dowód live forecastingu, CLV, ROI ani wykonania finansowego.

### Evidence and limitation

EXP-076 applies the shared uncertain family/tier offset to Player Elo,
TrueSkill, OpenSkill, Plackett-Luce and Thurstone-Mosteller only when both
sides have a prior domestic affiliation. Player Glicko is the regional
calibrated system; domestic same-family games receive no additional
probability offset.

```bash
python scripts/06_metamodel/06ak_multirating_family_symcal.py \
  --data-dir data \
  --output-dir reports/experiments/exp076_multirating_family_symcal
```

The 2024+ diagnostic result (`n=4311`) reduced LogLoss from `0.581427` to
`0.576200`, but its paired 95% CI was `[-0.013174, +0.000072]`; it does not
meet the global two-sided significance criterion. Cross-league rows (`n=526`)
improved from `0.593362` to `0.533148`, while domestic rows were weaker.
`ratings-v2` is therefore an explicitly versioned operational research
baseline, not evidence of financially executable performance or a replacement
for the frozen thesis result.

Skrócony runner:

```bash
# lekki tryb: scrape bukmacherów -> canonical matching -> features -> predykcje -> EV
# uruchamiaj ręcznie albo schedulerem co 1-2h, nie co kilka minut
python -m betting_app.scripts.run_daily_automation --operational-hybrid --min-ev 0.05

# samo przeliczenie predykcji/EV bez nowych requestów do bukmacherów
python -m betting_app.scripts.run_upcoming_prediction_pipeline --operational-hybrid --min-ev 0.05

# cięższy tryb po odświeżeniu zakończonych meczów GOL.GG
python -m betting_app.scripts.run_daily_automation \
  --refresh-golgg --reimport-golgg --rebuild-ratings --rebuild-w20 \
  --operational-hybrid --min-ev 0.05
```

## Zasada parserów HTML

Jeżeli scraper pracuje na HTML/DOM snapshotcie, ekstrakcja elementów powinna iść
przez `parsel.Selector`, a nie przez regex po HTML. Regex zostaje tylko do
parsowania tekstu liniowego (`document.body.innerText`), ID ze znanego URL-a albo
prostych etykiet/kursów.

## Ważne założenia finansowe

- EV liczone jest jako `p * odds * (1 - tax_rate) - 1`.
- Domyślny podatek: `12%`.
- Domyślny minimalny EV: `5%`.
- Domyślny suggested stake: Kelly 0.05 z limitami min/max.
- Wyniki są diagnostyczne; aplikacja nie dowodzi realnej przewagi bukmacherskiej.

## Zmienne środowiskowe

- `BETTING_APP_DB` — ścieżka do SQLite DB.
- `BETTING_APP_DEBUG_DIR` — katalog debug HTML/screenshot.
- `BETTING_APP_TAX_RATE` — domyślnie `0.12`.
- `BETTING_APP_MIN_EV` — domyślnie `0.05`.
- `BETTING_APP_BANKROLL` — domyślnie `100.0`.
- `BETTING_APP_HEADLESS` — `1`/`0` dla NoDriver.
