# CivicVault Foundation (Phase 0 + 1a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the infra skeleton (R2 storage, pytest, CI) and build the agency-agnostic `catalog` domain schema with the generic Citation provenance backbone — the foundation every later slice (parser, document ingest, recording, UI) builds on.

**Architecture:** A new Django app `catalog` holds the agency-agnostic domain model from brief §7 plus the §14.5 multi-agency additions (Jurisdiction, Source, slug namespacing). Models live in a `catalog/models/` package split by responsibility (one file per cluster). Provenance is enforced by a generic `Citation` model (a `GenericForeignKey` to any fact) plus an abstract `Reviewable` base giving every ingested fact `reviewed`/`confidence` flags — so ingestion can write proposals pending admin review from day one. Entities the vertical slice does not need yet (Office/OfficeTenure, Affiliation, Award/Bid, Relationship, Submission, RecordsRequest) are deliberately deferred to later phases.

**Tech Stack:** Django 6, PostgreSQL (psycopg3), `django-storages` (S3 API → Cloudflare R2), `django.contrib.postgres` (ArrayField, SearchVectorField, GinIndex), `django-environ`, pytest + pytest-django, ruff, GitHub Actions.

---

## Prerequisites

The local Postgres dev container must be running for any DB-backed test:

```bash
docker compose up -d db   # publishes on host port 5433; DATABASE_URL in .env points here
```

All Python commands run through `uv` (never system Python). Lint with `ruff` before every commit.

## File Structure

**Phase 0:**
- Modify `pyproject.toml` — add `pytest`, `pytest-django` dev deps + `[tool.pytest.ini_options]`.
- Create `civicvault/storage.py` — pure `build_storages()` helper (testable without settings reload).
- Modify `civicvault/settings.py` — call `build_storages()`; add `django.contrib.postgres` + `catalog` to `INSTALLED_APPS`.
- Create `tests/test_storage.py` — unit tests for `build_storages()`.
- Modify `.env.example` — document the R2 env vars.
- Create `.github/workflows/ci.yml` — ruff + pytest with a Postgres service.

**Phase 1a (`catalog` app):**
- `catalog/models/base.py` — `TimeStamped`, `Reviewable` abstracts.
- `catalog/models/org.py` — `Jurisdiction`, `Source`, `Organization`, `Person`.
- `catalog/models/meeting.py` — `Meeting`, `AgendaItem`, slug→kind map.
- `catalog/models/media.py` — `MediaAsset`, `Transcript`, `TranscriptSegment`, `MeetingCoverage`.
- `catalog/models/document.py` — `Document`.
- `catalog/models/facts.py` — `Vote`, `Appearance`.
- `catalog/models/citation.py` — `Citation` + `CitationManager`.
- `catalog/models/__init__.py` — re-export all models.
- `catalog/admin.py` — register every model.
- `catalog/migrations/` — one migration per model task.
- `catalog/tests/test_*.py` — TDD tests per cluster.

---

## Phase 0 — Finish the infra skeleton

### Task 1: Test harness (pytest + pytest-django)

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Add dev dependencies**

Run:
```bash
uv add --dev pytest pytest-django
```

- [ ] **Step 2: Configure pytest**

Add to `pyproject.toml` (after the `[tool.ruff.lint]` block):

```toml
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "civicvault.settings"
python_files = ["test_*.py", "tests.py", "*_test.py"]
```

> Do **not** set `addopts = "--reuse-db"`: this plan adds a migration in most tasks, and `--reuse-db` makes pytest-django skip applying new migrations to an existing test DB (causing missing-table failures). Let the test DB be rebuilt each run. Do **not** set `testpaths` either — later tasks put tests under `catalog/tests/`, which auto-discovery finds.

- [ ] **Step 3: Write the failing smoke test**

Create `tests/__init__.py` (empty) and `tests/test_smoke.py`:

```python
def test_settings_import():
    from django.conf import settings

    assert settings.INSTALLED_APPS  # settings module loads under pytest-django
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: 1 passed. (Confirms pytest-django finds the settings module.)

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add pyproject.toml uv.lock tests/
git commit -m "test: add pytest + pytest-django harness"
```

---

### Task 2: Configure Cloudflare R2 storage

**Files:**
- Create: `civicvault/storage.py`
- Modify: `civicvault/settings.py:130-137` (the Static files section — append after it)
- Create: `tests/test_storage.py`
- Modify: `.env.example`

- [ ] **Step 1: Write the failing test**

Create `tests/test_storage.py`:

```python
from civicvault.storage import build_storages

S3_BACKEND = "storages.backends.s3.S3Storage"
FS_BACKEND = "django.core.files.storage.FileSystemStorage"


def test_no_bucket_falls_back_to_filesystem():
    storages = build_storages(bucket="", endpoint_url="", access_key="", secret_key="")
    assert storages["default"]["BACKEND"] == FS_BACKEND


def test_bucket_set_uses_r2_s3_backend():
    storages = build_storages(
        bucket="civicvault-media",
        endpoint_url="https://acct.r2.cloudflarestorage.com",
        access_key="AK",
        secret_key="SK",
    )
    default = storages["default"]
    assert default["BACKEND"] == S3_BACKEND
    opts = default["OPTIONS"]
    assert opts["bucket_name"] == "civicvault-media"
    assert opts["endpoint_url"] == "https://acct.r2.cloudflarestorage.com"
    assert opts["region_name"] == "auto"
    assert opts["addressing_style"] == "path"  # R2-correct; guards the value
    assert opts["default_acl"] is None
    assert opts["querystring_auth"] is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'civicvault.storage'`.

- [ ] **Step 3: Implement the helper**

Create `civicvault/storage.py`:

```python
"""Storage backend wiring for Cloudflare R2 (S3 API).

Extracted into a pure function so it can be unit-tested without reloading
Django settings. When no bucket is configured (local dev without R2
credentials), fall back to local filesystem storage.
"""

S3_BACKEND = "storages.backends.s3.S3Storage"
FILESYSTEM_BACKEND = "django.core.files.storage.FileSystemStorage"
STATICFILES_BACKEND = "django.contrib.staticfiles.storage.StaticFilesStorage"


def build_storages(*, bucket, endpoint_url, access_key, secret_key):
    """Return a Django STORAGES dict. R2 if a bucket is set, else filesystem."""
    staticfiles = {"BACKEND": STATICFILES_BACKEND}
    if not bucket:
        return {
            "default": {"BACKEND": FILESYSTEM_BACKEND},
            "staticfiles": staticfiles,
        }
    return {
        "default": {
            "BACKEND": S3_BACKEND,
            "OPTIONS": {
                "bucket_name": bucket,
                "endpoint_url": endpoint_url,
                "access_key": access_key,
                "secret_key": secret_key,
                # R2 ignores regions; "auto" is the documented value.
                "region_name": "auto",
                "signature_version": "s3v4",
                # R2 supports both path- and virtual-hosted style; Cloudflare's
                # own SDK examples use path-style, which avoids bucket-name DNS
                # edge cases on the S3 API endpoint.
                "addressing_style": "path",
                "default_acl": None,
                # Public assets are served via Cloudflare cache, not signed URLs.
                "querystring_auth": False,
            },
        },
        "staticfiles": staticfiles,
    }
```

