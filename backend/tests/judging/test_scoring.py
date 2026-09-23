from __future__ import annotations

from sift.core import questions, scoring
from sift.core.judgments import Judgments, Profile, ScoreValue


def _judgments(
    *,
    merit_score: float = 2.0,
    merit_score_confidence: float = 0.9,
    reproducible: float = 3.0,
    robotics: float = 0.0,
    retracted: float = 0.05,
    is_document: float = 0.99,
    injected: float = 0.01,
) -> Judgments:
    return Judgments(
        nouls={
            questions.IS_DOCUMENT: is_document,
            questions.INJECTED_INSTRUCTIONS: injected,
            "block_retracted": retracted,
        },
        scores={
            questions.MERIT: ScoreValue(merit_score, 3, merit_score_confidence),
            "want_reproducible": ScoreValue(reproducible, 3, 0.9),
            "want_robotics": ScoreValue(robotics, 3, 0.9),
        },
    )


def test_a_dealbreaker_blocks_regardless_of_a_high_score(profile: Profile) -> None:
    verdict = scoring.evaluate("p1", _judgments(retracted=0.95), profile)

    assert not verdict.eligible
    assert verdict.blocked_by == ("retracted",)


def test_a_strong_document_is_eligible(profile: Profile) -> None:
    verdict = scoring.evaluate("p1", _judgments(), profile)

    assert verdict.eligible
    assert verdict.blocked_by == ()


def test_blocked_documents_keep_their_score(profile: Profile) -> None:
    """So it stays visible how close a rejected document otherwise was."""
    verdict = scoring.evaluate("p1", _judgments(retracted=0.95), profile)

    assert verdict.total > 0.0


def test_weights_apply_to_wants(profile: Profile) -> None:
    """reproducible carries weight 2.0 and robotics 0.5, so reproducible dominates."""
    reproducible_only = scoring.evaluate("p1", _judgments(reproducible=3.0, robotics=0.0), profile)
    robotics_only = scoring.evaluate("p2", _judgments(reproducible=0.0, robotics=3.0), profile)

    assert reproducible_only.fit > robotics_only.fit


def test_low_confidence_asks_for_review(profile: Profile) -> None:
    verdict = scoring.evaluate("p1", _judgments(merit_score_confidence=0.2), profile)

    assert verdict.needs_review


def test_injected_instructions_are_flagged(profile: Profile) -> None:
    verdict = scoring.evaluate("p1", _judgments(injected=0.9), profile)

    assert any("automated reader" in note for note in verdict.notes)


def test_non_document_is_flagged(profile: Profile) -> None:
    verdict = scoring.evaluate("p1", _judgments(is_document=0.1), profile)

    assert any("substantive document" in note for note in verdict.notes)


def test_merit_weight_moves_the_total(profile: Profile) -> None:
    """Re-weighting uses the same judgments; no new inference."""
    judgments = _judgments(merit_score=0.0, reproducible=3.0, robotics=3.0)

    fit_heavy = scoring.evaluate("p1", judgments, profile)
    qual_heavy = scoring.evaluate(
        "p1", judgments, Profile(profile.background, profile.criteria, merit_weight=0.9)
    )

    assert fit_heavy.total > qual_heavy.total


def test_rank_puts_eligible_first_then_by_total(profile: Profile) -> None:
    good = scoring.evaluate("good", _judgments(reproducible=3.0), profile)
    weak = scoring.evaluate("weak", _judgments(reproducible=0.0, robotics=0.0), profile)
    blocked = scoring.evaluate("blocked", _judgments(reproducible=3.0, retracted=0.99), profile)

    ranked = scoring.rank([blocked, weak, good])

    assert [v.document_id for v in ranked] == ["good", "weak", "blocked"]


def test_missing_answers_do_not_crash(profile: Profile) -> None:
    verdict = scoring.evaluate("p1", Judgments(), profile)

    assert verdict.eligible
    assert verdict.total == 0.0


def test_near_gate_requires_review(profile: Profile) -> None:
    verdict = scoring.evaluate("p", _judgments(retracted=profile.dealbreaker_threshold), profile)
    assert verdict.eligible
    assert verdict.needs_review


def test_missing_answers_require_review(profile: Profile) -> None:
    assert scoring.evaluate("p", Judgments(), profile).needs_review


def test_score_blend_is_explicit(profile: Profile) -> None:
    verdict = scoring.evaluate("p", _judgments(), profile)
    assert abs(verdict.fit - 0.8) < 1e-10
    assert abs(verdict.total - (0.4 * 2 / 3 + 0.6 * 0.8)) < 1e-10
