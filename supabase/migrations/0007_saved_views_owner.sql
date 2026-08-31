-- Per-user saved views (0007)
-- ===========================
-- dashboard_saved_views was keyed on `name` alone — views were shared across
-- every user and any editor could clobber or delete anyone's. Add `owner`
-- (the Supabase email) and key on (owner, kind, name). Existing rows migrate to
-- owner = '' (a legacy "shared" bucket that everyone still sees but nobody can
-- overwrite or delete).
--
-- Idempotent; also self-applied on API boot (backend/app/admin_schema.py).
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0007_saved_views_owner.sql

BEGIN;

CREATE TABLE IF NOT EXISTS dashboard_saved_views (
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    config     JSONB NOT NULL,
    owner      TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE dashboard_saved_views ADD COLUMN IF NOT EXISTS owner TEXT NOT NULL DEFAULT '';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'dashboard_saved_views_pkey') THEN
        ALTER TABLE dashboard_saved_views DROP CONSTRAINT dashboard_saved_views_pkey;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_saved_views_owner_kind_name') THEN
        ALTER TABLE dashboard_saved_views
            ADD CONSTRAINT uq_saved_views_owner_kind_name UNIQUE (owner, kind, name);
    END IF;
END $$;

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   ALTER TABLE dashboard_saved_views DROP CONSTRAINT IF EXISTS uq_saved_views_owner_kind_name;
--   ALTER TABLE dashboard_saved_views DROP COLUMN IF EXISTS owner;
--   -- (re-adding the name PK requires the table to have no duplicate names)
