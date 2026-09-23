from datetime import UTC, datetime

from sift.core.types import Page, Paper, empty_page


def test_empty_page_reports_the_window_it_was_asked_for() -> None:
    page: Page[Paper] = empty_page(limit=25, offset=50)
    assert page.items == ()
    assert page.total == 0
    assert (page.limit, page.offset) == (25, 50)


def test_total_is_the_whole_sequence_not_the_window() -> None:
    paper = Paper(
        arxiv_id="2401.00001",
        title="On Sifting",
        authors=("A. Author",),
        categories=("cs.IR",),
        published_at=datetime(2024, 1, 1, tzinfo=UTC),
        abstract="...",
    )
    page = Page(items=(paper,), total=137, limit=1, offset=0)
    assert len(page.items) == 1
    assert page.total == 137


def test_papers_are_hashable_so_they_can_be_deduplicated() -> None:
    def paper(arxiv_id: str) -> Paper:
        return Paper(
            arxiv_id=arxiv_id,
            title="t",
            authors=(),
            categories=(),
            published_at=datetime(2024, 1, 1, tzinfo=UTC),
            abstract="",
        )

    assert len({paper("2401.00001"), paper("2401.00001"), paper("2401.00002")}) == 2
