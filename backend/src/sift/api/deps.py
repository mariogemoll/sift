"""Request-scoped dependencies, resolved from state the app factory built."""

from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sift.judging.judgments import Profile


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


def get_http(request: Request) -> httpx.AsyncClient:
    http: httpx.AsyncClient = request.app.state.http
    return http


Http = Annotated[httpx.AsyncClient, Depends(get_http)]


def get_profile(request: Request) -> Profile:
    profile: Profile = request.app.state.profile
    return profile


RankedAgainst = Annotated[Profile, Depends(get_profile)]
