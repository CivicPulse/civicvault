# Slice 1c — Documents + OCR-flag + FTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Materialize each meeting folder's `files/` attachments as searchable `Document` rows — linked to Meeting + AgendaItem, with PDF text extracted, OCR status flagged, a deterministic R2 key, and a populated full-text `search_vector`.

**Architecture:** Approach A. The BCSD adapter (source-specific, pure) walks `files/`, extracts PDF text, classifies OCR status, computes the R2 key, and resolves file→agenda-item linkage, emitting richer `ParsedDocument` records. The generic loader persists them as `Document` rows inside its existing wipe/recreate transaction. A Postgres trigger maintains `search_vector` on every write. R2 upload-where-missing is an opt-in (`--upload`) step in the command, run after commit, so the atomic loader and the test suite never touch the network.

**Tech Stack:** Django 6, Postgres FTS (`tsvector`/GIN/trigger), `pypdf` (text extraction), `boto3` + `django-storages` (R2/S3), pytest-django.

**Spec:** `docs/superpowers/specs/2026-06-03-civicvault-1c-documents-fts-design.md`

---

## Context the implementer needs

- **Run everything with `uv run`** (never system python). Lint with `ruff` before each commit. `migrations/` and `archive_data/` are ruff-excluded.
- **Dev DB:** `docker compose up -d db` (host port 5433; `.env` points to it). Do NOT pass `--reuse-db` — the migration workflow needs a fresh test DB each run.
- **Deps already added** (planning spike, committed): `pypdf`, `boto3`. `uv add` again is a harmless no-op if you want to confirm.
- **Branch:** work on `feat/1c-documents-fts` (already checked out).
- **Enum values already confirmed to match the IR strings** — `Document.OCRStatus.values == ['has_text','ocr_needed','empty','unknown']`; `Document.Kind.values` includes `policy/memo/presentation/other`. So the loader maps IR strings to enums directly.
- **`.env` now sets `R2_BUCKET`**, so in tests `default_storage` is the live S3 backend. NEVER call `upload_missing` (or `default_storage.save/exists`) in a test without mocking it. The `--upload` flag is off by default precisely so the e2e path stays offline.
- **R2 key convention (verified against the live bucket):** `BCSD/<path from the BCSD_* collection dir onward>`, e.g. local `…/2025/04/<folder>/files/hmh.pdf` → `BCSD/BCSD_BOE_MEETINGS/2025/04/<folder>/files/hmh.pdf`. Self-locating on the `BCSD_`-prefixed path component (works identically for the real archive and the tmp-dir test layout).
- **Verify gates (all green before "done"):** `uv run pytest -q`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`, `uv run ruff check . && uv run ruff format --check .`.
- **Imports go at the top of the module.** Several tasks show `import`/`from` lines alongside an appended test function for readability — always place those import lines at the top of the target file with the existing imports, never mid-file. Appending an import in the middle of a file trips ruff `E402` (module-level import not at top). Skip any import already present.

## File structure

| File | Responsibility | Action |
|---|---|---|
| `catalog/ingest/ir.py` | Framework-neutral IR dataclasses | **Modify** — add attachment fields to `ParsedDocument` |
| `catalog/ingest/bcsd/files.py` | Pure per-file helpers: key, kind, title, PDF text+OCR classify | **Create** |
| `catalog/ingest/bcsd/adapter.py` | Folder → IR; now also enumerates `files/` → attachment docs | **Modify** |
| `catalog/ingest/storage.py` | `upload_missing` — idempotent R2 backfill | **Create** |
| `catalog/ingest/loader.py` | Generic IR → DB; now persists attachment Documents | **Modify** |
| `catalog/migrations/0010_document_search_vector_trigger.py` | FTS trigger | **Create** |
| `catalog/management/commands/ingest_bcsd.py` | CLI; `--upload` flag + post-commit upload + doc count | **Modify** |
| `catalog/tests/fixtures/pdfs.py` | Tiny validated PDF byte fixtures + writers | **Create** |
| `catalog/tests/test_bcsd_files.py` | Unit tests for `files.py` | **Create** |
| `catalog/tests/test_ingest_storage.py` | Unit tests for `upload_missing` | **Create** |
| `catalog/tests/test_ingest_loader.py` | Loader tests | **Modify** — add attachment-doc + FTS cases |
| `catalog/tests/test_ingest_bcsd_command.py` | E2E | **Modify** — stage `files/`, assert attachments |

---

## Task 1: Extend `ParsedDocument` with attachment fields

**Files:**
- Modify: `catalog/ingest/ir.py:60-64`
- Test: `catalog/tests/test_ingest_ir.py`

- [ ] **Step 1: Write the failing test**

Add to `catalog/tests/test_ingest_ir.py`:

```python
def test_parsed_document_attachment_fields_default():
    from catalog.ingest.ir import ParsedDocument

    # Existing source-doc usage keeps working with the new fields defaulted.
    src = ParsedDocument(kind="minutes", title="minutes.md", source_path="/x/minutes.md", text="hi")
    assert src.r2_key == ""
    assert src.ocr_status == "unknown"
    assert src.agenda_item_code is None
    assert src.is_attachment is False

    att = ParsedDocument(
        kind="memo", title="Action Memo", source_path="/x/files/m.pdf", text="body",
        r2_key="BCSD/.../files/m.pdf", ocr_status="has_text",
        agenda_item_code="FSS-3", is_attachment=True,
    )
    assert att.is_attachment is True
    assert att.agenda_item_code == "FSS-3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest catalog/tests/test_ingest_ir.py::test_parsed_document_attachment_fields_default -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'r2_key'`.

