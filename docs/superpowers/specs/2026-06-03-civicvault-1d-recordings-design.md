# CivicVault Slice 1d — Recordings: MediaAsset + VTT dedup + Matcher/Coverage — Design

**Date:** 2026-06-03
**Status:** Approved (design); pending implementation plan
**Source of truth:** [`project_brief.md`](../../../project_brief.md) §5.4–5.6 (recording formats), §6 (the matcher), §7 (media models), §8 Source-B, §9 (gotchas). This slice sequences those; it changes no locked decision.
**Roadmap:** [`2026-06-01-civicvault-mvp-plan-design.md`](2026-06-01-civicvault-mvp-plan-design.md) Phase 1 slice 1d.
**Predecessors:** slice 1b (Source-A parser) and slice 1c (Documents + OCR-flag + FTS), both merged to `main`.

## Purpose

Ingest BCSD meeting **recordings** (Source B) into the catalog: parse the sidecar set
(`info.json` + `.vtt` + media) into a `MediaAsset`, import the YouTube auto-caption transcript
(deduping the rolling-window format) into `TranscriptSegment`s, and run the §6 matcher to map the
recording onto the meeting(s) it covers via `MeetingCoverage` — including the combined
committee+board case that yields **two** coverage windows with an admin-confirmable split suggestion.
This is the data layer behind the brief's headline feature: a transcript hit → a timestamped YouTube
deep link (`watch?v=<id>&t=<start>s`). The public UI that consumes it is slice 1e.

## Critical scope finding (drove the fixture choice)

The 04/17/2025 committee+board pair that slices 1b/1c drove end-to-end **has no recording** in the
local archive: `BCSD_MEETING_RECORDINGS/` holds 60 distinct recordings with upload dates spanning only
**2021-03-18 → 2024-04-18**. The recording demo therefore pivots to **2023-01-19** — which is the exact
recording the brief names as the provided reference fixture (§12), and which exercises every branch
this slice implements in one date:

- **Combined recording** `CWjfBn10EJc`, `duration=13486` (~3h44m), `title="...Committee and Board Meeting 1/19/2023"`, `chapters: None` (no free split point) → two coverage windows + split suggestion.
- **Date drift:** `upload_date=20230120` vs meeting date `2023-01-19` → exercises the §6.2 title-date-preferred-with-window logic.
- **Two matching meeting folders:** committee `mid-107503` + board `mid-107593` under `BCSD_BOE_MEETINGS/2023/01/`.
- **Two non-meeting videos same day:** "Show Up Program" (`8QnY1vw4KTA`, `JCD8moc6V3U`) → the unlinked-MediaAsset branch.
- **Split heuristic feasible:** "call to order" appears at ~line 490 (committee) and ~line 14122 (board, ≈ recording midpoint) in the `.en.vtt`.

The 04/17/2025 anchor is left untouched (it simply has no recording).

## Locked scope decisions (from brainstorming)

