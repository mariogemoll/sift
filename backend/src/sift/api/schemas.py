"""Wire types. Separate from the domain so the contract can be versioned alone."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from sift.core.judgments import Kind, Profile, Verdict, VerdictStage
from sift.core.types import Assessed, Batch, BatchState, BatchStatus, ItemState, Page, Paper


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


class VerdictOut(BaseModel):
    """Where a paper stands against the wishlist.

    `stage` is `screen` when only the abstract was judged — `merit` is then null
    and `total` is fit alone — and `full` once the text was. The two totals are
    not on one scale. `per_criterion` holds each research interest's position on
    its levels, from 0 to 1: an ordering, not a percentage.
    """

    stage: VerdictStage
    eligible: bool
    total: float
    merit: float | None
    fit: float
    blocked_by: list[str]
    needs_review: bool
    notes: list[str]
    per_criterion: dict[str, float]

    @staticmethod
    def of(verdict: Verdict) -> "VerdictOut":
        return VerdictOut(
            stage=verdict.stage,
            eligible=verdict.eligible,
            total=verdict.total,
            merit=verdict.merit,
            fit=verdict.fit,
            blocked_by=list(verdict.blocked_by),
            needs_review=verdict.needs_review,
            notes=list(verdict.notes),
            per_criterion=dict(verdict.per_criterion),
        )


class AssessedOut(BaseModel):
    """A paper, and its verdict once it has been screened."""

    paper: PaperOut
    verdict: VerdictOut | None

    @staticmethod
    def of(assessed: Assessed) -> "AssessedOut":
        return AssessedOut(
            paper=PaperOut.of(assessed.paper),
            verdict=None if assessed.verdict is None else VerdictOut.of(assessed.verdict),
        )


class PaperPage(BaseModel):
    items: list[AssessedOut]
    total: int
    limit: int
    offset: int

    @staticmethod
    def of(page: Page[Assessed]) -> "PaperPage":
        return PaperPage(
            items=[AssessedOut.of(assessed) for assessed in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


class CriterionOut(BaseModel):
    id: str
    kind: Kind
    requirement: str
    weight: float


class ProfileOut(BaseModel):
    """The wishlist papers are ranked against, and the thresholds applied to it."""

    name: str
    categories: list[str]
    criteria: list[CriterionOut]
    merit_weight: float
    dealbreaker_threshold: float
    screen_threshold: float

    @staticmethod
    def of(profile: Profile) -> "ProfileOut":
        return ProfileOut(
            name=profile.name,
            categories=list(profile.categories),
            criteria=[
                CriterionOut(id=c.id, kind=c.kind, requirement=c.requirement, weight=c.weight)
                for c in profile.criteria
            ],
            merit_weight=profile.merit_weight,
            dealbreaker_threshold=profile.dealbreaker_threshold,
            screen_threshold=profile.screen_threshold,
        )


class BatchRequest(BaseModel):
    """Which papers to pull in: those new or revised on or after a date, in every
    category the wishlist names."""

    since: date


class BatchOut(BaseModel):
    """A batch and how far it has got.

    `added` counts papers new to the system; `items` counts every paper the batch
    has seen, and `progress` how many wait for each stage or ended in `done` or
    `dead`. `state` is the harvest's alone; `status` is the batch's as a whole,
    `processing` while its papers are still between stages. `attempts` and
    `last_error` describe harvest failures since the last page that succeeded.
    """

    id: int
    category: str
    since: date
    until: date
    state: BatchState
    pages: int
    added: int
    items: int
    progress: dict[ItemState, int]
    status: BatchStatus
    attempts: int
    last_error: str | None
    created_at: datetime
    finished_at: datetime | None

    @staticmethod
    def of(batch: Batch) -> "BatchOut":
        return BatchOut(
            id=batch.id,
            category=batch.category,
            since=batch.since,
            until=batch.until,
            state=batch.state,
            pages=batch.pages,
            added=batch.added,
            items=batch.items,
            progress=dict(batch.progress),
            status=batch.status,
            attempts=batch.attempts,
            last_error=batch.last_error,
            created_at=batch.created_at,
            finished_at=batch.finished_at,
        )
