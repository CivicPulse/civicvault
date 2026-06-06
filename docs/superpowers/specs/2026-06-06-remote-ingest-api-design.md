# Design: Remote Ingest REST API

**Date:** 2026-06-06
**Status:** Approved (design phase)
**Branch:** `feat/remote-ingest-api`

## Problem

Production runs in Kubernetes behind a cloudflared tunnel with no public database
access. Today, new BCSD meetings and recordings are loaded by running Django
management commands (`ingest_bcsd`, `ingest_recording`) against a direct database
connection — only possible from a machine with prod DB credentials.

We want a **local tool** to do all the heavy, machine-specific work (OCR, format
conversion, transcription) and then push the result to production over an
authenticated HTTP API — no direct DB connection required. Large media files
should upload **directly to R2** via presigned URLs so they never transit the
application pod.

## Goals

- Add/update meeting data in prod through an authenticated REST API.
- Upload attachment files to R2 via presigned PUT URLs returned by the API.
- Reuse the existing ingest pipeline (the framework-neutral IR + loaders) with no
  changes to its fact-writing logic.
- Preserve human review work already done in prod (`reviewed=True` facts).

## Non-goals (v1)

- **Recordings** (`load_recording`, the ±3-day matcher) — deferred to a fast
  follow once the meeting path is proven. The design keeps the door open for it.
- Multi-user / per-client tokens, OAuth, request signing (HMAC).
- A general-purpose public API. These endpoints exist solely for trusted ingest.

## Key decisions (resolved during brainstorming)

1. **Contract = the IR.** The local tool parses all the way down to the existing
   `ParsedMeeting` IR (`catalog/ingest/ir.py`) and POSTs it as JSON. The server
   deserializes it back into those frozen dataclasses and calls the **existing**
   `load_meeting()` unchanged. BCSD-specific parsing stays entirely local; the
   server stays agency-agnostic.
2. **Auth = single static bearer token.** A high-entropy secret in an env var
   (`INGEST_API_TOKEN`), sent as `Authorization: Bearer <token>`, compared in
   constant time. No user table.
3. **Uploads = upload-first, then commit.** The tool requests presigned PUT URLs
   for the file keys, uploads the bytes to R2 directly, then POSTs the meeting IR
   with `r2_key`s already embedded. Facts only land after bytes are safely stored.
4. **Scope = meetings only for v1.** Recordings later.
5. **Re-ingest guard.** Re-posting a meeting that has any `reviewed=True`
   Vote/Appearance/Motion is rejected (`409`) unless the request sets
   `"force": true`. New and fully-unreviewed meetings ingest normally.
6. **Reference local client included.** A `push_bcsd` management command that
   parses a folder, requests upload URLs, PUTs the files, and POSTs the IR —
   proving the loop end-to-end.

## Architecture

A new `catalog/api/` package exposes two authenticated JSON endpoints under
`/api/v1/`. The API is a thin authenticated wrapper over the existing IR loaders;
it adds no parsing and no new fact-writing logic.

```
Local tool (existing BCSD adapter + OCR/whisper)
   │  1. parse folder → ParsedMeeting (IR)
   │  2. POST /api/v1/uploads {keys:[...]}        ──► presigned PUT URLs (missing keys only)
   │  3. PUT each file ─────────────────────────► R2 S3 endpoint (direct, bypasses the pod)
   │  4. POST /api/v1/meetings  <serialized IR>   ──► load_meeting() → reviewed=False proposals
   ▼
Django pod (catalog/api/)  ──►  Postgres + R2 presign
```

The IR (`catalog/ingest/ir.py`) becomes a **published contract**. `load_meeting`
is used unchanged.

### File layout (all new, under `catalog/api/`)

| File | Responsibility |
|---|---|
| `__init__.py` | package marker |
| `auth.py` | `BearerTokenAuthentication` + `HasValidIngestToken` permission |
| `serializers.py` | one DRF serializer per IR dataclass; `.to_ir()` rebuilds the frozen dataclasses |
| `uploads.py` | presigned-PUT generation via a boto3 client built from the R2 env vars |
| `services.py` | shared BCSD `Jurisdiction`/`Source`/`Organization` get-or-create (extracted from `ingest_bcsd`) + the reviewed-fact guard |
| `views.py` | `UploadsView`, `MeetingsView` (DRF `APIView`) |
| `urls.py` | wires `/uploads` and `/meetings` |

