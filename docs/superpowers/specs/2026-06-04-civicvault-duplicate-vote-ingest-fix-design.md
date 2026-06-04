# CivicVault — Duplicate-Vote Ingest Fix (minutes header-depth) — Design

**Date:** 2026-06-04
**Status:** Approved (design); pending implementation plan
**Source of truth:** [`project_brief.md`](../../../project_brief.md) §5.2 (minutes parsing, motions/roll-call). This fixes a parser defect; it changes no locked decision.
**Roadmap:** [`2026-06-04-civicvault-influence-graph-roadmap.md`](2026-06-04-civicvault-influence-graph-roadmap.md) Phase 3, item 3. Split out as its own slice (the riskiest of the three Phase-3 pieces; it touches the parser everything else depends on, and it unblocks loading the full archive).
**Predecessors:** slice 1b (Source-A parser, `minutes_md.py`), merged to `main`.

## Purpose

The BCSD minutes parser silently miscounts which agenda item a roll call belongs to whenever a
meeting nests action sub-items below the recognized header depth. The visible symptom is a
duplicate-vote `IntegrityError` that aborts ingest for the affected meeting (the roadmap's
`2025-09-18` case). This slice fixes the root cause so every roll call attaches to the correct
`AgendaItem`, archive-wide, and adds a defensive guard so any *future* malformed minutes fails with a
clear, actionable error instead of a downstream database constraint violation.

## Critical scope finding (drove the ambition)

The roadmap framed this as a one-folder bug ("swap `2025-09-18` back in"). It is not. A parse-only
sweep over **all 539 meetings** with `minutes.md` shows:

- **83 meetings** contain five-or-more-hash sub-headers.
- **23 meetings** currently produce a duplicate-voter agenda item — i.e. they would raise the
  `uniq_vote_person_item` `IntegrityError` on load. They cluster in two source eras: **2014–2015
  board meetings** (consent-style nesting) and **2025–2026 committee meetings** (the
  Personnel / Executive-Session pattern). `2025-09-18` is simply the one that landed in the 8-day demo set.
- Beyond the loud crash, the same defect **silently misattributes** votes where it does not crash:
  a sub-item's roll call is filed under its parent item, so "how did X vote on PS-1" returns nothing
  while the parent shows phantom votes. For a provenance product this is arguably the worse failure.

**Decision:** fix for whole-archive correctness, with a regression sweep over all 539 meetings
proving zero new duplicates and zero dropped votes. The 8-day demo set is the proving ground, not the
boundary.

## Root cause (confirmed by reproduction)

`_ITEM_HEADER` in `catalog/ingest/bcsd/minutes_md.py:12` is:

```python
_ITEM_HEADER = re.compile(r"^####\s+(?:[ivxlc]+|[a-z]|\d+)\.\s+(?P<rest>.+?)\s*$")
```

It recognizes only **four-hash** headers with an **unescaped** ordinal dot. The minutes contain a
three-layer nesting the regex cannot see:

1. **Five-hash action sub-items** (`##### a. PS-1 Certified Personnel Report (ACTION)`) are not
   matched, so the block-builder folds them into the nearest four-hash parent
   (`#### i. Executive Session …`).
2. Each absorbed sub-item carries **its own roll call**. Folding PS-1's and PS-2's roll calls into
   one item means every voter appears twice → 12 votes for 6 people → the `IntegrityError`.
3. The deepest appointment lists use **six-hash headers with MultiMarkdown-escaped ordinals**
   (`###### 1\. Director of Research …`). Even after widening the hash count, `\d+\.` fails to match
   `1\.`, so seven appointment roll calls collapse into one item (the 2015-06-18 `PS-3` case:
   49 votes = 7 voters × 7 appointments).

Reproduction (committed as the regression fixtures) confirms each layer; the fix below was prototyped
against all 539 meetings before this design was written.

## The fix

### Core — broaden header recognition (`minutes_md.py`)

```python
_ITEM_HEADER = re.compile(r"^#{4,}\s+(?:[ivxlc]+|[a-z]|\d+)\\?\.\s+(?P<rest>.+?)\s*$")
```

Two changes, both verified necessary and sufficient:

- `####` → `#{4,}` — recognize four-hash items **and** any deeper nesting as item boundaries.
- `\.` → `\\?\.` — tolerate the MultiMarkdown backslash-escaped ordinal (`1\.` as well as `1.`).

