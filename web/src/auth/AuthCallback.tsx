import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { Anchor, Center, Loader, Stack, Text } from "@mantine/core";
import { BrandMark } from "@/components/Brand";
import { pingLoginOnce, useAuth } from "./AuthProvider";

/**
 * Landing route for the Supabase OAuth (Google) redirect. supabase-js parses the
 * `?code=` in the URL and exchanges it for a session (detectSessionInUrl), which
 * fires onAuthStateChange in AuthProvider. We just wait for that, then go home.
 */
export function AuthCallback() {
  const { session, loading } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [timedOut, setTimedOut] = useState(false);

  const oauthError = params.get("error_description") ?? params.get("error");

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
