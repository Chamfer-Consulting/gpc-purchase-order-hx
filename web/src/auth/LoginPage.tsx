import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import {
  Box,
  Button,
  Divider,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { Brand } from "@/components/Brand";
import { supabase } from "@/lib/supabase";
import { useAuth } from "./AuthProvider";

function GoogleG() {
  return (
    <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z" />
      <path fill="#FBBC05" d="M3.97 10.72A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.18.29-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.82.96 4.05l3.01-2.33Z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59C13.46.9 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z" />
    </svg>
  );
}

export function LoginPage() {
  const { session } = useAuth();
  const loc = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [googleBusy, setGoogleBusy] = useState(false);

  if (session) {
    const to = (loc.state as { from?: string })?.from ?? "/";
    return <Navigate to={to} replace />;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) setErr(error.message);
  }

  async function google() {
    setGoogleBusy(true);
    setErr(null);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
    // On success the browser redirects to Google and never returns here.
    if (error) {
      setErr(error.message);
      setGoogleBusy(false);
    }
  }

  return (
    <Box
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1.5rem",
        background:
          "radial-gradient(1100px 520px at 50% -10%, color-mix(in srgb, var(--gp-canopy) 22%, var(--gp-page)), var(--gp-page))",
      }}
    >
      <Stack align="center" gap="lg" w={380} maw="100%">
        <Stack align="center" gap={6}>
          <Brand size={40} />
          <Text size="sm" c="dimmed" ta="center">
            Purchase-order intelligence for the microgreen operation.
          </Text>
        </Stack>

        <Paper withBorder shadow="md" radius="md" p="xl" w="100%" bg="var(--gp-surface)">
          <Stack>
            <Text fw={600}>Sign in</Text>

            <Button
              variant="default"
              fullWidth
              leftSection={<GoogleG />}
              onClick={google}
              loading={googleBusy}
            >
              Continue with Google
            </Button>

            <Divider label="or" labelPosition="center" />

            <form onSubmit={submit}>
              <Stack>
                <TextInput
                  label="Email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.currentTarget.value)}
                  required
                />
                <PasswordInput
                  label="Password"
                  value={password}
                  onChange={(e) => setPassword(e.currentTarget.value)}
                  required
                />
                {err && (
                  <Text c="red" size="sm">
                    {err}
                  </Text>
                )}
                <Button type="submit" loading={busy} fullWidth>
                  Sign in
                </Button>
              </Stack>
            </form>
          </Stack>
        </Paper>

        <Text size="xs" c="dimmed">
          Garfield Produce Co. · team access only
        </Text>
      </Stack>
    </Box>
  );
}
