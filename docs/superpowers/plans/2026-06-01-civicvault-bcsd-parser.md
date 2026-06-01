# CivicVault Slice 1b — BCSD Source-A Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive the verified 04/17/2025 Bibb County committee + board meeting pair end-to-end — parse the folder name, `event.md`, `minutes.md` (all four motion-block variants, roster, per-person roll call, appearances) with an `agenda.md` fallback — into the `catalog` schema as `reviewed=False` proposals, each materialized `Vote`/`Appearance`/`Motion` backed by a `Citation` into the `minutes.md` Document.

**Architecture:** A clean **parse → IR → load** seam (brief §14.7). BCSD-specific parsers live under `catalog/ingest/bcsd/` and emit framework-neutral frozen dataclasses (the **intermediate representation**, `catalog/ingest/ir.py`) with zero Django imports — so they are pure and fixture-testable. A single agency-agnostic loader (`catalog/ingest/loader.py`) materializes that IR into Django rows idempotently and writes Citations. A management command (`ingest_bcsd`) wires a folder path → adapter → loader. Agency #2 is a new `catalog/ingest/<agency>/` package emitting the same IR; the loader is untouched.

**Tech Stack:** Python 3.12 (`dataclasses`, `re`, `pathlib`), Django 6 ORM, PostgreSQL, pytest + pytest-django, ruff. No new third-party dependencies.

---

## Prerequisites

The local Postgres dev container must be running for DB-backed (loader/command) tests:

```bash
docker compose up -d db   # host port 5433; DATABASE_URL in .env points here
```

All Python commands run through `uv` (never system Python). Lint with `ruff` before every commit. Do **not** add `--reuse-db` (this slice adds migrations; the test DB must rebuild each run). Baseline before starting: `uv run pytest -q` → **23 passed**, on branch `feat/bcsd-parser`.

---

## Scope (decisions locked for this slice)

**In scope:** folder-name + `event.md` + `minutes.md` + `agenda.md`-fallback parsing; the new `Motion` model; carry-forward schema hardening; the generic loader; the `ingest_bcsd` command; idempotent end-to-end load of the 04/17/2025 pair.

**Materialized this slice:** `Jurisdiction`, `Source`, the body `Organization`, `Meeting`, `AgendaItem`, `Person` (roster + movers/seconders + invocation/pledge/visitors), `Appearance`, `Vote` (roll-call only), `Motion`, the source `Document`s (`minutes.md`/`event.md`/`agenda.md`), and a `Citation` for every `Vote`/`Appearance`/`Motion`.

