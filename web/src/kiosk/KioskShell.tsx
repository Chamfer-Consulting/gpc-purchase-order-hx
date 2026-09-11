import { type ReactNode } from "react";
import { NavLink as RouterNavLink } from "react-router-dom";
import { Box, Group, Stack, Text, UnstyledButton } from "@mantine/core";
import { IconClipboardList, IconLogout, IconPlant2 } from "@tabler/icons-react";
import { Brand } from "@/components/Brand";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useAuth } from "@/auth/AuthProvider";

const TABS = [
  { to: "/yields", label: "Log harvest", icon: IconPlant2 },
  { to: "/yields/recent", label: "Recent entries", icon: IconClipboardList },
];

/**
 * The harvest-kiosk shell for the 'field' role — no sidebar, no FilterBar, no
 * analytics chrome. Large touch targets throughout; this runs on a shared
 * tablet, not a desk. See web/src/App.tsx's RoleRouter for how this replaces
 * AppShell entirely for 'field' accounts (a security boundary lives in the
 * backend's router-level role floor, not here — this is UX only).
 */
export function KioskShell({ children }: { children: ReactNode }) {
  const { session, signOut } = useAuth();

  return (
    <Box mih="100vh" bg="var(--gp-page)">
      <Box bg="var(--gp-canopy)" py="sm" px={{ base: "sm", sm: "lg" }}>
        <Group justify="space-between" wrap="nowrap">
          <Brand size={30} onDark markOnly />
          <Group gap="xs" wrap="nowrap">
            <ThemeToggle onDark />
            <UnstyledButton
              onClick={() => void signOut()}
              aria-label="Sign out"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "8px 12px",
                borderRadius: "var(--mantine-radius-md)",
                color: "var(--gp-nav-fg)",
              }}
            >
              <IconLogout size={18} />
              <Text size="sm" visibleFrom="xs">
                Sign out
              </Text>
            </UnstyledButton>
          </Group>
        </Group>
        {session?.user.email && (
          <Text size="xs" mt={2} c="var(--gp-nav-fg-muted)">
            {session.user.email}
          </Text>
        )}
      </Box>

      <Group gap={0} px={{ base: "sm", sm: "lg" }} pt="sm" wrap="nowrap">
        {TABS.map((t) => {
          const Icon = t.icon;
          return (
            <RouterNavLink
              key={t.to}
              to={t.to}
              end
              style={({ isActive }) => ({
                flex: 1,
                textDecoration: "none",
                textAlign: "center",
                padding: "14px 8px",
                fontWeight: 650,
                fontSize: 15,
                color: isActive ? "var(--gp-canopy)" : "var(--gp-ink-muted)",
                borderBottom: `3px solid ${isActive ? "var(--gp-accent)" : "transparent"}`,
              })}
            >
              <Stack gap={2} align="center">
                <Icon size={22} stroke={1.7} />
                {t.label}
              </Stack>
            </RouterNavLink>
          );
        })}
      </Group>

      <Box p={{ base: "sm", sm: "lg" }} maw={720} mx="auto">
        {children}
      </Box>
    </Box>
  );
}
