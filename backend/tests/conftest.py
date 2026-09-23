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
from pathlib import Path

import asyncpg
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sift.api.app import create_app
from sift.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "postgresql+asyncpg://sift:sift@localhost:5433/sift_test"


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
    url = os.environ.get("SIFT_TEST_DATABASE_URL", DEFAULT_URL)
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
def settings(database_url: str) -> Settings:
    return Settings(database_url=database_url)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client over the app, with lifespan run so the engine exists."""
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


@pytest.fixture
async def session(app: FastAPI, client: AsyncClient) -> AsyncIterator[AsyncSession]:
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
        await connection.execute("truncate table papers restart identity cascade")
    finally:
        await connection.close()
