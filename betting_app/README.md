# LoL Betting Manager

Lokalna aplikacja do ręcznej bukmacherki/analityki LoL. Aplikacja **nie stawia zakładów automatycznie** — służy do zbierania kursów, mapowania drużyn, liczenia EV, zapisywania decyzji i późniejszej analizy bankrolla/CLV.

## Status

MVP v0.1 na branchu `private/betting-playground`:

- SQLite schema i lokalna baza `data/betting_app.sqlite3`,
- główny ekran **LoL Odds Hub**: nadchodzące mecze, max/średnie kursy A/B, arbitraż, model, hybryda i karta szczegółów meczu,
- ręczne dodawanie snapshotów kursów i predykcji jako tryb pomocniczy,
- generowanie sygnałów EV+ jako diagnostyka, nie główny widok,
- manualny bet tracker,
- osobne portfele/konta per bukmacher i historia transakcji,
- rozliczanie zakładów i bankroll events,
- panel mapowania nazw drużyn,
- znormalizowany tracking kursów: `scrape_runs` → `bookmaker_events` → `bookmaker_markets` → `odds_outcome_snapshots`,
- scraper STS League of Legends prematch przez `sbk-exporter/v1/sports/ssr`,
- scrapery NoDriver/API dla Betclic, Superbet, eFortuna, Betfan, TOTALbet i Lebull.

## Uruchomienie

Z katalogu repozytorium:

```bash
python -m betting_app.scripts.init_db
streamlit run betting_app/app.py
```

Najważniejszy ekran do bieżącej pracy to **strona główna** `betting_app/app.py` / **LoL Odds Hub**:

- pokazuje listę najbliższych meczów,
- dla każdego meczu pokazuje `max kurs A`, `max kurs B`, średnie kursy, liczbę bukmacherów i arbitraż brutto/po podatku,
- po kliknięciu/wybraniu meczu pokazuje kartę: kursy u bukmacherów, linki do ofert, prawdopodobieństwa modelu i hybrydy, EV oraz składy z ostatniego meczu GOL.GG.

Pozostałe ekrany multipage:

- `07_model_opportunities.py` / **Wycena upcoming meczów LoL** — pokazuje status danych, predykcje modelu i hybrydy, best odds po obu stronach, średnie kursy, EV po podatku 12%, liczbę bukmacherów, linki do ofert oraz diagnostykę rosterów użytych z ostatniego meczu GOL.GG.
- `08_system_status.py` / **System status** — pokazuje czy automat działa bez SSH: ostatnie cykle schedulera, komendy, błędy, ostatni scrape per bookmaker, liczność tabel, backup SQLite i przyciski do ręcznego przeliczenia pipeline’u.
- `03_bets.py` / **Bets / portfele bukmacherów** — konta/portfele per bukmacher, wpłaty/wypłaty/korekty, ręczne wpisanie zakładu z kursem i późniejsze rozliczenie.

Jeżeli `streamlit` nie jest zainstalowany:

```bash
pip install streamlit
```

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
   - Strona główna Streamlit `app.py` jest agregatorem kursów: upcoming matches, max/avg odds, arbitraż i karta meczu.
   - Streamlit `07_model_opportunities.py` pozostaje bardziej technicznym widokiem opportunities/EV.
   - Streamlit `03_bets.py` trzyma portfele per bukmacher oraz ręcznie wpisane zakłady.

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
python -m betting_app.scripts.run_upcoming_prediction_pipeline --hybrid --min-ev 0.05
```

Close odds najlepiej robić selektywnie: najpierw panel wskazuje ciekawe EV+, potem otwierasz `offer_url` albo odpalasz pojedynczy scraper przed startem. Nie ma potrzeby agresywnie odpytywać wszystkich bukmacherów co kilka minut.

## Docker Compose / najprostsze przenoszenie

Dodane są pliki:

- `Dockerfile.betting` — obraz Python 3.12 + Chromium + zależności scraperów/modelu,
- `requirements-betting.txt` — zależności aplikacji bettingowej,
- `docker-compose.yml` — aplikacja Streamlit, lekki scheduler i opcjonalny heavy maintenance,
- `.dockerignore` — mniejszy kontekst buildu.

Najprostszy start:

```bash
docker compose up --build -d betting-app betting-scheduler
```

Panel będzie dostępny na:

```text
http://localhost:8501
```

Jeżeli laptop stoi w rogu pokoju i chcesz patrzeć z innego urządzenia w tej samej sieci, wejdź na:

```text
http://IP_LAPTOPA:8501
```

Adres IP sprawdzisz jednorazowo np. przez `ip addr` / ustawienia routera. Streamlit w kontenerze słucha na `0.0.0.0`, więc UI jest dostępne w LAN, o ile firewall laptopa nie blokuje portu 8501.

Co robią kontenery:

- `betting-app` — Streamlit UI,
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
  python -m betting_app.scripts.run_upcoming_prediction_pipeline --hybrid --min-ev 0.05
```

