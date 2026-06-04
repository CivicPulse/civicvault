# Appearance Name-Validation + Orphan Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the BCSD minutes parser from materializing prose fragments and role descriptors as `Person` rows, and add a safe command to delete the edge-less proposal nodes that re-ingestion leaves behind.

**Architecture:** A pure `looks_like_name()` predicate in `catalog/ingest/names.py` gates the three appearance-capture sites in `catalog/ingest/bcsd/minutes_md.py` (visitor, pledge, invocation); the invocation site additionally picks the name-shaped comma-segment so a "Role, Name" apposition recovers the real person. A new dry-run-default `prune_orphans` management command removes `Person`/vendor-`Organization` rows that have zero facts and zero relationships.

**Tech Stack:** Python 3 / Django, `pytest` + `pytest-django`, `uv` for all Python invocation, `ruff` for lint/format. No new dependencies, no migration.

**Spec:** [`docs/superpowers/specs/2026-06-04-civicvault-appearance-name-validation-design.md`](../specs/2026-06-04-civicvault-appearance-name-validation-design.md)

**Conventions for every task:**
- Run Python only via `uv run …` (never system python). Lint with `uv run ruff check .` and `uv run ruff format .` before each commit.
- `docker compose up -d db` must be running for any DB test. Commit on branch `fix/appearance-name-parsing`; never push, never merge to main without an explicit ask. Conventional Commits.
- Parser/predicate unit tests: `catalog/tests/`. Management-command tests: `tests/`.

---

## Task 1: `looks_like_name()` predicate in `names.py`

**Files:**
- Modify: `catalog/ingest/names.py` (add a regex constant, a particle set, and the function)
- Test: `catalog/tests/test_ingest_names.py` (existing file — append)

- [ ] **Step 1: Write the failing tests**

Append to `catalog/tests/test_ingest_names.py` (it already imports from `catalog.ingest.names`; add `looks_like_name` to that import):

```python
import pytest

from catalog.ingest.names import looks_like_name


@pytest.mark.parametrize(
    "text",
    [
        "Roy Miller",
        "Jessican Strohmetz",
        "Kenneth Moye",
        "Juawn Jackson",
        "Henry Ficklin",
        "Lisa Garrett-Boyd",
        "Madison Pritchard",
        "Smith",
        "John Q. Public",
        "Maria de la Cruz",
    ],
)
def test_looks_like_name_accepts_real_names(text):
    assert looks_like_name(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Four people addressed the Board for comments.",
        "They were:",
        "Two eighth grade students from Miller Middle School congratulated their new principal",
        "No visitors requested to address the Board.",
        "There were no requests to address the Board.",
        "Board member",
        "Little Miss and Mr. Cherry Blossom Festival 2024: Alexandria Habersham",
        "",
        "   ",
    ],
)
def test_looks_like_name_rejects_prose_and_descriptors(text):
    assert looks_like_name(text) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest catalog/tests/test_ingest_names.py -k looks_like_name -v`
Expected: FAIL — `ImportError: cannot import name 'looks_like_name'`.

- [ ] **Step 3: Implement the predicate**

In `catalog/ingest/names.py`, after the existing module-level regex constants (after `_WS = re.compile(r"\s+")`), add:

```python
_NAME_TOKEN = re.compile(r"^[A-Z][A-Za-z'’.-]*$")
_NAME_PARTICLES = {"de", "van", "von", "der", "da", "del", "la", "di", "bin", "al"}


def looks_like_name(text: str) -> bool:
    """True if text is shaped like a person name: 1–5 tokens, no terminal sentence
    punctuation, every token Capitalized (or a known nobiliary particle). Rejects
    prose ("Four people addressed the Board.") and role descriptors ("Board member")."""
    text = (text or "").strip()
    if not text or text[-1] in ".:;,":
        return False
    toks = text.split()
    if not (1 <= len(toks) <= 5):
        return False
    return all(t.lower() in _NAME_PARTICLES or bool(_NAME_TOKEN.match(t)) for t in toks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest catalog/tests/test_ingest_names.py -v`
