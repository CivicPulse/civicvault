# CivicVault — Phase 3 (finish): Vendor Normalization + Amount Capture — Design

**Date:** 2026-06-04
**Status:** Approved (design); pending implementation plan
**Source of truth:** [`project_brief.md`](../../../project_brief.md) §5.2 (minutes parsing), §7 (entity dedup), §14.3–14.5 (adapter contract / model). Adds structured fields; changes no locked decision.
**Roadmap:** [`2026-06-04-civicvault-influence-graph-roadmap.md`](2026-06-04-civicvault-influence-graph-roadmap.md) Phase 3, items 1 (vendor entity resolution) and 2 (amount capture). Item 3 (the `2025-09-18` duplicate-vote parser bug) **already shipped** as its own slice (`4cf4630`); this design covers only the two remaining pieces.
**Predecessors:** slice 1b (`minutes_md.py`), the influence-graph foundation (`Relationship`, `build_relationships`), and the duplicate-vote ingest fix — all on `main`.

## Purpose

The contract layer of the influence graph is real but not yet *trustworthy and complete*. Two defects undermine it:

1. **Vendor identity is split.** "School City" and "School City Assessment Platform" become two separate vendor nodes because names are slugged raw (`slugify(name)`) with no canonicalization. The graph overstates how many vendors exist and understates each one's footprint.
2. **Dollar amounts are re-derived at graph-build time** by regexing `agenda_item.outcome_text` for the largest `$` figure (`largest_amount()`). This is fragile (it cannot tell a contract value from a governance threshold) and it loses the verbatim context a reviewer needs.

Both share one fix: **stop deriving at graph-build time; capture structured truth at ingest time.** `build_relationships` becomes a *reader* of clean fields instead of a regex engine — which is also the seam Phase 4's external adapters and Splink-based resolution build on.

## Critical data finding (drove the design)

A scan of the real archive's `outcome_text` shows `$` figures are **not homogeneous**. Two distinct kinds coexist, often in the same corpus:

- **Contract amounts**, always framed by a cue phrase:
  `... in the amount not to exceed $255,500.00 to purchase desk shields ...`
  `... at an annual cost not to exceed $689,000.00 utilizing American Rescue Plan ...`
  `... in an aggregate amount not to exceed $1,190,822.00 for the fiscal year 2021-2022`
- **Governance thresholds**, embedded in policy/procedure text, with *no* contract cue:
  `... any contract in excess of $150,000.00. A proper bond ...`
  `... items valued less than $5,000.00 to the District ...`
  `... purchases over $30,000. The need for ...`

`largest_amount()` cannot distinguish them: on a policy item it would attach a *governance rule's* number to a contract edge. It also mishandles funding-source breakdowns (`not to exceed $439,500.00 (American Rescue Funds - $250,000 ...)` — the headline value is the first figure, not the largest) and OCR noise (`$50,000.oo`, which only ever appears in threshold text).

**Decision:** capture an amount **only when a contract-amount cue precedes the figure**, take the **first** such figure (the headline value), and store the **verbatim phrase** alongside it so a reviewer can judge "not to exceed" / annual-vs-total / multi-year without the parser inferring any of it. Threshold-only items get no amount — "amount not recorded" is the honest result, and a false amount is worse than a missing one.

## Decisions (settled in brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| **Amount home** | `AgendaItem` (not `Motion`, not both) | The money lives in `agenda_item.outcome_text`; **0** motions carry `$`. Agenda items are the unit users query and the unit `build_relationships` already iterates. One field, one migration. |
| **Amount capture** | Cue-anchored figure **+ verbatim phrase** (`amount_text`) | Avoids governance thresholds; preserves "not to exceed"/funding nuance for review; never infers annual vs total. |
| **Vendor collapsing** | Normalized key **+ curated alias map**, plus a **similarity *proposal* pass** | Deterministic collapses apply and are recorded in `aka`; fuzzy matches are only *suggested* and never auto-applied. The alias map is the auditable merge ledger. |
| **Proposal mechanism** | Alias map is the confirmation ledger; similarity is a suggester (`--suggest-merges`) | Honors "recorded, reviewable, never auto-applied" with zero new schema; keeps builds deterministic; seeds Phase 4 Splink as the `canonicalize()` + alias interface. |
| **Fuzzy library** | **None** — pure-Python token-set similarity | Roadmap mandates "no new external dependencies" for Phase 3; leaves Splink as Phase 4's first real ER dependency. |

## Architecture & data flow

```
minutes_md.py  ──extract_amount()──▶  ParsedAgendaItem(amount, amount_text)  ──▶  loader  ──▶  AgendaItem.amount / .amount_text
                                                                                                       │
orgs.py:  canonicalize_org_name() · org_key() · VENDOR_ALIASES · propose_collapses()                   ▼
        └────────────── used by ──────────────▶  build_relationships  ──reads item.amount, canonical vendor──▶  Relationship(amount=…)
```

