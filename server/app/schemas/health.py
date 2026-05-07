"""Healthcheck response schemas."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Healthcheck response payload."""

    status: str
    service: str
    environment: str
    database: str
