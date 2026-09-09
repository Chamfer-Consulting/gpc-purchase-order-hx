-- Customer aliasing (0013)
-- ========================
-- One canonical company name per customer, regardless of which buyer / spelling
-- a PO or invoice carried. The emailer of a PO ("Sean McLaughlin", "David
-- Jedlecki") is a buyer at the company, not the customer — canonical_name is
-- always the company (the QBO customer the invoice bills to).
--
-- `source`: 'auto' = seeded from confirmed po_invoice_links; 'manual' = a human
-- set it in Settings -> Customers. The seed below is idempotent (ON CONFLICT DO
-- NOTHING) so re-running never clobbers a manual mapping.
--
-- Table DDL is also in backend/app/admin_schema.py (runs on API boot). The seed
-- is here only — run once:
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0013_customer_aliases.sql
--
-- RLS is auto-enabled by the 0005 event trigger (deny-all, backend-only).

BEGIN;

CREATE TABLE IF NOT EXISTS customer_aliases (
    alias_name     TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    source         TEXT NOT NULL DEFAULT 'auto' CHECK (source IN ('auto', 'manual')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_customer_aliases_canonical ON customer_aliases (canonical_name);

-- Seed 1: every PO-side spelling that links (confirmed) to a QBO invoice ->
-- that invoice's QBO customer_name. When one PO spelling links to invoices from
-- more than one QBO customer (a wrong confirmed link somewhere), take the most
-- common target.
INSERT INTO customer_aliases (alias_name, canonical_name, source)
SELECT alias_name, canonical_name, 'auto'
FROM (
    SELECT po.customer_name AS alias_name,
           inv.customer_name AS canonical_name,
           row_number() OVER (
               PARTITION BY po.customer_name
               ORDER BY count(*) DESC, inv.customer_name
           ) AS rn
    FROM po_invoice_links l
    JOIN purchase_orders po ON po.id = l.po_id
    JOIN qbo_invoices inv ON inv.id = l.invoice_id
    WHERE l.confirmed = TRUE
      AND btrim(coalesce(po.customer_name, '')) <> ''
      AND btrim(coalesce(inv.customer_name, '')) <> ''
    GROUP BY po.customer_name, inv.customer_name
) ranked
WHERE rn = 1
ON CONFLICT (alias_name) DO NOTHING;

-- Seed 2: every QBO customer name maps to itself, so the resolver is a single
-- lookup (no "is this already canonical?" branch).
INSERT INTO customer_aliases (alias_name, canonical_name, source)
SELECT DISTINCT customer_name, customer_name, 'auto'
FROM qbo_invoices
WHERE btrim(coalesce(customer_name, '')) <> ''
ON CONFLICT (alias_name) DO NOTHING;

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   DROP TABLE IF EXISTS customer_aliases;