The pipeline shape is unchanged (pure parser → frozen IR → generic loader → thin command). Amount capture adds two fields that ride that pipeline end to end; vendor canonicalization adds a pure module (`orgs.py`, mirroring `names.py`) consumed at the org-creation sites.

## Component A — Amount capture

### A1. IR (`catalog/ingest/ir.py`)
Add to `ParsedAgendaItem` (frozen dataclass; `Decimal` is stdlib, so the parser stays Django-free):

```python
amount: Decimal | None = None
amount_text: str = ""
```

### A2. Parser (`catalog/ingest/bcsd/minutes_md.py`)
New pure function `extract_amount(outcome_text) -> tuple[Decimal | None, str]`:

- Match a dollar figure **only** when immediately preceded by a contract-amount cue, each
  optionally followed by `of` or `not to exceed`:
  `in (the|an) amount`, `at a[n] [annual] cost`, `aggregate amount`.
  (These are the patterns actually present in the archive; deliberately *not* broadened to
  generic phrasings like "for a total of", which appear in budget-report items and would
  capture non-contract figures.)
- Return the **first** cue-anchored figure as a `Decimal` (a trailing `(Funds — $250,000 …)` breakdown never overrides the headline value), plus the **verbatim window** from the cue through the figure (capped to `amount_text`'s length).
- No cue → `(None, "")`. Populate the two new IR fields when building each `ParsedAgendaItem`.

### A3. Loader (`catalog/ingest/loader.py:192`)
Pass the new fields straight through:

```python
amount=pitem.amount,
amount_text=pitem.amount_text,
```

### A4. Model + migration (`catalog/models/meeting.py`)
On `AgendaItem`:

```python
amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
amount_text = models.CharField(max_length=255, blank=True)
```

`max_digits=14` covers values into the hundreds of billions — comfortably past any district contract. Generate the migration with `makemigrations` and review the generated file.

### A5. Consumer (`catalog/management/commands/build_relationships.py`)
Replace `amount=largest_amount(item.outcome_text)` with `amount=item.amount`. Delete `largest_amount()` and the `MONEY` regex. The contract edge now shows an amount exactly where ingest captured one, and "amount not recorded" where the source truly omits it.

## Component B — Vendor canonicalization

### B1. New module `catalog/ingest/orgs.py` (mirrors `names.py`)
Pure, Django-free, unit-testable:

- `canonicalize_org_name(raw) -> str` — the clean **display** name. Strips leading `Approval of` / `Renewal of`; trailing `- Contract`, `- FY## Renewal`, `FY## Renewal`; standalone legal suffixes (`Inc`, `LLC`, `L.L.C.`, `Co`, `Corp`, `Ltd`, `Company`, `Incorporated`) — **only as a trailing token**, so "Costar" / "Coastal" are never truncated; collapses internal whitespace. Unknown/short input is returned unchanged.
- `org_key(raw) -> str` — lowercased, punctuation-stripped matching key derived from the canonical name. Two raws with the same key are the same vendor.
- `VENDOR_ALIASES: dict[str, str]` — curated variant-key → canonical-key. The durable, git-audited merge ledger (e.g. `"school city assessment platform": "school city"`).
- `resolve_key(raw) -> str` — `org_key(raw)` then alias-map redirect; the single function callers use to get a vendor's canonical key.
- `propose_collapses(names) -> list[tuple[str, str, float]]` — **pure-Python** token-set similarity (Jaccard over significant tokens) plus subset-containment, above a conservative threshold; returns only pairs **not already** unified by key or alias. Suggestion only; mutates nothing. It *cannot* (and must not try to) distinguish a true variant ("School City" / "School City Assessment Platform") from two genuinely distinct entities ("Imagine Learning" / "Imagine Learning Foundation") — both are surfaced for a human to judge. The guarantee is the reverse: a pair already merged by key or alias is **never** re-proposed.

### B2. Integration in `build_relationships`
- `vendor_name(title)` still extracts the raw name from the contract/renewal title. Then `canonicalize_org_name()` gives the display name and `resolve_key()` gives the slug input:
  `slug=slugify(resolve_key(name))[:255]` — so variants and known aliases share **one** node.
- On `get_or_create`, if the resolved vendor already exists under a *different* surface form, append that variant display name to `Organization.aka` **idempotently** (no duplicates), recording the collapse.
- New `--suggest-merges` flag: after the build, gather all vendor display names, run `propose_collapses`, and print the candidate pairs (with scores) that are **not yet** in `VENDOR_ALIASES`. A human promotes accepted pairs into the map; the next build collapses them deterministically. The flag changes no data.

### B3. Body org site (`catalog/management/commands/ingest_bcsd.py:53`)
The meeting-body `get_or_create` may adopt `canonicalize_org_name()` for consistency. Low-risk (body names rarely carry suffix noise) and **not required** for acceptance; included only if it falls out cleanly.

## Error handling & edge cases

- **No cue → no amount.** Edge reads "amount not recorded." OCR `$50,000.oo` appears only in threshold text (no cue) and is correctly skipped; documented in a test.
- **Suffix stripping is trailing-token-only** and never touches an interior or whole-word match ("Co" inside "Costar"). Empty/short names return unchanged with no collapse.
- **Subset containment is proposal-only** precisely because "Imagine Learning" ⊂ "Imagine Learning Foundation" may be genuinely distinct entities — the conservative threshold plus human confirmation is the safety net. False merges are the worst failure for an accountability tool, so every ambiguous call biases toward "don't assert."
- **Idempotency preserved.** `build_relationships` still owns the `derived-relationships` `Source` and rebuilds only its own rows; `aka` appends are dedup-guarded. The review gate is unchanged — everything new stays `reviewed=False` until `--review` (dev) or admin confirmation.

## Files

| File | Change |
|---|---|
| `catalog/ingest/ir.py` | `ParsedAgendaItem`: add `amount`, `amount_text`. |
| `catalog/ingest/bcsd/minutes_md.py` | Add `extract_amount()`; populate the two IR fields. |
| `catalog/ingest/loader.py` | Pass `amount` / `amount_text` into `AgendaItem.objects.create`. |
| `catalog/models/meeting.py` (+ migration) | `AgendaItem.amount` (Decimal) + `amount_text` (Char). |
| `catalog/ingest/orgs.py` (new) | `canonicalize_org_name`, `org_key`, `VENDOR_ALIASES`, `resolve_key`, `propose_collapses`. |
| `catalog/management/commands/build_relationships.py` | Read `item.amount`; canonicalize vendor via `orgs.py`; record `aka`; add `--suggest-merges`; delete `largest_amount`/`MONEY`. |
| `catalog/management/commands/ingest_bcsd.py` | Optional: canonicalize body name. |
| `catalog/tests/` + `tests/` | Unit + integration tests (below). |

## Verification & tests

**Unit — `orgs.py`:**
- `canonicalize_org_name`: suffix stripping (`Inc`/`LLC`/`Co`), `FY## Renewal`, `- Contract`, `Approval of`/`Renewal of`; "Costar" not truncated.
- `org_key` / `resolve_key`: variant equality; alias-map redirect collapses `School City Assessment Platform` → `school city`.
- `propose_collapses`: **surfaces** an unaliased subset look-alike (e.g. "Renaissance Star" / "Renaissance Star 360") for review; does **not** pair unrelated vendors; and **skips** a pair already unified by the alias map ("School City" / "School City Assessment Platform" → `[]`).

**Unit — `extract_amount` (fixtures grounded in real archive phrasings):**
- `not to exceed`, `in the amount of`, `at an annual cost not to exceed`, `aggregate amount not to exceed` → correct `Decimal` + verbatim `amount_text`.
- Policy-threshold-only text (`contract in excess of $150,000`, `valued less than $5,000.00`) → `(None, "")`.
- Funding-source breakdown (`$439,500.00 (American Rescue Funds - $250,000 …)`) → headline figure, not the largest/parenthetical.

**Integration:**
- Loader: a `ParsedAgendaItem` carrying `amount`/`amount_text` materializes them on `AgendaItem`.
- `build_relationships`: reads the structured `amount`; two vendor variants collapse to **one** `Organization` with the variant recorded in `aka`; `--suggest-merges` prints the expected candidate pair; an item with no captured amount yields a contract edge with no amount.

**Suite-wide:** full `pytest` green; `ruff check` + `ruff format --check` clean.

**Runbook note (dev data):** `AgendaItem.amount` is populated at ingest, so existing rows need a re-ingest to backfill — `uv run python manage.py ingest_bcsd <archive>` then `build_relationships --review`. Tests use fixtures and do not depend on the dev DB.

## Risks

- **Over-aggressive name collapsing merges two real vendors.** Mitigation: deterministic collapses are key/alias-exact only; everything fuzzy is a *proposal* gated by a human and the review gate. The alias map is reviewable in git.
- **A contract amount phrased without a recognized cue is missed.** Mitigation: cue list grounded in real archive text; "amount not recorded" is an honest, non-misleading default, and the verbatim `outcome_text` remains on the item for audit. New cue patterns are a one-line addition with a test.
- **Re-ingest churn on already-reviewed dev data.** Mitigation: amounts are additive (new nullable field); re-ingesting produces the corrected shape, which is the desired outcome, not a regression. Review state is reasserted by `build_relationships --review` in dev.

**Effort:** small–medium. One nullable-pair migration, one new pure module, a focused parser function, and a consumer refactor. No new external dependencies, no change to the graph-rendering layer.
