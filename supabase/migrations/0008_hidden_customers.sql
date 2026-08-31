-- Customer visibility (0008)
-- ==========================
-- Mirror of hidden_products: a customer_name on this list is excluded from every
-- analytics page (services/context.py), the same way a hidden product is. Keyed
-- on the invoice customer_name (qbo_invoices.customer_name) — the value the
-- analytics context groups by.
--
-- Idempotent; also self-applied on API boot (backend/app/admin_schema.py).
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0008_hidden_customers.sql

BEGIN;

CREATE TABLE IF NOT EXISTS hidden_customers (
    customer_name TEXT PRIMARY KEY,
    hidden_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   DROP TABLE IF EXISTS hidden_customers;
