# Remote Ingest API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authenticated `/api/v1` endpoints so a local tool can push parsed BCSD meeting IR to production and obtain presigned R2 upload URLs, reusing the existing `load_meeting` loader unchanged.

**Architecture:** A new `catalog/api/` package wraps the existing framework-neutral ingest IR + loaders behind two DRF `APIView`s. The local `push_bcsd` command parses a folder locally, requests presigned PUT URLs, uploads files straight to R2, then POSTs the serialized IR. A single static bearer token authenticates; a guard refuses to clobber `reviewed=True` facts unless `force` is passed.

**Tech Stack:** Django 6, Django REST Framework (already a dependency), boto3 (via django-storages, already present), pytest + pytest-django. No new dependencies. All Python via `uv run`.

**Reference:** Design doc at `docs/superpowers/specs/2026-06-06-remote-ingest-api-design.md`.

**Conventions to follow:**
- Run Python with `uv run` (never bare `python`).
- Lint with `uv run ruff check` and `uv run ruff format` before each commit.
- Run tests with `uv run pytest`.
- Conventional Commit messages; commit at the end of every task.
- Tests live in `catalog/tests/`, use `@pytest.mark.django_db` where the DB is touched, and build IR dataclasses directly (see `catalog/tests/test_ingest_loader.py` for the pattern).

---

## File Structure

| File | Responsibility |
|---|---|
| `catalog/api/__init__.py` | package marker (empty) |
| `catalog/api/auth.py` | `BearerTokenAuthentication` + `HasValidIngestToken` permission |
| `catalog/api/services.py` | shared BCSD `Jurisdiction`/`Source`/`Organization` get-or-create + `meeting_has_reviewed_facts` guard |
| `catalog/api/serializers.py` | DRF serializers for the IR + `to_ir()` rebuild + `payload_from_meeting()` for the client |
| `catalog/api/uploads.py` | R2 presigned-PUT generation + remote-storage detection |
| `catalog/api/views.py` | `UploadsView`, `MeetingsView` |
| `catalog/api/urls.py` | route `/uploads` and `/meetings` |
| `catalog/management/commands/push_bcsd.py` | reference local client |
| `civicvault/settings.py` | add `INGEST_API_TOKEN`, `INGEST_UPLOAD_URL_TTL`, expose `R2_*` settings |
| `civicvault/urls.py` | include `catalog.api.urls` at `api/v1/` |
| `catalog/management/commands/ingest_bcsd.py` | refactor to import BCSD constants from `services.py` |
| `.env.example` | document `INGEST_API_TOKEN` |
| `README.md` | "Remote ingest" section |

Test files (one per module): `catalog/tests/test_api_auth.py`, `test_api_services.py`, `test_api_serializers.py`, `test_api_uploads.py`, `test_api_meetings.py`, `test_push_bcsd_command.py`.

---

## Task 1: Settings & config

**Files:**
- Modify: `civicvault/settings.py`
- Modify: `.env.example`

- [ ] **Step 1: Expose R2 settings and the ingest knobs**

In `civicvault/settings.py`, find the `STORAGES = build_storages(...)` block. Replace the inline `env(...)` calls with named module-level settings, then pass them in, and add the two ingest settings directly below the block:

```python
# Object storage (Cloudflare R2 via the S3 API; R2 has zero egress fees).
# Unset R2_BUCKET → local filesystem storage so dev works without credentials.
R2_BUCKET = env("R2_BUCKET", default="")
R2_ENDPOINT_URL = env("R2_ENDPOINT_URL", default="")
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
R2_CUSTOM_DOMAIN = env("R2_CUSTOM_DOMAIN", default="")

STORAGES = build_storages(
    bucket=R2_BUCKET,
    endpoint_url=R2_ENDPOINT_URL,
    access_key=R2_ACCESS_KEY_ID,
    secret_key=R2_SECRET_ACCESS_KEY,
    custom_domain=R2_CUSTOM_DOMAIN,
)

# Remote ingest API (catalog/api). The token authenticates the local push tool;
# unset → the API denies every request. Presigned upload URLs expire after TTL.
INGEST_API_TOKEN = env("INGEST_API_TOKEN", default="")
INGEST_UPLOAD_URL_TTL = env.int("INGEST_UPLOAD_URL_TTL", default=3600)
```

- [ ] **Step 2: Document the token in `.env.example`**

Append to `.env.example` (after the R2 block):

```bash
# Remote ingest API token. Authenticates the local push tool (push_bcsd) to
# /api/v1. Unset → the API denies all requests. Generate a high-entropy value:
#   uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
# INGEST_API_TOKEN=
# Optional: presigned upload URL lifetime in seconds (default 3600).
# INGEST_UPLOAD_URL_TTL=3600
```

- [ ] **Step 3: Verify Django still boots**

Run: `uv run python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Lint & commit**

```bash
uv run ruff check civicvault/settings.py && uv run ruff format civicvault/settings.py
git add civicvault/settings.py .env.example
git commit -m "feat(api): expose R2 settings and ingest API config knobs"
```

---

## Task 2: Bearer-token authentication

**Files:**
- Create: `catalog/api/__init__.py`
- Create: `catalog/api/auth.py`
- Test: `catalog/tests/test_api_auth.py`

- [ ] **Step 1: Create the package marker**

Create `catalog/api/__init__.py` (empty file).

- [ ] **Step 2: Write the failing tests**

Create `catalog/tests/test_api_auth.py`:

```python
from django.contrib.auth.models import AnonymousUser

