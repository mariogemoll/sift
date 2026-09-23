"""Deterministic synthetic answers for offline runs; these do not assess text."""

from collections.abc import Sequence

from sift.core.cache import key_for
from sift.core.judgments import ChoiceValue, Judgments, ScoreValue
from sift.core.question_types import Choice, Noul, Score
from sift.core.questions import INJECTED_INSTRUCTIONS, IS_DOCUMENT

from .asker import Ask


def _answer(ask: Ask) -> Judgments:
    nouls: dict[str, float] = {}
    scores: dict[str, ScoreValue] = {}
    choices: dict[str, ChoiceValue] = {}
    for qid, question in ask.asked.items():
        digest = key_for(ask.state, {qid: question})
        fraction = int(digest[:8], 16) / 0xFFFFFFFF
        if isinstance(question, Noul):
            nouls[qid] = (
                (0.99 if ask.state.get("document", "").strip() else 0.01)
                if qid == IS_DOCUMENT
                else (0.01 if qid == INJECTED_INSTRUCTIONS else fraction)
            )
        elif isinstance(question, Score):
            maximum = len(question.criteria) - 1
            scores[qid] = ScoreValue(fraction * maximum, maximum, 0.9)
        elif isinstance(question, Choice):
            options = sorted(question.criteria)
            selected = options[int(digest[8:16], 16) % len(options)]
            probabilities = {
                option: 0.9 if option == selected else 0.1 / (len(options) - 1)
                for option in options
            }
            choices[qid] = ChoiceValue(selected, 0.9, probabilities)
    return Judgments(nouls, scores, choices)


class FakeAsker:
    """Repeatable answers independent of batch position, with no API key or I/O."""

    def __call__(self, asks: Sequence[Ask]) -> Sequence[Judgments]:
        return [_answer(ask) for ask in asks]
