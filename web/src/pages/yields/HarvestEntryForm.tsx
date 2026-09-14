import { useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Group,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Textarea,
  TextInput,
} from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { useMe } from "@/api/me";
import { useCreateYieldEntry, useYieldEmployees, useYieldProducts, type YieldUnit } from "@/api/yields";
import { SectionCard } from "@/components/SectionCard";
import { businessToday } from "@/lib/datetime";
import { notifySuccess } from "@/lib/notify";
import { errorMessage } from "@/lib/errors";

/** The harvest-logging form: product, weight, tray counts, who/where.
 *  Submitting resets weight/trays/notes but keeps product/unit/worker
 *  selected, since a packing run usually logs several entries in a row for
 *  the same setup. Shared by the field kiosk (HarvestEntryPage) and the
 *  office "Log harvest" page (YieldsLogPage) — same form either way, just a
 *  different chrome around it. */
export function HarvestEntryForm() {
  const { role } = useMe();
  const products = useYieldProducts();
  const employees = useYieldEmployees();
  const create = useCreateYieldEntry();
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

  const productOptions = useMemo(
    () => (products.data ?? []).map((p) => ({ value: String(p.id), label: p.name })),
    [products.data],
  );
  const employeeOptions = useMemo(
    () => (employees.data ?? []).map((e) => e.name),
    [employees.data],
  );

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

      <SectionCard title="Harvest">
        <Stack gap="md">
          <Select
            label="Product"
            placeholder="Choose a crop"
            data={productOptions}
            value={productId}
            onChange={handleProductChange}
            searchable
            size="md"
            disabled={products.isLoading}
            required
          />
          <TextInput
            type="date"
            label="Harvest date"
            description={dateLocked ? "Kiosk entries always log to today" : undefined}
            value={date}
            onChange={(e) => handleDateChange(e.currentTarget.value)}
            size="md"
            disabled={dateLocked}
          />
          <Group grow align="flex-end">
            <NumberInput
              label="Weight"
              value={weight}
              onChange={(v) => setWeight(v === "" ? "" : Number(v))}
              min={0}
              decimalScale={2}
              size="md"
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
              size="md"
            />
          </Group>
          <Group grow>
            <NumberInput
              label="Trays harvested"
              description="Number of trays in bin"
              value={trayCount}
              onChange={(v) => setTrayCount(v === "" ? "" : Number(v))}
              min={0}
              size="md"
            />
            <NumberInput
              label="Trays discarded"
              description="Not harvestable"
              value={discardedTrayCount}
              onChange={(v) => setDiscardedTrayCount(v === "" ? "" : Number(v))}
              min={0}
              size="md"
            />
          </Group>
          <TextInput
            label="Lot code"
            value={lotCode}
            onChange={(e) => handleLotCodeChange(e.currentTarget.value)}
            size="md"
          />
          <Select
            label="Harvested by"
            placeholder="Choose who's harvesting"
            data={employeeOptions}
            value={harvestedBy || null}
            onChange={(v) => setHarvestedBy(v ?? "")}
            searchable
            size="md"
            disabled={employees.isLoading}
            required
          />
          <Textarea
            label="Notes"
            value={notes}
            onChange={(e) => setNotes(e.currentTarget.value)}
            autosize
            minRows={2}
          />

          {create.error && <Alert color="red">{errorMessage(create.error)}</Alert>}

          <Button size="lg" loading={create.isPending} disabled={!canSubmit} onClick={submit}>
            Log harvest
          </Button>
        </Stack>
      </SectionCard>
    </Stack>
  );
}
