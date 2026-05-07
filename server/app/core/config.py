"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the FastAPI application.

    Attributes:
        app_name: Human-readable application name.
        environment: Runtime environment name.
        api_v1_prefix: Prefix for versioned API routes.
        cors_origins: Comma-separated list of allowed CORS origins.
        database_url: SQLAlchemy-compatible PostgreSQL connection string.
    """

    app_name: str = "EnsembleLegends API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description="Comma-separated allowed CORS origins.",
    )
    database_url: str = Field(
        default="postgresql+psycopg://ensemblelegends:ensemblelegends_dev_password@localhost:5432/ensemblelegends",
        description="SQLAlchemy-compatible database URL.",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """Return configured CORS origins as a normalized list.

        Returns:
            A list of non-empty origin strings.
        """
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings.

    Returns:
        Settings instance loaded from environment variables.
    """
    return Settings()
