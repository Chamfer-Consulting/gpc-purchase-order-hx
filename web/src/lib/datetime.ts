/**
 * Every timestamp in the app is shown in one fixed business timezone — not each
 * viewer's browser zone. This is a single-location business: "when" something
 * happened (an edit, a sync, a status change) should read the same for everyone
 * looking at it, whether they're logged in from the warehouse or a phone three
 * states away. The alternative (auto-detected per-viewer timezone) would make two
 * people looking at the same audit row see different times and, worse, silently
 * disagree on which *day* something happened near midnight.
 *
 * The backend always sends timestamps as timezone-aware ISO 8601 (a Postgres
 * TIMESTAMPTZ serialized with its UTC offset) — Intl.DateTimeFormat converts that
 * correctly regardless of the server's own session timezone. A plain DATE column
 * (po_date, delivery_date, txn_date — no time-of-day, no offset) has nothing to
 * convert and is left exactly as the server sent it.
 */
export const BUSINESS_TIMEZONE = "America/Chicago";

const PLAIN_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

const dateTimeParts = new Intl.DateTimeFormat("en-US", {
  timeZone: BUSINESS_TIMEZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const dateParts = new Intl.DateTimeFormat("en-US", {
  timeZone: BUSINESS_TIMEZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const tzName = new Intl.DateTimeFormat("en-US", {
  timeZone: BUSINESS_TIMEZONE,
  timeZoneName: "short",
});

function part(fmt: Intl.DateTimeFormat, d: Date, type: string): string {
  return fmt.formatToParts(d).find((p) => p.type === type)?.value ?? "";
}

/** Business-timezone abbreviation for a given instant (CST or CDT — the offset
 *  changes with daylight saving, so this isn't a fixed string). */
export function tzAbbrev(d: Date = new Date()): string {
  return part(tzName, d, "timeZoneName");
}

/** A timestamptz value ("2026-09-04T13:42:00Z" or a Postgres-style offset string)
 *  -> "2026-09-04 08:42 CDT" in the business timezone. "—" for null/unparseable. */
export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  const g = (t: string) => part(dateTimeParts, d, t);
  return `${g("year")}-${g("month")}-${g("day")} ${g("hour")}:${g("minute")} ${tzAbbrev(d)}`;
}

/** The calendar date a timestamptz value falls on in the business timezone —
 *  for a TIMESTAMPTZ column shown as a bare date (e.g. "captured", "delivered").
 *  A plain DATE-column string ("YYYY-MM-DD", no time part) passes through
 *  unchanged — there's no time-of-day to shift across a timezone boundary. */
export function fmtDateOnly(value: string | null | undefined): string {
  if (!value) return "—";
  if (PLAIN_DATE_RE.test(value)) return value;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  const g = (t: string) => part(dateParts, d, t);
  return `${g("year")}-${g("month")}-${g("day")}`;
}
