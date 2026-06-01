# Bibb County Civic Knowledge Base — Build Brief for Claude Code

**Purpose of this document.** Hand this to Claude Code as project context. It captures everything established during planning *and* everything verified by inspecting the real archive, so the implementing agent does not have to rediscover file formats, naming conventions, or edge cases. It deliberately contains **no code** — only specifications, data dictionaries, and decisions. Where it says "spec," the agent designs the implementation.

---

## 1. Project in one paragraph

A public, web-first knowledge base for the Bibb County (GA) Board of Education / School District. Anyone (anonymous, no login) can full-text search the archive, open a profile for a person / organization / meeting, see every structured fact traced back to its source document, follow relationships through an interactive color-coded graph, jump from a transcript hit to the exact second of the meeting video on YouTube, and share any view as a stable URL. The guiding principle is **provenance**: every asserted fact links to the document (and location) that evidences it.

**Primary user:** anonymous public. **Builder/operator:** solo. **Software:** open-source, self-hostable.

---

## 2. Operating constraints (these shape every decision)

- **Solo operator** → minimize the number of long-running services to patch/monitor/back up. Prefer one datastore doing many jobs; prefer batteries-included frameworks over hand-rolled auth/admin/API.
- **Anonymous-first** → core search/browse/graph must work with zero login and be cacheable. Accounts exist only for admin, API keys, and (possible future) premium.
- **Provenance is a hard requirement from day one** → retrofitting citations later is painful; build the citation model first.
- **Existing infrastructure must be reused** (see §3).

---

## 3. Locked technology decisions

| Concern | Decision | Notes / "don't over-build" guidance |
|---|---|---|
| System of record | **PostgreSQL** (16/17) | One datastore for relational + search + graph. |
| Full-text search | **Native Postgres FTS** (`tsvector` + GIN) for v1 | Upgrade path: **pg_search / ParadeDB** (BM25) only when relevance/scale demands. Do **not** stand up Elasticsearch. |
| Graph storage/queries | **Relational edge tables + recursive CTEs** for v1 | Upgrade path: **Apache AGE** (openCypher in Postgres) for true path-finding later. Do **not** add a separate graph DB. |
| App framework | **Django + Django REST Framework** | Built-in admin, auth, ORM, migrations, REST — covers most admin/API stories for free. |
| Front end | **Django server-rendered templates + HTMX + Alpine.js** | Clean canonical URLs (required for share-as-URL), SEO-friendly, minimal JS. Interactive bits are progressive enhancements, not a SPA. |
| Graph viz | **Sigma.js + graphology** (WebGL) | Color-coded nodes/edges, filter, focus/expand, over a JSON endpoint. Cytoscape.js acceptable alternative for small ego-graphs. |
| Object storage | **Cloudflare R2** (already holds the media) via `django-storages` (S3 API) | **R2 has zero egress fees** — serving PDFs/audio/video is cheap. Don't add MinIO. |
| Background jobs | **Procrastinate** (Postgres-backed) | Avoids standing up Redis/Celery. Used for ingestion, OCR, optional re-transcription. |
| Ingress / TLS | **Existing Traefik + Cloudflare Tunnel** | TLS terminates at Cloudflare. Don't add Caddy/nginx. |
| Edge protection | **Cloudflare** (caching, rate-limiting rules, bot management) | This is where media throttling + anti-scraping live, not in the app. |
| Entity resolution | **Splink** (DuckDB backend) | Dedupe people/orgs to canonical entities; admin reviews proposals before publish. |
| Transcription (if needed) | **faster-whisper** (segment + optional word timestamps) | Only if regenerating transcripts from FLAC — see §6.6. |
| Deploy | **K8s manifests** on the existing cluster; Docker Compose for local dev only | DB via **CloudNativePG** operator with base-backup + WAL shipping **to R2** (point-in-time recovery, no custom scripts). |

---

## 4. The archive: verified ground truth

Total: **2,710 directories, 23,378 files.** Meetings span **2013 → present** (earlier than the original "2015" estimate). Four top-level trees, each with a different shape:

```
BCSD_BOE_MEETINGS/      meeting records, foldered by date (the spine)
BCSD_DOCS/              flat list of website PDFs (reports, handbooks, notices)
BCSD_MEETING_RECORDINGS/ flat folder of recording sidecar sets (no subfolders)
BCSD_POLICIES/          policy markdown by code + consolidated/ + index.md + manifest.json
```

