# Supabase migrations

Numbered, applied in order. `0001` builds the whole schema from scratch; `0002+`
are the deltas made on `po-dashboard-rebuild` after the pre-cutover Neon schema.

| # | File | What it does |
|---|------|--------------|
| 0001 | `0001_init.sql` | **Full base schema** — every table + index, ordered to run top-to-bottom on an empty DB. Same objects as `/schema.sql` (which the extraction pipeline applies to the live DB); this is the migration baseline. |
| 0002 | `0002_admin_crud.sql` | PO lifecycle `status` + soft delete, per-line `voided`, `audit_log`, and the `status` CHECK constraint. |
| 0003 | `0003_po_documents.sql` | `po_documents` table (captured PO/invoice PDFs) + its `kind` CHECK constraint. |
| 0004 | `0004_drop_gdrive.sql` | Drops the retired `purchase_orders.drive_file_id` / `drive_synced_at`. |

Every file is idempotent (`IF NOT EXISTS` / guarded `DO $$`), so re-running any of
them is safe.

## Applying

### A — fresh Supabase database, no data to carry over

```bash
# SUPABASE_SESSION_URL = Supabase → Settings → Database → Connection string → Session (:5432)
for f in supabase/migrations/[0-9]*.sql; do
  echo ">>> $f"; psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f "$f" || break
done
```

`0001` alone produces the current schema; `0002`–`0004` then only add the two
CHECK constraints and are otherwise no-ops. Bring data in afterward by running the
extraction pipeline against the new `DATABASE_URL`, or with a data-only dump.

### B — migrating an existing (pre-cutover) Neon database

Restore the Neon dump first (see `docs/REBUILD-SETUP.md` §2), **then** apply the
deltas the old schema predates:

```bash
for f in supabase/migrations/000[2-4]_*.sql; do
  echo ">>> $f"; psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f "$f" || break
done
```

Running `0001` after a Neon restore is also harmless (all `IF NOT EXISTS`).

### Supabase CLI

`supabase db push` applies every file not yet recorded in
`supabase_migrations.schema_migrations`, in filename order — so `0001` → `0004`.
The plain-`psql` loop above is the reliable path for this repo; use `db push` if
you want the CLI to track applied versions.

## Relationship to `schema.sql`

`/schema.sql` stays the canonical full schema the extraction pipeline applies on
every publish. `0001_init.sql` is a copy of it (transaction-wrapped, reordered so
`po_documents` follows `qbo_invoices`). Future schema changes go in **both**: a
new `0005_*.sql` here **and** the matching block in `/schema.sql`. Migrations are
append-only — never edit `0001` after it's been applied anywhere.
