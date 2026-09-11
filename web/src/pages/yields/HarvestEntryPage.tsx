import { useMemo, useState } from "react";
import {
  Alert,
  Autocomplete,
  Button,
  Group,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { useCreateYieldEntry, useYieldEntries, useYieldProducts, type YieldUnit } from "@/api/yields";
import { SectionCard } from "@/components/SectionCard";
import { notifySuccess } from "@/lib/notify";
import { errorMessage } from "@/lib/errors";

function today(): string {
  // The tablet sits at the business — its local calendar day is the business day.
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  const pad = (v: number) => String(v).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Harvest kiosk home — product, weight, tray counts, who/where. Submitting
 *  resets weight/trays/notes but keeps product/unit/bin/worker selected, since
 *  a packing run usually logs several entries in a row for the same setup. */
export function HarvestEntryPage() {
  const products = useYieldProducts();
  // A rolling 30-day window of recent entries, just to seed the storage-bin /
  // harvested-by autocomplete suggestions — not a full history view.
  const recent = useYieldEntries({ date_from: daysAgo(30) });
  const create = useCreateYieldEntry();

  const [productId, setProductId] = useState<string | null>(null);
  const [date, setDate] = useState(today());
  const [weight, setWeight] = useState<number | "">("");
  const [unit, setUnit] = useState<YieldUnit>("oz");
  const [trayCount, setTrayCount] = useState<number | "">(0);
  const [discardedTrayCount, setDiscardedTrayCount] = useState<number | "">(0);
  const [storageBin, setStorageBin] = useState("");
  const [lotCode, setLotCode] = useState("");
  const [harvestedBy, setHarvestedBy] = useState("");
  const [notes, setNotes] = useState("");
  const [justLogged, setJustLogged] = useState(false);

  const productOptions = useMemo(
    () => (products.data ?? []).map((p) => ({ value: String(p.id), label: p.name })),
    [products.data],
  );
  const binSuggestions = useMemo(
    () =>
      Array.from(
        new Set((recent.data ?? []).map((e) => e.storage_bin).filter((v): v is string => Boolean(v))),
      ).sort(),
    [recent.data],
  );
  const workerSuggestions = useMemo(
    () => Array.from(new Set((recent.data ?? []).map((e) => e.harvested_by).filter(Boolean))).sort(),
    [recent.data],
  );

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
        storage_bin: storageBin.trim() || null,
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
      <div>
        <Text fw={700} fz={22}>
          Log harvest
        </Text>
        <Text size="sm" c="dimmed">
          One entry per packing run. Submitting clears the weight and tray counts so you can log the
          next run fast — product, bin, and worker stay set.
        </Text>
      </div>

      {justLogged && (
        <Alert color="gpGreen" icon={<IconCheck size={18} />} variant="light">
          Logged — ready for the next entry.
        </Alert>
      )}

      {products.data && products.data.length === 0 && (
        <Alert color="gray" variant="light">
          No harvest products set up yet. Ask an admin to add one under Settings.
        </Alert>
      )}

      <SectionCard title="Harvest">
        <Stack gap="md">
          <Select
            label="Product"
            placeholder="Choose a crop"
            data={productOptions}
            value={productId}
            onChange={setProductId}
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
              label="Trays packed"
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
          <Autocomplete
            label="Storage bin"
            placeholder="e.g. Bin A"
            data={binSuggestions}
            value={storageBin}
            onChange={setStorageBin}
            size="md"
          />
          <TextInput
            label="Lot code"
            value={lotCode}
            onChange={(e) => setLotCode(e.currentTarget.value)}
            size="md"
          />
          <Autocomplete
            label="Harvested by"
            placeholder="Worker name"
            data={workerSuggestions}
            value={harvestedBy}
            onChange={setHarvestedBy}
            size="md"
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
