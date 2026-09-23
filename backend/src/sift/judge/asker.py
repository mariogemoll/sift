"""The batch contract shared by model adapters."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from sift.core import questions
from sift.core.judgments import Document, Judgments, Profile
from sift.core.question_types import Question


@dataclass(frozen=True, slots=True)
class Ask:
    """All inputs for a single model request."""

    state: Mapping[str, str]
    asked: Mapping[str, Question]


class Asker(Protocol):
    """A batch of requests in, one judgment per request out, in the same order."""

    def __call__(self, asks: Sequence[Ask]) -> Sequence[Judgments]: ...


def ask_for(document: Document, profile: Profile) -> Ask:
    return Ask(questions.state_for(document, profile), questions.build(document, profile))
