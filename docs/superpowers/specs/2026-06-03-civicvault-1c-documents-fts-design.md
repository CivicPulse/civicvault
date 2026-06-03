# CivicVault — Slice 1c: Documents + OCR-flag + FTS — Design

**Date:** 2026-06-03. **Status:** approved (brainstorm), pending spec review → implementation plan.
**Roadmap:** `docs/superpowers/specs/2026-06-01-civicvault-mvp-plan-design.md` (Phase 1, sub-slice 1c).
**Brief:** `project_brief.md` §8 (ingestion pipeline), §8.1 (OCR verification), §7 (Document model).
**Predecessor:** slice 1b (BCSD Source-A parser) — merged to `main`. This slice consumes the IR and loader it produced.

## 1. Goal

Materialize the meeting's file attachments as searchable `Document` rows for the 04/17/2025
committee + board pair: walk each meeting folder's `files/`, create one `Document` per file
(linked to the Meeting and — where the `event.md ## Files` map says so — to an `AgendaItem`),
extract a searchable text layer from PDFs, classify each PDF's OCR status, ensure the binary
exists in R2, and populate the Postgres full-text `search_vector`.

"MVP done" for 1c: a real meeting's attachments are rows you can full-text search, each linked
to its meeting/agenda-item and each carrying a stable `r2_key` to its bytes in R2.

## 2. Scope decisions (locked during brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| OCR | **Detect & flag only** | Measure the text layer; flag `ocr_needed`. Actual OCR (ocrmypdf/Tesseract) is Phase 2's "OCR pass across all PDFs flagged `ocr_needed`". Keeps 1c dependency-light. |
| File storage | **R2 upload-where-missing** | Files already live in bucket `civpulse-data`; ingest verifies presence and only uploads gaps. For the target meeting all 68 files are already present → zero uploads. |
| Text extraction | **PDFs only** | 57+3 committee + 3 board files are PDFs. PPTX/PPT/extension-less get a `Document` row but `text=""`, `ocr_status=unknown`, deferred. |
| Structure | **Approach A** | Adapter extracts + classifies + resolves linkage (source-specific, pure); generic loader persists + uploads. Preserves the 1b adapter/loader seam. |
| FTS maintenance | **Postgres trigger** | `search_vector` stays correct on every write, including later admin edits — not just the ingest path. |

## 3. New dependencies

- `pypdf` — PDF text-layer extraction + per-page char measurement. Pure-Python, MIT, no system
  libraries. Correct tool for *flag-only* OCR detection (we measure text, not render images).
- `boto3` — required by the `django-storages` S3 backend that talks to R2. Currently
  `django-storages` is declared but `boto3` is absent, so the S3 backend would fail at runtime.

Add via `uv add pypdf boto3`.

## 4. Architecture & components

The data flow extends the existing 1b pipeline; new/changed units in **bold**:

```
ingest_bcsd command
   └─ parse_meeting_folder(folder, archive_root)   [bcsd/adapter.py]
        ├─ (existing) event.md / minutes.md / agenda.md parse
        └─ **enumerate files/ → ParsedDocument attachments**   [bcsd/files.py + adapter.py]
              ├─ compute r2_key (BCSD/<archive-relative-path>)
              ├─ extract_pdf_text(path) → (text, ocr_status)   [bcsd/files.py]
              └─ resolve agenda_item_code via the ## Files map
   └─ load_meeting(parsed)   [ingest/loader.py]
        ├─ (existing) wipe+recreate meeting facts & source .md Documents
        ├─ **create attachment Document rows (FKs, r2_key, text, ocr_status)**
        └─ **upload_missing(r2_key, local_path) per attachment**   [ingest/storage.py]
   DB trigger keeps Document.search_vector fresh   [migration]
```

Boundaries (each unit: what it does / how you use it / what it depends on):

- **`bcsd/files.py` (new, pure).** `extract_pdf_text(path) -> (text: str, ocr_status: str)` and
  `r2_key_for(local_path, archive_root) -> str` and `document_kind_for(filename) -> str`. Depends
  only on `pypdf` + stdlib. No Django, no DB, no network → fully unit-testable.
