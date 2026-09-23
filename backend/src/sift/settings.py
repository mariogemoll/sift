"""Configuration, read from the environment once per process."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every knob the service reads, with defaults that work on a laptop."""

    model_config = SettingsConfigDict(env_prefix="SIFT_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://sift:sift@localhost:5433/sift"
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)

    passphrase_hash: str = ""
    """scrypt hash of the one passphrase that opens the interface.

    Empty means no passphrase was configured, and the interface is closed rather
    than open: a deploy that loses the secret locks you out instead of letting
    everyone in. `sift passphrase` mints the value.
    """

    session_hours: int = 12
    """How long a session cookie stays valid. Fixed, not extended by activity."""

    cookie_secure: bool = False
    """Mark the session cookie Secure. False for plain-HTTP localhost; true in
    production, where the browser reaches the edge over HTTPS."""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
