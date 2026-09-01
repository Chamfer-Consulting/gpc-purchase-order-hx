import { useState } from "react";
import { ActionIcon, Menu } from "@mantine/core";
import { IconCopy, IconDownload, IconPhotoDown } from "@tabler/icons-react";
import type { EChartsOption } from "@/charts/echartsCore";
import { chartToPng, copyBlob, downloadBlob, slugify, type ExportContext } from "@/charts/exportChart";
import { notifyError, notifySuccess } from "@/lib/notify";

/** The ⋯-less export affordance on a chart card: a quiet download icon that opens
 *  a two-item menu — save a slide-ready PNG, or copy it straight to the clipboard. */
export function ChartExportMenu({ option, title, scope }: { option: EChartsOption } & ExportContext) {
  const [busy, setBusy] = useState<"png" | "copy" | null>(null);

  async function run(kind: "png" | "copy") {
    setBusy(kind);
    try {
      const blob = await chartToPng(option, { title, scope });
      if (kind === "png") {
        downloadBlob(blob, `${slugify(title)}.png`);
      } else if (await copyBlob(blob)) {
        notifySuccess("Chart image copied — paste it into your slides.");
      } else {
        downloadBlob(blob, `${slugify(title)}.png`);
        notifySuccess("Clipboard images aren't available here — downloaded the PNG instead.");
      }
    } catch (e) {
      notifyError(e, "Couldn't export the chart");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Menu shadow="md" width={210} position="bottom-end" withinPortal>
      <Menu.Target>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="sm"
          aria-label="Export chart"
          loading={busy != null}
        >
          <IconPhotoDown size={16} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Export · slide-ready 1280×720</Menu.Label>
        <Menu.Item leftSection={<IconDownload size={15} />} onClick={() => void run("png")}>
          Download PNG
        </Menu.Item>
        <Menu.Item leftSection={<IconCopy size={15} />} onClick={() => void run("copy")}>
          Copy image
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
