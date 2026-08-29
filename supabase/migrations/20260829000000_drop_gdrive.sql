-- Remove the Google Drive integration (po-dashboard-rebuild)
-- =========================================================
-- Original-PO-PDF archival now lives entirely in Supabase: the po_documents
-- table (see 20260828130000_po_documents.sql) holds the captured PDF bytes,
-- optionally offloaded to Supabase Storage. The Drive link columns are no
-- longer written or read by any code path (gdrive_client.py deleted, the
-- "Sync Drive links" button and the Edit-PO "Original PDF (Drive)" link
-- removed).
--
-- Apply with:
--   supabase db push
--   psql "$DATABASE_URL" -f supabase/migrations/20260829000000_drop_gdrive.sql
--
-- Idempotent.

BEGIN;

ALTER TABLE purchase_orders DROP COLUMN IF EXISTS drive_file_id;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS drive_synced_at;

COMMIT;

-- Rollback (columns only — the Drive folder contents are unaffected):
--   ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS drive_file_id TEXT;
--   ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS drive_synced_at TIMESTAMPTZ;
