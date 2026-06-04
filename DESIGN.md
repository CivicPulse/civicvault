---
name: CivicVault
description: An intelligence-database interface for the public record — dense, cited, terminal-native.
---

<!-- SEED: re-run /impeccable document once there's code to capture the actual tokens, tonal ramps, and component snippets. The colors below are the provisional anchors chosen during init, not finalized tokens. -->

# Design System: CivicVault

## 1. Overview

**Creative North Star: "The Open Dossier"**

CivicVault looks and feels like the case-file terminal of an intelligence agency — turned inside out and pointed at the *public* record. The room is dark and quiet; the data glows. A near-black field carries every screen, and a single cold signal color (electric cyan) marks what is live, linked, or active. Monospace type appears wherever a value must read as *exact* — an ID, a timestamp, a dollar amount, a vote tally, a transcript line — while a tight neutral grotesk carries headings and labels. The defining surface is the relationship graph: a constellation of glowing entity nodes over the dark field, agencies and people and dollars connected by faint lines. Density is welcome; these users came to dig.

The metaphor is structural, never costume. There are no CLASSIFIED stamps, no redaction bars, no fake clearance levels — the entire purpose of the product is to make the record *open*, so decorative secrecy would be a lie. The "agency database" feel is earned by genuine information density, citations on every fact, and the restraint of a serious instrument. Motion is responsive but disciplined: hover and focus feedback, content swaps as filters and searches resolve, a brief "resolving" beat when data loads — never scroll-driven theatrics, never a Hollywood HUD.

This system explicitly rejects three things: the rounded-pastel-card SaaS product page (this is an instrument, not a launch), literal redaction theater (the metaphor lives in the information architecture, not in costume), and the dreary blue-and-gray government portal with cramped unstyled tables (dense is the goal; dreary is failure). The calibration points are **Palantir Gotham** (the dark, entity-and-graph-driven intel surface — borrowed structurally) and **Linear, dark mode** (tight grotesk type, fast keyboard-driven interaction, one restrained accent — the proof that "dark and serious" need not be dreary or cosplay).

**Key Characteristics:**
- Dark-surface committed palette: a near-black cool field carries the screen; one cold cyan accent does all the signaling.
- Mono-for-data, grotesk-for-everything-else typography.
- The relationship graph is the signature component — glowing nodes on a dark field.
- Provenance is visible: a citation or source link is never more than one element away from any asserted fact.
- Restrained, responsive motion with a mandatory reduced-motion path.

## 2. Colors

A **Committed dark-surface** strategy: a single near-black cool field dominates 30–60%+ of every screen, and one cold signal color carries links, active states, and "live data." Color is rationed; its rarity is what makes it read as signal. *(Provisional seed anchors below — to be finalized as real tokens, with tonal ramps, on the next scan-mode run.)*

### Primary
- **Signal Cyan** (`oklch(75% 0.14 215)`): the one accent. Links, active/selected states, focus rings, "live" or freshly-ingested data, the current node in the graph. Used on a small fraction of any screen — never as a fill for large areas.

### Neutral
- **Vault Black** (`oklch(18% 0.02 240)`): the dominant field. Near-black with a faint cool tint so it reads as a deliberate cold surface, not a muddy gray.
- **Readout White** (`oklch(92% 0.01 240)`): primary text. Sits at ≥ 4.5:1 on Vault Black — body legibility is non-negotiable on the dark field.
- **Steel Muted** (`oklch(62% 0.02 240)`): secondary text, metadata, timestamps, dividers. Must still clear 4.5:1 for any text that carries meaning; reserve sub-4.5:1 tints for non-text hairlines only.

### Tertiary (graph only)
- **Agency hues** `[to be resolved during implementation]`: the relationship graph color-codes nodes by agency. These hues live *only* in the graph, are chosen for color-blind distinguishability, and are **always** paired with a label or shape — color is never the sole carrier of agency identity.

### Named Rules
**The One Signal Rule.** Cyan means *something is live, linked, or active*. It is never decoration. If cyan appears on a static, non-interactive element, it is wrong.

**The No-Costume Rule.** No `CLASSIFIED` stamps, no black redaction bars, no fake clearance badges, ever. The dossier metaphor is carried by structure (citations, case-file profiles, the graph), not by props.

## 3. Typography

