import { type ReactNode } from "react";
import { Button, Center, Loader, Paper, Stack, Text } from "@mantine/core";
import { BrandMark } from "@/components/Brand";
import { ApiError } from "@/lib/api";
import { useMe } from "@/api/me";
import { useAuth } from "./AuthProvider";

/** Sits inside RequireAuth: the Supabase session is valid, but the API may still
 *  refuse this email (not on the allow-list). Show a dead-end screen rather than
 *  a broken app of 403s. Any other /api/me failure falls through — pages handle
 *  their own errors. */
export function AccountGate({ children }: { children: ReactNode }) {
  const { signOut } = useAuth();
  const me = useMe();

  const notAllowed = me.error instanceof ApiError && me.error.code === "account_not_allowed";

  if (notAllowed) {
    return (
      <Center h="100vh" bg="var(--gp-page)" p="lg">
        <Stack align="center" gap="lg" w={400} maw="100%">
          <BrandMark size={40} />
          <Paper withBorder shadow="md" radius="md" p="xl" w="100%" bg="var(--gp-surface)">
            <Stack gap="sm">
              <Text fw={600}>Access needed</Text>
              <Text size="sm" c="dimmed">
                {me.email ? <b>{me.email}</b> : "This account"} isn't authorized for the Garfield
                Produce dashboard yet. Ask an admin to add you under Settings → Team.
              </Text>
              <Button variant="default" onClick={() => void signOut()}>
                Sign out
              </Button>
            </Stack>
          </Paper>
        </Stack>
      </Center>
    );
  }

  if (me.isLoading) {
    return (
      <Center h="100vh" bg="var(--gp-page)">
        <Stack align="center" gap="sm">
          <BrandMark size={40} />
          <Loader size="sm" />
        </Stack>
      </Center>
    );
  }

  return <>{children}</>;
}
