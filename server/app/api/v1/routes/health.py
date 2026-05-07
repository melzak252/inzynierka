"""Healthcheck endpoints for the API and database."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.health import HealthResponse


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def healthcheck(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Return basic application health status.

    Args:
        settings: Application configuration loaded from environment variables.

    Returns:
        A health response with service metadata.
    """
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
        database="not_checked",
    )


@router.get("/health/db", response_model=HealthResponse)
def database_healthcheck(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Return database connectivity health status.

    Args:
        db: SQLAlchemy database session.
        settings: Application configuration loaded from environment variables.

    Returns:
        A health response after executing a lightweight SQL query.
    """
    db.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
        database="ok",
    )