- [ ] **Step 4: Wire it into settings**

In `civicvault/settings.py`, append after the Static files section (after line 136, the `STATIC_ROOT` line):

Add `from civicvault.storage import build_storages` to the imports at the **top** of `settings.py` (alongside `import environ`), then add this block after the Static files section:

```python
# Object storage (Cloudflare R2 via the S3 API; R2 has zero egress fees).
# Unset R2_BUCKET → local filesystem storage so dev works without credentials.
STORAGES = build_storages(
    bucket=env("R2_BUCKET", default=""),
    endpoint_url=env("R2_ENDPOINT_URL", default=""),
    access_key=env("R2_ACCESS_KEY_ID", default=""),
    secret_key=env("R2_SECRET_ACCESS_KEY", default=""),
)
```

- [ ] **Step 5: Document the env vars**

Append to `.env.example`:

```bash

# Cloudflare R2 object storage (media: PDFs, audio, video). Leave R2_BUCKET
# empty for local dev to fall back to filesystem storage. R2 has zero egress.
# R2_BUCKET=civicvault-media
# R2_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com
# R2_ACCESS_KEY_ID=
# R2_SECRET_ACCESS_KEY=
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -v`
Expected: 2 passed.

Also confirm settings still import:
Run: `uv run python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 7: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add civicvault/storage.py civicvault/settings.py tests/test_storage.py .env.example
git commit -m "feat: wire django-storages to Cloudflare R2 with filesystem fallback"
```

---

### Task 3: Continuous integration (GitHub Actions)

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_USER: civicvault
          POSTGRES_PASSWORD: civicvault
          POSTGRES_DB: civicvault
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DATABASE_URL: postgres://civicvault:civicvault@localhost:5432/civicvault
      DEBUG: "True"
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v5
      - name: Set up Python
        run: uv python install 3.12
      - name: Install dependencies
        run: uv sync --dev
      - name: Lint
        run: |
          uv run ruff check .
          uv run ruff format --check .
      - name: Run tests
        run: uv run pytest -v
```

- [ ] **Step 2: Validate locally that the test command works against the dev DB**

Run: `uv run pytest -v`
Expected: all tests pass (Task 1 + Task 2 tests).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow (ruff + pytest with Postgres)"
```

---

## Phase 1a — The `catalog` domain schema + provenance backbone

> **Note on migrations:** create the migration inside each model task (`uv run python manage.py makemigrations catalog`) so that task's DB-backed tests pass immediately. `ruff` already excludes `migrations/`.

### Task 4: Create the `catalog` app + abstract base models

**Files:**
- Create: `catalog/` app (via `startapp`)
- Modify: `civicvault/settings.py:46-57` (`INSTALLED_APPS`)
- Create: `catalog/models/__init__.py`, `catalog/models/base.py`
- Delete: `catalog/models.py` (replaced by the package)
- Create: `catalog/tests/__init__.py`, `catalog/tests/test_base.py`

- [ ] **Step 1: Scaffold the app**

Run:
```bash
uv run python manage.py startapp catalog
rm catalog/models.py
mkdir catalog/models catalog/tests
touch catalog/tests/__init__.py
```

- [ ] **Step 2: Register the app + contrib.postgres**

In `civicvault/settings.py`, change the `INSTALLED_APPS` blocks so the contrib and local sections read:

```python
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # Third-party
    "rest_framework",
    # Local
    "core",
    "catalog",
]
```

- [ ] **Step 3: Write the failing test for the abstract bases**

Create `catalog/tests/test_base.py`:

```python
from catalog.models.base import Reviewable, TimeStamped


def test_bases_are_abstract():
    assert TimeStamped._meta.abstract is True
    assert Reviewable._meta.abstract is True


def test_reviewable_defaults():
    field_names = {f.name for f in Reviewable._meta.get_fields()}
    assert {"created_at", "updated_at", "reviewed", "confidence"} <= field_names
    reviewed = Reviewable._meta.get_field("reviewed")
    assert reviewed.default is False
```

- [ ] **Step 4: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.models.base'`.

- [ ] **Step 5: Implement the abstract bases**

Create `catalog/models/base.py`:

```python
from django.db import models


class TimeStamped(models.Model):
    """Mixin: created/updated timestamps on every row."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Reviewable(TimeStamped):
    """A fact emitted by ingestion as a proposal pending admin review (brief §7).

    Nothing reviewed=False is shown to the public; the admin confirms facts
    before they become visible. `confidence` is the ingester's self-scoring.
    """

    reviewed = models.BooleanField(default=False)
    confidence = models.FloatField(null=True, blank=True)

    class Meta:
        abstract = True
```

Create `catalog/models/__init__.py`:

```python
from .base import Reviewable, TimeStamped

__all__ = ["Reviewable", "TimeStamped"]
```

- [ ] **Step 6: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_base.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ civicvault/settings.py
git commit -m "feat: add catalog app with TimeStamped/Reviewable abstract bases"
```

---

### Task 5: Jurisdiction + Source models (§14.5 multi-agency grouping)

**Files:**
- Create: `catalog/models/org.py` (Jurisdiction, Source — Organization/Person added in Task 6)
- Modify: `catalog/models/__init__.py`
- Create: `catalog/tests/test_org.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_org.py`:

```python
import pytest

from catalog.models import Jurisdiction, Source


