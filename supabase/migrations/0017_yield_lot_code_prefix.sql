-- Yield product lot code prefix (0017)
-- =====================================
-- Each yield_product can carry a short lot-code prefix (e.g. "TK" for
-- Toscano Kale) so harvest entries get a consistent, traceable lot code
-- without retyping it every time — the kiosk/office entry form auto-fills
-- the lot code field with the selected product's prefix. Purely advisory
-- text; no format is enforced, and yield_entries.lot_code stays free TEXT
-- (the employee can still edit/extend it per entry, e.g. adding a date or
-- sequence suffix).
--
-- Table DDL is also in backend/app/admin_schema.py (runs on API boot).
--
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0017_yield_lot_code_prefix.sql

BEGIN;

ALTER TABLE yield_products ADD COLUMN IF NOT EXISTS lot_code_prefix TEXT;

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   ALTER TABLE yield_products DROP COLUMN IF EXISTS lot_code_prefix;
