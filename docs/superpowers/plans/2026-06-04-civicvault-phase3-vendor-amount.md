# Phase 3 (finish): Vendor Normalization + Amount Capture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture contract dollar amounts as structured `AgendaItem` fields at ingest time, and collapse vendor-name variants into one canonical `Organization` node, so the influence graph's contract layer is trustworthy and complete.

**Architecture:** Move two responsibilities out of `build_relationships`' graph-time regexing and into the ingest pipeline. Amount: a pure `extract_amount()` in the minutes parser populates new IR fields that flow parser → adapter → loader → `AgendaItem.amount`/`.amount_text`. Vendor: a new pure module `catalog/ingest/orgs.py` (mirroring `names.py`) canonicalizes names via a normalized key + curated alias map, with a pure-Python similarity pass that only *proposes* merges; `build_relationships` reads the structured amount and uses the canonicalizer.

**Tech Stack:** Python 3 / Django, `pytest` + `pytest-django`, `uv` for all Python invocation, `ruff` for lint/format. No new external dependencies.

**Spec:** [`docs/superpowers/specs/2026-06-04-civicvault-phase3-vendor-amount-design.md`](../specs/2026-06-04-civicvault-phase3-vendor-amount-design.md)

**Conventions for every task:**
- Run Python only via `uv run …` (never system python). Lint with `uv run ruff check .` and `uv run ruff format .` before each commit.
- `docker compose up -d db` must be running (Postgres on host port 5433) for any test that hits the DB.
- Commit on this branch (`feat/phase3-vendor-amount`); **never** push and **never** merge to `main` without an explicit ask. Conventional Commits.
- Tests live in `catalog/tests/` (parser/model/unit) and `tests/` (command/integration), matching the existing split.

---

## Task 1: Add `amount` + `amount_text` fields to `AgendaItem`

**Files:**
- Modify: `catalog/models/meeting.py` (the `AgendaItem` model, after `outcome_status` at line 100)
- Create (generated): `catalog/migrations/0014_agendaitem_amount.py`
- Test: `catalog/tests/test_meeting_amount.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_meeting_amount.py`:

```python
"""AgendaItem carries an optional structured contract amount + verbatim phrase."""

from decimal import Decimal

import pytest

from catalog.models import AgendaItem, Jurisdiction, Meeting, Organization


@pytest.mark.django_db
def test_agendaitem_stores_amount_and_phrase():
    jur = Jurisdiction.objects.create(name="Bibb", slug="bibb")
    body = Organization.objects.create(
        name="BOE", slug="boe", jurisdiction=jur, kind=Organization.Kind.COMMITTEE
    )
    meeting = Meeting.objects.create(body=body, jurisdiction=jur, date="2025-05-15", slug="m1")
    item = AgendaItem.objects.create(
        meeting=meeting,
        order=1,
        title="Renewal of Amira Learning",
        amount=Decimal("255300.00"),
        amount_text="in an amount not to exceed $255,300.00",
    )
    item.refresh_from_db()
    assert item.amount == Decimal("255300.00")
    assert item.amount_text == "in an amount not to exceed $255,300.00"


@pytest.mark.django_db
def test_agendaitem_amount_defaults_to_null():
    jur = Jurisdiction.objects.create(name="Bibb", slug="bibb")
    body = Organization.objects.create(
        name="BOE", slug="boe", jurisdiction=jur, kind=Organization.Kind.COMMITTEE
    )
    meeting = Meeting.objects.create(body=body, jurisdiction=jur, date="2025-05-15", slug="m1")
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="Policy Review")
    item.refresh_from_db()
    assert item.amount is None
    assert item.amount_text == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest catalog/tests/test_meeting_amount.py -v`
Expected: FAIL — `TypeError`/`FieldError` (AgendaItem has no `amount`).

- [ ] **Step 3: Add the fields**

In `catalog/models/meeting.py`, inside `class AgendaItem`, immediately after the `outcome_status` field (currently ending at line 100), add:

```python
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    amount_text = models.CharField(max_length=255, blank=True)
```

- [ ] **Step 4: Generate and review the migration**

Run: `uv run python manage.py makemigrations catalog`
Expected: creates `catalog/migrations/0014_agendaitem_amount.py` adding two fields. Open it and confirm it only `AddField`s `amount` and `amount_text` to `agendaitem` (no unintended changes).

- [ ] **Step 5: Apply the migration and run the test**

Run: `uv run python manage.py migrate catalog && uv run pytest catalog/tests/test_meeting_amount.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/models/meeting.py catalog/migrations/0014_agendaitem_amount.py catalog/tests/test_meeting_amount.py
git commit -m "feat(catalog): add structured amount + amount_text to AgendaItem"
```

---

## Task 2: Add `amount` + `amount_text` to the `ParsedAgendaItem` IR

