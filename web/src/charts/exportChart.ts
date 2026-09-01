/**
 * Presentation-quality chart export. Renders the chart off-screen at a fixed
 * 16:9 slide size, always on the light theme with a white ground, a proper
 * heading, the scope it was taken under, and a small footer credit — then hands
 * back a 2× PNG you can drop straight into a deck (download or clipboard).
 */
import { echarts, type EChartsOption } from "./echartsCore";
import { registerChartThemes } from "./theme";
import { FONT_FAMILY, LIGHT } from "./palette";

registerChartThemes();

const W = 1280;
const H = 720;
const BG = "#ffffff";
const CREDIT = "Garfield Produce · PO Dashboard";

export interface ExportContext {
  /** the chart's own heading */
  title: string;
  /** one line of context — date range, active filters, "All time", … */
  scope?: string;
}

function today(): string {
  return new Date().toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

/** Merge presentation chrome onto the live option. Keeps the data/series exactly;
 *  replaces layout, drops interactive-only bits (zoom slider, tooltip). */
function framed(base: EChartsOption, ctx: ExportContext): EChartsOption {
  const bump = (o: unknown, size: number) => {
    const one = (a: Record<string, unknown>) => ({
      ...a,
      axisLabel: { ...(a.axisLabel as object), fontSize: size },
      nameTextStyle: { ...(a.nameTextStyle as object), fontSize: size },
    });
    return Array.isArray(o) ? o.map((a) => one(a as Record<string, unknown>)) : o ? one(o as Record<string, unknown>) : o;
  };

  return {
    ...base,
    backgroundColor: BG,
    animation: false,
    dataZoom: undefined,
    tooltip: { show: false },
    title: [
      {
        text: ctx.title,
        subtext: ctx.scope || undefined,
        left: 44,
        top: 30,
        textStyle: { fontFamily: FONT_FAMILY, color: LIGHT.inkPrimary, fontSize: 22, fontWeight: 700 },
        subtextStyle: { fontFamily: FONT_FAMILY, color: LIGHT.inkMuted, fontSize: 13 },
      },
      {
        text: `${CREDIT}  ·  ${today()}`,
        left: 44,
        bottom: 22,
        textStyle: { fontFamily: FONT_FAMILY, color: LIGHT.inkMuted, fontSize: 11, fontWeight: 400 },
      },
    ],
    grid: {
      left: 56,
      right: 52,
      top: ctx.scope ? 104 : 84,
      bottom: 78,
      containLabel: true,
    },
    legend: {
      ...(base.legend as object),
      top: ctx.scope ? 104 : 84,
      right: 24,
      left: "auto",
      textStyle: { fontFamily: FONT_FAMILY, color: LIGHT.inkMuted, fontSize: 12 },
    },
    xAxis: bump(base.xAxis, 12) as EChartsOption["xAxis"],
    yAxis: bump(base.yAxis, 12) as EChartsOption["yAxis"],
  };
}

/** Render to a PNG blob. */
export async function chartToPng(base: EChartsOption, ctx: ExportContext): Promise<Blob> {
  const host = document.createElement("div");
  host.style.cssText = `position:fixed;left:-99999px;top:0;width:${W}px;height:${H}px;pointer-events:none`;
  document.body.appendChild(host);
  const inst = echarts.init(host, "po-light", { renderer: "canvas", width: W, height: H });
  try {
    inst.setOption(framed(base, ctx), true);
    // canvas paints synchronously on setOption; a frame's grace keeps it safe
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    const url = inst.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: BG });
    const res = await fetch(url);
    return await res.blob();
  } finally {
    inst.dispose();
    host.remove();
  }
}

export function slugify(s: string): string {
  return (s || "chart").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "").slice(0, 60);
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** True if the image made it onto the clipboard. */
export async function copyBlob(blob: Blob): Promise<boolean> {
  try {
    if (!navigator.clipboard || typeof ClipboardItem === "undefined") return false;
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    return true;
  } catch {
    return false;
  }
}
