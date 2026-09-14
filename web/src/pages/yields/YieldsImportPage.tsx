import { useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  FileInput,
  Group,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { IconArrowRight, IconCheck, IconDownload, IconUpload } from "@tabler/icons-react";
import { useMe } from "@/api/me";
import {
  useCreateYieldProduct,
  useImportYieldEntries,
  useYieldEntries,
  useYieldProducts,
  type YieldUnit,
} from "@/api/yields";
import { csvCell } from "@/components/DataGrid";
import { PageLayout } from "@/components/PageLayout";
import { SectionCard } from "@/components/SectionCard";
import { parseCsv } from "@/lib/csv";
import { errorMessage } from "@/lib/errors";
import { notifyError, notifySuccess } from "@/lib/notify";
import { pageMeta } from "@/nav";

interface ParsedRow {
  rowNum: number;
  product: string;
  date: string | null;
  weight: number | null;
  unit: YieldUnit | null;
  trayCount: number | null;
  harvestedBy: string | null;
  lotCode: string | null;
  error: string | null;
}

type Resolution = { kind: "map"; productId: number } | { kind: "create" };

const CREATE_VALUE = "__create__";
const VALID_UNITS: YieldUnit[] = ["oz", "lb", "g"];

function normalizeHeader(s: string): string {
  return s.trim().toLowerCase().replace(/[\s_]+/g, "");
}

/** Plain edit distance (insert/delete/substitute), no external library —
 *  same "no fuzzy-matching library needed, only a handful of names" call
 *  shared/qbo_matcher.py already makes for customer names; this catalog is
 *  just as small. */
function levenshteinDistance(a: string, b: string): number {
  const m = a.length;
  const n = b.length;
  if (m === 0) return n;
  if (n === 0) return m;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const curr = [i];
    for (let j = 1; j <= n; j++) {
      curr[j] = a[i - 1] === b[j - 1] ? prev[j - 1] : 1 + Math.min(prev[j - 1], prev[j], curr[j - 1]);
    }
    prev = curr;
  }
  return prev[n];
}

/** A close-but-not-exact catalog name — likely a typo in the CSV rather
 *  than a genuinely new crop. Purely a suggestion for the resolution picker
 *  below: nothing is ever mapped or created without the admin explicitly
 *  choosing it (clicking "Use this", or picking from the Select). */
function suggestCloseMatch(
  name: string,
  candidates: { id: number; name: string }[],
): { id: number; name: string } | null {
  const target = name.trim().toLowerCase();
  let best: { id: number; name: string } | null = null;
  let bestDist = Infinity;
  for (const p of candidates) {
    const dist = levenshteinDistance(target, p.name.toLowerCase());
    if (dist < bestDist) {
      bestDist = dist;
      best = p;
    }
  }
  if (!best || bestDist === 0) return null;
  const threshold = Math.max(1, Math.floor(best.name.length * 0.25));
  return bestDist <= threshold ? best : null;
}

/** A per-row unit is optional — most historical imports have no unit column
 *  at all and rely on the single batch-wide unit picker below — but when a
 *  row *does* carry one (notably the downloaded template's own example rows,
 *  which are real past entries and may not be in the batch's chosen unit),
 *  it must be one of the three valid units, not silently coerced. */
function parseUnitCell(raw: string): YieldUnit | null {
  const s = raw.trim().toLowerCase();
  return (VALID_UNITS as string[]).includes(s) ? (s as YieldUnit) : null;
}

const MONTH_NAMES: Record<string, number> = {
  jan: 1, january: 1,
  feb: 2, february: 2,
  mar: 3, march: 3,
  apr: 4, april: 4,
  may: 5,
  jun: 6, june: 6,
  jul: 7, july: 7,
  aug: 8, august: 8,
  sep: 9, sept: 9, september: 9,
  oct: 10, october: 10,
  nov: 11, november: 11,
  dec: 12, december: 12,
};

