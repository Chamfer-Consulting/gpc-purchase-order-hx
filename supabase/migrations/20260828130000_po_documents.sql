-- Captured source PDFs for purchase orders (po-dashboard-rebuild)
-- ==============================================================
-- The emailed PO PDF (pulled from Gmail) and the rendered invoice PDF (pulled
-- from QuickBooks' Print/Download endpoint), stored against the PO.
--
-- Apply with:
--   supabase db push
--   psql "$DATABASE_URL" -f supabase/migrations/20260828130000_po_documents.sql
--
-- Idempotent. The API also self-applies this on boot (backend/app/admin_schema.py).

BEGIN;

CREATE TABLE IF NOT EXISTS po_documents (
    id           BIGSERIAL PRIMARY KEY,
    po_id        INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    invoice_id   INTEGER REFERENCES qbo_invoices(id) ON DELETE SET NULL,  -- kind = 'invoice_pdf'
    kind         TEXT NOT NULL,          -- po_pdf | invoice_pdf | email_pdf | other
    source       TEXT NOT NULL,          -- gmail | qbo | upload
    filename     TEXT NOT NULL,
    mime_type    TEXT NOT NULL DEFAULT 'application/pdf',
    byte_size    INTEGER NOT NULL,
    content_hash TEXT NOT NULL,          -- sha256 hex
    content      BYTEA,                  -- inline bytes; NULL once offloaded to storage_path
    storage_path TEXT,                   -- reserved for a later Supabase Storage move
    captured_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    captured_by  TEXT,
    UNIQUE (po_id, kind, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_po_documents_po_id ON po_documents (po_id);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'po_documents_kind_chk') THEN
    ALTER TABLE po_documents ADD CONSTRAINT po_documents_kind_chk
      CHECK (kind IN ('po_pdf','invoice_pdf','email_pdf','other'));
  END IF;
END $$;

COMMIT;

-- Rollback:  DROP TABLE IF EXISTS po_documents;
