"""SDK-independent descriptions of typed questions."""

from collections.abc import Mapping
from dataclasses import dataclass

type Instructions = str | Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Noul:
    """An answer is P(yes), not a boolean or a self-reported confidence."""

    instructions: Instructions


@dataclass(frozen=True, slots=True)
class Score:
    """An answer is the probability-weighted position on an ordered ladder."""

    instructions: Instructions
    criteria: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.criteria) < 2:
            raise ValueError("a score needs at least two levels")


@dataclass(frozen=True, slots=True)
class Choice:
    """An answer is a distribution over named, mutually exclusive options."""

    instructions: Instructions
    criteria: Mapping[str, str]

    def __post_init__(self) -> None:
        if len(self.criteria) < 2:
            raise ValueError("a choice needs at least two options")


type Question = Noul | Score | Choice
