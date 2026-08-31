-- PO edit/review/reconcile rework — safety foundation (0006)
-- =========================================================
-- 1. purchase_orders.lock_version — optimistic concurrency. Every admin/edit
--    mutation does `... SET ..., lock_version = lock_version + 1 WHERE id = %s
--    AND (lock_version = %s)`; a 0-row result is a stale write -> HTTP 409.
-- 2. app_users — the authorization tier. role viewer < editor < admin. No row
--    for an email means 'editor' (backend default) so existing users keep
--    working; 'admin' must be granted explicitly.
--
-- NOTE: no uniqueness constraint on po_number. The revision model keeps every
-- version of a PO as its own status='active' row; qbo_matcher.get_latest_pos()
-- dedupes by po_number at read time.
--
-- Idempotent (IF NOT EXISTS / guarded). The API self-applies this same DDL on
-- boot (backend/app/admin_schema.py). Apply with `supabase db push` or:
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0006_po_locking_and_roles.sql

BEGIN;

-- 1. Optimistic-concurrency version ----------------------------------------
ALTER TABLE purchase_orders
  ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;

-- 2. Authorization tiers --------------------------------------------------
CREATE TABLE IF NOT EXISTS app_users (
    email      TEXT PRIMARY KEY,
    role       TEXT NOT NULL DEFAULT 'editor'
               CHECK (role IN ('viewer', 'editor', 'admin')),
    note       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed the owner as admin (harmless no-op if already present / different owner).
INSERT INTO app_users (email, role, note)
VALUES ('jcaternolo@gmail.com', 'admin', 'seed: repo owner')
ON CONFLICT (email) DO NOTHING;

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   ALTER TABLE purchase_orders DROP COLUMN IF EXISTS lock_version;
--   DROP TABLE IF EXISTS app_users;
