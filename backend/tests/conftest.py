"""Test fixtures.

The API tests run against a real Postgres, migrated by the real `alembic
upgrade head`. An ORM-metadata shortcut would leave the migrations untested,
which is the one thing about the schema that can silently rot.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from arxiv_fake import FakeArxiv
from sift.api.app import create_app
from sift.auth.passphrase import hash_passphrase
from sift.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


class TestSettings(BaseSettings):
    """Where the suite may create, drop and migrate its database.

    Read from `SIFT_TEST_DATABASE_URL` or from `.env`, so that two checkouts
    running the suite at once can each be pointed at a database of their own —
    the session fixture drops whatever it finds there.
    """

    __test__ = False
    model_config = SettingsConfigDict(
        env_prefix="SIFT_TEST_", env_file=ROOT / ".env", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://sift:sift@localhost:5433/sift_test"


PASSPHRASE = "the test passphrase"
# Hashed once for the whole session, with a fixed salt: scrypt is deliberately
# slow, and paying for it per test would be paying for nothing.
PASSPHRASE_HASH = hash_passphrase(PASSPHRASE, b"a fixed 16 bytes")


def _admin_dsn(url: str) -> tuple[str, str]:
    """Split an asyncpg SQLAlchemy URL into a server DSN and the database name."""
    plain = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    server, _, database = plain.rpartition("/")
    return f"{server}/postgres", database


async def _recreate(url: str) -> None:
    admin, database = _admin_dsn(url)
    try:
        connection = await asyncpg.connect(admin)
    except (OSError, asyncpg.PostgresError) as error:  # pragma: no cover - setup path
        raise RuntimeError(
            f"cannot reach Postgres at {admin}: {error}\nStart it with `docker compose up -d db`."
        ) from error
    try:
        await connection.execute(f'drop database if exists "{database}" with (force)')
        await connection.execute(f'create database "{database}"')
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A freshly created, freshly migrated database for the whole session."""
    url = TestSettings().database_url
    asyncio.run(_recreate(url))
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "SIFT_DATABASE_URL": url},
        check=True,
        capture_output=True,
    )
    yield url


@pytest.fixture
def passphrase() -> str:
    return PASSPHRASE


@pytest.fixture
def passphrase_hash() -> str:
    """What the app holds, for tests that need to forge or age a cookie."""
    return PASSPHRASE_HASH


WISHLIST = ROOT / "tests" / "wishlist.toml"


def _settings(database_url: str, passphrase_hash: str) -> Settings:
    # No background workers: tests drive every stage one step at a time. No pacing
    # either; the pacer has tests of its own.
    return Settings(
        database_url=database_url,
        passphrase_hash=passphrase_hash,
        worker=False,
        profile_path=WISHLIST,
        asker="fake",
        arxiv_interval_seconds=0.0,
    )


@pytest.fixture
def settings(database_url: str) -> Settings:
    return _settings(database_url, PASSPHRASE_HASH)


@pytest.fixture
def arxiv() -> FakeArxiv:
    return FakeArxiv()


@pytest.fixture
def app(settings: Settings, arxiv: FakeArxiv) -> FastAPI:
    return create_app(settings, transport=httpx.MockTransport(arxiv.handle))


@asynccontextmanager
async def _serving(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client over `app`, with lifespan run so the engine exists."""
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


@pytest.fixture
async def anonymous(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """A client carrying no session cookie."""
    async with _serving(app) as http:
        yield http


@pytest.fixture
async def client(anonymous: AsyncClient, passphrase: str) -> AsyncClient:
    """The same client, signed in — what a browser holds after the login page."""
    response = await anonymous.post("/auth/session", json={"passphrase": passphrase})
    assert response.status_code == 200
    return anonymous


@pytest.fixture
async def closed(database_url: str) -> AsyncIterator[AsyncClient]:
    """A client for a deployment with no passphrase configured.

    The hash is blanked explicitly, so a developer's own .env cannot turn the
    fail-closed case into the configured one.
    """
    async with _serving(create_app(_settings(database_url, ""))) as http:
        yield http


@pytest.fixture
async def session(app: FastAPI, anonymous: AsyncClient) -> AsyncIterator[AsyncSession]:
    """A session on the same database the app is using, for arranging rows."""
    factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with factory() as opened:
        yield opened


@pytest.fixture(autouse=True)
async def clean_tables(database_url: str) -> AsyncIterator[None]:
    """Every test starts from an empty database."""
    yield
    _, database = _admin_dsn(database_url)
    plain = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(plain)
    try:
        await connection.execute(
            "truncate table verdicts, judgments, paper_texts, batch_items, batches, papers"
            " restart identity cascade"
        )
    finally:
        await connection.close()