### 4.1 `BCSD_BOE_MEETINGS/` — the meeting tree
Path shape: `BCSD_BOE_MEETINGS/<YYYY>/<MM>/<meeting-folder>/`

**Meeting folder name format:** `YYYY-MM-DD_HHMM_<type-slug>_mid-<MeetingID>`
Examples: `2025-04-17_1600_committee-meeting_mid-124789`, `2025-04-17_1830_board-meeting_mid-124791`, `2013-10-17_1830_board-agenda_mid-34064`, `2013-12-09_1630_called-board-meeting_mid-35162`, `2014-07-29_1800_called-board-meeting-policy-review_mid-39007`.
- `HHMM` is 24-hour local start time.
- `type-slug` **varies** — known values include `committee-meeting`, `board-meeting`, `board-agenda`, `called-board-meeting`, `called-board-meeting-policy-review`. **Spec:** keep the raw slug; map known slugs to a Meeting "kind" enum, default unknown slugs to `other`.
- `MeetingID` is the source system's ID (also appears inside event.md and the Source URL).

**Each meeting folder contains:**
- `event.md` — cleanest **structured** metadata + agenda outline + file→agenda-item attribution (parse this first; see §5.1).
- `agenda.md` — the agenda as published (outline only; see §5.3).
- `minutes.md` — attendance roster + per-item outcomes/motions/votes (**richest source**; see §5.2). **May be absent** for some meetings (agenda-only records exist).
- `files/` — the attachments presented at the meeting (PDF, PPTX, PPT, DOCX, occasional extension-less files). Filenames are slugified.
- `raw/` — original `agenda.html`, `minutes.html`, and per-agenda-item `.html`/`.md` pairs. **Spec:** treat `raw/` as fallback/provenance; the top-level `event.md`/`minutes.md` are the primary parse targets.

> **Combined-meeting reality:** a regular date usually has **two meeting folders** — a committee meeting (~16:00) and a board meeting (~18:30) — but a **single recording often covers both** (see §6). Documents are separated per folder; the recording is not.

### 4.2 `BCSD_DOCS/` — website documents
Flat directory of PDFs. Content types observed: annual financial reports (CAFR/ACFR by fiscal year), per-school dress codes, employee/athletic handbooks, FERPA / Title IX notices, code of conduct (English + Spanish), community resource guides. **Spec:** ingest as standalone documents (no meeting link); metadata limited to filename + extracted text. Light heuristics can tag fiscal-year reports and per-school docs.

### 4.3 `BCSD_MEETING_RECORDINGS/` — recordings (flat)
See §5.4–§5.6 for the sidecar format, info.json fields, and the transcript reality. This is the **hardest ingestion source** because filenames encode the upload date (not the meeting date) and recordings are not 1:1 with meetings.

### 4.4 `BCSD_POLICIES/` — policies
- Files named by **policy code**: `GBA.md`, `JBCCA.md`, `IFCD.md`, etc.
- Regulation/exhibit variants encoded as suffixes: `-R_1_` = regulation, `-E_1_` = exhibit (e.g., `GARHA-R_1_.md`, `GBRIG-E_2_.md`).
- `consolidated/` — policies grouped by category: `board_governance.md`, `fiscal_management.md`, `instruction.md`, `personnel.md`, `students.md`, `support_services.md`, `facilities_development.md`, `education_agency_relations.md`, `foundations_and_basic_commitments.md`, `general_school_administration.md`, `school_community_relations.md`, `miscellaneous.md`.
- `index.md` and `manifest.json` (read `manifest.json` — likely the authoritative policy list/metadata).
- **Spec:** ingest each policy as a Document (kind=policy, no meeting link). The **policy code is the join key**: link policy-related agenda items (e.g., "PR-1 Policy GARHA, Employee Sick Leave Bank") to the matching policy document by code.

---

## 5. File-format specifications (for the parsers)

