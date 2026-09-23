"""Domain types. All immutable; nothing here knows about the network."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["want", "dealbreaker"]
VerdictStage = Literal["screen", "full"]


@dataclass(frozen=True, slots=True)
class Document:
    """One extracted document, as plain text."""

    id: str
    text: str


@dataclass(frozen=True, slots=True)
class Criterion:
    """One axis the user cares about, stable across documents."""

    id: str
    kind: Kind
    requirement: str
    weight: float = 1.0
    levels: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class Profile:
    """What the user has done (background) and what they want (criteria)."""

    background: str
    criteria: Sequence[Criterion]
    name: str = "default"
    """What verdicts are filed under, so rankings for different wishlists never mix."""
    categories: tuple[str, ...] = ()
    """Where the papers come from: the arXiv categories a batch harvests."""
    merit_weight: float = 0.4
    dealbreaker_threshold: float = 0.7
    review_confidence: float = 0.5
    review_margin: float = 0.05
    screen_threshold: float = 0.5
    """The least fit, judged from the abstract, that earns a paper a full-text read."""

    @property
    def wants(self) -> Sequence[Criterion]:
        return [c for c in self.criteria if c.kind == "want"]

    @property
    def dealbreakers(self) -> Sequence[Criterion]:
        return [c for c in self.criteria if c.kind == "dealbreaker"]


@dataclass(frozen=True, slots=True)
class ScoreValue:
    """A Score answer: a position on the levels, plus how concentrated it was."""

    value: float
    max_level: int
    confidence: float

    @property
    def normalized(self) -> float:
        """Position rescaled to 0..1, for ordering and thresholds only.

        This is not a percentage and does not recover a magnitude: the number
        means "this far along the levels that were written", nothing more.
        """
        return self.value / self.max_level if self.max_level else 0.0


@dataclass(frozen=True, slots=True)
class ChoiceValue:
    selected: str
    confidence: float
    probabilities: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class Judgments:
    """Raw model answers for one document, independent of any weighting."""

    nouls: Mapping[str, float] = field(default_factory=dict)
    scores: Mapping[str, ScoreValue] = field(default_factory=dict)
    choices: Mapping[str, ChoiceValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Verdict:
    """Where a document stands against a profile, after one stage of judging.

    `merit` is None for a screen: it is judged from the full text only.
    """

    document_id: str
    stage: VerdictStage
    eligible: bool
    total: float
    merit: float | None
    fit: float
    blocked_by: Sequence[str] = ()
    needs_review: bool = False
    notes: Sequence[str] = ()
    per_criterion: Mapping[str, float] = field(default_factory=dict)