**Deliberately deferred (state, don't build):**
- **File-attachment `Document` rows + text/OCR/FTS → slice 1c.** This slice captures the `event.md` `## Files` filename→agenda-item map into the IR but does **not** materialize the ~60 per-meeting file documents; 1c re-reads the stable `event.md` map. The only `Document`s created now are the source `.md` documents so Citations have an evidence target.
- **Vendor `Organization` extraction → later slice.** §5.2 flags vendor NER ("WM2A Architects", "CDW", …) as noisy + admin-review territory. This slice resolves the meeting **body** Organization and all **Persons** only.
- **Recordings / `MediaAsset` / coverage / transcript → slice 1d.**
- **Cross-meeting Person dedup → Splink (Phase 3).** This slice dedups Persons **within the load** by normalized-name slug (a roster name reused across the committee and board meetings resolves to one `Person` — correct), and accepts that two distinct same-name people would collide (resolved later by Splink + admin).

**Idempotency model (locked):** the loader keys `Meeting` on `(source, source_meeting_id)`. On re-ingest of a meeting it **deletes that meeting's existing meeting-scoped facts** (`AgendaItem` → cascades `Motion`/`Vote`; `Appearance`; source `Document` → cascades `Citation`) and recreates them. `Jurisdiction`/`Source`/`Organization`/`Person` are `get_or_create` (shared, never wiped). This is correct while everything is `reviewed=False`; revisiting re-ingest once admin review begins is out of scope (note it in code).

---

## File Structure

**Schema (new + modified):**
- Modify `catalog/models/facts.py` — add the `Motion` model (Reviewable fact).
- Modify `catalog/models/meeting.py` — tidy `SLUG_TO_KIND` into the class body; add `Meeting.slug` uniqueness + `AgendaItem (meeting, order)` uniqueness.
- Modify `catalog/models/org.py` — add `confidence` `CheckConstraint` to `Organization` + `Person`.
- Modify `catalog/models/document.py` — add `Document.r2_key` partial-unique.
- Modify `catalog/models/media.py` — add `MediaAsset.r2_key` partial-unique.
- Modify `catalog/models/__init__.py` — export `Motion`.
- Modify `catalog/admin.py` — register `Motion`.
- Create `catalog/migrations/0008_motion.py`, `catalog/migrations/0009_schema_hardening.py` (via `makemigrations`).

**Adapter framework (new):**
- Create `catalog/ingest/__init__.py`.
- Create `catalog/ingest/ir.py` — frozen IR dataclasses (the adapter contract; no Django imports).
- Create `catalog/ingest/names.py` — `normalize_name()` (pure).
- Create `catalog/ingest/loader.py` — `load_meeting(parsed, *, source, jurisdiction, body)` (generic; the only DB-touching module).

**BCSD adapter (new):**
- Create `catalog/ingest/bcsd/__init__.py`.
- Create `catalog/ingest/bcsd/foldername.py` — `parse_folder_name()`.
- Create `catalog/ingest/bcsd/event_md.py` — `parse_event_md()`.
- Create `catalog/ingest/bcsd/motions.py` — `parse_outcome_block()` (4 motion variants + roll call).
- Create `catalog/ingest/bcsd/minutes_md.py` — `parse_minutes_md()`.
- Create `catalog/ingest/bcsd/agenda_md.py` — `parse_agenda_md()` (fallback).
- Create `catalog/ingest/bcsd/adapter.py` — `parse_meeting_folder(path)` → `ParsedMeeting`.

**Command (new):**
- Create `catalog/management/__init__.py`, `catalog/management/commands/__init__.py`.
- Create `catalog/management/commands/ingest_bcsd.py`.

**Tests + fixtures (new):**
- Create `catalog/tests/fixtures/bcsd/committee/{event.md,minutes.md,agenda.md}` (copied from the verified archive).
- Create `catalog/tests/fixtures/bcsd/board/{event.md,minutes.md,agenda.md}` (copied from the verified archive).
- Create `catalog/tests/test_motion_model.py`, `test_ingest_names.py`, `test_bcsd_foldername.py`, `test_bcsd_event_md.py`, `test_bcsd_motions.py`, `test_bcsd_minutes_md.py`, `test_bcsd_agenda_md.py`, `test_bcsd_adapter.py`, `test_ingest_loader.py`, `test_ingest_bcsd_command.py`.

---

## Task 0: Copy verified fixtures into the repo

`archive_data/` is gitignored, so CI cannot read it. Commit the six verified files as test fixtures.

**Files:**
- Create: `catalog/tests/fixtures/bcsd/committee/{event.md,minutes.md,agenda.md}`
- Create: `catalog/tests/fixtures/bcsd/board/{event.md,minutes.md,agenda.md}`

- [ ] **Step 1: Copy the files**

```bash
ARCH="archive_data/bcsd/BCSD_BOE_MEETINGS/2025/04"
C="$ARCH/2025-04-17_1600_committee-meeting_mid-124789"
B="$ARCH/2025-04-17_1830_board-meeting_mid-124791"
mkdir -p catalog/tests/fixtures/bcsd/committee catalog/tests/fixtures/bcsd/board
cp "$C/event.md" "$C/minutes.md" "$C/agenda.md" catalog/tests/fixtures/bcsd/committee/
cp "$B/event.md" "$B/minutes.md" "$B/agenda.md" catalog/tests/fixtures/bcsd/board/
```

- [ ] **Step 2: Verify the copies exist and are non-empty**

Run: `wc -l catalog/tests/fixtures/bcsd/*/*.md`
Expected: six files, committee/minutes.md = 357 lines, board/minutes.md = 225 lines (the rest non-zero).

- [ ] **Step 3: Add a fixtures path helper for tests**

Create `catalog/tests/fixtures/__init__.py`:

```python
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent / "bcsd"


def fixture_text(meeting: str, name: str) -> str:
    """Read a committed BCSD fixture file, e.g. fixture_text("committee", "minutes.md")."""
    return (FIXTURES_DIR / meeting / name).read_text(encoding="utf-8")
```

- [ ] **Step 4: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/tests/fixtures/
git commit -m "test: add verified 04/17/2025 BCSD meeting fixtures"
```

---

## Task 1: Add the `Motion` model

**Files:**
- Modify: `catalog/models/facts.py`
- Modify: `catalog/models/__init__.py`
- Modify: `catalog/admin.py`
- Create: `catalog/tests/test_motion_model.py`
- Create: `catalog/migrations/0008_motion.py` (via `makemigrations`)

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_motion_model.py`:

```python
import datetime

import pytest
from django.db import IntegrityError

from catalog.models import (
    AgendaItem,
    Jurisdiction,
    Meeting,
    Motion,
    Organization,
    Person,
)


@pytest.fixture
def item(db):
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.COMMITTEE, slug="c"
    )
    return AgendaItem.objects.create(meeting=meeting, order=1, code="FSS-8", title="Chromebooks")


@pytest.mark.django_db
def test_motion_defaults_to_unreviewed_proposal(item):
    mover = Person.objects.create(full_name="Lisa Garrett-Boyd", slug="lisa-garrett-boyd")
    second = Person.objects.create(full_name="Myrtice Johnson", slug="myrtice-johnson")
    motion = Motion.objects.create(
        agenda_item=item,
        kind=Motion.Kind.INITIAL,
        sequence=0,
        moved_by=mover,
        seconded_by=second,
        result_text="Unanimously Approved",
        status=Motion.Status.UNANIMOUS,
    )
    assert motion.reviewed is False
    assert motion.moved_by == mover
    assert motion.seconded_by == second
    assert item.motions.count() == 1


@pytest.mark.django_db
def test_initial_and_amended_motions_coexist_on_one_item(item):
    Motion.objects.create(agenda_item=item, kind=Motion.Kind.INITIAL, sequence=0)
    Motion.objects.create(agenda_item=item, kind=Motion.Kind.AMENDED, sequence=1)
    assert item.motions.count() == 2


@pytest.mark.django_db
def test_motion_sequence_unique_per_item(item):
    Motion.objects.create(agenda_item=item, kind=Motion.Kind.SIMPLE, sequence=0)
    with pytest.raises(IntegrityError):
        Motion.objects.create(agenda_item=item, kind=Motion.Kind.AMENDED, sequence=0)


@pytest.mark.django_db
def test_motion_confidence_must_be_in_range(item):
    with pytest.raises(IntegrityError):
        Motion.objects.create(agenda_item=item, sequence=0, confidence=1.5)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_motion_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'Motion'`.

- [ ] **Step 3: Implement `Motion`**

Append to `catalog/models/facts.py` (add the `Person` import if not already broad — it is imported). Add at the top, after the existing imports, the `Q` is available via `models.Q`:

```python
class Motion(Reviewable):
    """A motion recorded against an agenda item (brief §5.2). A single item may
    carry an initial + amended pair (FSS-8) or a consent-agenda anchor motion that
    approves many items en bloc. Movers/seconders are proposed Persons; the
    per-member roll call (where present) is stored as Vote rows on the item."""

    class Kind(models.TextChoices):
        SIMPLE = "simple", "Simple"
        INITIAL = "initial", "Initial"
        AMENDED = "amended", "Amended"

    class Status(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        UNANIMOUS = "unanimous", "Unanimously Approved"
        NONE = "none", "No Recorded Result"

    agenda_item = models.ForeignKey(
        AgendaItem, on_delete=models.CASCADE, related_name="motions"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SIMPLE)
    sequence = models.PositiveSmallIntegerField(default=0)
    moved_by = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.SET_NULL, related_name="motions_moved"
    )
    seconded_by = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.SET_NULL, related_name="motions_seconded"
    )
    result_text = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NONE)

    class Meta:
        ordering = ["agenda_item", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["agenda_item", "sequence"], name="uniq_motion_item_sequence"
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__isnull=True)
                | models.Q(confidence__gte=0, confidence__lte=1),
                name="confidence_range_motion",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} motion on {self.agenda_item} ({self.status})"
```

Update `catalog/models/__init__.py` — add the import and `"Motion"` in alphabetical position:

```python
from .facts import Appearance, Motion, Vote
```

and insert `"Motion",` into `__all__` after `"MeetingCoverage",`.

- [ ] **Step 4: Register in admin**

In `catalog/admin.py`, add `Motion` to the import block (alphabetical, after `Meeting`/`MeetingCoverage`) and register it:

```python
@admin.register(Motion)
class MotionAdmin(admin.ModelAdmin):
    list_display = ("agenda_item", "kind", "sequence", "moved_by", "seconded_by", "status", "reviewed")
    list_filter = ("kind", "status", "reviewed")
```

- [ ] **Step 5: Make the migration**

Run: `uv run python manage.py makemigrations catalog --name motion`
Expected: creates `catalog/migrations/0008_motion.py`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest catalog/tests/test_motion_model.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/
git commit -m "feat: add Motion reviewable fact with initial/amended support"
```

---

## Task 2: Carry-forward schema hardening

Applies the four "cheap now, painful after data exists" items from the foundation review, plus the idempotency constraints the loader relies on. **Code-only** change: tidy `SLUG_TO_KIND`. **Migration** changes: r2_key partial-uniques, `confidence` ranges on `Organization`/`Person`/`Vote`/`Appearance`, `Meeting.slug` uniqueness, `AgendaItem (meeting, order)` uniqueness, `Appearance (person, meeting, role)` uniqueness.

**Files:**
- Modify: `catalog/models/meeting.py`, `catalog/models/org.py`, `catalog/models/facts.py`, `catalog/models/document.py`, `catalog/models/media.py`
- Create: `catalog/tests/test_schema_hardening.py`
- Create: `catalog/migrations/0009_schema_hardening.py` (via `makemigrations`)

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_schema_hardening.py`:

```python
import datetime

import pytest
from django.db import IntegrityError, transaction

from catalog.models import (
    AgendaItem,
    Appearance,
    Document,
    Jurisdiction,
    MediaAsset,
    Meeting,
    Organization,
    Person,
    Vote,
)


@pytest.mark.django_db
def test_document_r2_key_unique_but_blank_allowed():
    Document.objects.create(title="a")  # blank r2_key
    Document.objects.create(title="b")  # blank r2_key again -> allowed
    Document.objects.create(title="c", r2_key="bcsd/x.pdf")
    with pytest.raises(IntegrityError):
        Document.objects.create(title="d", r2_key="bcsd/x.pdf")


@pytest.mark.django_db
def test_media_r2_key_unique_but_blank_allowed():
    MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO)
    MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO)  # blank again -> allowed
    MediaAsset.objects.create(kind=MediaAsset.Kind.PDF, r2_key="bcsd/v.mp4")
    with pytest.raises(IntegrityError):
        MediaAsset.objects.create(kind=MediaAsset.Kind.PDF, r2_key="bcsd/v.mp4")


@pytest.mark.django_db
def test_confidence_range_enforced_on_person():
    with pytest.raises(IntegrityError):
        Person.objects.create(full_name="x", slug="x", confidence=2.0)


@pytest.mark.django_db
def test_confidence_range_enforced_on_vote():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b"
    )
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="x")
    person = Person.objects.create(full_name="p", slug="p")
    with pytest.raises(IntegrityError):
        Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA, confidence=-0.1)


@pytest.mark.django_db
def test_meeting_slug_unique_within_jurisdiction():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    Meeting.objects.create(
        body=body, jurisdiction=jur, date=datetime.date(2025, 4, 17),
        kind=Meeting.Kind.BOARD, slug="2025-04-17-board", source_meeting_id="1",
    )
    with pytest.raises(IntegrityError):
        Meeting.objects.create(
            body=body, jurisdiction=jur, date=datetime.date(2025, 4, 18),
            kind=Meeting.Kind.BOARD, slug="2025-04-17-board", source_meeting_id="2",
        )


@pytest.mark.django_db
def test_agenda_item_order_unique_per_meeting():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b"
    )
    AgendaItem.objects.create(meeting=meeting, order=1, title="x")
    with pytest.raises(IntegrityError):
        AgendaItem.objects.create(meeting=meeting, order=1, title="y")


@pytest.mark.django_db
def test_appearance_unique_per_person_meeting_role():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b"
    )
    person = Person.objects.create(full_name="p", slug="p")
    Appearance.objects.create(person=person, meeting=meeting, role=Appearance.Role.MEMBER)
    # same person, same meeting, different role -> allowed (member + invocation)
    Appearance.objects.create(person=person, meeting=meeting, role=Appearance.Role.INVOCATION)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Appearance.objects.create(person=person, meeting=meeting, role=Appearance.Role.MEMBER)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_schema_hardening.py -v`
Expected: FAIL (constraints not present yet — creates succeed where the test expects `IntegrityError`).

- [ ] **Step 3a: Tidy `SLUG_TO_KIND` and add `Meeting`/`AgendaItem` constraints (`catalog/models/meeting.py`)**

Replace the module-level `SLUG_TO_KIND` dict + the post-class `Meeting.SLUG_TO_KIND = SLUG_TO_KIND` reassignment by defining the map **inside the class body**. The class becomes:

```python
from django.db import models

from .base import TimeStamped
from .org import Jurisdiction, Organization, Source


class Meeting(TimeStamped):
    """The ingestion anchor: one meeting record (brief §7)."""

    # Maps the archive's folder type-slug to a Kind (brief §4.1).
    SLUG_TO_KIND = {
        "committee-meeting": "committee",
        "board-meeting": "board",
        "board-agenda": "board_agenda",
        "called-board-meeting": "called_board",
        "called-board-meeting-policy-review": "called_board",
    }

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
            ),
            models.UniqueConstraint(
                fields=["jurisdiction", "slug"],
                name="uniq_meeting_slug_per_jurisdiction",
            ),
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(jurisdiction__isnull=True),
                name="uniq_global_meeting_slug",
            ),
        ]

    @classmethod
    def kind_from_slug(cls, slug):
        """Map a raw folder type-slug to a Kind; unknown slugs → OTHER (§4.1)."""
        return cls.SLUG_TO_KIND.get(slug, cls.Kind.OTHER)

    def __str__(self):
        return f"{self.date} {self.get_kind_display()}"
```

And in the existing `AgendaItem` class `Meta`, add the unique constraint (keep `ordering`):

```python
    class Meta:
        ordering = ["meeting", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["meeting", "order"], name="uniq_agendaitem_meeting_order"
            )
        ]
```

- [ ] **Step 3b: Add `confidence` ranges on `Organization` + `Person` (`catalog/models/org.py`)**

In `Organization.Meta.constraints`, append:

```python
            models.CheckConstraint(
                condition=models.Q(confidence__isnull=True)
                | models.Q(confidence__gte=0, confidence__lte=1),
                name="confidence_range_organization",
            ),
```

`Person` has no `Meta` yet — add one:

```python
    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(confidence__isnull=True)
                | models.Q(confidence__gte=0, confidence__lte=1),
                name="confidence_range_person",
            )
        ]
```

- [ ] **Step 3c: Add `confidence` range on `Vote` + `confidence` range and role-uniqueness on `Appearance` (`catalog/models/facts.py`)**

In `Vote.Meta.constraints`, append the check:

```python
            models.CheckConstraint(
                condition=models.Q(confidence__isnull=True)
                | models.Q(confidence__gte=0, confidence__lte=1),
                name="confidence_range_vote",
            ),
```

`Appearance` has no `Meta` yet — add one:

```python
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["person", "meeting", "role"],
                name="uniq_appearance_person_meeting_role",
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__isnull=True)
                | models.Q(confidence__gte=0, confidence__lte=1),
                name="confidence_range_appearance",
            ),
        ]
```

- [ ] **Step 3d: Add `r2_key` partial-uniques (`catalog/models/document.py`, `catalog/models/media.py`)**

`Document` already has a `Meta` with `indexes` — add a `constraints` list:

```python
    class Meta:
        indexes = [GinIndex(fields=["search_vector"], name="gin_document_search")]
        constraints = [
            models.UniqueConstraint(
                fields=["r2_key"], condition=~models.Q(r2_key=""), name="uniq_document_r2_key"
            )
        ]
```

`MediaAsset` has no `Meta` — add one:

```python
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["r2_key"], condition=~models.Q(r2_key=""), name="uniq_media_r2_key"
            )
        ]
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations catalog --name schema_hardening`
Expected: creates `catalog/migrations/0009_schema_hardening.py` adding the constraints above (no field changes).

- [ ] **Step 5: Run tests to verify they pass (and the full suite is still green)**

Run: `uv run pytest catalog/tests/test_schema_hardening.py -v`
Expected: 7 passed.
Run: `uv run pytest -q`
Expected: all prior tests still pass (foundation 23 + Motion 4 + hardening 7).

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/
git commit -m "feat: apply slice-1b schema hardening (r2_key/slug uniqueness, confidence range, idempotency keys)"
```

---

## Task 3: The intermediate representation (IR)

The adapter contract (brief §14.3): framework-neutral frozen dataclasses. **No Django imports** — this is what keeps parsers pure and CI-fast.

**Files:**
- Create: `catalog/ingest/__init__.py` (empty)
- Create: `catalog/ingest/ir.py`
- Create: `catalog/tests/test_ingest_ir.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_ingest_ir.py`:

```python
import dataclasses
import datetime

from catalog.ingest.ir import (
    ParsedAgendaItem,
    ParsedAppearance,
    ParsedDocument,
    ParsedMeeting,
    ParsedMotion,
    ParsedPerson,
    ParsedVote,
)


def test_parsed_person_is_frozen():
    p = ParsedPerson(full_name="Myrtice Johnson", raw_name="Ms. Myrtice Johnson")
    assert p.full_name == "Myrtice Johnson"
    assert dataclasses.is_frozen(p) if hasattr(dataclasses, "is_frozen") else True
    try:
        p.full_name = "x"
        raise AssertionError("should be frozen")
    except dataclasses.FrozenInstanceError:
        pass


def test_parsed_meeting_composes_children():
    person = ParsedPerson(full_name="James Freeman", raw_name="Mr. James Freeman")
    motion = ParsedMotion(
        kind="simple", sequence=0, moved_by=person, seconded_by=None,
        result_text="Unanimously approved", status="unanimous",
    )
    vote = ParsedVote(person=person, value="yea")
    item = ParsedAgendaItem(
        order=5, code="FSS-3", title="Math adoption", item_type="action",
        reading_stage="", section="V. FISCAL/SUPPORT SERVICES COMMITTEE",
        outcome_text="authorized ... $5,515,711.09", outcome_status="unanimous",
        motions=(motion,), votes=(vote,), file_names=("hmh.pdf",),
    )
    appearance = ParsedAppearance(person=person, role="invocation")
    doc = ParsedDocument(kind="minutes", title="minutes.md", source_path="x/minutes.md", text="...")
    meeting = ParsedMeeting(
        date=datetime.date(2025, 4, 17), start_time=datetime.time(16, 0),
        kind_slug="committee-meeting", source_meeting_id="124789",
        source_url="https://...", source_path="x", folder_name="2025-04-17_1600_committee-meeting_mid-124789",
        title="Committee Meeting", roster=(person,), agenda_items=(item,),
        appearances=(appearance,), has_minutes=True, raw_documents=(doc,),
    )
    assert meeting.agenda_items[0].motions[0].moved_by.full_name == "James Freeman"
    assert meeting.has_minutes is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_ingest_ir.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.ingest'`.

- [ ] **Step 3: Implement the IR**

Create `catalog/ingest/__init__.py` (empty). Create `catalog/ingest/ir.py`:

```python
"""Adapter contract: framework-neutral parsed records (brief §14.3).

Every ingestion adapter emits these dataclasses; the generic loader consumes
them. Intentionally NO Django imports so parsers stay pure and unit-testable.
String enum values mirror the model TextChoices values (e.g. "yea", "action",
"unanimous") so the loader maps them with a plain lookup.
"""

import datetime
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedPerson:
    """A person mention. `full_name` is normalized; `raw_name` is verbatim source."""

    full_name: str
    raw_name: str
    role_hint: str = ""  # trailing roster role, e.g. "President"


@dataclass(frozen=True)
class ParsedVote:
    person: ParsedPerson
    value: str  # "yea" | "nay" | "abstain" | "absent"


@dataclass(frozen=True)
class ParsedMotion:
    kind: str  # "simple" | "initial" | "amended"
    sequence: int
    moved_by: ParsedPerson | None
    seconded_by: ParsedPerson | None
    result_text: str
    status: str  # "passed" | "failed" | "unanimous" | "none"


@dataclass(frozen=True)
class ParsedAppearance:
    person: ParsedPerson
    role: str  # "member" | "invocation" | "pledge" | "speaker" | "presenter" | "staff"


@dataclass(frozen=True)
class ParsedAgendaItem:
    order: int
    code: str
    title: str
    item_type: str  # "action" | "presentation" | "information" | "other"
    reading_stage: str  # "first" | "second" | ""
    section: str
    outcome_text: str = ""
    outcome_status: str = "none"
    motions: tuple[ParsedMotion, ...] = ()
    votes: tuple[ParsedVote, ...] = ()
    file_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedDocument:
    kind: str  # "minutes" | "agenda" | "other"
    title: str
    source_path: str
    text: str


@dataclass(frozen=True)
class ParsedMeeting:
    date: datetime.date
    start_time: datetime.time | None
    kind_slug: str
    source_meeting_id: str
    source_url: str
    source_path: str
    folder_name: str
    title: str
    roster: tuple[ParsedPerson, ...] = ()
    agenda_items: tuple[ParsedAgendaItem, ...] = ()
    appearances: tuple[ParsedAppearance, ...] = ()  # invocation/pledge/visitors (NOT roster)
    has_minutes: bool = False
    raw_documents: tuple[ParsedDocument, ...] = ()
```

> Note: `field` is imported for forward-compatibility with mutable defaults if a later adapter needs them; if ruff flags it as unused, drop the import.

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_ingest_ir.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/__init__.py catalog/ingest/ir.py catalog/tests/test_ingest_ir.py
git commit -m "feat: add ingestion IR dataclasses (adapter contract)"
```

---

## Task 4: Name normalization

Brief §5.2: strip leading honorific (`Ms.|Mr.|Mrs.|Dr.|Miss`), collapse internal double spaces, trim a trailing `, <Role>`. Pure function, heavily fixture-driven (handles `Ms.  Myrtice Johnson` double-space and `Attorney Roy Miller`).

**Files:**
- Create: `catalog/ingest/names.py`
- Create: `catalog/tests/test_ingest_names.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_ingest_names.py`:

```python
import pytest

from catalog.ingest.names import normalize_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Ms. Myrtice Johnson", "Myrtice Johnson"),
        ("Mr. Daryl Morton", "Daryl Morton"),
        ("Mrs. Kristin Hanlon", "Kristin Hanlon"),
        ("Dr. Henry Ficklin", "Henry Ficklin"),
        ("Ms.  Myrtice Johnson", "Myrtice Johnson"),  # double space after honorific
        (" Dr. Sundra Woodford", "Sundra Woodford"),  # leading space (variant 2 quirk)
        ("Ms. Myrtice Johnson, President", "Myrtice Johnson"),  # trailing role
        ("Dr. Lisa Garrett-Boyd, Board Member", "Lisa Garrett-Boyd"),
        ("Attorney Roy Miller", "Attorney Roy Miller"),  # "Attorney" is not a known honorific
        ("Jessican Strohmetz", "Jessican Strohmetz"),  # OCR typo preserved verbatim
        ("Miss Jane Doe", "Jane Doe"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_role_hint_via_split():
    from catalog.ingest.names import split_name_and_role

    name, role = split_name_and_role("Ms. Myrtice Johnson, President")
    assert name == "Myrtice Johnson"
    assert role == "President"

    name, role = split_name_and_role("Dr. Henry Ficklin")
    assert name == "Henry Ficklin"
    assert role == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_ingest_names.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.ingest.names'`.

- [ ] **Step 3: Implement**

Create `catalog/ingest/names.py`:

```python
"""Person-name normalization (brief §5.2).

Strips a leading honorific, collapses internal whitespace, and trims a trailing
", <Role>". OCR typos and unknown prefixes (e.g. "Attorney") are preserved
verbatim — resolution against the roster and cross-meeting dedup happen later.
"""

import re

_HONORIFIC = re.compile(r"^(Ms|Mr|Mrs|Dr|Miss)\.?\s+", re.IGNORECASE)
_WS = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    """Return a clean display name: no honorific, single-spaced, no trailing role."""
    name, _role = split_name_and_role(raw)
    return name


def split_name_and_role(raw: str) -> tuple[str, str]:
    """Return (clean_name, role). Role is the text after the first comma, or ""."""
    text = _WS.sub(" ", raw).strip()
    role = ""
    if "," in text:
        text, _, role = text.partition(",")
        text = text.strip()
        role = role.strip()
    text = _HONORIFIC.sub("", text).strip()
    return text, role
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_ingest_names.py -v`
Expected: 12 passed (11 parametrized + 1).

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/names.py catalog/tests/test_ingest_names.py
git commit -m "feat: add ingest name normalization"
```

---

## Task 5: Folder-name parser

Brief §4.1: `YYYY-MM-DD_HHMM_<type-slug>_mid-<MeetingID>`.

**Files:**
- Create: `catalog/ingest/bcsd/__init__.py` (empty)
- Create: `catalog/ingest/bcsd/foldername.py`
- Create: `catalog/tests/test_bcsd_foldername.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_bcsd_foldername.py`:

```python
import datetime

import pytest

from catalog.ingest.bcsd.foldername import ParsedFolderName, parse_folder_name


def test_parse_committee_folder():
    fn = parse_folder_name("2025-04-17_1600_committee-meeting_mid-124789")
    assert fn == ParsedFolderName(
        date=datetime.date(2025, 4, 17),
        start_time=datetime.time(16, 0),
        type_slug="committee-meeting",
        meeting_id="124789",
    )


def test_parse_board_folder():
    fn = parse_folder_name("2025-04-17_1830_board-meeting_mid-124791")
    assert fn.start_time == datetime.time(18, 30)
    assert fn.type_slug == "board-meeting"
    assert fn.meeting_id == "124791"


def test_parse_multiword_type_slug():
    fn = parse_folder_name("2014-07-29_1800_called-board-meeting-policy-review_mid-39007")
    assert fn.type_slug == "called-board-meeting-policy-review"
    assert fn.meeting_id == "39007"


def test_invalid_folder_name_raises():
    with pytest.raises(ValueError):
        parse_folder_name("not-a-meeting-folder")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_foldername.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.ingest.bcsd'`.

- [ ] **Step 3: Implement**

Create `catalog/ingest/bcsd/__init__.py` (empty). Create `catalog/ingest/bcsd/foldername.py`:

```python
"""Parse a BCSD meeting folder name (brief §4.1).

Format: YYYY-MM-DD_HHMM_<type-slug>_mid-<MeetingID>
The type-slug may contain hyphens, so anchor on the trailing `_mid-<id>`.
"""

import datetime
import re
from dataclasses import dataclass

_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{4})_(?P<slug>.+)_mid-(?P<mid>\d+)$"
)


@dataclass(frozen=True)
class ParsedFolderName:
    date: datetime.date
    start_time: datetime.time
    type_slug: str
    meeting_id: str


def parse_folder_name(name: str) -> ParsedFolderName:
    m = _PATTERN.match(name.strip())
    if not m:
        raise ValueError(f"Not a BCSD meeting folder name: {name!r}")
    date = datetime.date.fromisoformat(m["date"])
    hhmm = m["time"]
    start_time = datetime.time(int(hhmm[:2]), int(hhmm[2:]))
    return ParsedFolderName(
        date=date, start_time=start_time, type_slug=m["slug"], meeting_id=m["mid"]
    )
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_bcsd_foldername.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/bcsd/__init__.py catalog/ingest/bcsd/foldername.py catalog/tests/test_bcsd_foldername.py
git commit -m "feat: add BCSD folder-name parser"
```

---

## Task 6: `event.md` parser

Brief §5.1: title line, bulleted metadata block, `## Agenda Items` outline, `## Files` filename→item map. Returns metadata + agenda-item skeletons + a filename→attribution map. Agenda-item lines look like `- i. IS-1 School Consolidation Update and Recommendation (PRESENTATION)` or section lines `- IV. INSTRUCTIONAL SERVICES COMMITTEE`. HTML entities like `&amp;` must be unescaped.

**Files:**
- Create: `catalog/ingest/bcsd/event_md.py`
- Create: `catalog/tests/test_bcsd_event_md.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_bcsd_event_md.py`:

```python
from catalog.ingest.bcsd.event_md import parse_event_md
from catalog.tests.fixtures import fixture_text


def test_committee_event_metadata():
    ev = parse_event_md(fixture_text("committee", "event.md"))
    assert ev.meeting_id == "124789"
    assert ev.meeting_type == "Committee Meeting"
    assert ev.source_url.endswith("MID=124789")


def test_committee_event_agenda_items_have_codes_and_types():
    ev = parse_event_md(fixture_text("committee", "event.md"))
    by_code = {it.code: it for it in ev.agenda_items if it.code}
    # FSS-3 is an ACTION item.
    assert "FSS-3" in by_code
    assert by_code["FSS-3"].item_type == "action"
    assert by_code["FSS-3"].title.startswith("Mathematics Instructional Resources")
    # PR-1 carries a Second Reading stage.
    assert by_code["PR-1"].reading_stage == "second"
    # PR-4 is INFORMATION + First Reading.
    assert by_code["PR-4"].item_type == "information"
    assert by_code["PR-4"].reading_stage == "first"
    # HTML entity unescaped in a title.
    assert "&amp;" not in by_code["FSS-4"].title
    assert "&" in by_code["FSS-4"].title


def test_committee_event_files_map():
    ev = parse_event_md(fixture_text("committee", "event.md"))
    # The HMH quote pdf is attributed to FSS-3.
    assert ev.files["hmh.pdf"].startswith("ii. FSS-3")
    # Order is preserved and every line captured (60 attachments downloaded).
    assert len(ev.files) >= 55


def test_board_event_files_map_small():
    ev = parse_event_md(fixture_text("board", "event.md"))
    assert ev.meeting_id == "124791"
    assert "supt-board-041725-ppt.pptx" in ev.files
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_event_md.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `catalog/ingest/bcsd/event_md.py`:

```python
"""Parse a BCSD event.md (brief §5.1): metadata + agenda outline + files map."""

import html
import re
from dataclasses import dataclass, field

# An agenda-item line carries a code like "IS-1", "FSS-3", "PR-4", "PS-1", "FI-1".
_CODE = re.compile(r"\b([A-Z]{2,4}-\d+)\b")
_TYPE = re.compile(r"\(([A-Z]+)(?:\s*-\s*(First|Second)\s+Reading)?\)\s*$", re.IGNORECASE)
# Leading outline prefix: "I.", "i.", "a.", "ii." etc.
_OUTLINE_PREFIX = re.compile(r"^(?:[IVXLC]+|[ivxlc]+|[a-z]|\d+)\.\s+")
# A files line: `filename` (attribution text)
_FILE_LINE = re.compile(r"^-\s*`(?P<fname>[^`]+)`\s*\((?P<attr>.*)\)\s*$")
_META_LINE = re.compile(r"^-\s*\*\*(?P<key>[^:]+):\*\*\s*(?P<val>.*)$")

_TYPE_MAP = {
    "ACTION": "action",
    "PRESENTATION": "presentation",
    "INFORMATION": "information",
}


@dataclass(frozen=True)
class EventItem:
    order: int
    code: str
    title: str
    item_type: str
    reading_stage: str
    section: str


@dataclass(frozen=True)
class ParsedEvent:
    meeting_id: str
    meeting_type: str
    source_url: str
    folder: str
    agenda_items: tuple[EventItem, ...] = ()
    files: dict[str, str] = field(default_factory=dict)


def _classify(text: str) -> tuple[str, str]:
    """Return (item_type, reading_stage) from a trailing (TYPE - Reading) marker."""
    m = _TYPE.search(text)
    if not m:
        return "other", ""
    item_type = _TYPE_MAP.get(m.group(1).upper(), "other")
    stage = (m.group(2) or "").lower()
    return item_type, stage


def parse_event_md(text: str) -> ParsedEvent:
    lines = text.splitlines()
    meta: dict[str, str] = {}
    items: list[EventItem] = []
    files: dict[str, str] = {}
    section = ""
    order = 0
    mode = "meta"

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("## Agenda Items"):
            mode = "agenda"
            continue
        if stripped.startswith("## Files"):
            mode = "files"
            continue
        if stripped.startswith("## Notes"):
            mode = "notes"
            continue

        if mode == "meta":
            mm = _META_LINE.match(stripped)
            if mm:
                meta[mm["key"].strip().lower()] = html.unescape(mm["val"].strip().strip("`"))
        elif mode == "agenda":
            if not stripped.startswith("- "):
                continue
            body = html.unescape(stripped[2:].strip())
            prefix_m = _OUTLINE_PREFIX.match(body)
            content = body[prefix_m.end():] if prefix_m else body
            code_m = _CODE.search(content)
            if code_m is None and content.isupper() is False and prefix_m and prefix_m.group(0)[0].isupper():
                # Heuristic: an uppercase Roman-numeral line with no code is a section header.
                pass
            # Section headers are the Roman-numeral, all-caps committee names.
            is_section = bool(re.match(r"^[IVXLC]+\.\s", body)) and code_m is None
            if is_section:
                section = body
                continue
            order += 1
            code = code_m.group(1) if code_m else ""
            item_type, stage = _classify(content)
            # Title: strip a leading code token and the trailing (TYPE) marker.
            title = content
            if code:
                title = title[code_m.end():].strip()
            title = _TYPE.sub("", title).strip()
            items.append(
                EventItem(
                    order=order, code=code, title=title, item_type=item_type,
                    reading_stage=stage, section=section,
                )
            )
        elif mode == "files":
            fm = _FILE_LINE.match(stripped)
            if fm:
                files[fm["fname"]] = html.unescape(fm["attr"].strip())

    return ParsedEvent(
        meeting_id=meta.get("meeting id", ""),
        meeting_type=meta.get("meeting type", ""),
        source_url=meta.get("source url", ""),
        folder=meta.get("folder", ""),
        agenda_items=tuple(items),
        files=files,
    )
```

> **Implementer note:** The section-vs-item discrimination above is the tricky part. The rule is: a line is a **section header** when it begins with a Roman numeral + `.` AND contains no `[A-Z]{2,4}-\d+` code (e.g. `IV. INSTRUCTIONAL SERVICES COMMITTEE`). Everything else with an outline prefix is an item. Verify against the fixture: the committee `event.md` yields items for IS-1…FI-4 and sections IV/V/VI/VII/VIII. Adjust the regex only if a fixture assertion fails; keep the public return type stable.

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_bcsd_event_md.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/bcsd/event_md.py catalog/tests/test_bcsd_event_md.py
git commit -m "feat: add BCSD event.md parser (metadata, agenda items, files map)"
```

---

## Task 7: Motion-block + roll-call parser (the four variants)

Brief §5.2 — the riskiest parser. Given the lines of one item's outcome block (everything between its `####` header and the next header), return `(outcome_text, list[ParsedMotion], list[ParsedVote])`. Handles:
1. **Bulleted:** `- Motion made by:` / `- Motion seconded by:` then `_Voting results:_ <result>`.
2. **Non-bulleted:** `Motion made by:` / `Motion seconded by:` / `Voting: <result>`.
3. **Initial + Amended:** `Initial Motion made by:` / `Initial Motion seconded by:` / `Voting:` / `Amended Motion made by:` / `Voting:`.
4. **Per-person roll call:** after `_Voting results:_`, bulleted `- Yes: <name>` / `- No: <name>` / `- Abstain:` / `- Absent:`.

**Files:**
- Create: `catalog/ingest/bcsd/motions.py`
- Create: `catalog/tests/test_bcsd_motions.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_bcsd_motions.py`:

```python
from catalog.ingest.bcsd.motions import parse_outcome_block


def test_variant1_bulleted_unanimous():
    block = [
        "The Board authorized the purchase in an amount not to exceed $5,515,711.09.",
        "",
        "- Motion made by: Dr. Henry Ficklin",
        "- Motion seconded by: Dr. Lisa Garrett-Boyd",
        "",
        "_Voting results:_ Unanimously approved",
    ]
    text, motions, votes = parse_outcome_block(block)
    assert "5,515,711.09" in text
    assert len(motions) == 1
    assert motions[0].kind == "simple"
    assert motions[0].moved_by.full_name == "Henry Ficklin"
    assert motions[0].seconded_by.full_name == "Lisa Garrett-Boyd"
    assert motions[0].status == "unanimous"
    assert votes == []


def test_variant2_non_bulleted():
    block = [
        "The Board voted to enter into Executive Session at 6:03 p.m.",
        "",
        "Motion made by: Dr. Sundra Woodford",
        "",
        "Motion seconded by: Mr. Daryl Morton",
        "",
        "Voting: Unanimously Approved",
    ]
    text, motions, votes = parse_outcome_block(block)
    assert len(motions) == 1
    assert motions[0].moved_by.full_name == "Sundra Woodford"
    assert motions[0].status == "unanimous"


def test_variant3_initial_and_amended():
    block = [
        "The Board entertained a motion ... SureLock Technology ... $2,919,243.58 ...",
        "Upon a request for clarification ... the initial motion was amended as follows:",
        "The Board authorizes the purchase order ... contingent upon the passage of FSS-11 ...",
        "",
        "Initial Motion made by: Dr. Lisa Garrett-Boyd",
        "",
        "Initial Motion seconded by: Ms.  Myrtice Johnson",
        "",
        "Voting: Unanimously Approved",
        "",
        "Amended Motion made by: Mr. James Freeman",
        "",
        "Voting: Unanimously Approved",
    ]
    text, motions, votes = parse_outcome_block(block)
    assert len(motions) == 2
    assert motions[0].kind == "initial"
    assert motions[0].sequence == 0
    assert motions[0].seconded_by.full_name == "Myrtice Johnson"  # double-space normalized
    assert motions[1].kind == "amended"
    assert motions[1].sequence == 1
    assert motions[1].moved_by.full_name == "James Freeman"


def test_variant4_per_person_roll_call():
    block = [
        "The Board approved the Consent Agenda as revised ...",
        "",
        "- Motion made by: Mr. James Freeman",
        "- Motion seconded by: Mr. Daryl Morton",
        "",
        "_Voting results:_ Unanimously approved",
        "",
        "- Yes: Ms. Myrtice Johnson",
        "- Yes: Mr. Daryl Morton",
        "- Yes: Mrs. Kristin Hanlon",
        "- Yes: Dr. Henry Ficklin",
        "- Yes: Mr. Barney Hester",
        "- Yes: Dr. Sundra Woodford",
        "- Yes: Mr. James Freeman",
        "- Yes: Dr. Lisa Garrett-Boyd",
    ]
    text, motions, votes = parse_outcome_block(block)
    assert len(motions) == 1
    assert len(votes) == 8
    assert all(v.value == "yea" for v in votes)
    assert votes[0].person.full_name == "Myrtice Johnson"


def test_no_motion_block_returns_text_only():
    block = ["This item was informational; no action taken."]
    text, motions, votes = parse_outcome_block(block)
    assert motions == []
    assert votes == []
    assert text.startswith("This item")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_motions.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `catalog/ingest/bcsd/motions.py`:

```python
"""Parse a BCSD minutes outcome block: motion variants + roll call (brief §5.2)."""

import re

from catalog.ingest.ir import ParsedMotion, ParsedPerson, ParsedVote
from catalog.ingest.names import normalize_name

# Strip an optional leading "- " bullet, tolerate the four label forms.
_MOVED = re.compile(r"^-?\s*(Initial |Amended )?Motion made by:\s*(?P<name>.+?)\s*$")
_SECONDED = re.compile(r"^-?\s*(Initial |Amended )?Motion seconded by:\s*(?P<name>.+?)\s*$")
_VOTING = re.compile(r"^-?\s*(?:_?Voting(?: results)?:?_?)\s*(?P<result>.+?)\s*$", re.IGNORECASE)
_ROLL = re.compile(r"^-\s*(?P<label>Yes|No|Abstain|Absent):\s*(?P<name>.+?)\s*$", re.IGNORECASE)

_ROLL_VALUE = {"yes": "yea", "no": "nay", "abstain": "abstain", "absent": "absent"}


def _person(raw: str) -> ParsedPerson:
    return ParsedPerson(full_name=normalize_name(raw), raw_name=raw.strip())


def _status(result_text: str) -> str:
    low = result_text.lower()
    if "unanim" in low:
        return "unanimous"
    if "fail" in low or "denied" in low or "not approved" in low:
        return "failed"
    if result_text:
        return "passed"
    return "none"


def parse_outcome_block(lines: list[str]) -> tuple[str, list[ParsedMotion], list[ParsedVote]]:
    """Return (outcome_text, motions, roll_call_votes) for one agenda item."""
    motions: list[ParsedMotion] = []
    votes: list[ParsedVote] = []
    prose: list[str] = []

    # Working state for the motion currently being assembled.
    cur_kind = "simple"
    cur_moved: ParsedPerson | None = None
    cur_seconded: ParsedPerson | None = None
    seq = 0
    have_motion_signal = False

    def flush(result_text: str):
        nonlocal cur_kind, cur_moved, cur_seconded, seq, have_motion_signal
        if not have_motion_signal and not result_text:
            return
        motions.append(
            ParsedMotion(
                kind=cur_kind, sequence=seq, moved_by=cur_moved,
                seconded_by=cur_seconded, result_text=result_text.strip(),
                status=_status(result_text),
            )
        )
        seq += 1
        cur_kind = "amended" if cur_kind in ("initial", "amended") else "simple"
        cur_moved = None
        cur_seconded = None
        have_motion_signal = False

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        roll_m = _ROLL.match(line)
        if roll_m:
            votes.append(
                ParsedVote(
                    person=_person(roll_m["name"]),
                    value=_ROLL_VALUE[roll_m["label"].lower()],
                )
            )
            continue
        moved_m = _MOVED.match(line)
        if moved_m:
            label = (moved_m.group(1) or "").strip().lower()
            if label == "initial":
                cur_kind = "initial"
            elif label == "amended":
                # A new amended motion begins; flush any pending unflushed motion first.
                if have_motion_signal and cur_moved is not None and cur_seconded is not None:
                    pass
                cur_kind = "amended"
            cur_moved = _person(moved_m["name"])
            have_motion_signal = True
            continue
        seconded_m = _SECONDED.match(line)
        if seconded_m:
            cur_seconded = _person(seconded_m["name"])
            have_motion_signal = True
            continue
        voting_m = _VOTING.match(line)
        if voting_m and (have_motion_signal or motions):
            flush(voting_m["result"])
            continue
        prose.append(line)

    # An item may end with a dangling motion that never had an explicit result line.
    if have_motion_signal:
        flush("")

    return "\n".join(prose).strip(), motions, votes
```

> **Implementer note:** Variant 3 is the trap. "Initial Motion made by / seconded by / Voting:" must flush motion #0 (kind=initial, seq=0) on its `Voting:` line, then "Amended Motion made by / Voting:" flushes motion #1 (kind=amended, seq=1) — note the amended motion in the board fixture has **no** seconded line, so `seconded_by` is `None` there. Run the tests; if `test_variant3` fails, trace the flush sequencing rather than widening the regexes. Keep `parse_outcome_block`'s signature stable — later tasks depend on it.

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_bcsd_motions.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/bcsd/motions.py catalog/tests/test_bcsd_motions.py
git commit -m "feat: add BCSD motion-block + roll-call parser (4 variants)"
```

---

## Task 8: `minutes.md` parser

Brief §5.2. Parses the `## Meeting Minutes` body: attendance roster (`#### Voting Members`), per-item outcome blocks keyed by code/title (delegating to `parse_outcome_block`), and the special appearances — invocation ("The invocation was given by <Name>."), pledge (Pledge subitem name), and visitors ("Invitation to Visitors" speaker list). Returns roster + an outcome map + appearances.

**Files:**
- Create: `catalog/ingest/bcsd/minutes_md.py`
- Create: `catalog/tests/test_bcsd_minutes_md.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_bcsd_minutes_md.py`:

```python
from catalog.ingest.bcsd.minutes_md import parse_minutes_md
from catalog.tests.fixtures import fixture_text


def test_committee_roster():
    parsed = parse_minutes_md(fixture_text("committee", "minutes.md"))
    names = {p.full_name for p in parsed.roster}
    assert "Myrtice Johnson" in names
    assert "Lisa Garrett-Boyd" in names
    assert len(parsed.roster) == 8
    # Role hint captured from "- Ms. Myrtice Johnson, President".
    pres = next(p for p in parsed.roster if p.full_name == "Myrtice Johnson")
    assert pres.role_hint == "President"


def test_committee_invocation_appearance():
    parsed = parse_minutes_md(fixture_text("committee", "minutes.md"))
    invos = [a for a in parsed.appearances if a.role == "invocation"]
    assert len(invos) == 1
    assert invos[0].person.full_name == "Henry Ficklin"


def test_committee_fss3_outcome_and_motion():
    parsed = parse_minutes_md(fixture_text("committee", "minutes.md"))
    fss3 = parsed.outcomes["FSS-3"]
    assert "5,515,711.09" in fss3.outcome_text
    assert len(fss3.motions) == 1
    assert fss3.motions[0].moved_by.full_name == "Henry Ficklin"
    assert fss3.outcome_status == "unanimous"


def test_committee_fss8_initial_amended():
    parsed = parse_minutes_md(fixture_text("committee", "minutes.md"))
    fss8 = parsed.outcomes["FSS-8"]
    assert len(fss8.motions) == 2
    assert fss8.motions[0].kind == "initial"
    assert fss8.motions[1].kind == "amended"


def test_committee_pr2_postponed_status():
    parsed = parse_minutes_md(fixture_text("committee", "minutes.md"))
    pr2 = parsed.outcomes["PR-2"]
    # The item was postponed even though the motion to postpone was unanimous.
    assert pr2.outcome_status == "postponed"


def test_board_roll_call_votes():
    parsed = parse_minutes_md(fixture_text("board", "minutes.md"))
    # The consent-agenda anchor item ("Confirmation of Minutes") carries 8 yea votes.
    anchor = parsed.outcomes["Confirmation of Minutes - Board Meetings (2025) - March"]
    assert len(anchor.votes) == 8
    assert all(v.value == "yea" for v in anchor.votes)


def test_board_visitor_and_pledge_appearances():
    parsed = parse_minutes_md(fixture_text("board", "minutes.md"))
    speakers = {a.person.full_name for a in parsed.appearances if a.role == "speaker"}
    assert "Attorney Roy Miller" in speakers
    assert "Jessican Strohmetz" in speakers  # OCR typo preserved
    pledges = [a for a in parsed.appearances if a.role == "pledge"]
    assert len(pledges) == 1
    assert "Nikolai Connor Floore" in pledges[0].person.raw_name
    invos = [a for a in parsed.appearances if a.role == "invocation"]
    assert invos[0].person.full_name == "Arizona Watkins"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `catalog/ingest/bcsd/minutes_md.py`:

```python
"""Parse a BCSD minutes.md (brief §5.2): roster, per-item outcomes, appearances."""

import html
import re
from dataclasses import dataclass, field

from catalog.ingest.bcsd.motions import parse_outcome_block
from catalog.ingest.ir import ParsedAppearance, ParsedMotion, ParsedPerson, ParsedVote
from catalog.ingest.names import normalize_name, split_name_and_role

_CODE = re.compile(r"\b([A-Z]{2,4}-\d+)\b")
_ITEM_HEADER = re.compile(r"^####\s+(?:[ivxlc]+|[a-z]|\d+)\.\s+(?P<rest>.+?)\s*$")
_SECTION_HEADER = re.compile(r"^###\s+(?P<rest>.+?)\s*$")
_INVOCATION = re.compile(r"invocation was given by\s+(?P<name>[^.]+)\.?", re.IGNORECASE)


@dataclass(frozen=True)
class ItemOutcome:
    code: str
    title: str
    outcome_text: str
    outcome_status: str
    motions: tuple[ParsedMotion, ...]
    votes: tuple[ParsedVote, ...]


@dataclass(frozen=True)
class ParsedMinutes:
    roster: tuple[ParsedPerson, ...] = ()
    outcomes: dict[str, ItemOutcome] = field(default_factory=dict)
    appearances: tuple[ParsedAppearance, ...] = ()


def _derive_status(outcome_text: str, motions: list[ParsedMotion]) -> str:
    low = outcome_text.lower()
    if "postpone" in low:
        return "postponed"
    if "tabled" in low or "table the" in low:
        return "tabled"
    if motions:
        # Reflect the motion result onto the item where it isn't postponed/tabled.
        if any(m.status == "unanimous" for m in motions):
            return "unanimous"
        if any(m.status == "failed" for m in motions):
            return "failed"
        return "passed"
    return "none"


def _split_meeting_minutes(text: str) -> list[str]:
    """Return the lines of the `## Meeting Minutes` section (after the agenda echo)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("## Meeting Minutes"):
            return lines[i + 1 :]
    return lines


def _parse_roster(body: list[str]) -> list[ParsedPerson]:
    roster: list[ParsedPerson] = []
    in_voting = False
    for line in body:
        s = line.strip()
        if s.startswith("#### Voting Members"):
            in_voting = True
            continue
        if in_voting and s.startswith("###"):
            break
        if in_voting and s.startswith("- "):
            raw = html.unescape(s[2:].strip())
            name, role = split_name_and_role(raw)
            roster.append(ParsedPerson(full_name=name, raw_name=raw, role_hint=role))
    return roster


def _parse_appearances(body: list[str]) -> list[ParsedAppearance]:
    appearances: list[ParsedAppearance] = []
    section = ""
    i = 0
    while i < len(body):
        s = body[i].strip()
        sec_m = _SECTION_HEADER.match(s)
        if sec_m:
            section = sec_m["rest"].upper()
        # Invocation prose.
        inv = _INVOCATION.search(s)
        if inv:
            raw = html.unescape(inv["name"].strip())
            appearances.append(
                ParsedAppearance(
                    person=ParsedPerson(full_name=normalize_name(raw), raw_name=raw),
                    role="invocation",
                )
            )
        # Pledge: subitem under a PLEDGE section header.
        if "PLEDGE OF ALLEGIANCE" in section and s.startswith("#### "):
            item_m = _ITEM_HEADER.match(s)
            if item_m:
                raw = html.unescape(item_m["rest"].strip())
                appearances.append(
                    ParsedAppearance(
                        person=ParsedPerson(full_name=normalize_name(raw), raw_name=raw),
                        role="pledge",
                    )
                )
        # Visitors: bare-name lines under the INVITATION TO VISITORS section.
        if "INVITATION TO VISITORS" in section and s and not s.startswith(("#", "-", "The ", "_")):
            raw = html.unescape(s)
            appearances.append(
                ParsedAppearance(
                    person=ParsedPerson(full_name=normalize_name(raw), raw_name=raw),
                    role="speaker",
                )
            )
        i += 1
    return appearances


def parse_minutes_md(text: str) -> ParsedMinutes:
    body = _split_meeting_minutes(text)
    roster = _parse_roster(body)
    appearances = _parse_appearances(body)

    # Walk item headers; collect each item's block until the next ### / #### header.
    outcomes: dict[str, ItemOutcome] = {}
    headers: list[tuple[int, str]] = []
    for idx, line in enumerate(body):
        if _ITEM_HEADER.match(line.strip()):
            headers.append((idx, line.strip()))
    for n, (idx, header) in enumerate(headers):
        end = headers[n + 1][0] if n + 1 < len(headers) else len(body)
        # Stop the block at the next section header too.
        block_lines = []
        for j in range(idx + 1, end):
            s = body[j].strip()
            if s.startswith("### ") and not s.startswith("#### "):
                break
            block_lines.append(body[j])
        rest = html.unescape(_ITEM_HEADER.match(header)["rest"])
        code_m = _CODE.search(rest)
        code = code_m.group(1) if code_m else ""
        # Title: strip code + trailing (TYPE...) marker.
        title = rest
        if code:
            title = title[code_m.end():].strip()
        title = re.sub(r"\s*\([A-Z].*\)\s*$", "", title).strip()
        otext, motions, votes = parse_outcome_block(block_lines)
        status = _derive_status(otext, motions)
        key = code or title
        outcomes[key] = ItemOutcome(
            code=code, title=title, outcome_text=otext, outcome_status=status,
            motions=tuple(motions), votes=tuple(votes),
        )

    return ParsedMinutes(
        roster=tuple(roster), outcomes=outcomes, appearances=tuple(appearances)
    )
```

> **Implementer note:** Key items by `code` when present, else by the cleaned `title` (that's why the board consent anchor is keyed `"Confirmation of Minutes - Board Meetings (2025) - March"`). The visitor heuristic ("bare-name line under INVITATION TO VISITORS that isn't a header/bullet/prose") is deliberately loose — verify it captures exactly `Attorney Roy Miller` and `Jessican Strohmetz` and not the "The following citizens submitted..." prose line. Adjust the prose-prefix filter only as needed to pass the fixture assertions.

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/bcsd/minutes_md.py catalog/tests/test_bcsd_minutes_md.py
git commit -m "feat: add BCSD minutes.md parser (roster, outcomes, appearances)"
```

---

## Task 9: `agenda.md` fallback parser

Brief §5.3: same outline as the top of `minutes.md`, no minutes body. Used only when `minutes.md` is absent. Yields agenda items (order/code/title/type/section) but no outcomes/votes.

**Files:**
- Create: `catalog/ingest/bcsd/agenda_md.py`
- Create: `catalog/tests/test_bcsd_agenda_md.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_bcsd_agenda_md.py`:

```python
from catalog.ingest.bcsd.agenda_md import parse_agenda_md
from catalog.tests.fixtures import fixture_text


def test_agenda_items_from_outline():
    items = parse_agenda_md(fixture_text("committee", "agenda.md"))
    by_code = {it.code: it for it in items if it.code}
    assert "FSS-3" in by_code
    assert by_code["FSS-3"].item_type == "action"
    # Section captured.
    assert "FISCAL" in by_code["FSS-3"].section.upper()


def test_agenda_has_no_outcomes():
    items = parse_agenda_md(fixture_text("committee", "agenda.md"))
    # agenda items carry order but the fallback never sets outcome data here.
    assert all(it.order > 0 for it in items)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_agenda_md.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `catalog/ingest/bcsd/agenda_md.py`:

```python
"""Parse a BCSD agenda.md outline (brief §5.3) — fallback when minutes are absent.

The `## Agenda` section uses Markdown headers: `### <Roman>. <SECTION>` and
`#### <numeral>. <CODE> <Title> (<TYPE>)`, identical to the agenda echo at the
top of minutes.md. Reuses the event.md classification helpers."""

import html
import re

from catalog.ingest.bcsd.event_md import EventItem, _CODE, _classify

_ITEM = re.compile(r"^####\s+(?:[ivxlc]+|[a-z]|\d+)\.\s+(?P<rest>.+?)\s*$")
_SECTION = re.compile(r"^###\s+(?P<rest>[IVXLC]+\.\s+.+?)\s*$")


def parse_agenda_md(text: str) -> list[EventItem]:
    items: list[EventItem] = []
    section = ""
    order = 0
    in_agenda = False
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("## Agenda"):
            in_agenda = True
            continue
        if s.startswith("## Meeting Minutes"):
            break
        if not in_agenda:
            continue
        sec_m = _SECTION.match(s)
        item_m = _ITEM.match(s)
        if sec_m and not _CODE.search(sec_m["rest"]):
            section = html.unescape(sec_m["rest"])
            continue
        if item_m:
            rest = html.unescape(item_m["rest"])
            code_m = _CODE.search(rest)
            code = code_m.group(1) if code_m else ""
            item_type, stage = _classify(rest)
            title = rest[code_m.end():].strip() if code else rest
            title = re.sub(r"\s*\([A-Z].*\)\s*$", "", title).strip()
            order += 1
            items.append(
                EventItem(
                    order=order, code=code, title=title, item_type=item_type,
                    reading_stage=stage, section=section,
                )
            )
    return items
```

> **Implementer note:** This reuses `EventItem`, `_CODE`, and `_classify` from `event_md.py` (importing a leading-underscore name across modules in the same package is acceptable here — they are package-internal helpers, not public API). If a reviewer objects to the underscore import, promote `_classify`/`_CODE` to non-underscore names in `event_md.py` and update both call sites.

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_bcsd_agenda_md.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/bcsd/agenda_md.py catalog/tests/test_bcsd_agenda_md.py
git commit -m "feat: add BCSD agenda.md fallback parser"
```

---

## Task 10: BCSD adapter orchestrator

Ties the parsers together: given a meeting folder `Path`, produce one `ParsedMeeting` IR. Joins `event.md` agenda items with `minutes.md` outcomes by code/title, attaches `## Files` filenames, builds roster + appearances + source documents. Falls back to `agenda.md` when `minutes.md` is absent.

**Files:**
- Create: `catalog/ingest/bcsd/adapter.py`
- Create: `catalog/tests/test_bcsd_adapter.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_bcsd_adapter.py`:

```python
import datetime
import shutil
from pathlib import Path

import pytest

from catalog.ingest.bcsd.adapter import parse_meeting_folder
from catalog.tests.fixtures import FIXTURES_DIR


def _make_folder(tmp_path: Path, fixture: str, folder_name: str, *, with_minutes=True) -> Path:
    src = FIXTURES_DIR / fixture
    dst = tmp_path / folder_name
    dst.mkdir()
    shutil.copy(src / "event.md", dst / "event.md")
    shutil.copy(src / "agenda.md", dst / "agenda.md")
    if with_minutes:
        shutil.copy(src / "minutes.md", dst / "minutes.md")
    return dst


def test_committee_meeting_parsed(tmp_path):
    folder = _make_folder(tmp_path, "committee", "2025-04-17_1600_committee-meeting_mid-124789")
    pm = parse_meeting_folder(folder)
    assert pm.date == datetime.date(2025, 4, 17)
    assert pm.start_time == datetime.time(16, 0)
    assert pm.kind_slug == "committee-meeting"
    assert pm.source_meeting_id == "124789"
    assert pm.has_minutes is True
    assert len(pm.roster) == 8

    by_code = {it.code: it for it in pm.agenda_items if it.code}
    fss3 = by_code["FSS-3"]
    assert fss3.outcome_status == "unanimous"
    assert len(fss3.motions) == 1
    assert fss3.motions[0].moved_by.full_name == "Henry Ficklin"
    assert "hmh.pdf" in fss3.file_names
    # FSS-8 initial+amended carried through the join.
    assert len(by_code["FSS-8"].motions) == 2


def test_board_roll_call_carried_through(tmp_path):
    folder = _make_folder(tmp_path, "board", "2025-04-17_1830_board-meeting_mid-124791")
    pm = parse_meeting_folder(folder)
    assert pm.kind_slug == "board-meeting"
    # The consent-agenda anchor item carries 8 roll-call votes.
    anchor = next(it for it in pm.agenda_items if it.title.startswith("Confirmation of Minutes"))
    assert len(anchor.votes) == 8
    speakers = {a.person.full_name for a in pm.appearances if a.role == "speaker"}
    assert {"Attorney Roy Miller", "Jessican Strohmetz"} <= speakers


def test_minutes_absent_falls_back_to_agenda(tmp_path):
    folder = _make_folder(
        tmp_path, "committee", "2025-04-17_1600_committee-meeting_mid-124789", with_minutes=False
    )
    pm = parse_meeting_folder(folder)
    assert pm.has_minutes is False
    assert len(pm.agenda_items) > 0
    # No minutes -> no outcomes/votes/motions materialized.
    assert all(not it.motions and not it.votes for it in pm.agenda_items)
    assert pm.roster == ()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `catalog/ingest/bcsd/adapter.py`:

```python
"""BCSD Source-A adapter: a meeting folder → one ParsedMeeting IR (brief §4–§5)."""

from pathlib import Path

from catalog.ingest.bcsd.agenda_md import parse_agenda_md
from catalog.ingest.bcsd.event_md import parse_event_md
from catalog.ingest.bcsd.foldername import parse_folder_name
from catalog.ingest.bcsd.minutes_md import parse_minutes_md
from catalog.ingest.ir import (
    ParsedAgendaItem,
    ParsedDocument,
    ParsedMeeting,
)


def _files_for_item(files: dict[str, str], code: str, title: str) -> tuple[str, ...]:
    """Filenames whose attribution text references this item's code or title."""
    out = []
    needle = code or title
    for fname, attr in files.items():
        if needle and needle in attr:
            out.append(fname)
    return tuple(out)


def parse_meeting_folder(folder: Path) -> ParsedMeeting:
    folder = Path(folder)
    fn = parse_folder_name(folder.name)
    event_text = (folder / "event.md").read_text(encoding="utf-8")
    event = parse_event_md(event_text)

    minutes_path = folder / "minutes.md"
    agenda_path = folder / "agenda.md"
    has_minutes = minutes_path.exists()

    raw_documents = [
        ParsedDocument(kind="other", title="event.md", source_path=str(folder / "event.md"),
                       text=event_text),
    ]

    if has_minutes:
        minutes_text = minutes_path.read_text(encoding="utf-8")
        minutes = parse_minutes_md(minutes_text)
        event_items = event.agenda_items
        roster = minutes.roster
        appearances = minutes.appearances
        raw_documents.append(
            ParsedDocument(kind="minutes", title="minutes.md",
                           source_path=str(minutes_path), text=minutes_text)
        )
    else:
        # Fallback: build items from agenda.md (or event.md if agenda missing).
        if agenda_path.exists():
            agenda_text = agenda_path.read_text(encoding="utf-8")
            event_items = tuple(parse_agenda_md(agenda_text))
        else:
            event_items = event.agenda_items
        minutes = None
        roster = ()
        appearances = ()

    if agenda_path.exists():
        raw_documents.append(
            ParsedDocument(kind="agenda", title="agenda.md", source_path=str(agenda_path),
                           text=agenda_path.read_text(encoding="utf-8"))
        )

    items: list[ParsedAgendaItem] = []
    for ev in event_items:
        outcome = None
        if minutes is not None:
            outcome = minutes.outcomes.get(ev.code) or minutes.outcomes.get(ev.title)
        items.append(
            ParsedAgendaItem(
                order=ev.order, code=ev.code, title=ev.title, item_type=ev.item_type,
                reading_stage=ev.reading_stage, section=ev.section,
                outcome_text=outcome.outcome_text if outcome else "",
                outcome_status=outcome.outcome_status if outcome else "none",
                motions=outcome.motions if outcome else (),
                votes=outcome.votes if outcome else (),
                file_names=_files_for_item(event.files, ev.code, ev.title),
            )
        )

    return ParsedMeeting(
        date=fn.date,
        start_time=fn.start_time,
        kind_slug=fn.type_slug,
        source_meeting_id=fn.meeting_id or event.meeting_id,
        source_url=event.source_url,
        source_path=str(folder),
        folder_name=folder.name,
        title=event.meeting_type or folder.name,
        roster=tuple(roster),
        agenda_items=tuple(items),
        appearances=tuple(appearances),
        has_minutes=has_minutes,
        raw_documents=tuple(raw_documents),
    )
```

> **Implementer note:** The join prefers `minutes.outcomes[code]`, falling back to `minutes.outcomes[title]` (for code-less items like the board consent anchor). When `minutes.md` is absent, items come from `agenda.md` and carry no outcomes. Keep `parse_meeting_folder(folder: Path) -> ParsedMeeting` stable — the loader and command call it.

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_bcsd_adapter.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/bcsd/adapter.py catalog/tests/test_bcsd_adapter.py
git commit -m "feat: add BCSD adapter orchestrator (folder -> ParsedMeeting IR)"
```

---

## Task 11: The generic loader

The only DB-touching ingestion module, and agency-agnostic: it consumes a `ParsedMeeting` IR plus a `(source, jurisdiction, body)` context and materializes rows as `reviewed=False` proposals, with a `Citation` into the `minutes.md` Document for every `Vote`/`Appearance`/`Motion`. Idempotent at the meeting level (wipe-and-recreate meeting-scoped facts; `get_or_create` shared entities).

**Files:**
- Create: `catalog/ingest/loader.py`
- Create: `catalog/tests/test_ingest_loader.py`

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_ingest_loader.py`:

```python
import datetime

import pytest

from catalog.ingest.ir import (
    ParsedAgendaItem,
    ParsedAppearance,
    ParsedDocument,
    ParsedMeeting,
    ParsedMotion,
    ParsedPerson,
    ParsedVote,
)
from catalog.ingest.loader import load_meeting
from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    Meeting,
    Motion,
    Organization,
    Person,
    Source,
    Vote,
)


@pytest.fixture
def context(db):
    jur = Jurisdiction.objects.create(
        name="Bibb County Board of Education", slug="bibb-county-boe",
        kind=Jurisdiction.Kind.SCHOOL_DISTRICT,
    )
    source = Source.objects.create(name="BCSD BOE Meetings", slug="bcsd-boe-meetings", adapter="bcsd")
    body = Organization.objects.create(
        name="Board of Education", slug="boe", kind=Organization.Kind.COMMITTEE, jurisdiction=jur
    )
    return jur, source, body


def _person(name):
    return ParsedPerson(full_name=name, raw_name=name)


def _sample_meeting():
    ficklin = _person("Henry Ficklin")
    boyd = _person("Lisa Garrett-Boyd")
    johnson = _person("Myrtice Johnson")
    fss3 = ParsedAgendaItem(
        order=5, code="FSS-3", title="Math adoption", item_type="action", reading_stage="",
        section="V. FISCAL", outcome_text="authorized ... $5,515,711.09", outcome_status="unanimous",
        motions=(ParsedMotion(kind="simple", sequence=0, moved_by=ficklin, seconded_by=boyd,
                              result_text="Unanimously approved", status="unanimous"),),
    )
    consent = ParsedAgendaItem(
        order=20, code="", title="Confirmation of Minutes", item_type="action", reading_stage="",
        section="VIII. CONSENT AGENDA", outcome_text="approved consent", outcome_status="passed",
        motions=(ParsedMotion(kind="simple", sequence=0, moved_by=johnson, seconded_by=ficklin,
                              result_text="Unanimously approved", status="unanimous"),),
        votes=(ParsedVote(person=johnson, value="yea"), ParsedVote(person=ficklin, value="yea")),
    )
    return ParsedMeeting(
        date=datetime.date(2025, 4, 17), start_time=datetime.time(16, 0),
        kind_slug="committee-meeting", source_meeting_id="124789",
        source_url="https://simbli/MID=124789", source_path="/x/committee",
        folder_name="2025-04-17_1600_committee-meeting_mid-124789", title="Committee Meeting",
        roster=(johnson, ficklin, boyd), agenda_items=(fss3, consent),
        appearances=(ParsedAppearance(person=ficklin, role="invocation"),),
        has_minutes=True,
        raw_documents=(ParsedDocument(kind="minutes", title="minutes.md",
                                      source_path="/x/committee/minutes.md", text="..."),),
    )


@pytest.mark.django_db
def test_load_creates_meeting_items_and_proposals(context):
    jur, source, body = context
    meeting = load_meeting(_sample_meeting(), source=source, jurisdiction=jur, body=body)

    assert meeting.source_meeting_id == "124789"
    assert meeting.kind == Meeting.Kind.COMMITTEE
    assert meeting.start_time == datetime.time(16, 0)
    assert meeting.reviewed is False if hasattr(meeting, "reviewed") else True
    # Roster members each get a member Appearance.
    assert Appearance.objects.filter(meeting=meeting, role=Appearance.Role.MEMBER).count() == 3
    # Invocation appearance present.
    assert Appearance.objects.filter(meeting=meeting, role=Appearance.Role.INVOCATION).count() == 1
    # FSS-3 unanimous, no roll call -> NO Vote rows, status on the item.
    fss3 = AgendaItem.objects.get(meeting=meeting, code="FSS-3")
    assert fss3.outcome_status == AgendaItem.OutcomeStatus.UNANIMOUS
    assert Vote.objects.filter(agenda_item=fss3).count() == 0
    assert Motion.objects.filter(agenda_item=fss3).count() == 1
    # Consent anchor has a roll call -> 2 Vote rows.
    consent = AgendaItem.objects.get(meeting=meeting, title="Confirmation of Minutes")
    assert Vote.objects.filter(agenda_item=consent).count() == 2


@pytest.mark.django_db
def test_every_fact_has_a_citation_into_minutes(context):
    jur, source, body = context
    meeting = load_meeting(_sample_meeting(), source=source, jurisdiction=jur, body=body)
    minutes = Document.objects.get(meeting=meeting, kind=Document.Kind.MINUTES)

    for vote in Vote.objects.filter(agenda_item__meeting=meeting):
        cites = Citation.objects.for_fact(vote)
        assert cites.count() >= 1
        assert cites.first().document == minutes
    for motion in Motion.objects.filter(agenda_item__meeting=meeting):
        assert Citation.objects.for_fact(motion).count() >= 1
    for appearance in Appearance.objects.filter(meeting=meeting):
        assert Citation.objects.for_fact(appearance).count() >= 1


@pytest.mark.django_db
def test_everything_is_unreviewed(context):
    jur, source, body = context
    meeting = load_meeting(_sample_meeting(), source=source, jurisdiction=jur, body=body)
    assert not Vote.objects.filter(agenda_item__meeting=meeting, reviewed=True).exists()
    assert not Appearance.objects.filter(meeting=meeting, reviewed=True).exists()
    assert not Motion.objects.filter(agenda_item__meeting=meeting, reviewed=True).exists()
    assert not Person.objects.filter(reviewed=True).exists()


@pytest.mark.django_db
def test_reload_is_idempotent(context):
    jur, source, body = context
    load_meeting(_sample_meeting(), source=source, jurisdiction=jur, body=body)
    load_meeting(_sample_meeting(), source=source, jurisdiction=jur, body=body)
    assert Meeting.objects.filter(source=source, source_meeting_id="124789").count() == 1
    meeting = Meeting.objects.get(source=source, source_meeting_id="124789")
    # No duplicate items/votes/persons after a second run.
    assert AgendaItem.objects.filter(meeting=meeting).count() == 2
    assert Vote.objects.filter(agenda_item__meeting=meeting).count() == 2
    assert Person.objects.count() == 3  # johnson, ficklin, boyd reused, not duplicated
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_ingest_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.ingest.loader'`.

- [ ] **Step 3: Implement**

Create `catalog/ingest/loader.py`:

```python
"""Generic IR → Django loader (brief §14.3). Agency-agnostic: it never imports a
BCSD module. Writes everything as reviewed=False proposals and emits a Citation
into the minutes Document for every materialized Vote/Appearance/Motion.

Idempotency: keyed on Meeting (source, source_meeting_id). Re-ingest wipes the
meeting's existing facts (agenda items -> motions/votes; appearances; source
documents -> citations) and recreates them. Shared entities (Jurisdiction,
Source, Organization, Person) are get_or_create and never wiped. NOTE: once admin
review begins, this wipe strategy must be revisited (out of scope for slice 1b).
"""

from django.db import transaction
from django.utils.text import slugify

from catalog.ingest.ir import ParsedMeeting, ParsedPerson
from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Meeting,
    Motion,
    Person,
    Vote,
)

_ITEM_TYPE = {
    "action": AgendaItem.ItemType.ACTION,
    "presentation": AgendaItem.ItemType.PRESENTATION,
    "information": AgendaItem.ItemType.INFORMATION,
    "other": AgendaItem.ItemType.OTHER,
}
_READING = {"first": AgendaItem.ReadingStage.FIRST, "second": AgendaItem.ReadingStage.SECOND, "": ""}
_OUTCOME = {
    "passed": AgendaItem.OutcomeStatus.PASSED,
    "failed": AgendaItem.OutcomeStatus.FAILED,
    "tabled": AgendaItem.OutcomeStatus.TABLED,
    "postponed": AgendaItem.OutcomeStatus.POSTPONED,
    "unanimous": AgendaItem.OutcomeStatus.UNANIMOUS,
    "none": AgendaItem.OutcomeStatus.NONE,
}
_VOTE_VALUE = {
    "yea": Vote.Value.YEA,
    "nay": Vote.Value.NAY,
    "abstain": Vote.Value.ABSTAIN,
    "absent": Vote.Value.ABSENT,
}
_MOTION_KIND = {"simple": Motion.Kind.SIMPLE, "initial": Motion.Kind.INITIAL, "amended": Motion.Kind.AMENDED}
_MOTION_STATUS = {
    "passed": Motion.Status.PASSED,
    "failed": Motion.Status.FAILED,
    "unanimous": Motion.Status.UNANIMOUS,
    "none": Motion.Status.NONE,
}
_APPEARANCE_ROLE = {
    "member": Appearance.Role.MEMBER,
    "speaker": Appearance.Role.SPEAKER,
    "presenter": Appearance.Role.PRESENTER,
    "staff": Appearance.Role.STAFF,
    "invocation": Appearance.Role.INVOCATION,
    "pledge": Appearance.Role.PLEDGE,
}


def _meeting_slug(parsed: ParsedMeeting) -> str:
    return slugify(f"{parsed.date.isoformat()}-{parsed.kind_slug}-mid-{parsed.source_meeting_id}")


def _get_person(parsed_person: ParsedPerson, cache: dict[str, Person]) -> Person:
    slug = slugify(parsed_person.full_name) or slugify(parsed_person.raw_name)
    if slug in cache:
        return cache[slug]
    person, _ = Person.objects.get_or_create(
        slug=slug, defaults={"full_name": parsed_person.full_name, "reviewed": False}
    )
    cache[slug] = person
    return person


@transaction.atomic
def load_meeting(parsed: ParsedMeeting, *, source, jurisdiction, body) -> Meeting:
    meeting, _ = Meeting.objects.update_or_create(
        source=source,
        source_meeting_id=parsed.source_meeting_id,
        defaults={
            "body": body,
            "jurisdiction": jurisdiction,
            "date": parsed.date,
            "start_time": parsed.start_time,
            "kind": Meeting.kind_from_slug(parsed.kind_slug),
            "raw_type_slug": parsed.kind_slug,
            "title": parsed.title,
            "source_url": parsed.source_url,
            "source_path": parsed.source_path,
            "slug": _meeting_slug(parsed),
        },
    )

    # Idempotency: wipe this meeting's existing facts before recreating.
    AgendaItem.objects.filter(meeting=meeting).delete()  # cascades motions + votes
    Appearance.objects.filter(meeting=meeting).delete()
    Document.objects.filter(meeting=meeting).delete()  # cascades citations on these docs

    # Source documents (so Citations have an evidence target).
    minutes_doc = None
    for pdoc in parsed.raw_documents:
        kind = {"minutes": Document.Kind.MINUTES, "agenda": Document.Kind.AGENDA}.get(
            pdoc.kind, Document.Kind.OTHER
        )
        doc = Document.objects.create(
            title=pdoc.title, kind=kind, meeting=meeting, source=source,
            source_url=parsed.source_url,
            ocr_status=Document.OCRStatus.HAS_TEXT,
        )
        if pdoc.kind == "minutes":
            minutes_doc = doc

    person_cache: dict[str, Person] = {}

    # Roster -> member appearances (+ citation when we have a minutes doc).
    for rp in parsed.roster:
        person = _get_person(rp, person_cache)
        appearance = Appearance.objects.create(
            person=person, meeting=meeting, role=Appearance.Role.MEMBER, reviewed=False
        )
        if minutes_doc:
            Citation.objects.create(fact=appearance, document=minutes_doc)

    # Other appearances (invocation/pledge/visitors).
    for pa in parsed.appearances:
        person = _get_person(pa.person, person_cache)
        appearance = Appearance.objects.create(
            person=person, meeting=meeting,
            role=_APPEARANCE_ROLE.get(pa.role, Appearance.Role.SPEAKER), reviewed=False
        )
        if minutes_doc:
            Citation.objects.create(fact=appearance, document=minutes_doc)

    # Agenda items + motions + roll-call votes.
    for pitem in parsed.agenda_items:
        item = AgendaItem.objects.create(
            meeting=meeting, order=pitem.order, code=pitem.code, title=pitem.title,
            item_type=_ITEM_TYPE.get(pitem.item_type, AgendaItem.ItemType.OTHER),
            reading_stage=_READING.get(pitem.reading_stage, ""),
            outcome_text=pitem.outcome_text,
            outcome_status=_OUTCOME.get(pitem.outcome_status, AgendaItem.OutcomeStatus.NONE),
        )
        for pm in pitem.motions:
            motion = Motion.objects.create(
                agenda_item=item, kind=_MOTION_KIND.get(pm.kind, Motion.Kind.SIMPLE),
                sequence=pm.sequence,
                moved_by=_get_person(pm.moved_by, person_cache) if pm.moved_by else None,
                seconded_by=_get_person(pm.seconded_by, person_cache) if pm.seconded_by else None,
                result_text=pm.result_text,
                status=_MOTION_STATUS.get(pm.status, Motion.Status.NONE), reviewed=False,
            )
            if minutes_doc:
                Citation.objects.create(fact=motion, document=minutes_doc)
        for pv in pitem.votes:
            person = _get_person(pv.person, person_cache)
            vote = Vote.objects.create(
                person=person, agenda_item=item,
                value=_VOTE_VALUE.get(pv.value, Vote.Value.YEA), reviewed=False
            )
            if minutes_doc:
                Citation.objects.create(fact=vote, document=minutes_doc)

    return meeting
```

> **Implementer note:** The loader must import `Vote` at the top alongside the other models and never reference a BCSD module (the boundary is one-directional: BCSD → IR → loader). The `Citation.objects.create(fact=..., document=minutes_doc)` calls rely on the generic-FK `fact=` shortcut wired in the foundation's `Citation`. Materialize a `Vote` **only** from `pitem.votes` (explicit roll call) — never synthesize per-member yea votes for unanimous items (§9 #13).

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_ingest_loader.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/loader.py catalog/tests/test_ingest_loader.py
git commit -m "feat: add generic IR loader with provenance citations"
```

---

## Task 12: `ingest_bcsd` management command + end-to-end test

Wires a folder path → adapter → loader, bootstrapping the BCSD `Jurisdiction`/`Source`/body `Organization`. Drives the real 04/17/2025 pair end-to-end against the committed fixtures.

**Files:**
- Create: `catalog/management/__init__.py`, `catalog/management/commands/__init__.py` (empty)
- Create: `catalog/management/commands/ingest_bcsd.py`
- Create: `catalog/tests/test_ingest_bcsd_command.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_ingest_bcsd_command.py`:

```python
import shutil

import pytest
from django.core.management import call_command

from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Jurisdiction,
    Meeting,
    Motion,
    Organization,
    Source,
    Vote,
)
from catalog.tests.fixtures import FIXTURES_DIR


