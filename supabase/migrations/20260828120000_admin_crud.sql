-- Admin CRUD for purchase orders (po-dashboard-rebuild)
-- =====================================================
-- Lifecycle status + soft delete, per-line void, and an append-only audit log.
--
-- Apply with either:
--   supabase db push                         (from the repo root, links to your project)
--   psql "$DATABASE_URL" -f supabase/migrations/20260828120000_admin_crud.sql
--
-- Every statement is idempotent (IF NOT EXISTS / guarded), so re-running is safe.
-- The API also self-applies this exact DDL on boot (backend/app/admin_schema.py),
-- so a deploy that precedes this migration still works; running the migration
-- makes the change explicit and permanent.

BEGIN;

-- 1. Purchase-order lifecycle -------------------------------------------------
-- status: active | draft | cancelled | withdrawn | voided | deleted
--   * only 'active' rows appear in reports / analytics / the review queue
--   * any non-'active' row (and any admin-touched row) is skipped by the
--     extraction pipeline: sync_dashboard.py's upsert guard is
--     WHERE edited = FALSE AND COALESCE(status,'active') = 'active'
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS status        TEXT NOT NULL DEFAULT 'active';
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS status_reason TEXT;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS status_at     TIMESTAMPTZ;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS deleted_at    TIMESTAMPTZ;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS edited_by     TEXT;

CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders (status);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'purchase_orders_status_chk'
  ) THEN
    ALTER TABLE purchase_orders
      ADD CONSTRAINT purchase_orders_status_chk
      CHECK (status IN ('active','draft','cancelled','withdrawn','voided','deleted'));
  END IF;
END $$;

-- 2. Per-line void ----------------------------------------------------------
-- Distinct from is_removed (a revision "ghost" line): voided keeps the line on
-- the order but drops it from totals reconciliation and every report.
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS voided      BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS void_reason TEXT;

-- 3. Audit log ------------------------------------------------------------
-- One row per admin mutation: who (Supabase user email), what action, which
-- entity, and the before/after slice as JSON. Written by
-- backend/app/services/audit.py; viewed per-PO in the Edit PO page.
CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    actor      TEXT,
    action     TEXT NOT NULL,   -- create | update | status | delete | restore | link | unlink | line_void | customer | revision
    entity     TEXT NOT NULL,   -- purchase_order | line_item | po_invoice_link
    entity_id  TEXT,
    before     JSONB,
    after      JSONB,
    at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log (entity, entity_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_at     ON audit_log (at DESC);

COMMIT;

-- Rollback (manual) --------------------------------------------------------
--   ALTER TABLE purchase_orders DROP CONSTRAINT IF EXISTS purchase_orders_status_chk;
--   ALTER TABLE purchase_orders
--     DROP COLUMN IF EXISTS status, DROP COLUMN IF EXISTS status_reason,
--     DROP COLUMN IF EXISTS status_at, DROP COLUMN IF EXISTS deleted_at,
--     DROP COLUMN IF EXISTS edited_by;
--   ALTER TABLE line_items DROP COLUMN IF EXISTS voided, DROP COLUMN IF EXISTS void_reason;
--   DROP TABLE IF EXISTS audit_log;
