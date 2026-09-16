-- New 'external_viewer' role: page-scoped read access for outside parties (0020)
-- ===========================================================================
-- A new role, rank 0 (same floor as 'field') -- never the implicit default,
-- only ever an explicit grant. Unlike every other role, its access isn't a
-- single rank on the field < viewer < editor < admin ladder: an admin grants
-- it individual nav pages one at a time (Settings -> Team), e.g. one outside
-- party might see Overview + Customers while another sees only Pricing.
--
-- app_users.external_pages stores that per-account grant list directly (an
-- array of nav page keys, e.g. '/customers', matching web/src/nav.tsx's `to`
-- paths) -- no separate join table, since it's a small, bounded, per-user
-- list that's naturally 1:1 with the account row. Empty/unused for every
-- other role.
--
-- Table DDL is also in backend/app/admin_schema.py (runs on API boot).
--
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0020_external_viewer_role.sql

BEGIN;

ALTER TABLE app_users ADD COLUMN IF NOT EXISTS external_pages TEXT[] NOT NULL DEFAULT '{}';

ALTER TABLE app_users DROP CONSTRAINT IF EXISTS app_users_role_check;
ALTER TABLE app_users ADD CONSTRAINT app_users_role_check
    CHECK (role IN ('field', 'viewer', 'editor', 'admin', 'external_viewer'));

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   ALTER TABLE app_users DROP CONSTRAINT IF EXISTS app_users_role_check;
--   ALTER TABLE app_users ADD CONSTRAINT app_users_role_check
--       CHECK (role IN ('field', 'viewer', 'editor', 'admin'));
--   ALTER TABLE app_users DROP COLUMN IF EXISTS external_pages;