Ciężki maintenance z GOL.GG korzysta teraz z lokalnego scrapera `betting_app/scrapers/golgg.py`:

```bash
docker compose --profile maintenance run --rm betting-maintenance
```

Zmienna `EMBEDDED_RIFT_ESPORT_DIR` może jeszcze występować w starych komendach dla kompatybilności, ale `refresh_golgg_results` jej już nie potrzebuje.

Zmienne środowiskowe:

```text
BETTING_APP_PORT=8501
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
docker compose up --build -d betting-app betting-scheduler
```

3. Upewniasz się, że Docker startuje po restarcie systemu:

```bash
sudo systemctl enable docker
```

4. Od tej pory kontenery mają `restart: unless-stopped`, więc po restarcie laptopa Docker powinien sam podnieść UI i scheduler.
5. Bez SSH korzystasz głównie z paneli:
   - **Wycena upcoming meczów LoL** — wyniki, EV, best odds, linki do ofert,
   - **System status** — czy scheduler żyje, ostatnie błędy, ostatnie scrape’y, backup i ręczne przyciski.

Scheduler zapisuje swoje cykle do tabel:

- `automation_runs`,
- `automation_commands`.

Dzięki temu nie trzeba czytać logów Dockera, żeby zobaczyć czy automat działa. Logi Dockera zostają tylko jako awaryjna diagnostyka.

Backup lokalnej bazy:

```bash
python -m betting_app.scripts.backup_sqlite
```

W UI jest też przycisk **Backup SQLite**. Backupy trafiają do:

```text
data/backups/
```

Rekomendowany praktyczny model:

- lekki scheduler działa sam co 2h,
- GOL.GG / ratingi / W20 robisz co 2–3 dni przez maintenance,
- close odds odpalasz selektywnie z panelu przy interesujących EV+,
- wyniki oglądasz w Streamlit, nie w terminalu.

## Testowy flow bez bukmachera

1. Inicjalizacja bazy:

```bash
python -m betting_app.scripts.init_db
```

2. Wrzucenie przykładowych kursów dry-run:

```bash
python -m betting_app.scripts.scrape_odds --bookmaker dry-run
```

3. W Streamlit, na stronie `Opportunities`, dodaj ręcznie predykcję dla meczu.

4. Kliknij `Przelicz sygnały EV+`.

5. Jeżeli EV przekroczy próg, oznacz sygnał jako postawiony.

6. Na stronie `Bets` rozlicz zakład jako `won/lost/void/cancelled`.

## Portfele per bukmacher i ręczne logowanie zakładów

Każdy bukmacher może mieć osobne konto/portfel:

- tabela `bookmaker_accounts` — saldo per bukmacher/konto,
- tabela `bookmaker_wallet_transactions` — wpłaty, wypłaty, stake postawiony, zwrot/wygrana,
- tabela `bets` — historia ręcznie wpisanych zakładów, kurs, stake, strona, wynik, profit.

Workflow:

1. Wejdź w Streamlit → **Bets / portfele bukmacherów**.
2. Dodaj portfel, np. `STS / main`, `Betclic / main`, `Superbet / main`.
3. Po faktycznym ręcznym postawieniu kuponu wpisz:
   - portfel,
   - mecz,
   - stronę `a/b`,
   - stake,
   - rzeczywisty kurs,
   - opcjonalnie wybierz sygnał modelu/EV z listy.
