-- Restrict sign-up to allowed email domains + explicit exceptions (0011)
-- =====================================================================
-- A Supabase "before user created" auth hook. It runs BEFORE auth.users gets a
-- row, so an outsider who completes Google OAuth is bounced at the source (the
-- backend allow-list in app/auth.py is the second layer — belt and braces).
--
-- Keep this list in sync with the API's ALLOWED_EMAIL_DOMAINS / ALLOWED_EMAILS.
--
-- ⚠️  Creating the function is not enough — enable it in the Supabase dashboard:
--     Authentication → Hooks → "Before user created" → Postgres →
--     select public.restrict_signup_domain
--     (or set [auth.hook.before_user_created] in supabase/config.toml for local).

create or replace function public.restrict_signup_domain(event jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_email    text := lower(coalesce(event -> 'user' ->> 'email', ''));
  v_domain   text := split_part(v_email, '@', 2);
  ok_domains text[] := array['garfieldproduce.com', 'adelantecenter.org'];
  ok_emails  text[] := array['jcaternolo@gmail.com'];
begin
  if v_email = '' then
    return jsonb_build_object('error', jsonb_build_object(
      'http_code', 400, 'message', 'An email is required.'));
  end if;

  -- already granted a role? always allow (covers off-domain teammates added
  -- via Settings → Team).
  if exists (select 1 from public.app_users au where lower(au.email) = v_email) then
    return '{}'::jsonb;
  end if;

  if v_domain = any (ok_domains) or v_email = any (ok_emails) then
    return '{}'::jsonb;
  end if;

  return jsonb_build_object('error', jsonb_build_object(
    'http_code', 403,
    'message', 'This email domain is not authorized for the Garfield Produce dashboard.'));
end;
$$;

-- the auth hook runs as supabase_auth_admin
grant execute on function public.restrict_signup_domain(jsonb) to supabase_auth_admin;
revoke execute on function public.restrict_signup_domain(jsonb) from authenticated, anon, public;
grant usage on schema public to supabase_auth_admin;
grant select on table public.app_users to supabase_auth_admin;
