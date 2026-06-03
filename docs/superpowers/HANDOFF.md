# CivicVault — Session Handoff

**Updated:** 2026-06-03. **Read this first if you are a fresh agent continuing CivicVault.**

## What CivicVault is

A public, anonymous-access civic knowledge base for local government — meetings, documents, people, orgs, money, and the relationships between them — with **provenance** as the hard rule (every asserted fact links to its source). First dataset: the Bibb County (GA) Board of Education. Agency-agnostic core; new agencies are added via ingestion adapters.

**Source of truth for the whole design:** `project_brief.md` (root). It is the spec — sections are referenced as §N throughout. Do not re-litigate its locked tech decisions (§3): Postgres (FTS + edges + jobs), Django + DRF, server-rendered templates + HTMX + Alpine, Sigma.js graph, Cloudflare R2 (`django-storages`), Procrastinate jobs, Splink entity resolution, faster-whisper, K8s + CloudNativePG deploy.

**MVP roadmap (approved):** `docs/superpowers/specs/2026-06-01-civicvault-mvp-plan-design.md` — 6 phases, vertical-slice-first.

## Where we are

**Done and merged to `main` (pushed):** Phase 0 (pytest harness, R2 storage wiring, CI) + Phase 1a (the `catalog` agency-agnostic domain schema + generic `Citation` provenance backbone; migrations 0001–0007).

**COMPLETE — slice 1b, the BCSD Source-A parser — merged to `main` and pushed.** All 13 tasks (Task 0–12) implemented, two-stage reviewed, and a final whole-branch review passed (with fixes applied). `uv run pytest -q` → **83 passed**; `makemigrations --check --dry-run` → No changes; `manage.py check` → clean; ruff clean.
- **Plan:** `docs/superpowers/plans/2026-06-01-civicvault-bcsd-parser.md` (13 tasks, Task 0–12).
- **Execution method:** subagent-driven-development — a fresh implementer subagent per task, then a two-stage review (spec-compliance, then code-quality), controller evaluates reviewer findings rather than applying blindly. The two-stage gate caught three real bugs the spec tests missed (see "Review catches" below); the final whole-branch review caught the within-load unique-constraint risk (now fixed — see "Former open risk" below).
- **Shipped (Tasks 0–12):** fixtures in `catalog/tests/fixtures/bcsd/{committee,board}/`; `Motion` model (migration 0008); schema hardening (migration 0009: r2_key/slug uniqueness, confidence-range checks, idempotency keys); the IR (`catalog/ingest/ir.py`); name normalization (`catalog/ingest/names.py`); the BCSD parsers under `catalog/ingest/bcsd/` — `foldername.py`, `event_md.py`, `motions.py` (4 variants), `minutes_md.py`, `agenda_md.py`, `adapter.py`; the generic loader (`catalog/ingest/loader.py`); and the `ingest_bcsd` management command (`catalog/management/commands/ingest_bcsd.py`) with an end-to-end test driving the real 04/17/2025 committee+board pair.
- **Real-archive smoke test (manual, not CI):** committee → 34 items / 0 votes / 9 appearances; board → 20 items / 16 votes / 12 appearances; all `reviewed=False`.

