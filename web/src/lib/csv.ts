/**
 * Minimal RFC4180-ish CSV parser — quoted fields (commas/newlines inside
 * quotes, "" as an escaped quote), CRLF or LF line endings. No dependency:
 * this is the only CSV-consuming feature in the app so far (see the Yields
 * import page), and the format is small/known enough not to warrant one.
 */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  let i = 0;
  const n = text.length;

  const endField = () => {
    row.push(field);
    field = "";
  };
  const endRow = () => {
    endField();
    rows.push(row);
    row = [];
  };

  while (i < n) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i++;
        continue;
      }
      field += c;
      i++;
      continue;
    }
    if (c === '"') {
      inQuotes = true;
      i++;
      continue;
    }
    if (c === ",") {
      endField();
      i++;
      continue;
    }
    if (c === "\r") {
      i++;
      continue;
    }
    if (c === "\n") {
      endRow();
      i++;
      continue;
    }
    field += c;
    i++;
  }
  // trailing field/row (a file with no final newline)
  if (field !== "" || row.length > 0) endRow();

  // drop fully-blank trailing rows (a trailing newline in the file)
  while (rows.length > 0 && rows[rows.length - 1].every((f) => f.trim() === "")) rows.pop();

  return rows;
}
