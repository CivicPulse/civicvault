"""Tiny, dependency-free PDF fixtures for text-extraction tests.

TEXT_PDF: one page, 76 chars of text → classifies has_text (76 cpp > 50).
EMPTY_PDF: one page, no content stream → 0 chars → classifies ocr_needed.
"""

from pathlib import Path

_TEXT = b"chromebooks lightspeed renewal microsoft lenovo financial services agreement"
_STREAM = b"BT /F1 18 Tf 72 700 Td (" + _TEXT + b") Tj ET\n"
TEXT_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
    b"/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>endobj\n"
    b"4 0 obj<</Length "
    + str(len(_STREAM)).encode()
    + b">>stream\n"
    + _STREAM
    + b"endstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R/Size 6>>\nstartxref\n0\n%%EOF"
)
EMPTY_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R>>endobj\n"
    b"4 0 obj<</Length 0>>stream\nendstream endobj\n"
    b"trailer<</Root 1 0 R/Size 5>>\nstartxref\n0\n%%EOF"
)


def write_text_pdf(path: Path) -> Path:
    path.write_bytes(TEXT_PDF)
    return path


def write_empty_pdf(path: Path) -> Path:
    path.write_bytes(EMPTY_PDF)
    return path