def _stage_pair(tmp_path):
    """Lay out the two meeting folders as the archive does."""
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
    return root


@pytest.mark.django_db
def test_command_ingests_both_meetings(tmp_path):
    root = _stage_pair(tmp_path)
    call_command("ingest_bcsd", str(root / "2025-04-17_1600_committee-meeting_mid-124789"))
    call_command("ingest_bcsd", str(root / "2025-04-17_1830_board-meeting_mid-124791"))

    assert Meeting.objects.count() == 2
    assert Jurisdiction.objects.filter(slug="bibb-county-boe").exists()
    assert Source.objects.filter(adapter="bcsd").exists()

    committee = Meeting.objects.get(source_meeting_id="124789")
    assert committee.kind == Meeting.Kind.COMMITTEE
    # FSS-8 carries an initial + amended motion.
    fss8 = AgendaItem.objects.get(meeting=committee, code="FSS-8")
    assert Motion.objects.filter(agenda_item=fss8).count() == 2

    board = Meeting.objects.get(source_meeting_id="124791")
    # The board consent anchor materialized 8 roll-call votes; the adjourn + PS-6 add more.
    assert Vote.objects.filter(agenda_item__meeting=board).count() >= 8
    # Visitors captured as speaker appearances.
    assert Appearance.objects.filter(
        meeting=board, role=Appearance.Role.SPEAKER
    ).count() >= 2

    # Provenance: every vote is cited into the minutes.
    for vote in Vote.objects.all():
        assert Citation.objects.for_fact(vote).count() >= 1

    # Nothing is auto-reviewed.
    assert not Vote.objects.filter(reviewed=True).exists()
    assert not Appearance.objects.filter(reviewed=True).exists()


