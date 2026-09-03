import dayjs from "dayjs";
import { Button } from "@mantine/core";
import { useFilters, type Filters } from "./useFilters";

/**
 * Quick-select timeline windows. Each is a trailing range ending today; "All"
 * clears the date filter. Rendered as a chip group (mobile) and, inside the
 * desktop date pill, as a list — both share the range math here.
 */
export type PresetId = "1W" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "ALL";

export const PRESETS: { id: PresetId; label: string; long: string }[] = [
  { id: "1W", label: "1W", long: "Past week" },
  { id: "1M", label: "1M", long: "Past month" },
  { id: "3M", label: "3M", long: "Past 3 months" },
  { id: "6M", label: "6M", long: "Past 6 months" },
  { id: "YTD", label: "YTD", long: "Year to date" },
  { id: "1Y", label: "1Y", long: "Past year" },
  { id: "ALL", label: "All", long: "Any date" },
];

export function rangeFor(id: PresetId): { start: string | null; end: string | null } {
  const today = dayjs();
  const end = today.format("YYYY-MM-DD");
  switch (id) {
    case "1W":
      return { start: today.subtract(1, "week").format("YYYY-MM-DD"), end };
    case "1M":
      return { start: today.subtract(1, "month").format("YYYY-MM-DD"), end };
    case "3M":
      return { start: today.subtract(3, "month").format("YYYY-MM-DD"), end };
    case "6M":
      return { start: today.subtract(6, "month").format("YYYY-MM-DD"), end };
    case "YTD":
      return { start: today.startOf("year").format("YYYY-MM-DD"), end };
    case "1Y":
      return { start: today.subtract(1, "year").format("YYYY-MM-DD"), end };
    case "ALL":
      return { start: null, end: null };
  }
}

/** Which preset (if any) the current start/end exactly matches. */
export function activePreset(f: Pick<Filters, "start" | "end">): PresetId | null {
  for (const { id } of PRESETS) {
    if (id === "ALL") continue;
    const r = rangeFor(id);
    if (f.start === r.start && f.end === r.end) return id;
  }
  return null;
}

export function RangePresets() {
  const { filters, setFilters } = useFilters();

  return (
    <Button.Group>
      {PRESETS.map(({ id, label }) => {
        const r = rangeFor(id);
        const active = filters.start === r.start && filters.end === r.end;
        return (
          <Button
            key={id}
            size="xs"
            variant={active ? "filled" : "default"}
            onClick={() => setFilters({ start: r.start, end: r.end })}
          >
            {label}
          </Button>
        );
      })}
    </Button.Group>
  );
}
