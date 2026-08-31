# Supabase migrations

Numbered, applied in order. `0001` builds the whole schema from scratch; `0002+`
are the deltas made on `po-dashboard-rebuild` after the pre-cutover Neon schema.

| # | File | What it does |
|---|------|--------------|
| 0001 | `0001_init.sql` | **Full base schema** — every table + index, ordered to run top-to-bottom on an empty DB. Same objects as `/schema.sql` (which the extraction pipeline applies to the live DB); this is the migration baseline. |
| 0002 | `0002_admin_crud.sql` | PO lifecycle `status` + soft delete, per-line `voided`, `audit_log`, and the `status` CHECK constraint. |
| 0003 | `0003_po_documents.sql` | `po_documents` table (captured PO/invoice PDFs) + its `kind` CHECK constraint. |
| 0004 | `0004_drop_gdrive.sql` | Drops the retired `purchase_orders.drive_file_id` / `drive_synced_at`. |
| 0005 | `0005_rls_lockdown.sql` | Enables RLS (deny-all, no policies) on every `public` table, revokes all `anon` / `authenticated` grants, and installs an `ensure_rls` event trigger so future tables get RLS automatically. Needs the `postgres` role. |

Every file is idempotent (`IF NOT EXISTS` / guarded `DO $$`), so re-running any of
them is safe.

## Row-level security model

All DB access is server-side: the FastAPI backend connects as `postgres`
(`BYPASSRLS`); the browser only ever calls Supabase **Auth**, never PostgREST.
So `0005` locks `public` down completely — `anon` and `authenticated` can neither
reach a row (RLS deny-all) nor even hold a table grant. The Supabase advisor's
17× "RLS enabled, no policy" is **INFO-level and expected** here; do not add
policies. (One opt-in exception is noted in `0005` for the review-queue Realtime
feed.)

## Applying

Run all five, in order, against the **session** connection:

```bash
# SUPABASE_SESSION_URL = Supabase → Settings → Database → Connection string → Session (:5432)
for f in supabase/migrations/[0-9]*.sql; do
  echo ">>> $f"; psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f "$f" || break
done
```

All idempotent. `0001` builds the schema; `0002`–`0003` add two CHECK constraints;
`0004` drops the retired Drive columns; `0005` enables RLS + revokes the
browser-role grants. Then load data — a **data-only** `pg_dump`/`pg_restore` from
Neon (`docs/REBUILD-SETUP.md` §2.2), or by running the extraction pipeline against
the new `DATABASE_URL`.

`supabase db push` does the same and records versions in
`supabase_migrations.schema_migrations`; the `psql` loop is the reliable path.
Don't do a full `pg_restore --clean` of a Neon dump *after* the migrations — it
would drop the migrated schema (RLS lockdown included).

## Relationship to `schema.sql`

`/schema.sql` stays the canonical full schema the extraction pipeline applies on
every publish. `0001_init.sql` is a copy of it (transaction-wrapped, reordered so
`po_documents` follows `qbo_invoices`). Future schema changes go in **both**: a
new `0005_*.sql` here **and** the matching block in `/schema.sql`. Migrations are
append-only — never edit `0001` after it's been applied anywhere.
