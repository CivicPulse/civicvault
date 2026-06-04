# Phase 3 (finish) — Kickoff prompt

Copy everything in the fenced block below into a fresh Claude Code session started in this repo.
Phase 3's duplicate-vote **ingest fix** already shipped (merged to local `main`, `4cf4630`);
this kickoff finishes the two remaining pieces: **vendor normalization** + **amount capture**.

````text
You're picking up CivicVault, a Django civic-transparency app. The active work is the
relationship/influence graph. Phase 3 is partly done: the duplicate-vote **ingest fix**
shipped (merged to local main, 4cf4630). Your job is to FINISH Phase 3 — the two remaining
pieces: **vendor normalization** and **amount capture**. Do NOT start coding:
brainstorm → write a spec → write a plan → then execute.

## 0. First five minutes (orient before reading)
cd /media/kwhatcher/Storage/civicvault
git branch --show-current            # expect: main
git log --oneline -3                 # tip should be 4cf4630
git status --short                   # clean tree
docker compose up -d db              # Postgres on host port 5433 (.env points here)
uv run pytest -q                     # expect: 193 passed
uv run python manage.py build_relationships --review   # 7 board-member + 14 vendor-contract edges
uv run python manage.py runserver    # open http://127.0.0.1:8011/graph/ to see today's state

ALWAYS `uv run` for Python (never system python); `uv add` for deps. Ruff-clean before every
commit (`uv run ruff check . && uv run ruff format --check .`). Conventional Commits. Commit
on a BRANCH, not main. **Never push to GitHub**; never merge to main without an explicit ask
(local main is 23 commits ahead of origin/main, intentionally unpushed).

## 1. Read these, in order
- docs/superpowers/specs/2026-06-04-civicvault-influence-graph-roadmap.md  ← read
  "Where we are now", then the **Phase 3** section in full (scope, files, acceptance, risks).
- As a pattern reference for the spec/plan format and the TDD + subagent workflow you'll
  follow, skim the just-shipped Phase-3 ingest-fix pair:
  docs/superpowers/specs/2026-06-04-civicvault-duplicate-vote-ingest-fix-design.md
  docs/superpowers/plans/2026-06-04-civicvault-duplicate-vote-ingest-fix.md
- Memory auto-loads: graph-session-state, graph-review-gate.

## 2. The two pieces to build
### A. Vendor normalization (entity resolution, lightweight)
Today "School City" and "School City Assessment Platform" become two separate vendor nodes.
Normalize vendor names before get_or_create so it's one node per real vendor.
- Canonicalize: strip "FY## Renewal", "- Contract", "Approval of", legal suffixes (Inc/LLC/Co),
  case/whitespace. Collapse known variants via a normalized key + small alias map, OR a
  conservative similarity pass (token-set ratio). Record collapses in `Organization.aka`.
- Keep it CONSERVATIVE and REVIEWABLE — collapses are proposals, surfaced in `aka`, gated by
  reviewed=True. Over-merging two genuinely different vendors is the failure to avoid.
- Build it so Phase 4's Splink-based resolution can reuse/escalate it (this is the seed).
- Mirror the person-name analog: catalog/ingest/names.py (normalize_name/split_name_and_role).
  Put org canonicalization in catalog/ingest/names.py or a new catalog/ingest/orgs.py, reused
  by BOTH the loader and build_relationships.

### B. Amount capture in ingest
Move dollar extraction out of build_relationships (it currently regexes
`agenda_item.outcome_text` at graph-build time via `largest_amount()`) into ingest as
STRUCTURED data.
- Add an `amount` (Decimal) field to Motion and/or AgendaItem (DECISION below) + migration.
- Populate it from the BCSD parser. Then build_relationships reads the structured field.
- Semantics nuance: "not to exceed", annual vs total, multi-year. Capture the FIGURE plus the
  verbatim phrase (e.g. in a note/amount_text field); do NOT infer. Contract edges should show
  an amount wherever the source states one, and "amount not recorded" only when it truly omits.

## 3. Key facts & gotchas (don't relearn these)
- Dollar amounts live in **agenda_item.outcome_text** (38 items have them), NOT
  motion.result_text (0 motions carry $). 58 documents have $ in text. This is the seam.
- Current code to refactor: catalog/management/commands/build_relationships.py
  (`vendor_name()`, `largest_amount()`, `VENDOR_PATTERNS`, `MONEY`, `slugify(name)` for vendor slug).
- Models: catalog/models/org.py (Organization has `aka` ArrayField, Kind company/nonprofit/
  campaign, jurisdiction=None for cross-agency vendors, slug uniqueness constraints);
  catalog/models/facts.py (Motion); catalog/models/meeting.py (AgendaItem).
- BCSD parser: catalog/ingest/bcsd/minutes_md.py + agenda_md.py; loader catalog/ingest/loader.py;
  IR catalog/ingest/ir.py. Mirror the pure-parser → IR → generic loader → thin command pattern.
- Migrations: `uv run python manage.py makemigrations` then `migrate`; review the generated file.
- Review gate: everything new is reviewed=False; only reviewed=True shows on /graph. Vendor
  collapses must be reviewable, not auto-applied.
- Dev data: `build_relationships --review` re-derives edges; the dev DB has BCSD meetings with
  ~75% reviewed (a one-off seed, not committed).

## 4. Decisions to get from the user BEFORE writing the plan (ask one at a time)
1. **Amount home:** `amount` on Motion, on AgendaItem, or both? (Motions are the action; agenda
   items are the unit users query. Roadmap leans toward AgendaItem.)
2. **Canonicalization strategy:** alias-map only / normalized-key / token-set similarity — and
   how aggressive (conservative is the default for an accountability tool).
3. Whether to also capture the verbatim amount phrase (and where), given "not to exceed"/multi-year.

## 5. Acceptance (from the roadmap)
- One vendor node per real vendor (no "School City" split); collapses recorded in `aka`.
- Contract edges show amounts wherever the source states one; "amount not recorded" only when
  the source truly omits it.
- Tests: canonicalization unit tests; amount-extraction tests against real fixture text.
- ruff clean; full suite green; small commits on a branch.

## 6. Workflow (required)
superpowers skills: brainstorming (HARD GATE: no code until a design is approved) →
writing-plans → subagent-driven-development (fresh subagent per task, two-stage review).
Roadmap groups these two pieces in ONE spec/plan together. Write spec to
docs/superpowers/specs/2026-06-04-civicvault-phase3-vendor-amount-design.md and plan to
docs/superpowers/plans/2026-06-04-civicvault-phase3-vendor-amount.md, matching the existing
files' format. After any UI change, verify in a browser and save shots to gitignored screenshots/.
````
