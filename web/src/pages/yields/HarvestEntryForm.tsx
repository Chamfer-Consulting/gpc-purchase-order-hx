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
import { useCreateYieldEntry, useYieldEmployees, useYieldProducts, type YieldUnit } from "@/api/yields";
import { SectionCard } from "@/components/SectionCard";
import { notifySuccess } from "@/lib/notify";
import { errorMessage } from "@/lib/errors";

function today(): string {
  // The tablet/office sits at the business — its local calendar day is the business day.
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The harvest-logging form: product, weight, tray counts, who/where.
 *  Submitting resets weight/trays/notes but keeps product/unit/worker
 *  selected, since a packing run usually logs several entries in a row for
 *  the same setup. Shared by the field kiosk (HarvestEntryPage) and the
 *  office "Log harvest" page (YieldsLogPage) — same form either way, just a
 *  different chrome around it. */
export function HarvestEntryForm() {
  const products = useYieldProducts();
  const employees = useYieldEmployees();
  const create = useCreateYieldEntry();

  const [productId, setProductId] = useState<string | null>(null);
  const [date, setDate] = useState(today());
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

  // Auto-fill the lot code with the selected product's prefix, but only while
  // the field still holds whatever we last auto-filled — once the employee
  // types something of their own, switching products stops overwriting it.
  const lastAutoPrefixRef = useRef("");
  const handleProductChange = (id: string | null) => {
    setProductId(id);
    const prefix = (products.data ?? []).find((p) => String(p.id) === id)?.lot_code_prefix ?? "";
    setLotCode((current) => (current === lastAutoPrefixRef.current ? prefix : current));
    lastAutoPrefixRef.current = prefix;
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
            value={date}
            onChange={(e) => setDate(e.currentTarget.value)}
            size="md"
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
            onChange={(e) => setLotCode(e.currentTarget.value)}
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
