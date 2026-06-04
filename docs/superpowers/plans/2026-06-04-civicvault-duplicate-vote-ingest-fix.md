# Duplicate-Vote Ingest Fix (minutes header-depth) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the BCSD minutes parser attach every roll call to the correct `AgendaItem`, eliminating the archive-wide duplicate-vote `IntegrityError` (23 of 539 meetings) and the silent vote-misattribution behind it.

**Architecture:** Broaden one regex (`_ITEM_HEADER`) in `catalog/ingest/bcsd/minutes_md.py` to recognize 4-or-more-hash item headers and MultiMarkdown backslash-escaped ordinals, so nested action sub-items own their own roll-call blocks. Add a parse-time fail-loud guard against a repeated voter in a single item. Prove correctness with new fixtures, a guard test, an end-to-end ingest test, and a local archive-wide regression sweep (skipped when `archive_data/` is absent, e.g. in CI).

**Tech Stack:** Python 3.12, Django, pytest / pytest-django, `uv` for all Python execution, `ruff` for lint/format.

**Design source:** [`../specs/2026-06-04-civicvault-duplicate-vote-ingest-fix-design.md`](../specs/2026-06-04-civicvault-duplicate-vote-ingest-fix-design.md)

**Pre-flight (run once before Task 1):**
```bash
docker compose up -d db
uv run pytest -q          # expect a green baseline before changing anything
```

> **Shell-quoting warning for any ad-hoc regex probe:** never test a regex containing `\\?` through `bash -c "..."` — the double-quote layer mangles the backslash and gives misleading results. Put probe code in a `.py` file run from the repo root (`uv run python file.py`) so the regex is exactly what Python sees.

---

### Task 1: Add the bug-reproducing fixture

**Files:**
- Create: `catalog/tests/fixtures/bcsd/personnel/event.md`
- Create: `catalog/tests/fixtures/bcsd/personnel/minutes.md`

This synthetic committee meeting reproduces all three nesting layers in one fixture: a four-hash `Executive Session` item (two unanimous, un-rolled motions), two five-hash action sub-items (`PS-1`, `PS-2`) that each carry their own roll call, and a five-hash `PS-3` whose roll calls live in six-hash, **backslash-escaped-ordinal** appointment sub-items (one of which has an abstention — the per-decision signal the coarse parse destroyed). Five voters keep counts unambiguous.

- [ ] **Step 1: Create `catalog/tests/fixtures/bcsd/personnel/event.md`**

```markdown
# Committee Meeting

- **Meeting ID:** 999001
- **Date / Time:** 06/19/2025 - 04:00 PM
- **Meeting Type:** Committee Meeting
- **Source URL:** https://simbli.eboardsolutions.com/SB_Meetings/ViewMeeting.aspx?S=4013&MID=999001
- **Folder:** `2025-06-19_1600_committee-meeting_mid-999001`
- **Agenda Saved:** yes
- **Minutes Saved:** yes
- **Attachments Downloaded:** 0

## Agenda Items

- I. Call to Order
- II. PERSONNEL SERVICES COMMITTEE
- i. Executive Session for Personnel Matters
- a. PS-1 Certified Personnel Report (ACTION)
- b. PS-2 Classified Personnel Report (ACTION)
- c. PS-3 Administrative Appointments (ACTION)
- 1. Director of Research
- 2. Assistant Principal Southfield
- III. Adjourn

## Files
```

- [ ] **Step 2: Create `catalog/tests/fixtures/bcsd/personnel/minutes.md`**

