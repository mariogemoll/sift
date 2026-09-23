from __future__ import annotations

import pytest

from sift.judging.judgments import Criterion, Profile


@pytest.fixture
def profile() -> Profile:
    return Profile(
        background="Research in robot learning and reliable manipulation.",
        criteria=(
            Criterion(
                "reproducible", "want", "The paper provides reproducible experiments", weight=2.0
            ),
            Criterion("robotics", "want", "The paper studies robotics", weight=0.5),
            Criterion("retracted", "dealbreaker", "The paper has been retracted"),
        ),
    )


@pytest.fixture(autouse=True)
def clean_tables() -> None:
    """These pure units do not use the database."""