4. Aplikacja odejmie stake z konkretnego portfela.
5. Po wyniku rozliczasz zakład jako `won/lost/void/cancelled`; przy wygranej aplikacja dolicza payout po podatku 12%.

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
4. `odds_outcome_snapshots` — pojedynczy tick kursu dla outcome’u z timestampem `scraped_at`.

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
python -m betting_app.scripts.rebuild_ratings --ratings-version latest-full
python -m betting_app.scripts.rebuild_w20_features --feature-version w20-latest --window-size 20
python -m betting_app.scripts.run_upcoming_prediction_pipeline --hybrid --min-ev 0.05
python -m betting_app.scripts.list_upcoming_model_predictions --positive-only
```

Skrócony runner:

```bash
# lekki tryb: scrape bukmacherów -> canonical matching -> features -> predykcje -> EV
# uruchamiaj ręcznie albo schedulerem co 1-2h, nie co kilka minut
python -m betting_app.scripts.run_daily_automation --hybrid --min-ev 0.05

# samo przeliczenie predykcji/EV bez nowych requestów do bukmacherów
python -m betting_app.scripts.run_upcoming_prediction_pipeline --hybrid --min-ev 0.05

# cięższy tryb po odświeżeniu zakończonych meczów GOL.GG
python -m betting_app.scripts.run_daily_automation \
  --refresh-golgg --reimport-golgg --rebuild-ratings --rebuild-w20 --min-ev 0.05
```

Po pipeline uruchom panel:

```bash
streamlit run betting_app/app.py
```

W zakładce **Wycena upcoming meczów LoL** można też odpalić lekki pipeline z UI (`skip scrape` domyślnie włączone) i filtrować opportunities po minimalnym EV oraz liczbie bukmacherów.

Przebudowa ratingów mirroruje historyczny pipeline
`scripts/05_ratingi_baseline/03_generate_ratings.py`: chronologiczny przebieg po
GOL.GG, aktualizacja dopiero po grze/meczu, systemy `elo`, `gl` (Glicko-2), `ts`,
`os`, `pl`, `tm`, osobno dla teamów i graczy. Wyniki trafiają do `rating_runs` i
`entity_ratings`.

Smoke test ratingów:

```bash
python -m betting_app.scripts.rebuild_ratings --limit 100 --ratings-version smoke-ratings
```

Przebudowa W20:

```bash
python -m betting_app.scripts.rebuild_w20_features --feature-version w20-latest --window-size 20
```

W20 zapisuje najnowszy leakage-safe kontekst drużynowy do `team_rolling_features`:
`win_rate`, `kills`, `deaths`, `gd15`, `dpm`, `vspm`, `towers`, `dragons`,
`nashors`, `gold`, `duration` oraz pełny `features_json` z `team_id` i
`last_match_at`.

Automatyczna predykcja upcoming:

```bash
python -m betting_app.scripts.build_upcoming_features
python -m betting_app.scripts.predict_upcoming_matches
python -m betting_app.scripts.generate_hybrid_predictions --alpha 0.50 --temperature 0.80
python -m betting_app.scripts.generate_model_ev_signals --min-ev 0.05
python -m betting_app.scripts.list_upcoming_model_predictions --positive-only
```

Na tym etapie model automatyczny `Operational-PlayerTeamRatings-W20/v0.2` używa
player-based ratingów, team-level ratingów i W20. Ponieważ bukmacherzy nie
podają pewnych składów, roster upcoming jest aproksymowany ostatnim zaobserwowanym
składem tej drużyny w GOL.GG. Nie jest to jeszcze finalny Sym-Cal z pracy, ale
jest już w pełni automatyczny i diagnostyka źródła rosteru/braków trafia do
`upcoming_match_features.features_json`.

Hybryda model--rynek jest zgodna z ideą z eksperymentów EXP-032/033/041:

```text
p_hybrid = alpha * temperature(p_model, T) + (1 - alpha) * p_market
```

gdzie `p_market` to średnia no-vig probability z aktualnych kursów bukmacherów.
Domyślnie używamy kompromisu `alpha=0.50`, `T=0.80`, który w historycznych
eksperymentach dawał bardzo dobry LogLoss; dla maksymalizacji LogLoss testowany
był też obszar `alpha≈0.60--0.80`, `T=0.80`.

Kontrola, czy artefakty modelu z pracy nadal reprodukują metryki EXP-039:

```bash
python -m betting_app.scripts.validate_thesis_model
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
