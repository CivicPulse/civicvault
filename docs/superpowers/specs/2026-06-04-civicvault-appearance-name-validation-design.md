# CivicVault — Appearance Name-Validation + Orphan Pruning — Design

**Date:** 2026-06-04
**Status:** Approved (design); pending implementation plan
**Source of truth:** [`project_brief.md`](../../../project_brief.md) §5.2 (minutes parsing), §7 (person dedup). Fixes a parser-quality defect; changes no locked decision.
**Predecessors:** slice 1b (`minutes_md.py`, `names.py`); the influence-graph work and Phase 3 (vendor/amount), all on `main`.
**Branch:** `fix/appearance-name-parsing`.

## Purpose

The BCSD minutes parser materializes prose fragments and role descriptors as `Person` rows, polluting the catalog and the `/graph` influence graph. Observed junk "persons": *"Four people addressed the Board for comments."*, *"There were no requests to address the Board."*, *"No visitors requested to address the Board."*, *"They were:"*, *"Two eighth grade students from Miller Middle School congratulated their new principal…"*, *"Board member"*, and the mangled *"Little Miss and Mr. Cherry Blossom Festival 2024: Alexandria Habersham"*.

This slice fixes the root cause so appearance capture only yields real names, and adds a tool to remove the orphaned proposal nodes the bug (and re-ingestion generally) leaves behind.

## Root cause (confirmed by reproduction)

`_parse_appearances` in `catalog/ingest/bcsd/minutes_md.py` captures text fragments as `Person` names **with no validation that the fragment is name-shaped**. Three capture sites, three symptoms, one cause:

1. **Visitor capture** (`INVITATION TO VISITORS` section): appends any non-blank line not starting with `#`/`-`/`The `/`_` as a `speaker`. Real minutes narrate this section in **prose** when no one is named — e.g. 2024-03-21 board:
   ```
   ### VI. INVITATION TO VISITORS TO ADDRESS THE BOARD

   Four people addressed the Board for comments.

   They were:

   Two eighth grade students from Miller Middle School congratulated their new principal…
   ```
   The correct capture here is **zero** speakers. The working case (2025-04-17 board) lists names plainly — *"Attorney Roy Miller"*, *"Jessican Strohmetz"* — after a *"The following citizens…:"* lead-in.
2. **Pledge capture** (`####` under `PLEDGE OF ALLEGIANCE`): appends the entire sub-item header. The 2024-03-21 header is an award format — `Little Miss and Mr. Cherry Blossom Festival 2024: Alexandria Habersham, <school>; Beau Mote, <school>` — which `split_name_and_role` (comma-partition) mangles into one junk name.
3. **Invocation** (`The invocation was given by …`): `split_name_and_role` assumes `Name, Role` and partitions on the first comma. The 2024-09-19 phrasing is **role-first apposition** — *"…given by Board member, Dr. Juawn Jackson."* — so it takes "Board member" as the name and discards the real person (Dr. Juawn Jackson, who is already a board node).

### Discriminator (empirically validated)

A name-shape predicate cleanly separates names from prose/descriptors across **every** real case. Validated:

| Must pass (→ name) | Must fail (→ rejected) |
|---|---|
| Attorney Roy Miller → "Roy Miller" | Four people addressed the Board for comments. |
| Jessican Strohmetz | They were: |
| Reverend Kenneth Moye → "Kenneth Moye" | Two eighth grade students from Miller Middle School… |
| Dr. Juawn Jackson → "Juawn Jackson" | No visitors requested to address the Board. |
| Henry Ficklin / Lisa Garrett-Boyd / Madison Pritchard | There were no requests to address the Board. |
| | Board member |
| | Little Miss and Mr. Cherry Blossom Festival 2024: Alexandria Habersham |

The signals: terminal sentence punctuation (`. : ; ,`), bounded token count, and every token being Capitalized (or a nobiliary particle). No ordinary lowercase content word ("people", "were", "member") may appear.

## Decisions (settled in brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| **Pledge handling** | Drop if not name-shaped (uniform gate) | One rule everywhere; pledge leaders are ceremonial students, not decision-makers. Losing two student names is acceptable; corpus-specific award parsing is not worth the fragility. |
| **Invocation apposition** | Handle in the invocation path only | Smallest blast radius; leaves shared `split_name_and_role` (roster) untouched. |
| **Orphan cleanup** | Reusable `prune_orphans` command | The strand-after-reingest problem recurs (junk Persons now, stale vendor earlier). A safe, dry-run-default command fixes it for good. |

## Architecture & data flow