1. **Anchor on 2023-01-19** for the recording demo (above).
2. **Build faster-whisper now**, but **opt-in only** (behind `--whisper`, OFF by default) and **mocked in CI** (no model weights downloaded, no network). It runs only when a recording lacks a `.vtt`. The first real FLAC transcription is an operator validation step (as 1c's first live `--upload` was).
3. **Fixture-complete matcher branches only:** combined→two-windows+split, single→one-window, no-match→unlinked. **Defer to Phase 2:** multi-upload duplicate primary-selection / `duplicate_candidate` flagging and the matcher at archive scale.

## Architecture (Approach A: parallel pipeline + agency-agnostic matcher)

Follows the established 1b/1c shape — pure parsers → frozen IR dataclasses → generic loader → thin
command — and preserves the §14.3 adapter boundary: anything that knows BCSD/YouTube file formats
lives under `catalog/ingest/bcsd/`; the generic core (`ir.py`, `loader.py`, `match.py`,
`transcribe.py`) never imports a BCSD module.

| File | Purpose | Boundary |
|---|---|---|
| `catalog/ingest/ir.py` (extend) | Add `ParsedTranscriptSegment`, `ParsedRecording` frozen dataclasses | core (pure) |
| `catalog/ingest/bcsd/recording.py` | Group sidecars by YouTube ID (tolerant of `_.`/`__`); parse `info.json`; parse meeting date from title (§6.2 formats); detect combined → build `ParsedRecording` | adapter (pure) |
| `catalog/ingest/bcsd/vtt.py` | YouTube rolling-window dedup → `tuple[ParsedTranscriptSegment, ...]` | adapter (pure) |
| `catalog/ingest/transcribe.py` | faster-whisper FLAC→segments (opt-in) → same IR shape | core (format-neutral output) |
| `catalog/ingest/match.py` | `match_recording(parsed, candidate_meetings)`; `suggest_split(segments)` | **core (agency-agnostic)** |
| `catalog/ingest/loader.py` (extend) | `load_recording(parsed, decisions, *, source)` persists MediaAsset/Transcript/Segments/Coverage | core |
| `catalog/management/commands/ingest_recording.py` | Thin wiring; `--whisper`, `--upload` flags | adapter |

### IR additions (`catalog/ingest/ir.py`)

```python
@dataclass(frozen=True)
class ParsedTranscriptSegment:
    start: float        # absolute seconds in the recording = YouTube ?t= value
    end: float
    text: str

@dataclass(frozen=True)
class ParsedRecording:
    youtube_id: str
    title: str
    recorded_on: datetime.date | None    # parsed from title (§6.2); preferred anchor
    upload_date: datetime.date | None     # info.json upload_date (fallback anchor)
    duration_seconds: int | None
    source_url: str
    r2_key: str                           # "BCSD/..." convention (see §R2 below); may be ""
    is_combined: bool                     # title contains both "Committee" and "Board"
    segments: tuple[ParsedTranscriptSegment, ...] = ()
    transcript_origin: str = "youtube_captions"  # "youtube_captions" | "whisper" | "" (none → flag)
    source_path: str = ""                 # the .info.json path
```

### Data flow (`ingest_recording`)

```
sidecar set (grouped by YouTube ID)
   │  recording.py  →  ParsedRecording (no segments yet)
   │  vtt.py (prefer .en.vtt → fallback .en-orig.vtt)  →  segments, origin="youtube_captions"
   │     └─ no .vtt and --whisper:      transcribe.py(FLAC)  →  segments, origin="whisper"
   │     └─ no .vtt and not --whisper:  segments=(), origin=""  (log: transcription-needed)
   ▼
ParsedRecording (with segments)
   │  match.py: query Meetings where date in [recorded_on ± window]; decide coverage + split
   ▼
list[CoverageDecision]   (0, 1, or 2 windows; split offset; split_confirmed=False)
   │  loader.load_recording(...)
   ▼
MediaAsset + Transcript + TranscriptSegment[] + MeetingCoverage[]   (evidence; no Citations)
```

## Component design

### 1. Sidecar parsing (`bcsd/recording.py`)

- **Grouping:** given a stem or directory, collect all files sharing the YouTube ID. Match by
  `YOUTUBE_ID` (11-char token before the trailing separator) + extension, tolerating both `_.ext`
  and `__ext` separators (§5.4 / §9.10). The ID is the canonical group key.
- **`info.json` (§5.5):** read `id`, `title`/`fulltitle`, `duration`, `upload_date` (`YYYYMMDD`),
  `webpage_url`. `chapters` is expected absent (do not rely on it).
- **Title date (§6.2):** parse the meeting date from the title across all observed formats —
  `M/D/YYYY`, `M_D_YYYY`, `M.D.YYYY`, `Month D YYYY`, `Month_D_YYYY`. This is `recorded_on`, the
  preferred matcher anchor. If no title date parses, `recorded_on=None` (matcher falls back to
  `upload_date` with the backward window).
- **Combined detection:** `is_combined = ("committee" in title.lower() and "board" in title.lower())`.
- **`r2_key`:** reuse the slice-1c `BCSD/<path from BCSD_* dir>` convention via the existing
  self-locating helper pattern; recordings live under `BCSD_MEETING_RECORDINGS/`. If the file is not
  under a `BCSD_*` ancestor, leave `r2_key=""` (uploads are opt-in; an empty key simply means
  "not uploadable / not yet keyed"). MediaAsset's unique constraint on `r2_key` is conditional on
  non-empty, so multiple un-keyed assets are allowed.

### 2. VTT rolling-window dedup (`bcsd/vtt.py`) — highest risk, dedicated TDD

YouTube auto-caption VTT (§5.6) interleaves a real multi-second cue with a ~10 ms "preview" cue that
duplicates the previous line; the new text is the *tail* line of each cue. A naive WebVTT read emits
each line 2–3×.

**Algorithm:**
1. Parse cues with a tolerant regex `HH:MM:SS.mmm --> HH:MM:SS.mmm`, ignoring the trailing cue
   settings (`align:start position:0%`).
2. Clean each cue body: strip inline timing tags (`<\d\d:\d\d:\d\d\.\d\d\d>`) and `<c>`/`</c>`;
   collapse internal whitespace; drop empty / whitespace-only / `[Music]`-only lines.
3. Dedup the rolling window: keep a "last committed text" pointer; for each cue emit only the line(s)
   that differ from what was already committed (the new tail). Skip near-zero-duration preview cues.
4. Emit `ParsedTranscriptSegment(start, end, text)` with monotonic, non-overlapping spans (clamp a
   cue's `end` to the next kept cue's `start` where they would overlap).

**Tests:** synthetic fixtures reproducing the preview→committed→next-preview pattern assert no
duplicated text, monotonic non-overlapping starts, tags stripped, `[Music]` dropped; a trimmed real
slice from the 2023-01-19 `.vtt` asserts deduped word count ≪ raw line count.

### 3. The matcher (`match.py`) — agency-agnostic core

```python
@dataclass(frozen=True)
class CoverageDecision:
    meeting_id: int
    start_offset: float
    end_offset: float | None       # None = to end of recording
    split_confirmed: bool = False
```

`match_recording(parsed, candidate_meetings) -> list[CoverageDecision]`. `candidate_meetings` are the
`Meeting` rows whose `date` falls in `[anchor − window, anchor + window]`, where `anchor =
recorded_on or upload_date` and `window = 3 days` (default; §6.2 — meetings are uploaded 0–3 days
after the meeting, so a symmetric ±3-day window safely covers both the drift and same-day uploads).
The command does the DB query and passes the rows in; `match.py` stays pure of querying details.

Branches:
- **2 candidate meetings (committee + board) + combined recording** → **two** decisions:
  committee `[0, split)`, board `[split, None)`, both `split_confirmed=False`, where `split =
  suggest_split(segments)`. **If `suggest_split` returns `None`** (fewer than two call-to-order
  markers): emit a **single** decision spanning the whole recording `[0, None)` attached to the
  earlier meeting (committee), and log a "manual split needed" warning — the §6.4 conservative choice
  (do not guess a midpoint). Identify committee vs board by `kind` (committee meeting first) and/or
  `start_time`.
- **1 candidate meeting** → one decision `[0, None)`.
- **0 candidate meetings** → empty list → MediaAsset persisted **unlinked** (no coverage rows).
- **>2 candidates or multiple recordings same date / duplicates** → out of scope (Phase 2);
  for 1d, the command operates on one recording at a time and the matcher considers the committee+board
  pair only.

**`suggest_split(segments) -> float | None` (§6.4):** scan segment text for "call/come … to order"
(regex `\bto order\b` with a short lookback admitting `call`/`come`); return the `start` of the
**second** match (committee is first, so the second marks the board). Fewer than two matches → `None`.
The split is always a suggestion; nothing auto-confirms.

### 4. faster-whisper (`transcribe.py`) — opt-in, mocked in CI

- Dependency: `uv add faster-whisper`.
- `transcribe_flac(path, *, model_size="base") -> tuple[ParsedTranscriptSegment, ...]` wraps
  `WhisperModel(model_size).transcribe(path)` and maps whisper's `(start, end, text)` segments to the
  IR shape. Returns origin `"whisper"` to the caller.
- Invoked from the command **only** when `.vtt` is absent **and** `--whisper` is passed. Otherwise a
  missing `.vtt` yields a MediaAsset with no Transcript and a logged "transcription-needed" note.
- **CI:** never invoked for real — tests mock `transcribe_flac` (or `WhisperModel`) and assert the
  loader maps mocked segments → a `Transcript(origin="whisper")` + `TranscriptSegment`s. Real
  transcription is a documented operator validation step.

### 5. Loader (`load_recording` in `loader.py`)

- Signature: `load_recording(parsed: ParsedRecording, decisions: list[CoverageDecision], *, source) -> MediaAsset`.
- **Idempotency:** `MediaAsset` keyed on `youtube_id` (fallback `r2_key`) via `update_or_create`. On
  re-ingest, wipe the asset's `Transcript`s (cascades `TranscriptSegment`s) and its `MeetingCoverage`
  rows, then recreate. Shared `Source` is `get_or_create`. Mirrors `load_meeting`'s
  wipe-and-recreate-while-`reviewed=False` model.
- Create one `Transcript` with `origin` from `parsed.transcript_origin` (skip the Transcript entirely
  if `origin == ""` / no segments); `bulk_create` the `TranscriptSegment`s. Then create
  `MeetingCoverage` rows from `decisions`.
- `search_vector` on segments is populated by the DB trigger (migration 0011); after `bulk_create`,
  the loader does **not** set it in Python.
- **Fail-loud** (consistent with `load_meeting`): unknown `transcript_origin`, or a `CoverageDecision`
  whose `meeting_id` does not resolve → `ValueError`.
- **Provenance:** MediaAsset/Transcript/TranscriptSegment are **evidence artifacts** — no `Citation`
  rows, not `Reviewable` (same rationale as 1c's Document). `MeetingCoverage` is a derived mapping; its
  review gate is its own `split_confirmed` flag (admin confirms via the Phase-1e/4 scrubber). The
  provenance invariant (every *asserted fact* has ≥1 Citation) is unaffected — transcripts assert no
  facts.

### 6. Command (`ingest_recording`)

- `ingest_recording <sidecar-stem-or-dir> [--whisper] [--upload]`.
- Resolves the sidecar set (`recording.py`), imports the transcript (`vtt.py`, or `transcribe.py` when
  `--whisper` and no `.vtt`), queries DB `Meeting`s by date window, runs `match.py`, calls
  `load_recording`.
- `--upload` pushes the recording's large sidecars (`.mp4`/`.flac`/`.jpg`) to R2 via the existing
  `upload_missing` helper (OFF by default — same network-safety reason as 1c: `.env` points at live S3).
- Prints a summary: asset (`youtube_id`), `#segments`, `#coverages`, the split offset (if any),
  `unlinked?`.

### 7. Migration 0011 — TranscriptSegment FTS trigger

Postgres trigger on `INSERT`/`UPDATE` of `TranscriptSegment` setting
`search_vector = to_tsvector('english', text)`. The GIN index (`gin_segment_search`) is already
declared on the model. Direct mirror of `Document`'s migration 0010. No model field changes (the
field already exists), so this is a hand-written `migrations.RunSQL` migration like 0010.

## Testing strategy

- **Unit (CI, fast, mostly no DB):**
  - `vtt.py`: synthetic rolling fixtures + trimmed real slice (dedup correctness).
  - `recording.py`: title-date parsing across the §6.2 formats; sidecar grouping with `_.`/`__`
    tolerance; combined detection; `r2_key` derivation.
  - `match.py`: 2-window+split, 1-window, unlinked, and `<2`-call-to-order fallback (pure, with
    lightweight meeting stand-ins / minimal DB rows).
  - `transcribe.py`: mocked model → IR mapping.
- **Integration (CI, DB):** `load_recording` idempotency (re-ingest wipes + recreates), FTS
  `search_vector` populated by the trigger, coverage rows correct, evidence-not-reviewable invariants.
  An end-to-end test ingests a **synthetic** committee+board pair + a synthetic combined recording and
  asserts two coverage windows + a split suggestion.
- **Committed fixtures:** tiny synthetic `.info.json` + small rolling-window `.vtt` under
  `catalog/tests/fixtures/recordings/` (mirrors 1c's tiny committed PDF byte-fixtures). No large media
  committed to git.
- **Manual smoke (not CI):** after ingesting the real 2023-01-19 committee + board folders, run
  `ingest_recording` against the real 2023-01-19 sidecar set in `archive_data/`. Expect: 1 MediaAsset,
  several thousand deduped segments, **2** coverage windows, a split suggestion ≈ the line-14122
  timestamp, both `split_confirmed=False`. Then run it against a "Show Up Program" video and expect an
  **unlinked** MediaAsset (0 coverages).

## R2 key convention

Reuse the verified slice-1c convention: `r2_key = "BCSD/" + <path from the BCSD_* collection dir onward>`,
via the same self-locating approach (scan for the `BCSD_*` ancestor). Recordings sit under
`BCSD_MEETING_RECORDINGS/`. Unlike attachments (which must be keyable or fail loud), a recording with
no `BCSD_*` ancestor gets `r2_key=""` rather than raising — keys only matter for the opt-in `--upload`.

## Out of scope / deferred (carry forward)

- **Multi-upload duplicate primary-selection** and `duplicate_candidate` flagging (longest duration /
  most-complete sidecar set) → Phase 2 ("matcher at scale").
- **Matcher at archive scale** over all 425 recording sets, Procrastinate jobs → Phase 2.
- **faster-whisper as a default quality pass** over recordings that already have a `.vtt`,
  word-level timestamps → later (1d runs whisper only as the missing-`.vtt` fallback, opt-in).
- **Admin split-confirm scrubber UI** (the human gate on `split_confirmed`) → Phase 1e / Phase 4.
- **The transcript→video deep-link UI** and search over segments → slice 1e (1d delivers the data +
  FTS index they consume).
- Carried from earlier slices: consent-anchor vote attachment, procedural-section votes, same-name
  Person collisions (Phase 3), actual OCR / PPTX text / Source C (Phase 2).

## Execution

Subagent-driven-development, same as 1b/1c: a fresh implementer subagent per task, then a two-stage
review (spec-compliance, then code-quality); the controller evaluates reviewer findings rather than
applying blindly; a final whole-branch review before merge. TDD against fixtures throughout. Commit
after each task; `ruff` clean before every commit; merge to `main` and push when the slice is green
(`uv run pytest -q`, `manage.py check`, `makemigrations --check --dry-run`, `ruff check`/`format`).
