"""Turn raw judgments into a ranked verdict. Pure: no network, no I/O.

Weights and thresholds live here rather than in the questions, so changing how
much something counts never means asking the model again.
"""

from __future__ import annotations

from .judgments import Judgments, Profile, Verdict
from .questions import (
    BLOCK_PREFIX,
    INJECTED_INSTRUCTIONS,
    IS_DOCUMENT,
    MERIT,
    WANT_PREFIX,
)


def _weighted_fit(judgments: Judgments, profile: Profile) -> tuple[float, dict[str, float]]:
    per_criterion: dict[str, float] = {}
    total_weight = 0.0
    accumulated = 0.0
    for criterion in profile.wants:
        score = judgments.scores.get(WANT_PREFIX + criterion.id)
        if score is None:
            continue
        per_criterion[criterion.id] = score.normalized
        accumulated += criterion.weight * score.normalized
        total_weight += criterion.weight
    fit = accumulated / total_weight if total_weight else 0.0
    return fit, per_criterion


def _blocked_by(judgments: Judgments, profile: Profile) -> tuple[str, ...]:
    """A dealbreaker is a gate, not a low weight: no amount of strength elsewhere
    should be able to average it away."""
    return tuple(
        criterion.id
        for criterion in profile.dealbreakers
        if (value := judgments.nouls.get(BLOCK_PREFIX + criterion.id)) is not None
        and value > profile.dealbreaker_threshold
    )


def _criteria_doubts(judgments: Judgments, profile: Profile) -> list[str]:
    """Why the criteria answers are not to be trusted as they stand, if they are not."""
    doubts: list[str] = []
    for criterion in profile.wants:
        answer = judgments.scores.get(WANT_PREFIX + criterion.id)
        if answer is None or answer.confidence < profile.review_confidence:
            doubts.append(f"missing or low confidence judgment: {criterion.id}")
    for criterion in profile.dealbreakers:
        probability = judgments.nouls.get(BLOCK_PREFIX + criterion.id)
        if (
            probability is None
            or abs(probability - profile.dealbreaker_threshold) <= profile.review_margin
        ):
            doubts.append(f"missing or near-threshold gate judgment: {criterion.id}")
    return doubts


def evaluate(document_id: str, judgments: Judgments, profile: Profile) -> Verdict:
    """Gates first, then a weighted blend of merit and research fit, from the full text."""
    notes: list[str] = []

    if judgments.nouls.get(IS_DOCUMENT, 1.0) < 0.5:
        notes.append("does not look like a substantive document")
    if judgments.nouls.get(INJECTED_INSTRUCTIONS, 0.0) > 0.5:
        notes.append("contains text aimed at an automated reader; treat with suspicion")

    blocked_by = _blocked_by(judgments, profile)
    merit_score = judgments.scores.get(MERIT)
    merit = merit_score.normalized if merit_score else 0.0
    fit, per_criterion = _weighted_fit(judgments, profile)

    weight = profile.merit_weight
    total = weight * merit + (1.0 - weight) * fit

    needs_review = merit_score is not None and merit_score.confidence < profile.review_confidence
    if needs_review:
        notes.append("low confidence on the merit judgment")

    doubts = _criteria_doubts(judgments, profile)
    needs_review = needs_review or bool(doubts)
    notes.extend(doubts)
    if (
        merit_score is None
        or IS_DOCUMENT not in judgments.nouls
        or INJECTED_INSTRUCTIONS not in judgments.nouls
    ):
        needs_review = True
        notes.append("missing document integrity or merit judgment")
    if (
        judgments.nouls.get(IS_DOCUMENT, 1.0) < 0.5
        or judgments.nouls.get(INJECTED_INSTRUCTIONS, 0.0) > 0.5
    ):
        needs_review = True

    return Verdict(
        document_id=document_id,
        stage="full",
        eligible=not blocked_by,
        total=total,
        merit=merit,
        fit=fit,
        blocked_by=blocked_by,
        needs_review=needs_review,
        notes=tuple(notes),
        per_criterion=per_criterion,
    )


def screen(document_id: str, judgments: Judgments, profile: Profile) -> Verdict:
    """The same gates and fit, from the abstract alone. There is no merit here:
    an abstract says what a paper claims, not how well it backs the claim."""
    blocked_by = _blocked_by(judgments, profile)
    fit, per_criterion = _weighted_fit(judgments, profile)
    doubts = _criteria_doubts(judgments, profile)
    return Verdict(
        document_id=document_id,
        stage="screen",
        eligible=not blocked_by,
        total=fit,
        merit=None,
        fit=fit,
        blocked_by=blocked_by,
        needs_review=bool(doubts),
        notes=tuple(doubts),
        per_criterion=per_criterion,
    )


def passes_screen(verdict: Verdict, profile: Profile) -> bool:
    """Whether a screened paper earns a download and a full-text judgment."""
    return verdict.eligible and verdict.total >= profile.screen_threshold


def rank(verdicts: list[Verdict]) -> list[Verdict]:
    """Eligible documents first, full-text verdicts ahead of screens, then by total.

    A screen's total is fit alone and a full verdict's blends in merit, so the two
    are not on one scale; a paper judged in full has also already passed a screen.
    Blocked ones keep their score so it stays visible what was rejected and how
    close it otherwise was.
    """
    return sorted(verdicts, key=lambda v: (not v.eligible, v.stage != "full", -v.total))
