# CivicVault MVP — Development Plan

**Date:** 2026-06-01
**Status:** Approved (design); pending implementation plan
**Source of truth:** [`project_brief.md`](../../../project_brief.md) — this plan sequences the brief; it does not change any locked decision in it.

## Purpose

Get CivicVault from its current Django skeleton to a usable MVP: a public, anonymous-access civic knowledge base over the Bibb County (GA) Board of Education archive, where a stranger can search the archive, open a person/org/meeting, see source-linked facts and immediate connections, jump to the exact second of a meeting video, and share the URL — no account, on a phone, fast.

The architecture (datastore, framework, search, graph, storage, jobs) is **already locked in §3 of the brief** and is not reopened here. This document fixes the **sequencing and scope** of the build.

## Current state (verified 2026-06-01)

- §12 step 1 (infra skeleton) **mostly done:** Django 6, Postgres dev env (Docker Compose, port 5433, `pg_trgm`/`unaccent` active), 12-factor settings, `/healthz/` liveness check, ruff configured.
- `django-storages` is **installed but not configured** for R2.
- `core/models.py` is **empty** — no domain models yet.
- The real BCSD archive is present locally under `archive_data/bcsd/`: **22,241** meeting files / 2,709 folders (`BCSD_BOE_MEETINGS`), **425** recording sidecar files (`BCSD_MEETING_RECORDINGS`), **307** policy files (`BCSD_POLICIES`), **71** docs (`BCSD_DOCS`).

## Locked plan-shaping decisions

These four decisions were made during brainstorming and shape the phase structure:

1. **Build strategy: vertical slice first.** Drive ONE meeting (the verified 04/17/2025 committee + board pair) all the way through — schema → parse → page → search → video deep-link — before broadening to the full archive. This de-risks the hard integration (recording matching, provenance) early and produces a working site in days, not weeks. Chosen over the brief's layered §12 order and over a "full-schema-first" hybrid.
2. **Transcripts: YouTube captions + Whisper for gaps only.** Use existing `.en.vtt` auto-captions (via a dedup importer); run faster-whisper from FLAC only for recordings missing a `.vtt`. This is the brief's §13 minimum recommendation. Not re-transcribing everything in MVP.
3. **Entity resolution: full Splink in MVP.** Stand up the Splink (DuckDB) probabilistic pipeline with admin review/merge, exactly as §11 #6 specifies — not a deferred/deterministic-only approach.
4. **Deploy target: local/staging MVP, production deploy as the final phase.** Prove the full experience locally (Docker Compose + Postgres, R2 wired), then treat production K8s deploy as a clearly-scoped final phase triggered when ready.

### Why vertical-slice and provenance-day-one do not conflict

A single meeting driven fully end-to-end already exercises ~70% of the §7 schema: Meeting, AgendaItem, Document, Person, Vote, Appearance, MediaAsset, Transcript, TranscriptSegment, MeetingCoverage, **and the generic Citation backbone**. So the slice *forces* provenance to exist immediately — satisfying the brief's hard "provenance from day one" rule without a separate "build all schema first" step. The entities the slice does not need (Award/Bid, Relationship, Affiliation, Office/OfficeTenure, Submission/RecordsRequest) are added as the archive broadens in later phases.

## Phases

### Phase 0 — Finish the infra skeleton

Closes the gaps in §12 step 1 that the vertical slice depends on.

- Wire `django-storages` → Cloudflare R2 (S3 API), driven by environment variables.
- Add pytest and a CI workflow (ruff lint + tests). This is the TDD harness the parsers in Phase 1 require.
- **Procrastinate is deferred to Phase 2.** Slice-1 ingests a single meeting via a one-off management command; a Postgres-backed job queue is unnecessary until ingestion runs at archive scale.

**Exit:** R2 reachable from Django; `pytest` and CI green on the skeleton.

### Phase 1 — The vertical slice: one meeting, end-to-end ⭐

