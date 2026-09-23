"""Reads and writes over verdicts, one per paper and wishlist."""

from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sift.judging.judgments import Verdict
from sift.storage.models import Verdict as VerdictRow


async def put_verdict(
    session: AsyncSession, paper_id: int, profile: str, verdict: Verdict, judgment_key: str
) -> None:
    """Record a paper's verdict. A screen never replaces a full verdict: a paper
    screened again for another batch has already been read in full."""
    values = {
        "stage": verdict.stage,
        "eligible": verdict.eligible,
        "total": verdict.total,
        "merit": verdict.merit,
        "fit": verdict.fit,
        "blocked_by": list(verdict.blocked_by),
        "needs_review": verdict.needs_review,
        "notes": list(verdict.notes),
        "per_criterion": dict(verdict.per_criterion),
        "judgment_key": judgment_key,
    }
    statement = insert(VerdictRow).values(paper_id=paper_id, profile=profile, **values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[VerdictRow.paper_id, VerdictRow.profile],
            set_=values,
            where=or_(VerdictRow.stage == "screen", statement.excluded.stage == "full"),
        )
    )