import pytest
from rest_framework import exceptions
from rest_framework.test import APIRequestFactory

from catalog.api.auth import BearerTokenAuthentication, HasValidIngestToken

TOKEN = "s3cret-ingest-token"


def _request(header=None):
    factory = APIRequestFactory()
    kwargs = {"HTTP_AUTHORIZATION": header} if header else {}
    return factory.post("/api/v1/meetings", **kwargs)


def test_valid_token_authenticates(settings):
    settings.INGEST_API_TOKEN = TOKEN
    user, auth = BearerTokenAuthentication().authenticate(_request(f"Bearer {TOKEN}"))
    assert isinstance(user, AnonymousUser)
    assert auth == TOKEN


def test_no_header_returns_none(settings):
    settings.INGEST_API_TOKEN = TOKEN
    assert BearerTokenAuthentication().authenticate(_request()) is None


def test_wrong_token_raises(settings):
    settings.INGEST_API_TOKEN = TOKEN
    with pytest.raises(exceptions.AuthenticationFailed):
        BearerTokenAuthentication().authenticate(_request("Bearer nope"))


def test_unconfigured_token_denies(settings):
    settings.INGEST_API_TOKEN = ""
    with pytest.raises(exceptions.AuthenticationFailed):
        BearerTokenAuthentication().authenticate(_request("Bearer anything"))


def test_authenticate_header_present():
    assert BearerTokenAuthentication().authenticate_header(_request()) == "Bearer"


def test_permission_checks_request_auth():
    perm = HasValidIngestToken()

    class _Req:
        auth = None

    assert perm.has_permission(_Req(), view=None) is False
    _Req.auth = TOKEN
    assert perm.has_permission(_Req(), view=None) is True
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest catalog/tests/test_api_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.api.auth'`.

- [ ] **Step 4: Implement the auth module**

Create `catalog/api/auth.py`:

```python
"""Single-token bearer authentication for the remote ingest API.

No user table: the token is a shared secret in settings.INGEST_API_TOKEN.
When the token is unset the authenticator denies everything — never an
accidental open door. Comparison is timing-safe.
"""

from django.contrib.auth.models import AnonymousUser
from django.utils.crypto import constant_time_compare
from rest_framework import authentication, exceptions, permissions


class BearerTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1")
        if not header:
            return None  # no credentials → let the permission return 401
        parts = header.split()
        if parts[0] != self.keyword:
            return None  # a different scheme; not ours to judge
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Invalid bearer header.")
        configured = settings_token()
        if not configured:
            raise exceptions.AuthenticationFailed("Ingest API token not configured.")
        if not constant_time_compare(parts[1], configured):
            raise exceptions.AuthenticationFailed("Invalid token.")
        return (AnonymousUser(), parts[1])

    def authenticate_header(self, request):
        # Returning a value makes DRF render auth failures as 401 (not 403).
        return self.keyword


def settings_token():
    from django.conf import settings

    return settings.INGEST_API_TOKEN


class HasValidIngestToken(permissions.BasePermission):
    message = "A valid ingest token is required."

    def has_permission(self, request, view):
        return bool(request.auth)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest catalog/tests/test_api_auth.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Lint & commit**

```bash
uv run ruff check catalog/api/ catalog/tests/test_api_auth.py && uv run ruff format catalog/api/ catalog/tests/test_api_auth.py
git add catalog/api/__init__.py catalog/api/auth.py catalog/tests/test_api_auth.py
git commit -m "feat(api): bearer-token authentication for the ingest API"
```

---

## Task 3: Services — BCSD context + reviewed-fact guard

**Files:**
- Create: `catalog/api/services.py`
- Modify: `catalog/management/commands/ingest_bcsd.py`
- Test: `catalog/tests/test_api_services.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_api_services.py`:

```python
import datetime

import pytest

from catalog.api.services import bcsd_context, meeting_has_reviewed_facts
from catalog.models import AgendaItem, Meeting, Person, Vote


@pytest.mark.django_db
def test_bcsd_context_is_idempotent():
    jur1, src1, body1 = bcsd_context()
    jur2, src2, body2 = bcsd_context()
    assert (jur1.pk, src1.pk, body1.pk) == (jur2.pk, src2.pk, body2.pk)
    assert src1.slug == "bcsd-boe-meetings"


@pytest.mark.django_db
def test_guard_false_for_unknown_meeting():
    _, source, _ = bcsd_context()
    assert meeting_has_reviewed_facts(source, "mid-404") is False


@pytest.mark.django_db
def test_guard_detects_reviewed_vote():
    jur, source, body = bcsd_context()
    meeting = Meeting.objects.create(
        source=source, jurisdiction=jur, body=body, source_meeting_id="mid-1",
        date=datetime.date(2025, 1, 9), kind=Meeting.Kind.BOARD, slug="m-1",
    )
    item = AgendaItem.objects.create(meeting=meeting, order=1, code="A", title="x")
    person = Person.objects.create(full_name="Jane Doe", slug="jane-doe")
    assert meeting_has_reviewed_facts(source, "mid-1") is False
    Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA, reviewed=True)
    assert meeting_has_reviewed_facts(source, "mid-1") is True
```

(Confirm `Meeting.Kind.BOARD` exists; if the enum member differs, use the actual value from `catalog/models/meeting.py`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest catalog/tests/test_api_services.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.api.services'`.

- [ ] **Step 3: Implement the services module**

Create `catalog/api/services.py`:

```python
"""Shared helpers for the ingest API: the BCSD entity context (one definition,
reused by both the API and the ingest_bcsd command) and the reviewed-fact guard
that protects human review work from being clobbered on re-ingest."""

from catalog.models import (
    Appearance,
    Jurisdiction,
    Meeting,
    Motion,
    Organization,
    Source,
    Vote,
)

JURISDICTION = {
    "slug": "bibb-county-boe",
    "name": "Bibb County Board of Education",
    "kind": Jurisdiction.Kind.SCHOOL_DISTRICT,
}
SOURCE = {"slug": "bcsd-boe-meetings", "name": "BCSD BOE Meetings", "adapter": "bcsd"}
BODY = {
    "slug": "boe",
    "name": "Bibb County Board of Education",
    "kind": Organization.Kind.COMMITTEE,
}


def bcsd_context():
    """get_or_create the BCSD Jurisdiction, Source, and Organization (body)."""
    jurisdiction, _ = Jurisdiction.objects.get_or_create(
        slug=JURISDICTION["slug"],
        defaults={"name": JURISDICTION["name"], "kind": JURISDICTION["kind"]},
    )
    source, _ = Source.objects.get_or_create(
        slug=SOURCE["slug"],
        defaults={
            "name": SOURCE["name"],
            "adapter": SOURCE["adapter"],
            "jurisdiction": jurisdiction,
        },
    )
    body, _ = Organization.objects.get_or_create(
        slug=BODY["slug"],
        jurisdiction=jurisdiction,
        defaults={"name": BODY["name"], "kind": BODY["kind"], "reviewed": True},
    )
    return jurisdiction, source, body


def meeting_has_reviewed_facts(source, source_meeting_id) -> bool:
    """True if a meeting (by natural key) already holds any reviewed=True
    Vote, Appearance, or Motion — the facts load_meeting would wipe."""
    meeting = Meeting.objects.filter(
        source=source, source_meeting_id=source_meeting_id
    ).first()
    if meeting is None:
        return False
    return (
        Vote.objects.filter(agenda_item__meeting=meeting, reviewed=True).exists()
        or Appearance.objects.filter(meeting=meeting, reviewed=True).exists()
        or Motion.objects.filter(agenda_item__meeting=meeting, reviewed=True).exists()
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest catalog/tests/test_api_services.py -v`
Expected: PASS (3 passed). If `Meeting` requires fields the test omitted, adjust the test's `Meeting.objects.create(...)` to satisfy NOT NULL columns (check `catalog/models/meeting.py`).

- [ ] **Step 5: Refactor `ingest_bcsd` to reuse the shared context**

In `catalog/management/commands/ingest_bcsd.py`, delete the module-level `JURISDICTION`, `SOURCE`, `BODY` dicts and the inline get_or_create block in `handle`. Replace the get_or_create block with:

```python
from catalog.api.services import bcsd_context
```
and in `handle`, swap the three get_or_create blocks for:
```python
        jurisdiction, source, body = bcsd_context()
```
Leave the rest of `handle` (parse, `load_meeting`, upload, summary) unchanged.

- [ ] **Step 6: Verify the existing command test still passes**

Run: `uv run pytest catalog/tests/test_ingest_bcsd_command.py -v`
Expected: PASS (no behavior change).

- [ ] **Step 7: Lint & commit**

```bash
uv run ruff check catalog/api/services.py catalog/management/commands/ingest_bcsd.py catalog/tests/test_api_services.py && uv run ruff format catalog/api/services.py catalog/management/commands/ingest_bcsd.py catalog/tests/test_api_services.py
git add catalog/api/services.py catalog/management/commands/ingest_bcsd.py catalog/tests/test_api_services.py
git commit -m "feat(api): BCSD context + reviewed-fact guard, shared with ingest_bcsd"
```

---

## Task 4: IR serializers (round-trip)

**Files:**
- Create: `catalog/api/serializers.py`
- Test: `catalog/tests/test_api_serializers.py`

- [ ] **Step 1: Write the failing round-trip test**

Create `catalog/tests/test_api_serializers.py`:

```python
import datetime
import json
from decimal import Decimal

from catalog.api.serializers import MeetingSerializer, payload_from_meeting
from catalog.ingest.ir import (
    ParsedAgendaItem,
    ParsedAppearance,
    ParsedDocument,
    ParsedMeeting,
    ParsedMotion,
    ParsedPerson,
    ParsedVote,
)


def _meeting():
    p = ParsedPerson(full_name="Henry Ficklin", raw_name="Mr. Ficklin", role_hint="President")
    voter = ParsedPerson(full_name="Lisa Garrett-Boyd", raw_name="Ms. Garrett-Boyd")
    item = ParsedAgendaItem(
        order=5, code="FSS-3", title="Math adoption", item_type="action",
        reading_stage="", section="V. FISCAL", outcome_text="Approved",
        outcome_status="passed", amount=Decimal("5515711.09"), amount_text="$5,515,711.09",
        motions=(ParsedMotion(kind="simple", sequence=1, moved_by=p, seconded_by=voter,
                              result_text="Approved", status="passed"),),
        votes=(ParsedVote(person=voter, value="yea"),),
        file_names=("budget.pdf",),
    )
    doc = ParsedDocument(
        kind="policy", title="Budget", source_path="/tmp/budget.pdf", text="",
        r2_key="BCSD/2025/budget.pdf", ocr_status="has_text",
        agenda_item_code="FSS-3", is_attachment=True,
    )
    return ParsedMeeting(
        date=datetime.date(2025, 1, 9), start_time=datetime.time(19, 0),
        kind_slug="board", source_meeting_id="mid-1", source_url="https://x",
        source_path="/tmp/m", folder_name="2025-01-09 Board", title="Board Meeting",
        roster=(p,), agenda_items=(item,), appearances=(ParsedAppearance(person=p, role="member"),),
        has_minutes=True, raw_documents=(doc,),
    )


def test_round_trip_through_json():
    original = _meeting()
    # Simulate the wire: dataclass → JSON string → dict → serializer → dataclass.
    wire = json.loads(json.dumps(payload_from_meeting(original), default=str))
    serializer = MeetingSerializer(data=wire)
    assert serializer.is_valid(), serializer.errors
    rebuilt = serializer.to_ir()
    assert rebuilt == original


def test_decimal_precision_preserved():
    wire = json.loads(json.dumps(payload_from_meeting(_meeting()), default=str))
    rebuilt = MeetingSerializer(data=wire)
    assert rebuilt.is_valid(), rebuilt.errors
    assert rebuilt.to_ir().agenda_items[0].amount == Decimal("5515711.09")


def test_payload_is_plain_data():
    payload = payload_from_meeting(_meeting())
    assert isinstance(payload, dict)
    assert payload["agenda_items"][0]["votes"][0]["value"] == "yea"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest catalog/tests/test_api_serializers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.api.serializers'`.

- [ ] **Step 3: Implement the serializers**

Create `catalog/api/serializers.py`:

```python
"""DRF serializers mirroring the ingest IR (catalog/ingest/ir.py). They validate
inbound JSON and rebuild the frozen IR dataclasses via `to_ir()`. The IR is the
published API contract; field types are chosen for exact round-trip (Decimal,
date, time). `payload_from_meeting` does the inverse (dataclass → JSON-safe dict)
for the local push client and tests."""

import dataclasses

from rest_framework import serializers

from catalog.ingest import ir


class PersonSerializer(serializers.Serializer):
    full_name = serializers.CharField()
    raw_name = serializers.CharField()
    role_hint = serializers.CharField(required=False, allow_blank=True, default="")


class VoteSerializer(serializers.Serializer):
    person = PersonSerializer()
    value = serializers.CharField()


class MotionSerializer(serializers.Serializer):
    kind = serializers.CharField()
    sequence = serializers.IntegerField()
    moved_by = PersonSerializer(required=False, allow_null=True)
    seconded_by = PersonSerializer(required=False, allow_null=True)
    result_text = serializers.CharField(allow_blank=True)
    status = serializers.CharField()


class AppearanceSerializer(serializers.Serializer):
    person = PersonSerializer()
    role = serializers.CharField()


class AgendaItemSerializer(serializers.Serializer):
    order = serializers.IntegerField()
    code = serializers.CharField(allow_blank=True)
    title = serializers.CharField(allow_blank=True)
    item_type = serializers.CharField()
    reading_stage = serializers.CharField(allow_blank=True)
    section = serializers.CharField(allow_blank=True)
    outcome_text = serializers.CharField(required=False, allow_blank=True, default="")
    outcome_status = serializers.CharField(required=False, default="none")
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True, default=None
    )
    amount_text = serializers.CharField(required=False, allow_blank=True, default="")
    motions = MotionSerializer(many=True, required=False, default=list)
    votes = VoteSerializer(many=True, required=False, default=list)
    file_names = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )


class DocumentSerializer(serializers.Serializer):
    kind = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    source_path = serializers.CharField(allow_blank=True)
    text = serializers.CharField(allow_blank=True)
    r2_key = serializers.CharField(required=False, allow_blank=True, default="")
    ocr_status = serializers.CharField(required=False, default="unknown")
    agenda_item_code = serializers.CharField(required=False, allow_null=True, default=None)
    is_attachment = serializers.BooleanField(required=False, default=False)


class MeetingSerializer(serializers.Serializer):
    date = serializers.DateField()
    start_time = serializers.TimeField(required=False, allow_null=True, default=None)
    kind_slug = serializers.CharField()
    source_meeting_id = serializers.CharField()
    source_url = serializers.CharField(allow_blank=True)
    source_path = serializers.CharField(allow_blank=True)
    folder_name = serializers.CharField(allow_blank=True)
    title = serializers.CharField(allow_blank=True)
    roster = PersonSerializer(many=True, required=False, default=list)
    agenda_items = AgendaItemSerializer(many=True, required=False, default=list)
    appearances = AppearanceSerializer(many=True, required=False, default=list)
    has_minutes = serializers.BooleanField(required=False, default=False)
    raw_documents = DocumentSerializer(many=True, required=False, default=list)

    def to_ir(self) -> ir.ParsedMeeting:
        d = self.validated_data
        return ir.ParsedMeeting(
            date=d["date"],
            start_time=d["start_time"],
            kind_slug=d["kind_slug"],
            source_meeting_id=d["source_meeting_id"],
            source_url=d["source_url"],
            source_path=d["source_path"],
            folder_name=d["folder_name"],
            title=d["title"],
            roster=tuple(_person(p) for p in d["roster"]),
            agenda_items=tuple(_agenda_item(a) for a in d["agenda_items"]),
            appearances=tuple(_appearance(a) for a in d["appearances"]),
            has_minutes=d["has_minutes"],
            raw_documents=tuple(_document(x) for x in d["raw_documents"]),
        )


def _person(d) -> ir.ParsedPerson:
    return ir.ParsedPerson(
        full_name=d["full_name"], raw_name=d["raw_name"], role_hint=d.get("role_hint", "")
    )


def _opt_person(d):
    return _person(d) if d else None


def _vote(d) -> ir.ParsedVote:
    return ir.ParsedVote(person=_person(d["person"]), value=d["value"])


def _motion(d) -> ir.ParsedMotion:
    return ir.ParsedMotion(
        kind=d["kind"], sequence=d["sequence"], moved_by=_opt_person(d.get("moved_by")),
        seconded_by=_opt_person(d.get("seconded_by")), result_text=d["result_text"],
        status=d["status"],
    )


def _appearance(d) -> ir.ParsedAppearance:
    return ir.ParsedAppearance(person=_person(d["person"]), role=d["role"])


def _agenda_item(d) -> ir.ParsedAgendaItem:
    return ir.ParsedAgendaItem(
        order=d["order"], code=d["code"], title=d["title"], item_type=d["item_type"],
        reading_stage=d["reading_stage"], section=d["section"],
        outcome_text=d.get("outcome_text", ""), outcome_status=d.get("outcome_status", "none"),
        amount=d.get("amount"), amount_text=d.get("amount_text", ""),
        motions=tuple(_motion(m) for m in d.get("motions", [])),
        votes=tuple(_vote(v) for v in d.get("votes", [])),
        file_names=tuple(d.get("file_names", [])),
    )


def _document(d) -> ir.ParsedDocument:
    return ir.ParsedDocument(
        kind=d["kind"], title=d["title"], source_path=d["source_path"], text=d["text"],
        r2_key=d.get("r2_key", ""), ocr_status=d.get("ocr_status", "unknown"),
        agenda_item_code=d.get("agenda_item_code"), is_attachment=d.get("is_attachment", False),
    )


def payload_from_meeting(parsed: ir.ParsedMeeting) -> dict:
    """Dataclass → plain dict (tuples become lists). JSON-encode with
    `json.dumps(..., default=str)` so Decimal/date/time serialize as strings the
    serializers parse back exactly."""
    return dataclasses.asdict(parsed)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest catalog/tests/test_api_serializers.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint & commit**

```bash
uv run ruff check catalog/api/serializers.py catalog/tests/test_api_serializers.py && uv run ruff format catalog/api/serializers.py catalog/tests/test_api_serializers.py
git add catalog/api/serializers.py catalog/tests/test_api_serializers.py
git commit -m "feat(api): IR serializers with exact round-trip + payload builder"
```

---

## Task 5: Presigned uploads + UploadsView

**Files:**
- Create: `catalog/api/uploads.py`
- Create: `catalog/api/views.py` (UploadsView only this task)
- Create: `catalog/api/urls.py`
- Modify: `civicvault/urls.py`
- Test: `catalog/tests/test_api_uploads.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_api_uploads.py`:

```python
import pytest
from rest_framework.test import APIClient

