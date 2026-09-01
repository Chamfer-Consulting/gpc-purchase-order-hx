import dayjs from "dayjs";
import { Button } from "@mantine/core";
import { useFilters } from "./useFilters";

/**
 * Quick-select timeline chips, stock-tracker style. Each sets the URL date range
 * (useFilters) to a trailing window ending today; "All" clears it. The chip whose
 * computed range matches the current one is filled.
 */
type PresetId = "1W" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "ALL";

const PRESETS: { id: PresetId; label: string }[] = [
  { id: "1W", label: "1W" },
  { id: "1M", label: "1M" },
  { id: "3M", label: "3M" },
  { id: "6M", label: "6M" },
  { id: "YTD", label: "YTD" },
  { id: "1Y", label: "1Y" },
  { id: "ALL", label: "All" },
];

function rangeFor(id: PresetId): { start: string | null; end: string | null } {
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