### 5.1 `event.md` (structured — parse first)
- Title line: `# <Meeting Type>` (e.g., `# Committee Meeting`, `# Board Meeting`).
- Bulleted metadata block, keys observed: **Meeting ID**, **Date / Time** (`MM/DD/YYYY - HH:MM AM/PM`), **Meeting Type**, **Source URL** (simbli eboardsolutions; carries `S=` site id and `MID=` meeting id), **Folder** (echoes the folder name), **Agenda Saved** (yes/no), **Minutes Saved** (yes/no), **Attachments Downloaded** (integer count).
- `## Agenda Items` — flat bulleted list; outline numbering (`I.`, `i.`, `a.`) is preserved as leading text.
- `## Files` — bulleted; **each line maps an attachment filename to its agenda item**, format: `` `<filename>` (<agenda item attribution text>) ``. **This is the document↔agenda-item link — capture it.**
- `## Notes` — optional; e.g., "Attachment icon present but no attachment URLs extracted: …".

### 5.2 `minutes.md` (richest — votes, roster, outcomes)
Structure: the agenda outline (repeated) then `## Meeting Minutes`.
- **Attendance:** `### Attendance` → `#### Voting Members` → bulleted `- <Honorific>. <Name>, <Role>` (e.g., `- Ms. Myrtice Johnson, President`). **This roster is the canonical name list for in-meeting name resolution** (President, Vice President, Treasurer, Board Member).
- **Agenda sections:** `### <Roman>. <SECTION NAME>` (e.g., `### V. FISCAL/SUPPORT SERVICES COMMITTEE`).
- **Agenda items:** `#### <numeral>. <CODE> <Title> (<TYPE>)`.
  - **Item code** pattern: `[A-Z]{2,4}-\d+` (IS-1, FSS-3, PR-1, PS-1, FI-1).
  - **Type** in parentheses: `(ACTION)`, `(PRESENTATION)`, `(INFORMATION)`, with optional reading stage `(ACTION - Second Reading)`, `(INFORMATION - First Reading)`.
- **Outcome paragraph** (for action items): free text describing what was authorized; **often contains dollar amounts** (`$5,515,711.09`) and **vendor names** (WM2A Architects, Warren Associates Inc., SP Design Group, Yancey Bus Sales, SureLock Technology, CDW, Dell, Lenovo Financial Services). Extract amounts by regex; extract vendors via NER + admin review (noisy).
- **Motion blocks — four variants the parser must handle:**
  1. *Bulleted:* `- Motion made by: <Name>` / `- Motion seconded by: <Name>` then `_Voting results:_ <result>`.
  2. *Non-bulleted:* `Motion made by: <Name>` / `Motion seconded by: <Name>` / `Voting: <result>`.
  3. *Initial + Amended:* `Initial Motion made by:` / `Initial Motion seconded by:` / `Voting:` / `Amended Motion made by:` / `Voting:` (two motions on one item).
  4. *Per-person roll call:* after `_Voting results:_`, a bulleted roll call — `- Yes: <Honorific>. <Name>` / `- No: <Name>` / etc. (seen on board-meeting consent-agenda and key votes). **This is the per-member voting data** — capture each (person, value).
- **Result strings:** "Unanimously approved" / "Unanimously Approved" (case varies) → unanimous; explicit roll call → per-member tally.
- **Other appearances to capture:** invocation giver ("The invocation was given by <Name>"), Pledge of Allegiance leader (student name + grade + school), and **"Invitation to Visitors to Address the Board"** speakers (e.g., "Attorney Roy Miller", "Jessican Strohmetz" — note real-world typos/OCR noise) → person appearances with role `speaker`/`presenter`.
- **Name normalization spec:** strip leading honorific (`Ms.|Mr.|Mrs.|Dr.|Miss`), collapse internal double spaces (e.g., "Ms.  Myrtice Johnson"), trim trailing `, <Role>`. Resolve against the meeting roster first, then cross-meeting via Splink.

### 5.3 `agenda.md`
Same outline as the top of minutes.md, without the minutes body. Header line carries meeting type + date/time + location address. Use as fallback when `minutes.md` is absent (yields agenda items but no votes/outcomes).

### 5.4 Recording sidecar set (`BCSD_MEETING_RECORDINGS/`)
Flat folder. Each recording = a set of files sharing a stem. Extensions observed: `.info.json`, `.en.vtt`, `.en-orig.vtt`, `.flac`, `.mp4`, `.jpg`, `.description`.
- **Stem format:** `YYYY-MM-DD-<Title_With_Underscores>_<YOUTUBE_ID>_`
  - Leading `YYYY-MM-DD` = **upload date, NOT meeting date** (critical — see §6.2).
  - `YOUTUBE_ID` = 11-char token immediately before the trailing `_`.