```markdown
# Committee Meeting \| 06/19/2025 - 04:00 PM

## Meeting Minutes

### Attendance

#### Voting Members

- Ms. Alice Adams, President
- Mr. Bob Brown, Vice President
- Mrs. Carla Cruz, Treasurer
- Dr. Dan Davis, Board Member
- Mr. Eve Evans, Board Member

### I. Call to Order

The meeting was called to order at 4 p.m.

### II. PERSONNEL SERVICES COMMITTEE

#### i. Executive Session for Personnel Matters

The Board voted unanimously to enter Executive Session at 4:10 p.m.

Motion made by: Mr. Bob Brown

Motion seconded by: Mrs. Carla Cruz

Voting: Unanimously Approved

The Board voted unanimously to return from Executive Session at 5:00 p.m.

Motion made by: Mrs. Carla Cruz

Motion seconded by: Dr. Dan Davis

Voting: Unanimously Approved

##### a. PS-1 Certified Personnel Report (ACTION)

A motion was made to approve PS-1 as presented.

- Motion made by: Mr. Bob Brown
- Motion seconded by: Dr. Dan Davis

_Voting results:_

- Yes: Ms. Alice Adams
- Yes: Mr. Bob Brown
- Yes: Mrs. Carla Cruz
- Yes: Dr. Dan Davis
- Yes: Mr. Eve Evans

##### b. PS-2 Classified Personnel Report (ACTION)

A motion was made to approve PS-2 as presented.

- Motion made by: Dr. Dan Davis
- Motion seconded by: Mr. Bob Brown

_Voting results:_

- Yes: Ms. Alice Adams
- Yes: Mr. Bob Brown
- Yes: Mrs. Carla Cruz
- Yes: Dr. Dan Davis
- Yes: Mr. Eve Evans

##### c. PS-3 Administrative Appointments (ACTION)

###### 1\. Director of Research

_Voting results:_

- Yes: Ms. Alice Adams
- Yes: Mr. Bob Brown
- Yes: Mrs. Carla Cruz
- Yes: Dr. Dan Davis
- Yes: Mr. Eve Evans

###### 2\. Assistant Principal Southfield

_Voting results:_

- Yes: Ms. Alice Adams
- Yes: Mr. Bob Brown
- Yes: Mrs. Carla Cruz
- Yes: Dr. Dan Davis
- Abstain: Mr. Eve Evans

### III. Adjourn

The meeting was adjourned at 5:05 p.m.
```

- [ ] **Step 3: Commit**

```bash
git add catalog/tests/fixtures/bcsd/personnel/
git commit -m "test: add personnel fixture reproducing nested-roll-call duplicate-vote bug"
```

---

### Task 2: Five-hash recognition — separate PS-1 / PS-2 roll calls

**Files:**
- Modify: `catalog/ingest/bcsd/minutes_md.py:12`
- Test: `catalog/tests/test_bcsd_minutes_md.py`

- [ ] **Step 1: Write the failing test**

Append to `catalog/tests/test_bcsd_minutes_md.py`:

```python
def test_personnel_five_hash_subitems_separate_roll_calls():
    parsed = parse_minutes_md(fixture_text("personnel", "minutes.md"))

    ps1 = parsed.outcomes["PS-1"]
    ps2 = parsed.outcomes["PS-2"]
    assert len(ps1.votes) == 5
    assert len(ps2.votes) == 5
    assert all(v.value == "yea" for v in ps1.votes)

    # The four-hash Executive Session item keeps only its two un-rolled motions;
    # the PS roll calls must NOT have been absorbed into it.
    exec_item = parsed.outcomes["Executive Session for Personnel Matters"]
    assert len(exec_item.votes) == 0
    assert len(exec_item.motions) == 2
    assert exec_item.outcome_status == "unanimous"

    # PS-1 and PS-2 each carry their own single roll call (no duplicate voter).
    for code in ("PS-1", "PS-2"):
        names = [v.person.full_name for v in parsed.outcomes[code].votes]
        assert len(names) == len(set(names)), f"duplicate voter in {code}"
```

> Note: the *global* "no duplicate voter in ANY outcome" invariant is asserted in Task 3, not here — PS-3's six-hash escaped-ordinal appointments still merge until Task 3's change, so a global check would fail at this stage. Task 2 only asserts the items its five-hash fix governs.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py::test_personnel_five_hash_subitems_separate_roll_calls -v`
Expected: FAIL — `KeyError: 'PS-1'` (its roll call is currently absorbed into the Executive Session block, which instead holds 10 duplicated votes).

- [ ] **Step 3: Broaden the header regex to four-or-more hashes**

In `catalog/ingest/bcsd/minutes_md.py`, change line 12 from:

```python
_ITEM_HEADER = re.compile(r"^####\s+(?:[ivxlc]+|[a-z]|\d+)\.\s+(?P<rest>.+?)\s*$")
```

to:

```python
_ITEM_HEADER = re.compile(r"^#{4,}\s+(?:[ivxlc]+|[a-z]|\d+)\.\s+(?P<rest>.+?)\s*$")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py::test_personnel_five_hash_subitems_separate_roll_calls -v`
Expected: PASS

- [ ] **Step 5: Run the existing minutes tests to confirm no regression**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py -v`
Expected: PASS for all — the fix only *adds* (empty) outcome entries for previously-absorbed sub-items; FSS-3, FSS-8, PR-2, and the board roll-call anchors are unchanged.

