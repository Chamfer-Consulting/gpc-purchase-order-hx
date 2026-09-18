import { useMemo, useState } from "react";
import { Button, Modal, Select, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { IconChevronDown, IconSearch, IconX } from "@tabler/icons-react";
import { useTouchUi } from "@/hooks/useTouchUi";

export interface GridPickerOption {
  value: string;
  label: string;
}

/** A Select alternative for touch: the closed field looks and sizes like
 *  any other input (so it costs no extra room in the form — the no-scroll
 *  kiosk shell has to fit everything above the fold), but tapping it opens
 *  a full-screen grid of large buttons instead of a small dropdown list.
 *  Picking one is a single tap on a target several times the size of a
 *  normal Select option row. A search box up top keeps a long roster
 *  (many products, many employees) just as fast to narrow down.
 *
 *  On a mouse/keyboard desktop (`useTouchUi` false) this renders as a plain
 *  compact searchable `Select` instead — the full-screen tap grid has no
 *  benefit there and just looks oversized next to a normal desktop form. */
export function GridPickerField({
  label,
  placeholder,
  description,
  value,
  options,
  onChange,
  disabled,
  required,
  searchPlaceholder = "Search…",
}: {
  label: string;
  placeholder?: string;
  description?: string;
  value: string | null;
  options: GridPickerOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  required?: boolean;
  searchPlaceholder?: string;
}) {
  // useTouchUi() starts `false` on the very first render (matchMedia hasn't
  // resolved yet) and can flip to `true` a moment later on any touch device
  // — so every hook below MUST run unconditionally on every render, same
  // order, regardless of isTouch. An early `return` before a hook call
  // (the previous shape of this component) is a Rules-of-Hooks violation
  // that only ever manifests on a touch device: React sees a different
  // number of hooks between the isTouch=false render and the very next
  // isTouch=true render and hard-crashes — with no error boundary in the
  // app, that blanks the whole page. Desktop never hits this since isTouch
  // starts and stays false there, which is exactly why tsc/build (and every
  // desktop-only manual check) never caught it.
  const isTouch = useTouchUi();
  const [opened, { open, close }] = useDisclosure(false);
  const [search, setSearch] = useState("");
  const fullScreen = useMediaQuery("(max-width: 48em)");
  const selectedLabel = options.find((o) => o.value === value)?.label ?? "";
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
  }, [options, search]);

  if (!isTouch) {
    return (
      <Select
        label={label}
        description={description}
        placeholder={placeholder}
        required={required}
        data={options}
        value={value}
        onChange={(v) => v && onChange(v)}
        disabled={disabled}
        searchable
        size="sm"
      />
    );
  }

  const handleOpen = () => {
    if (disabled) return;
    setSearch("");
    open();
  };

  const pick = (v: string) => {
    onChange(v);
    close();
  };

  return (
    <>
      <TextInput
        label={label}
        description={description}
        placeholder={placeholder}
        required={required}
        value={selectedLabel}
        readOnly
        disabled={disabled}
        onClick={handleOpen}
        rightSection={<IconChevronDown size={16} style={{ opacity: 0.6 }} />}
        size="lg"
        style={{ cursor: disabled ? undefined : "pointer" }}
        styles={{ input: { cursor: disabled ? undefined : "pointer" } }}
      />
      <Modal
        opened={opened}
        onClose={close}
        title={label}
        size="lg"
        fullScreen={fullScreen}
        withCloseButton={false}
      >
        <Stack gap="md">
          {/* A real, labeled button instead of the small X Mantine would
           *  otherwise put in the corner — easier to notice and understand
           *  for anyone unfamiliar with that convention. Placed above the
           *  search box (not below the grid) so it's never scrolled out of
           *  view on a long roster. */}
          <Button variant="light" color="gray" fullWidth leftSection={<IconX size={18} />} onClick={close}>
            Cancel
          </Button>
          <TextInput
            placeholder={searchPlaceholder}
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            leftSection={<IconSearch size={16} />}
            size="lg"
            autoFocus
          />
          {filtered.length === 0 ? (
            <Text c="dimmed" size="sm">
              No matches.
            </Text>
          ) : (
            <SimpleGrid cols={{ base: 2, xs: 3 }} spacing="sm">
              {filtered.map((o) => (
                <Button
                  key={o.value}
                  variant={o.value === value ? "filled" : "light"}
                  color="gpGreen"
                  size="lg"
                  h="auto"
                  py="sm"
                  styles={{ label: { whiteSpace: "normal", textAlign: "center", lineHeight: 1.25 } }}
                  onClick={() => pick(o.value)}
                >
                  {o.label}
                </Button>
              ))}
            </SimpleGrid>
          )}
        </Stack>
      </Modal>
    </>
  );
}
