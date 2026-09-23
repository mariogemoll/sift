"""Small, valid PDFs built in memory, so the tests carry no binary fixtures."""


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf(*pages: str) -> bytes:
    """A PDF with one line of Helvetica text per page. An empty string is a page with no text."""
    count = len(pages)
    # Objects: 1 catalog, 2 page tree, 3 font, then a page and its content stream per page.
    kids = " ".join(f"{4 + 2 * index} 0 R" for index in range(count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for index, text in enumerate(pages):
        content = 5 + 2 * index
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content} 0 R >>".encode()
        )
        stream = f"BT /F1 12 Tf 72 720 Td ({_escape(text)}) Tj ET".encode() if text else b""
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))

    body = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n%s\nendobj\n" % (number, obj)
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(body)
