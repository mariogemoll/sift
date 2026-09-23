"""A stand-in for arXiv's OAI-PMH interface, and responses shaped like the ones it returns."""

from dataclasses import dataclass, field
from html import escape

import httpx


@dataclass
class FakeArxiv:
    """Answers with `status` and `body`, and remembers what it was asked.

    A request carrying a resumption token is answered from `pages` instead, so a
    test can lay out a listing that runs over several pages.
    """

    status: int = 200
    body: str = ""
    pages: dict[str, str] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        token = request.url.params.get("resumptionToken")
        if self.status != 200 or token is None:
            return httpx.Response(self.status, text=self.body)
        return httpx.Response(200, text=self.pages[token])


@dataclass(frozen=True)
class Entry:
    """One paper as arXiv's metadata format describes it."""

    id: str = "2609.26780"
    title: str = "A Paper"
    abstract: str = "What it is about."
    authors: tuple[tuple[str, str], ...] = (("Author", "A."),)
    categories: str = "cs.IR"
    created: str = "2026-09-22"


_ENVELOPE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
    "<responseDate>2026-09-23T00:00:00Z</responseDate>{}</OAI-PMH>"
)


def _record(entry: Entry) -> str:
    authors = "".join(
        f"<author><keyname>{escape(keyname)}</keyname>"
        f"<forenames>{escape(forenames)}</forenames></author>"
        for keyname, forenames in entry.authors
    )
    return (
        f"<record><header><identifier>oai:arXiv.org:{entry.id}</identifier></header>"
        '<metadata><arXiv xmlns="http://arxiv.org/OAI/arXiv/">'
        f"<id>{entry.id}</id><created>{entry.created}</created><authors>{authors}</authors>"
        f"<title>{escape(entry.title)}</title><categories>{entry.categories}</categories>"
        f"<abstract>{escape(entry.abstract)}</abstract></arXiv></metadata></record>"
    )


def records(*entries: Entry, token: str | None = None) -> str:
    """A ListRecords page. With `token`, it carries a resumption token; an empty one ends the list.

    arXiv puts the size of the page in hand into `completeListSize`, so the fake does too.
    """
    resumption = (
        f'<resumptionToken completeListSize="{len(entries)}" cursor="0">{token}</resumptionToken>'
        if token is not None
        else ""
    )
    return _ENVELOPE.format(
        f"<ListRecords>{''.join(_record(entry) for entry in entries)}{resumption}</ListRecords>"
    )


def oai_error(code: str, reason: str) -> str:
    return _ENVELOPE.format(f'<error code="{code}">{escape(reason)}</error>')
