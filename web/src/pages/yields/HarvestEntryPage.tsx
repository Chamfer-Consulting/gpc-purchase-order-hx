import { Stack, Text } from "@mantine/core";
import { HarvestEntryForm } from "./HarvestEntryForm";

/** Harvest kiosk home (the 'field' role's only real page) — no PageLayout
 *  chrome here (KioskShell already supplies the page frame), so the title
 *  block is local rather than coming from breadcrumbs/title props. */
export function HarvestEntryPage() {
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
      <HarvestEntryForm />
    </Stack>
  );
}