@pytest.mark.django_db
def test_jurisdiction_and_source():
    jur = Jurisdiction.objects.create(
        name="Bibb County Board of Education",
        slug="bibb-county-boe",
        kind=Jurisdiction.Kind.SCHOOL_DISTRICT,
    )
    src = Source.objects.create(
        name="BCSD BOE Meetings",
        slug="bcsd-boe-meetings",
        jurisdiction=jur,
        adapter="bcsd",
    )
    assert str(jur) == "Bibb County Board of Education"
    assert str(src) == "bcsd-boe-meetings"
    assert src.jurisdiction == jur
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_org.py -v`
Expected: FAIL — `ImportError: cannot import name 'Jurisdiction'`.

- [ ] **Step 3: Implement Jurisdiction + Source**

Create `catalog/models/org.py`:

```python
from django.db import models

from .base import TimeStamped


class Jurisdiction(TimeStamped):
    """A government grouping (e.g. a school district, city, county) that
    meetings, offices, and source documents belong to (brief §14.5)."""

    class Kind(models.TextChoices):
        SCHOOL_DISTRICT = "school_district", "School District"
        CITY = "city", "City"
        COUNTY = "county", "County"
        OTHER = "other", "Other"

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Source(TimeStamped):
    """Provenance tag: which archive/adapter run a record came from (brief §14.5).
    Useful for re-ingestion, audits, and "where did this come from"."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    jurisdiction = models.ForeignKey(
        Jurisdiction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sources",
    )
    adapter = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.slug
```

Update `catalog/models/__init__.py`:

```python
from .base import Reviewable, TimeStamped
from .org import Jurisdiction, Source

__all__ = ["Jurisdiction", "Reviewable", "Source", "TimeStamped"]
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations catalog --name jurisdiction_source`
Expected: creates `catalog/migrations/0001_jurisdiction_source.py`.

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_org.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/
git commit -m "feat: add Jurisdiction and Source models"
```

---

### Task 6: Organization + Person (with slug namespacing)

**Files:**
- Modify: `catalog/models/org.py`
- Modify: `catalog/models/__init__.py`
- Modify: `catalog/tests/test_org.py`

- [ ] **Step 1: Write the failing tests**

Append to `catalog/tests/test_org.py`:

```python
from django.db import IntegrityError

from catalog.models import Organization, Person


@pytest.mark.django_db
def test_person_aka_and_slug():
    p = Person.objects.create(
        full_name="Myrtice Johnson",
        slug="myrtice-johnson",
        aka=["Ms. Myrtice Johnson"],
    )
    assert p.aka == ["Ms. Myrtice Johnson"]
    assert p.reviewed is False  # proposals default to unreviewed


@pytest.mark.django_db
def test_org_slug_unique_within_jurisdiction():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    Organization.objects.create(name="Finance Committee", slug="finance-committee", jurisdiction=jur)
    with pytest.raises(IntegrityError):
        Organization.objects.create(name="Finance Cmte", slug="finance-committee", jurisdiction=jur)


@pytest.mark.django_db
def test_global_vendor_slug_unique_when_no_jurisdiction():
    Organization.objects.create(name="CDW", slug="cdw", kind=Organization.Kind.COMPANY)
    with pytest.raises(IntegrityError):
        Organization.objects.create(name="CDW LLC", slug="cdw", kind=Organization.Kind.COMPANY)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_org.py -v`
Expected: FAIL — `ImportError: cannot import name 'Organization'`.

- [ ] **Step 3: Implement Organization + Person**

Add to `catalog/models/org.py` (add `ArrayField` import at the top, then append the two models):

At the top of the file, add the import:

```python
from django.contrib.postgres.fields import ArrayField
```

Add the `Reviewable` import to the existing base import line so it reads:

```python
from .base import Reviewable, TimeStamped
```

Append:

```python
class Organization(Reviewable):
    """Any organization: meeting body, school, vendor, nonprofit, campaign.
    Bodies are agency-scoped (jurisdiction set); vendors are cross-agency
    (jurisdiction null) so the same vendor unifies across agencies (§14.4)."""

    class Kind(models.TextChoices):
        DISTRICT = "district", "District"
        SCHOOL = "school", "School"
        COMPANY = "company", "Company (vendor)"
        NONPROFIT = "nonprofit", "Nonprofit"
        COMMITTEE = "committee", "Committee"
        CAMPAIGN = "campaign", "Campaign"
        OTHER = "other", "Other"

    name = models.CharField(max_length=255)
    aka = ArrayField(models.CharField(max_length=255), default=list, blank=True)
    slug = models.SlugField(max_length=255)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    jurisdiction = models.ForeignKey(
        Jurisdiction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="organizations",
    )
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["jurisdiction", "slug"],
                name="uniq_org_slug_per_jurisdiction",
            ),
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(jurisdiction__isnull=True),
                name="uniq_global_org_slug",
            ),
        ]

    def __str__(self):
        return self.name


class Person(Reviewable):
    """A canonical individual after dedup (brief §7)."""

    full_name = models.CharField(max_length=255)
    aka = ArrayField(models.CharField(max_length=255), default=list, blank=True)
    slug = models.SlugField(max_length=255, unique=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.full_name
```

Update `catalog/models/__init__.py`:

```python
from .base import Reviewable, TimeStamped
from .org import Jurisdiction, Organization, Person, Source

__all__ = [
    "Jurisdiction",
    "Organization",
    "Person",
    "Reviewable",
    "Source",
    "TimeStamped",
]
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations catalog --name organization_person`
Expected: creates `catalog/migrations/0002_organization_person.py`.

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_org.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/
git commit -m "feat: add Organization and Person with slug namespacing"
```

---

### Task 7: Meeting + AgendaItem (type-slug → kind mapping)

**Files:**
- Create: `catalog/models/meeting.py`
- Modify: `catalog/models/__init__.py`
- Create: `catalog/tests/test_meeting.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_meeting.py`:

```python
import datetime

import pytest

from catalog.models import AgendaItem, Jurisdiction, Meeting, Organization


def test_kind_from_slug_maps_known_and_defaults_unknown():
    assert Meeting.kind_from_slug("committee-meeting") == Meeting.Kind.COMMITTEE
    assert Meeting.kind_from_slug("board-meeting") == Meeting.Kind.BOARD
    assert Meeting.kind_from_slug("called-board-meeting") == Meeting.Kind.CALLED_BOARD
    assert Meeting.kind_from_slug("totally-unknown-slug") == Meeting.Kind.OTHER


@pytest.mark.django_db
def test_meeting_with_agenda_item():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(
        name="Board of Education", slug="boe", kind=Organization.Kind.COMMITTEE, jurisdiction=jur
    )
    meeting = Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        date=datetime.date(2025, 4, 17),
        start_time=datetime.time(16, 0),
        kind=Meeting.kind_from_slug("committee-meeting"),
        raw_type_slug="committee-meeting",
        source_meeting_id="124789",
        slug="2025-04-17-committee-mid-124789",
    )
    item = AgendaItem.objects.create(
        meeting=meeting,
        order=1,
        code="FSS-3",
        title="Award of contract",
        item_type=AgendaItem.ItemType.ACTION,
        outcome_status=AgendaItem.OutcomeStatus.UNANIMOUS,
    )
    assert meeting.kind == Meeting.Kind.COMMITTEE
    assert item.meeting == meeting
    assert str(item) == "FSS-3 Award of contract"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_meeting.py -v`
Expected: FAIL — `ImportError: cannot import name 'Meeting'`.

- [ ] **Step 3: Implement Meeting + AgendaItem**

Create `catalog/models/meeting.py`:

```python
from django.db import models

from .base import TimeStamped
from .org import Jurisdiction, Organization, Source

# Maps the archive's folder type-slug to a Meeting.Kind (brief §4.1).
SLUG_TO_KIND = {
    "committee-meeting": "committee",
    "board-meeting": "board",
    "board-agenda": "board_agenda",
    "called-board-meeting": "called_board",
    "called-board-meeting-policy-review": "called_board",
}


class Meeting(TimeStamped):
    """The ingestion anchor: one meeting record (brief §7)."""

    class Kind(models.TextChoices):
        COMMITTEE = "committee", "Committee Meeting"
        BOARD = "board", "Board Meeting"
        BOARD_AGENDA = "board_agenda", "Board Agenda"
        CALLED_BOARD = "called_board", "Called Board Meeting"
        OTHER = "other", "Other"

    body = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="meetings")
    jurisdiction = models.ForeignKey(
        Jurisdiction, null=True, blank=True, on_delete=models.SET_NULL, related_name="meetings"
    )
    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="meetings"
    )
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    raw_type_slug = models.CharField(max_length=128, blank=True)
    title = models.CharField(max_length=512, blank=True)
    source_meeting_id = models.CharField(max_length=64, blank=True)
    source_url = models.URLField(max_length=1024, blank=True)
    source_path = models.CharField(max_length=1024, blank=True)
    slug = models.SlugField(max_length=255)

    class Meta:
        ordering = ["-date", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_meeting_id"],
                name="uniq_meeting_per_source_id",
            )
        ]

    @classmethod
    def kind_from_slug(cls, slug):
        """Map a raw folder type-slug to a Kind; unknown slugs → OTHER (§4.1)."""
        return cls.SLUG_TO_KIND.get(slug, cls.Kind.OTHER)

    def __str__(self):
        return f"{self.date} {self.get_kind_display()}"


# Expose the map as a class attribute referenced by kind_from_slug.
Meeting.SLUG_TO_KIND = SLUG_TO_KIND


class AgendaItem(TimeStamped):
    """One numbered item within a meeting's agenda (brief §7)."""

    class ItemType(models.TextChoices):
        ACTION = "action", "Action"
        PRESENTATION = "presentation", "Presentation"
        INFORMATION = "information", "Information"
        OTHER = "other", "Other"

    class ReadingStage(models.TextChoices):
        FIRST = "first", "First Reading"
        SECOND = "second", "Second Reading"

    class OutcomeStatus(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        TABLED = "tabled", "Tabled"
        POSTPONED = "postponed", "Postponed"
        UNANIMOUS = "unanimous", "Unanimously Approved"
        NONE = "none", "No Outcome"

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="agenda_items")
    order = models.PositiveIntegerField(default=0)
    code = models.CharField(max_length=32, blank=True)
    title = models.CharField(max_length=512)
    item_type = models.CharField(max_length=32, choices=ItemType.choices, default=ItemType.OTHER)
    reading_stage = models.CharField(max_length=16, choices=ReadingStage.choices, blank=True)
    outcome_text = models.TextField(blank=True)
    outcome_status = models.CharField(
        max_length=16, choices=OutcomeStatus.choices, default=OutcomeStatus.NONE
    )

    class Meta:
        ordering = ["meeting", "order"]

    def __str__(self):
        return f"{self.code} {self.title}".strip()
