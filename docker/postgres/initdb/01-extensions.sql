-- Runs once on first cluster initialization (see docker-entrypoint-initdb.d).
-- Enables the extensions the brief pairs with native Postgres FTS:
--   pg_trgm  — trigram similarity for fuzzy/typo-tolerant matching (noisy OCR'd
--              names in entity resolution) and fast ILIKE.
--   unaccent — diacritic-insensitive text search.
-- Production (CloudNativePG) enables these via a Django migration instead; this
-- script covers local dev only.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