from catalog.api import uploads as uploads_mod

TOKEN = "s3cret-ingest-token"


def _client(settings):
    settings.INGEST_API_TOKEN = TOKEN
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
    return c


@pytest.mark.django_db
def test_uploads_requires_auth(settings):
    settings.INGEST_API_TOKEN = TOKEN
    resp = APIClient().post("/api/v1/uploads", {"keys": ["a"]}, format="json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_uploads_503_without_remote_storage(settings):
    # Default test storage is the filesystem fallback → no remote storage.
    resp = _client(settings).post("/api/v1/uploads", {"keys": ["a"]}, format="json")
    assert resp.status_code == 503


@pytest.mark.django_db
def test_uploads_presigns_missing_and_skips_present(settings, monkeypatch):
    monkeypatch.setattr(uploads_mod, "remote_storage_available", lambda: True)

    class _Storage:
        def exists(self, key):
            return key == "present.pdf"

    class _S3:
        def generate_presigned_url(self, op, Params, ExpiresIn):
            return f"https://r2.example/{Params['Key']}?sig=1"

    monkeypatch.setattr(uploads_mod, "default_storage", _Storage())
    monkeypatch.setattr(uploads_mod, "_client", lambda: _S3())

    resp = _client(settings).post(
        "/api/v1/uploads", {"keys": ["missing.pdf", "present.pdf"]}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped"] == ["present.pdf"]
    assert len(body["uploads"]) == 1
    assert body["uploads"][0]["key"] == "missing.pdf"
    assert body["uploads"][0]["url"].startswith("https://r2.example/missing.pdf")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest catalog/tests/test_api_uploads.py -v`
Expected: FAIL — `404` / import error (URLs and modules don't exist yet).

- [ ] **Step 3: Implement the uploads helper**

Create `catalog/api/uploads.py`:

```python
"""R2 presigned-PUT generation for the ingest API. Builds a boto3 S3 client from
the R2 settings and signs PUT URLs that target the R2 S3 endpoint directly, so
the local tool uploads large media without it transiting the app pod. Idempotent:
keys already present in the bucket are skipped (mirrors ingest.storage)."""

import boto3
from botocore.config import Config
from django.conf import settings
from django.core.files.storage import FileSystemStorage, default_storage


def remote_storage_available() -> bool:
    """False on the local filesystem fallback (no R2_BUCKET configured)."""
    return not isinstance(default_storage, FileSystemStorage)


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def presign_uploads(keys) -> dict:
    client = _client()
    bucket = settings.R2_BUCKET
    ttl = settings.INGEST_UPLOAD_URL_TTL
    uploads, skipped = [], []
    for key in keys:
        if default_storage.exists(key):
            skipped.append(key)
            continue
        url = client.generate_presigned_url(
            "put_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=ttl
        )
        uploads.append({"key": key, "url": url, "expires_in": ttl})
    return {"uploads": uploads, "skipped": skipped}
```

- [ ] **Step 4: Implement UploadsView**

Create `catalog/api/views.py`:

```python
"""Ingest API views: presigned uploads + meeting ingest. Thin wrappers over the
existing IR loaders; all auth via the single bearer token."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.api.auth import BearerTokenAuthentication, HasValidIngestToken
from catalog.api.serializers import UploadRequestSerializer
from catalog.api.uploads import presign_uploads, remote_storage_available


class UploadsView(APIView):
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [HasValidIngestToken]

    def post(self, request):
        if not remote_storage_available():
            return Response(
                {"detail": "No remote storage configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        serializer = UploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(presign_uploads(serializer.validated_data["keys"]))
```

- [ ] **Step 5: Add `UploadRequestSerializer` to serializers.py**

Append to `catalog/api/serializers.py`:

```python
class UploadRequestSerializer(serializers.Serializer):
    keys = serializers.ListField(child=serializers.CharField(), allow_empty=False)
```

- [ ] **Step 6: Wire URLs**

Create `catalog/api/urls.py`:

```python
"""Routes for the remote ingest API (mounted at /api/v1/)."""

from django.urls import path

from catalog.api.views import UploadsView

urlpatterns = [
    path("uploads", UploadsView.as_view(), name="api-uploads"),
]
```

In `civicvault/urls.py`, add the include (keep the existing imports):

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("catalog.api.urls")),
    path("", include("core.urls")),
]
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest catalog/tests/test_api_uploads.py -v`
Expected: PASS (3 passed).

- [ ] **Step 8: Lint & commit**

```bash
uv run ruff check catalog/api/ civicvault/urls.py catalog/tests/test_api_uploads.py && uv run ruff format catalog/api/ civicvault/urls.py catalog/tests/test_api_uploads.py
git add catalog/api/uploads.py catalog/api/views.py catalog/api/urls.py catalog/api/serializers.py civicvault/urls.py catalog/tests/test_api_uploads.py
git commit -m "feat(api): presigned R2 upload endpoint"
```

---

## Task 6: MeetingsView

**Files:**
- Modify: `catalog/api/views.py`
- Modify: `catalog/api/urls.py`
- Test: `catalog/tests/test_api_meetings.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_api_meetings.py`:

```python
import datetime
import json
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from catalog.api.serializers import payload_from_meeting
from catalog.ingest.ir import (
    ParsedAgendaItem,
    ParsedMeeting,
    ParsedPerson,
    ParsedVote,
)
from catalog.models import Vote

TOKEN = "s3cret-ingest-token"


def _client(settings):
    settings.INGEST_API_TOKEN = TOKEN
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
    return c


def _wire(parsed):
    return json.loads(json.dumps(payload_from_meeting(parsed), default=str))


def _meeting(source_meeting_id="mid-1"):
    voter = ParsedPerson(full_name="Lisa Garrett-Boyd", raw_name="Ms. Garrett-Boyd")
    item = ParsedAgendaItem(
        order=1, code="A-1", title="Adopt", item_type="action", reading_stage="",
        section="V", outcome_status="passed", amount=Decimal("100.00"),
        votes=(ParsedVote(person=voter, value="yea"),),
    )
    return ParsedMeeting(
        date=datetime.date(2025, 1, 9), start_time=None, kind_slug="board",
        source_meeting_id=source_meeting_id, source_url="https://x", source_path="/m",
        folder_name="f", title="Board Meeting", agenda_items=(item,),
    )


@pytest.mark.django_db
def test_post_meeting_creates_unreviewed_proposals(settings):
    resp = _client(settings).post("/api/v1/meetings", _wire(_meeting()), format="json")
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["source_meeting_id"] == "mid-1"
    assert body["votes"] == 1
    assert body["reviewed"] is False
    assert Vote.objects.filter(reviewed=False).count() == 1


@pytest.mark.django_db
def test_repost_unreviewed_meeting_succeeds(settings):
    client = _client(settings)
    client.post("/api/v1/meetings", _wire(_meeting()), format="json")
    resp = client.post("/api/v1/meetings", _wire(_meeting()), format="json")
    assert resp.status_code == 201


@pytest.mark.django_db
def test_repost_over_reviewed_fact_conflicts(settings):
    _client(settings).post("/api/v1/meetings", _wire(_meeting()), format="json")
    Vote.objects.update(reviewed=True)  # simulate admin review
    resp = _client(settings).post("/api/v1/meetings", _wire(_meeting()), format="json")
    assert resp.status_code == 409


@pytest.mark.django_db
def test_force_overrides_reviewed_conflict(settings):
    _client(settings).post("/api/v1/meetings", _wire(_meeting()), format="json")
    Vote.objects.update(reviewed=True)
    payload = _wire(_meeting())
    payload["force"] = True
    resp = _client(settings).post("/api/v1/meetings", payload, format="json")
    assert resp.status_code == 201
    assert Vote.objects.filter(reviewed=False).count() == 1  # wiped & recreated


@pytest.mark.django_db
def test_bad_vote_value_returns_422(settings):
    payload = _wire(_meeting())
    payload["agenda_items"][0]["votes"][0]["value"] = "maybe"
    resp = _client(settings).post("/api/v1/meetings", payload, format="json")
    assert resp.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest catalog/tests/test_api_meetings.py -v`
Expected: FAIL — `404` (the `/meetings` route does not exist yet).

- [ ] **Step 3: Add MeetingsView**

In `catalog/api/views.py`, **replace** the existing
`from catalog.api.serializers import UploadRequestSerializer` line with the
following three import lines (so `UploadRequestSerializer` is imported once):

```python
from catalog.api.serializers import MeetingSerializer, UploadRequestSerializer
from catalog.api.services import bcsd_context, meeting_has_reviewed_facts
from catalog.ingest.loader import load_meeting
```

Then append the view and helper:

```python
class MeetingsView(APIView):
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [HasValidIngestToken]

    def post(self, request):
        force = bool(request.data.get("force", False))
        serializer = MeetingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parsed = serializer.to_ir()

        jurisdiction, source, body = bcsd_context()
        if not force and meeting_has_reviewed_facts(source, parsed.source_meeting_id):
            return Response(
                {
                    "detail": (
                        f"Meeting {parsed.source_meeting_id} has reviewed facts; "
                        f"pass force=true to overwrite."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            meeting = load_meeting(
                parsed, source=source, jurisdiction=jurisdiction, body=body
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        return Response(_summary(parsed, meeting), status=status.HTTP_201_CREATED)


def _summary(parsed, meeting) -> dict:
    attachments = sum(1 for d in parsed.raw_documents if d.is_attachment)
    return {
        "slug": meeting.slug,
        "source_meeting_id": meeting.source_meeting_id,
        "agenda_items": meeting.agenda_items.count(),
        "votes": sum(i.votes.count() for i in meeting.agenda_items.all()),
        "appearances": meeting.appearances.count(),
        "attachments": attachments,
        "reviewed": False,
    }
```

- [ ] **Step 4: Route `/meetings`**

In `catalog/api/urls.py`, import `MeetingsView` and add the route:

```python
from catalog.api.views import MeetingsView, UploadsView

urlpatterns = [
    path("uploads", UploadsView.as_view(), name="api-uploads"),
    path("meetings", MeetingsView.as_view(), name="api-meetings"),
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest catalog/tests/test_api_meetings.py -v`
Expected: PASS (5 passed). If the bad-vote case surfaces as a serializer `400` rather than a loader `422`, that is acceptable (validation caught it earlier) — but the loader raises `ValueError` for unknown vote values, and `value` is a free `CharField`, so it should reach the loader and return `422`. Confirm the assertion matches reality; if DRF returns `400`, change the test's expected status to `400` and note that validation is stricter than planned.

- [ ] **Step 6: Lint & commit**

```bash
uv run ruff check catalog/api/views.py catalog/api/urls.py catalog/tests/test_api_meetings.py && uv run ruff format catalog/api/views.py catalog/api/urls.py catalog/tests/test_api_meetings.py
git add catalog/api/views.py catalog/api/urls.py catalog/tests/test_api_meetings.py
git commit -m "feat(api): meeting ingest endpoint with reviewed-fact guard"
```

---

## Task 7: `push_bcsd` reference client

**Files:**
- Create: `catalog/management/commands/push_bcsd.py`
- Test: `catalog/tests/test_push_bcsd_command.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_push_bcsd_command.py`. It monkeypatches the module-level HTTP helpers so no network is touched, and reuses the existing command test's `_stage_pair` helper to lay out a real meeting folder (the committee folder includes a real `hmh.pdf` attachment, which exercises the upload path).

```python
import pytest
from django.core.management import call_command

from catalog.management.commands import push_bcsd
# Reuse the folder-staging helper from the existing command test.
from catalog.tests.test_ingest_bcsd_command import _stage_pair

COMMITTEE = "2025-04-17_1600_committee-meeting_mid-124789"


@pytest.mark.django_db
def test_push_bcsd_uploads_then_posts(monkeypatch, tmp_path):
    posted = {}
    put_urls = []

    def fake_post(url, token, payload):
        if url.endswith("/uploads"):
            # Presign every requested key.
            return 200, {
                "uploads": [
                    {"key": k, "url": f"https://r2/{k}", "expires_in": 3600}
                    for k in payload["keys"]
                ],
                "skipped": [],
            }
        posted["url"] = url
        posted["payload"] = payload
        return 201, {"source_meeting_id": payload["source_meeting_id"], "votes": 0}

    def fake_put(url, path):
        put_urls.append(url)
        return 200

    monkeypatch.setattr(push_bcsd, "_post", fake_post)
    monkeypatch.setattr(push_bcsd, "_put_file", fake_put)

    root = _stage_pair(tmp_path)
    call_command(
        "push_bcsd", str(root / COMMITTEE),
        "--api-base", "https://vault.example", "--token", "t",
    )

    assert posted["url"] == "https://vault.example/api/v1/meetings"
    assert posted["payload"]["source_meeting_id"]
    # The committee folder's hmh.pdf attachment was uploaded via a presigned PUT.
    assert any("hmh.pdf" in u for u in put_urls)
```

Note: importing `_stage_pair` pulls in `catalog/tests/test_ingest_bcsd_command.py` at import time, which is fine (it only defines helpers/tests). If pytest collection objects to the cross-import, copy the `_stage_pair` body and its two `from catalog.tests.fixtures...` imports into this test file instead.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest catalog/tests/test_push_bcsd_command.py -v`
Expected: FAIL — `ModuleNotFoundError` / command not found.

- [ ] **Step 3: Implement the command**

Create `catalog/management/commands/push_bcsd.py`:

```python
"""Local client: parse a BCSD meeting folder, upload its attachments to R2 via
presigned URLs from the API, then POST the parsed IR to /api/v1/meetings. The
inverse of running ingest_bcsd against a direct DB connection — but it needs no
DB access, only the API token and base URL."""

import json
import os
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.api.serializers import payload_from_meeting
from catalog.ingest.bcsd.adapter import parse_meeting_folder


def _post(url, token, payload):
    body = json.dumps(payload, default=str).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310 (trusted operator URL)
        return resp.status, json.loads(resp.read())


def _put_file(url, path):
    with open(path, "rb") as fh:
        req = urllib.request.Request(url, data=fh.read(), method="PUT")
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        return resp.status


class Command(BaseCommand):
    help = "Parse a BCSD meeting folder and push it to the remote ingest API."

    def add_arguments(self, parser):
        parser.add_argument("folder")
        parser.add_argument("--api-base", default=os.environ.get("INGEST_API_BASE", ""))
        parser.add_argument("--token", default=os.environ.get("INGEST_API_TOKEN", ""))
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--no-upload", action="store_true")

    def handle(self, *args, **options):
        folder = Path(options["folder"])
        if not folder.is_dir():
            raise CommandError(f"Not a directory: {folder}")
        api_base = options["api_base"].rstrip("/")
        token = options["token"]
        if not api_base or not token:
            raise CommandError("Both --api-base and --token (or their env vars) are required.")

        parsed = parse_meeting_folder(folder)

        if not options["no_upload"]:
            attachments = {
                d.r2_key: d.source_path
                for d in parsed.raw_documents
                if d.is_attachment and d.r2_key and d.source_path
            }
            if attachments:
                status, body = _post(
                    f"{api_base}/api/v1/uploads", token, {"keys": list(attachments)}
                )
                if status != 200:
                    raise CommandError(f"Upload presign failed ({status}): {body}")
                for item in body["uploads"]:
                    _put_file(item["url"], attachments[item["key"]])
                self.stdout.write(
                    f"Uploaded {len(body['uploads'])}, skipped {len(body['skipped'])}."
                )

        payload = payload_from_meeting(parsed)
        if options["force"]:
            payload["force"] = True
        status, body = _post(f"{api_base}/api/v1/meetings", token, payload)
        if status not in (200, 201):
            raise CommandError(f"Meeting POST failed ({status}): {body}")
        self.stdout.write(self.style.SUCCESS(f"Pushed {body.get('source_meeting_id')}: {body}"))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest catalog/tests/test_push_bcsd_command.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Lint & commit**

```bash
uv run ruff check catalog/management/commands/push_bcsd.py catalog/tests/test_push_bcsd_command.py && uv run ruff format catalog/management/commands/push_bcsd.py catalog/tests/test_push_bcsd_command.py
git add catalog/management/commands/push_bcsd.py catalog/tests/test_push_bcsd_command.py
git commit -m "feat(api): push_bcsd local client for the remote ingest API"
```

---

## Task 8: Docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Remote ingest" section**

In `README.md`, add a section documenting the workflow (place it near the existing ingest docs):

```markdown
## Remote ingest (no DB connection)

A local tool can push parsed meetings to production over HTTP — no database
connection required. The server reuses the same loader as `ingest_bcsd`, writing
everything as `reviewed=False` proposals.

1. Set a token on the server (k8s secret) and locally:
   `INGEST_API_TOKEN=$(uv run python -c "import secrets; print(secrets.token_urlsafe(48))")`
2. Push a meeting folder:
   ```bash
   uv run python manage.py push_bcsd /path/to/meeting-folder \
     --api-base https://vault.civpulse.org --token "$INGEST_API_TOKEN"
   ```

The client parses the folder locally, requests presigned R2 upload URLs for
attachments, uploads the files directly to R2, then POSTs the meeting. Re-posting
a meeting that already has admin-reviewed facts is rejected unless you pass
`--force`.

**Endpoints** (both require `Authorization: Bearer <INGEST_API_TOKEN>`):
- `POST /api/v1/uploads` — `{"keys": [...]}` → presigned PUT URLs for missing keys.
- `POST /api/v1/meetings` — serialized meeting IR (+ optional `"force": true`).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(api): document the remote ingest workflow"
```

---

## Task 9: Full suite + final verification

- [ ] **Step 1: Run the whole test suite**

Run: `uv run pytest -q`
Expected: all pass (the new API tests plus the untouched existing suite).

- [ ] **Step 2: Lint the whole tree**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no errors; formatting clean.

- [ ] **Step 3: Django checks**

Run: `uv run python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 4: Confirm no migrations were needed**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected` (this feature adds no models).

---

## Deployment notes (out of plan scope, for the operator)

- Set `INGEST_API_TOKEN` as a Kubernetes secret and inject it into the app
  deployment env (same mechanism as the R2 keys). Without it the API denies all
  requests — safe by default.
- No migration to run. The deploy is the standard image build + rollout.
- The presigned-URL host is the R2 S3 endpoint (`<acct>.r2.cloudflarestorage.com`),
  which the local tool reaches directly; only the JSON API goes through the
  cloudflared tunnel.
```
