-- Yield employees (0015)
-- ======================
-- A roster so the harvest kiosk's "harvested by" field is a tap-to-pick
-- Select instead of typing a name every time. yield_entries.harvested_by
-- stays free TEXT (no FK) — this is a curated suggestion list, not a
-- referential-integrity change, so renaming/retiring/deleting an employee
-- never touches existing entry history.
--
-- Table DDL is also in backend/app/admin_schema.py (runs on API boot).
-- RLS is auto-enabled by the 0005 event trigger (deny-all, backend-only).
--
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0015_yield_employees.sql

BEGIN;

CREATE TABLE IF NOT EXISTS yield_employees (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_yield_employees_active ON yield_employees (active);

-- Seed from any harvested_by names already on record, so existing entry
-- history isn't orphaned from the new roster.
INSERT INTO yield_employees (name)
SELECT DISTINCT btrim(harvested_by) FROM yield_entries
WHERE harvested_by IS NOT NULL AND btrim(harvested_by) <> ''
ON CONFLICT (name) DO NOTHING;

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   DROP TABLE IF EXISTS yield_employees;