- **`bcsd/adapter.py` (extended).** Gains an `archive_root` parameter; after the existing parse,
  enumerates `files/`, calls `files.py` helpers, resolves linkage from the `## Files` map, and
  appends attachment `ParsedDocument`s to the meeting IR. Stays pure (filesystem read only).
- **`ingest/ir.py` (extended).** `ParsedDocument` gains attachment fields (see §5).
- **`ingest/loader.py` (extended).** Persists attachment Documents inside the existing
  wipe/recreate block; calls the storage helper. Stays source-agnostic — it never computes a key
  or knows about `BCSD/`; the key arrives on the IR.
- **`ingest/storage.py` (new).** `upload_missing(r2_key, local_path)`: idempotent R2 backfill via
  `django.core.files.storage.default_storage`. Mockable; no-ops when R2 is unconfigured.
- **Migration.** Adds the `search_vector` maintenance trigger.

## 5. IR change (`ParsedDocument`)

```python
@dataclass(frozen=True)
class ParsedDocument:
    kind: str                     # existing: "minutes" | "agenda" | "other" | + heuristic kinds
    title: str
    source_path: str
    text: str
    # --- new attachment fields (defaults keep .md source docs working) ---
    r2_key: str = ""
    ocr_status: str = "unknown"   # "has_text" | "ocr_needed" | "empty" | "unknown"
    agenda_item_code: str | None = None   # None → meeting-level (no AgendaItem FK)
    is_attachment: bool = False
```

Existing `.md` source Documents (minutes/agenda) are emitted exactly as before — they simply leave
the new fields at their defaults and `is_attachment=False`.

## 6. Text extraction & OCR classification (`extract_pdf_text`)

Using `pypdf`:

1. Open the PDF. If it has **0 pages** → `("", "empty")`.
2. Extract text from every page; concatenate. Let `total = len(text.strip())`, `pages = n`.
3. Classify:
   - `total == 0` → `ocr_needed` (a scanned/image-only PDF: pages but no text layer).
   - `total / pages < MIN_CHARS_PER_PAGE` → `ocr_needed` (sparse text layer).
   - else → `has_text`.