- [ ] **Step 3: Implement**

Replace `ParsedDocument` in `catalog/ingest/ir.py` (currently lines 59-64) with:

```python
@dataclass(frozen=True)
class ParsedDocument:
    kind: str  # "minutes" | "agenda" | "other" | attachment heuristics (policy/memo/presentation)
    title: str
    source_path: str
    text: str
    # Attachment fields (defaults keep the existing .md source-doc call sites working).
    r2_key: str = ""
    ocr_status: str = "unknown"  # "has_text" | "ocr_needed" | "empty" | "unknown"
    agenda_item_code: str | None = None  # None → meeting-level (no AgendaItem link)
    is_attachment: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest catalog/tests/test_ingest_ir.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check catalog/ingest/ir.py && uv run ruff format catalog/ingest/ir.py
git add catalog/ingest/ir.py catalog/tests/test_ingest_ir.py
git commit -m "feat: add attachment fields to ParsedDocument IR"
```

---

## Task 2: `files.py` — key, kind, and title helpers (pure)

**Files:**
- Create: `catalog/ingest/bcsd/files.py`
- Test: `catalog/tests/test_bcsd_files.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_bcsd_files.py`:

```python
from pathlib import Path

from catalog.ingest.bcsd.files import document_kind_for, r2_key_for, title_for


def test_r2_key_locates_bcsd_component():
    p = Path("/anything/archive_data/bcsd/BCSD_BOE_MEETINGS/2025/04/mtg/files/hmh.pdf")
    assert r2_key_for(p) == "BCSD/BCSD_BOE_MEETINGS/2025/04/mtg/files/hmh.pdf"


def test_r2_key_works_for_tmp_test_layout():
    p = Path("/tmp/pytest-x/BCSD_BOE_MEETINGS/2025/04/mtg/files/a.pdf")
    assert r2_key_for(p) == "BCSD/BCSD_BOE_MEETINGS/2025/04/mtg/files/a.pdf"


def test_r2_key_without_bcsd_component_raises():
    import pytest

    with pytest.raises(ValueError):
        r2_key_for(Path("/tmp/no/collection/here/file.pdf"))


def test_document_kind_heuristics():
    assert document_kind_for("action-memo-math-adoption-signed.pdf") == "memo"
    assert document_kind_for("board-policy-garha-2nd-reading.pdf") == "policy"
    assert document_kind_for("regulation-afc-r-1-emergency-closings.pdf") == "policy"
    assert document_kind_for("school-consolidation-final.pptx") == "presentation"
    assert document_kind_for("fss-1m-1.PPT") == "presentation"
    assert document_kind_for("some-random-quote-52159.pdf") == "other"


def test_title_for_deslugs_filename():
    assert title_for("action-memo-math-adoption-signed.pdf") == "Action Memo Math Adoption Signed"
    assert title_for("hmh.pdf") == "Hmh"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_files.py -q`
Expected: FAIL — `ModuleNotFoundError: catalog.ingest.bcsd.files`.

- [ ] **Step 3: Implement**

Create `catalog/ingest/bcsd/files.py`:

```python
"""Pure per-file helpers for BCSD attachments: R2 key, Document kind, title,
and PDF text extraction with OCR-status classification. No Django, no DB, no
network — unit-testable in isolation."""

import logging
from pathlib import Path

# pypdf logs noisy "Ignoring wrong pointing object" warnings on many real PDFs;
# silence them so ingest output stays readable.
logging.getLogger("pypdf").setLevel(logging.ERROR)

# Brief §8.1: "a few dozen chars/page". Below this average → flag for OCR.
MIN_CHARS_PER_PAGE = 50


def r2_key_for(local_path: Path) -> str:
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
    if "policy" in name or "regulation" in name:
        return "policy"
    if "memo" in name:
        return "memo"
    return "other"


def title_for(filename: str) -> str:
    """Readable title from a slugified filename (drop extension, hyphens→spaces, title-case)."""
    stem = Path(filename).stem
    return stem.replace("-", " ").replace("_", " ").strip().title()
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest catalog/tests/test_bcsd_files.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
uv run ruff check catalog/ingest/bcsd/files.py catalog/tests/test_bcsd_files.py && uv run ruff format catalog/ingest/bcsd/files.py catalog/tests/test_bcsd_files.py
git add catalog/ingest/bcsd/files.py catalog/tests/test_bcsd_files.py
git commit -m "feat: add BCSD file helpers (r2 key, kind, title)"
```

