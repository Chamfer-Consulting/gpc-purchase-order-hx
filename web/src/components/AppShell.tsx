import { type ReactNode } from "react";
import { NavLink as RouterNavLink, useLocation } from "react-router-dom";
import { AppShell as MantineAppShell, Burger, Group, NavLink, Text } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useAuth } from "@/auth/AuthProvider";

const NAV: { label: string; to: string }[] = [
  { label: "Overview", to: "/" },
  { label: "Customer 360", to: "/customers" },
  { label: "Products & Sizes", to: "/products" },
  { label: "Explore", to: "/explore" },
  { label: "Order Lifecycle", to: "/lifecycle" },
  { label: "Data Quality", to: "/data-quality" },
  { label: "Match & Reconcile", to: "/match" },
  { label: "Extraction Review", to: "/review" },
  { label: "Settings", to: "/settings" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const [opened, { toggle }] = useDisclosure();
  const { session, signOut } = useAuth();
  const loc = useLocation();

  return (
    <MantineAppShell
      header={{ height: 52 }}
      navbar={{ width: 220, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <MantineAppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Text fw={600}>PO Dashboard</Text>
          </Group>
          <Group gap="xs">
            <Text size="xs" c="dimmed">
              {session?.user.email}
            </Text>
            <Text
              size="xs"
              c="blue"
              style={{ cursor: "pointer" }}
              onClick={() => void signOut()}
            >
              Sign out
            </Text>
          </Group>
        </Group>
      </MantineAppShell.Header>

      <MantineAppShell.Navbar p="xs">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            component={RouterNavLink}
            to={n.to}
            label={n.label}
            active={loc.pathname === n.to}
          />
        ))}
      </MantineAppShell.Navbar>

      <MantineAppShell.Main>{children}</MantineAppShell.Main>
    </MantineAppShell>
  );
}