**Files:**
- Modify: `catalog/ingest/ir.py` (imports at line 9; `ParsedAgendaItem` at lines 44-56)
- Test: `catalog/tests/test_ir_amount.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_ir_amount.py`:

```python
"""ParsedAgendaItem carries an optional Decimal amount + verbatim phrase."""

from decimal import Decimal

from catalog.ingest.ir import ParsedAgendaItem


def test_parsed_agenda_item_defaults_have_no_amount():
    item = ParsedAgendaItem(
        order=1, code="FSS-3", title="x", item_type="action", reading_stage="", section="S"
    )
    assert item.amount is None
    assert item.amount_text == ""


def test_parsed_agenda_item_accepts_amount():
    item = ParsedAgendaItem(
        order=1,
        code="FSS-3",
        title="x",
        item_type="action",
        reading_stage="",
        section="S",
        amount=Decimal("255300.00"),
        amount_text="in an amount not to exceed $255,300.00",
    )
    assert item.amount == Decimal("255300.00")
    assert item.amount_text == "in an amount not to exceed $255,300.00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest catalog/tests/test_ir_amount.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'amount'`.

- [ ] **Step 3: Add the fields to the IR**

In `catalog/ingest/ir.py`, change the import line 9 from:

```python
from dataclasses import dataclass
```

to:

```python
from dataclasses import dataclass
from decimal import Decimal
```

(If `import datetime` is the first import, keep ordering ruff-clean: `Decimal` import goes with the other stdlib imports; run `ruff format` in Step 5.)

Then in `class ParsedAgendaItem`, add two fields after `outcome_status: str = "none"` (line 53), keeping them among the defaulted fields:

```python
    amount: Decimal | None = None
    amount_text: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest catalog/tests/test_ir_amount.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/ingest/ir.py catalog/tests/test_ir_amount.py
git commit -m "feat(ingest): add amount + amount_text to ParsedAgendaItem IR"
```

---

## Task 3: `extract_amount()` in the minutes parser + `ItemOutcome` fields

**Files:**
- Modify: `catalog/ingest/bcsd/minutes_md.py` (imports lines 3-5; `ItemOutcome` lines 17-24; outcome assembly lines 171-191)
- Test: `catalog/tests/test_extract_amount.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_extract_amount.py`:

```python
"""extract_amount() captures a contract figure ONLY when a contract cue precedes it,
and preserves the verbatim phrase. Governance thresholds yield no amount."""

from decimal import Decimal

from catalog.ingest.bcsd.minutes_md import extract_amount


def test_in_the_amount_not_to_exceed():
    amt, phrase = extract_amount(
        "Approved the purchase in an amount not to exceed $255,500.00 to purchase desk shields."
    )
    assert amt == Decimal("255500.00")
    assert phrase == "in an amount not to exceed $255,500.00"


def test_in_the_amount_of():
    amt, phrase = extract_amount("Motion carried in the amount of $1,000.00.")
    assert amt == Decimal("1000.00")
    assert phrase == "in the amount of $1,000.00"


def test_annual_cost_not_to_exceed():
    amt, phrase = extract_amount(
        "Approved the Academy at an annual cost not to exceed $689,000.00 utilizing funds."
    )
    assert amt == Decimal("689000.00")
    assert "at an annual cost not to exceed $689,000.00" == phrase


def test_aggregate_amount():
    amt, _ = extract_amount(
        "Approved services in an aggregate amount not to exceed $1,190,822.00 for FY 2021-2022."
    )
    assert amt == Decimal("1190822.00")


def test_headline_figure_wins_over_parenthetical_breakdown():
    amt, _ = extract_amount(
        "Approved Elements in an amount not to exceed $439,500.00 "
        "(American Rescue Funds - $250,000.00 and local - $189,500.00)."
    )
    assert amt == Decimal("439500.00")


def test_governance_threshold_has_no_amount():
    assert extract_amount("No contract in excess of $150,000.00 without a proper bond.") == (
        None,
        "",
    )
    assert extract_amount("Surplus items valued less than $5,000.00 may be sold.") == (None, "")
    assert extract_amount("Purchases over $30,000 require board approval.") == (None, "")


def test_no_dollar_figure_at_all():
    assert extract_amount("Approved unanimously.") == (None, "")
    assert extract_amount("") == (None, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest catalog/tests/test_extract_amount.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_amount'`.

- [ ] **Step 3: Implement `extract_amount` and widen `ItemOutcome`**

In `catalog/ingest/bcsd/minutes_md.py`:

(a) Add the `Decimal` import. Change lines 3-5 from:

```python
import html
import re
from dataclasses import dataclass, field
```

to:

```python
import html
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
```

(b) Add the cue regex and function near the other module-level regexes (after line 14, the `_INVOCATION` definition):

