"""Choosing what of a paper's extracted text a model reads.

A model judges better from less when the rest is unrelated to the question, and
its input is bounded anyway. The reference list is the largest part of a paper
that says nothing about the paper itself, and appendices usually follow it, so
the text is cut at the references heading first and capped after that. Cutting
only from the end would drop the conclusions and keep the bibliography.
"""

import re

_REFERENCES_HEADING = re.compile(
    r"^[ \t]*(?:\d+\.?|[IVX]+\.)?[ \t]*(?:references|bibliography|works cited)[ \t]*:?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)

EARLIEST_REFERENCES = 0.3
"""A references heading before this fraction of the text is taken for a table of
contents or a sentence that happens to be the word alone, not the section."""


def without_references(text: str) -> str:
    """The text up to the first references heading past the opening stretch, or all of it."""
    earliest = int(len(text) * EARLIEST_REFERENCES)
    for heading in _REFERENCES_HEADING.finditer(text):
        if heading.start() >= earliest:
            return text[: heading.start()].rstrip()
    return text


def capped(text: str, max_chars: int) -> str:
    """At most `max_chars`, cut at a whitespace boundary where there is one."""
    if max_chars <= 0:
        raise ValueError(f"max_chars must be positive, got {max_chars}")
    if len(text) <= max_chars:
        return text
    head = text[:max_chars]
    boundary = max(head.rfind(" "), head.rfind("\n"))
    return (head[:boundary] if boundary > 0 else head).rstrip()


def for_judging(text: str, max_chars: int) -> str:
    return capped(without_references(text), max_chars)
