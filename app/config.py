"""
config.py — Application configuration for the CAO 48.1 Compliance API.

Uses Pydantic Settings to load configuration from environment variables
with sensible defaults for local development.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Attributes:
        app_name: Display name of the API.
        app_version: Semantic version string (shown in /health and OpenAPI spec).
        environment: Runtime environment — 'development' skips proxy secret validation.
        rapidapi_proxy_secret: The secret from the RapidAPI Provider Dashboard.
            Validated on every request in production.
        log_level: Python logging level.
        host: Bind address for uvicorn.
        port: Bind port for uvicorn.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "CAO 48.1 Compliance API"
    app_version: str = "0.7.0"
    environment: str = "development"  # "development" | "production"

    # RapidAPI integration
    rapidapi_proxy_secret: str = ""

    # Server
    log_level: str = "info"
    host: str = "0.0.0.0"
    port: int = 8000


# Singleton instance — import this throughout the app
settings = Settings()