```
names.py: looks_like_name(text)
        └── used by ──▶ minutes_md.py _parse_appearances:
                              • visitor   → append only if name-shaped
                              • pledge    → append only if name-shaped
                              • invocation→ _resolve_apposition_name() picks the name-shaped comma-segment

prune_orphans (management command, dry-run default)
        └── deletes ──▶ Reviewable Person rows AND vendor-kind Organization rows
                         with zero connecting facts and zero relationships
```

The parser stays pure and Django-free; the predicate lives beside `normalize_name`.

## Component A — `looks_like_name()` (`catalog/ingest/names.py`)

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

## Component B — gate the capture sites (`catalog/ingest/bcsd/minutes_md.py`)

- **Visitor:** drop the loose `("#", "-", "The ", "_")` prefix heuristic to a structural-only guard (`("#", "-")`) and append only when `looks_like_name(normalize_name(line))`. The predicate subsumes the "The …:" lead-in (terminal colon) and all prose.
- **Pledge:** append only when `looks_like_name(normalize_name(rest))`.
- **Invocation:** new helper
  ```python
  def _resolve_apposition_name(raw: str) -> str:
      """From an invocation 'given by X' string, return the first comma-segment that
      normalizes to a name-shaped value, else "". Recovers 'Juawn Jackson' from
      'Board member, Dr. Juawn Jackson'; keeps 'Kenneth Moye' from 'Reverend Kenneth
      Moye, <church>'."""
      for seg in raw.split(","):
          name = normalize_name(seg)
          if looks_like_name(name):
              return name
      return ""
  ```
  Append the invocation appearance only when the resolved name is non-empty; `ParsedPerson.raw_name` retains the full original string for provenance.

## Component C — `prune_orphans` (`catalog/management/commands/prune_orphans.py`)

Conservative cleanup of edge-less proposal nodes. **Dry-run by default; `--apply` to delete.**

- **Person** orphan: zero `appearances`, zero `votes`, zero `motions_moved`, zero `motions_seconded`, and zero `Relationship` rows referencing it (as subject or object via the generic FK).
- **Organization** orphan: **vendor kinds only** (`company`, `nonprofit`, `campaign`) with zero `meetings` (as body) and zero `Relationship` references. Bodies, schools, and jurisdiction-scoped orgs are never considered.

By construction an orphan has no connecting facts, so deletion strands nothing (no citations, no edges). Output reports counts and the names it deletes (or would delete, in dry-run).

## Verification & tests

**Unit — `looks_like_name` (`catalog/tests/test_names.py`, new file if absent):**
- All 7 real names pass; all 7 real prose/descriptor fragments fail.
- Edges: single token ("Smith"), initials ("John Q. Public"), hyphen ("Garrett-Boyd"), particle ("Maria de la Cruz") pass; empty → False.

**Unit — `_parse_appearances` against real fixture text (`catalog/tests/test_bcsd_minutes_md.py`, new fixtures grounded in the meetings above):**
- Visitor prose block → **0** speakers; the named block ("Attorney Roy Miller" / "Jessican Strohmetz") → **2** speakers ("Roy Miller", "Jessican Strohmetz").
- Pledge award-title header → **0** pledge appearances; a plain-name pledge sub-item → 1.
- Invocation "Board member, Dr. Juawn Jackson" → one invocation appearance "Juawn Jackson"; "Reverend Kenneth Moye, <church>" → "Kenneth Moye"; an all-prose invocation tail → none.

**Command — `prune_orphans` (`tests/test_prune_orphans.py`, alongside the other management-command tests):**
- An orphan Person (no facts) and an orphan vendor Org (no relationships) are deleted under `--apply`.
- A connected Person (has an appearance) and a body Organization (has a meeting) are preserved.
- Default run (no `--apply`) deletes nothing and reports the would-delete set.

**Suite-wide:** full `pytest` green; `ruff check` + `ruff format --check` clean.

## Operational follow-up (not code; after merge)

Re-ingest the 17 loaded meetings with the snapshot/restore-reviewed procedure, then `build_relationships --review`, then `prune_orphans --apply` to drop the now-edge-less junk Persons. Re-verify `/graph` shows no prose nodes and that Juawn Jackson carries an invocation appearance.

## Risks

- **Over-rejection of an unusual real name** (e.g. all-lowercase stylization). Mitigation: members come from the roster path (unaffected); only ceremonial visitor/pledge/invocation names route through the gate, where a missed low-value name is preferable to a false person. New shapes are a one-line predicate adjustment with a test.
- **`prune_orphans` deleting something legitimate.** Mitigation: dry-run default; vendor-kind orgs only; requires zero facts AND zero relationships; reviewable output before `--apply`.

**Effort:** small. One predicate, three gated call sites, one small command, focused tests. No new dependencies, no schema/migration change.
