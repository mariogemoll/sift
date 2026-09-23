"""Text out of a PDF, and a hash of that text.

The hash is over the extracted text rather than the PDF's bytes, so two
downloads that differ only in metadata or compression count as the same
document.

Extraction is CPU-bound and synchronous; an async caller runs it in a thread.
"""

import hashlib
import io

from pypdf import PdfReader

from sift.core.retry import Terminal
from sift.ingest.failures import FetchFailed


def clean(text: str) -> str:
    """Text that encodes as UTF-8 and that Postgres will store.

    pypdf can hand back characters outside the Basic Multilingual Plane — the
    mathematical alphabets papers use for variables — as two separate UTF-16
    surrogates rather than one character. Surrogates are not encodable on their
    own, so a pair is joined back into its character and one left alone is
    replaced. NUL is dropped: Postgres refuses it in text.
    """
    joined = text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return joined.replace("\x00", "")


def extract_text(pdf: bytes) -> str:
    """Every page's text, pages separated by a blank line. Pages with no text are skipped."""
    try:
        reader = PdfReader(io.BytesIO(pdf))
        pages = [page.extract_text() for page in reader.pages]
    # The input is whatever a server sent, and pypdf reports malformed input
    # through more exception types than its own; any of them means unreadable.
    except Exception as error:
        raise FetchFailed(Terminal(f"the PDF cannot be read: {error}")) from error

    text = "\n\n".join(stripped for page in pages if (stripped := clean(page).strip()))
    if not text:
        raise FetchFailed(Terminal("the PDF has no text layer"))
    return text


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
