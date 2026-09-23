"""Configuration, read from the environment once per process."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
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

    worker: bool = True
    """Run a harvest worker inside the API process. Every process that runs one
    takes part; they coordinate through the database, not with each other."""

    lease_seconds: float = 120.0
    """How long a worker may hold a batch without recording progress. Must outlast
    one announcement request, HTTP timeout included."""

    idle_poll_seconds: float = 2.0
    """How often an idle worker looks for work."""

    arxiv_interval_seconds: float = 3.0
    """The least gap between the end of one request to arXiv and the start of the
    next, announcements and PDFs alike. arXiv asks for three seconds. The pacer
    that keeps it is per process, so running several processes divides it."""

    profile_path: Path = Path("wishlist.toml")
    """The wishlist papers are screened and ranked against."""

    asker: Literal["fake", "typesafe"] = "fake"
    """Who answers the questions. `fake` is deterministic and needs no key."""

    typesafe_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("SIFT_TYPESAFE_API_KEY", "TYPESAFE_API_KEY")
    )
    typesafe_model: str = "jev-1.13.0"
    """A pinned version rather than an alias, because it keys the judgment cache."""
    typesafe_timeout_seconds: float = 60.0

    download: bool | None = None
    """Fetch PDFs from arXiv for papers that pass the screen. Unset, only when a
    real model will read them: the fake asker's answers ignore the text, so with
    it a download would put load on arXiv for nothing."""

    screen_workers: int = Field(default=8, ge=0)
    """Concurrent screens per process: the model budget for abstracts."""
    fetch_workers: int = Field(default=2, ge=0)
    """More than one only overlaps extraction with the next download; the arXiv
    pacer still lets one request go at a time."""
    judge_workers: int = Field(default=4, ge=0)
    """Concurrent full-text judgments per process."""

    item_lease_seconds: float = 300.0
    """How long a stage may hold an item. Must outlast a PDF download's deadline
    plus the wait for the pacer behind the other fetch workers."""

    pdf_max_bytes: int = 50 * 1024 * 1024
    pdf_deadline_seconds: float = 120.0
    """For the whole download, however slowly the server sends it."""

    judge_max_chars: int = 48_000
    """How much of a paper's text, references removed, the full judgment reads.
    About 12k tokens, well inside the model's 32k for state and question."""


def downloads(settings: Settings) -> bool:
    return settings.download if settings.download is not None else settings.asker != "fake"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
