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
| `server/` | Backend FastAPI, widoki Jinja2 + HTMX, API predykcji i dostęp do PostgreSQL. |
| `frontend/` | Odłożony scaffold React + TypeScript + Vite, do ewentualnego powrotu po prototypie HTMX. |
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

### Aplikacja webowa

Startowy stos aplikacyjny składa się z PostgreSQL oraz backendu FastAPI renderującego widoki Jinja2 + HTMX. Najprostsze uruchomienie lokalne:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Usługi:

- Aplikacja Jinja2 + HTMX: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- PostgreSQL: `localhost:5432`

Szybka weryfikacja API:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health
Invoke-RestMethod http://localhost:8000/api/v1/health/db
Invoke-WebRequest http://localhost:8000
```

### Skrypty badawcze

Projekt powinien być uruchamiany z aktywnego środowiska wirtualnego i z katalogu głównego repozytorium:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\03_dane_pipeline\00_profile_datasets_for_whitepaper.py
```

## Uwagi organizacyjne

- Nowy kod wielokrotnego użytku powinien trafiać do `src/`.
- Jednorazowe eksperymenty i generatory artefaktów powinny trafiać do odpowiedniego folderu w `scripts/`.
- Dane powinny pozostawać lokalnie w `data/`, a nie w katalogu głównym projektu.