- [ ] **Step 6: Commit**

```bash
git add catalog/ingest/bcsd/minutes_md.py catalog/tests/test_bcsd_minutes_md.py
git commit -m "fix(ingest): recognize 4+-hash minutes sub-items so nested roll calls separate"
```

---

### Task 3: Escaped-ordinal recognition — six-hash appointment roll calls

**Files:**
- Modify: `catalog/ingest/bcsd/minutes_md.py:12`
- Test: `catalog/tests/test_bcsd_minutes_md.py`

The `PS-3` appointment sub-items use MultiMarkdown escaped ordinals (`###### 1\. …`). After Task 2 these six-hash headers are at a recognized depth, but `\d+\.` still fails to match `1\.`, so their roll calls remain merged under `PS-3`. This task tolerates the escaped dot.

- [ ] **Step 1: Write the failing test**

Append to `catalog/tests/test_bcsd_minutes_md.py`:

```python
def test_personnel_six_hash_escaped_ordinal_appointments_separate():
    parsed = parse_minutes_md(fixture_text("personnel", "minutes.md"))

    director = parsed.outcomes["Director of Research"]
    asst = parsed.outcomes["Assistant Principal Southfield"]
    assert len(director.votes) == 5
    assert all(v.value == "yea" for v in director.votes)

    # The abstention on the second appointment must survive as its own roll call —
    # this per-decision difference is the signal the coarse parse destroyed.
    assert len(asst.votes) == 5
    assert sum(1 for v in asst.votes if v.value == "abstain") == 1
    abstainer = next(v for v in asst.votes if v.value == "abstain")
    assert abstainer.person.full_name == "Eve Evans"

    # PS-3's own block is now empty (its roll calls moved to the appointments).
    assert len(parsed.outcomes["PS-3"].votes) == 0

    # Global invariant — now satisfiable: NO agenda item contains the same voter
    # twice anywhere in the fixture.
    for oc in parsed.outcomes.values():
        names = [v.person.full_name for v in oc.votes]
        assert len(names) == len(set(names)), f"duplicate voter in {oc.code or oc.title!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py::test_personnel_six_hash_escaped_ordinal_appointments_separate -v`
Expected: FAIL — `KeyError: 'Director of Research'` (the appointment roll calls are still merged under `PS-3`, which holds 10 duplicated votes).

- [ ] **Step 3: Tolerate the backslash-escaped ordinal dot**

In `catalog/ingest/bcsd/minutes_md.py`, change line 12 from:

```python
_ITEM_HEADER = re.compile(r"^#{4,}\s+(?:[ivxlc]+|[a-z]|\d+)\.\s+(?P<rest>.+?)\s*$")
```

to:

```python
_ITEM_HEADER = re.compile(r"^#{4,}\s+(?:[ivxlc]+|[a-z]|\d+)\\?\.\s+(?P<rest>.+?)\s*$")
```

