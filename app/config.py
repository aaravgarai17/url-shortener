from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    base_url: str = "http://localhost:8000"
    environment: str = "development"

    database_url: str = "postgresql+psycopg2://shortener:shortener@localhost:5432/shortener"
    redis_url: str = "redis://localhost:6379/0"

    cache_ttl_seconds: int = 3600

    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
