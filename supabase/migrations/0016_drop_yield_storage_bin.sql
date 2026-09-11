-- Drop yield_entries.storage_bin (0016)
-- ======================================
-- Turned out not to be needed — dropped rather than left as unused, dead
-- column. No production data existed in this column at the time of removal
-- (yield_entries was empty), so this is a clean drop, not a migration of
-- existing values.
--
-- Also removed from backend/app/admin_schema.py's CREATE TABLE (self-applies
-- on API boot) and the yield_entries block in /schema.sql.
--
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0016_drop_yield_storage_bin.sql

BEGIN;

ALTER TABLE yield_entries DROP COLUMN IF EXISTS storage_bin;

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   ALTER TABLE yield_entries ADD COLUMN storage_bin TEXT;