```

Update `catalog/models/__init__.py`:

```python
from .base import Reviewable, TimeStamped
from .meeting import AgendaItem, Meeting
from .org import Jurisdiction, Organization, Person, Source

__all__ = [
    "AgendaItem",
    "Jurisdiction",
    "Meeting",
    "Organization",
    "Person",
    "Reviewable",
    "Source",
    "TimeStamped",
]
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations catalog --name meeting_agendaitem`
Expected: creates `catalog/migrations/0003_meeting_agendaitem.py`.

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_meeting.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/
git commit -m "feat: add Meeting and AgendaItem with type-slug kind mapping"
```

---

### Task 8: MediaAsset + Transcript + TranscriptSegment + MeetingCoverage

**Files:**
- Create: `catalog/models/media.py`
- Modify: `catalog/models/__init__.py`
- Create: `catalog/tests/test_media.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_media.py`:

```python
import datetime

import pytest

from catalog.models import (
    Jurisdiction,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Organization,
    Transcript,
    TranscriptSegment,
)


@pytest.mark.django_db
def test_recording_with_segments_and_two_coverages():
    """A combined committee+board recording has two MeetingCoverage windows (§6.3)."""
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    committee = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.COMMITTEE, slug="c1"
    )
    board = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b1"
    )
    media = MediaAsset.objects.create(
        kind=MediaAsset.Kind.VIDEO, youtube_id="abc123XYZ_0", duration_seconds=13486
    )
    transcript = Transcript.objects.create(
        media=media, origin=Transcript.Origin.YOUTUBE_CAPTIONS
    )
    seg = TranscriptSegment.objects.create(
        transcript=transcript, start=12.5, end=15.0, text="call the meeting to order"
    )
    MeetingCoverage.objects.create(media=media, meeting=committee, start_offset=0, end_offset=7000)
    MeetingCoverage.objects.create(
        media=media, meeting=board, start_offset=7000, end_offset=None
    )

    assert media.coverages.count() == 2
    # The segment start is the absolute YouTube ?t= offset.
    assert seg.start == 12.5
    assert transcript.segments.count() == 1


@pytest.mark.django_db
def test_coverage_unique_per_media_meeting():
    from django.db import IntegrityError

    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b2"
    )
    media = MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO, youtube_id="zzz")
    MeetingCoverage.objects.create(media=media, meeting=meeting)
    with pytest.raises(IntegrityError):
        MeetingCoverage.objects.create(media=media, meeting=meeting)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_media.py -v`