**COMPLETE — slice 1c, Documents + OCR-flag + FTS — merged to `main` and pushed.** All 10 tasks implemented via subagent-driven-development (fresh implementer per task + two-stage spec/quality review + a final whole-branch review). `uv run pytest -q` → **119 passed**; `makemigrations --check --dry-run` → No changes; `manage.py check` → clean; ruff check + format clean.
- **Spec:** `docs/superpowers/specs/2026-06-03-civicvault-1c-documents-fts-design.md`. **Plan:** `docs/superpowers/plans/2026-06-03-civicvault-1c-documents-fts.md` (10 tasks).
- **Shipped:** `pypdf` + `boto3` deps; attachment fields on `ParsedDocument` IR; pure helpers `catalog/ingest/bcsd/files.py` (`r2_key_for`, `document_kind_for`, `title_for`, `extract_pdf_text`); adapter `files/` enumeration → attachment `ParsedDocument`s; generic storage helper `catalog/ingest/storage.py` (`upload_missing`); loader persists attachment `Document` rows (FK to meeting + AgendaItem, `r2_key`/`text`/`ocr_status`); FTS `search_vector` Postgres trigger (migration **0010**, title weight A + text weight B, `english`); opt-in `--upload` command flag; tiny committed PDF byte-fixtures `catalog/tests/fixtures/pdfs.py`.
- **Scope decisions (locked):** OCR = **detect-and-flag only** (actual OCR → Phase 2); text extraction = **PDFs only** (PPTX/PPT/extension-less get a Document row with `ocr_status=unknown`, empty text); storage = **R2 upload-where-missing** (idempotent), opt-in behind `--upload` (OFF by default so the test suite — where `.env` sets `R2_BUCKET` → live S3 — never hits the network); `Document` is **not** `Reviewable` (it's an evidence artifact, not an asserted fact — only Votes/Motions/Appearances are reviewed).
- **R2 key convention (verified vs the live `civpulse-data` bucket):** `r2_key = "BCSD/" + <path from the BCSD_* collection dir onward>`. Implemented self-locating in `r2_key_for` (scans for the `BCSD_*` ancestor) rather than via an `archive_root` param as the spec §4 originally sketched — a deliberate refinement (mount-point-agnostic, no caller threading; spec text not updated, code is the source of truth). Fail-loud: raises `ValueError` if no `BCSD_*` ancestor (never persist an un-keyable attachment).
- **Real-archive smoke test (manual, not CI):** committee `mid-124789` → **64 attachment docs** (53 has_text / 4 ocr_needed / 7 unknown [the 3 pptx + 1 ppt + 3 extension-less non-PDFs]; kinds: 22 policy / 10 memo / 5 presentation / 27 other; 51/64 linked to an agenda item). All files already present in R2 → `--upload` would upload 0.

### Immediate next task: **slice 1d** (not yet planned)
The next vertical slice per the MVP roadmap (`docs/superpowers/specs/2026-06-01-civicvault-mvp-plan-design.md`) is **slice 1d — the recording slice**: locate the recording for 04/17/2025, parse `info.json` → `MediaAsset`, run the **VTT dedup importer** (strip inline tags, collapse YouTube rolling-window repetition into clean non-overlapping segments → `TranscriptSegment`s), run the §6 matcher → `MeetingCoverage` (the combined committee+board recording yields **two** coverage windows with a §6.4 split suggestion); run faster-whisper only if the `.vtt` is missing. Start with brainstorming/writing-plans before implementing. Carry-forward limitations (below) that intersect later slices: consent-anchor vote attachment, procedural-section votes, same-name Person collisions (Phase 3 entity resolution).

### Deferred from slice 1c (carry forward)
- **Actual OCR** of `ocr_needed` PDFs (ocrmypdf/Tesseract) → Phase 2 ("OCR pass across all PDFs flagged `ocr_needed`").
- **PPTX/PPT/extension-less text extraction** → later slice (rows already exist with `ocr_status=unknown`, empty text).
- **Source C** standalone docs (`BCSD_DOCS/`, `BCSD_POLICIES/` with policy-code linking) → later.
- **Vendor/Organization NER** from outcome paragraphs → later.
- **`--upload` against a real R2 backend** is untested in CI (correctly mocked there); the first live `--upload` run is an operator validation step.

## Decisions locked during slice 1b
- **A `Motion` model was added** (user decision): a Reviewable fact on `AgendaItem` (kind simple/initial/amended, moved_by/seconded_by Person FKs, sequence, result_text, status). Citations attach to motions too.
- **Deferred (stated, not built):** file-attachment `Document` rows + text/OCR/FTS → slice 1c (1b captures the `event.md ## Files` map into the IR but materializes only the source `.md` Documents); vendor `Organization` NER → later slice; recordings/MediaAsset/coverage/transcripts → slice 1d.
- **Idempotency model:** loader keys `Meeting` on `(source, source_meeting_id)`; on re-ingest it WIPES the meeting's facts (AgendaItems→Motions/Votes, Appearances, Documents→Citations) and recreates them; shared `Person`/`Source`/`Jurisdiction`/`Organization` are `get_or_create`, never wiped. Correct while everything is `reviewed=False`; revisit once admin review begins.
- **Loader is fail-loud:** unknown vote value / appearance role / empty-slug person → `ValueError` (surfaces parser/data bugs instead of silently corrupting).

## Known limitations surfaced during review (carry forward / flag to user)
1. **Procedural `###` sections are NOT materialized as agenda items.** Only coded `#### ` items become `AgendaItem`s. So motions/roll-calls recorded directly under procedural sections — notably the **board ADJOURN 8-member roll call** and the **"APPROVAL OF AGENDA" initial+amended motion** — are **not captured this slice**. This is coherent (event.md/agenda.md also treat these as sections, so there's nothing to attach them to), but it's a real data gap. If procedural votes are wanted, scope a follow-up that synthesizes agenda items for procedural sections. (The motion parser already correctly handles that block shape — see commit `2b8af00` — so only the adapter/loader side needs the follow-up.)
2. **Cross-meeting same-name Person collision.** Persons are deduped within a load by `slugify(full_name)`. Two distinct real people sharing a name would merge into one `Person`. Resolved later by Splink + admin review (Phase 3).
3. **Non-ASCII person names raise `ValueError`** in the loader (empty slug). Fine for ASCII BCSD board members; a non-Latin agency will need a slug strategy (hash/UUID fallback) added then.
4. **Consent-anchor vote attachment.** The en-bloc consent-agenda roll call is recorded in the source inside the *first* sub-item block (e.g. "Confirmation of Minutes"). The loader therefore attaches all those votes to that one `AgendaItem`, NOT to each individually approved item in the consent block. A query like "how did X vote on FSS-3" will return no `Vote` row even though FSS-3 was approved in that en-bloc roll call. This faithfully reflects the source layout; a follow-up could synthesise a synthetic consent-block `AgendaItem` or fan the votes out to each sub-item, but that is out of scope for slice 1b.

**Former open risk — now FIXED:** within-load `Appearance`/`Vote` unique-constraint collisions (e.g. two roster entries that slugify to the same Person, or a duplicate roll-call entry) previously raised a raw `IntegrityError` that aborted the meeting opaquely. The loader now catches each such `IntegrityError` at all three create sites and immediately re-raises a descriptive `ValueError` naming the offending person and meeting/item. The full transaction still rolls back (same abort behaviour), but the error message is now actionable. Regression tests cover both the duplicate-roster and duplicate-vote paths.

## Review catches worth remembering (why the two-stage gate matters)
- Motion parser: board "APPROVAL OF AGENDA" is an initial+amended pair with NO intervening `Voting:` line → the initial motion was being dropped + the seconder leaked. Fixed (`2b8af00`).
- Adapter `_files_for_item`: substring match made `FSS-1` absorb `FSS-10`/`FSS-11` attachments → fixed to word-boundary regex (`70dde3b`).
- event.md titles: dash-separated codes (`PS-1 - Certified...`) left a leading `"- "` in the title → stripped (`a258a88`).

## How to work (project conventions — also in `claude.md`)
- **Always `uv run`** for Python/Django (never system python). `uv add` / `uv add --dev` for deps.
- **`ruff`** lint + format; clean before every commit. `migrations` and `archive_data` are ruff-excluded.
- **Conventional Commits.** Small, focused commits. **Commit after each task.**
- **Git workflow:** short-lived feature branches; merge to `main` regularly; **push `main` after merging/committing** (pushing IS expected for this project — overrides the global "never push" default); **never force-push**.
- **Process:** superpowers project. Slice 1b is being executed via **subagent-driven-development** (fresh implementer per task + two-stage review). **As controller, evaluate reviewer findings — don't apply them blindly** (e.g. an invocation-regex "fix" that would have broken honorific names was correctly rejected; the `event.md` doc `kind="other"` was kept because no `EVENT` Document.Kind exists).
- **Dev DB:** Postgres via `docker compose up -d db` (host port **5433**; `.env` points to it). Do NOT set `--reuse-db` (the incremental-migration workflow needs a fresh test DB each run).
- **Verify before claiming done:** `uv run pytest -q`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`, `uv run ruff check . && uv run ruff format --check .`.

## Start-of-session checklist (starting slice 1d — 1c is done & merged)
1. `git status` / `git branch` — expect branch `main`, clean tree (untracked `.claude/` is fine).
2. `docker compose up -d db`, then `uv run pytest -q` → expect **119 passing**.
3. Read the MVP roadmap (`docs/superpowers/specs/2026-06-01-civicvault-mvp-plan-design.md`) for the slice 1d scope (recordings: `info.json` → MediaAsset, VTT dedup importer → TranscriptSegments, §6 matcher → MeetingCoverage), and `project_brief.md` §6 (the coverage matcher) + §8 Source-B. The recording sidecars live under `archive_data/bcsd/BCSD_MEETING_RECORDINGS/`.
4. Brainstorm + write a plan for 1d before implementing (superpowers:writing-plans), then execute via subagent-driven-development (fresh implementer per task + two-stage review), same as 1b/1c.
5. Carry-forward limitations to fold into later scope: consent-anchor vote attachment, procedural-section votes, same-name Person collisions (Phase 3 entity resolution); plus the slice-1c deferrals listed above (actual OCR, PPTX/PPT text, Source C docs/policies).
