# CivicVault — Session Handoff

**Written:** 2026-06-01. **Read this first if you are a fresh agent continuing CivicVault.**

## What CivicVault is

A public, anonymous-access civic knowledge base for local government — meetings, documents, people, orgs, money, and the relationships between them — with **provenance** as the hard rule (every asserted fact links to its source). First dataset: the Bibb County (GA) Board of Education. Agency-agnostic core; new agencies are added via ingestion adapters.

**Source of truth for the whole design:** `project_brief.md` (root). It is the spec — sections are referenced as §N throughout. Do not re-litigate its locked tech decisions (§3): Postgres (FTS + edges + jobs), Django + DRF, server-rendered templates + HTMX + Alpine, Sigma.js graph, Cloudflare R2 (`django-storages`), Procrastinate jobs, Splink entity resolution, faster-whisper, K8s + CloudNativePG deploy.

## Where we are

**MVP roadmap (approved):** `docs/superpowers/specs/2026-06-01-civicvault-mvp-plan-design.md`
6 phases, **vertical-slice-first**. Locked decisions: vertical slice first; YouTube captions + Whisper-for-gaps-only; full Splink in MVP; production deploy is the final phase (local/staging until then).

**Done and merged to `main` (pushed):** Phase 0 + Phase 1a.
- **Phase 0:** pytest+pytest-django harness; Cloudflare R2 storage wiring (`civicvault/storage.py`, filesystem fallback when no bucket); GitHub Actions CI (`.github/workflows/ci.yml`, Postgres service).
- **Phase 1a:** the `catalog` Django app — the agency-agnostic domain schema. 14 models across `catalog/models/*.py`: abstract `TimeStamped`/`Reviewable` bases; `Jurisdiction`, `Source` (§14.5 multi-agency); `Organization`, `Person` (slug namespacing); `Meeting`, `AgendaItem` (`kind_from_slug`); `MediaAsset`, `Transcript`, `TranscriptSegment`, `MeetingCoverage`; `Document` (FTS columns + GIN index, unpopulated); `Vote`, `Appearance` (reviewable facts); `Citation` (generic-FK provenance backbone). All in admin. Migrations 0001→0007. **23 tests pass.**

The plan that produced Phase 0+1a (with full task detail and a "Carry into slice 1b" section): `docs/superpowers/plans/2026-06-01-civicvault-foundation-schema.md`.

## Immediate next task: slice 1b — the BCSD Source-A parser

Drive the verified **04/17/2025 committee + board** meeting pair end-to-end (it's the brief's known-good fixture). Parse, behind a clean **ingestion-adapter boundary** (§14.7), so agency #2 is a new adapter not a refactor:
- Folder-name → date/start_time/type-slug→kind/MeetingID (§4.1).
- `event.md` → metadata + the `## Files` filename→agenda-item map (§5.1).
- `minutes.md` → attendance roster, per-item outcome_text/status, motion movers/seconders (**all four motion-block variants**, §5.2), per-person roll-call → `Vote`s, invocation/pledge/visitor → `Appearance`s.
- `agenda.md` fallback when `minutes.md` is absent (§5.3).
- Emit proposed `Person`/`Organization` mentions; write everything `reviewed=False`; emit a `Citation` (→ the `minutes.md` `Document`, page where available) for every materialized `Vote`/`Appearance`. The shape is encoded by `catalog/tests/test_provenance_smoke.py`.

**Apply these BEFORE any bulk load (from the Phase 1a final review — see the plan's "Carry into slice 1b" section):**
1. Partial unique on `Document.r2_key` and `MediaAsset.r2_key` (`condition=~Q(r2_key="")`).
2. A uniqueness story for `Meeting.slug` (mirror the `Organization` partial-unique pattern) before the public-URL slice.
3. `CheckConstraint` bounding `confidence` to 0.0–1.0.
4. Tidy `Meeting.SLUG_TO_KIND`: define the map inside the class body, drop the module global + post-class reassignment (cosmetic; current form is correct).

**Real archive data is local:** `archive_data/bcsd/` (BCSD_BOE_MEETINGS = 22,241 files / 2,709 dirs; BCSD_MEETING_RECORDINGS = 425; BCSD_POLICIES = 307; BCSD_DOCS = 71). The 04/17/2025 committee + board folders live under `archive_data/bcsd/BCSD_BOE_MEETINGS/2025/04/`.

Slices after 1b (each its own plan, authored against then-real code): 1c document+OCR+FTS, 1d recordings/VTT-dedup/matcher, 1e public read UI. Then Phase 2 broaden, Phase 3 Splink, Phase 4 polish, Phase 5 deploy.

## How to work (project conventions — also in `claude.md`)

- **Always `uv run`** for Python/Django (never system python). `uv add` / `uv add --dev` for deps.
- **`ruff`** lint + format; clean before every commit. Migrations and `archive_data` are excluded.
- **Conventional Commits.** Small, focused commits.
- **Git workflow (now codified in `claude.md`):** open short-lived **feature branches**, merge to `main` regularly, **push `main` after merging/committing locally** (pushing IS expected for this project — overrides the global "never push" default), **never force-push**.
- **Process:** this is a superpowers project. For new feature work, the discipline is brainstorm → writing-plans → **subagent-driven-development** (fresh implementer subagent per task + two-stage review: spec compliance, then code quality). The MVP spec already exists, so for 1b go straight to writing a 1b plan against the real schema, then subagent-driven execution. **As controller, evaluate reviewer findings — don't apply them blindly** (during 1a a reviewer's CASCADE suggestion would have introduced a bug; it was correctly rejected).
- **Dev DB:** Postgres via `docker compose up -d db` (host port **5433**; `.env` already points to it; `pg_trgm`/`unaccent` extensions active). Do NOT set `--reuse-db` (the incremental-migration workflow needs a fresh test DB each run).
- **Verify before claiming done:** `uv run pytest -q`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`, `uv run ruff check . && uv run ruff format --check .`.

## Start-of-session checklist

1. `git status` / `git branch` (expect clean `main`, up to date with origin).
2. `docker compose up -d db` then confirm `uv run pytest -q` is green (23 passing).
3. Read `project_brief.md` §4–§6 (BCSD adapter spec) and §5 (file-format specs) before planning 1b.
4. Open a fresh feature branch (e.g. `feat/bcsd-parser`), then plan slice 1b and execute via subagent-driven-development.