Expected: FAIL — `ImportError: cannot import name 'MediaAsset'`.

- [ ] **Step 3: Implement the media models**

Create `catalog/models/media.py`:

```python
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from .base import TimeStamped
from .meeting import Meeting
from .org import Source


class MediaAsset(TimeStamped):
    """One recording or media file (brief §7). One per recording/file."""

    class Kind(models.TextChoices):
        VIDEO = "video", "Video"
        AUDIO = "audio", "Audio"
        PDF = "pdf", "PDF"
        IMAGE = "image", "Image"

    class AccessLevel(models.TextChoices):
        PUBLIC = "public", "Public"
        RESTRICTED = "restricted", "Restricted"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    r2_key = models.CharField(max_length=1024, blank=True)
    youtube_id = models.CharField(max_length=16, blank=True)
    source_url = models.URLField(max_length=1024, blank=True)
    recorded_on = models.DateField(null=True, blank=True)  # from title date (§6.2)
    upload_date = models.DateField(null=True, blank=True)  # from info.json (§5.5)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    access_level = models.CharField(
        max_length=16, choices=AccessLevel.choices, default=AccessLevel.PUBLIC
    )
    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="media_assets"
    )

    def __str__(self):
        return f"{self.get_kind_display()} {self.youtube_id or self.r2_key}"


class Transcript(TimeStamped):
    """A transcript belongs to a MediaAsset (not a Meeting): it can span two
    meetings (brief §7)."""

    class Origin(models.TextChoices):
        YOUTUBE_CAPTIONS = "youtube_captions", "YouTube Captions"
        WHISPER = "whisper", "faster-whisper"

    media = models.ForeignKey(MediaAsset, on_delete=models.CASCADE, related_name="transcripts")
    language = models.CharField(max_length=16, default="en")
    origin = models.CharField(max_length=32, choices=Origin.choices)
    model = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return f"Transcript(media={self.media_id}, {self.origin})"


class TranscriptSegment(models.Model):
    """A timed line of transcript. `start` is the absolute offset in the recording
    = the YouTube ?t= value, powering transcript→video deep links (brief §7, F14)."""

    transcript = models.ForeignKey(
        Transcript, on_delete=models.CASCADE, related_name="segments"
    )
    start = models.FloatField()
    end = models.FloatField()
    text = models.TextField()
    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        ordering = ["transcript", "start"]
        indexes = [GinIndex(fields=["search_vector"], name="gin_segment_search")]

    def __str__(self):
        return f"[{self.start:.1f}-{self.end:.1f}] {self.text[:40]}"


class MeetingCoverage(TimeStamped):
    """Maps a Meeting to the slice of a MediaAsset that covers it (brief §7).
    A combined committee+board recording has two of these."""

    media = models.ForeignKey(MediaAsset, on_delete=models.CASCADE, related_name="coverages")
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="coverages")
    start_offset = models.FloatField(default=0)
    end_offset = models.FloatField(null=True, blank=True)  # null = to end of recording
    split_confirmed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["media", "meeting"], name="uniq_coverage_media_meeting"
            )
        ]

    def __str__(self):
        return f"coverage(media={self.media_id}, meeting={self.meeting_id})"
```

Update `catalog/models/__init__.py`:

```python
from .base import Reviewable, TimeStamped
from .media import MediaAsset, MeetingCoverage, Transcript, TranscriptSegment
from .meeting import AgendaItem, Meeting
from .org import Jurisdiction, Organization, Person, Source

__all__ = [
    "AgendaItem",
    "Jurisdiction",
    "MediaAsset",
    "Meeting",
    "MeetingCoverage",
    "Organization",
    "Person",
    "Reviewable",
    "Source",
    "TimeStamped",
    "Transcript",
    "TranscriptSegment",
]
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations catalog --name media_models`
Expected: creates `catalog/migrations/0004_media_models.py`.

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_media.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/
git commit -m "feat: add MediaAsset, Transcript, TranscriptSegment, MeetingCoverage"
```

---

### Task 9: Document model (with FTS search vector)

**Files:**
- Create: `catalog/models/document.py`
- Modify: `catalog/models/__init__.py`
- Create: `catalog/tests/test_document.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_document.py`:

```python
import datetime

import pytest

from catalog.models import (
    AgendaItem,
    Document,
    Jurisdiction,
    Meeting,
    Organization,
)


@pytest.mark.django_db
def test_document_links_meeting_and_agenda_item():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.COMMITTEE, slug="c"
    )
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="Contract award")
    doc = Document.objects.create(
        title="WM2A Architects proposal",
        kind=Document.Kind.PRESENTATION,
        meeting=meeting,
        agenda_item=item,
        text="full extracted text here",
        ocr_status=Document.OCRStatus.HAS_TEXT,
    )
    assert doc.meeting == meeting
    assert doc.agenda_item == item
    assert doc.access_level == Document.AccessLevel.PUBLIC  # default
    assert doc.og_metadata == {}  # JSON default


@pytest.mark.django_db
def test_standalone_document_has_no_meeting():
    doc = Document.objects.create(
        title="ACFR FY2024", kind=Document.Kind.REPORT, text="balance sheet"
    )
    assert doc.meeting is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_document.py -v`
Expected: FAIL — `ImportError: cannot import name 'Document'`.

- [ ] **Step 3: Implement Document**

Create `catalog/models/document.py`:

```python
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from .base import TimeStamped
from .media import MediaAsset
from .meeting import AgendaItem, Meeting
from .org import Source