Expected: PASS (all, including the existing name-normalization tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/ingest/names.py catalog/tests/test_ingest_names.py
git commit -m "feat(ingest): add looks_like_name predicate for appearance validation"
```

---

## Task 2: Gate the visitor-capture site

**Files:**
- Modify: `catalog/ingest/bcsd/minutes_md.py` (import line 9; the visitor branch at lines 144-154)
- Test: `catalog/tests/test_bcsd_minutes_md.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `catalog/tests/test_bcsd_minutes_md.py` (it already imports `parse_minutes_md`):

```python
def _minutes(section_body: str) -> str:
    """Wrap a minutes section so parse_minutes_md sees it as the Meeting Minutes body."""
    return "# Doc\n\n## Meeting Minutes\n\n" + section_body


def test_visitor_prose_is_not_captured_as_speakers():
    text = _minutes(
        "### VI. INVITATION TO VISITORS TO ADDRESS THE BOARD\n\n"
        "Four people addressed the Board for comments.\n\n"
        "They were:\n\n"
        "Two eighth grade students from Miller Middle School congratulated their new principal.\n"
    )
    parsed = parse_minutes_md(text)
    assert [a for a in parsed.appearances if a.role == "speaker"] == []


def test_named_visitors_are_captured():
    text = _minutes(
        "### VI. INVITATION TO VISITORS TO ADDRESS THE BOARD\n\n"
        "The following citizens submitted requests to address the Board:\n\n"
        "Attorney Roy Miller\n\n"
        "Jessican Strohmetz\n"
    )
    parsed = parse_minutes_md(text)
    names = sorted(a.person.full_name for a in parsed.appearances if a.role == "speaker")
    assert names == ["Jessican Strohmetz", "Roy Miller"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py -k "visitor" -v`
Expected: FAIL — `test_visitor_prose_is_not_captured_as_speakers` fails (3 prose lines captured as speakers).

- [ ] **Step 3: Add the import and gate the visitor branch**

In `catalog/ingest/bcsd/minutes_md.py`, change the import (line 9) from:

```python
from catalog.ingest.names import normalize_name, split_name_and_role
```

to:

```python
from catalog.ingest.names import looks_like_name, normalize_name, split_name_and_role
```

Then replace the visitor branch (lines 144-154) — currently:

```python
        # Visitors: bare-name lines under the INVITATION TO VISITORS section.
        # Exclude blank lines, headers, bullet points, lines starting with "The "
        # (e.g. the introductory prose line), and markdown emphasis markers.
        if "INVITATION TO VISITORS" in section and s and not s.startswith(("#", "-", "The ", "_")):
            raw = html.unescape(s)
            appearances.append(
                ParsedAppearance(
                    person=ParsedPerson(full_name=normalize_name(raw), raw_name=raw),
                    role="speaker",
                )
            )
```

with:

```python
        # Visitors: name-shaped lines under the INVITATION TO VISITORS section. The
        # section is often narrated in prose ("Four people addressed the Board.");
        # looks_like_name() is the real filter, so only structural prefixes are excluded.
        if "INVITATION TO VISITORS" in section and s and not s.startswith(("#", "-")):
            raw = html.unescape(s)
            name = normalize_name(raw)
            if looks_like_name(name):
                appearances.append(
                    ParsedAppearance(
                        person=ParsedPerson(full_name=name, raw_name=raw),
                        role="speaker",
                    )
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py -v`
Expected: PASS (all, including the existing committee/board minutes tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/ingest/bcsd/minutes_md.py catalog/tests/test_bcsd_minutes_md.py
git commit -m "fix(ingest): only capture name-shaped visitor speakers, not prose"
```

---

## Task 3: Gate the pledge-capture site

**Files:**
- Modify: `catalog/ingest/bcsd/minutes_md.py` (the pledge branch at lines 132-142)
- Test: `catalog/tests/test_bcsd_minutes_md.py` (append; reuses the `_minutes` helper from Task 2)

- [ ] **Step 1: Write the failing tests**

Append to `catalog/tests/test_bcsd_minutes_md.py`:

```python
def test_pledge_award_title_header_is_not_captured():
    text = _minutes(
        "### III. PLEDGE OF ALLEGIANCE\n\n"
        "#### i. Little Miss and Mr. Cherry Blossom Festival 2024: "
        "Alexandria Habersham, Alexander II School; Beau Mote, Vineville Academy\n"
    )
    parsed = parse_minutes_md(text)
    assert [a for a in parsed.appearances if a.role == "pledge"] == []


def test_plain_name_pledge_is_captured():
    text = _minutes("### III. PLEDGE OF ALLEGIANCE\n\n#### i. Madison Pritchard\n")
    parsed = parse_minutes_md(text)
    pledges = [a for a in parsed.appearances if a.role == "pledge"]
    assert len(pledges) == 1
    assert pledges[0].person.full_name == "Madison Pritchard"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py -k "pledge" -v`
Expected: FAIL — `test_pledge_award_title_header_is_not_captured` fails (the award header is captured).

- [ ] **Step 3: Gate the pledge branch**

In `catalog/ingest/bcsd/minutes_md.py`, replace the pledge branch (lines 132-142) — currently:

```python
        # Pledge leader: the #### sub-item under a PLEDGE OF ALLEGIANCE section.
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
```

with:

```python
        # Pledge leader: a #### sub-item under PLEDGE OF ALLEGIANCE, but only when the
        # header is a plain name — award-title headers ("Little Miss and Mr. … 2024:
        # Name, School; …") are not people and are dropped.
        if "PLEDGE OF ALLEGIANCE" in section and s.startswith("#### "):
            item_m = _ITEM_HEADER.match(s)
            if item_m:
                raw = html.unescape(item_m["rest"].strip())
                name = normalize_name(raw)
                if looks_like_name(name):
                    appearances.append(
                        ParsedAppearance(
                            person=ParsedPerson(full_name=name, raw_name=raw),
                            role="pledge",
                        )
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py -v`
Expected: PASS (all).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/ingest/bcsd/minutes_md.py catalog/tests/test_bcsd_minutes_md.py
git commit -m "fix(ingest): drop non-name pledge award-title headers"
```

---

## Task 4: Invocation apposition — recover the real name

**Files:**
- Modify: `catalog/ingest/bcsd/minutes_md.py` (add `_resolve_apposition_name`; change the invocation branch at lines 123-130)
- Test: `catalog/tests/test_bcsd_minutes_md.py` (append; reuses `_minutes`)

- [ ] **Step 1: Write the failing tests**

Append to `catalog/tests/test_bcsd_minutes_md.py`:

```python
def test_invocation_apposition_recovers_real_name():
    text = _minutes(
        "### IV. INVOCATION\n\nThe invocation was given by Board member, Dr. Juawn Jackson.\n"
    )
    parsed = parse_minutes_md(text)
    inv = [a for a in parsed.appearances if a.role == "invocation"]
    assert len(inv) == 1
    assert inv[0].person.full_name == "Juawn Jackson"


def test_invocation_keeps_name_before_affiliation():
    text = _minutes(
        "### IV. INVOCATION\n\n"
        "The invocation was given by Reverend Kenneth Moye, Washington Avenue Presbyterian Church.\n"
    )
    parsed = parse_minutes_md(text)
    inv = [a for a in parsed.appearances if a.role == "invocation"]
    assert len(inv) == 1
    assert inv[0].person.full_name == "Kenneth Moye"


def test_invocation_all_prose_is_skipped():
    text = _minutes(
        "### IV. INVOCATION\n\nThe invocation was given by a member of the community.\n"
    )
    parsed = parse_minutes_md(text)
    assert [a for a in parsed.appearances if a.role == "invocation"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py -k "invocation" -v`
Expected: FAIL — `test_invocation_apposition_recovers_real_name` yields "Board member", and the all-prose case still appends.

- [ ] **Step 3: Add the helper and gate the invocation branch**

In `catalog/ingest/bcsd/minutes_md.py`, add a module-level helper just above `_parse_appearances` (after `_parse_roster`):

```python
def _resolve_apposition_name(raw: str) -> str:
    """From an invocation 'given by X' string, return the first comma-segment that
    normalizes to a name-shaped value, else "". Recovers 'Juawn Jackson' from
    'Board member, Dr. Juawn Jackson'; keeps 'Kenneth Moye' from 'Reverend Kenneth
    Moye, <church>'; returns "" when no segment is a name."""
    for seg in raw.split(","):
        name = normalize_name(seg)
        if looks_like_name(name):
            return name
    return ""
```

Then replace the invocation branch (lines 123-130) — currently:

```python
        if inv:
            raw = html.unescape(inv["name"].strip())
            appearances.append(
                ParsedAppearance(
                    person=ParsedPerson(full_name=normalize_name(raw), raw_name=raw),
                    role="invocation",
                )
            )
```

with:

```python
        if inv:
            raw = html.unescape(inv["name"].strip())
            name = _resolve_apposition_name(raw)
            if name:
                appearances.append(
                    ParsedAppearance(
                        person=ParsedPerson(full_name=name, raw_name=raw),
                        role="invocation",
                    )
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py -v`
Expected: PASS (all).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/ingest/bcsd/minutes_md.py catalog/tests/test_bcsd_minutes_md.py
git commit -m "fix(ingest): resolve invocation Role,Name apposition to the real person"
```

---

## Task 5: `prune_orphans` management command

**Files:**
- Create: `catalog/management/commands/prune_orphans.py`
- Test: `tests/test_prune_orphans.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prune_orphans.py`:

```python
"""prune_orphans deletes edge-less proposal nodes (Persons / vendor Organizations)
with zero facts and zero relationships. Dry-run unless --apply. Bodies and connected
entities are never deleted."""

import datetime

import pytest
from django.core.management import call_command

from catalog.models import (
    Appearance,
    Jurisdiction,
    Meeting,
    Organization,
    Person,
)


@pytest.fixture
def mixed(db):
    jur = Jurisdiction.objects.create(name="Bibb", slug="bibb")
    body = Organization.objects.create(
        name="BOE", slug="boe", jurisdiction=jur, kind=Organization.Kind.COMMITTEE
    )
    meeting = Meeting.objects.create(body=body, jurisdiction=jur, date=datetime.date(2025, 5, 15), slug="m1")
    connected = Person.objects.create(full_name="Henry Ficklin", slug="henry")
    Appearance.objects.create(person=connected, meeting=meeting, role=Appearance.Role.MEMBER)
    orphan_person = Person.objects.create(full_name="They were:", slug="they-were")
    orphan_vendor = Organization.objects.create(
        name="Stale Vendor", slug="stale-vendor", jurisdiction=None, kind=Organization.Kind.COMPANY
    )
    return {
        "body": body,
        "connected": connected,
        "orphan_person": orphan_person,
        "orphan_vendor": orphan_vendor,
    }


@pytest.mark.django_db
def test_dry_run_deletes_nothing(mixed):
    call_command("prune_orphans")  # no --apply
    assert Person.objects.filter(pk=mixed["orphan_person"].pk).exists()
    assert Organization.objects.filter(pk=mixed["orphan_vendor"].pk).exists()


@pytest.mark.django_db
def test_apply_deletes_only_orphans(mixed):
    call_command("prune_orphans", apply=True)
    # orphans gone
    assert not Person.objects.filter(pk=mixed["orphan_person"].pk).exists()
    assert not Organization.objects.filter(pk=mixed["orphan_vendor"].pk).exists()
    # connected person and the body survive
    assert Person.objects.filter(pk=mixed["connected"].pk).exists()
    assert Organization.objects.filter(pk=mixed["body"].pk).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prune_orphans.py -v`
Expected: FAIL — `CommandError: Unknown command: 'prune_orphans'`.

- [ ] **Step 3: Create the command**

Create `catalog/management/commands/prune_orphans.py`:

```python
"""Delete edge-less proposal nodes left behind by re-ingestion or relationship
rebuilds: Persons with no facts/relationships, and vendor-kind Organizations with
no relationships or meetings. Dry-run by default; pass --apply to delete.

Only entities with ZERO connecting facts are eligible, so deletion strands nothing
(no citations, no edges). Bodies, schools, and jurisdiction-scoped orgs are never
considered — only the cross-agency vendor kinds.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Organization, Person, Relationship

VENDOR_KINDS = (
    Organization.Kind.COMPANY,
    Organization.Kind.NONPROFIT,
    Organization.Kind.CAMPAIGN,
)


def _related_ids(content_type):
    """Set of object PKs referenced by any Relationship as subject or object."""
    subj = Relationship.objects.filter(subject_ct=content_type).values_list("subject_id", flat=True)
    obj = Relationship.objects.filter(object_ct=content_type).values_list("object_id", flat=True)
    return set(subj) | set(obj)


def orphan_persons():
    person_ct = ContentType.objects.get_for_model(Person)
    in_rel = _related_ids(person_ct)
    return [
        p
        for p in Person.objects.all()
        if p.pk not in in_rel
        and not p.appearances.exists()
        and not p.votes.exists()
        and not p.motions_moved.exists()
        and not p.motions_seconded.exists()
    ]


def orphan_vendor_orgs():
    org_ct = ContentType.objects.get_for_model(Organization)
    in_rel = _related_ids(org_ct)
    return [
        o
        for o in Organization.objects.filter(kind__in=VENDOR_KINDS)
        if o.pk not in in_rel and not o.meetings.exists()
    ]


class Command(BaseCommand):
    help = "Delete edge-less proposal Persons and vendor Organizations (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete the orphans (default: dry-run, only report).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        persons = orphan_persons()
        orgs = orphan_vendor_orgs()
        for p in persons:
            self.stdout.write(f"  person  {p.full_name!r}")
        for o in orgs:
            self.stdout.write(f"  vendor  {o.name!r}")
        if options["apply"]:
            for p in persons:
                p.delete()
            for o in orgs:
                o.delete()
            self.stdout.write(
                self.style.SUCCESS(f"Deleted {len(persons)} persons and {len(orgs)} vendor orgs.")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: would delete {len(persons)} persons and {len(orgs)} vendor orgs. "
                    f"Pass --apply to delete."
                )
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prune_orphans.py -v`
Expected: PASS (both).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/management/commands/prune_orphans.py tests/test_prune_orphans.py
git commit -m "feat(catalog): add prune_orphans command for edge-less proposal nodes"
```

---

## Task 6: Full-suite verification + operational runbook

**Files:** none (verification + manual dev-data refresh).

- [ ] **Step 1: Run the entire test suite**

Run: `uv run pytest -q`
Expected: PASS — the prior count plus the new tests, no failures.

- [ ] **Step 2: Confirm lint + format are clean**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no findings.

- [ ] **Step 3: Refresh dev data (manual; mutates the dev DB)**

The fix changes parse output, so re-ingest the loaded meetings, preserving reviewed state, then prune:

```bash
docker compose up -d db
# Re-ingest the 17 loaded meetings (snapshot/restore reviewed state — same procedure
# used for the Phase 3 amount backfill), then:
uv run python manage.py build_relationships --review
uv run python manage.py prune_orphans            # dry-run: review what will be removed
uv run python manage.py prune_orphans --apply    # delete the now-edge-less junk Persons
```

Expected: the dry-run lists the prose "persons" (e.g. "They were:", "Four people addressed the Board for comments."); `--apply` removes them. The 2024-09-19 invocation now attaches to **Juawn Jackson** (an existing board member) rather than creating "Board member".

- [ ] **Step 4: Visual check of the graph**

Open `http://127.0.0.1:8011/graph/` and confirm no prose nodes remain and that the member/vendor topology is intact. Save a screenshot to the gitignored `screenshots/`.

---

## Self-review notes (for the implementer)

- **Spec coverage:** predicate → Task 1; visitor/pledge/invocation gates → Tasks 2/3/4 (invocation includes the apposition recovery); `prune_orphans` → Task 5; verification + runbook → Task 6. Every spec section maps to a task.
- **Order:** Task 2 adds the `looks_like_name` import to `minutes_md.py`; Tasks 3 and 4 rely on it already being imported. Do them in order.
- **Type/name consistency:** `looks_like_name(text) -> bool` and `_resolve_apposition_name(raw) -> str` are used with identical signatures everywhere. `orphan_persons()` / `orphan_vendor_orgs()` return lists of model instances.
- **Watch:** the minutes tests build minimal inline text via the `_minutes()` helper and assert on `parsed.appearances` filtered by `role`; they do not need fixture files. Confirm the `_minutes` helper is added once (Task 2) and reused by Tasks 3-4 in the same file.