```python
# A contract-amount cue immediately preceding a $ figure. Each cue may be followed
# by "of" or "not to exceed". Grounded in real BCSD outcome text; deliberately NOT
# broadened to generic phrasings (e.g. "for a total of") that appear in budget items.
_AMOUNT_CUE = re.compile(
    r"(?P<phrase>"
    r"(?:in\s+(?:the|an)\s+amount|at\s+a(?:n)?(?:\s+annual)?\s+cost|aggregate\s+amount)"
    r"(?:\s+(?:of|not\s+to\s+exceed))?"
    r"\s*\$\s*(?P<num>[\d,]+(?:\.\d{2})?))",
    re.IGNORECASE,
)


def extract_amount(outcome_text: str) -> tuple[Decimal | None, str]:
    """Return (figure, verbatim_phrase) for the FIRST contract-amount cue, else (None, "").

    Captures a dollar figure only when a contract-amount cue precedes it
    ("in the amount [not to exceed] of $X", "at an annual cost not to exceed $X",
    "aggregate amount of $X"). Governance thresholds ("contract in excess of
    $150,000") carry no cue and yield no amount. A trailing funding-source
    breakdown never overrides the headline value (the first match wins).
    """
    m = _AMOUNT_CUE.search(outcome_text or "")
    if not m:
        return None, ""
    try:
        value = Decimal(m.group("num").replace(",", ""))
    except InvalidOperation:
        return None, ""
    phrase = " ".join(m.group("phrase").split())[:255]
    return value, phrase
```

(c) Add `amount`/`amount_text` to `ItemOutcome`. Change the dataclass (lines 17-24) from:

```python
@dataclass(frozen=True)
class ItemOutcome:
    code: str
    title: str
    outcome_text: str
    outcome_status: str
    motions: tuple[ParsedMotion, ...]
    votes: tuple[ParsedVote, ...]
```

to:

```python
@dataclass(frozen=True)
class ItemOutcome:
    code: str
    title: str
    outcome_text: str
    outcome_status: str
    motions: tuple[ParsedMotion, ...]
    votes: tuple[ParsedVote, ...]
    amount: Decimal | None = None
    amount_text: str = ""
```

(d) Populate them where `ItemOutcome` is built. In `parse_minutes_md`, the block currently at lines 184-191 builds the outcome; change it from:

```python
        outcomes[key] = ItemOutcome(
            code=code,
            title=title,
            outcome_text=otext,
            outcome_status=status,
            motions=tuple(motions),
            votes=tuple(votes),
        )
```

to:

```python
        amount, amount_text = extract_amount(otext)
        outcomes[key] = ItemOutcome(
            code=code,
            title=title,
            outcome_text=otext,
            outcome_status=status,
            motions=tuple(motions),
            votes=tuple(votes),
            amount=amount,
            amount_text=amount_text,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest catalog/tests/test_extract_amount.py -v`
Expected: PASS (all cases).

- [ ] **Step 5: Confirm no parser regressions**

Run: `uv run pytest catalog/tests/test_bcsd_minutes_md.py -v`
Expected: PASS (existing minutes tests unaffected — `ItemOutcome` gained only defaulted fields).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/ingest/bcsd/minutes_md.py catalog/tests/test_extract_amount.py
git commit -m "feat(ingest): extract cue-anchored contract amount from minutes outcome text"
```

---

## Task 4: Flow the amount through the adapter into `ParsedAgendaItem`

**Files:**
- Modify: `catalog/ingest/bcsd/adapter.py` (the `ParsedAgendaItem(...)` construction at lines 137-149)
- Test: `catalog/tests/test_bcsd_adapter.py` (add one test; reuse existing fixtures)

- [ ] **Step 1: Write the failing test**

`catalog/tests/test_bcsd_adapter.py` already imports `datetime`, `parse_meeting_folder`, and the `_make_folder` helper, and the `committee` fixture's FSS-3 minutes outcome reads "… in an amount not to exceed $5,515,711.09." Add `from decimal import Decimal` to the import block, then append a test that runs the **real adapter join** and asserts the amount flows onto the item:

```python
def test_adapter_carries_cue_anchored_amount_through_join(tmp_path):
    folder = _make_folder(tmp_path, "committee", "2025-04-17_1600_committee-meeting_mid-124789")
    pm = parse_meeting_folder(folder)
    by_code = {it.code: it for it in pm.agenda_items if it.code}
    fss3 = by_code["FSS-3"]
    assert fss3.amount == Decimal("5515711.09")
    assert "not to exceed $5,515,711.09" in fss3.amount_text
    # An item whose outcome states no contract-cued figure carries no amount.
    assert all(
        it.amount is None for it in pm.agenda_items if it.code and not it.amount_text
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest catalog/tests/test_bcsd_adapter.py -k cue_anchored -v`
Expected: FAIL — `fss3.amount` is `None` (the adapter builds the item without passing the amount through).

- [ ] **Step 3: Wire the mapping in the adapter**

In `catalog/ingest/bcsd/adapter.py`, the `ParsedAgendaItem(...)` built at lines 137-149 currently ends:

```python
                motions=outcome.motions if outcome else (),
                votes=outcome.votes if outcome else (),
                file_names=_files_for_item(event.files, ev.code, ev.title),
            )