`civicvault/urls.py` gains `path("api/v1/", include("catalog.api.urls"))`.

## Component details

### Authentication (`auth.py`)

- `BearerTokenAuthentication(BaseAuthentication)` reads `settings.INGEST_API_TOKEN`.
  - If the token is unset/blank → **deny everything** (raise `AuthenticationFailed`);
    never an accidental open door.
  - Parse the `Authorization` header; require the `Bearer ` scheme.
  - Compare with `django.utils.crypto.constant_time_compare` (timing-safe).
  - On success: return `(AnonymousUser(), token)` so `request.auth = token`.
  - Implement `authenticate_header()` → `"Bearer"` so DRF renders auth failures
    as `401` (without it, DRF falls back to `403`).
- `HasValidIngestToken(BasePermission)`: `return bool(request.auth)`.
- Both are set **per-view** (`authentication_classes` / `permission_classes`), not
  as global DRF defaults, so the public site's views are unaffected.

### `POST /api/v1/uploads` (`UploadsView` + `uploads.py`)

Request:
```json
{"keys": ["BCSD/2025/.../attachment.pdf", "..."]}
```

For each key, check R2 with `default_storage.exists(key)` (mirrors the
idempotency of `catalog/ingest/storage.upload_missing`). Return a presigned PUT
URL only for keys **not** already present.

Response (`200`):
```json
{
  "uploads": [
    {"key": "BCSD/2025/.../attachment.pdf",
     "url": "https://<acct>.r2.cloudflarestorage.com/<bucket>/...?X-Amz-...",
     "expires_in": 3600}
  ],
  "skipped": ["BCSD/2025/.../already-there.pdf"]
}
```

- Presigning uses a boto3 S3 client built directly from the R2 env vars
  (`R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`,
  `region_name="auto"`, `signature_version="s3v4"`) calling
  `generate_presigned_url("put_object", ...)`. The URL targets the **R2 S3 API
  endpoint**, not the public custom domain, so the tool PUTs straight to R2 and
  large media never transits the pod.
- When storage is the local-filesystem fallback (no `R2_BUCKET`), return `503`
  with a clear "no remote storage configured" message. Detected the same way
  `upload_missing` does: `isinstance(default_storage, FileSystemStorage)`.

### `POST /api/v1/meetings` (`MeetingsView`)

Body: the serialized `ParsedMeeting` (nested agenda items → motions/votes,
appearances, roster, documents with their `r2_key`s already filled in), plus an
optional top-level `"force": true`.

View flow:

1. **Deserialize & validate.** `MeetingSerializer(data=request.data)`,
   `is_valid(raise_exception=True)` → `400` with field detail on failure.
   `serializer.to_ir()` reconstructs the frozen dataclasses. `Decimal`/`date`/
   `time` round-trip precisely (`DecimalField`, `DateField`, `TimeField`) so a
   `$5,515,711.09` amount is never floated.
2. **Reviewed-data guard** (`services.meeting_has_reviewed_facts`). Look up the
   existing `Meeting` by `(source, source_meeting_id)`. If it exists and has any
   `reviewed=True` Vote / Appearance / Motion, and `force` is not set → `409
   Conflict` naming the meeting. The check lives in the API layer; `load_meeting`
   stays pure.
3. **Resolve entities.** `services.bcsd_context()` get-or-creates the BCSD
   `Jurisdiction` / `Source` / `Organization` using the same constants
   `ingest_bcsd` uses (extracted into the shared helper so they live in one place;
   `ingest_bcsd` is refactored to import them).
4. **Load.** Call the existing
   `load_meeting(parsed, source=…, jurisdiction=…, body=…)` — same transaction,
   same idempotent wipe-and-recreate, same `reviewed=False` proposals.
5. **Respond `201`** with a summary:
   ```json
   {"slug": "...", "source_meeting_id": "...", "agenda_items": 12, "votes": 30,
    "appearances": 7, "attachments": 4, "reviewed": false}
   ```

### Serializers (`serializers.py`)

One DRF `Serializer` per IR dataclass, nested to mirror the structure:

- `ParsedPersonSerializer`, `ParsedVoteSerializer`, `ParsedMotionSerializer`,
  `ParsedAppearanceSerializer`, `ParsedAgendaItemSerializer`,
  `ParsedDocumentSerializer`, `ParsedMeetingSerializer`.
