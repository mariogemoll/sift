"""Configuration, read from the environment once per process."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every knob the service reads, with defaults that work on a laptop."""

    model_config = SettingsConfigDict(env_prefix="SIFT_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://sift:sift@localhost:5433/sift"
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
