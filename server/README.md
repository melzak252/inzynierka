# EnsembleLegends Server

Backend aplikacji predykcji meczów League of Legends. Na start renderuje prosty interfejs
Jinja2 + HTMX, a równolegle utrzymuje API FastAPI pod przyszłe integracje.

## Stack

- FastAPI
- Jinja2
- HTMX
- SQLAlchemy
- PostgreSQL
- Pydantic Settings

## Lokalnie przez Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Backend będzie dostępny pod adresem:

- Widok aplikacji: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- Healthcheck: `http://localhost:8000/api/v1/health`
