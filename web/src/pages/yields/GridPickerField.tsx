import { useMemo, useState } from "react";
import { Button, Modal, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { IconChevronDown, IconSearch } from "@tabler/icons-react";

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
 *  (many products, many employees) just as fast to narrow down. */
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
  const [opened, { open, close }] = useDisclosure(false);
  const [search, setSearch] = useState("");
  const fullScreen = useMediaQuery("(max-width: 48em)");

  const selectedLabel = options.find((o) => o.value === value)?.label ?? "";
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
  }, [options, search]);

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
      <Modal opened={opened} onClose={close} title={label} size="lg" fullScreen={fullScreen}>
        <Stack gap="md">
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