---

## Task 3: PDF fixtures + `extract_pdf_text` classification

**Files:**
- Create: `catalog/tests/fixtures/pdfs.py`
- Modify: `catalog/ingest/bcsd/files.py`
- Test: `catalog/tests/test_bcsd_files.py`

- [ ] **Step 1: Create the validated PDF fixtures helper**

Create `catalog/tests/fixtures/pdfs.py` (byte literals validated with pypdf during planning):

```python
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
    b"4 0 obj<</Length " + str(len(_STREAM)).encode() + b">>stream\n" + _STREAM + b"endstream endobj\n"
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
```

- [ ] **Step 2: Write the failing extraction test**

Append to `catalog/tests/test_bcsd_files.py`:

```python
from catalog.ingest.bcsd.files import extract_pdf_text
from catalog.tests.fixtures.pdfs import write_empty_pdf, write_text_pdf


def test_extract_pdf_text_has_text(tmp_path):
    pdf = write_text_pdf(tmp_path / "t.pdf")
    text, status = extract_pdf_text(pdf)
    assert "chromebooks" in text
    assert status == "has_text"


def test_extract_pdf_text_no_text_layer_is_ocr_needed(tmp_path):
    pdf = write_empty_pdf(tmp_path / "e.pdf")
    text, status = extract_pdf_text(pdf)
    assert text == ""
    assert status == "ocr_needed"


def test_extract_pdf_text_unreadable_is_unknown(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not really a pdf")
    text, status = extract_pdf_text(bad)
    assert text == ""
    assert status == "unknown"
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_files.py -k extract -q`
Expected: FAIL — `ImportError: cannot import name 'extract_pdf_text'`.

- [ ] **Step 4: Implement `extract_pdf_text`**

Append to `catalog/ingest/bcsd/files.py` (and add `from pypdf import PdfReader` at the top with the other imports):

```python
def extract_pdf_text(local_path: Path) -> tuple[str, str]:
    """Return (text, ocr_status). Status ∈ has_text | ocr_needed | empty | unknown.

    - 0 pages → ("", "empty")
    - pages but no/sparse text layer (< MIN_CHARS_PER_PAGE avg) → ocr_needed
    - unreadable PDF → ("", "unknown") and a logged warning (one bad attachment
      must not abort an otherwise-good meeting ingest)
    """
    try:
        reader = PdfReader(str(local_path))
        pages = reader.pages
        if len(pages) == 0:
            return "", "empty"
        text = "".join((page.extract_text() or "") for page in pages)
        total = len(text.strip())
        if total == 0 or total / len(pages) < MIN_CHARS_PER_PAGE:
            return text, "ocr_needed"
        return text, "has_text"
    except Exception:
        logging.getLogger(__name__).warning("Unreadable PDF, flagging unknown: %s", local_path)
        return "", "unknown"
```

Add the import near the top:

```python
from pypdf import PdfReader
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest catalog/tests/test_bcsd_files.py -q`
Expected: PASS (8 tests total).

- [ ] **Step 6: Commit**

```bash
uv run ruff check catalog/ingest/bcsd/files.py catalog/tests/ && uv run ruff format catalog/ingest/bcsd/files.py catalog/tests/fixtures/pdfs.py catalog/tests/test_bcsd_files.py
git add catalog/ingest/bcsd/files.py catalog/tests/fixtures/pdfs.py catalog/tests/test_bcsd_files.py
git commit -m "feat: add PDF text extraction with OCR-status classification"
```

---

## Task 4: Adapter enumerates `files/` → attachment ParsedDocuments

**Files:**
- Modify: `catalog/ingest/bcsd/adapter.py`
- Test: `catalog/tests/test_bcsd_adapter.py`

- [ ] **Step 1: Write the failing test**

Append to `catalog/tests/test_bcsd_adapter.py` (import helpers at top if not present):