```

Change it to also carry the amount:

```python
                motions=outcome.motions if outcome else (),
                votes=outcome.votes if outcome else (),
                amount=outcome.amount if outcome else None,
                amount_text=outcome.amount_text if outcome else "",
                file_names=_files_for_item(event.files, ev.code, ev.title),
            )
```

- [ ] **Step 4: Run the adapter suite**

Run: `uv run pytest catalog/tests/test_bcsd_adapter.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/ingest/bcsd/adapter.py catalog/tests/test_bcsd_adapter.py
git commit -m "feat(ingest): carry parsed amount through the BCSD adapter join"
```

---

## Task 5: Persist the amount in the loader

**Files:**
- Modify: `catalog/ingest/loader.py` (the `AgendaItem.objects.create(...)` at lines 192-201)
- Test: `catalog/tests/test_ingest_loader.py` (add one test)

- [ ] **Step 1: Write the failing test**

`catalog/tests/test_ingest_loader.py` already imports `ParsedAgendaItem`, `ParsedMeeting`, `AgendaItem`, `load_meeting`, and provides a `context` fixture that returns `(jur, source, body)`. Add `from decimal import Decimal` to the import block (top of file) if not present, then append this test:

```python
@pytest.mark.django_db
def test_loader_persists_agenda_item_amount(context):
    jur, source, body = context
    parsed = ParsedMeeting(
        date=datetime.date(2025, 5, 15),
        start_time=None,
        kind_slug="committee-meeting",
        source_meeting_id="mid-amount-1",
        source_url="",
        source_path="",
        folder_name="2025-05-15_committee_mid-amount-1",
        title="Committee Meeting",
        agenda_items=(
            ParsedAgendaItem(
                order=1,
                code="FSS-9",
                title="Renewal of Amira Learning",
                item_type="action",
                reading_stage="",
                section="V. FISCAL",
                outcome_text="in an amount not to exceed $255,300.00",
                outcome_status="unanimous",
                amount=Decimal("255300.00"),
                amount_text="in an amount not to exceed $255,300.00",
            ),
        ),
        has_minutes=True,
    )
    load_meeting(parsed, source=source, jurisdiction=jur, body=body)
    item = AgendaItem.objects.get(code="FSS-9")
    assert item.amount == Decimal("255300.00")
    assert item.amount_text == "in an amount not to exceed $255,300.00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest catalog/tests/test_ingest_loader.py -k amount -v`
Expected: FAIL — `item.amount` is `None` (loader does not yet pass the fields).

- [ ] **Step 3: Pass the fields in the loader**

In `catalog/ingest/loader.py`, the `AgendaItem.objects.create(...)` at lines 192-201 currently ends:

```python
            outcome_text=pitem.outcome_text,
            outcome_status=_OUTCOME.get(pitem.outcome_status, AgendaItem.OutcomeStatus.NONE),
        )
```

Change it to:

```python
            outcome_text=pitem.outcome_text,
            outcome_status=_OUTCOME.get(pitem.outcome_status, AgendaItem.OutcomeStatus.NONE),
            amount=pitem.amount,
            amount_text=pitem.amount_text,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest catalog/tests/test_ingest_loader.py -k amount -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/ingest/loader.py catalog/tests/test_ingest_loader.py
git commit -m "feat(ingest): persist AgendaItem.amount + amount_text in the loader"
```

---

## Task 6: `build_relationships` reads the structured amount (retire `largest_amount`)

**Files:**
- Modify: `catalog/management/commands/build_relationships.py` (remove `MONEY` line 49 and `largest_amount` lines 66-76; change the `Relationship` creation at line 172)
- Modify: `tests/test_build_relationships.py` (the `corpus` fixture + the amount test — they must now set the structured field)

- [ ] **Step 1: Update the existing test to drive structured amount (write the failing expectation)**

In `tests/test_build_relationships.py`, the `corpus` fixture creates the Amira item from `outcome_text` only. Add the structured field and a top-of-file `from decimal import Decimal`. Change:

```python
    AgendaItem.objects.create(
        meeting=meeting,
        order=1,
        title="Renewal of Amira Learning",
        outcome_text="Approved in an amount not to exceed $255,300.00.",
    )
```

to:

```python
    AgendaItem.objects.create(
        meeting=meeting,
        order=1,
        title="Renewal of Amira Learning",
        outcome_text="Approved in an amount not to exceed $255,300.00.",
        amount=Decimal("255300.00"),
        amount_text="in an amount not to exceed $255,300.00",
    )
```