- Field types chosen for exact round-trip:
  - amounts → `DecimalField(max_digits=14, decimal_places=2, allow_null=True)` (matches `AgendaItem.amount`)
  - `date`/`start_time` → `DateField` / `TimeField(allow_null=True)`
  - nested tuples → nested serializer with `many=True`
  - string enums (`"yea"`, `"action"`, `"unanimous"`) → `CharField`; the loader
    already maps them via plain lookups, so no enum coercion here.
- Each serializer exposes a `to_ir()` that returns the corresponding frozen
  dataclass, converting nested lists back to tuples (the dataclasses are
  `frozen=True` with `tuple` fields).
- Unknown/`reviewed`-style fields are not accepted from the client; the loader
  controls review state.

## Error handling

| Condition | Status |
|---|---|
| Missing / blank / wrong bearer token | `401` |
| Malformed IR / failed validation | `400` (field errors) |
| Re-post over reviewed facts without `force` | `409` |
| Uploads requested but no R2 configured | `503` |
| Loader `ValueError` (duplicate vote, bad enum, unslug-able person) | `422` with the loader's message |
| Meeting ingest success | `201` |
| Uploads success | `200` |

The `422` path is a small wrapper: the view catches `ValueError` from
`load_meeting` and returns it as a structured error rather than a `500`.

## Settings & config

- `INGEST_API_TOKEN = env("INGEST_API_TOKEN", default="")` — added to
  `.env.example` with a generation hint
  (`uv run python -c "import secrets; print(secrets.token_urlsafe(48))"`); set as
  a k8s secret in prod.
- `INGEST_UPLOAD_URL_TTL = env.int("INGEST_UPLOAD_URL_TTL", default=3600)`.
- No new dependencies — DRF and boto3 (via `django-storages`) are already present.

## Reference local client: `push_bcsd` management command

`catalog/management/commands/push_bcsd.py`. Mirrors `ingest_bcsd` but targets the
API instead of the DB:

1. `parse_meeting_folder(folder)` → `ParsedMeeting` (reuses the existing adapter).
2. Collect attachment `r2_key`s; `POST /api/v1/uploads` to get presigned URLs.
3. `PUT` each returned file to its URL (plain `urllib`/`requests`; skip keys the
   server reported as already present).
4. Serialize the IR to JSON and `POST /api/v1/meetings`.
5. Print the server's summary.

Arguments / config:
- `folder` (positional).
- `--api-base` (or `INGEST_API_BASE` env), e.g. `https://vault.civpulse.org`.
- token from `INGEST_API_TOKEN` env.
- `--force` → sets `"force": true` in the meetings POST.
- `--no-upload` → skip the upload step (metadata-only re-post).

Serializing the IR client-side reuses the same serializers (or a small
`dataclasses.asdict` + JSON-safe encoder for `Decimal`/`date`); the server is the
source of truth for validation.

## Testing (pytest-django)

- **Serializers:** IR → JSON → IR equality; `Decimal`/`date`/`time` precision;
  nested motions/votes survive the round-trip.
- **Auth:** no token / wrong token / right token; unset-env → deny.
- **Uploads:** already-present key skipped; missing key presigned; filesystem
  fallback → `503` (monkeypatch `default_storage` / the boto3 client).
- **Meetings:** happy path writes `reviewed=False`; re-post of an unreviewed
  meeting re-ingests; re-post over a `reviewed=True` fact → `409`; `force=true`
  overrides; bad enum → `422`.
- **`push_bcsd`:** end-to-end against Django's test client or a mocked API base
  (parse a fixture folder → assert the right calls/payloads).

## Build sequence

1. Settings: `INGEST_API_TOKEN`, `INGEST_UPLOAD_URL_TTL`, `.env.example`.
2. `auth.py` + tests.
3. `serializers.py` + round-trip tests.
4. `services.py` (extract BCSD constants from `ingest_bcsd`; reviewed-fact guard).
5. `uploads.py` + `UploadsView` + tests.
6. `MeetingsView` + tests.
7. `urls.py` wiring + the `api/v1/` include.
8. `push_bcsd` command + tests.
9. Docs: README "Remote ingest" section; k8s secret note.