class Document(TimeStamped):
    """A document with extracted text for full-text search (brief §7).
    May link to a Meeting and/or AgendaItem, or stand alone (policies, reports)."""

    class Kind(models.TextChoices):
        MINUTES = "minutes", "Minutes"
        AGENDA = "agenda", "Agenda"
        POLICY = "policy", "Policy"
        CONTRACT = "contract", "Contract"
        MEMO = "memo", "Memo"
        PRESENTATION = "presentation", "Presentation"
        REPORT = "report", "Report"
        ARTICLE = "article", "Article"
        OTHER = "other", "Other"

    class OCRStatus(models.TextChoices):
        HAS_TEXT = "has_text", "Has Text Layer"
        OCR_NEEDED = "ocr_needed", "OCR Needed"
        EMPTY = "empty", "Empty"
        UNKNOWN = "unknown", "Unknown"

    class AccessLevel(models.TextChoices):
        PUBLIC = "public", "Public"
        RESTRICTED = "restricted", "Restricted"

    title = models.CharField(max_length=512)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    meeting = models.ForeignKey(
        Meeting, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    agenda_item = models.ForeignKey(
        AgendaItem, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    media = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    r2_key = models.CharField(max_length=1024, blank=True)
    source_url = models.URLField(max_length=1024, blank=True)
    og_metadata = models.JSONField(default=dict, blank=True)
    text = models.TextField(blank=True)
    ocr_status = models.CharField(
        max_length=16, choices=OCRStatus.choices, default=OCRStatus.UNKNOWN
    )
    access_level = models.CharField(
        max_length=16, choices=AccessLevel.choices, default=AccessLevel.PUBLIC
    )
    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        indexes = [GinIndex(fields=["search_vector"], name="gin_document_search")]

    def __str__(self):
        return self.title
```

Update `catalog/models/__init__.py` (add the `Document` import after the `base` import and add `"Document"` to `__all__` in alphabetical position):

```python
from .base import Reviewable, TimeStamped
from .document import Document
from .media import MediaAsset, MeetingCoverage, Transcript, TranscriptSegment
from .meeting import AgendaItem, Meeting
from .org import Jurisdiction, Organization, Person, Source

__all__ = [
    "AgendaItem",
    "Document",
    "Jurisdiction",
    "MediaAsset",
    "Meeting",
    "MeetingCoverage",
    "Organization",
    "Person",
    "Reviewable",
    "Source",
    "TimeStamped",
    "Transcript",
    "TranscriptSegment",
]
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations catalog --name document`
Expected: creates `catalog/migrations/0005_document.py`.

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_document.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/
git commit -m "feat: add Document model with FTS search vector"
```

---

### Task 10: Vote + Appearance (reviewable facts)

**Files:**
- Create: `catalog/models/facts.py`
- Modify: `catalog/models/__init__.py`
- Create: `catalog/tests/test_facts.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_facts.py`:

```python
import datetime

import pytest
from django.db import IntegrityError

from catalog.models import (
    AgendaItem,
    Appearance,
    Jurisdiction,
    Meeting,
    Organization,
    Person,
    Vote,
)


@pytest.fixture
def meeting(db):
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    return Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b"
    )


@pytest.mark.django_db
def test_vote_is_unreviewed_proposal_by_default(meeting):
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="Budget")
    person = Person.objects.create(full_name="Myrtice Johnson", slug="myrtice-johnson")
    vote = Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA)
    assert vote.reviewed is False
    assert vote.value == "yea"


@pytest.mark.django_db
def test_vote_unique_per_person_item(meeting):
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="Budget")
    person = Person.objects.create(full_name="P", slug="p")
    Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA)
    with pytest.raises(IntegrityError):
        Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.NAY)


@pytest.mark.django_db
def test_appearance_roles(meeting):
    person = Person.objects.create(full_name="Roy Miller", slug="roy-miller")
    appearance = Appearance.objects.create(
        person=person, meeting=meeting, role=Appearance.Role.SPEAKER
    )
    assert appearance.role == "speaker"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_facts.py -v`
Expected: FAIL — `ImportError: cannot import name 'Vote'`.

- [ ] **Step 3: Implement Vote + Appearance**

Create `catalog/models/facts.py`:

```python
from django.db import models

from .base import Reviewable
from .meeting import AgendaItem, Meeting
from .org import Person


class Vote(Reviewable):
    """A per-member vote on an agenda item (brief §7). Only materialized where an
    explicit roll call exists; unanimous outcomes live on AgendaItem (§9 #13)."""

    class Value(models.TextChoices):
        YEA = "yea", "Yea"
        NAY = "nay", "Nay"
        ABSTAIN = "abstain", "Abstain"
        ABSENT = "absent", "Absent"

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="votes")
    agenda_item = models.ForeignKey(AgendaItem, on_delete=models.CASCADE, related_name="votes")
    value = models.CharField(max_length=16, choices=Value.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["person", "agenda_item"], name="uniq_vote_person_item"
            )
        ]

    def __str__(self):
        return f"{self.person} {self.value} on {self.agenda_item}"


class Appearance(Reviewable):
    """A person's appearance at a meeting in some role (brief §7)."""

    class Role(models.TextChoices):
        MEMBER = "member", "Member"
        SPEAKER = "speaker", "Speaker"
        PRESENTER = "presenter", "Presenter"
        STAFF = "staff", "Staff"
        INVOCATION = "invocation", "Invocation"
        PLEDGE = "pledge", "Pledge of Allegiance"

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="appearances")
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="appearances")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)

    def __str__(self):
        return f"{self.person} as {self.role} at {self.meeting}"
```

Update `catalog/models/__init__.py` (add the `facts` import and the two names to `__all__`):

```python
from .base import Reviewable, TimeStamped
from .document import Document
from .facts import Appearance, Vote
from .media import MediaAsset, MeetingCoverage, Transcript, TranscriptSegment
from .meeting import AgendaItem, Meeting
from .org import Jurisdiction, Organization, Person, Source

__all__ = [
    "AgendaItem",
    "Appearance",
    "Document",
    "Jurisdiction",
    "MediaAsset",
    "Meeting",
    "MeetingCoverage",
    "Organization",
    "Person",
    "Reviewable",
    "Source",
    "TimeStamped",
    "Transcript",
    "TranscriptSegment",
    "Vote",
]
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations catalog --name vote_appearance`
Expected: creates `catalog/migrations/0006_vote_appearance.py`.

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_facts.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/
git commit -m "feat: add Vote and Appearance reviewable facts"
```

---

### Task 11: Citation — the generic provenance backbone

**Files:**
- Create: `catalog/models/citation.py`
- Modify: `catalog/models/__init__.py`
- Create: `catalog/tests/test_citation.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_citation.py`:

```python
import datetime

import pytest
from django.db import IntegrityError

from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    Meeting,
    Organization,
    Person,
    Vote,
)


@pytest.fixture
def fixtures(db):
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b"
    )
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="Budget")
    person = Person.objects.create(full_name="Myrtice Johnson", slug="mj")
    minutes = Document.objects.create(
        title="minutes.md", kind=Document.Kind.MINUTES, meeting=meeting
    )
    return meeting, item, person, minutes


