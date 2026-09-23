"""Wire types. Separate from the domain so the contract can be versioned alone."""

from datetime import datetime

from pydantic import BaseModel, Field

from sift.core.types import Page, Paper


class HealthResponse(BaseModel):
    """What `/health` reports. `ok` is false when the database is unreachable."""

    ok: bool
    database: bool
    revision: str | None = Field(
        default=None, description="Migration the database is on, null if never migrated"
    )


class SignIn(BaseModel):
    """The one credential there is."""

    passphrase: str = Field(min_length=1)


class SessionStatus(BaseModel):
    """Whether the caller is signed in, and whether signing in is even possible.

    `configured` is false when the deployment has no passphrase hash, so the
    login page can say that rather than blame the phrase you typed.
    """

    authenticated: bool
    configured: bool


class PaperOut(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    categories: list[str]
    published_at: datetime
    abstract: str

    @staticmethod
    def of(paper: Paper) -> "PaperOut":
        return PaperOut(
            arxiv_id=paper.arxiv_id,
            title=paper.title,
            authors=list(paper.authors),
            categories=list(paper.categories),
            published_at=paper.published_at,
            abstract=paper.abstract,
        )


class PaperPage(BaseModel):
    items: list[PaperOut]
    total: int
    limit: int
    offset: int

    @staticmethod
    def of(page: Page[Paper]) -> "PaperPage":
        return PaperPage(
            items=[PaperOut.of(paper) for paper in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