/** y/mo/da -> "YYYY-MM-DD", but only for a date that actually exists — a
 *  regex alone accepts calendar-invalid values like month 13 or Feb 30
 *  (which would then fail the backend's strict date parsing and 422 the
 *  *entire* import batch instead of just this row), so every candidate is
 *  round-tripped through Date.UTC to confirm it didn't get silently
 *  normalized (e.g. day 30 in April rolling over to May). */
function ymd(y: number, mo: number, da: number): string | null {
  if (mo < 1 || mo > 12 || da < 1 || da > 31) return null;
  const d = new Date(Date.UTC(y, mo - 1, da));
  if (d.getUTCFullYear() !== y || d.getUTCMonth() !== mo - 1 || d.getUTCDate() !== da) return null;
  const pad = (v: number) => String(v).padStart(2, "0");
  return `${y}-${pad(mo)}-${pad(da)}`;
}

/** Accepts the date-cell text Excel, Google Sheets, and Apple Numbers most
 *  commonly produce when saved/exported as CSV:
 *  - ISO "2026-01-05".
 *  - Numeric "1/5/2026" or "1-5-2026" — this business is US-based, so an
 *    ambiguous (day <= 12) numeric date is read month-first, matching all
 *    three apps' default US-locale export. A day > 12 (unambiguously
 *    day-first, e.g. a sheet exported under a DD/MM locale) is rejected
 *    rather than silently reinterpreted — better a flagged row than a
 *    wrong date shipped silently.
 *  - A spelled-out month name — "Jan 5, 2026", "5 Jan 2026", "5-Jan-2026",
 *    "January 5 2026" — unambiguous regardless of day/month order, so
 *    these don't depend on the US-locale assumption above. Common Excel/
 *    Numbers custom date formats (e.g. "d-mmm-yyyy").
 *  - A bare integer, as a last resort — a date cell whose format got reset
 *    to General before export leaks Excel's internal serial day-count
 *    instead of text. Only accepted if it decodes to a plausible year, so
 *    a stray number that isn't actually a date still gets rejected. */
function parseDateCell(raw: string): string | null {
  const s = raw.trim();
  if (!s) return null;

  const iso = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (iso) return ymd(Number(iso[1]), Number(iso[2]), Number(iso[3]));

  const numeric = s.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$/);
  if (numeric) return ymd(Number(numeric[3]), Number(numeric[1]), Number(numeric[2]));

  const monthFirst = s.match(/^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$/);
  if (monthFirst) {
    const mo = MONTH_NAMES[monthFirst[1].toLowerCase()];
    if (mo) return ymd(Number(monthFirst[3]), mo, Number(monthFirst[2]));
  }

  const dayFirst = s.match(/^(\d{1,2})(?:st|nd|rd|th)?[\s-]+([A-Za-z]+)\.?[\s,-]+(\d{4})$/);
  if (dayFirst) {
    const mo = MONTH_NAMES[dayFirst[2].toLowerCase()];
    if (mo) return ymd(Number(dayFirst[3]), mo, Number(dayFirst[1]));
  }

  if (/^\d{4,6}$/.test(s)) {
    const serial = Number(s);
    // Excel's day 0 is 1899-12-30 (not -12-31 or 1900-01-01) — the
    // standard correction for its built-in "1900 was a leap year" bug,
    // valid for every serial number past that fictitious Feb 29, 1900.
    const d = new Date(Date.UTC(1899, 11, 30) + serial * 86_400_000);
    const y = d.getUTCFullYear();
    if (y >= 1970 && y <= 2200) return ymd(y, d.getUTCMonth() + 1, d.getUTCDate());
  }

  return null;
}

const PREVIEW_LIMIT = 50;