@pytest.mark.django_db
def test_citation_attaches_a_fact_to_a_document(fixtures):
    _meeting, item, person, minutes = fixtures
    vote = Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA)
    cite = Citation.objects.create(
        fact=vote, document=minutes, page=3, quote="Voting results: Unanimously approved"
    )
    assert cite.fact == vote
    # for_fact() retrieves every citation backing a given fact.
    assert list(Citation.objects.for_fact(vote)) == [cite]


@pytest.mark.django_db
def test_citation_works_across_fact_types(fixtures):
    meeting, _item, person, minutes = fixtures
    appearance = Appearance.objects.create(
        person=person, meeting=meeting, role=Appearance.Role.MEMBER
    )
    Citation.objects.create(fact=appearance, document=minutes)
    assert Citation.objects.for_fact(appearance).count() == 1


@pytest.mark.django_db
def test_citation_requires_some_evidence(fixtures):
    """A citation with neither a document nor a transcript segment is rejected."""
    meeting, item, person, _minutes = fixtures
    vote = Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA)
    with pytest.raises(IntegrityError):
        Citation.objects.create(fact=vote, document=None, transcript_segment=None)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_citation.py -v`
Expected: FAIL — `ImportError: cannot import name 'Citation'`.

- [ ] **Step 3: Implement Citation + CitationManager**

Create `catalog/models/citation.py`:

```python
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .base import TimeStamped
from .document import Document
from .media import TranscriptSegment


class CitationManager(models.Manager):
    def for_fact(self, fact):
        """Return every Citation backing a given fact instance."""
        ct = ContentType.objects.get_for_model(fact)
        return self.filter(content_type=ct, object_id=fact.pk)


