"""The FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sift.api.routes import health, papers
from sift.settings import Settings, get_settings
from sift.storage.engine import create_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an app bound to `settings`, defaulting to the environment.

    Taking settings as an argument is what lets a test point the same app at a
    throwaway database.
    """
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(resolved.database_url)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="sift",
        version="0.1.0",
        summary="Rank documents against weighted criteria",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(papers.router)
    return app


app = create_app()
