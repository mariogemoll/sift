"""The batch contract shared by model adapters."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from sift.core import questions
from sift.core.judgments import Document, Judgments, Profile
from sift.core.question_types import Question
from sift.core.retry import Failure


@dataclass(frozen=True, slots=True)
class Ask:
    """All inputs for a single model request."""

    state: Mapping[str, str]
    asked: Mapping[str, Question]


class AskFailed(RuntimeError):
    """The model could not answer; `failure` says whether asking again could help."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.reason)
        self.failure = failure


class Asker(Protocol):
    """A batch of requests in, one judgment per request out, in the same order.

    `model` names what answers, precisely enough to key a cache: two askers with
    the same name must give interchangeable answers. A request that cannot be
    answered raises `AskFailed`.
    """

    @property
    def model(self) -> str: ...

    async def __call__(self, asks: Sequence[Ask]) -> Sequence[Judgments]: ...


def ask_for(document: Document, profile: Profile) -> Ask:
    """The full judgment of a document's text."""
    return Ask(questions.state_for(document, profile), questions.build(document, profile))


def screen_ask_for(title: str, abstract: str, profile: Profile) -> Ask:
    """The screen of a paper from its listing."""
    return Ask(questions.screen_state_for(title, abstract, profile), questions.criteria(profile))
