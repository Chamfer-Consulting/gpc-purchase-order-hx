-- Yield notes tied to a lot, not a product (0018)
-- =================================================
-- Notes now tie to a specific lot_code (the default/primary case — a
-- traceability-relevant observation about that exact harvest lot) or are
-- left general (lot_code NULL — not specific to any one lot). Replaces the
-- earlier yield_product_id association, which no note had used yet.
--
-- lot_code is free TEXT, matching yield_entries.lot_code — not a FK (lot
-- codes aren't a normalized entity, same reasoning as yield_entries itself).
--
-- Table DDL is also in backend/app/admin_schema.py (runs on API boot).
--
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0018_yield_notes_lot_code.sql

BEGIN;

ALTER TABLE yield_notes DROP COLUMN IF EXISTS yield_product_id;
ALTER TABLE yield_notes ADD COLUMN IF NOT EXISTS lot_code TEXT;
CREATE INDEX IF NOT EXISTS idx_yield_notes_lot_code ON yield_notes (lot_code, note_date);

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   ALTER TABLE yield_notes DROP COLUMN IF EXISTS lot_code;
--   ALTER TABLE yield_notes ADD COLUMN yield_product_id INTEGER REFERENCES yield_products(id) ON DELETE SET NULL;
