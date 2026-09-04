/**
 * US federal holidays — computed, not a hardcoded per-year table, so the range
 * this app's data spans (2017 on) and any future year both just work. Purely a
 * "did order volume move around this date" overlay, not a bank/observance
 * calendar: a fixed-date holiday landing on a weekend is NOT shifted to the
 * nearest weekday (that shift is about which day a bank is closed, not about
 * when a customer's ordering behavior would actually move).
 */
export interface Holiday {
  /** ISO "YYYY-MM-DD" */
  date: string;
  name: string;
}

const iso = (y: number, m: number, d: number): string =>
  `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;

/** The date of the nth (1-based) given weekday (0=Sun..6=Sat) in a month. */
function nthWeekday(year: number, month: number, weekday: number, n: number): number {
  const firstWeekday = new Date(Date.UTC(year, month, 1)).getUTCDay();
  return 1 + ((weekday - firstWeekday + 7) % 7) + (n - 1) * 7;
}

/** The date of the LAST given weekday in a month. */
function lastWeekday(year: number, month: number, weekday: number): number {
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const lastDayWeekday = new Date(Date.UTC(year, month, daysInMonth)).getUTCDay();
  return daysInMonth - ((lastDayWeekday - weekday + 7) % 7);
}

/** The 11 US federal holidays observed in one calendar year. */
export function usHolidaysForYear(year: number): Holiday[] {
  return [
    { date: iso(year, 0, 1), name: "New Year's Day" },
    { date: iso(year, 0, nthWeekday(year, 0, 1, 3)), name: "Martin Luther King Jr. Day" },
    { date: iso(year, 1, nthWeekday(year, 1, 1, 3)), name: "Presidents' Day" },
    { date: iso(year, 4, lastWeekday(year, 4, 1)), name: "Memorial Day" },
    { date: iso(year, 5, 19), name: "Juneteenth" },
    { date: iso(year, 6, 4), name: "Independence Day" },
    { date: iso(year, 8, nthWeekday(year, 8, 1, 1)), name: "Labor Day" },
    { date: iso(year, 9, nthWeekday(year, 9, 1, 2)), name: "Columbus Day" },
    { date: iso(year, 10, 11), name: "Veterans Day" },
    { date: iso(year, 10, nthWeekday(year, 10, 4, 4)), name: "Thanksgiving" },
    { date: iso(year, 11, 25), name: "Christmas Day" },
  ];
}

/** US federal holidays falling within [startISO, endISO] inclusive. */
export function usHolidaysInRange(startISO: string, endISO: string): Holiday[] {
  const y0 = Number(startISO.slice(0, 4));
  const y1 = Number(endISO.slice(0, 4));
  if (!Number.isFinite(y0) || !Number.isFinite(y1)) return [];
  const out: Holiday[] = [];
  for (let y = y0; y <= y1; y++) out.push(...usHolidaysForYear(y));
  return out.filter((h) => h.date >= startISO && h.date <= endISO);
}