@pytest.mark.django_db
def test_command_is_idempotent(tmp_path):
    root = _stage_pair(tmp_path)
    folder = str(root / "2025-04-17_1600_committee-meeting_mid-124789")
    call_command("ingest_bcsd", folder)
    call_command("ingest_bcsd", folder)
    assert Meeting.objects.filter(source_meeting_id="124789").count() == 1
    committee = Meeting.objects.get(source_meeting_id="124789")
    fss8 = AgendaItem.objects.get(meeting=committee, code="FSS-8")
    assert Motion.objects.filter(agenda_item=fss8).count() == 2  # not 4
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest catalog/tests/test_ingest_bcsd_command.py -v`
Expected: FAIL — `CommandError: Unknown command: 'ingest_bcsd'`.

- [ ] **Step 3: Implement**

Create `catalog/management/__init__.py` and `catalog/management/commands/__init__.py` (both empty). Create `catalog/management/commands/ingest_bcsd.py`:

```python
"""Ingest one BCSD meeting folder (Source A) into the catalog as proposals."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.ingest.bcsd.adapter import parse_meeting_folder
from catalog.ingest.loader import load_meeting
from catalog.models import Jurisdiction, Organization, Source

JURISDICTION = {
    "slug": "bibb-county-boe",
    "name": "Bibb County Board of Education",
    "kind": Jurisdiction.Kind.SCHOOL_DISTRICT,
}
SOURCE = {"slug": "bcsd-boe-meetings", "name": "BCSD BOE Meetings", "adapter": "bcsd"}
BODY = {"slug": "boe", "name": "Bibb County Board of Education", "kind": Organization.Kind.COMMITTEE}


class Command(BaseCommand):
    help = "Ingest a BCSD meeting folder (Source A) into the catalog as reviewed=False proposals."

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Path to a single meeting folder.")

    def handle(self, *args, **options):
        folder = Path(options["folder"])
        if not folder.is_dir():
            raise CommandError(f"Not a directory: {folder}")

        jurisdiction, _ = Jurisdiction.objects.get_or_create(
            slug=JURISDICTION["slug"],
            defaults={"name": JURISDICTION["name"], "kind": JURISDICTION["kind"]},
        )
        source, _ = Source.objects.get_or_create(
            slug=SOURCE["slug"],
            defaults={"name": SOURCE["name"], "adapter": SOURCE["adapter"], "jurisdiction": jurisdiction},
        )
        body, _ = Organization.objects.get_or_create(
            slug=BODY["slug"], jurisdiction=jurisdiction,
            defaults={"name": BODY["name"], "kind": BODY["kind"], "reviewed": True},
        )

        parsed = parse_meeting_folder(folder)
        meeting = load_meeting(parsed, source=source, jurisdiction=jurisdiction, body=body)
        self.stdout.write(
            self.style.SUCCESS(
                f"Ingested {meeting} (mid={meeting.source_meeting_id}): "
                f"{meeting.agenda_items.count()} items, "
                f"{sum(i.votes.count() for i in meeting.agenda_items.all())} votes, "
                f"{meeting.appearances.count()} appearances (all reviewed=False)."
            )
        )
```

> **Implementer note:** The body `Organization` is created with `reviewed=True` — it's an operator-asserted anchor (the known meeting body), not a parsed proposal. Persons and facts remain `reviewed=False`.

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest catalog/tests/test_ingest_bcsd_command.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the full suite + system checks**

Run: `uv run pytest -q`
Expected: all tests pass (foundation 23 + this slice's new tests).
Run: `uv run python manage.py check`
Expected: `System check identified no issues`.
Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 6: Smoke-test against the REAL archive (manual; not committed)**

Run:
```bash
uv run python manage.py ingest_bcsd \
  "archive_data/bcsd/BCSD_BOE_MEETINGS/2025/04/2025-04-17_1600_committee-meeting_mid-124789"
uv run python manage.py ingest_bcsd \
  "archive_data/bcsd/BCSD_BOE_MEETINGS/2025/04/2025-04-17_1830_board-meeting_mid-124791"
```
Expected: two `SUCCESS` lines; committee reports ~46 items and 0 votes (all unanimous, no roll call), board reports its consent/PS-6/adjourn roll-call votes. (This writes to the dev DB; it is a manual sanity check, not part of CI.)

- [ ] **Step 7: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/management/ catalog/tests/test_ingest_bcsd_command.py
git commit -m "feat: add ingest_bcsd management command (end-to-end Source-A ingest)"
```

---

## Self-Review

**Spec coverage (brief §4–§6, §8 Source A, §9, handoff 1b list):**
- Folder-name → date/time/type-slug→kind/MeetingID (§4.1) → Task 5 + loader `kind_from_slug`. ✓
- `event.md` metadata + `## Files` map (§5.1) → Task 6 + adapter `_files_for_item`. ✓
- `minutes.md` roster (§5.2) → Task 8 `_parse_roster`. ✓
- Per-item outcome_text/status (§5.2) → Task 8 `_derive_status` (incl. postponed/tabled nuance). ✓
- All four motion-block variants (§5.2 #1–4, §9 #8) → Task 7 with a dedicated test per variant. ✓
- Per-person roll-call → `Vote`s (§5.2 #4) → Task 7 + loader. ✓
- Invocation/pledge/visitor → `Appearance`s (§5.2) → Task 8 `_parse_appearances`. ✓
- Name normalization (§5.2, §9 #9) → Task 4 (honorifics, double-space, trailing role, OCR-typo passthrough). ✓
- `agenda.md` fallback when minutes absent (§5.3, §9 #7) → Task 9 + adapter branch + Task 10 test. ✓
- type-slug varies / unknown → `other` (§4.1, §9 #6) → existing `kind_from_slug`, exercised. ✓
- Don't over-assert votes: per-member only on explicit roll call (§9 #13) → loader materializes `Vote` only from `pitem.votes`; unanimous lives on `AgendaItem`/`Motion`. ✓
- Provenance from day one: proposals + citations (§9 #14) → loader writes `reviewed=False` + `Citation` per Vote/Appearance/Motion; test_provenance shape honored. ✓
- Clean adapter boundary (§14.3, §14.7) → IR (Task 3) + generic loader (Task 11), BCSD code isolated under `catalog/ingest/bcsd/`. ✓
- Carry-forward items 1–4 (foundation review) → Task 2 (r2_key uniques, Meeting.slug uniqueness, confidence range ×5 models, SLUG_TO_KIND tidy). ✓
- Motion model (user decision) → Task 1. ✓

**Placeholder scan:** No TBD/TODO/placeholder code. Every code step shows complete, runnable code; every command shows expected output. (The loader's vote mapping is the explicit module-level `_VOTE_VALUE` dict.)

**Type consistency:** `parse_outcome_block(lines) -> (str, list[ParsedMotion], list[ParsedVote])` defined in Task 7, consumed in Task 8. `parse_meeting_folder(folder) -> ParsedMeeting` defined in Task 10, consumed in Tasks 11/12. `EventItem`/`_classify`/`_CODE` defined in Task 6, reused in Task 9. `load_meeting(parsed, *, source, jurisdiction, body) -> Meeting` defined in Task 11, called in Task 12. IR field names (`agenda_items`, `outcome_status`, `file_names`, `roster`, `appearances`, `raw_documents`) defined in Task 3 and used identically downstream. `Motion.Kind`/`Motion.Status` defined in Task 1, mapped in Task 11.

**Deferred-scope honored:** no file-attachment Documents, no vendor Organizations, no recordings — each stated in Scope and absent from tasks.