```python
import shutil

from catalog.ingest.bcsd.adapter import parse_meeting_folder
from catalog.tests.fixtures import FIXTURES_DIR
from catalog.tests.fixtures.pdfs import write_empty_pdf, write_text_pdf


def _committee_folder_with_files(tmp_path):
    folder = tmp_path / "BCSD_BOE_MEETINGS" / "2025" / "04" / "2025-04-17_1600_committee-meeting_mid-124789"
    (folder / "files").mkdir(parents=True)
    for fname in ("event.md", "minutes.md", "agenda.md"):
        shutil.copy(FIXTURES_DIR / "committee" / fname, folder / fname)
    # One file that the ## Files map links to FSS-3 (text layer), one unmapped (no text).
    write_text_pdf(folder / "files" / "hmh.pdf")  # mapped to FSS-3 in committee/event.md
    write_empty_pdf(folder / "files" / "unmapped-extra.pdf")
    return folder


def test_adapter_emits_attachment_documents(tmp_path):
    folder = _committee_folder_with_files(tmp_path)
    parsed = parse_meeting_folder(folder)

    attachments = [d for d in parsed.raw_documents if d.is_attachment]
    by_name = {d.source_path.rsplit("/", 1)[-1]: d for d in attachments}
    assert set(by_name) == {"hmh.pdf", "unmapped-extra.pdf"}

    hmh = by_name["hmh.pdf"]
    assert hmh.ocr_status == "has_text"
    assert "chromebooks" in hmh.text
    assert hmh.agenda_item_code == "FSS-3"
    assert hmh.r2_key.endswith(
        "BCSD_BOE_MEETINGS/2025/04/2025-04-17_1600_committee-meeting_mid-124789/files/hmh.pdf"
    )
    assert hmh.r2_key.startswith("BCSD/")

    extra = by_name["unmapped-extra.pdf"]
    assert extra.agenda_item_code is None  # not in the ## Files map → meeting-level
    assert extra.ocr_status == "ocr_needed"


def test_adapter_without_files_dir_emits_no_attachments(tmp_path):
    folder = tmp_path / "BCSD_BOE_MEETINGS" / "2025" / "04" / "2025-04-17_1830_board-meeting_mid-124791"
    folder.mkdir(parents=True)
    for fname in ("event.md", "minutes.md", "agenda.md"):
        shutil.copy(FIXTURES_DIR / "board" / fname, folder / fname)
    parsed = parse_meeting_folder(folder)
    assert [d for d in parsed.raw_documents if d.is_attachment] == []
```

