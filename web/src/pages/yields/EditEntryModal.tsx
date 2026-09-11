import { useMemo, useState } from "react";
import {
  Alert,
  Button,
  Group,
  Modal,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { errorMessage } from "@/lib/errors";
import { notifyError, notifySuccess } from "@/lib/notify";
import { useUpdateYieldEntry, useYieldEmployees, type YieldEntry, type YieldUnit } from "@/api/yields";

function EditEntryForm({ entry, employees, onClose }: {
  entry: YieldEntry;
  employees: string[];
  onClose: () => void;
}) {
  const update = useUpdateYieldEntry();

  const [date, setDate] = useState(entry.harvest_date);
  const [weight, setWeight] = useState<number | "">(entry.weight);
  const [unit, setUnit] = useState<YieldUnit>(entry.unit);
  const [trayCount, setTrayCount] = useState<number | "">(entry.tray_count);
  const [discardedTrayCount, setDiscardedTrayCount] = useState<number | "">(entry.discarded_tray_count);
  const [lotCode, setLotCode] = useState(entry.lot_code ?? "");
  const [harvestedBy, setHarvestedBy] = useState(entry.harvested_by);
  const [notes, setNotes] = useState(entry.notes ?? "");

  const canSave = weight !== "" && Number(weight) > 0 && harvestedBy.trim() !== "";

  const save = () => {
    if (!canSave) return;
    update.mutate(
      {
        id: entry.id,
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
          notifySuccess("Entry updated.");
          onClose();
        },
        onError: (e) => notifyError(e),
      },
    );
  };

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        {entry.product_name}
      </Text>
      <TextInput type="date" label="Harvest date" value={date} onChange={(e) => setDate(e.currentTarget.value)} />
      <Group grow align="flex-end">
        <NumberInput
          label="Weight"
          value={weight}
          onChange={(v) => setWeight(v === "" ? "" : Number(v))}
          min={0}
          decimalScale={2}
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
        />
      </Group>
      <Group grow>
        <NumberInput
          label="Trays harvested"
          description="Number of trays in bin"
          value={trayCount}
          onChange={(v) => setTrayCount(v === "" ? "" : Number(v))}
          min={0}
        />
        <NumberInput
          label="Trays discarded"
          description="Not harvestable"
          value={discardedTrayCount}
          onChange={(v) => setDiscardedTrayCount(v === "" ? "" : Number(v))}
          min={0}
        />
      </Group>
      <TextInput label="Lot code" value={lotCode} onChange={(e) => setLotCode(e.currentTarget.value)} />
      <Select
        label="Harvested by"
        data={employees}
        value={harvestedBy || null}
        onChange={(v) => setHarvestedBy(v ?? "")}
        searchable
        required
      />
      <Textarea label="Notes" value={notes} onChange={(e) => setNotes(e.currentTarget.value)} autosize minRows={2} />

      {update.error && <Alert color="red">{errorMessage(update.error)}</Alert>}

      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>
          Cancel
        </Button>
        <Button loading={update.isPending} disabled={!canSave} onClick={save}>
          Save
        </Button>
      </Group>
    </Stack>
  );
}

/** Corrections to an already-logged entry — shared by the kiosk's "My recent
 *  entries" and the office entries table. `entry` is the row being edited
 *  (null = closed); keyed by id so switching which row is open resets the
 *  form to that row's values instead of carrying over stale edits. */
export function EditEntryModal({ entry, onClose }: { entry: YieldEntry | null; onClose: () => void }) {
  const employees = useYieldEmployees();
  const employeeOptions = useMemo(() => (employees.data ?? []).map((e) => e.name), [employees.data]);

  return (
    <Modal opened={entry != null} onClose={onClose} title="Edit harvest entry" size="md">
      {entry && <EditEntryForm key={entry.id} entry={entry} employees={employeeOptions} onClose={onClose} />}
    </Modal>
  );
}
