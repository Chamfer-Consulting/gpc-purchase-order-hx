-- Case-insensitive uniqueness for product names + lot code prefixes (0019)
-- ===========================================================================
-- yield_products.name already had a case-SENSITIVE UNIQUE constraint (0014)
-- — "Kale" and "kale" could coexist as two separate, confusingly-duplicate
-- products. lot_code_prefix (0017) had no uniqueness check at all — two
-- different products could share a prefix, so their auto-generated lot
-- codes (prefix + date) would be genuinely indistinguishable from each
-- other on any given day, defeating the entire point of a traceability
-- code. Both are now enforced case-insensitively via functional unique
-- indexes. lot_code_prefix stays unconstrained when NULL — Postgres never
-- treats two NULLs as equal, so any number of products with no prefix set
-- still coexist fine, same as before.
--
-- Verified against the live data before writing this migration: no
-- existing case-insensitive name duplicates, no existing lot_code_prefix
-- duplicates.
--
-- Table DDL is also in backend/app/admin_schema.py (runs on API boot).
--
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0019_yield_product_unique_ci.sql

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS idx_yield_products_name_lower ON yield_products (lower(name));
CREATE UNIQUE INDEX IF NOT EXISTS idx_yield_products_lot_prefix_lower ON yield_products (lower(lot_code_prefix));

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   DROP INDEX IF EXISTS idx_yield_products_name_lower;
--   DROP INDEX IF EXISTS idx_yield_products_lot_prefix_lower;