export function YieldsImportPage() {
  const meta = pageMeta("/yields/import");
  const { canAdmin, roleKnown } = useMe();
  const products = useYieldProducts(true);
  const recent = useYieldEntries({});
  const createProduct = useCreateYieldProduct();
  const importEntries = useImportYieldEntries();

  const [file, setFile] = useState<File | null>(null);
  const [headerError, setHeaderError] = useState<string | null>(null);
  const [parsed, setParsed] = useState<ParsedRow[] | null>(null);
  const [resolutions, setResolutions] = useState<Record<string, Resolution>>({});
  // oz is the app-wide default (HarvestEntryForm, the DB column default) —
  // match it here too, for rows with no unit column of their own.
  const [unit, setUnit] = useState<YieldUnit>("oz");
  const [harvestedBy, setHarvestedBy] = useState("");
  const [importing, setImporting] = useState(false);
  const [lastResult, setLastResult] = useState<{ created: number; duplicates: number } | null>(null);

  const downloadTemplate = () => {
    const header = ["date", "product", "weight", "unit", "trays", "harvester", "lot_code"];
    const examples = (recent.data ?? [])
      .slice(0, 5)
      .map((e) => [
        e.harvest_date,
        e.product_name,
        String(e.weight),
        e.unit,
        String(e.tray_count),
        e.harvested_by,
        e.lot_code ?? "",
      ]);
    const lines = [header, ...examples].map((cells) => cells.map(csvCell).join(","));
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "yields-import-template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleFile = async (f: File | null) => {
    setFile(f);
    setResolutions({});
    setLastResult(null);
    if (!f) {
      setParsed(null);
      setHeaderError(null);
      return;
    }
    const text = await f.text();
    const table = parseCsv(text);
    if (table.length < 2) {
      setHeaderError("The file has no data rows.");
      setParsed(null);
      return;
    }
    const header = table[0].map(normalizeHeader);
    const dateIx = header.findIndex((h) => h === "date" || h === "harvestdate");
    const productIx = header.findIndex((h) => h === "product" || h === "productname" || h === "crop");
    const weightIx = header.findIndex((h) => h === "weight");
    const unitIx = header.findIndex((h) => h === "unit");
    const traysIx = header.findIndex((h) => h === "trays" || h === "traycount" || h === "traysharvested");
    const harvesterIx = header.findIndex((h) => h === "harvester" || h === "harvestedby");
    const lotIx = header.findIndex((h) => h === "lotcode" || h === "lot");
    if (dateIx < 0 || productIx < 0 || weightIx < 0) {
      setHeaderError(
        `Couldn't find the required columns — need "date", "product", and "weight". Found: ${table[0].join(", ")}`,
      );
      setParsed(null);
      return;
    }
    setHeaderError(null);
    const rows: ParsedRow[] = table.slice(1).map((cells, i) => {
      const productRaw = (cells[productIx] ?? "").trim();
      const dateRaw = (cells[dateIx] ?? "").trim();
      const weightRaw = (cells[weightIx] ?? "").trim();
      const unitRaw = unitIx >= 0 ? (cells[unitIx] ?? "").trim() : "";
      const traysRaw = traysIx >= 0 ? (cells[traysIx] ?? "").trim() : "";
      const harvesterRaw = harvesterIx >= 0 ? (cells[harvesterIx] ?? "").trim() : "";
      const lotRaw = lotIx >= 0 ? (cells[lotIx] ?? "").trim() : "";
      const date = parseDateCell(dateRaw);
      const weightNum = weightRaw ? Number(weightRaw) : NaN;
      const unitCell = unitRaw ? parseUnitCell(unitRaw) : null;
      const traysNum = traysRaw ? Number(traysRaw) : NaN;
      let error: string | null = null;
      if (!productRaw) error = "Missing product";
      else if (!date) error = `Unparseable date "${dateRaw}"`;
      else if (!Number.isFinite(weightNum) || weightNum <= 0) error = `Invalid weight "${weightRaw}"`;
      else if (unitRaw && !unitCell) error = `Unrecognized unit "${unitRaw}" (must be oz, lb, or g)`;
      else if (traysRaw && (!Number.isInteger(traysNum) || traysNum < 0))
        error = `Invalid trays "${traysRaw}"`;
      return {
        rowNum: i + 2,
        product: productRaw,
        date,
        weight: Number.isFinite(weightNum) ? weightNum : null,
        unit: unitCell,
        trayCount: traysRaw && Number.isFinite(traysNum) ? traysNum : null,
        harvestedBy: harvesterRaw || null,
        lotCode: lotRaw || null,
        error,
      };
    });
    setParsed(rows);
  };

  // Only active products auto-match a CSV row's name — a name that matches a
  // *retired* product still falls into "unmatched" below, so the admin has to
  // explicitly decide (via the resolution picker, which does list retired
  // products) rather than new entries silently landing on a retired product.
  const activeProducts = useMemo(() => (products.data ?? []).filter((p) => p.active), [products.data]);
  const productNameSet = useMemo(
    () => new Set(activeProducts.map((p) => p.name.toLowerCase())),
    [activeProducts],
  );
  const productOptions = useMemo(
    () => (products.data ?? []).map((p) => ({ value: String(p.id), label: p.name })),
    [products.data],
  );

  // Keyed by lowercase name — the "already exists" check above (productNameSet)
  // is case-insensitive, so grouping unmatched rows case-sensitively would
  // split one real unmatched product into several undercounted entries (e.g.
  // "Toscano Kale" and "toscano kale" as two separate unresolved groups).
  // Each group keeps the first-seen casing as its display/create name. Each
  // also gets a `suggestion` — the closest catalog name by edit distance
  // (active or retired, same pool the manual picker offers), for the "did
  // you mean…" prompt below. It's only ever a suggestion: nothing is mapped
  // or created without the admin clicking something.
  const unmatchedNames = useMemo(() => {
    if (!parsed) return [];
    const seen = new Map<string, string>();
    for (const r of parsed) {
      if (!r.error && r.product && !productNameSet.has(r.product.toLowerCase())) {
        const key = r.product.toLowerCase();
        if (!seen.has(key)) seen.set(key, r.product);
      }
    }
    const catalog = products.data ?? [];
    return Array.from(seen.entries())
      .map(([key, name]) => ({ key, name, suggestion: suggestCloseMatch(name, catalog) }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [parsed, productNameSet, products.data]);

  const countFor = (key: string) => parsed?.filter((r) => r.product.toLowerCase() === key).length ?? 0;

  const validCount = parsed ? parsed.filter((r) => !r.error).length : 0;
  const errorRows = parsed ? parsed.filter((r) => r.error) : [];

  const allResolved = unmatchedNames.every((n) => resolutions[n.key] != null);
  const canImport =
    !!parsed && !headerError && validCount > 0 && allResolved && harvestedBy.trim() !== "" && !importing;

  const handleImport = async () => {
    if (!parsed || !canImport) return;
    setImporting(true);
    try {
      const toCreate = unmatchedNames.filter(({ key }) => resolutions[key]?.kind === "create");
      const createdProducts = await Promise.all(
        toCreate.map(({ name }) => createProduct.mutateAsync({ name })),
      );
      const createdIds: Record<string, number> = {};
      toCreate.forEach(({ key }, i) => {
        createdIds[key] = createdProducts[i].id;
      });
      const idByLowerName = new Map(activeProducts.map((p) => [p.name.toLowerCase(), p.id]));
      const resolveProductId = (rawName: string): number | null => {
        const key = rawName.toLowerCase();
        const exact = idByLowerName.get(key);
        if (exact != null) return exact;
        const res = resolutions[key];
        if (res?.kind === "map") return res.productId;
        if (res?.kind === "create") return createdIds[key] ?? null;
        return null;
      };
      const entries = parsed
        .filter((r) => !r.error)
        .map((r) => ({
          yield_product_id: resolveProductId(r.product),
          harvest_date: r.date as string,
          weight: r.weight as number,
          unit: r.unit ?? unit,
          tray_count: r.trayCount ?? 0,
          lot_code: r.lotCode,
          harvested_by: r.harvestedBy ?? harvestedBy.trim(),
        }))
        .filter((e): e is typeof e & { yield_product_id: number } => e.yield_product_id != null);

      const result = await importEntries.mutateAsync(entries);
      notifySuccess(`Imported ${result.created} entries.`);
      setLastResult({ created: result.created, duplicates: result.skipped_duplicates });
      setFile(null);
      setParsed(null);
      setResolutions({});
    } catch (e) {
      notifyError(e);
    } finally {
      setImporting(false);
    }
  };

  if (roleKnown && !canAdmin) {
    return (
      <PageLayout title={meta?.title ?? "Import"} description={meta?.description} breadcrumbs={meta?.breadcrumbs}>
        <Alert color="gray" variant="light" title="Admin access required">
          Bulk-importing historical entries is only available to admins.
        </Alert>
      </PageLayout>
    );
  }

  return (
    <PageLayout
      title={meta?.title ?? "Import"}
      description={meta?.description ?? "Bring in past harvest history from a CSV file."}
      breadcrumbs={meta?.breadcrumbs}
      width="form"
    >
      <SectionCard
        title="Upload a CSV"
        subtitle='Columns: "date" (accepts however Excel, Sheets, or Numbers exports it — e.g. "2026-01-05", "1/5/2026", or "5-Jan-2026"), "product", "weight" — plus optionally "unit", "trays", "harvester", and "lot_code".'
        actions={
          <Button
            size="xs"
            variant="light"
            leftSection={<IconDownload size={14} />}
            onClick={downloadTemplate}
            disabled={recent.isLoading}
          >
            Download template
          </Button>
        }
      >
        <Stack gap="md">
          <Text size="xs" c="dimmed">
            The template includes your 5 most recent entries as examples — replace or delete them before
            filling in your own rows. If you leave them in, they won't be double-entered: importing a row
            that already matches an existing entry (same product, date, weight, and unit) is skipped
            automatically.
          </Text>
          <FileInput
            placeholder="Choose a .csv file"
            accept=".csv,text/csv"
            leftSection={<IconUpload size={16} />}
            value={file}
            onChange={handleFile}
            clearable
          />

          {headerError && (
            <Alert color="red" variant="light">
              {headerError}
            </Alert>
          )}

          {lastResult != null && (
            <Alert color="gpGreen" icon={<IconCheck size={18} />} variant="light">
              Imported {lastResult.created} entries.
              {lastResult.duplicates > 0 &&
                ` Skipped ${lastResult.duplicates} already-present entr${lastResult.duplicates === 1 ? "y" : "ies"}.`}
            </Alert>
          )}

          {parsed && !headerError && (
            <>
              <Group gap="sm" wrap="wrap">
                <Badge variant="light" color="gpGreen">
                  {validCount} valid row{validCount === 1 ? "" : "s"}
                </Badge>
                {errorRows.length > 0 && (
                  <Badge variant="light" color="red">
                    {errorRows.length} skipped
                  </Badge>
                )}
              </Group>

              {errorRows.length > 0 && (
                <Alert color="yellow" variant="light" title="Rows that will be skipped">
                  <Stack gap={2}>
                    {errorRows.slice(0, 20).map((r) => (
                      <Text key={r.rowNum} size="xs">
                        Row {r.rowNum}: {r.error}
                      </Text>
                    ))}
                    {errorRows.length > 20 && (
                      <Text size="xs" c="dimmed">
                        …and {errorRows.length - 20} more
                      </Text>
                    )}
                  </Stack>
                </Alert>
              )}

              {unmatchedNames.length > 0 && (
                <SectionCard
                  title="Resolve unmatched products"
                  subtitle="These names don't match anything in your product catalog yet — map each to an existing product or create a new one. Nothing is added automatically."
                >
                  <Stack gap="sm">
                    {unmatchedNames.map(({ key, name, suggestion }) => (
                      <Stack key={key} gap={4}>
                        <Group justify="space-between" wrap="nowrap" gap="sm">
                          <div style={{ minWidth: 0, flex: "1 1 auto" }}>
                            <Text size="sm" fw={500} truncate>
                              {name}
                            </Text>
                            <Text size="xs" c="dimmed">
                              {countFor(key)} row{countFor(key) === 1 ? "" : "s"}
                            </Text>
                          </div>
                          <Select
                            placeholder="Map or create…"
                            data={[
                              { value: CREATE_VALUE, label: `+ Create "${name}"` },
                              ...productOptions,
                            ]}
                            value={
                              resolutions[key]?.kind === "map"
                                ? String(resolutions[key].productId)
                                : resolutions[key]?.kind === "create"
                                  ? CREATE_VALUE
                                  : null
                            }
                            onChange={(v) =>
                              setResolutions((r) => ({
                                ...r,
                                ...(v == null
                                  ? {}
                                  : {
                                      [key]:
                                        v === CREATE_VALUE
                                          ? { kind: "create" }
                                          : { kind: "map", productId: Number(v) },
                                    }),
                              }))
                            }
                            searchable
                            size="xs"
                            w={220}
                          />
                        </Group>
                        {suggestion && resolutions[key] == null && (
                          <Group gap={6} wrap="nowrap">
                            <Text size="xs" c="dimmed">
                              Possible spelling mistake — did you mean
                            </Text>
                            <IconArrowRight size={12} style={{ opacity: 0.6 }} />
                            <Badge size="xs" variant="light" color="gpGreen">
                              {suggestion.name}
                            </Badge>
                            <Button
                              size="compact-xs"
                              variant="subtle"
                              onClick={() =>
                                setResolutions((r) => ({
                                  ...r,
                                  [key]: { kind: "map", productId: suggestion.id },
                                }))
                              }
                            >
                              Use this
                            </Button>
                          </Group>
                        )}
                      </Stack>
                    ))}
                  </Stack>
                </SectionCard>
              )}

              <Group gap="sm" wrap="wrap" align="flex-end">
                <Select
                  label="Weight unit"
                  description="Used for rows without their own unit column"
                  data={[
                    { value: "oz", label: "oz" },
                    { value: "lb", label: "lb" },
                    { value: "g", label: "g" },
                  ]}
                  value={unit}
                  onChange={(v) => setUnit((v as YieldUnit) ?? "oz")}
                  allowDeselect={false}
                  w={220}
                />
                <TextInput
                  label="Attribute these entries to"
                  placeholder="e.g. Historical Import, or a name"
                  value={harvestedBy}
                  onChange={(e) => setHarvestedBy(e.currentTarget.value)}
                  description="Used for rows without their own harvester column"
                  w={320}
                />
              </Group>

              {parsed.filter((r) => !r.error).length > 0 && (
                <Table.ScrollContainer minWidth={760} maxHeight={360} type="native">
                  <Table verticalSpacing="xs" stickyHeader>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Row</Table.Th>
                        <Table.Th>Date</Table.Th>
                        <Table.Th>Product</Table.Th>
                        <Table.Th ta="right">Weight</Table.Th>
                        <Table.Th ta="right">Trays</Table.Th>
                        <Table.Th>Harvester</Table.Th>
                        <Table.Th>Lot</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {parsed
                        .filter((r) => !r.error)
                        .slice(0, PREVIEW_LIMIT)
                        .map((r) => (
                          <Table.Tr key={r.rowNum}>
                            <Table.Td>{r.rowNum}</Table.Td>
                            <Table.Td>{r.date}</Table.Td>
                            <Table.Td>{r.product}</Table.Td>
                            <Table.Td ta="right">
                              {r.weight} {r.unit ?? unit}
                            </Table.Td>
                            <Table.Td ta="right">{r.trayCount ?? 0}</Table.Td>
                            <Table.Td>{r.harvestedBy ?? (harvestedBy.trim() || "—")}</Table.Td>
                            <Table.Td>{r.lotCode ?? "—"}</Table.Td>
                          </Table.Tr>
                        ))}
                    </Table.Tbody>
                  </Table>
                  {validCount > PREVIEW_LIMIT && (
                    <Text size="xs" c="dimmed" mt="xs">
                      Showing the first {PREVIEW_LIMIT} of {validCount} rows.
                    </Text>
                  )}
                </Table.ScrollContainer>
              )}

              {importEntries.error && <Alert color="red">{errorMessage(importEntries.error)}</Alert>}

              <Group justify="flex-end">
                <Button loading={importing} disabled={!canImport} onClick={handleImport}>
                  Import {validCount} entr{validCount === 1 ? "y" : "ies"}
                </Button>
              </Group>
            </>
          )}
        </Stack>
      </SectionCard>
    </PageLayout>
  );
}