- **Separator quirk:** the uploaded samples use a double-underscore before the extension (`..._<ID>__info.json`, `..._<ID>__en.vtt`) while the tree listing shows `..._<ID>_.info.json`. **Spec:** match sidecars by the YouTube ID and extension, not by an exact separator count — tolerate `_.ext` and `__ext`.
- A recording may be **missing** the `.vtt` (transcript) and/or other sidecars. Presence is per-file, not guaranteed.

### 5.5 `info.json` (yt-dlp metadata) — fields to use
`id` (YouTube id) · `title` / `fulltitle` (contains the meeting date) · `duration` (seconds — e.g., 13486 ≈ 3h44m for a combined committee+board) · `upload_date` (`YYYYMMDD`) · `timestamp` (unix) · `webpage_url` (full YouTube URL) · `channel` / `uploader` (`bibbschools`) · `description` · `categories` · `chapters` (**absent in sample → no free split point; see §6.4**).

### 5.6 Transcript reality — IMPORTANT
The `.vtt` files are **YouTube auto-captions, not openai-whisper output**, despite earlier recollection. Signatures confirmed in the data: `align:start position:0%` cue settings, inline word-timing tags like `<00:00:00.120><c> you</c>`, and **rolling-window duplication** (each line appears first as a preview then as a committed cue). Implications and spec:
- **Dedup required:** a naive WebVTT read double-counts text. The importer must strip inline `<...>`/`<c>` tags and collapse the rolling repetition into clean, non-overlapping segments with `start`/`end` seconds.
- **No speaker labels** and lower accuracy than a clean whisper pass.
- `.en.vtt` and `.en-orig.vtt` were **byte-identical** in the sample. **Spec:** prefer `.en.vtt`, fall back to `.en-orig.vtt`.
- **Quality upgrade option (decision for operator):** the operator holds the FLAC, so transcripts can be (re)generated with **faster-whisper** for clean segment-level JSON (and optional word timestamps). Recommended at least for recordings missing a `.vtt`, and optionally as a quality pass over all. Either way, the deep-link feature (F14) only needs accurate segment `start` offsets.

---

## 6. Recording ↔ meeting matching (the hard part) — algorithm spec

A recording maps to **0, 1, or 2** meetings. Build a dedicated matcher; do not assume 1:1.

### 6.1 Anchor
Anchor matching on the **meeting date**, then resolve which meeting(s) that date's recording covers.

### 6.2 Deriving the candidate date (order of preference)
1. **Parse the date out of the title** — handle all observed formats: `M/D/YYYY`, `M_D_YYYY`, `M.D.YYYY`, `Month D YYYY`, `Month_D_YYYY` (e.g., `1/19/2023`, `1_19_2023`, `04.15.2021`, `3.18.2021`, `June_17_2021`, `August_19_2021`).
2. **Fallback to `upload_date`** with a backward window (meeting typically uploaded 0–3 days *before* the upload date). Use a small ± window when searching meeting folders.
3. If both disagree, **trust the title date**; flag for review when they diverge by more than the window.

### 6.3 Resolving to meeting folder(s) on that date
- **2 meetings same date** (committee + board) **and one recording** whose duration is large (heuristic: > ~2 hours, or simply "covers both" by title containing both "Committee" and "Board"): create **two MeetingCoverage windows** over the single recording (see §7).
- **2 meetings, two recordings** (committee and board uploaded separately): match each recording to its meeting by title keyword (`Committee` vs `Board`) and/or by start time.
- **1 meeting, 1 recording:** single coverage window spanning the whole recording.
- **Recording matches no meeting folder:** still ingest the recording as a MediaAsset + transcript, but leave it **unlinked** (no MeetingCoverage). This covers non-meeting videos present in the folder — e.g., "GA State Board of Education Town Hall," "Bibb County Student of the Year," "Memorandum of Understanding Signing Day."
- **Multiple recordings per date that look like duplicates/re-uploads** (observed: a date with three distinct YouTube IDs; a file whose upload-date prefix and title-date disagree by weeks): **spec** = pick a primary by longest duration / most-complete sidecars, flag the rest as `duplicate_candidate` for admin review rather than auto-linking all.

