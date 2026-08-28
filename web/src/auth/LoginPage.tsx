import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Button, Card, Center, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { supabase } from "@/lib/supabase";
import { useAuth } from "./AuthProvider";

export function LoginPage() {
  const { session } = useAuth();
  const loc = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  return (
    <Center h="100vh" p="md">
      <Card withBorder shadow="sm" radius="md" w={360} p="xl">
        <Stack>
          <Title order={3}>PO Dashboard</Title>
          <Text size="sm" c="dimmed">
            Sign in with your team account.
          </Text>
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
      </Card>
    </Center>
  );
}
