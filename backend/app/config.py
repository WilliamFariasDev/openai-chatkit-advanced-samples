"""Configuration settings for the application."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str | None = None

    # OpenAI
    openai_api_key: str
    default_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None

    # Server
    port: int = 8000
    host: str = "0.0.0.0"
    environment: str = "development"

    # Admin
    admin_api_key: str | None = None


settings = Settings()
