# Civic Knowledge Base

A public, web-first knowledge base for **local government** — meetings, documents, policies, people, organizations, money, and the relationships between them.

Anyone can search the full archive, open a profile for a person, organization, or meeting, see every fact traced back to its source document, follow the connections through an interactive graph, jump from a transcript hit to the exact second of a meeting video, and share any view as a plain URL — all without an account.

> **Guiding principle: provenance.** For an accountability tool, trust is the product. Every asserted fact links back to the document (and location) that evidences it. Nothing is claimed without a citation.

---

## Scope & vision

The goal is a single place to explore the public record across **many government agencies and organizations** — school districts, city and county governments, boards, authorities, committees, campaigns, vendors, and the people who move between them. Much of the value comes from connecting records *across* those bodies: the same vendor, official, or dollar appearing in more than one place.

The platform is **agency-agnostic by design**. Every agency or organization is modeled as just another entity, so new bodies are added by writing an ingestion adapter for their records — not by changing the core.

**Starting dataset:** the **Bibb County (GA) Board of Education / School District** — a large existing archive of meetings (2013–present), policies, and documents. It is the first agency onboarded and the proving ground for the model and pipeline; it is the beginning of the project, not its boundary.

**Primary user:** anonymous members of the public. **Built and operated by:** a solo maintainer. **Software:** open-source and self-hostable.

---

## Why this exists

Local government generates a large, scattered public record — agendas, minutes, contracts, policies, hours of meeting video — spread across many bodies and portals. It is technically "public" but practically hard to search, cross-reference, or share. This project turns those records into a single, searchable, source-linked knowledge base that makes the public record usable by ordinary residents, journalists, and researchers — and, as more agencies are added, makes the connections *between* them visible.

---

## What it does

- **Full-text search** across all documents *and* meeting-video transcripts, with filters (agency, type, date, meeting).
- **Profiles** for people, organizations, and meetings — each fact footnoted to its source.
- **Knowledge graph** of relationships between people and organizations, *across agencies*: color-coded, filterable, shareable.
- **Timestamped video** — a transcript match links straight to that moment in the meeting recording on YouTube.
- **Voting records** — per-member votes parsed from the minutes.
- **Vendor / contract activity** — who bid, who was awarded, and for how much, across the bodies they deal with.
- **Shareable URLs** — every search, profile, and graph view is a stable link you can text to someone.
- **Open access for tools** — a public read API (planned) so researchers can use the data programmatically instead of scraping.

---

## Technology

Built to keep a solo operator's footprint small — one datastore doing most of the work, batteries-included frameworks, and reuse of existing infrastructure.

- **PostgreSQL** as the system of record (relational data, full-text search, and graph queries — no separate search engine or graph database to run).
- **Django + Django REST Framework** for the app, admin, and API.
- **Server-rendered templates + HTMX**, with **Sigma.js** for the relationship graph.
- **Cloudflare R2** for media (zero egress fees), behind the existing **Cloudflare Tunnel + Traefik** ingress.
- **Splink** for entity resolution; **Procrastinate** for background ingestion jobs.
- Deployed on **Kubernetes**; **CloudNativePG** with backups to R2.

The full rationale, upgrade paths, and "don't over-build" guidance are in the project brief.

---

## Project status

**Pre-implementation / building toward MVP.** The data model, ingestion strategy, and architecture are specified, and the first agency's archive (Bibb County BOE) has been inventoried and its formats validated. Onboarding the first dataset comes first; additional agencies follow once the model and pipeline are proven. See the brief for the MVP scope and build order.

---

## Local development

Python is managed with [`uv`](https://docs.astral.sh/uv/); the database runs in Docker.

```bash
# 1. Install dependencies into a local virtualenv.
uv sync

# 2. Create your env file and start Postgres (compose.yaml is local-dev only).
cp .env.example .env
docker compose up -d db

# 3. Apply migrations and run the app.
uv run python manage.py migrate
uv run python manage.py runserver
```

The app reads `DATABASE_URL` from `.env` and connects to the compose Postgres on
`localhost:5433` (user/password/db all `civicvault`; host port 5433 avoids
clashing with a host-installed Postgres). The container preloads the
`pg_trgm` and `unaccent` extensions on first start. Liveness check:
`curl http://127.0.0.1:8000/healthz/` → `{"status": "ok"}`.

If `DATABASE_URL` is unset, Django falls back to a local SQLite file.

---

## Documentation

### [`project_brief.md`](./project_brief.md) — the detailed build brief

The single source of truth for implementation. Read this before writing code. It specifies the platform architecture and the onboarding of the **first dataset (Bibb County BOE)**; the same patterns generalize to future agencies. It contains:

- **Locked technology decisions** — the stack above, with rationale and explicit upgrade paths.
- **The first archive's verified ground truth** — the four data trees, their layouts, naming conventions, and scale (≈ 23,000 files spanning 2013–present).
- **File-format specifications** — exactly how to parse meeting folders, `event.md`, `minutes.md` (rosters, the four motion-block formats, per-member roll-call votes), recording sidecars, `info.json`, and the transcript `.vtt` files.
- **The recording↔meeting matching algorithm** — handling combined committee+board recordings, upload-date-vs-meeting-date mismatches, duplicate uploads, and non-meeting videos.
- **The data model** — a complete, agency-agnostic data dictionary (entities, fields, relationships) with the provenance/citation backbone.
- **The ingestion pipeline** — the three-source-plus-join design, including OCR verification.
- **A consolidated gotchas checklist** — the dozen-plus real-world quirks that will otherwise trip up an implementation.
- **MVP scope, a suggested build order, and open verification items.**

> As additional agencies are onboarded, each gets its own ingestion notes; the core architecture and data model described in the brief stay the same.

---

## License

Open source — license to be finalized. (All ingested source material is government public record.)