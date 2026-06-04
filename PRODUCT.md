# Product

## Register

product

## Users

Anonymous members of the public — no account, no login. Three concrete shapes of
that user:

- **Residents** checking on their local government: what was decided, who voted
  how, where their money went. Low patience, varied tech literacy, often arriving
  from a shared link or a search engine on a phone.
- **Journalists** working a story: looking for a specific vote, contract, vendor,
  or official, and needing to cite the exact source quickly and confidently.
- **Researchers** doing systematic work across many records and, increasingly,
  across multiple agencies — following the same vendor, official, or dollar from
  one body to another.

The shared job: **find a fact in the public record, trust it, and share it** —
without having to scrape portals, download PDFs, or scrub through hours of meeting
video. Their context is investigative and accountability-driven, not casual
browsing.

## Product Purpose

CivicVault turns the scattered public record of local government — agendas,
minutes, contracts, policies, hours of meeting video — into a single, searchable,
**source-linked** knowledge base. Anyone can full-text search documents and video
transcripts, open a profile for a person / organization / meeting, follow
relationships through an interactive graph, jump from a transcript hit to the exact
second of the video, and share any view as a stable URL.

The platform is **agency-agnostic by design**: every agency is just another entity,
onboarded by writing an ingestion adapter, not by changing the core. The first
dataset is the Bibb County (GA) Board of Education — the proving ground, not the
boundary. Much of the long-term value is *cross-agency*: the same vendor, official,
or dollar surfacing in more than one body.

Success looks like: a resident, journalist, or researcher answers a question about
their local government in minutes instead of hours, lands on a fact they can trust
because it cites its source, and shares it as a link that shows the same thing to
the next person.

## Brand Personality

**Utility-first, with the feel of an intelligence-agency database.** Think the
fictional dossier/case-file terminal from a spy thriller — dense, authoritative,
built for someone who is *digging*, not being marketed to. The aesthetic is
terminal-native and evidence-forward: monospace and structured data where it earns
its place, calm and precise everywhere. Restrained HUD / terminal touches are
welcome when they reinforce the "serious instrument" feel; they must never become
the point.

Three words: **authoritative, precise, instrumental.**

Emotional goal: the user should feel they've been handed a *serious instrument* for
interrogating the public record — one that is fast, exacting, and never asks them to
take its word for anything. Credibility comes from rigor and provenance, not polish
or persuasion.

## Anti-references

- **Not a SaaS / startup product page.** No rounded pastel cards, gradient hero
  blobs, friendly mascots, or marketing-landing tropes. This is an instrument, not a
  launch.
- **Not literal redaction theater.** No black redaction bars, "CLASSIFIED" stamps,
  or fake clearance levels as decoration. The intelligence-database metaphor must be
  carried *structurally* (case-file information architecture, dossier-style profiles,
  citations everywhere) — never as costume. Decorative secrecy would undercut a tool
  whose entire purpose is making the record *open*.
- **Not a dreary government portal.** No bland blue-and-gray municipal-website
  feel, cramped unstyled tables, or clip-art. Dense is good; dreary is failure.
- **Acceptable, in moderation:** restrained sci-fi / HUD / terminal cues (subtle
  glow, monospace, scan-line-free structure) — used to signal "serious instrument,"
  kept legible and never tipping into Hollywood VFX or Matrix-rain cosplay.

## Design Principles

1. **Provenance is the product.** Every asserted fact links back to the document
   (and the location inside it) that evidences it. The path from a claim to its
   source — a PDF page, a transcript line, a video timestamp — is always one step
   away. Nothing is shown as fact without a citation; trust is the deliverable.
2. **Agency-agnostic, always.** The interface never special-cases the first
   dataset. Every agency is just another entity. If a screen only makes sense for
   Bibb County, it's wrong. Design for the cross-agency record from day one.
3. **The record is the star; chrome recedes.** Utility-first. Density is a feature,
   not a flaw — these users came to dig. Navigation, decoration, and brand sit behind
   the data and the evidence, not in front of them.
4. **Authority through rigor, not decoration.** The serious-instrument feel is
   *earned* by precision, legibility, and honest data — not by visual effects. When a
   choice is between looking impressive and being exact, be exact.
5. **Public and shareable by default.** Every search, profile, and graph view is a
   stable, accountable URL — no login, no gatekeeping. Transparency is structural:
   what one person can see and cite, anyone can.

## Accessibility & Inclusion

Target **WCAG 2.2 AA**, with extra care for the failure modes a dark/terminal
aesthetic invites:

- **Contrast on dark surfaces:** body text ≥ 4.5:1, large text ≥ 3:1, against the
  actual dark background — not muted gray "for mood." This is the single easiest
  thing to get wrong here and the first thing to check.
- **Keyboard and screen-reader first:** full keyboard navigation; transcript jumps,
  graph controls, and filters all reachable and announced. Link text stands alone.
- **Motion is optional:** every HUD / terminal / reveal animation needs a
  `prefers-reduced-motion: reduce` alternative (crossfade or instant). Motion never
  gates content visibility.
- **Color is never the only signal:** the knowledge graph is color-coded by agency,
  so agency must *also* be conveyed by label, shape, or text — color-blind users must
  never lose information that sighted users get from hue alone.