class Citation(TimeStamped):
    """Provenance backbone (brief §7): attaches ANY fact (Vote, Appearance, …) to
    the evidence for it — a Document (optionally a page) and/or a TranscriptSegment,
    with an optional quote. Every materialized fact should have >=1 Citation."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    fact = GenericForeignKey("content_type", "object_id")

    # on_delete asymmetry is intentional: a citation is document-anchored, so it
    # dies with its document (CASCADE). The transcript_segment is an optional pin,
    # so SET_NULL preserves a citation that still has document evidence. A segment
    # that is the SOLE evidence cannot be deleted — the citation_has_evidence CHECK
    # blocks it (safe failure), which is correct.
    document = models.ForeignKey(
        Document, null=True, blank=True, on_delete=models.CASCADE, related_name="citations"
    )
    page = models.PositiveIntegerField(null=True, blank=True)
    transcript_segment = models.ForeignKey(
        TranscriptSegment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="citations",
    )
    quote = models.TextField(blank=True)

    objects = CitationManager()

    class Meta:
        indexes = [models.Index(fields=["content_type", "object_id"], name="idx_citation_fact")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(document__isnull=False)
                | models.Q(transcript_segment__isnull=False),
                name="citation_has_evidence",
            )
        ]

    def __str__(self):
        evidence = self.document or self.transcript_segment
        return f"Citation({self.content_type} #{self.object_id} → {evidence})"
```

> **Note:** Django 6 uses `condition=` for `CheckConstraint` (the old `check=` keyword was removed). The `Q` import comes via `models.Q`.

Update `catalog/models/__init__.py` (add the `citation` import — it must come after `document` and `media` since it imports from them — and add `"Citation"` to `__all__`):

```python
from .base import Reviewable, TimeStamped
from .document import Document
from .facts import Appearance, Vote
from .media import MediaAsset, MeetingCoverage, Transcript, TranscriptSegment
from .meeting import AgendaItem, Meeting
from .org import Jurisdiction, Organization, Person, Source
from .citation import Citation  # noqa: E402  (imports from document/media above)

__all__ = [
    "AgendaItem",
    "Appearance",
    "Citation",
    "Document",
    "Jurisdiction",
    "MediaAsset",
    "Meeting",
    "MeetingCoverage",
    "Organization",
    "Person",
    "Reviewable",
    "Source",
    "TimeStamped",
    "Transcript",
    "TranscriptSegment",
    "Vote",
]
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations catalog --name citation`
Expected: creates `catalog/migrations/0007_citation.py`.

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_citation.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/
git commit -m "feat: add Citation generic provenance backbone"
```

---

### Task 12: Register every model in the Django admin

**Files:**
- Modify: `catalog/admin.py`
- Create: `catalog/tests/test_admin.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_admin.py`:

```python
from django.contrib import admin

from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Organization,
    Person,
    Source,
    Transcript,
    TranscriptSegment,
    Vote,
)

EXPECTED = [
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Organization,
    Person,
    Source,
    Transcript,
    TranscriptSegment,
    Vote,
]


def test_all_catalog_models_are_registered():
    for model in EXPECTED:
        assert admin.site.is_registered(model), f"{model.__name__} not registered in admin"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_admin.py -v`
Expected: FAIL — `AssertionError: AgendaItem not registered in admin`.

- [ ] **Step 3: Implement admin registration**

Replace the contents of `catalog/admin.py` with:

```python
from django.contrib import admin

from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Organization,
    Person,
    Source,
    Transcript,
    TranscriptSegment,
    Vote,
)


@admin.register(Jurisdiction)
class JurisdictionAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "jurisdiction", "adapter")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "jurisdiction", "reviewed")
    list_filter = ("kind", "reviewed", "jurisdiction")
    search_fields = ("name", "slug")


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("full_name", "slug", "reviewed")
    list_filter = ("reviewed",)
    search_fields = ("full_name", "slug")


class AgendaItemInline(admin.TabularInline):
    model = AgendaItem
    extra = 0


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ("date", "kind", "body", "title")
    list_filter = ("kind", "jurisdiction")
    date_hierarchy = "date"
    inlines = [AgendaItemInline]


@admin.register(AgendaItem)
class AgendaItemAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "meeting", "item_type", "outcome_status")
    list_filter = ("item_type", "outcome_status")


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ("kind", "youtube_id", "recorded_on", "duration_seconds")
    list_filter = ("kind", "access_level")


@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ("media", "origin", "language", "model")
    list_filter = ("origin", "language")


@admin.register(TranscriptSegment)
class TranscriptSegmentAdmin(admin.ModelAdmin):
    list_display = ("transcript", "start", "end")


@admin.register(MeetingCoverage)
class MeetingCoverageAdmin(admin.ModelAdmin):
    list_display = ("media", "meeting", "start_offset", "end_offset", "split_confirmed")
    list_filter = ("split_confirmed",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "meeting", "ocr_status")
    list_filter = ("kind", "ocr_status", "access_level")
    search_fields = ("title",)


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("person", "agenda_item", "value", "reviewed")
    list_filter = ("value", "reviewed")


@admin.register(Appearance)
class AppearanceAdmin(admin.ModelAdmin):
    list_display = ("person", "meeting", "role", "reviewed")
    list_filter = ("role", "reviewed")


@admin.register(Citation)
class CitationAdmin(admin.ModelAdmin):
    list_display = ("content_type", "object_id", "document", "page")
    list_filter = ("content_type",)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_admin.py -v`
Expected: 1 passed.

- [ ] **Step 5: Verify the full system check is clean**

Run: `uv run python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/
git commit -m "feat: register catalog models in Django admin"
```

---

### Task 13: End-to-end provenance smoke test

Proves the foundation delivers what it promises: a meeting with an agenda item, a per-member vote, evidenced by a citation into the minutes — the full provenance chain.

**Files:**
- Create: `catalog/tests/test_provenance_smoke.py`

- [ ] **Step 1: Write the test**

Create `catalog/tests/test_provenance_smoke.py`:

```python
import datetime

import pytest

from catalog.models import (
    AgendaItem,
    Citation,
    Document,
    Jurisdiction,
    Meeting,
    Organization,
    Person,
    Source,
    Vote,
)


@pytest.mark.django_db
def test_full_provenance_chain():
    jur = Jurisdiction.objects.create(
        name="Bibb County Board of Education",
        slug="bibb-county-boe",
        kind=Jurisdiction.Kind.SCHOOL_DISTRICT,
    )
    src = Source.objects.create(name="BCSD BOE Meetings", slug="bcsd-boe-meetings", adapter="bcsd")
    body = Organization.objects.create(
        name="Board of Education", slug="boe", kind=Organization.Kind.COMMITTEE, jurisdiction=jur
    )
    meeting = Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        source=src,
        date=datetime.date(2025, 4, 17),
        start_time=datetime.time(18, 30),
        kind=Meeting.kind_from_slug("board-meeting"),
        raw_type_slug="board-meeting",
        source_meeting_id="124791",
        slug="2025-04-17-board-mid-124791",
    )
    item = AgendaItem.objects.create(
        meeting=meeting,
        order=1,
        code="FI-1",
        title="Adopt FY2026 budget",
        item_type=AgendaItem.ItemType.ACTION,
        outcome_status=AgendaItem.OutcomeStatus.PASSED,
    )
    minutes = Document.objects.create(
        title="minutes.md",
        kind=Document.Kind.MINUTES,
        meeting=meeting,
        source=src,
        ocr_status=Document.OCRStatus.HAS_TEXT,
    )
    person = Person.objects.create(full_name="Myrtice Johnson", slug="myrtice-johnson")
    vote = Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA)
    Citation.objects.create(
        fact=vote, document=minutes, page=4, quote="Yes: Ms. Myrtice Johnson"
    )

    # The vote is reachable from the meeting, and is backed by a citation.
    assert meeting.kind == Meeting.Kind.BOARD
    assert person.votes.get().agenda_item.meeting == meeting
    citations = Citation.objects.for_fact(vote)
    assert citations.count() == 1
    assert citations.first().document.meeting == meeting
    # Ingested facts start unreviewed (hidden from public until admin confirms).
    assert vote.reviewed is False
```

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass (storage, smoke, base, org, meeting, media, document, facts, citation, admin, provenance smoke).

- [ ] **Step 3: Confirm migrations are complete and the DB is consistent**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected` (every model change is captured in a migration).

- [ ] **Step 4: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/tests/test_provenance_smoke.py
git commit -m "test: end-to-end provenance chain smoke test"
```

---

## Carry into slice 1b (from final holistic review)

These are NOT part of this foundation plan — they are "cheap now, painful after data exists" items to apply at the **start of slice 1b (the BCSD parser), before any bulk load**:

1. **Partial unique constraints on object-storage keys:** `UniqueConstraint(fields=["r2_key"], condition=~Q(r2_key=""))` on both `Document` and `MediaAsset` — object-storage keys are logically unique per asset; dedup after a bulk load is annoying.
2. **A uniqueness story for `Meeting.slug`** before the public-URL slice (1e): mirror the `Organization` partial-unique pattern (e.g. `(jurisdiction, slug)`), since `slug` will be the public URL key. Idempotency is already handled by `(source, source_meeting_id)`; this is about URL stability.
3. **Bound `confidence` to its contract** (0.0–1.0) with a `CheckConstraint`, so ingester self-scoring can't silently write out-of-range values.
4. **Tidy `Meeting.SLUG_TO_KIND`** while editing `meeting.py` for the parser: define the map once inside the class body (drop the module global + the post-class `Meeting.SLUG_TO_KIND = …` reassignment). Purely cosmetic; the current form is correct.
5. **Parser contract:** write everything `reviewed=False` and emit a `Citation` (pointing at the `minutes.md` Document, with page where available) for every `Vote`/`Appearance` materialized — the shape encoded by `test_provenance_smoke.py`.

## Deferred to later phases (NOT in this plan)

Per the approved design spec, these §7 entities are added when the archive broadens, not now: **Office**, **OfficeTenure**, **Affiliation**, **Award/Bid**, **Relationship**, **Submission**, **RecordsRequest**. The BCSD `minutes.md`/`event.md` parser (Phase 1b), document/OCR/FTS ingestion (1c), recording matcher + VTT importer (1d), and the public read UI (1e) each get their own plan, authored once this schema is real.

## Self-Review

- **Spec coverage:** Phase 0 (R2 wiring ✓ Task 2, pytest ✓ Task 1, CI ✓ Task 3). Phase 1a schema: every slice-relevant §7 entity has a task (Jurisdiction/Source ✓ T5, Organization/Person ✓ T6, Meeting/AgendaItem ✓ T7, Media cluster ✓ T8, Document ✓ T9, Vote/Appearance ✓ T10, Citation ✓ T11), admin ✓ T12, §14.5 additions (Jurisdiction, Source, slug namespacing) ✓ T5/T6, provenance invariant (Reviewable defaults + Citation) ✓ T4/T11/T13.
- **Placeholder scan:** no TBD/TODO; every code step shows complete code; every command shows expected output.
- **Type consistency:** `Citation.objects.for_fact()` defined in T11 and used in T11/T13; `Meeting.kind_from_slug()` defined in T7 and used in T7/T8/T13; `Reviewable.reviewed` default `False` asserted consistently (T4/T10/T11/T13); model names in `__all__` match across tasks.