With this, each leaf sub-item owns its own outcome/roll-call block and joins to its `event.md`
counterpart by `code` (or `title` when code-less), exactly as today. The existing block-segmentation
loop already terminates a block on the next item header or a `### ` section boundary and needs **no
change**. The ordinal requirement (`(?:[ivxlc]+|[a-z]|\d+)\.`) is what keeps deepening safe:
non-item four-hash headers like `#### Voting Members` / `#### Attendance` have no `ordinal.` and remain
unmatched, so widening the hash count does **not** widen false positives.

The now-obsolete "consent-anchor attachment" limitation note (`minutes_md.py:154-160`) is rewritten to
describe the corrected behavior (the residual genuine consent-anchor case, if any, is the only thing it
should still warn about).

### Guard — fail loud on a repeated voter (`minutes_md.py`)

After a leaf item's votes are parsed, assert no `Person` appears twice in that single block. On
violation, **raise a descriptive `ValueError`** naming the meeting/item and the repeated voter, and
**fail the whole meeting's ingest** (matching the loader's existing fail-loud posture at
`loader.py:227`). With the core fix in place, **nothing in the current 539-meeting archive trips this
guard** — it is insurance against future malformed minutes, converting a cryptic DB `IntegrityError`
into a clear parser-level diagnosis at the point of the actual problem.

## Data-shape consequence (intended, worth noting)

Deep items now materialize as **separate `AgendaItem`s**. "Administrative Appointments" becomes seven
rows, each with its own roll call, rather than one row with a merged 49-vote blob. This is strictly
more faithful to the source and is the *point*: a differing roll call per appointment (an abstention
on one specific hire) is exactly the conflict-of-interest signal the product exists to surface, and the
old behavior destroyed it. The change increases item granularity only on meetings that genuinely
nest action sub-items.

No model or migration change. No loader change — its existing fail-loud `ValueError` stays as the last
line of defense behind the new parser guard.

## Verification & tests

**Unit (fixtures grounded in real archive text):**
- The `2025-09-18` Personnel/Executive-Session pattern: `#### i. Executive Session` followed by
  `##### a. PS-1` / `##### b. PS-2`, each with a roll call → asserts each PS item gets its own 6 votes,
  Executive Session keeps only its two (un-rolled) motions, no duplicate voter anywhere.
- The `2015-06-18` six-hash escaped-ordinal appointment pattern (`###### 1\. …`) → asserts the
  appointment sub-items separate and no item carries a duplicate voter.
- The guard: a synthetic block with the same voter twice → asserts a `ValueError` naming the item and
  the repeated voter.

**Archive sweep (the "verify no regressions" requirement):**
- A test that parses **all 539 meetings** (PDF text-extraction stubbed for speed — only the
  `event.md`↔`minutes.md` join matters) and asserts the measured invariant: **0 agenda items with a
  duplicate voter** and **0 vote-bearing minutes outcomes that join to no event item** (no dropped
  votes). This freezes the exact result the prototype produced and guards against future parser
  regressions. If the local archive is unavailable in CI, the sweep is marked to skip cleanly (it is a
  developer/operator regression gate over local source data, not a packaged fixture).

**End-to-end:**
- Load `2025-09-18` via the real ingest command and confirm it persists without error, with PS-1/PS-2
  votes attached to PS-1/PS-2 (not to Executive Session). Restore `2025-09-18` to the demo set in place
  of the `2025-05-15` swap noted in the roadmap, so all 8 demo days load via one command.

## Files

| File | Change |
|---|---|
| `catalog/ingest/bcsd/minutes_md.py` | Broaden `_ITEM_HEADER` regex; add the repeated-voter guard; rewrite the stale consent-anchor note. |
| `tests/` (new + extended) | Personnel/Executive-Session fixture; six-hash escaped-ordinal fixture; guard fixture; the 539-meeting parse sweep. |

No changes to models, migrations, `loader.py`, `ir.py`, or the graph layer.

## Risks

- **Granularity churn on already-reviewed dev data.** Only `2025-09-18` among the 8 demo days is
  affected, and it is not currently loaded — so dev-DB impact is limited to the newly-loadable meeting.
  Re-running ingest on the full archive later will produce the corrected (more granular) shape; that is
  the desired outcome, not a regression.
- **An unforeseen deeper nesting** in some meeting could still merge roll calls. Mitigation: the
  fail-loud guard converts any such case into a clear, named error rather than silent corruption — and
  the 539-meeting sweep would catch it before merge.
- **`event.md` join misses** for a newly-separated sub-item (item present in minutes but absent from
  the agenda echo) would drop its votes. Mitigation: the sweep's "0 dropped vote-bearing outcomes"
  assertion specifically detects this; the prototype measured zero.

**Effort:** small. Two-character regex change at the core, plus a guard and a thorough test sweep. No
new dependencies, no schema change.
