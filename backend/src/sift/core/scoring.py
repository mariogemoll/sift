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


def evaluate(document_id: str, judgments: Judgments, profile: Profile) -> Verdict:
    """Gates first, then a weighted blend of merit and research fit.

    A dealbreaker is a gate, not a low weight: no amount of strength elsewhere
    should be able to average it away.
    """
    notes: list[str] = []
    blocked_by: list[str] = []

    if judgments.nouls.get(IS_DOCUMENT, 1.0) < 0.5:
        notes.append("does not look like a substantive document")
    if judgments.nouls.get(INJECTED_INSTRUCTIONS, 0.0) > 0.5:
        notes.append("contains text aimed at an automated reader; treat with suspicion")

    for criterion in profile.dealbreakers:
        value = judgments.nouls.get(BLOCK_PREFIX + criterion.id)
        if value is not None and value > profile.dealbreaker_threshold:
            blocked_by.append(criterion.id)

    merit_score = judgments.scores.get(MERIT)
    merit = merit_score.normalized if merit_score else 0.0
    fit, per_criterion = _weighted_fit(judgments, profile)

    weight = profile.merit_weight
    total = weight * merit + (1.0 - weight) * fit

    needs_review = merit_score is not None and merit_score.confidence < profile.review_confidence
    if needs_review:
        notes.append("low confidence on the merit judgment")

    for criterion in profile.wants:
        answer = judgments.scores.get(WANT_PREFIX + criterion.id)
        if answer is None or answer.confidence < profile.review_confidence:
            needs_review = True
            notes.append(f"missing or low confidence judgment: {criterion.id}")
    for criterion in profile.dealbreakers:
        probability = judgments.nouls.get(BLOCK_PREFIX + criterion.id)
        if (
            probability is None
            or abs(probability - profile.dealbreaker_threshold) <= profile.review_margin
        ):
            needs_review = True
            notes.append(f"missing or near-threshold gate judgment: {criterion.id}")
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
        eligible=not blocked_by,
        total=total,
        merit=merit,
        fit=fit,
        blocked_by=tuple(blocked_by),
        needs_review=needs_review,
        notes=tuple(notes),
        per_criterion=per_criterion,
    )


def rank(verdicts: list[Verdict]) -> list[Verdict]:
    """Eligible documents first, then by total. Blocked ones keep their score
    so it stays visible what was rejected and how close it otherwise was."""
    return sorted(verdicts, key=lambda v: (not v.eligible, -v.total))
