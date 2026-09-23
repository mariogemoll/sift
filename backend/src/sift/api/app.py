"""The FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sift.api import gate
from sift.api.routes import auth, batches, health, papers
from sift.settings import Settings, get_settings
from sift.storage.engine import create_engine, create_session_factory

logger = logging.getLogger(__name__)


# arXiv asks API clients to identify themselves.
USER_AGENT = "sift/0.1"


def create_app(
    settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    """Build an app bound to `settings`, defaulting to the environment.

    Taking settings as an argument is what lets a test point the same app at a
    throwaway database; `transport`, when given, carries every outgoing request,
    so a test can stand in for arXiv.
    """
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(resolved.database_url)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(30.0),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as http:
            app.state.http = http
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
    app.state.gate = gate.build(resolved)
    if not gate.configured(app.state.gate):
        logger.warning(
            "No usable SIFT_PASSPHRASE_HASH: the interface is closed to everyone. "
            "Mint one with `sift passphrase`."
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # /health is open because the load balancer polls it and it reveals nothing.
    # Everything that reads data names the guard, so a new router has to decide.
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(papers.router, dependencies=[Depends(gate.guard)])
    app.include_router(batches.router, dependencies=[Depends(gate.guard)])
    return app


app = create_app()