### 6.4 The committee→board split inside a combined recording
- No YouTube chapters exist (verified), so the split is not free.
- **Heuristic:** transcribe/scan the segments for "call … (this/the) meeting to order"; the committee meeting is first, so the **second** "call to order" typically marks the board meeting's start. (Cross-check: minutes.md records actual clock times — e.g., committee "called to order at 4 p.m.", board "called to order at 7:10 p.m." — which can corroborate but not directly map to recording offset.)
- **The split is a suggestion, admin-confirmed.** Store the suggested offset; require a human to confirm via a small admin tool (transcript scrubber). Until confirmed, attribute ambiguous segments conservatively (e.g., leave both windows open or assign whole recording to the day's record) rather than guessing wrong.

---

## 7. Data model — data dictionary (agent designs the schema)

Meeting-centric, with **generic provenance**. Express in Django models; the agent chooses field types. Entities and their essential fields/relationships:

- **Person** — canonical individual after dedup. Fields: full_name, aka[], slug, notes.
- **Organization** — kind ∈ {district, school, company(vendor), nonprofit, committee, campaign, other}; name, aka[], slug.
- **Office** — a seat/role tied to an Organization (e.g., "Board Member, District 3").
- **OfficeTenure** — Person↔Office with start/end dates and selection ∈ {elected, appointed}. (Powers "offices over time.")
- **Meeting** — body (Organization), date, start_time, kind (mapped from folder type-slug), title, source_meeting_id, source_url, source_path (archive folder), slug. **The ingestion anchor.**
- **AgendaItem** — Meeting FK, order, code (e.g., FSS-3), title, item_type ∈ {action, presentation, information, …}, reading_stage (first/second, optional), outcome_text, outcome_status (passed/failed/tabled/postponed/unanimous).
- **MediaAsset** — kind ∈ {video, audio, pdf, image}; r2_key, youtube_id, source_url, recorded_on, upload_date, duration_seconds, access_level. (One per recording/file.)
- **Transcript** — belongs to a **MediaAsset** (not a Meeting; it can span two meetings); language, source ∈ {youtube_captions, whisper}, model.
- **TranscriptSegment** — Transcript FK, start (sec), end (sec), text, search vector. `start` is the absolute offset in the recording = the YouTube `?t=` value. **Powers transcript→timestamped-video deep links.**
- **MeetingCoverage** — maps a Meeting to the slice of a MediaAsset that covers it: media FK, meeting FK, start_offset, end_offset (null = to end), split_confirmed (bool). **A combined recording has two of these.** A meeting's segments = the recording's segments whose `start` falls in `[start_offset, end_offset)`.
- **Document** — title, kind ∈ {minutes, agenda, policy, contract, memo, presentation, report, article, other}, Meeting FK (nullable), AgendaItem FK (nullable — from event.md file mapping), MediaAsset FK (nullable), r2_key, source_url, og_metadata (json, for future link-out previews), text (extracted, for FTS), ocr_status ∈ {has_text, ocr_needed, empty, unknown}, access_level, search vector.
- **Affiliation** — Person↔Organization with role (owner/officer/member/employee/donor/candidate) + dates. (Powers person/org profiles, campaign finance later.)
- **Vote** — Person↔AgendaItem with value ∈ {yea, nay, abstain, absent}. From the per-person roll call; for "unanimously approved" with a known roster, the agent decides whether to materialize per-member yea votes against the attendance roster or store a unanimous-outcome flag (recommend: store outcome on AgendaItem; materialize per-member Votes only where an explicit roll call exists, to avoid asserting unrecorded detail).
- **Appearance** — Person↔Meeting with role ∈ {member, speaker, presenter, staff, invocation, pledge}. (Powers "meetings a person appeared at.")
- **Award / Bid** — vendor (Organization) ↔ body (Organization), optional AgendaItem FK, amount, status ∈ {bid, awarded, rejected}, date. (Powers vendor bid/award stats.)
- **Relationship** — generic typed edge between any two of Person/Organization: src, dst, kind (free-text typed, e.g., spouse_of, subsidiary_of, donated_to), dates. (Powers the knowledge graph's arbitrary edges.)
- **Citation** (provenance backbone) — attaches **any** fact (generic FK to Vote/Affiliation/Award/Office­Tenure/Appearance/Relationship/etc.) to a **Document**, with optional page and optional **TranscriptSegment**, plus an optional short quote. Every materialized fact should have ≥1 Citation.
- **Submission** and **RecordsRequest** — later phases (public contribution + "please add this" tracking). Stub the models; UI deferred.

**Provenance rule:** ingestion writes facts as *proposals* (with a confidence + reviewed flag) that the admin confirms before they're publicly visible. Citations are created at the same time as the facts.

---

## 8. Ingestion pipeline — spec (three sources + join)

Run as Procrastinate jobs; idempotent (re-running upserts, keyed on source IDs / paths). Order:

**Source A — meeting tree (`BCSD_BOE_MEETINGS/YYYY/MM/<folder>/`)**
1. Parse folder name → date, start_time, type-slug→kind, MeetingID. Upsert Meeting.
2. Parse `event.md` → confirm metadata; capture the `## Files` filename→agenda-item map.
3. Parse `minutes.md` (if present) → attendance roster; per-item outcome_text/status; motion movers/seconders; per-person roll-call Votes; invocation/pledge/visitor Appearances. (Fallback to `agenda.md` for outline if minutes absent.)
4. For each file in `files/`: upsert Document (link Meeting + AgendaItem via the event.md map), set r2_key, **verify OCR/text layer** (see §8.1), extract text, index for FTS.
5. Emit proposed Person/Organization mentions (from roster, movers, vendors, speakers) for resolution.

**Source B — recordings (`BCSD_MEETING_RECORDINGS/`)**
1. Group sidecars by YouTube ID (tolerant of `_.`/`__` separators).
2. Parse `info.json` → MediaAsset (youtube_id, duration, upload_date, recorded_on from title date, webpage_url).
3. Import transcript: parse `.en.vtt` (fallback `.en-orig.vtt`), **dedup the YouTube rolling format**, write TranscriptSegments. If no `.vtt`, flag for (faster-whisper) transcription from FLAC.
4. Run the **matcher** (§6) → create 0/1/2 MeetingCoverage rows; suggest split for combined recordings; flag duplicates/unlinked recordings for review.

**Source C — standalone docs & policies**
1. `BCSD_DOCS/`: upsert Document(kind=report/other, meeting=None), extract text, FTS, light filename heuristics (fiscal year, school).
2. `BCSD_POLICIES/`: read `manifest.json`; upsert Document(kind=policy, meeting=None) per policy code; record regulation/exhibit variants; link to policy-related AgendaItems by code.

**Join — entity resolution**
- Run **Splink** over proposed Persons/Organizations → canonical entities. Seed Person matching with the per-meeting rosters (high-precision anchors). Admin reviews/merges before publish.

### 8.1 OCR verification spec
Most PDFs *should* already have a text layer but this must be **verified, not assumed**. Spec: for each PDF, measure extractable text per page; if below a small threshold (≈ a few dozen chars/page), mark `ocr_needed` and route through an OCR pass (ocrmypdf/Tesseract) to add a searchable layer, then re-extract. Record `ocr_status` on the Document.

---

## 9. Consolidated gotchas checklist (things that will bite an implementer)

1. **Recording filename date = upload date, not meeting date.** Parse the meeting date from the title (5+ formats).
2. **`.vtt` are YouTube auto-captions, not whisper.** Must dedup rolling cues + strip inline tags; no speaker labels; consider re-transcribing from FLAC.
3. **Recordings are not 1:1 with meetings:** combined committee+board videos (~3.7 hr), multiple uploads per date, re-uploads with drifted dates, and non-meeting videos that match nothing.
4. **No YouTube chapters** → committee/board split needs the "second call to order" heuristic, admin-confirmed.
5. **Combined recordings need two coverage windows**, with segments attributed by offset.
6. **type-slug varies** (committee-meeting/board-meeting/board-agenda/called-board-meeting/…); map known, default `other`.
7. **`minutes.md` can be absent**; fall back to `agenda.md` (no votes then).
8. **Four motion-block formats** + initial/amended motions + per-person roll calls; case varies ("approved"/"Approved").
9. **Name noise:** honorifics, double spaces, OCR typos in visitor names; resolve against the roster first.
10. **Sidecar separator inconsistency** (`_.ext` vs `__ext`); match by YouTube ID + extension.
11. **Some recordings lack `.vtt`** (and other sidecars); presence is per-file.
12. **Archive starts 2013**, not 2015; scale ≈ 23k files / 2.7k dirs.
13. **Don't over-assert votes:** only materialize per-member Votes where an explicit roll call exists; otherwise store the outcome + a unanimous flag.
14. **Provenance from day one:** facts are proposals-with-citations pending admin review.

---

## 10. Access, media & abuse (brief)

- Media already in **R2**; **zero egress** removes the bandwidth-cost concern entirely. Serve public assets via Cloudflare cache.
- Edge protections (rate limits, bot management, caching) live in **Cloudflare**, not the app. App mints short-TTL presigned R2 URLs only if/when a gated asset class is introduced.
- Current dataset is **public record** → no restricted/premium gating needed for the MVP. Keep `access_level` on Document/MediaAsset for a possible future licensed-newspaper case (which would be store-OG-metadata-and-link-out, since no license is held).

---

## 11. MVP scope (what to build first)

1. Three-source ingestion (A/B/C) → Meetings, AgendaItems, Documents (with OCR verification), Transcripts/Segments, MeetingCoverage.
2. Full-text search with filters (type, date, meeting) over **documents and transcript segments**.
3. Pages: Meeting (agenda, documents, embedded YouTube, outcomes), Person profile, Organization profile — every fact **source-linked**.
4. Transcript hit → **timestamped YouTube deep link** (`watch?v=<id>&t=<start>s`).
5. Per-member **voting history** (data is parseable now, so include it).
6. Entity resolution (Splink) + admin review workflow.
7. One-hop **ego graph** on profiles (taste of the full graph); **stable shareable URLs** everywhere.
8. Django admin for content management + the committee/board **split-confirm** tool.

**Deferred:** global interactive graph explorer; public submissions + moderation; calendar/iCal; vendor bid/award dashboards; public API with keys; restricted/premium machinery; semantic search (pgvector).

**MVP "done":** a stranger can search the archive, open a person/org/meeting, see source-linked facts and immediate connections, jump to the exact second of a meeting video, and share the URL — no account, on a phone, fast.

---

## 12. Suggested build order for Claude Code

1. **Repo + infra skeleton:** Django project, Postgres, Docker Compose (local), `django-storages`→R2 config, base settings, CI lint/test. Health-check page.
2. **Schema:** all §7 models + migrations + Django admin registration. Generic Citation wired up.
3. **Parsers (Source A):** folder-name, `event.md`, `minutes.md` (all four motion variants, roster, roll call, appearances), `agenda.md` fallback. Unit-test against the provided 04/17/2025 committee + board samples (known-good fixtures).
4. **Document ingest + OCR verification + FTS indexing** for `files/`, `BCSD_DOCS/`, `BCSD_POLICIES/` (with policy-code linking).
5. **Recordings (Source B):** sidecar grouping, `info.json` parse, **VTT dedup importer**, then the **matcher** (§6) + **split suggestion** + admin confirm tool.
6. **Entity resolution:** Splink pipeline + admin review/merge UI.
7. **Public read UI:** search-with-filters, Meeting/Person/Org pages with citations, transcript deep links, voting history, one-hop ego graph (Sigma.js over a JSON endpoint), canonical shareable URLs.
8. **K8s manifests + CloudNativePG (backups to R2) + Traefik IngressRoute**; Cloudflare cache/rate-limit/bot rules; `robots.txt` + an "API key instead of scraping" page (API itself deferred).

Provide the agent with: this brief, read access to the four trees (or a representative sample per tree), and the verified sample fixtures (the 04/17/2025 committee `minutes.md`/`event.md`/`agenda.md`, the board equivalents, and the 1/19/2023 recording `info.json` + `.en.vtt`).

---

## 13. Still-open verification items (confirm before/while building)

- **Re-transcribe decision:** accept YouTube captions as-is for v1, or run faster-whisper from FLAC for quality/coverage? (At minimum, transcribe recordings missing a `.vtt`.)
- **`manifest.json` in `BCSD_POLICIES/`:** confirm its schema; likely the authoritative policy list to drive Source C.
- **Coverage of recordings:** what fraction of meeting dates actually have a recording? (Determines how prominent the video feature is.)
- **Multi-upload dates:** confirm the dedup rule (longest duration + most-complete sidecar set as primary) matches reality on a few sampled dates.
- **Officials over time:** is there a roster history (who served when) beyond per-meeting attendance, to populate OfficeTenure with accurate start/end dates? If not, derive tenure spans from first/last attendance as an approximation, flagged as inferred.