import pytest

from sift.core.text import capped, for_judging, without_references

BODY = "Introduction\n" + "We study things. " * 50 + "\nConclusion\nIt works.\n"


@pytest.mark.parametrize(
    "heading", ["References", "REFERENCES", "7 References", "VII. References", "Bibliography"]
)
def test_the_reference_list_and_what_follows_it_are_dropped(heading: str) -> None:
    text = f"{BODY}{heading}\n[1] A. Author. A title. 2020.\nAppendix A\nMore proofs."
    assert without_references(text) == BODY.rstrip()


def test_the_first_heading_past_the_opening_stretch_is_the_one_cut_at() -> None:
    """Appendices sometimes carry a references list of their own; both go."""
    text = f"{BODY}References\n[1] x\nAppendix\nReferences\n[2] y"
    assert without_references(text) == BODY.rstrip()


def test_a_heading_near_the_start_is_not_the_reference_list() -> None:
    text = f"Contents\nReferences\n{BODY}"
    assert without_references(text) == text


def test_the_word_inside_a_sentence_is_not_a_heading() -> None:
    text = f"{BODY}See the references below for details.\nMore text."
    assert without_references(text) == text


def test_text_without_references_is_kept_whole() -> None:
    assert without_references(BODY) == BODY


def test_capping_cuts_at_whitespace() -> None:
    assert capped("alpha beta gamma", 12) == "alpha beta"
    assert capped("alpha beta", 100) == "alpha beta"
    assert capped("unbroken", 4) == "unbr"


def test_capping_needs_a_positive_limit() -> None:
    with pytest.raises(ValueError):
        capped("text", 0)


def test_references_go_before_the_cap_applies() -> None:
    """Capping first would spend the budget on the bibliography."""
    text = f"{BODY}References\n" + "[n] A citation. " * 1000
    assert for_judging(text, len(BODY)) == BODY.rstrip()
