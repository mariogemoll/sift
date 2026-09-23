from __future__ import annotations

from sift.judging import questions
from sift.judging.judgments import Criterion, Document, Profile
from sift.judging.question_types import Noul, Score


def test_builds_one_question_per_criterion_plus_the_fixed_set(profile: Profile) -> None:
    built = questions.build(Document("p1", "Some paper"), profile)

    assert set(built) == {
        questions.IS_DOCUMENT,
        questions.INJECTED_INSTRUCTIONS,
        questions.MERIT,
        "want_reproducible",
        "want_robotics",
        "block_retracted",
    }


def test_primitive_matches_the_kind_of_judgment(profile: Profile) -> None:
    built = questions.build(Document("p1", "Some paper"), profile)

    assert isinstance(built["want_reproducible"], Score)
    assert isinstance(built["block_retracted"], Noul)
    assert isinstance(built[questions.MERIT], Score)


def test_dealbreakers_are_nouls_not_a_choice(profile: Profile) -> None:
    """A Choice always picks a winner; a Noul can be low for every dealbreaker."""
    built = questions.build(Document("p1", "Some paper"), profile)

    blockers = [q for qid, q in built.items() if qid.startswith(questions.BLOCK_PREFIX)]
    assert blockers and all(isinstance(q, Noul) for q in blockers)


def test_custom_levels_override_the_default_ladder() -> None:
    profile = Profile(
        background="background",
        criteria=(
            Criterion(
                "experiments",
                "want",
                "Includes real robot experiments",
                levels=("below", "at", "above"),
            ),
        ),
    )
    built = questions.build(Document("p1", "paper"), profile)
    question = built["want_experiments"]
    assert isinstance(question, Score)
    assert list(question.criteria) == ["below", "at", "above"]


def test_state_carries_only_the_document_and_the_background(profile: Profile) -> None:
    state = questions.state_for(Document("p1", "Some paper"), profile)

    assert set(state) == {"document", "background"}


def test_the_screen_asks_the_criteria_only(profile: Profile) -> None:
    assert set(questions.criteria(profile)) == {
        "want_reproducible",
        "want_robotics",
        "block_retracted",
    }


def test_the_screen_reads_title_and_abstract_as_the_document(profile: Profile) -> None:
    state = questions.screen_state_for("A Title", "The abstract.", profile)

    assert state == {"document": "A Title\n\nThe abstract.", "background": profile.background}


def test_screen_and_full_text_ask_the_criteria_identically(profile: Profile) -> None:
    full = questions.build(Document("p1", "Some paper"), profile)
    assert all(full[qid] == question for qid, question in questions.criteria(profile).items())
