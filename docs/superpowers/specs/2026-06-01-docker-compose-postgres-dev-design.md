# Docker Compose Postgres dev environment — design

**Date:** 2026-06-01
**Status:** Approved
**Build-order step:** Completes the Postgres + Docker Compose portion of §12 step 1
("Repo + infra skeleton") in `project_brief.md`.

## Goal

Provide a one-command local Postgres for development and make Postgres the active
dev database, so the upcoming schema work (generic-FK provenance, FTS
`SearchVector` + GIN indexes, trigram-based entity resolution) runs against the
same engine as production. Per brief §3, Docker Compose is **local dev only** — it
does not mirror production's CloudNativePG-managed Postgres.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Stack scope | Postgres only | Django runs on the host via `uv run`, matching the project's uv-first workflow. Lightest, fastest iteration. |
| Postgres version | `postgres:17` | Within the brief's pinned 16/17 range; latest stable major. |
| Extensions | `pg_trgm`, `unaccent` | Trigram similarity for fuzzy/typo-tolerant matching of noisy OCR'd names (entity resolution) and fast `ILIKE`; diacritic-insensitive search. Both ship in the official image. |
| Dev DB default | Switch dev to Postgres now | Schema work next leans on Postgres-specific features; dev-on-SQLite would drift. SQLite remains the in-code fallback when `DATABASE_URL` is unset. |

## Components

1. **`compose.yaml`** (repo root) — single `db` service:
   - `image: postgres:17`
   - environment with overridable defaults: `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`,
     all defaulting to `civicvault`
   - `ports: ["${POSTGRES_PORT:-5433}:5432"]` — published on host **5433** because a
     host-installed Postgres already holds 5432; container-internal port stays 5432
   - named volume `pgdata` mounted at `/var/lib/postgresql/data` for persistence
   - bind-mount `./docker/postgres/initdb` → `/docker-entrypoint-initdb.d:ro`
   - `pg_isready` healthcheck so scripts can wait for readiness before migrating
   - no top-level `version:` key (obsolete in modern Compose); no `depends_on` (single service)

2. **`docker/postgres/initdb/01-extensions.sql`** — runs once on first cluster init:
   ```sql
   CREATE EXTENSION IF NOT EXISTS pg_trgm;
   CREATE EXTENSION IF NOT EXISTS unaccent;
   ```

3. **Driver dependency** — `psycopg[binary]` added via `uv add`. Django 6 speaks
   psycopg 3; without the driver, `migrate` against Postgres fails at import time.

4. **Environment wiring**:
   - `.env.example`: document
     `DATABASE_URL=postgres://civicvault:civicvault@localhost:5433/civicvault`
     and the optional `POSTGRES_*` override vars.
   - local `.env` (gitignored): set that `DATABASE_URL` so dev uses Postgres now.

5. **`README.md`** — a short "Local development" section:
   `docker compose up -d db` → `uv run python manage.py migrate` → `runserver`.

## Data flow

`uv run` Django process on host → reads `DATABASE_URL` from `.env` via
`django-environ` → connects to the `db` container published on `localhost:5432`
→ psycopg 3 → Postgres 17 with `pg_trgm`/`unaccent` preloaded.

## Production-parity note (not built in this task)

Production uses CloudNativePG, not this compose file, so `initdb` scripts do not
run there. When step 2 introduces migrations, the same extensions will be enabled
via a Django migration (`django.contrib.postgres.operations.TrigramExtension`,
`UnaccentExtension`) so every environment converges. The init script covers dev
only.

## Verification

1. `docker compose up -d db`; wait for the healthcheck to report healthy.
2. `uv run python manage.py migrate` — applies Django's built-in app tables to Postgres.
3. `uv run python manage.py check` — no issues.
4. `uv run python manage.py runserver`; `curl /healthz/` returns `{"status":"ok"}` 200,
   confirming the app talks to Postgres.
5. `ruff check` + `ruff format --check` pass before commit.

## Out of scope (YAGNI)

App container, DB admin UI (Adminer/pgAdmin), Redis, ParadeDB/Apache AGE images,
production K8s/CloudNativePG manifests.