4. `MIN_CHARS_PER_PAGE = 50` (the brief's "a few dozen chars/page"), defined as a named module
   constant so it is tunable without touching logic.

A corrupt/unreadable PDF (pypdf raises) → log a warning and emit `("", "unknown")` rather than
crashing the whole meeting; the row still exists with its `r2_key` for a later pass. (This is a
deliberate, narrow exception to the loader's fail-loud stance: a single bad attachment must not
abort an otherwise-good meeting ingest. Parser/data bugs in the *structured* facts stay fail-loud.)

Non-PDF files skip extraction entirely → `text=""`, `ocr_status="unknown"`.

## 7. R2 key convention & upload-where-missing

**Key:** `r2_key = "BCSD/" + <file path relative to the BCSD archive root>`, where the archive
root (default `archive_data/bcsd`, overridable via a command flag) is the local directory that
maps to the bucket's `BCSD/` prefix. Verified against the live bucket, e.g.:

```
local : archive_data/bcsd/BCSD_BOE_MEETINGS/2025/04/<folder>/files/hmh.pdf
r2_key:                BCSD/BCSD_BOE_MEETINGS/2025/04/<folder>/files/hmh.pdf
```

(The lowercase local `bcsd/` dir maps to the uppercase `BCSD/` key prefix — an easy-to-miss
mismatch, called out explicitly so the idempotency check actually matches existing objects.)

**`upload_missing(r2_key, local_path)`:**
- If `default_storage` is the **filesystem** fallback (no `R2_BUCKET` configured) → no-op + debug
  log. Offline dev/CI never touches the network.
- Else `if not default_storage.exists(r2_key): default_storage.save(r2_key, File(open(local_path,'rb')))`.
- For the target meeting all 68 keys already exist → every call is a cheap existence check, zero
  uploads.

R2 credentials for real runs come from `.env` (`R2_BUCKET=civpulse-data`, `R2_ENDPOINT_URL`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`); the rclone `civdata` remote already holds working
credentials for the same account. Wiring `.env` is an operator step, not a code change.

## 8. Document linkage, kind, title

- **Linkage.** Reuse the adapter's existing `_files_for_item` word-boundary map (the 1b
  `FSS-1`/`FSS-10` fix). A file referenced by the `## Files` map → `agenda_item_code` of that item
  (at most one). A file on disk **not** in the map → `agenda_item_code=None` (meeting-level).
- **Map entry with no file on disk** → skip with a logged warning. The `## Files` map legitimately
  lists more than the staged/synced files (the test fixtures stage only a few PDFs); this must not
  fail the ingest.
- **Kind** via light filename heuristics on the slug: contains `policy`/`regulation` → `policy`;
  contains `memo` → `memo`; `.pptx`/`.ppt` or contains `presentation` → `presentation`; else
  `other`. (`Document.Kind` already defines these values.)
- **Title** = the filename stem, de-slugified to a readable string (hyphens → spaces, title-cased),
  matching how the source presents it; raw filename retained implicitly via `r2_key`.

## 9. FTS trigger (migration)

A migration runs raw SQL creating a trigger function that maintains `search_vector` on
INSERT/UPDATE of `Document`:

```sql
search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.text,  '')), 'B');
```

- Trigger fires `BEFORE INSERT OR UPDATE`. The GIN index `gin_document_search` (already migrated)
  serves queries.
- Chosen over a one-shot `Document.objects.update(search_vector=SearchVector(...))` in the loader
  because Documents will be edited during admin review (Phase 3); a trigger keeps the index correct
  for *all* writers, the loader's wipe/recreate included. `reverse_sql` drops the trigger + function.

## 10. Idempotency

The loader already deletes `Document.objects.filter(meeting=meeting)` (cascading their Citations)
and recreates them each run. Attachment Documents ride that exact path → re-ingest is idempotent
with no new bookkeeping. `r2_key`'s partial-unique constraint is satisfied because the prior rows
are deleted before recreation within the same atomic transaction. R2 objects are never deleted
(content is immutable at a key); only created-if-missing.

## 11. Testing strategy

- **Fixtures.** Add 2 tiny committed PDFs under `catalog/tests/fixtures/bcsd/committee/files/`:
  one with a real text layer (→ `has_text`) whose filename matches a `## Files` map entry so it
  links to an AgendaItem, and one near-empty/no-text (→ `ocr_needed`). Extend `_stage_pair` to copy
  the `files/` dir. Staging only 2 of the 64 mapped files also exercises the "map entry, no file on
  disk → skip" path for free.
- **Unit (`bcsd/files.py`), no DB/network:** `extract_pdf_text` returns `has_text`/`ocr_needed`/
  `empty`/`unknown` for the right inputs; `r2_key_for` produces the verified `BCSD/...` keys;
  `document_kind_for` maps the heuristics.
- **Loader/integration:** attachment Documents created with correct meeting/agenda_item FKs,
  `r2_key`, `text`, `ocr_status`; a `Document.objects.filter(search_vector=SearchQuery(...))` query
  matches the text-layer fixture (proves the trigger fires); meeting-level vs item-level linkage.
- **Storage helper:** `upload_missing` skips when the object exists and uploads when absent, both
  against a mocked `default_storage`; no-ops under filesystem fallback.
- **E2E (`test_ingest_bcsd_command.py`):** after ingest, attachment Documents exist for the staged
  files, the unstaged-but-mapped files are silently skipped, and `reviewed` stays False throughout.

Verify gates (all must pass before "done"): `uv run pytest -q`, `manage.py check`,
`makemigrations --check --dry-run`, `ruff check` + `ruff format --check`.

## 12. Out of scope (carry-forward)

- **Actual OCR** of `ocr_needed` PDFs → Phase 2.
- **PPTX/PPT/extension-less text extraction** → later slice (rows exist now with `unknown` status).
- **Source C** standalone docs (`BCSD_DOCS/`, `BCSD_POLICIES/` with policy-code linking) → later.
- **Vendor/Organization NER** from outcome paragraphs → later.
- **Consent-anchor vote attachment, procedural-section items, same-name Person collisions** —
  unchanged 1b carry-forwards; not touched here.
