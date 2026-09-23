"""Reads and writes over the papers table. Functions, not a repository class."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import Select, and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sift.judging.judgments import Verdict, VerdictStage
from sift.storage.models import Paper as PaperRow
from sift.storage.models import Verdict as VerdictRow
from sift.types import Order, Page, Paper


@dataclass(frozen=True, slots=True)
class Assessed:
    """A paper and where it stands against a wishlist; None until it is screened."""

    paper: Paper
    verdict: Verdict | None


def _to_domain(row: PaperRow) -> Paper:
    return Paper(
        arxiv_id=row.arxiv_id,
        title=row.title,
        authors=tuple(row.authors),
        categories=tuple(row.categories),
        published_at=row.published_at,
        abstract=row.abstract,
    )


def _verdict(row: VerdictRow, arxiv_id: str) -> Verdict:
    return Verdict(
        document_id=arxiv_id,
        stage=cast(VerdictStage, row.stage),
        eligible=row.eligible,
        total=row.total,
        merit=row.merit,
        fit=row.fit,
        blocked_by=tuple(row.blocked_by),
        needs_review=row.needs_review,
        notes=tuple(row.notes),
        per_criterion=dict(row.per_criterion),
    )


def _within(
    statement: Select[tuple[PaperRow, VerdictRow]], since: datetime | None
) -> Select[tuple[PaperRow, VerdictRow]]:
    return statement if since is None else statement.where(PaperRow.published_at >= since)


async def list_papers(
    session: AsyncSession,
    *,
    profile: str,
    limit: int,
    offset: int,
    since: datetime | None = None,
    order: Order = "rank",
) -> Page[Assessed]:
    """Papers published on or after `since`, each with its verdict under `profile`.

    Ranked: eligible papers first, those read in full ahead of those only
    screened, then by total; papers not yet screened come last. A screen's total
    is fit alone and a full verdict's blends in merit, so each is compared only
    with its own kind. Newest: by publication date alone.
    """
    joined = _within(
        select(PaperRow, VerdictRow).outerjoin(
            VerdictRow, and_(VerdictRow.paper_id == PaperRow.id, VerdictRow.profile == profile)
        ),
        since,
    )
    newest = (PaperRow.published_at.desc(), PaperRow.id.desc())
    ordered = (
        joined.order_by(*newest)
        if order == "newest"
        else joined.order_by(
            VerdictRow.paper_id.is_(None),
            VerdictRow.eligible.desc(),
            (VerdictRow.stage == "full").desc(),
            VerdictRow.total.desc(),
            *newest,
        )
    )
    rows = (await session.execute(ordered.limit(limit).offset(offset))).tuples().all()
    counted = select(func.count()).select_from(PaperRow)
    if since is not None:
        counted = counted.where(PaperRow.published_at >= since)
    return Page(
        items=tuple(
            Assessed(
                paper=_to_domain(paper),
                verdict=None if verdict is None else _verdict(verdict, paper.arxiv_id),
            )
            for paper, verdict in rows
        ),
        total=await session.scalar(counted) or 0,
        limit=limit,
        offset=offset,
    )


async def add_papers(session: AsyncSession, papers: Sequence[Paper]) -> int:
    """Insert the papers not already stored, keyed on arXiv id. Returns how many were new.

    Asking for the same window twice is expected, so a paper already present is
    skipped rather than an error.
    """
    if not papers:
        return 0
    statement = (
        insert(PaperRow)
        .values(
            [
                {
                    "arxiv_id": paper.arxiv_id,
                    "title": paper.title,
                    "authors": list(paper.authors),
                    "categories": list(paper.categories),
                    "published_at": paper.published_at,
                    "abstract": paper.abstract,
                }
                for paper in papers
            ]
        )
        .on_conflict_do_nothing(index_elements=[PaperRow.arxiv_id])
        .returning(PaperRow.id)
    )
    return len((await session.scalars(statement)).all())