**Display Font:** A tight neutral grotesk `[family to be chosen at implementation — e.g. a precise grotesk in the spirit of Inter/Söhne/Geist]`
**Body Font:** Same grotesk family, regular weights, for prose (minutes, descriptions, longer reading).
**Label/Mono Font:** A monospace `[family to be chosen — e.g. a clean coding mono like Geist Mono / JetBrains Mono]`

**Character:** Grotesk carries the human-readable voice — calm, dense, authoritative. Mono is reserved for *data that must read as exact*: IDs, timestamps, dollar amounts, vote tallies, transcript line markers, video timecodes, citations. The contrast between the two is the typographic tell of the whole system — proportional = narrative, mono = evidence.

### Hierarchy
- **Display** (grotesk, tight, `clamp` max ≤ 6rem, letter-spacing ≥ -0.04em): page/entity titles. Used sparingly; this is an instrument, not a hero-driven landing.
- **Headline** (grotesk, semibold): section headers within a profile or results view.
- **Title** (grotesk, medium): card/row titles, entity names in lists.
- **Body** (grotesk, regular, line-height ~1.6, max 65–75ch): minutes, descriptions, outcome paragraphs.
- **Label** (grotesk or mono, uppercase ≤ 4 words only, restrained tracking): filter labels, column headers, status chips.
- **Data** (mono): the evidence layer — timestamps, `$5,515,711.09`, vote counts, document IDs, transcript markers.

### Named Rules
**The Evidence-is-Mono Rule.** If a value is a citation, an identifier, a timestamp, or a number that someone might quote or verify, it is set in mono. Narrative prose is never mono.

## 4. Elevation

Mostly **flat, with light tonal layering** — depth comes from subtly lighter near-black surfaces stacked on the Vault Black field, not from drop shadows. This suits both the dark palette (shadows read poorly on near-black) and the responsive-but-restrained motion energy. The one sanctioned use of *glow* (not shadow) is the relationship graph: nodes carry a faint cyan/agency-hue bloom so the constellation reads as luminous data. That glow is the single permitted "HUD" flourish and must stay subtle — bloom, not neon.

### Named Rules
**The Tonal-Layer Rule.** Surfaces separate by getting *lighter* (a step up from Vault Black), never by casting a shadow. Reserve glow exclusively for graph nodes and active focus rings.

## 5. Components

No components exist yet (the app is a skeleton). The forward-looking priorities, once building begins:

- **The Relationship Graph** — the signature component. Glowing entity nodes on the dark field, agency-colored *and* labeled/shaped, faint connecting lines, focus/expand interaction. This is the visual identity; build it with the most care.
- **Search + results** — dense, scannable rows; mono for IDs/dates/amounts; a transcript hit links straight to the video second.
- **Entity profile (the "dossier")** — every asserted fact footnoted to its source, citation one element away.

Real component tokens, states, and snippets land on the next scan-mode `/impeccable document` run.

## 6. Do's and Don'ts

### Do:
- **Do** keep a near-black cool field (`oklch(18% 0.02 240)`-ish) as the dominant surface and ration Signal Cyan to interactive/live elements only.
- **Do** set every citation, ID, timestamp, dollar amount, and vote tally in **mono**, so evidence reads as exact.
- **Do** keep body text at ≥ 4.5:1 against the dark field — verify contrast; never let "muted for mood" drop meaningful text below the bar.
- **Do** make the relationship graph luminous and central, with nodes encoded by **label/shape as well as color**.
- **Do** give every HUD/terminal/reveal motion a `prefers-reduced-motion: reduce` fallback (crossfade or instant).

### Don't:
- **Don't** make it look like a SaaS / startup product page — no rounded pastel cards, gradient hero blobs, mascots, or marketing-landing tropes. This is an instrument, not a launch.
- **Don't** use literal redaction theater — no black redaction bars, `CLASSIFIED` stamps, or fake clearance levels as decoration. The metaphor is structural, never costume.
- **Don't** fall into dreary government-portal styling — no bland blue-and-gray, cramped unstyled tables, or clip-art. Dense is the goal; dreary is failure.
- **Don't** tip the terminal cues into Hollywood VFX — no neon glows, scanlines, hex-grid overlays, or Matrix-rain green. Restrained intel-terminal, not a movie effect.
- **Don't** let color be the only signal for agency in the graph — pair every hue with a label or shape.
