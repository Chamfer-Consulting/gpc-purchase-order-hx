import { ActionIcon, useComputedColorScheme, useMantineColorScheme } from "@mantine/core";
import { IconMoon, IconSun } from "@tabler/icons-react";

/** Light/dark toggle. Flips between explicit light and dark (never back to auto). */
export function ThemeToggle({ onDark = false }: { onDark?: boolean }) {
  const { setColorScheme } = useMantineColorScheme();
  const computed = useComputedColorScheme("light", { getInitialValueInEffect: true });
  const next = computed === "dark" ? "light" : "dark";

  return (
    <ActionIcon
      variant="subtle"
      color={onDark ? "gray" : undefined}
      size="lg"
      radius="md"
      aria-label={`Switch to ${next} theme`}
      onClick={() => setColorScheme(next)}
      style={onDark ? { color: "var(--gp-nav-fg)" } : undefined}
    >
      {computed === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
    </ActionIcon>
  );
}
