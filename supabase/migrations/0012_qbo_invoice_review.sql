-- QBO invoice status columns + a hidden-invoices visibility list
-- =============================================================
-- Lets the Data Quality page surface QuickBooks invoices that were auto-generated
-- from a recurring template but never sent / paid / matched (phantom invoices that
-- inflate revenue), and lets a human exclude one from every analytics page — the
-- invoice analogue of hidden_products (0008) / hidden_customers.
--
-- The four qbo_invoices columns are materialised from raw_json at sync time
-- (shared/qbo_client.py::sync_invoices). This migration also backfills them for
-- the invoices already stored. Idempotent; the API self-applies the DDL on boot
-- (backend/app/admin_schema.py), the pipeline via schema.sql.

BEGIN;

ALTER TABLE qbo_invoices
  ADD COLUMN IF NOT EXISTS email_status TEXT,          -- EmailSent | NeedToSend | NotSet
  ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ,   -- DeliveryInfo.DeliveryTime (emailed)
  ADD COLUMN IF NOT EXISTS balance      NUMERIC,       -- amount still owed
  ADD COLUMN IF NOT EXISTS recur_ref    TEXT;          -- RecurDataRef.value => from a recurring template

UPDATE qbo_invoices SET
  email_status = raw_json->>'EmailStatus',
  delivered_at = NULLIF(raw_json#>>'{DeliveryInfo,DeliveryTime}', '')::timestamptz,
  balance      = NULLIF(raw_json->>'Balance', '')::numeric,
  recur_ref    = raw_json#>>'{RecurDataRef,value}'
WHERE raw_json IS NOT NULL;

CREATE TABLE IF NOT EXISTS hidden_invoices (
    qbo_invoice_id TEXT PRIMARY KEY,
    reason         TEXT,
    hidden_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;

-- Rollback (manual):
--   DROP TABLE IF EXISTS hidden_invoices;
--   ALTER TABLE qbo_invoices
--     DROP COLUMN IF EXISTS email_status, DROP COLUMN IF EXISTS delivered_at,
--     DROP COLUMN IF EXISTS balance,      DROP COLUMN IF EXISTS recur_ref;
