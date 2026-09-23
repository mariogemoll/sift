"""The FastAPI application factory."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta

import httpx
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sift.api import gate
from sift.api.routes import auth, batches, health, papers, profile
from sift.core.retry import RetryPolicy
from sift.core.types import Stage
from sift.ingest.pacing import Pacer
from sift.ingest.pdf import Limits
from sift.judge import Asker, FakeAsker
from sift.pipeline import wishlist
from sift.pipeline.harvest import Harvest, run_harvester
from sift.pipeline.stages import Work, run_stage
from sift.settings import Settings, downloads, get_settings
from sift.storage.engine import create_engine, create_session_factory

logger = logging.getLogger(__name__)


# arXiv asks API clients to identify themselves.
USER_AGENT = "sift/0.1"


async def _asker(settings: Settings, stack: AsyncExitStack) -> Asker:
    if settings.asker == "fake":
        return FakeAsker()
    # Imported here so the fake needs nothing from the SDK.
    from sift.judge import typesafe

    if settings.typesafe_api_key is None:
        raise RuntimeError("SIFT_ASKER=typesafe needs TYPESAFE_API_KEY")
    sdk = await stack.enter_async_context(
        typesafe.client(
            settings.typesafe_api_key.get_secret_value(),
            timeout=settings.typesafe_timeout_seconds,
        )
    )
    return typesafe.TypeSafeAsker(sdk, settings.typesafe_model)


def _stage_workers(settings: Settings) -> dict[Stage, int]:
    return {
        "screen": settings.screen_workers,
        "fetch": settings.fetch_workers,
        "judge": settings.judge_workers,
    }


def create_app(
    settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    """Build an app bound to `settings`, defaulting to the environment.

    Taking settings as an argument is what lets a test point the same app at a
    throwaway database; `transport`, when given, carries every outgoing request,
    so a test can stand in for arXiv.
    """
    resolved = settings or get_settings()
    # Read up front, so a broken wishlist stops the service from starting at all.
    ranked_against = wishlist.load(resolved.profile_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(resolved.database_url)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        async with AsyncExitStack() as stack:
            http = await stack.enter_async_context(
                httpx.AsyncClient(
                    transport=transport,
                    timeout=httpx.Timeout(30.0),
                    headers={"User-Agent": USER_AGENT},
                    follow_redirects=True,
                )
            )
            app.state.http = http
            arxiv = Pacer(resolved.arxiv_interval_seconds)
            app.state.arxiv = arxiv
            work = Work(
                factory=app.state.session_factory,
                http=http,
                arxiv=arxiv,
                limits=Limits(
                    max_bytes=resolved.pdf_max_bytes, deadline=resolved.pdf_deadline_seconds
                ),
                asker=await _asker(resolved, stack),
                profile=ranked_against,
                max_chars=resolved.judge_max_chars,
                lease=timedelta(seconds=resolved.item_lease_seconds),
                policy=RetryPolicy(),
                download=downloads(resolved),
            )
            app.state.work = work
            harvest = Harvest(
                factory=app.state.session_factory,
                http=http,
                arxiv=arxiv,
                lease=timedelta(seconds=resolved.lease_seconds),
                policy=RetryPolicy(),
            )
            app.state.harvest = harvest
            stop = asyncio.Event()
            idle = timedelta(seconds=resolved.idle_poll_seconds)
            tasks = (
                [
                    asyncio.create_task(run_harvester(harvest, stop, idle), name="harvest worker"),
                    *(
                        asyncio.create_task(
                            run_stage(work, stage, stop, idle), name=f"{stage} worker {n}"
                        )
                        for stage, count in _stage_workers(resolved).items()
                        for n in range(count)
                    ),
                ]
                if resolved.worker
                else []
            )
            try:
                yield
            finally:
                stop.set()
                await asyncio.gather(*tasks)
                await engine.dispose()

    app = FastAPI(
        title="sift",
        version="0.1.0",
        summary="Rank documents against weighted criteria",
        lifespan=lifespan,
    )
    app.state.gate = gate.build(resolved)
    app.state.profile = ranked_against
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
    app.include_router(profile.router, dependencies=[Depends(gate.guard)])
    return app


app = create_app()
