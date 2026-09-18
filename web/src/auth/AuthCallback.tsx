import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { Anchor, Center, Loader, Stack, Text } from "@mantine/core";
import { BrandMark } from "@/components/Brand";
import { pingLoginOnce, useAuth } from "./AuthProvider";

/** Reads an error out of whichever part of the URL Supabase actually put it
 *  in. supabase-js defaults to the implicit flow (no `flowType` is set in
 *  lib/supabase.ts), so a successful session AND an auth error both land in
 *  the `#` fragment, not the query string — an expired/already-used magic
 *  link, a denied Google consent, or a rate limit all redirect here as
 *  `#error=...&error_description=...`. Query-string params are also checked
 *  for forward compatibility if the flow type ever changes to PKCE. */
function getAuthErrorFromUrl(searchParams: URLSearchParams): string | null {
  const fromQuery = searchParams.get("error_description") ?? searchParams.get("error");
  if (fromQuery) return fromQuery;
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  const hashParams = new URLSearchParams(hash);
  const fromHash = hashParams.get("error_description") ?? hashParams.get("error");
  return fromHash ? fromHash.replace(/\+/g, " ") : null;
}

/**
 * Landing route for the Supabase OAuth (Google) / magic-link redirect.
 * supabase-js parses the URL and exchanges it for a session
 * (detectSessionInUrl), which fires onAuthStateChange in AuthProvider. We
 * just wait for that, then go home.
 */
export function AuthCallback() {
  const { session, loading } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [timedOut, setTimedOut] = useState(false);

  const oauthError = getAuthErrorFromUrl(params);

  useEffect(() => {
    if (session) {
      pingLoginOnce(); // safety net if the OAuth exchange didn't emit SIGNED_IN
      navigate("/", { replace: true });
    }
  }, [session, navigate]);

  useEffect(() => {
    const t = setTimeout(() => setTimedOut(true), 8000);
    return () => clearTimeout(t);
  }, []);

  if (session) return <Navigate to="/" replace />;

  return (
    <Center h="100vh" p="md" bg="var(--gp-page)">
      <Stack align="center" gap="sm">
        <BrandMark size={40} />
        {oauthError || (timedOut && !loading) ? (
          <>
            <Text c="red" size="sm" ta="center">
              {oauthError ?? "Sign-in didn't complete."}
            </Text>
            <Anchor component={Link} to="/login">
              Back to sign in
            </Anchor>
          </>
        ) : (
          <>
            <Loader />
            <Text size="sm" c="dimmed">
              Signing you in…
            </Text>
          </>
        )}
      </Stack>
    </Center>
  );
}
