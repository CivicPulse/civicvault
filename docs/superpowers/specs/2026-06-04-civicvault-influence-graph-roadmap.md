# CivicVault — Influence Graph Roadmap & Handoff (Phases 3, 4, 5)

**Created:** 2026-06-04. **Status:** high-level plan + handoff. **Audience:** the next agent (or human) continuing the relationship/influence-graph work.

This document is a *roadmap*, not a task-by-task plan. Each phase below gets its own detailed `docs/superpowers/plans/…` (TDD, checkbox, subagent-driven-development) when it is actually picked up. Read the "Where we are now" handoff first; it is the ground truth the three phases build on.

---

## TL;DR

The relationship graph can now draw **typed, directed, citation-backed edges** between entities, and it is populated with the two relationships the BCSD corpus can prove today: **board members → body** and **body → vendor contracts (with dollar amounts)**. The product goal — *"visualize how money and influence affect government decisions"* — needs three more things:

- **Phase 3 — Clean the data we already have.** De-duplicate vendor entities and capture dollar amounts reliably during ingest, so the contract layer is trustworthy and complete.
- **Phase 4 — Bring in the edges we can't derive from minutes.** External adapters for ownership, donations, and officer/board roles (`owns`, `donates_to`, `employed_as`). This is what makes a real conflict-of-interest chain *exist* in the graph.
- **Phase 5 — Let users follow the chain.** A "path between two entities" view that surfaces the influence path (e.g. a vendor's owner → a charity → that charity's CEO who sits on the board that approves the vendor's contract).

The hard rule across all three: **provenance is the product**. Every edge cites its source, and nothing `reviewed=False` reaches the public graph.

---

## Where we are now (handoff)

### What shipped (this body of work)

The influence-graph foundation is built, tested (185 passing), and committed on branch `feat/knowledge-graph` (not yet merged/pushed):

1. **`Relationship` model** — `catalog/models/relationship.py`. A `Reviewable`, directed, typed tie between any two entities:
   - `subject` / `object` are `GenericForeignKey`s (so the same model carries person→org and org→org, and later person→person).
   - `predicate` ∈ `{board_member_of, employed_as, owns, contracts_with, donates_to, affiliated_with}` (extend as needed).
   - `amount` (Decimal), `role` (e.g. "CEO"), `occurred_on` (date), `note`, `source` (FK to `Source` for idempotent rebuilds).
   - Provenance reuses the existing generic `Citation` (`catalog/models/citation.py`): a Citation points at a Relationship via `content_type`/`object_id`, exactly as it points at Votes/Motions today.
   - Migration `catalog/migrations/0013_relationship.py`.

2. **Derivation command** — `catalog/management/commands/build_relationships.py`. Conservatively derives, *only from what the corpus proves*:
   - `board_member_of`: from reviewed `Appearance(role=member)`, cited to the meeting's minutes document.
   - `contracts_with`: from agenda titles matching tight patterns (`Renewal of X`, `X - FY## Renewal`, `X - Contract`), creating cross-agency vendor `Organization(kind=company, jurisdiction=None)` rows; the dollar amount is lifted from `agenda_item.outcome_text`; cited to the meeting document.
   - Idempotent: owns a `derived-relationships` `Source`; each run deletes its own prior rows + their citations and rebuilds.
   - Creates `reviewed=False` proposals by default; `--review` flips them (and the vendor orgs) reviewed for dev visibility.

3. **Graph view rendering** — `core/views.py` `graph()`:
   - `GRAPH_TYPES` now splits organizations into **`body`** (violet) and **`vendor`** (blue) node types; `VENDOR_KINDS = {company, nonprofit, campaign}`.
   - Reads `Relationship` rows: `board_member_of` relabels the person↔body edge to "board member"; `contracts_with` adds directed body→vendor edges, dollar-summed, with the contracts as the edge payload.
   - Edge payload is generic: `{label, summary, rows:[{label, sub, note}], weight, kind}`. `rows` is the relationship detail (meetings for membership, contracts for vendors).
   - Review gate intact: only `reviewed=True` entities/relationships emitted.

4. **Front-end** — `core/static/core/js/graph.js`, `core/static/core/css/graph.css`, `templates/core/graph.html`:
   - Directed edges (SVG arrowhead marker, `fill: context-stroke` so the arrow matches edge color/state); clickable edges via a fat transparent hit-line per edge.
   - Contract edges render in money-gold (`.g-edge--contracts_with`); active state still Signal Cyan (One Signal Rule).
   - Relationship view in the rail: select two entities (modifier-click), click the edge, or click a connection in a node's rail → see the cited evidence (`summary` + `rows`).
   - Live search + type filters (Jurisdiction / Body / Vendor / Person), no-JS fallback list, full `prefers-reduced-motion` path.

5. **Tests** — `tests/test_graph_view.py` (graph shape, gate, relationship rendering), `tests/test_build_relationships.py` (derivation + idempotency + citations).

### Current dev data state

8 BCSD days / 16 meetings ingested; ~75% of facts reviewed (seeded). `build_relationships --review` has been run → **7 board-member** + **8 vendor-contract** edges (Renaissance Star 360 $2.0M, Imagine Learning $1.57M, Infinite Campus $415K, Amira Learning $255K, etc.). All 21 relationships are cited. See the `graph-review-gate` memory.

### Key facts & gotchas (do not relearn these the hard way)

- **Dollar amounts live in `agenda_item.outcome_text`** (38 items have them), **NOT `motion.result_text`** (0 motions carry `$`). 58 documents have `$` in `text`. This is the seam Phase 3 must formalize.
- **Vendor names are not yet normalized.** "School City" and "School City Assessment Platform" produce two separate vendor nodes today. Slug is `slugify(name)`. Phase 3 fixes this.
- **One source folder fails ingest:** `2025-09-18` committee (`mid-128424`) raises a duplicate-vote `IntegrityError` (Myrtice Johnson votes twice on an empty-titled agenda item). It was swapped for `2025-05-15`. A parser fix is owed (related to the consent-anchor / procedural-vote gaps noted in the root `HANDOFF.md`).
- **Org kinds already support the vision:** `Organization.Kind` has `company`, `nonprofit`, `campaign`. Vendors are `jurisdiction=None` (cross-agency) by design — this is what lets the same vendor unify across agencies later.
- **Entity resolution is the long pole** for Phase 4: matching "Jake Johnson" in a corporate filing to the `Person` who sits on the board is the hard part. The brief's stack (`project_brief.md` §3) names **Splink** for this; it is not yet wired up.
- **Citation requires evidence:** the `citation_has_evidence` CHECK means a Citation must have a `document` or `transcript_segment`. External-source relationships (Phase 4) will need a `Document` row representing the external record (e.g. a 990 PDF, a filing page) to cite against. Plan for that.

### How to run / verify

```bash
docker compose up -d db                 # Postgres on host port 5433
uv run pytest -q                        # expect 185 passing
uv run python manage.py build_relationships --review   # (re)derive edges in dev
uv run python manage.py runserver       # /graph/ to see it
uv run ruff check . && uv run ruff format --check .
```

---

## Phase 3 — Vendor normalization + amount capture

**Goal:** make the contract layer we already have trustworthy and complete: one node per real vendor, and a captured dollar amount on every contract action that states one.

**Why first:** it is low-risk, uses only data already in the corpus, and every later phase (and the path view) is more legible when vendors are de-duplicated and amounts are reliable. It also pays down the `2025-09-18` ingest bug.

### Scope

1. **Vendor entity resolution (lightweight).** Normalize vendor names before `get_or_create`:
   - Canonicalize: strip "FY## Renewal", "- Contract", "Approval of", legal suffixes (Inc/LLC/Co), case/whitespace.
   - Collapse known variants ("School City" ≡ "School City Assessment Platform") via a normalized key + a small alias map, OR a similarity pass (token-set ratio). Keep it conservative and reviewable; record collapses as `Organization.aka`.
   - This is the *seed* of the Splink-based resolution Phase 4 needs; build it so Phase 4 can reuse/escalate it.
2. **Amount capture in ingest.** Move dollar extraction out of the derivation command and into ingest, as structured data:
   - Add an `amount` (Decimal) to `Motion` and/or `AgendaItem` (decision below), populated by the BCSD minutes/agenda parser from `outcome_text` / motion result blocks.
   - `build_relationships` then reads the structured field instead of regexing `outcome_text` at graph-build time.
3. **Fix the `2025-09-18` duplicate-vote parser bug** (consent-anchor / procedural roll-call handling) so the 8th day and other affected folders ingest cleanly. Cross-reference root `HANDOFF.md` "Known limitations" #1 and #4.

### Files (anticipated)

- `catalog/ingest/bcsd/minutes_md.py` / `motions.py` — amount parsing; consent/procedural fix.
- `catalog/models/facts.py` or `meeting.py` — `amount` field + migration.
- `catalog/ingest/names.py` (or a new `catalog/ingest/orgs.py`) — vendor canonicalization, reused by the loader and `build_relationships`.
- `catalog/management/commands/build_relationships.py` — read structured amount; use the canonicalizer.

### Acceptance

- One vendor node per real vendor (no "School City" / "School City Assessment Platform" split); collapses recorded in `aka`.
- Contract edges show amounts wherever the source states one; "amount not recorded" only when the source truly omits it.
- `2025-09-18` committee ingests without error; all 8 demo days load via one command.
- Tests: canonicalization unit tests; amount-extraction tests against real fixture text; a regression test for the duplicate-vote folder.

### Risks

- Over-aggressive name collapsing merges two genuinely different vendors. Mitigation: conservative + reviewable (collapses are proposals, surfaced in `aka`, gated).
- Amount semantics: "not to exceed", annual vs total, multi-year. Capture the figure + the verbatim phrase in `note`; do not infer.

**Effort:** small–medium. No new external dependencies.

---

## Phase 4 — External relationship adapters (the influence layer)

**Goal:** populate the predicates that cannot be derived from meeting minutes — `owns`, `donates_to`, `employed_as` (CEO/officer) — from public external sources, each edge cited and reviewed. This is what turns the graph from "who attends and what we buy" into "who is connected to whom, and how the money flows."

**This is the big lift.** It is fundamentally an *ingestion + entity-resolution* problem, not a graph-rendering one (the rendering already supports these predicates).

### Data sources (Georgia / Bibb County first, agency-agnostic by design)

| Predicate | Source | Access | Notes |
|---|---|---|---|
| `owns`, `employed_as` (officers, registered agent) | **GA Secretary of State, Corporations Division** (eCorp business search) | Web search; bulk/download availability is limited | Gives officers, registered agent, control persons. Beneficial ownership is often not disclosed; capture what is filed. |
| `donates_to` (campaign contributions) | **GA Government Transparency & Campaign Finance Commission** (ethics.ga.gov) | Public search/exports | Contributions to candidate/committee filers, incl. local school-board races. The "money into politics" edge. |
| `employed_as`, nonprofit officers, grants | **IRS Form 990** | Bulk e-file XML (IRS / AWS open data); **ProPublica Nonprofit Explorer API** | Officers, key employees, compensation, grants. The "charity CEO" edge in the sketch. |
| (later) government contracts beyond minutes | GA procurement / USAspending (federal) | APIs | Lower priority for a local school district. |

### Architecture (mirror the existing ingest pipeline)

Follow the slice 1b/1c/1d pattern exactly (see root `HANDOFF.md`): **pure parser per source → frozen IR dataclass → agency-agnostic loader → thin management command.**

- One adapter per source under `catalog/ingest/<source>/` (e.g. `catalog/ingest/gasos/`, `catalog/ingest/ethics/`, `catalog/ingest/irs990/`), each emitting a common `ParsedRelationship` IR (subject descriptor, object descriptor, predicate, amount, date, source-record reference for citation).
- A generic `load_relationships(parsed, source)` in `catalog/ingest/loader.py` that resolves each endpoint to a `Person`/`Organization`, creates the `Relationship` (`reviewed=False`), and attaches a `Citation` to a `Document` representing the external record.
- New management commands `ingest_gasos` / `ingest_campaign_finance` / `ingest_990`, opt-in network like `--upload`/`--whisper`, mocked in CI.

### Entity resolution (the crux)

- Each external record names a person/org as a string; it must resolve to the *same* `Person`/`Organization` already in the graph. This is **Splink** territory (`project_brief.md` §3). Until Splink is wired, do conservative blocking + exact/normalized match, and emit `reviewed=False` proposals that an admin confirms (the gate is the safety net).
- Build on the Phase 3 canonicalizer. Cross-source resolution (same person across SOS + ethics + 990) is the new work here.
- A new-but-cited entity that resolves to nobody is still valuable: create the external `Person`/`Organization` (reviewed proposal) and the relationship; resolution can merge later.

### Provenance for external records

- Each external source record becomes a `Document` (kind `report`/`other`, `source_url` to the filing, optional stored snapshot in R2) so `Citation` has something to point at (satisfies `citation_has_evidence`). Decide: store a snapshot, or cite by URL only.

### Acceptance

- At least one external predicate end-to-end (recommend `donates_to` from campaign finance — cleanest structured data, directly "money into government"): real, cited, reviewed edges visible in the graph.
- A board member with a campaign-finance donor, or a vendor with a filed officer, renders as a multi-hop influence structure.
- Every external edge cites a retrievable source; nothing unreviewed shows publicly.

### Risks / open questions

- **Source availability & terms:** confirm bulk access / scraping terms per source before committing. GA SOS bulk data is the least certain.
- **Entity-resolution precision:** false merges create *false* influence claims — the worst possible failure for a provenance product. Keep everything reviewable; consider a confidence threshold below which edges stay hidden even when reviewed.
- **Scope creep:** do one source per slice. Recommend order: campaign finance → 990 → SOS.

**Effort:** large; one slice per source. Pulls Splink into the stack.

---

## Phase 5 — Path-finding: "influence chains"

**Goal:** the payoff feature. Select two entities and reveal the relationship path(s) between them, with every hop cited — e.g. *vendor → (owned by) → person → (donated to) → campaign → (of) → board member → (board member of) → body → (contracts with) → vendor*. This is how a user *sees* a conflict of interest instead of inferring it.

**Depends on Phase 4** for interesting chains (with only board-member + contract edges, paths are short). The mechanism can be built and demoed on current data first.

### Approach

- **Algorithm:** shortest path (and optionally up to *k* paths, bounded depth ~4–5) over the relationship edge set. At current scale, load the subgraph and BFS in Python. At scale, a Postgres recursive CTE over a `relationships` edge view, or a precomputed adjacency. Treat edges as **undirected for traversal** (a connection is a connection) but **render direction** on the result.
- **API:** `GET /graph/path/?from=<id>&to=<id>` → JSON: ordered nodes + the cited edge between each pair (reuse the edge payload shape). Respect the review gate (only traverse reviewed edges).
- **UI:** we already have two-node (modifier-click) selection and the relationship rail. Add a "Find path" affordance when two nodes are selected → highlight the path in the graph (dim everything else), and render the chain in the rail as a sequence of hops, each with its predicate, amount, and a citation link. Reuse the One Signal Rule (cyan path) and the existing dim/active machinery.
- **Framing:** label what the chain *means* without editorializing — show the facts and their sources; let the reader conclude. (Aligns with the brand: "authority through rigor, not decoration.")

### Files (anticipated)

- `core/views.py` — `graph_path` view + URL.
- `core/static/core/js/graph.js` — pair → "find path", path highlight, chain rail.
- `core/static/core/css/graph.css` — path/chain styles.
- Tests: path correctness (incl. no-path, multi-hop), gate (no path through unreviewed edges).

### Acceptance

- Selecting two connected entities shows a cited, directed chain in the rail and a highlighted path in the graph.
- "No path" is handled gracefully.
- Paths never traverse unreviewed edges.

### Risks

- Path explosion / cycles at scale → bound depth and result count; dedupe; `log` when truncated (no silent caps).
- Undirected-traversal vs directed-meaning can confuse; the rail must show each hop's real direction and predicate.

**Effort:** medium. Mostly new traversal + a focused UI addition; the rendering substrate exists.

---

## Cross-cutting principles (apply to all three)

- **Provenance is non-negotiable.** Every materialized edge has ≥1 `Citation` to a retrievable source. No citation → it does not ship.
- **Review gate is the safety net.** Everything new is `reviewed=False` until an admin confirms; the public graph already filters on `reviewed=True`. This is what makes aggressive external ingestion safe.
- **Agency-agnostic core.** Source-specific parsing lives in `catalog/ingest/<source>/`; resolution, loading, and rendering stay generic. Bibb County is the proving ground, not the boundary.
- **False edges are worse than missing edges** for an accountability tool. Bias every ambiguous call toward "don't assert."
- **Reuse the pipeline shape** (pure parser → IR → generic loader → thin command) and the subagent-driven-development + two-stage-review process used for slices 1b–1d.

## Sequencing & dependencies

```
Phase 3 (clean current data) ── independent, do first
        │
        ├─> Phase 4 (external edges) ── needs Phase 3's canonicalizer; pulls in Splink
        │
        └─> Phase 5 (path-finding) ── mechanism buildable now; valuable after Phase 4
```

Recommended order: **3 → 4 (campaign finance slice) → 5 (path mechanism) → 4 (990, then SOS)**, interleaving 5 once the first external source lands so the payoff is visible early.

## Open decisions for the user

1. **Amount home (Phase 3):** put `amount` on `Motion`, on `AgendaItem`, or both? (Motions are the action; agenda items are the unit users query.)
2. **External source order (Phase 4):** confirm campaign-finance-first, and confirm we may snapshot external records to R2 for durable citations (vs cite-by-URL only).
3. **Path semantics (Phase 5):** undirected traversal with directed display — acceptable? And the max hop depth.
4. **Splink now or later:** wire Splink in Phase 4, or defer with conservative matching + the review gate until precision demands it?

## Start-of-session checklist (continuing this work)

1. `git checkout feat/knowledge-graph` (or merge it to `main` first — coordinate with the user; this branch is not yet pushed).
2. `docker compose up -d db`; `uv run pytest -q` → expect **185 passing**.
3. `uv run python manage.py build_relationships --review`; open `/graph/` to see current state.
4. Read this doc's "Where we are now" + the `graph-review-gate` memory + root `HANDOFF.md` (consent-anchor / procedural-vote limitations relevant to Phase 3).
5. Pick a phase; write its detailed `docs/superpowers/plans/2026-…-civicvault-<phase>.md` (TDD, checkbox, subagent-driven-development) before touching code; brainstorm first.