(The `\\?` matches an optional literal backslash before the ordinal dot, so both `1.` and `1\.` are recognized.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py::test_personnel_six_hash_escaped_ordinal_appointments_separate -v`
Expected: PASS

- [ ] **Step 5: Run the full minutes + adapter test modules**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py catalog/tests/test_bcsd_adapter.py -v`
Expected: PASS for all.

- [ ] **Step 6: Commit**

```bash
git add catalog/ingest/bcsd/minutes_md.py catalog/tests/test_bcsd_minutes_md.py
git commit -m "fix(ingest): tolerate MultiMarkdown escaped ordinals in minutes headers"
```

---

### Task 4: Fail-loud guard against a repeated voter

**Files:**
- Modify: `catalog/ingest/bcsd/minutes_md.py` (in `parse_minutes_md`, after `parse_outcome_block` returns)
- Test: `catalog/tests/test_bcsd_minutes_md.py`

With the regex fix nothing in the archive trips this guard; it is insurance against a future minutes layout that nests roll calls at an unforeseen depth. It must fail loudly at parse time (whole meeting) with a clear, named error — not silently, and not as a downstream DB `IntegrityError`.

- [ ] **Step 1: Write the failing test**

First, add `import pytest` to the **top** of `catalog/tests/test_bcsd_minutes_md.py` (above the existing `from catalog...` imports) so the import stays at module level and ruff does not flag E402. Then append this test function to the end of the file:

```python
def test_repeated_voter_in_one_item_raises():
    # A single item whose block contains two roll calls naming the same person —
    # the malformed shape the guard must catch.
    text = """## Meeting Minutes

### Attendance

#### Voting Members

- Ms. Alice Adams, President
- Mr. Bob Brown, Board Member

### IV. SOME COMMITTEE

#### i. SC-1 Some Action

_Voting results:_

- Yes: Ms. Alice Adams
- Yes: Mr. Bob Brown

_Voting results:_

- Yes: Ms. Alice Adams
- Yes: Mr. Bob Brown
"""
    with pytest.raises(ValueError, match=r"Duplicate vote for 'Alice Adams'"):
        parse_minutes_md(text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py::test_repeated_voter_in_one_item_raises -v`
Expected: FAIL — no exception raised (the parser currently produces an outcome with two `Alice Adams` votes instead of raising).

- [ ] **Step 3: Add the guard in `parse_minutes_md`**

In `catalog/ingest/bcsd/minutes_md.py`, locate the loop body in `parse_minutes_md` immediately after:

```python
        otext, motions, votes = parse_outcome_block(block_lines)
        status = _derive_status(otext, motions)
        key = code or title
```

Insert this guard directly after that `key = code or title` line and before the `outcomes[key] = ItemOutcome(...)` assignment:

```python
        seen_voters: set[str] = set()
        for v in votes:
            if v.person.full_name in seen_voters:
                raise ValueError(
                    f"Duplicate vote for {v.person.full_name!r} within agenda item "
                    f"{key!r}: the minutes nest multiple roll calls under one item "
                    f"header at a depth the parser did not separate. Fix the source "
                    f"layout or extend _ITEM_HEADER."
                )
            seen_voters.add(v.person.full_name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py::test_repeated_voter_in_one_item_raises -v`
Expected: PASS

- [ ] **Step 5: Confirm the personnel fixture still parses cleanly (guard does not false-trip)**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py -v`
Expected: PASS for all (the personnel fixture has no repeated voter after the regex fix).

- [ ] **Step 6: Commit**

```bash
git add catalog/ingest/bcsd/minutes_md.py catalog/tests/test_bcsd_minutes_md.py
git commit -m "fix(ingest): fail loud on a repeated voter within one agenda item"
```

---

### Task 5: End-to-end ingest test (loader no longer raises; votes correctly attributed)

**Files:**
- Test: `catalog/tests/test_ingest_bcsd_command.py`

Proves the whole pipeline: the personnel folder ingests without the `uniq_vote_person_item` `IntegrityError`, and PS-1/PS-2/appointment votes land on their own items — not on Executive Session.

- [ ] **Step 1: Write the failing test**

Append to `catalog/tests/test_ingest_bcsd_command.py`:

```python
@pytest.mark.django_db
def test_command_ingests_nested_personnel_without_duplicate_votes(tmp_path):
    folder_name = "2025-06-19_1600_committee-meeting_mid-999001"
    dst = tmp_path / "BCSD_BOE_MEETINGS" / "2025" / "06" / folder_name
    dst.mkdir(parents=True)
    for fname in ("event.md", "minutes.md"):
        shutil.copy(FIXTURES_DIR / "personnel" / fname, dst / fname)

    # Must not raise the duplicate-vote IntegrityError.
    call_command("ingest_bcsd", str(dst))

    meeting = Meeting.objects.get(source_meeting_id="999001")

    ps1 = AgendaItem.objects.get(meeting=meeting, code="PS-1")
    ps2 = AgendaItem.objects.get(meeting=meeting, code="PS-2")
    assert Vote.objects.filter(agenda_item=ps1).count() == 5
    assert Vote.objects.filter(agenda_item=ps2).count() == 5

    # Executive Session keeps its motions and carries NO votes.
    exec_item = AgendaItem.objects.get(meeting=meeting, title="Executive Session for Personnel Matters")
    assert Vote.objects.filter(agenda_item=exec_item).count() == 0
    assert Motion.objects.filter(agenda_item=exec_item).count() == 2

    # Appointment roll calls attach to the appointment items; the abstention survives.
    director = AgendaItem.objects.get(meeting=meeting, title="Director of Research")
    asst = AgendaItem.objects.get(meeting=meeting, title="Assistant Principal Southfield")
    assert Vote.objects.filter(agenda_item=director).count() == 5
    assert Vote.objects.filter(agenda_item=asst, value=Vote.Value.ABSTAIN).count() == 1

    # 5 + 5 + 5 + 5 = 20 votes total; none lost, none duplicated.
    assert Vote.objects.filter(agenda_item__meeting=meeting).count() == 20
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest catalog/tests/test_ingest_bcsd_command.py::test_command_ingests_nested_personnel_without_duplicate_votes -v`
Expected: PASS (Tasks 2–4 already fixed the parser; this is the integration proof). If it fails with an `IntegrityError`, the parser fix is incomplete — stop and revisit Tasks 2–3.

- [ ] **Step 3: Commit**

```bash
git add catalog/tests/test_ingest_bcsd_command.py
git commit -m "test(ingest): end-to-end personnel meeting ingests with correct vote attribution"
```

---

### Task 6: Archive-wide regression sweep (local; skipped when archive absent)

**Files:**
- Create: `catalog/tests/test_minutes_archive_sweep.py`

Freezes the measured invariant — across every real `minutes.md`, **zero** agenda items with a duplicate voter and **zero** vote-bearing minutes outcomes that join to no event item. `archive_data/` is gitignored, so the test skips cleanly where it is absent (CI) and runs as a developer regression gate locally.

- [ ] **Step 1: Write the sweep test**

Create `catalog/tests/test_minutes_archive_sweep.py`:

```python
"""Local regression gate: parse every real BCSD minutes.md and assert the parser
attaches every roll call correctly. archive_data/ is gitignored, so this skips
cleanly when the archive is unavailable (e.g. CI)."""

from collections import Counter
from pathlib import Path
from unittest import mock

import pytest

from catalog.ingest.bcsd import adapter as bcsd_adapter
from catalog.ingest.bcsd.adapter import parse_meeting_folder
from catalog.ingest.bcsd.minutes_md import parse_minutes_md

_ARCHIVE = Path(__file__).resolve().parents[2] / "archive_data" / "bcsd" / "BCSD_BOE_MEETINGS"


def _meeting_folders():
    if not _ARCHIVE.is_dir():
        return []
    return sorted(p.parent for p in _ARCHIVE.rglob("minutes.md"))


@pytest.mark.skipif(not _ARCHIVE.is_dir(), reason="archive_data/ not present (gitignored; CI)")
def test_no_meeting_has_duplicate_or_dropped_votes():
    folders = _meeting_folders()
    assert folders, "archive present but no minutes.md found"

    dup_items, dropped = [], []
    # Skip slow PDF text-extraction — only the event.md<->minutes.md join matters here.
    with mock.patch.object(bcsd_adapter, "extract_pdf_text", lambda p: ("", "unknown")):
        for folder in folders:
            parsed = parse_meeting_folder(folder)

            # (1) No materialized agenda item may contain the same voter twice.
            for item in parsed.agenda_items:
                names = [v.person.full_name for v in item.votes]
                if any(c > 1 for c in Counter(names).values()):
                    dup_items.append((folder.name, item.code or item.title))

            # (2) No vote-bearing minutes outcome may fail to join an event item
            # (which would silently drop those votes).
            mins = parse_minutes_md((folder / "minutes.md").read_text(encoding="utf-8"))
            joined = set()
            for item in parsed.agenda_items:
                joined.add(item.code)
                joined.add(item.title)
            for key, oc in mins.outcomes.items():
                if oc.votes and key not in joined:
                    dropped.append((folder.name, key, len(oc.votes)))

    assert not dup_items, f"duplicate-voter items: {dup_items[:10]}"
    assert not dropped, f"dropped vote-bearing outcomes: {dropped[:10]}"
```

- [ ] **Step 2: Run the sweep**

Run: `uv run pytest catalog/tests/test_minutes_archive_sweep.py -v`
Expected (locally, archive present): PASS — `test_no_meeting_has_duplicate_or_dropped_votes`.
Expected (no archive): SKIPPED with reason "archive_data/ not present".
If it FAILS, the reported `dup_items` / `dropped` lists name the offending meetings — investigate before proceeding (the fix is supposed to make both empty).

- [ ] **Step 3: Commit**

```bash
git add catalog/tests/test_minutes_archive_sweep.py
git commit -m "test(ingest): archive-wide sweep asserts no duplicate or dropped votes"
```

---

### Task 7: Refresh the stale limitation note; full suite + lint

**Files:**
- Modify: `catalog/ingest/bcsd/minutes_md.py:154-160` (the consent-anchor NOTE)
- Whole suite + ruff

- [ ] **Step 1: Rewrite the obsolete consent-anchor note**

In `catalog/ingest/bcsd/minutes_md.py`, the block-builder carries a NOTE (around lines 154-160) describing the old behavior where a sub-item's roll call was attached only to the first sub-item. Replace that NOTE comment with one that reflects the corrected behavior:

```python
        # NOTE — header depth: every "#{4,} <ordinal>. ..." line (including
        # MultiMarkdown escaped ordinals like "1\.") is its own item, so each
        # leaf sub-item owns its roll call and joins to its event.md counterpart
        # by code/title. A *genuine* consent-agenda anchor — one roll call that
        # approves several items en bloc under a single header — is still
        # attached only to that anchor item; that faithfully reflects the source
        # and is the intended behavior, not the duplicate-vote bug this fixed.
```

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -q`
Expected: all pass (the pre-flight baseline count plus the new tests; the archive sweep passes locally or skips in CI).

- [ ] **Step 3: Lint and format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean. If `format --check` reports diffs, run `uv run ruff format .` and re-run the check.

- [ ] **Step 4: Commit**

```bash
git add catalog/ingest/bcsd/minutes_md.py
git commit -m "docs(ingest): refresh minutes header-depth note to match corrected behavior"
```

---

### Task 8: Operator verification — load the real 2025-09-18 meeting

Not a code change. Confirms the fix on the real data that motivated it and restores `2025-09-18` to the dev demo set (it was swapped for `2025-05-15` while the bug was open). `archive_data/` is local-only, so this runs on the developer machine.

- [ ] **Step 1: Ingest the previously-failing meeting**

```bash
uv run python manage.py ingest_bcsd \
  archive_data/bcsd/BCSD_BOE_MEETINGS/2025/09/2025-09-18_1600_committee-meeting_mid-128424
```
Expected: completes without an `IntegrityError` / `ValueError`.

- [ ] **Step 2: Spot-check vote attribution in a shell**

```bash
uv run python manage.py shell -c "
from catalog.models import Meeting, AgendaItem, Vote
m = Meeting.objects.get(source_meeting_id='128424')
for code in ('PS-1','PS-2'):
    it = AgendaItem.objects.filter(meeting=m, code=code).first()
    print(code, '->', Vote.objects.filter(agenda_item=it).count(), 'votes' if it else 'MISSING')
exec_items = AgendaItem.objects.filter(meeting=m, title__icontains='Executive Session')
for it in exec_items:
    print('ExecSession votes:', Vote.objects.filter(agenda_item=it).count())
"
```
Expected: `PS-1` and `PS-2` each report their own roll-call votes; the Executive Session item reports `0` votes.

- [ ] **Step 3: Re-derive relationships so the graph reflects the now-loadable meeting**

```bash
uv run python manage.py build_relationships --review
```
Expected: succeeds; the contract/board-member edge counts may rise now that 2025-09-18 is loaded.

- [ ] **Step 4: Final confirmation**

```bash
uv run pytest -q && uv run ruff check .
```
Expected: green. The branch now carries the complete fix.

---

## Self-Review

- **Spec coverage:**
  - "Broaden `_ITEM_HEADER` to `#{4,}` + escaped ordinal" → Tasks 2 & 3.
  - "Fail-loud repeated-voter guard, whole-meeting" → Task 4.
  - "Each leaf joins by code/title; data-shape splits deep items" → verified by Task 5 (appointment items materialize with their own votes) and Task 6 (no dropped votes).
  - "Unit fixtures for Personnel/Exec-Session and escaped-ordinal patterns" → Task 1 fixture + Tasks 2/3 tests.
  - "Guard test" → Task 4.
  - "539-meeting sweep, skip-if-absent, 0 dup / 0 dropped" → Task 6.
  - "End-to-end load of 2025-09-18; restore to demo set" → Task 8 (and Task 5 proves the mechanism on a committed fixture, since 2025-09-18 itself is gitignored).
  - "Rewrite stale consent-anchor note" → Task 7.
  - "No model/migration/loader change" → honored; only `minutes_md.py` + tests/fixtures touched.
- **Placeholder scan:** none — every step carries concrete fixture text, test code, the exact regex, and exact commands.
- **Type/identifier consistency:** `parse_minutes_md`, `parse_meeting_folder`, `_ITEM_HEADER`, `ItemOutcome.votes/.motions/.outcome_status/.code/.title`, `fixture_text`, `FIXTURES_DIR`, `Vote.Value.ABSTAIN`, `source_meeting_id="999001"`, and fixture titles ("Executive Session for Personnel Matters", "Director of Research", "Assistant Principal Southfield") are used identically across the fixture, the unit tests, and the e2e test.
