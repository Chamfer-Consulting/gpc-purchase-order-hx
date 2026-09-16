import { useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Group,
  NumberInput,
  SegmentedControl,
  Stack,
  Textarea,
  TextInput,
} from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { useMe } from "@/api/me";
import {
  HISTORICAL_HARVESTER_NAME,
  useCreateYieldEntry,
  useYieldEmployees,
  useYieldEntries,
  useYieldProducts,
  type YieldUnit,
} from "@/api/yields";
import { SectionCard } from "@/components/SectionCard";
import { businessToday } from "@/lib/datetime";
import { notifySuccess } from "@/lib/notify";
import { errorMessage } from "@/lib/errors";
import { useTouchUi } from "@/hooks/useTouchUi";
import { GridPickerField, type GridPickerOption } from "./GridPickerField";

/** Moves the option matching `value` (if any, and if not already first) to
 *  the front of the list — used to bubble "whatever was used last" to the
 *  top of a GridPickerField's grid without disturbing the rest of the
 *  order. */
function moveToFront(options: GridPickerOption[], value: string | undefined): GridPickerOption[] {
  if (!value) return options;
  const idx = options.findIndex((o) => o.value === value);
  if (idx <= 0) return options;
  const reordered = [...options];
  const [match] = reordered.splice(idx, 1);
  reordered.unshift(match);
  return reordered;
}

/** The harvest-logging form: product, weight, tray counts, who/where.
 *  Submitting resets weight/trays/notes but keeps product/unit/worker
 *  selected, since a packing run usually logs several entries in a row for
 *  the same setup. Shared by the field kiosk (HarvestEntryPage) and the
 *  office "Log harvest" page (YieldsLogPage) — same form either way, just a
 *  different chrome around it. */
