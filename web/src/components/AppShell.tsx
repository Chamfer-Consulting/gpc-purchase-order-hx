import { type ReactNode } from "react";
import { NavLink as RouterNavLink } from "react-router-dom";
import {
  AppShell as MantineAppShell,
  Avatar,
  Badge,
  Box,
  Burger,
  Group,
  Menu,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconChevronDown, IconLogout } from "@tabler/icons-react";
import { useAuth } from "@/auth/AuthProvider";
import { useMe } from "@/api/me";
import { NAV_SECTIONS } from "@/nav";
import { Brand } from "./Brand";
import { ThemeToggle } from "./ThemeToggle";
import styles from "./AppShell.module.css";

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <MantineAppShell.Section grow component="nav" aria-label="Primary">
      {NAV_SECTIONS.map((section) => (
        <Box key={section.label} mb={4}>
          <div className={styles.sectionLabel}>{section.label}</div>
          {section.items.map((item) => {
            const Icon = item.icon;
            return (
              <RouterNavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                onClick={onNavigate}
                className={({ isActive }) =>
                  [styles.link, isActive && styles.linkActive].filter(Boolean).join(" ")
                }
              >
                <Icon size={18} stroke={1.7} className={styles.linkIcon} />
                {item.label}
              </RouterNavLink>
            );
          })}
        </Box>
      ))}
    </MantineAppShell.Section>
  );
}

function UserMenu() {
  const { session, signOut } = useAuth();
  const { role } = useMe();
  const email = session?.user.email ?? "";
  const initial = email.slice(0, 1).toUpperCase() || "?";

  return (
    <Menu position="bottom-end" width={240} withArrow shadow="md">
      <Menu.Target>
        <UnstyledButton
          aria-label="Account menu"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "4px 8px",
            borderRadius: "var(--mantine-radius-md)",
            color: "var(--gp-nav-fg)",
          }}
        >
          <Avatar size={28} radius="xl" color="gpGreen" variant="filled">
            {initial}
          </Avatar>
          <Text size="sm" c="var(--gp-nav-fg)" visibleFrom="sm" maw={180} truncate>
            {email}
          </Text>
          <IconChevronDown size={14} style={{ color: "var(--gp-nav-fg-muted)" }} />
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Signed in as</Menu.Label>
        <Menu.Item style={{ pointerEvents: "none" }}>
          <Group justify="space-between" wrap="nowrap" gap="xs">
            <Text size="sm" truncate>
              {email}
            </Text>
            <Badge size="xs" variant="light" color={role === "admin" ? "gpGold" : role === "editor" ? "gpGreen" : "gray"}>
              {role}
            </Badge>
          </Group>
        </Menu.Item>
        <Menu.Divider />
        <Menu.Item
          color="red"
          leftSection={<IconLogout size={16} />}
          onClick={() => void signOut()}
        >
          Sign out
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [opened, { toggle, close }] = useDisclosure();

  return (
    <MantineAppShell
      header={{ height: 58 }}
      navbar={{ width: 248, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <MantineAppShell.Header className={styles.header} withBorder={false}>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
              color="var(--gp-nav-fg)"
              aria-label="Toggle navigation"
            />
            <Brand size={30} onDark />
          </Group>
          <Group gap={4} wrap="nowrap">
            <ThemeToggle onDark />
            <UserMenu />
          </Group>
        </Group>
      </MantineAppShell.Header>

      <MantineAppShell.Navbar className={styles.navbar} withBorder={false}>
        <NavList onNavigate={close} />
      </MantineAppShell.Navbar>

      <MantineAppShell.Main className={styles.main}>
        <div className={styles.content}>{children}</div>
      </MantineAppShell.Main>
    </MantineAppShell>
  );
}
