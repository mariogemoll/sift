"""An asker whose answers and failures a test lays out in advance."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from sift.judging import Ask, AskFailed
from sift.judging.judgments import Judgments, ScoreValue
from sift.judging.question_types import Noul, Score
from sift.judging.questions import INJECTED_INSTRUCTIONS, IS_DOCUMENT
from sift.retry import Failure


@dataclass
class ScriptedAsker:
    """Answers every research interest with the fit of the first word in `fits`
    found in the document, and every dealbreaker with the probability of the first
    word in `blocks`. Raises the queued `failures` first, one per ask.

    Merit is always strong and the integrity checks always clean, so a test's
    outcome turns on fit and dealbreakers alone.
    """

    fits: Mapping[str, float] = field(default_factory=dict)
    blocks: Mapping[str, float] = field(default_factory=dict)
    default_fit: float = 1.0
    failures: list[Failure] = field(default_factory=list)
    asks: list[Ask] = field(default_factory=list)
    model: str = "scripted"

    def _lookup(self, table: Mapping[str, float], document: str, default: float) -> float:
        return next((value for word, value in table.items() if word in document), default)

    def _answer(self, ask: Ask) -> Judgments:
        document = ask.state["document"]
        nouls: dict[str, float] = {}
        scores: dict[str, ScoreValue] = {}
        for qid, question in ask.asked.items():
            if isinstance(question, Noul):
                nouls[qid] = (
                    0.99
                    if qid == IS_DOCUMENT
                    else 0.01
                    if qid == INJECTED_INSTRUCTIONS
                    else self._lookup(self.blocks, document, 0.01)
                )
            elif isinstance(question, Score):
                top = len(question.criteria) - 1
                fraction = self._lookup(self.fits, document, self.default_fit)
                scores[qid] = ScoreValue(fraction * top, top, 0.9)
        return Judgments(nouls, scores)

    async def __call__(self, asks: Sequence[Ask]) -> Sequence[Judgments]:
        answers = []
        for ask in asks:
            self.asks.append(ask)
            if self.failures:
                raise AskFailed(self.failures.pop(0))
            answers.append(self._answer(ask))
        return answers
