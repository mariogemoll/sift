"""The judgment cache: a model's raw answers, keyed by a hash of all it was given."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sift.core.cache import from_json, to_json
from sift.core.judgments import Judgments
from sift.storage.models import Judgment


async def cached_judgments(session: AsyncSession, key: str) -> Judgments | None:
    answers = await session.scalar(select(Judgment.answers).where(Judgment.key == key))
    return None if answers is None else from_json(answers)


async def store_judgments(
    session: AsyncSession, key: str, model: str, judgments: Judgments
) -> None:
    """Keep answers for reuse. Answers already stored under the key stand: the key
    covers every input, so a second set is the same question asked twice."""
    await session.execute(
        insert(Judgment)
        .values(key=key, model=model, answers=to_json(judgments))
        .on_conflict_do_nothing(index_elements=[Judgment.key])
    )
