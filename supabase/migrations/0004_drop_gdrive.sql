-- Remove the Google Drive integration (po-dashboard-rebuild)
-- =========================================================
-- Original-PO-PDF archival now lives entirely in Supabase: the po_documents
-- table (0003) holds the captured PDF bytes, optionally offloaded to Supabase
-- Storage. The Drive link columns are no longer written or read by any code path
-- (gdrive_client.py deleted, the "Sync Drive links" button and the Edit-PO
-- "Original PDF (Drive)" link removed).
--
-- Apply with:
--   supabase db push
--   psql "$SUPABASE_SESSION_URL" -f supabase/migrations/0004_drop_gdrive.sql
--
-- Idempotent. A no-op on a DB built from 0001_init (never had the columns); the
-- real delta a restored pre-cutover Neon dump needs.

BEGIN;

ALTER TABLE purchase_orders DROP COLUMN IF EXISTS drive_file_id;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS drive_synced_at;

COMMIT;

-- Rollback (columns only — the Drive folder contents are unaffected):
--   ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS drive_file_id TEXT;
--   ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS drive_synced_at TIMESTAMPTZ;
