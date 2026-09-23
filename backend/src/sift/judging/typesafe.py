"""Jev, TypeSafe's System One model, behind the `Asker` contract.

Each ask is one request, and a batch's requests run concurrently: the caller
decides how many asks to hand over at once, which is what bounds the load.

The SDK is built without retries of its own. The pipeline already persists
attempts and backs off with jitter; a second, in-process retry loop underneath
it would multiply the attempts and hide them from the item that records them.
"""

import asyncio
from collections.abc import Mapping, Sequence

from typesafe_sdk import (
    AsyncTypeSafeClient,
    RetryPolicy,
    SystemOneResponse,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeError,
    TypeSafeRateLimitError,
)
from typesafe_sdk import Choice as SdkChoice
from typesafe_sdk import Noul as SdkNoul
from typesafe_sdk import Score as SdkScore

from sift.judging.judgments import ChoiceValue, Judgments, ScoreValue
from sift.judging.question_types import Choice, Instructions, Noul, Question, Score
from sift.retry import Failure, Retryable, Terminal

from .asker import Ask, AskFailed

type SdkQuestion = SdkNoul | SdkScore | SdkChoice

_RETRYABLE_STATUSES = frozenset({408, 425, 429})


def client(api_key: str, *, timeout: float) -> AsyncTypeSafeClient:
    return AsyncTypeSafeClient(api_key=api_key, retry=RetryPolicy(max_retries=0), timeout=timeout)


def _instructions(instructions: Instructions) -> str | dict[str, str]:
    return instructions if isinstance(instructions, str) else dict(instructions)


def to_sdk(question: Question) -> SdkQuestion:
    match question:
        case Noul(instructions):
            return SdkNoul(instructions=_instructions(instructions))
        case Score(instructions, criteria):
            return SdkScore(instructions=_instructions(instructions), criteria=list(criteria))
        case Choice(instructions, criteria):
            return SdkChoice(instructions=_instructions(instructions), criteria=dict(criteria))


def to_judgments(response: SystemOneResponse, asked: Mapping[str, Question]) -> Judgments:
    """Answers the response carries, typed by what was asked.

    An answer that is missing, or of a different type than the question, is left
    out rather than guessed; scoring treats a missing answer as a reason for review.
    """
    nouls: dict[str, float] = {}
    scores: dict[str, ScoreValue] = {}
    choices: dict[str, ChoiceValue] = {}
    for qid, question in asked.items():
        match question:
            case Noul() if qid in response.nouls:
                nouls[qid] = response.nouls[qid].noul
            case Score(_, criteria) if qid in response.scores:
                answer = response.scores[qid]
                scores[qid] = ScoreValue(answer.score, len(criteria) - 1, answer.confidence)
            case Choice() if qid in response.choices:
                picked = response.choices[qid]
                choices[qid] = ChoiceValue(
                    picked.choice, picked.confidence, dict(picked.probabilities)
                )
    return Judgments(nouls, scores, choices)


def failure_of(error: TypeSafeError) -> Failure:
    """Throttling, overload, server trouble and broken connections are worth another
    attempt; a request the service refuses as malformed or unauthorized is not."""
    reason = f"TypeSafe: {error}"
    match error:
        case TypeSafeRateLimitError(retry_after_ms=int() | float() as wait_ms):
            return Retryable(reason, retry_after=wait_ms / 1000)
        case TypeSafeAPIError(status=status) if status >= 500 or status in _RETRYABLE_STATUSES:
            return Retryable(reason)
        case TypeSafeAPIConnectionError():
            return Retryable(reason)
        case _:
            return Terminal(reason)


class TypeSafeAsker:
    """Asks Jev. `model` should be a pinned version, not an alias such as
    `jev-latest`: it keys the judgment cache, and an alias moves underneath it."""

    def __init__(self, sdk: AsyncTypeSafeClient, model: str) -> None:
        self._sdk = sdk
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def _one(self, ask: Ask) -> Judgments:
        try:
            response = await self._sdk.system_one(
                state=dict(ask.state),
                questions={qid: to_sdk(question) for qid, question in ask.asked.items()},
                model=self._model,
            )
        except TypeSafeError as error:
            raise AskFailed(failure_of(error)) from error
        return to_judgments(response, ask.asked)

    async def __call__(self, asks: Sequence[Ask]) -> Sequence[Judgments]:
        return await asyncio.gather(*(self._one(ask) for ask in asks))