Then add a test asserting the amount now comes from the field, not the text — append:

```python
@pytest.mark.django_db
def test_amount_comes_from_structured_field_not_text(corpus):
    # An item whose text contains a larger *governance threshold* figure but whose
    # structured amount is the real contract value must use the structured value.
    item = AgendaItem.objects.get(title="Renewal of Amira Learning")
    item.outcome_text = "Contract in excess of $999,999.00 prohibited. Approved."
    item.save(update_fields=["outcome_text"])
    call_command("build_relationships", review=True)
    rel = Relationship.objects.get(predicate=Relationship.Predicate.CONTRACTS_WITH)
    assert str(rel.amount) == "255300.00"  # from item.amount, not the $999,999 in text
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `uv run pytest tests/test_build_relationships.py -v`
Expected: `test_amount_comes_from_structured_field_not_text` FAILS (command still regexes `outcome_text`, so it would pick `$999,999.00`); the other amount test may still pass because text and field agree.

- [ ] **Step 3: Read the structured field; delete the regex helpers**

In `catalog/management/commands/build_relationships.py`:

(a) Delete the `MONEY` regex (line 49):

```python
MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
```

(b) Delete the entire `largest_amount` function (lines 66-76):

```python
def largest_amount(text):
    """The biggest dollar figure in some text (the contract value), or None."""
    best = None
    for raw in MONEY.findall(text or ""):
        try:
            val = Decimal(raw.replace(",", ""))
        except InvalidOperation:
            continue
        if best is None or val > best:
            best = val
    return best
```

(c) In the `contracts_with` loop, change the `Relationship.objects.create(...)` call (line 172) from:

```python
                amount=largest_amount(item.outcome_text),
```

to:

```python
                amount=item.amount,
```

(d) Remove now-unused imports. If `Decimal`/`InvalidOperation` (line 18) are no longer referenced anywhere else in the file, delete that import line. Run `uv run ruff check .` — it will flag any unused import; remove exactly what it reports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_build_relationships.py -v`
Expected: PASS (all, including the new structured-field test).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/management/commands/build_relationships.py tests/test_build_relationships.py
git commit -m "refactor(graph): build_relationships reads structured AgendaItem.amount"
```

---

## Task 7: New `catalog/ingest/orgs.py` canonicalization module

**Files:**
- Create: `catalog/ingest/orgs.py`
- Test: `catalog/tests/test_orgs.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_orgs.py`:

```python
"""Vendor-name canonicalization: deterministic collapse via key + curated alias map,
plus a conservative similarity pass that only *proposes* merges."""

from catalog.ingest.orgs import (
    canonicalize_org_name,
    org_key,
    propose_collapses,
    resolve_key,
)


def test_canonicalize_strips_legal_suffix():
    assert canonicalize_org_name("Amira Learning, Inc.") == "Amira Learning"
    assert canonicalize_org_name("School City LLC") == "School City"
    assert canonicalize_org_name("Infinite Campus Co.") == "Infinite Campus"


def test_canonicalize_strips_renewal_and_contract_tails():
    assert canonicalize_org_name("Imagine Learning - FY24 Renewal") == "Imagine Learning"
    assert canonicalize_org_name("Renaissance Star 360 - Contract") == "Renaissance Star 360"
    assert canonicalize_org_name("Amira Learning FY23 Renewal") == "Amira Learning"


def test_canonicalize_strips_leading_approval_or_renewal():
    assert canonicalize_org_name("Approval of Amira Learning") == "Amira Learning"
    assert canonicalize_org_name("Renewal of Imagine Learning") == "Imagine Learning"


def test_canonicalize_does_not_truncate_words_that_start_like_a_suffix():
    # "Co" is a suffix only as a standalone trailing token, never inside a word.
    assert canonicalize_org_name("Costar Technologies") == "Costar Technologies"
    assert canonicalize_org_name("Incite Group") == "Incite Group"


def test_org_key_unifies_surface_variants():
    assert org_key("Amira Learning, Inc.") == org_key("amira learning llc")
    assert org_key("Amira Learning") == "amira learning"


def test_resolve_key_applies_alias_map():
    # Curated alias collapses the School City variant onto the canonical key.
    assert resolve_key("School City Assessment Platform") == resolve_key("School City")
    assert resolve_key("School City") == "school city"


def test_propose_collapses_surfaces_unaliased_lookalike():
    pairs = propose_collapses(["Renaissance Star", "Renaissance Star 360", "Infinite Campus"])
    flat = {frozenset((a, b)) for a, b, _ in pairs}
    assert frozenset(("Renaissance Star", "Renaissance Star 360")) in flat
    assert frozenset(("Renaissance Star", "Infinite Campus")) not in flat


