import pytest

from pdf_fake import pdf
from sift.core.retry import Terminal
from sift.ingest.extract import content_hash, extract_text
from sift.ingest.failures import FetchFailed


def test_text_comes_out_page_by_page() -> None:
    assert extract_text(pdf("First page", "Second page")) == "First page\n\nSecond page"


def test_pages_without_text_are_skipped() -> None:
    assert extract_text(pdf("Before", "", "After")) == "Before\n\nAfter"


def test_a_pdf_with_no_text_at_all_is_terminal() -> None:
    with pytest.raises(FetchFailed) as caught:
        extract_text(pdf("", ""))
    assert caught.value.failure == Terminal("the PDF has no text layer")


def test_a_corrupt_pdf_is_terminal() -> None:
    with pytest.raises(FetchFailed) as caught:
        extract_text(b"%PDF-1.4\nthis is not a PDF at all")
    assert isinstance(caught.value.failure, Terminal)
    assert caught.value.failure.reason.startswith("the PDF cannot be read")


def test_the_hash_is_of_the_text_so_the_same_text_dedupes() -> None:
    assert content_hash("same words") == content_hash("same words")
    assert content_hash("same words") != content_hash("other words")


def test_the_hash_is_hex_sha256() -> None:
    assert content_hash("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