(If `FIXTURES_DIR` / `shutil` are already imported at the top of the file, don't duplicate them.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_adapter.py -k attachment -q`
Expected: FAIL — attachments list is empty (adapter doesn't enumerate `files/` yet).

- [ ] **Step 3: Implement — enumerate files in the adapter**

In `catalog/ingest/bcsd/adapter.py`, add the import near the top:

```python
from catalog.ingest.bcsd.files import (
    document_kind_for,
    extract_pdf_text,
    r2_key_for,
    title_for,
)
```

Then, after the `items` loop is built (after line 105, before the `return ParsedMeeting(...)`), insert attachment enumeration. It inverts the per-item `file_names` already computed into a filename→code map, then walks the `files/` dir:

```python
    # Attachments: invert the per-item file map (filename -> item code), then walk files/.
    code_by_file: dict[str, str] = {}
    for item in items:
        for fname in item.file_names:
            code_by_file.setdefault(fname, item.code)

    files_dir = folder / "files"
    if files_dir.is_dir():
        for path in sorted(p for p in files_dir.iterdir() if p.is_file()):
            text, ocr_status = ("", "unknown")
            if path.suffix.lower() == ".pdf":
                text, ocr_status = extract_pdf_text(path)
            raw_documents.append(
                ParsedDocument(
                    kind=document_kind_for(path.name),
                    title=title_for(path.name),
                    source_path=str(path),
                    text=text,
                    r2_key=r2_key_for(path),
                    ocr_status=ocr_status,
                    agenda_item_code=code_by_file.get(path.name),
                    is_attachment=True,
                )
            )
```

Note: `raw_documents` is a `list` at this point in the function (the source `.md` docs were appended to it), so `.append` is valid; it is converted to a tuple in the `ParsedMeeting(...)` call.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest catalog/tests/test_bcsd_adapter.py -q`
Expected: PASS (existing adapter tests + 2 new).

- [ ] **Step 5: Commit**

```bash
uv run ruff check catalog/ingest/bcsd/adapter.py catalog/tests/test_bcsd_adapter.py && uv run ruff format catalog/ingest/bcsd/adapter.py catalog/tests/test_bcsd_adapter.py
git add catalog/ingest/bcsd/adapter.py catalog/tests/test_bcsd_adapter.py
git commit -m "feat: enumerate files/ into attachment ParsedDocuments"
```

---

## Task 5: `storage.py` — `upload_missing`

**Files:**
- Create: `catalog/ingest/storage.py`
- Test: `catalog/tests/test_ingest_storage.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_ingest_storage.py`:

```python
from unittest import mock

from django.core.files.storage import FileSystemStorage

from catalog.ingest import storage


def test_upload_missing_skips_when_object_exists(tmp_path):
    local = tmp_path / "a.pdf"
    local.write_bytes(b"%PDF-1.4 x")
    fake = mock.Mock()
    fake.exists.return_value = True
    with mock.patch.object(storage, "default_storage", fake):
        uploaded = storage.upload_missing("BCSD/x/a.pdf", str(local))
    assert uploaded is False
    fake.save.assert_not_called()


def test_upload_missing_uploads_when_absent(tmp_path):
    local = tmp_path / "a.pdf"
    local.write_bytes(b"%PDF-1.4 x")
    fake = mock.Mock()
    fake.exists.return_value = False
    with mock.patch.object(storage, "default_storage", fake):
        uploaded = storage.upload_missing("BCSD/x/a.pdf", str(local))
    assert uploaded is True
    assert fake.save.call_count == 1
    assert fake.save.call_args[0][0] == "BCSD/x/a.pdf"


def test_upload_missing_noops_on_filesystem_backend(tmp_path):
    local = tmp_path / "a.pdf"
    local.write_bytes(b"%PDF-1.4 x")
    fs = FileSystemStorage(location=str(tmp_path / "store"))
    with mock.patch.object(storage, "default_storage", fs):
        uploaded = storage.upload_missing("BCSD/x/a.pdf", str(local))
    assert uploaded is False  # never writes when storage is the local fallback
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest catalog/tests/test_ingest_storage.py -q`
Expected: FAIL — `ModuleNotFoundError: catalog.ingest.storage`.

- [ ] **Step 3: Implement**

Create `catalog/ingest/storage.py`:

```python
"""Idempotent R2 backfill. Generic (no BCSD knowledge): the caller supplies the
already-computed key. No-ops when storage is the local filesystem fallback so
offline dev/CI never touch the network."""

import logging

from django.core.files import File
from django.core.files.storage import FileSystemStorage, default_storage

logger = logging.getLogger(__name__)


def upload_missing(r2_key: str, local_path: str) -> bool:
    """Upload local_path to r2_key only if the object is absent. Returns True iff
    bytes were uploaded."""
    if isinstance(default_storage, FileSystemStorage):
        logger.debug("Filesystem storage fallback; skipping upload of %s", r2_key)
        return False
    if default_storage.exists(r2_key):
        return False
    with open(local_path, "rb") as fh:
        default_storage.save(r2_key, File(fh))
    logger.info("Uploaded missing object to R2: %s", r2_key)
    return True
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest catalog/tests/test_ingest_storage.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
uv run ruff check catalog/ingest/storage.py catalog/tests/test_ingest_storage.py && uv run ruff format catalog/ingest/storage.py catalog/tests/test_ingest_storage.py
git add catalog/ingest/storage.py catalog/tests/test_ingest_storage.py
git commit -m "feat: add idempotent R2 upload_missing helper"
```

---

## Task 6: Loader persists attachment Documents

**Files:**
- Modify: `catalog/ingest/loader.py`
- Test: `catalog/tests/test_ingest_loader.py`

- [ ] **Step 1: Write the failing test**

Append to `catalog/tests/test_ingest_loader.py`. It reuses the module's existing `context` fixture (`→ jur, source, body`) and `_sample_meeting()` builder (which already includes an `FSS-3` agenda item), adding two attachment docs via `dataclasses.replace`. Add `import dataclasses` at the top of the module; `ParsedDocument` and `Document` are already imported there.

```python
@pytest.mark.django_db
def test_loader_persists_attachment_documents(context):
    jur, source, body = context
    base = _sample_meeting()  # has agenda item FSS-3 + a minutes source doc
    parsed = dataclasses.replace(
        base,
        raw_documents=base.raw_documents
        + (
            ParsedDocument(
                kind="memo", title="HMH", source_path="/x/files/hmh.pdf", text="chromebooks",
                r2_key="BCSD/x/files/hmh.pdf", ocr_status="has_text",
                agenda_item_code="FSS-3", is_attachment=True,
            ),
            ParsedDocument(
                kind="other", title="Extra", source_path="/x/files/extra.pdf", text="",
                r2_key="BCSD/x/files/extra.pdf", ocr_status="ocr_needed",
                agenda_item_code=None, is_attachment=True,
            ),
        ),
    )
    meeting = load_meeting(parsed, source=source, jurisdiction=jur, body=body)

    docs = Document.objects.filter(meeting=meeting, r2_key__startswith="BCSD/")
    assert docs.count() == 2
    hmh = docs.get(r2_key="BCSD/x/files/hmh.pdf")
    assert hmh.kind == Document.Kind.MEMO
    assert hmh.ocr_status == Document.OCRStatus.HAS_TEXT
    assert hmh.agenda_item.code == "FSS-3"
    extra = docs.get(r2_key="BCSD/x/files/extra.pdf")
    assert extra.agenda_item is None  # meeting-level
    assert extra.ocr_status == Document.OCRStatus.OCR_NEEDED
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest catalog/tests/test_ingest_loader.py -k attachment -q`
Expected: FAIL — only 0 attachment docs created (loader ignores attachment IR).

- [ ] **Step 3: Implement — two edits in `loader.py`**

**Edit A** — skip attachments in the existing source-doc loop. Replace the loop body guard at line 117:

```python
    minutes_doc = None
    for pdoc in parsed.raw_documents:
        if pdoc.is_attachment:
            continue  # attachment docs are created after agenda items exist (see below)
        kind = Document.Kind(pdoc.kind) if pdoc.kind in Document.Kind.values else Document.Kind.OTHER
        doc = Document.objects.create(
            title=pdoc.title,
            kind=kind,
            meeting=meeting,
            source=source,
            source_url=parsed.source_url,
            text=pdoc.text,
            ocr_status=Document.OCRStatus.HAS_TEXT,
        )
        if pdoc.kind == "minutes":
            minutes_doc = doc
```

**Edit B** — build `item_by_code` in the agenda loop, then create attachment docs after it. In the `for pitem in parsed.agenda_items:` loop, immediately after `item = AgendaItem.objects.create(...)` (line 177-186), add:

```python
        item_by_code[pitem.code] = item
```

and declare `item_by_code: dict[str, AgendaItem] = {}` just before that loop (near line 175, alongside the comment).

Then, just before `return meeting` (line 222), add the attachment-doc block:

```python
    # Attachment Documents (created after agenda items so the FK can resolve).
    # The FTS search_vector is populated by a DB trigger (migration 0010).
    for pdoc in parsed.raw_documents:
        if not pdoc.is_attachment:
            continue
        Document.objects.create(
            title=pdoc.title,
            kind=Document.Kind(pdoc.kind) if pdoc.kind in Document.Kind.values else Document.Kind.OTHER,
            meeting=meeting,
            agenda_item=item_by_code.get(pdoc.agenda_item_code),
            source=source,
            r2_key=pdoc.r2_key,
            text=pdoc.text,
            ocr_status=Document.OCRStatus(pdoc.ocr_status),
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest catalog/tests/test_ingest_loader.py -q`
Expected: PASS (existing loader tests + new attachment test).

- [ ] **Step 5: Commit**

```bash
uv run ruff check catalog/ingest/loader.py catalog/tests/test_ingest_loader.py && uv run ruff format catalog/ingest/loader.py catalog/tests/test_ingest_loader.py
git add catalog/ingest/loader.py catalog/tests/test_ingest_loader.py
git commit -m "feat: persist attachment Documents in the loader"
```

---

## Task 7: FTS `search_vector` trigger migration

**Files:**
- Create: `catalog/migrations/0010_document_search_vector_trigger.py`
- Test: `catalog/tests/test_document.py`

- [ ] **Step 1: Write the failing test**

Append to `catalog/tests/test_document.py`:

```python
import pytest
from django.contrib.postgres.search import SearchQuery

from catalog.models import Document


@pytest.mark.django_db
def test_search_vector_trigger_populates_on_insert():
    doc = Document.objects.create(title="Lightspeed Renewal", text="chromebooks for students")
    # Title (weight A) is searchable.
    assert Document.objects.filter(search_vector=SearchQuery("lightspeed")).filter(pk=doc.pk).exists()
    # Body text (weight B) is searchable.
    assert Document.objects.filter(search_vector=SearchQuery("chromebooks")).filter(pk=doc.pk).exists()


@pytest.mark.django_db
def test_search_vector_trigger_updates_on_text_change():
    doc = Document.objects.create(title="Doc", text="microsoft")
    doc.text = "lenovo lease"
    doc.save()
    assert Document.objects.filter(search_vector=SearchQuery("lenovo")).filter(pk=doc.pk).exists()
    assert not Document.objects.filter(search_vector=SearchQuery("microsoft")).filter(pk=doc.pk).exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest catalog/tests/test_document.py -k search_vector -q`
Expected: FAIL — `search_vector` is NULL (no trigger), so the queries match nothing.

- [ ] **Step 3: Create the migration**

Create `catalog/migrations/0010_document_search_vector_trigger.py`:

```python
from django.db import migrations

_FORWARD = r"""
CREATE FUNCTION catalog_document_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.text, '')), 'B');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER document_search_vector_trigger
BEFORE INSERT OR UPDATE ON catalog_document
FOR EACH ROW EXECUTE FUNCTION catalog_document_search_vector_update();
"""

_REVERSE = r"""
DROP TRIGGER IF EXISTS document_search_vector_trigger ON catalog_document;
DROP FUNCTION IF EXISTS catalog_document_search_vector_update();
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0009_schema_hardening")]
    operations = [migrations.RunSQL(sql=_FORWARD, reverse_sql=_REVERSE)]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest catalog/tests/test_document.py -q`
Expected: PASS.

- [ ] **Step 5: Confirm no model changes were missed**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected" (the trigger is data-layer only; the model is unchanged).

- [ ] **Step 6: Commit**

```bash
git add catalog/migrations/0010_document_search_vector_trigger.py catalog/tests/test_document.py
git commit -m "feat: maintain Document.search_vector via Postgres trigger"
```

---

## Task 8: Command — `--upload` flag + post-commit upload + doc count

**Files:**
- Modify: `catalog/management/commands/ingest_bcsd.py`
- Test: `catalog/tests/test_ingest_bcsd_command.py`

- [ ] **Step 0: Extend `_stage_pair` to stage a committee `files/` dir (needed by this task's test and Task 9)**

Add the import at the top of `catalog/tests/test_ingest_bcsd_command.py`:

```python
from catalog.tests.fixtures.pdfs import write_empty_pdf, write_text_pdf
```

Replace `_stage_pair` with a version that also writes two PDFs into the committee folder's `files/` (a mapped text PDF + an empty one):

```python
def _stage_pair(tmp_path):
    """Lay out the two meeting folders as the archive does, with a committee files/ dir."""
    specs = [
        ("committee", "2025-04-17_1600_committee-meeting_mid-124789"),
        ("board", "2025-04-17_1830_board-meeting_mid-124791"),
    ]
    root = tmp_path / "BCSD_BOE_MEETINGS" / "2025" / "04"
    for fixture, folder_name in specs:
        dst = root / folder_name
        dst.mkdir(parents=True)
        for fname in ("event.md", "minutes.md", "agenda.md"):
            shutil.copy(FIXTURES_DIR / fixture / fname, dst / fname)
    # Stage two real attachments into the committee folder. hmh.pdf is referenced
    # by committee/event.md's ## Files map (→ FSS-3); the empty one is unmapped.
    # Only 2 of the 60+ mapped files exist on disk → exercises the "map entry,
    # no file on disk → skipped" path for free.
    committee_files = root / "2025-04-17_1600_committee-meeting_mid-124789" / "files"
    committee_files.mkdir()
    write_text_pdf(committee_files / "hmh.pdf")
    write_empty_pdf(committee_files / "unmapped-extra.pdf")
    return root
```

The two pre-existing tests (`test_command_ingests_both_meetings`, `test_command_is_idempotent`) keep passing — they don't assert on attachments, and re-ingest wipes + recreates attachment Documents.

- [ ] **Step 1: Write the failing test**

Append to `catalog/tests/test_ingest_bcsd_command.py` (it already imports `call_command`, `pytest`, `shutil`, `FIXTURES_DIR`, and `Meeting`):

```python
from unittest import mock


@pytest.mark.django_db
def test_command_uploads_only_with_flag(tmp_path):
    root = _stage_pair(tmp_path)  # Step 0 made this stage the committee files/ dir
    folder = str(root / "2025-04-17_1600_committee-meeting_mid-124789")

    # Default: no --upload → storage is never touched (keeps tests offline).
    with mock.patch("catalog.management.commands.ingest_bcsd.upload_missing") as up:
        call_command("ingest_bcsd", folder)
    up.assert_not_called()

    # With --upload → upload_missing is called for each attachment.
    with mock.patch(
        "catalog.management.commands.ingest_bcsd.upload_missing", return_value=False
    ) as up:
        call_command("ingest_bcsd", folder, "--upload")
    assert up.call_count >= 1
    # Keys are the BCSD/ convention.
    assert all(c.args[0].startswith("BCSD/") for c in up.call_args_list)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest catalog/tests/test_ingest_bcsd_command.py -k upload -q`
Expected: FAIL — `upload_missing` is not imported in the command / `--upload` unknown.

- [ ] **Step 3: Implement**

In `catalog/management/commands/ingest_bcsd.py`:

Add import:

```python
from catalog.ingest.storage import upload_missing
```

Add the flag in `add_arguments`:

```python
        parser.add_argument(
            "--upload",
            action="store_true",
            help="Upload attachment files to R2 where missing (default: off).",
        )
```

After `meeting = load_meeting(...)` and before the success write, add the upload pass + counts:

```python
        attachments = [d for d in parsed.raw_documents if d.is_attachment]
        uploaded = 0
        if options["upload"]:
            for pdoc in attachments:
                if pdoc.r2_key and upload_missing(pdoc.r2_key, pdoc.source_path):
                    uploaded += 1
```

Extend the success message to report documents (and uploads when relevant):

```python
        self.stdout.write(
            self.style.SUCCESS(
                f"Ingested {meeting} (mid={meeting.source_meeting_id}): "
                f"{meeting.agenda_items.count()} items, "
                f"{sum(i.votes.count() for i in meeting.agenda_items.all())} votes, "
                f"{meeting.appearances.count()} appearances, "
                f"{len(attachments)} attachment docs "
                f"({uploaded} uploaded to R2) (all reviewed=False)."
            )
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest catalog/tests/test_ingest_bcsd_command.py -k upload -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check catalog/management/commands/ingest_bcsd.py catalog/tests/test_ingest_bcsd_command.py && uv run ruff format catalog/management/commands/ingest_bcsd.py catalog/tests/test_ingest_bcsd_command.py
git add catalog/management/commands/ingest_bcsd.py catalog/tests/test_ingest_bcsd_command.py
git commit -m "feat: add --upload flag and attachment-doc reporting to ingest_bcsd"
```

---

## Task 9: E2E — stage `files/` and assert attachment ingest

**Files:**
- Modify: `catalog/tests/test_ingest_bcsd_command.py`

> `_stage_pair` was already extended to stage the committee `files/` dir in Task 8 Step 0; this task only adds the e2e assertion test.

- [ ] **Step 1: Add the e2e assertions test**

Append (add these imports at the top of the module if not already present):

```python
from django.contrib.postgres.search import SearchQuery

from catalog.models import Document


@pytest.mark.django_db
def test_command_ingests_attachment_documents(tmp_path):
    root = _stage_pair(tmp_path)
    call_command("ingest_bcsd", str(root / "2025-04-17_1600_committee-meeting_mid-124789"))

    committee = Meeting.objects.get(source_meeting_id="124789")
    attachments = Document.objects.filter(meeting=committee, r2_key__startswith="BCSD/")
    # Exactly the two files staged on disk (the other mapped files are silently skipped).
    assert attachments.count() == 2

    hmh = attachments.get(r2_key__endswith="/files/hmh.pdf")
    assert hmh.agenda_item is not None and hmh.agenda_item.code == "FSS-3"
    assert hmh.ocr_status == Document.OCRStatus.HAS_TEXT
    # search_vector populated by the trigger → full-text query matches.
    assert attachments.filter(search_vector=SearchQuery("chromebooks")).filter(pk=hmh.pk).exists()

    extra = attachments.get(r2_key__endswith="/files/unmapped-extra.pdf")
    assert extra.agenda_item is None
    assert extra.ocr_status == Document.OCRStatus.OCR_NEEDED

    # Nothing auto-reviewed.
    assert not attachments.filter(reviewed=True).exists()
```

- [ ] **Step 2: Run the whole command test module**

Run: `uv run pytest catalog/tests/test_ingest_bcsd_command.py -q`
Expected: PASS — the existing two tests (now staging `files/`), the upload-flag test, and the new attachment test. (The pre-existing `test_command_is_idempotent` still passes: re-ingest wipes + recreates the attachment Documents too.)

- [ ] **Step 3: Commit**

```bash
uv run ruff check catalog/tests/test_ingest_bcsd_command.py && uv run ruff format catalog/tests/test_ingest_bcsd_command.py
git add catalog/tests/test_ingest_bcsd_command.py
git commit -m "test: e2e attachment-document ingest with FTS and linkage"
```

---

## Task 10: Full verification + handoff update

**Files:**
- Modify: `docs/superpowers/HANDOFF.md`

- [ ] **Step 1: Run all four verify gates**

```bash
uv run pytest -q
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run ruff check . && uv run ruff format --check .
```
Expected: all green; pytest count up by the new tests (~13 added); "No changes detected"; ruff clean.

- [ ] **Step 2: Optional real-archive smoke test (manual, not CI)**

```bash
uv run python manage.py ingest_bcsd \
  archive_data/bcsd/BCSD_BOE_MEETINGS/2025/04/2025-04-17_1600_committee-meeting_mid-124789
```
Expected output mentions `64 attachment docs (0 uploaded to R2)` (no `--upload`, so zero uploads; all 64 files already exist in `civpulse-data`). Add `--upload` to verify the existence-check path against the live bucket (still 0 uploads, since everything is present).

- [ ] **Step 3: Update the handoff**

Edit `docs/superpowers/HANDOFF.md`: mark slice 1c complete; record the new test count; note carry-forwards still open (actual OCR → Phase 2; PPTX/PPT/extension-less text; Source C standalone docs/policies; the 1b carry-forwards). Point "Immediate next task" at **slice 1d** (recordings: `info.json` → MediaAsset, VTT dedup importer, §6 matcher → MeetingCoverage).

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/HANDOFF.md
git commit -m "docs: mark slice 1c complete; point handoff at slice 1d"
```

- [ ] **Step 5: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill to merge `feat/1c-documents-fts` → `main` and push (pushing `main` is expected for this project).

---

## Self-review notes (for the implementer)

- **Spec coverage:** §3 deps (Task pre-done), §5 IR (T1), §6 extraction/classification (T3), §7 key + upload (T2/T5/T8), §8 linkage/kind/title (T2/T4/T6), §9 FTS trigger (T7), §10 idempotency (covered by the existing wipe + T9's idempotency test), §11 tests (T2–T9). All mapped.
- **Two deliberate spec refinements** (consistent with approved decisions): r2_key is self-locating on the `BCSD_` component rather than via a passed `archive_root` flag; upload is an opt-in `--upload` command step run after the transaction (not inside the loader) — keeps network I/O out of the atomic block and out of tests.
- **Type consistency:** `extract_pdf_text` returns `(text, status)` everywhere; `ParsedDocument` attachment fields (`r2_key`, `ocr_status`, `agenda_item_code`, `is_attachment`) are used identically in adapter, loader, and command; IR `ocr_status`/`kind` strings map 1:1 to `Document.OCRStatus`/`Document.Kind` values (verified).
- **Watch:** `default_storage` is the live S3 backend in tests (because `.env` has `R2_BUCKET`) — never exercise it unmocked; the `--upload` default-off gate plus the storage-helper mocks keep the suite offline.
