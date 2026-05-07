# EnsembleLegends Server

Backend API dla aplikacji predykcji meczów League of Legends.

## Stack

- FastAPI
- SQLAlchemy
- PostgreSQL
- Pydantic Settings

## Lokalnie przez Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up --build
```

API będzie dostępne pod adresem:

- `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- Healthcheck: `http://localhost:8000/api/v1/health`