def test_propose_collapses_skips_pairs_already_unified_by_alias():
    # Already merged by the alias map → never re-proposed.
    assert propose_collapses(["School City", "School City Assessment Platform"]) == []


def test_propose_collapses_skips_exact_key_matches():
    # Same canonical key (suffix-only difference) → already one vendor → not proposed.
    assert propose_collapses(["Amira Learning, Inc.", "Amira Learning LLC"]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest catalog/tests/test_orgs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.ingest.orgs'`.

- [ ] **Step 3: Create the module**

Create `catalog/ingest/orgs.py`:

```python
"""Organization-name canonicalization (brief §7, §14.4); mirrors names.py for people.

Pure and Django-free, so it is unit-testable and reusable by both the loader (body
orgs) and build_relationships (vendor orgs). Deterministic collapses — a normalized
key match, or a curated alias — are applied at create time and recorded in
Organization.aka. Fuzzy look-alikes are only *proposed* by propose_collapses(); a
human promotes accepted pairs into VENDOR_ALIASES, the auditable merge ledger. This
is the seed of the Phase 4 Splink-based resolution.
"""

import re

_LEADING = re.compile(r"^(?:approval\s+of|renewal\s+of)\s+", re.IGNORECASE)
_TRAILING = re.compile(
    r"\s*[-–]\s*(?:contract|fy\s*\d*\s*renewal)\s*$|\s*fy\s*\d+\s*renewal\s*$",
    re.IGNORECASE,
)
_SUFFIX = re.compile(
    r"[,\s]+(?:inc|incorporated|llc|l\.l\.c\.|co|corp|corporation|ltd|company)\.?$",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9\s]")

# Generic words ignored when comparing token sets, so "School City" ⊂ "School City
# Assessment Platform" stays detectable while filler words don't inflate overlap.
_STOP = {"the", "of", "and", "for", "a", "an", "services", "service", "system", "systems"}


def canonicalize_org_name(raw: str) -> str:
    """Clean display name: strip Approval/Renewal lead-ins, FY/contract tails, and a
    single trailing legal suffix; collapse whitespace. Empty result falls back to raw."""
    name = _WS.sub(" ", (raw or "")).strip()
    name = _LEADING.sub("", name).strip()
    prev = None
    while prev != name:
        prev = name
        name = _TRAILING.sub("", name).strip(" .,-–")
    name = _SUFFIX.sub("", name).strip(" .,-–")
    return name or _WS.sub(" ", (raw or "")).strip()


def org_key(raw: str) -> str:
    """Lowercased, punctuation-stripped matching key for the canonical name."""
    name = _PUNCT.sub(" ", canonicalize_org_name(raw).lower())
    return _WS.sub(" ", name).strip()


# Curated merge ledger: variant key -> canonical key. Promote accepted
# propose_collapses() suggestions here; the next build collapses them deterministically.
VENDOR_ALIASES: dict[str, str] = {
    "school city assessment platform": "school city",
}


def resolve_key(raw: str) -> str:
    """org_key() then a single alias redirect to the canonical key."""
    key = org_key(raw)
    return VENDOR_ALIASES.get(key, key)


def _tokens(key: str) -> set[str]:
    return {t for t in key.split() if t not in _STOP}


def propose_collapses(names, threshold: float = 0.6) -> list[tuple[str, str, float]]:
    """Suggest (name_a, name_b, score) pairs that look like the same vendor but are NOT
    yet unified by key or alias. Pure-Python token-set Jaccard + subset containment.

    Suggestions only — this mutates nothing and is the input to a human decision. It
    cannot distinguish a true variant from two distinct entities (that is why a human
    confirms); the guarantee is the reverse: an already-unified pair is never proposed.
    """
    resolved = [(n, resolve_key(n)) for n in names]
    proposals: list[tuple[str, str, float]] = []
    for i in range(len(resolved)):
        for j in range(i + 1, len(resolved)):
            (na, ka), (nb, kb) = resolved[i], resolved[j]
            if ka == kb:
                continue  # already the same vendor (key or alias) — never re-propose
            ta, tb = _tokens(ka), _tokens(kb)
            if not ta or not tb:
                continue
            subset = ta <= tb or tb <= ta
            jaccard = len(ta & tb) / len(ta | tb)
            if subset or jaccard >= threshold:
                proposals.append((na, nb, round(1.0 if subset else jaccard, 3)))
    return proposals
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest catalog/tests/test_orgs.py -v`
Expected: PASS (all cases).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/ingest/orgs.py catalog/tests/test_orgs.py
git commit -m "feat(ingest): add orgs.py vendor canonicalization + merge proposals"
```

---

## Task 8: `build_relationships` canonicalizes vendors and records `aka`

**Files:**
- Modify: `catalog/management/commands/build_relationships.py` (imports; the `contracts_with` vendor `get_or_create` at lines 157-165)
- Test: `tests/test_build_relationships.py` (add collapse + aka tests)

- [ ] **Step 1: Write the failing tests**

In `tests/test_build_relationships.py`, extend the `corpus` fixture with two collapsible vendor items, then add tests. Inside the `corpus` fixture (before `return {...}`), add:

```python
    # Two surface forms of one vendor: the canonical name and an aliased variant.
    AgendaItem.objects.create(meeting=meeting, order=3, title="Renewal of School City")
    AgendaItem.objects.create(
        meeting=meeting, order=4, title="Renewal of School City Assessment Platform"
    )
```

Then append:

```python
@pytest.mark.django_db
def test_vendor_variants_collapse_to_one_node_with_aka(corpus):
    call_command("build_relationships", review=True)
    school_city = Organization.objects.filter(slug="school-city")
    assert school_city.count() == 1
    org = school_city.first()
    assert org.name == "School City"
    assert "School City Assessment Platform" in org.aka


@pytest.mark.django_db
def test_collapsed_vendor_has_one_contract_edge_per_item(corpus):
    # Two agenda items naming the same (collapsed) vendor → two contract edges that
    # both point at the single vendor node (the items are distinct contract actions).
    call_command("build_relationships", review=True)
    org = Organization.objects.get(slug="school-city")
    edges = Relationship.objects.filter(
        predicate=Relationship.Predicate.CONTRACTS_WITH, object_id=org.pk
    )
    assert edges.count() == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_build_relationships.py -k "collapse or aka" -v`
Expected: FAIL — today `slugify(name)` produces `school-city` and `school-city-assessment-platform` (two nodes); `aka` stays empty.

- [ ] **Step 3: Use the canonicalizer in the command**

In `catalog/management/commands/build_relationships.py`:

(a) Add the import near the other `catalog.*` imports (after the `from catalog.models import (...)` block):

```python
from catalog.ingest.orgs import canonicalize_org_name, resolve_key
```

(b) Replace the vendor resolution block. The loop body currently (lines 153-165) is:

```python
            name = vendor_name(item.title)
            body = item.meeting.body
            if not name or not (body and body.reviewed):
                continue
            vendor, _ = Organization.objects.get_or_create(
                slug=slugify(name)[:255],
                jurisdiction=None,  # vendors are cross-agency by design
                defaults={
                    "name": name,
                    "kind": Organization.Kind.COMPANY,
                    "reviewed": review,
                },
            )
```

Change it to:

```python
            name = vendor_name(item.title)
            body = item.meeting.body
            if not name or not (body and body.reviewed):
                continue
            display = canonicalize_org_name(name)
            vendor, created = Organization.objects.get_or_create(
                slug=slugify(resolve_key(name))[:255],
                jurisdiction=None,  # vendors are cross-agency by design
                defaults={
                    "name": display,
                    "kind": Organization.Kind.COMPANY,
                    "reviewed": review,
                },
            )
            # Record a collapsed surface-form variant on the canonical node.
            if not created and display != vendor.name and display not in vendor.aka:
                vendor.aka = [*vendor.aka, display]
                vendor.save(update_fields=["aka"])
```

> The amount line added in Task 6 (`amount=item.amount`) stays as-is in the `Relationship.objects.create` below this block.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_build_relationships.py -v`
Expected: PASS (all, including the existing vendor/idempotency tests — re-runs must not duplicate `aka` entries).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/management/commands/build_relationships.py tests/test_build_relationships.py
git commit -m "feat(graph): canonicalize vendor names + record collapses in aka"
```

---

## Task 9: `--suggest-merges` flag surfaces fuzzy candidates

**Files:**
- Modify: `catalog/management/commands/build_relationships.py` (`add_arguments`; end of `handle`)
- Test: `tests/test_build_relationships.py` (add a flag test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_build_relationships.py`:

```python
@pytest.mark.django_db
def test_suggest_merges_reports_unaliased_lookalikes(corpus, capsys):
    # Add two look-alike vendor items that are NOT in the alias map.
    meeting = corpus["meeting"]
    AgendaItem.objects.create(meeting=meeting, order=5, title="Renewal of Renaissance Star")
    AgendaItem.objects.create(meeting=meeting, order=6, title="Renewal of Renaissance Star 360")
    call_command("build_relationships", review=True, suggest_merges=True)
    out = capsys.readouterr().out
    assert "Renaissance Star" in out
    assert "Renaissance Star 360" in out
    # An already-aliased pair (School City) must NOT appear as a suggestion.
    assert "School City Assessment Platform" not in out.split("suggest", 1)[-1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_build_relationships.py -k suggest -v`
Expected: FAIL — `--suggest-merges` is not a recognized option (or no suggestion output).

- [ ] **Step 3: Add the flag and the suggestion pass**

In `catalog/management/commands/build_relationships.py`:

(a) Update the import added in Task 8 to also bring in `propose_collapses`:

```python
from catalog.ingest.orgs import canonicalize_org_name, propose_collapses, resolve_key
```

(b) In `add_arguments`, after the existing `--review` argument, add:

```python
        parser.add_argument(
            "--suggest-merges",
            action="store_true",
            help="Print conservative vendor-merge proposals (look-alike names not yet "
            "unified by the alias map). Suggestions only — nothing is changed.",
        )
```

(c) At the end of `handle`, after the final `self.stdout.write(...)` success line, add:

```python
        if options["suggest_merges"]:
            vendor_names = list(
                Organization.objects.filter(
                    kind=Organization.Kind.COMPANY, jurisdiction__isnull=True
                ).values_list("name", flat=True)
            )
            proposals = propose_collapses(vendor_names)
            if proposals:
                self.stdout.write("Vendor-merge suggestions (review, then add to VENDOR_ALIASES):")
                for a, b, score in sorted(proposals, key=lambda p: -p[2]):
                    self.stdout.write(f"  [{score:.2f}] {a!r}  ≈  {b!r}")
            else:
                self.stdout.write("No vendor-merge suggestions.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_build_relationships.py -k suggest -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add catalog/management/commands/build_relationships.py tests/test_build_relationships.py
git commit -m "feat(graph): add --suggest-merges vendor proposal report"
```

---

## Task 10: Full-suite verification + dev-data runbook note

**Files:**
- Modify: `docs/superpowers/specs/2026-06-04-civicvault-influence-graph-roadmap.md` (tick Phase 3 acceptance — optional housekeeping)

- [ ] **Step 1: Run the entire test suite**

Run: `uv run pytest -q`
Expected: PASS — the pre-existing count (193) plus the new tests (no failures, no errors).

- [ ] **Step 2: Confirm lint + format are clean**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no findings; format check reports nothing to change.

- [ ] **Step 3: Re-ingest dev data and re-derive edges (manual verification)**

The new `AgendaItem.amount` is populated at ingest, so existing rows are backfilled only by re-ingesting. Run:

```bash
docker compose up -d db
uv run python manage.py ingest_bcsd <path-to-an-archive-folder-with-minutes>
uv run python manage.py build_relationships --review
uv run python manage.py build_relationships --review --suggest-merges
```

Expected: contract edges show amounts where the minutes state one; `--suggest-merges` prints any look-alike vendor pairs not yet aliased (or "No vendor-merge suggestions").

- [ ] **Step 4: Visual check of the graph (UI sanity)**

Run `uv run python manage.py runserver` and open `http://127.0.0.1:8011/graph/`. Confirm: no duplicate "School City" nodes; contract edges display dollar amounts; an item with no captured amount shows "amount not recorded" rather than a wrong figure. Save a screenshot to the gitignored `screenshots/` directory.

- [ ] **Step 5: Final commit (if the roadmap was ticked)**

```bash
uv run ruff check . && uv run ruff format .
git add -A
git commit -m "docs(phase3): mark vendor normalization + amount capture acceptance met"
```

---

## Self-review notes (for the implementer)

- **Spec coverage:** amount-home → Task 1; cue-anchored capture + verbatim phrase → Task 3; IR/adapter/loader flow → Tasks 2/4/5; `build_relationships` reads structured amount → Task 6; canonicalize + alias + `aka` → Tasks 7/8; similarity *proposals* (never auto-applied) → Tasks 7/9. The one spec item intentionally **not** given a task is §B3 (optionally canonicalizing the body-org name in `ingest_bcsd.py`): the spec marks it optional and not required for acceptance, and body names carry none of the suffix/renewal noise vendors do — adopt it later only if a body name actually needs it. Everything required for acceptance maps to a task.
- **Order matters:** Tasks 1→6 are the amount slice (each green before the next); 7→9 the vendor slice; 10 verifies the whole. Task 6 *changes* an existing test fixture — do it exactly as written or the amount assertions will read from `outcome_text` and silently pass for the wrong reason.
- **Type/name consistency:** `extract_amount(text) -> (Decimal|None, str)`, `canonicalize_org_name`, `org_key`, `resolve_key`, `propose_collapses` are used with identical signatures everywhere they appear. `AgendaItem.amount` is `Decimal|None`; `amount_text` is `str`.
- **Watch:** when you delete `largest_amount` (Task 6) also remove the now-unused `Decimal`/`InvalidOperation` import in that command file — let `ruff check` tell you. The loader test (Task 5) uses the file's existing `context` fixture (`jur, source, body = context`) and `load_meeting(parsed, source=source, jurisdiction=jur, body=body)`; the adapter test (Task 4) imports `ItemOutcome` from `catalog.ingest.bcsd.minutes_md`. Both are concrete against the current files — no fixture invention needed.
</content>
</invoke>
