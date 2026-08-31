-- 0005_rls_lockdown — lock the public schema to the server-side role
-- ============================================================================
-- This app does ALL database access through the FastAPI backend, which connects
-- as the `postgres` role (BYPASSRLS). The browser only ever talks to Supabase
-- Auth — never to PostgREST (`/rest/v1/`). So the correct posture is:
--
--   * RLS ON for every public table, with NO policies  -> deny-all for `anon`
--     and `authenticated`. The "RLS enabled, no policy" advisor is INFO-level
--     and EXPECTED here — do not add policies to "fix" it.
--   * `anon` / `authenticated` hold no table / sequence privileges either, so a
--     leaked publishable key (it ships in the SPA bundle) or a signed-in user
--     cannot read or write the data via PostgREST even if a table's RLS were
--     ever toggled off.
--   * An `ensure_rls` event trigger auto-enables RLS on any table created later
--     in `public` (so the API's own boot-time DDL, or a future migration that
--     forgets, is still covered).
--
-- Realtime note: with deny-all RLS the `authenticated` role receives no change
-- events, so the review-queue live refresh (useRealtimeInvalidate) is inert. To
-- turn it on later: add `purchase_orders` + `extraction_reviews` to the
-- `supabase_realtime` publication AND add `... FOR SELECT TO authenticated USING
-- (true)` policies on just those two tables.
--
-- Also (dashboard, not SQL): Auth → enable "Prevent use of leaked passwords".
--
-- Requires the migration role (postgres). Idempotent.

BEGIN;

-- 1. Event trigger: enable RLS on every new public table automatically.
CREATE OR REPLACE FUNCTION public.rls_auto_enable()
  RETURNS event_trigger
  LANGUAGE plpgsql
  SECURITY DEFINER
  SET search_path TO 'pg_catalog'
AS $fn$
DECLARE
  cmd record;
BEGIN
  FOR cmd IN
    SELECT * FROM pg_event_trigger_ddl_commands()
    WHERE command_tag IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
      AND object_type IN ('table', 'partitioned table')
  LOOP
    IF cmd.schema_name = 'public' THEN
      BEGIN
        EXECUTE format('ALTER TABLE IF EXISTS %s ENABLE ROW LEVEL SECURITY', cmd.object_identity);
        RAISE LOG 'rls_auto_enable: enabled RLS on %', cmd.object_identity;
      EXCEPTION WHEN OTHERS THEN
        RAISE LOG 'rls_auto_enable: could not enable RLS on %', cmd.object_identity;
      END;
    END IF;
  END LOOP;
END;
$fn$;

REVOKE ALL ON FUNCTION public.rls_auto_enable() FROM PUBLIC, anon, authenticated;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_event_trigger WHERE evtname = 'ensure_rls') THEN
    CREATE EVENT TRIGGER ensure_rls ON ddl_command_end
      EXECUTE FUNCTION public.rls_auto_enable();
  END IF;
END $$;

-- 2. Backfill: RLS on for every table that already exists in public.
DO $$
DECLARE t regclass;
BEGIN
  FOR t IN
    SELECT c.oid::regclass
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r'
  LOOP
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;

-- 3. Strip the default Supabase grants from the browser-facing roles.
REVOKE ALL PRIVILEGES ON ALL TABLES    IN SCHEMA public FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES    FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;

COMMIT;

-- No rollback: re-granting anon/authenticated access to public would re-open
-- PostgREST to the entire dataset.