Target: the 04/17/2025 committee + board meeting pair (the brief's known-good fixture). Deliver everything the "MVP done" sentence promises, scoped to this one meeting.

- **1a — Schema + provenance.** The slice's §7 models + migrations + Django admin registration + the generic **Citation** backbone. Includes the §14.5 multi-agency additions now (Jurisdiction/Agency grouping, Source/Collection provenance tag, agency-scoped slug namespacing) — cheap to add now, a painful migration later.
- **1b — Source-A parser (BCSD adapter, TDD).** Folder-name parse, `event.md` (metadata + `## Files` filename→agenda-item map), `minutes.md` (all four motion-block variants, attendance roster, per-person roll call, invocation/pledge/visitor appearances), `agenda.md` fallback. Test-first against the committee + board fixtures. **Built behind a clean ingestion-adapter boundary (§14.7) from the first line** so agency #2 is a new adapter, not a refactor.
- **1c — Documents + OCR + FTS.** Ingest this meeting's `files/`: upsert Document (linked to Meeting + AgendaItem via the `event.md` map), verify OCR/text layer (§8.1), extract text, Postgres FTS (`tsvector` + GIN) indexing.
- **1d — Recording slice.** Locate the recording for that date, parse `info.json` → MediaAsset, run the **VTT dedup importer** (strip inline tags, collapse rolling-window repetition into clean non-overlapping segments), run the §6 matcher → MeetingCoverage. The combined committee+board recording produces **two coverage windows** with a §6.4 split suggestion. Run faster-whisper only if the `.vtt` is missing.
- **1e — Public read UI.** Meeting page (agenda, documents, embedded YouTube, source-linked outcomes), Person and Organization profiles, per-member voting history, search-with-filters over this meeting's documents + transcript segments, **transcript hit → timestamped YouTube deep link** (`watch?v=<id>&t=<start>s`), one-hop ego graph (Sigma.js over a JSON endpoint), canonical shareable URLs throughout.

**Exit:** a working public site for one real meeting — searchable, source-linked, video-deep-linkable, shareable, usable on a phone with no login.

### Phase 2 — Broaden ingestion to the full archive

- Stand up **Procrastinate** (Postgres-backed jobs); make ingestion idempotent (upsert keyed on source IDs / paths).
- **Source A** over all 2,709 meeting folders; harden the parser against real-world variety: varying type-slugs (map known, default `other`), absent `minutes.md` (fall back to `agenda.md`), the full motion-format spread, and name noise (honorifics, double spaces, OCR typos).
- **Source C:** `BCSD_DOCS` (71 standalone docs, light filename heuristics) + `BCSD_POLICIES` (307; read `manifest.json` as authoritative, link policy-related agenda items by policy code).
- **Source B:** all 425 recording sidecar sets; matcher at scale (0/1/2 coverage windows, duplicate/re-upload flagging, unlinked non-meeting videos); faster-whisper for recordings missing a `.vtt`.
- OCR pass across all PDFs flagged `ocr_needed`.

**Exit:** the full BCSD archive ingested as reviewable proposals with citations.

### Phase 3 — Entity resolution at scale (Splink) + publish workflow

- **Splink (DuckDB)** over proposed Persons/Organizations; per-meeting roster seeding as high-precision Person anchors; **global vendor/firm resolution** (the cross-agency payoff); admin review/merge UI; guardrail blocking false cross-agency person merges on name alone (§14.4).
- Enforce the **proposals → admin confirm → public** workflow: facts and their citations are created during ingestion but hidden from the public until reviewed.

**Exit:** canonical, deduped, admin-confirmed entities visible publicly; unreviewed proposals hidden.

### Phase 4 — Scale & polish the public experience

- FTS relevance and filters over the full corpus; pagination and query performance; tuned GIN indexes.
- Ego-graph and profile completeness across real data; shareable-URL coverage; the committee/board **split-confirm** scrubber admin tool polished for routine use.

**Exit:** the §11 MVP experience holds up over the whole archive, fast and complete.

### Phase 5 — Production deploy (final, operator-triggered)

- K8s manifests on the existing cluster; **CloudNativePG** with base-backup + WAL shipping to R2 (point-in-time recovery); Traefik IngressRoute; Cloudflare cache / rate-limit / bot-management rules; `robots.txt` plus an "use the API key instead of scraping" page (the API itself remains deferred).

**Exit:** publicly reachable, backed up, edge-protected — the brief's literal "a stranger can…" criterion met in production.

## Cross-cutting invariants (every phase)

- **Provenance invariant:** every materialized fact carries ≥1 Citation, created at the same time as the fact (§7, §2).
- **Adapter boundary:** all BCSD-specific parsing and matching stays isolated behind the §14.3 adapter contract; the core pipeline (resolution → review → publish → index → graph) is agency-agnostic.
- **Proposals pending review:** ingestion writes facts as proposals with confidence + reviewed flags; nothing is publicly visible until admin-confirmed.
- **TDD against fixtures:** parsers are written test-first against the known-good sample records.
- **YAGNI / deferred:** global interactive graph explorer, public submissions + moderation, calendar/iCal, vendor bid/award dashboards, public API with keys, restricted/premium machinery, and semantic search (pgvector) are all explicitly **out of MVP scope** (§11 Deferred).

## Open verification items to confirm during the build (§13)

- `manifest.json` schema in `BCSD_POLICIES/` (confirm it is the authoritative policy list before Source C).
- Fraction of meeting dates that actually have a recording (determines how prominent the video feature is).
- Multi-upload dedup rule (longest duration + most-complete sidecar set as primary) against a few sampled dates.
- Whether a roster history exists to populate `OfficeTenure` accurately, or tenure spans must be inferred from first/last attendance (flagged as inferred).
