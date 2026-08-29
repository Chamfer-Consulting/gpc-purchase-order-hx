# Supabase migrations

Deltas applied to the Supabase Postgres **after** the one-time Neon → Supabase
data load (see `docs/REBUILD-SETUP.md` §2). The base schema comes over with that
`pg_dump | psql`; everything here is a change made since, in timestamp order.

| Migration | What it does |
|-----------|--------------|
| `20260828120000_admin_crud.sql` | PO lifecycle `status` + soft delete, per-line `voided`, `audit_log` table. Backs the admin CRUD surface on `po-dashboard-rebuild`. |
| `20260828130000_po_documents.sql` | `po_documents` table — captured source PDFs (emailed PO from Gmail, invoice from QuickBooks), bytes stored inline. |
| `20260829000000_drop_gdrive.sql` | Drops `purchase_orders.drive_file_id` / `drive_synced_at`. The Google Drive integration is removed; original-PDF archival is now `po_documents` (above) on Supabase. |

## Applying

**With the Supabase CLI** (once, from the repo root):

```bash
supabase init                     # if there's no supabase/config.toml yet
supabase link --project-ref <ref> # from the project's dashboard URL
supabase db push                  # applies every migration not yet recorded
```

**Or straight with psql** (no CLI, no migration bookkeeping):

```bash
psql "$DATABASE_URL" -f supabase/migrations/20260828120000_admin_crud.sql
```

Every migration here is idempotent (`IF NOT EXISTS` / guarded `DO $$` blocks), so
re-running one is harmless.

## Relationship to `schema.sql`

`schema.sql` at the repo root stays the canonical full schema — the extraction
pipeline applies it on every publish. New DDL lands in **both** places: a dated
file here (for `supabase db push`) and the matching block in `schema.sql` (for the
pipeline). `backend/app/admin_schema.py` also self-applies the admin-CRUD DDL on
API startup, so a deploy that runs before the migration still boots.
