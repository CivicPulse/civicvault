"""Pure per-file helpers for BCSD attachments: R2 key, Document kind, title,
and PDF text extraction with OCR-status classification. No Django, no DB, no
network — unit-testable in isolation."""

import logging
from pathlib import Path

from pypdf import PdfReader

# pypdf logs noisy "Ignoring wrong pointing object" warnings on many real PDFs;
# silence them so ingest output stays readable.
logging.getLogger("pypdf").setLevel(logging.ERROR)

# Brief §8.1: "a few dozen chars/page". Below this average → flag for OCR.
MIN_CHARS_PER_PAGE = 50


def r2_key_for(local_path: Path | str) -> str:
    """Bucket key = 'BCSD/' + the path from the top-level BCSD_* collection dir
    onward. Self-locating so it matches the live bucket regardless of mount point."""
    parts = Path(local_path).parts
    for i, part in enumerate(parts):
        if part.startswith("BCSD_"):
            return "BCSD/" + "/".join(parts[i:])
    raise ValueError(f"No BCSD_* collection dir in path: {local_path}")


def document_kind_for(filename: str) -> str:
    """Light filename heuristics → a Document.Kind value. Defaults to 'other'."""
    name = filename.lower()
    if name.endswith((".ppt", ".pptx")) or "presentation" in name:
        return "presentation"
    if "minutes" in name:
        return "minutes"
    if "agenda" in name:
        return "agenda"
    if "policy" in name or "regulation" in name:
        return "policy"
    if "memo" in name:
        return "memo"
    return "other"


def title_for(filename: str) -> str:
    """Readable title from a slugified filename (drop extension, hyphens→spaces, title-case)."""
    stem = Path(filename).stem
    return stem.replace("-", " ").replace("_", " ").strip().title()


def extract_pdf_text(local_path: Path) -> tuple[str, str]:
    """Return (text, ocr_status). Status ∈ has_text | ocr_needed | empty | unknown.

    - 0 pages → ("", "empty")
    - pages but no/sparse text layer (< MIN_CHARS_PER_PAGE avg) → ocr_needed
      (the returned text may be empty or sparse in this case)
    - unreadable PDF → ("", "unknown") and a logged warning (one bad attachment
      must not abort an otherwise-good meeting ingest)
    """
    try:
        reader = PdfReader(local_path)
        pages = reader.pages
        if len(pages) == 0:
            return "", "empty"
        text = "".join((page.extract_text() or "") for page in pages).strip()
        total = len(text)
        if total == 0 or total / len(pages) < MIN_CHARS_PER_PAGE:
            return text, "ocr_needed"
        return text, "has_text"
    except Exception:
        logging.getLogger(__name__).warning("Unreadable PDF, flagging unknown: %s", local_path)
        return "", "unknown"
