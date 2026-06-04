# Phase 4 — Kickoff prompt

Copy everything in the fenced block below into a fresh Claude Code session started in this repo.
Phase 4 = external relationship adapters (`owns` / `donates_to` / `employed_as`).

> **Sequencing note:** the roadmap intends Phase 4's entity resolution to build on Phase 3's
> **vendor canonicalizer**, which is NOT yet built (only the Phase-3 duplicate-vote ingest fix
> shipped). See `PHASE3-FINISH-KICKOFF.md`. Decide with the user whether to finish Phase 3 first
> or proceed with conservative matching and backfill (decision #4 below).

````text
You're picking up CivicVault, a Django civic-transparency app. The active work is the
relationship graph. Your job this session is **Phase 4 — external relationship adapters**.
Do NOT start coding: brainstorm → write a spec → write a plan → then execute.

## 0. First five minutes (orient before reading)
cd /media/kwhatcher/Storage/civicvault
git branch --show-current            # expect: main
git log --oneline -3                 # tip should be 4cf4630 (Phase-3 ingest fix)
git status --short                   # tree should be clean
docker compose up -d db              # Postgres on host port 5433 (.env points here)
uv run pytest -q                     # expect: 193 passed
uv run ruff check .                  # expect: clean

ALWAYS use `uv run` for Python (never system python) and `uv add` for deps. Ruff-clean
before every commit. Conventional Commits. Commit on a branch, NOT main. **Never push to
GitHub** and never merge to main without an explicit ask (local main is currently 23
commits ahead of origin/main and intentionally unpushed).

## 1. Read these, in order
- docs/superpowers/specs/2026-06-04-civicvault-influence-graph-roadmap.md  ← the plan;
  read "Where we are now", then the **Phase 4** section in full.
- docs/superpowers/HANDOFF.md  ← older MVP-slice track; ingest pipeline shape + known limits.
- project_brief.md §3  ← names **Splink** for entity resolution (not yet wired up).
- As a *pattern reference* for the spec/plan format and the TDD/subagent workflow you'll
  follow, skim the Phase-3 pair already shipped:
  docs/superpowers/specs/2026-06-04-civicvault-duplicate-vote-ingest-fix-design.md
  docs/superpowers/plans/2026-06-04-civicvault-duplicate-vote-ingest-fix.md

## 2. What exists to build on
- The graph already RENDERS the Phase-4 predicates — this is an *ingestion + entity-
  resolution* problem, not a rendering one.
- Cited, directed `Relationship` model: catalog/models/relationship.py
  (predicate ∈ {board_member_of, employed_as, owns, contracts_with, donates_to,
  affiliated_with}; GenericFK subject/object; amount/role/occurred_on/source fields).
- The established ingest pattern to mirror EXACTLY (pure parser → frozen IR dataclass →
  agency-agnostic loader → thin management command):
  catalog/ingest/ir.py, catalog/ingest/loader.py, catalog/ingest/bcsd/*,
  catalog/management/commands/ingest_bcsd.py + ingest_recording.py.
- Review gate is load-bearing: everything new is `reviewed=False`; only `reviewed=True`
  reaches the public /graph. This is what makes aggressive external ingestion safe.

## 3. Phase 4 scope (keep it to ONE source this slice)
Populate predicates that can't come from minutes — `owns`, `donates_to`, `employed_as` —
from public external sources, each edge cited and reviewed. Recommended order:
**campaign finance (GA ethics.ga.gov) → IRS 990 (ProPublica API) → GA SOS**.
Do ONE source per slice. Recommend starting with **campaign-finance `donates_to`**
(cleanest structured data; directly "money into government").

Architecture for the slice: a new adapter under catalog/ingest/<source>/ emitting a common
`ParsedRelationship` IR; a generic `load_relationships(parsed, source)` in loader.py that
resolves endpoints to Person/Organization, creates `reviewed=False` Relationships, and
attaches a Citation; a thin `ingest_<source>` command with opt-in network (mock in CI).

## 4. Gotchas (don't relearn these)
- **Citations need evidence:** the `citation_has_evidence` CHECK requires a `document` or
  `transcript_segment`. Each external record must become a `Document` (kind report/other,
  source_url to the filing, optional R2 snapshot) so the Citation has something to point at.
- **Entity resolution is the crux** — matching "Jake Johnson" in a filing to the Person on
  the board. False merges create FALSE influence claims (worst failure for this product).
  Until Splink is wired, do conservative normalized/exact match + `reviewed=False` proposals;
  bias every ambiguous call toward "don't assert".
- **Dependency:** Phase 4 was meant to build on Phase 3's vendor *canonicalizer*, but only
  the Phase-3 duplicate-vote *ingest fix* shipped — **vendor normalization + amount capture
  are still un-built** (see docs/superpowers/PHASE3-FINISH-KICKOFF.md). Decide with the user
  whether to build the canonicalizer first or proceed with conservative matching.

## 5. Decisions to get from the user BEFORE writing the plan (ask one at a time)
1. Confirm **campaign-finance-first** as the slice.
2. **R2 snapshots vs cite-by-URL only** for external source records?
3. **Wire Splink now, or defer** behind the review gate with conservative matching until
   precision demands it?
4. Build the **Phase-3 vendor canonicalizer first**, or proceed and backfill?
5. Source access/terms: confirm bulk/scrape terms for the chosen source before committing.

## 6. Workflow (required)
Use the superpowers skills: brainstorming (HARD GATE: no code until a design is approved) →
writing-plans → subagent-driven-development (fresh subagent per task + two-stage review).
Write the spec to docs/superpowers/specs/2026-06-04-civicvault-phase4-<source>-design.md and
the plan to docs/superpowers/plans/2026-06-04-civicvault-phase4-<source>.md, matching the
Phase-3 files' format. After any UI change, verify in a browser and save shots to the
gitignored screenshots/. Memory index auto-loads; see graph-session-state + graph-review-gate.
````