export function HarvestEntryForm() {
  const { role } = useMe();
  // Large touch-sized fields make sense on the kiosk/tablet/phone this form
  // was built for, but are oversized on a mouse/keyboard desktop (the office
  // "Log harvest" page renders this exact same form) — scale down there.
  const isTouch = useTouchUi();
  const fieldSize = isTouch ? "lg" : "sm";
  const submitSize = isTouch ? "xl" : "sm";
  const stackGap = isTouch ? "xl" : "md";
  const products = useYieldProducts();
  const employees = useYieldEmployees();
  const create = useCreateYieldEntry();
  // The single most recent entry (any product, any device) — whoever/
  // whatever it was is most likely still what's being packed at the kiosk,
  // so both the Product and Harvested-by pickers bubble it to the top of
  // their grid instead of leaving them alphabetical. Same "reorder, never
  // auto-select" rule for both: a wrong silent default for either field
  // (crop or harvester) is a real traceability risk, not just a cosmetic
  // one.
  const lastEntry = useYieldEntries({ include_voided: false, limit: 1 });
  const lastHarvestedBy = lastEntry.data?.[0]?.harvested_by;
  const lastProductId = lastEntry.data?.[0]?.yield_product_id;
  // A 'field' (kiosk) account can only edit/void its own *same-day* entries
  // (backend: _assert_can_touch) — so letting them freely change the date on
  // create risks a mis-tap silently logging to yesterday, invisible in "My
  // recent entries" and then unfixable from the kiosk (the same-day check
  // would reject the correction too). Lock the field to today for that role;
  // the office "Log harvest" page (editor/admin) still needs to backfill.
  const dateLocked = role === "field";

  const [productId, setProductId] = useState<string | null>(null);
  const [date, setDate] = useState(businessToday());
  const [weight, setWeight] = useState<number | "">("");
  const [unit, setUnit] = useState<YieldUnit>("oz");
  const [trayCount, setTrayCount] = useState<number | "">(0);
  const [discardedTrayCount, setDiscardedTrayCount] = useState<number | "">(0);
  const [lotCode, setLotCode] = useState("");
  const [harvestedBy, setHarvestedBy] = useState("");
  const [notes, setNotes] = useState("");
  const [justLogged, setJustLogged] = useState(false);
  // Product/unit/worker persist across submits for a packing run's several
  // entries in a row (see the file doc comment) — jump focus straight back
  // to Weight after each one so that rhythm doesn't need a tap in between.
  const weightInputRef = useRef<HTMLInputElement>(null);

  const productOptions = useMemo(() => {
    const base = (products.data ?? []).map((p) => ({ value: String(p.id), label: p.name }));
    return moveToFront(base, lastProductId != null ? String(lastProductId) : undefined);
  }, [products.data, lastProductId]);
  // "Historical Data" is a real roster entry (CSV import's default
  // attribution for backfilled rows with no known harvester) but never a
  // real person — nobody logging today's harvest should ever pick it.
  const employeeOptions = useMemo(() => {
    const base = (employees.data ?? [])
      .filter((e) => e.name !== HISTORICAL_HARVESTER_NAME)
      .map((e) => ({ value: e.name, label: e.name }));
    return moveToFront(base, lastHarvestedBy);
  }, [employees.data, lastHarvestedBy]);

  // Auto-fill the lot code as the selected product's prefix + the harvest
  // date's MMDD (e.g. "TK0911"), but only until the employee types something
  // of their own into the field — an explicit "has this been hand-edited"
  // flag, not a value comparison, so a manual edit that happens to coincide
  // with a later auto-computed value can't make auto-fill silently resume
  // and clobber it.
  const lotEditedRef = useRef(false);
  const autoLot = (id: string | null, harvestDate: string) => {
    const prefix = (products.data ?? []).find((p) => String(p.id) === id)?.lot_code_prefix ?? "";
    if (!prefix || harvestDate.length < 10) return prefix;
    return prefix + harvestDate.slice(5, 7) + harvestDate.slice(8, 10);
  };
  const applyAutoLot = (next: string) => {
    if (!lotEditedRef.current) setLotCode(next);
  };
  const handleLotCodeChange = (value: string) => {
    lotEditedRef.current = true;
    setLotCode(value);
  };
  const handleProductChange = (id: string | null) => {
    setProductId(id);
    // A hand-edit only ever made sense in the context of the *previous*
    // product's prefix — switching crops always gets a fresh auto-fill for
    // the new one, rather than silently carrying over a stale, wrong-prefix
    // lot code the employee never actually typed for this product.
    lotEditedRef.current = false;
    setLotCode(autoLot(id, date));
  };
  const handleDateChange = (value: string) => {
    setDate(value);
    applyAutoLot(autoLot(productId, value));
  };

  const canSubmit = productId != null && weight !== "" && Number(weight) > 0 && harvestedBy.trim() !== "";

  const submit = () => {
    if (!canSubmit || productId == null) return;
    create.mutate(
      {
        yield_product_id: Number(productId),
        harvest_date: date,
        weight: Number(weight),
        unit,
        tray_count: Number(trayCount) || 0,
        discarded_tray_count: Number(discardedTrayCount) || 0,
        lot_code: lotCode.trim() || null,
        harvested_by: harvestedBy.trim(),
        notes: notes.trim() || null,
      },
      {
        onSuccess: () => {
          notifySuccess("Harvest logged.");
          setWeight("");
          setTrayCount(0);
          setDiscardedTrayCount(0);
          setNotes("");
          setJustLogged(true);
          weightInputRef.current?.focus();
          setTimeout(() => setJustLogged(false), 2500);
        },
      },
    );
  };

  return (
    <Stack gap="lg">
      {justLogged && (
        <Alert color="gpGreen" icon={<IconCheck size={18} />} variant="light">
          Logged — ready for the next entry.
        </Alert>
      )}

      {products.data && products.data.length === 0 && (
        <Alert color="gray" variant="light">
          No harvest products set up yet — add one under Product Yields → Products.
        </Alert>
      )}

      {employees.data && employees.data.length === 0 && (
        <Alert color="gray" variant="light">
          No employees set up yet — add one under Product Yields → Products → Harvest team.
        </Alert>
      )}

      <SectionCard>
        <Stack gap={stackGap}>
          <GridPickerField
            label="Product"
            placeholder="Choose a crop"
            searchPlaceholder="Search products…"
            options={productOptions}
            value={productId}
            onChange={handleProductChange}
            disabled={products.isLoading}
            required
          />
          <TextInput
            type="date"
            label="Harvest date"
            description={dateLocked ? "Kiosk entries always log to today" : undefined}
            value={date}
            onChange={(e) => handleDateChange(e.currentTarget.value)}
            size={fieldSize}
            disabled={dateLocked}
          />
          <Group grow align="flex-end" gap="md">
            <NumberInput
              ref={weightInputRef}
              label="Weight"
              value={weight}
              onChange={(v) => setWeight(v === "" ? "" : Number(v))}
              min={0}
              decimalScale={2}
              inputMode="decimal"
              size={fieldSize}
              required
            />
            <SegmentedControl
              value={unit}
              onChange={(v) => setUnit(v as YieldUnit)}
              data={[
                { value: "oz", label: "oz" },
                { value: "lb", label: "lb" },
                { value: "g", label: "g" },
              ]}
              size={fieldSize}
            />
          </Group>
          <Group grow gap="md">
            <NumberInput
              label="Trays harvested"
              description="Number of trays in bin"
              value={trayCount}
              onChange={(v) => setTrayCount(v === "" ? "" : Number(v))}
              min={0}
              inputMode="numeric"
              size={fieldSize}
            />
            <NumberInput
              label="Trays discarded"
              description="Not harvestable"
              value={discardedTrayCount}
              onChange={(v) => setDiscardedTrayCount(v === "" ? "" : Number(v))}
              min={0}
              inputMode="numeric"
              size={fieldSize}
            />
          </Group>
          <TextInput
            label="Lot code"
            value={lotCode}
            onChange={(e) => handleLotCodeChange(e.currentTarget.value)}
            size={fieldSize}
          />
          <GridPickerField
            label="Harvested by"
            placeholder="Choose who's harvesting"
            searchPlaceholder="Search team…"
            options={employeeOptions}
            value={harvestedBy || null}
            onChange={setHarvestedBy}
            disabled={employees.isLoading}
            required
          />
          <Textarea
            label="Notes"
            value={notes}
            onChange={(e) => setNotes(e.currentTarget.value)}
            autosize
            minRows={2}
            size={fieldSize}
          />

          {create.error && <Alert color="red">{errorMessage(create.error)}</Alert>}

          <Button size={submitSize} loading={create.isPending} disabled={!canSubmit} onClick={submit}>
            Log harvest
          </Button>
        </Stack>
      </SectionCard>
    </Stack>
  );
}
