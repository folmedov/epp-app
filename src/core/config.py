"""Core configuration for the EEPP ingestion project.

Provides a small Pydantic v2 settings container that loads environment
variables and centralizes config values used across the app.
"""
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Application configuration loaded from environment.

    Fields are named in UPPER_SNAKE_CASE to match environment variable
    conventions. Defaults are safe for local development.
    """

    DATABASE_URL: str = Field(..., description="Postgres DSN (asyncpg compatible)")
    APP_ENV: str = Field("development", description="Application environment")
    LOG_LEVEL: str = Field("INFO", description="Logging level")

    # Scraper Settings
    SCRAPER_TIMEOUT: int = Field(30, description="Timeout for API calls in seconds")
    SCRAPER_MAX_RETRIES: int = Field(3, description="Max retries for failed requests")

    # PocketBase (Optional/Legacy support)
    PB_URL: Optional[str] = Field(None, description="PocketBase API URL")
    PB_TOKEN: Optional[str] = Field(None, description="PocketBase Admin Token")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

settings = Config()

__all__ = ["Config", "settings"]
