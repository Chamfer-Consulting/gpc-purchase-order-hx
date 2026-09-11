"""Idempotent DDL for the admin-CRUD surface (status / soft-delete / voided lines /
audit_log). The canonical copy lives in schema.sql, but the API never runs
schema.sql — the extraction pipeline does — so until this branch merges the
deployed backend may hit a database that only has main's columns. Run once on
startup; every statement is IF NOT EXISTS, so it's a no-op on an up-to-date DB."""

import logging

log = logging.getLogger("admin-schema")

_DDL = """
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS status_reason TEXT;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS status_at TIMESTAMPTZ;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS edited_by TEXT;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders (status);

CREATE TABLE IF NOT EXISTS app_users (
    email      TEXT PRIMARY KEY,
    role       TEXT NOT NULL DEFAULT 'editor' CHECK (role IN ('field','viewer','editor','admin')),
    note       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO app_users (email, role, note) VALUES ('jcaternolo@gmail.com', 'admin', 'seed: repo owner')
ON CONFLICT (email) DO NOTHING;
-- 'field' role (0014) added after this table already existed in deployed DBs —
-- CREATE TABLE IF NOT EXISTS above is a no-op there, so fix the constraint directly.
ALTER TABLE app_users DROP CONSTRAINT IF EXISTS app_users_role_check;
ALTER TABLE app_users ADD CONSTRAINT app_users_role_check
    CHECK (role IN ('field','viewer','editor','admin'));

ALTER TABLE line_items ADD COLUMN IF NOT EXISTS voided BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS void_reason TEXT;

-- Line math-check acknowledgement (0009) — keep the mismatch on record but drop it
-- from the Data Quality fix queue (genuine vendor-side discrepancy).
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS math_ack BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS math_ack_by TEXT;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS math_ack_at TIMESTAMPTZ;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS math_ack_reason TEXT;

CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    actor      TEXT,
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  TEXT,
    before     JSONB,
    after      JSONB,
    at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log (entity, entity_id, at DESC);

CREATE TABLE IF NOT EXISTS po_documents (
    id           BIGSERIAL PRIMARY KEY,
    po_id        INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    invoice_id   INTEGER REFERENCES qbo_invoices(id) ON DELETE SET NULL,
    kind         TEXT NOT NULL,
    source       TEXT NOT NULL,
    filename     TEXT NOT NULL,
    mime_type    TEXT NOT NULL DEFAULT 'application/pdf',
    byte_size    INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    content      BYTEA,
    storage_path TEXT,
    captured_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    captured_by  TEXT,
    UNIQUE (po_id, kind, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_po_documents_po_id ON po_documents (po_id);

-- Saved views are per-user (0007). Legacy name-PK rows migrate to owner = ''
-- (shared, read-only). New rows are keyed (owner, kind, name).
CREATE TABLE IF NOT EXISTS dashboard_saved_views (
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    config     JSONB NOT NULL,
    owner      TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE dashboard_saved_views ADD COLUMN IF NOT EXISTS owner TEXT NOT NULL DEFAULT '';
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'dashboard_saved_views_pkey') THEN
        ALTER TABLE dashboard_saved_views DROP CONSTRAINT dashboard_saved_views_pkey;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_saved_views_owner_kind_name') THEN
        ALTER TABLE dashboard_saved_views
            ADD CONSTRAINT uq_saved_views_owner_kind_name UNIQUE (owner, kind, name);
    END IF;
END $$;

-- Customer visibility — the customer analogue of hidden_products (0008).
CREATE TABLE IF NOT EXISTS hidden_customers (
    customer_name TEXT PRIMARY KEY,
    hidden_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- QBO invoice status (materialised from raw_json at sync) + invoice visibility
-- list — the Data Quality "unsent / auto-generated invoice" review (migration 0012).
-- qbo_invoices is created by schema.sql (the pipeline); skip quietly if it's not
-- here yet on a bare DB.
DO $$
BEGIN
    ALTER TABLE qbo_invoices ADD COLUMN IF NOT EXISTS email_status TEXT;
    ALTER TABLE qbo_invoices ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ;
    ALTER TABLE qbo_invoices ADD COLUMN IF NOT EXISTS balance      NUMERIC;
    ALTER TABLE qbo_invoices ADD COLUMN IF NOT EXISTS recur_ref    TEXT;
EXCEPTION WHEN undefined_table THEN NULL;
END $$;
CREATE TABLE IF NOT EXISTS hidden_invoices (
    qbo_invoice_id TEXT PRIMARY KEY,
    reason         TEXT,
    hidden_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Customer aliasing (0013) — one canonical company name per customer, no matter
-- which buyer / spelling a PO or invoice carried. Seed lives in the migration
-- file (idempotent), not here — this just guarantees the table exists.
CREATE TABLE IF NOT EXISTS customer_aliases (
    alias_name     TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    source         TEXT NOT NULL DEFAULT 'auto' CHECK (source IN ('auto', 'manual')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_customer_aliases_canonical ON customer_aliases (canonical_name);

-- Product Yields (0014) — harvest logging, a separate domain from PO/QBO sales.
-- See supabase/migrations/0014_yields.sql for the full rationale.
CREATE TABLE IF NOT EXISTS yield_products (
    id               SERIAL PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    notes            TEXT,
    lot_code_prefix  TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_yield_products_active ON yield_products (active);
-- lot_code_prefix (0017) — the CREATE TABLE above is a no-op on an
-- already-existing table, so fix it directly too.
ALTER TABLE yield_products ADD COLUMN IF NOT EXISTS lot_code_prefix TEXT;

CREATE TABLE IF NOT EXISTS yield_product_sales_links (
    id                 SERIAL PRIMARY KEY,
    yield_product_id   INTEGER NOT NULL REFERENCES yield_products(id) ON DELETE CASCADE,
    sales_product_name TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (yield_product_id, sales_product_name)
);
CREATE INDEX IF NOT EXISTS idx_yield_links_sales_name ON yield_product_sales_links (sales_product_name);

CREATE TABLE IF NOT EXISTS yield_entries (
    id                     BIGSERIAL PRIMARY KEY,
    yield_product_id       INTEGER NOT NULL REFERENCES yield_products(id) ON DELETE RESTRICT,
    harvest_date           DATE NOT NULL,
    weight                 NUMERIC(10,2) NOT NULL CHECK (weight > 0),
    unit                   TEXT NOT NULL DEFAULT 'oz' CHECK (unit IN ('oz', 'lb', 'g')),
    tray_count             INTEGER NOT NULL DEFAULT 0 CHECK (tray_count >= 0),
    discarded_tray_count   INTEGER NOT NULL DEFAULT 0 CHECK (discarded_tray_count >= 0),
    lot_code               TEXT,
    harvested_by           TEXT NOT NULL,
    submitted_by           TEXT NOT NULL,
    notes                  TEXT,
    voided                 BOOLEAN NOT NULL DEFAULT FALSE,
    void_reason            TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_yield_entries_date ON yield_entries (harvest_date);
CREATE INDEX IF NOT EXISTS idx_yield_entries_product_date ON yield_entries (yield_product_id, harvest_date);
-- storage_bin (0016) — dropped, turned out not to be needed. The CREATE TABLE
-- above is a no-op on an already-existing table, so fix it directly too.
ALTER TABLE yield_entries DROP COLUMN IF EXISTS storage_bin;

CREATE TABLE IF NOT EXISTS yield_notes (
    id                BIGSERIAL PRIMARY KEY,
    yield_product_id  INTEGER REFERENCES yield_products(id) ON DELETE SET NULL,
    note_date         DATE NOT NULL DEFAULT CURRENT_DATE,
    note              TEXT NOT NULL,
    submitted_by      TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_yield_notes_product ON yield_notes (yield_product_id, note_date);

-- Yield employees (0015) — a roster so the kiosk's "harvested by" field is a
-- tap-to-pick Select. Free TEXT on yield_entries stays unchanged (no FK).
CREATE TABLE IF NOT EXISTS yield_employees (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_yield_employees_active ON yield_employees (active);
INSERT INTO yield_employees (name)
SELECT DISTINCT btrim(harvested_by) FROM yield_entries
WHERE harvested_by IS NOT NULL AND btrim(harvested_by) <> ''
ON CONFLICT (name) DO NOTHING;
"""


def ensure_admin_schema() -> None:
    from .reused_db import reused_conn

    try:
        with reused_conn() as conn, conn.cursor() as cur:
            cur.execute(_DDL)
            conn.commit()
        log.info("admin schema ensured")
    except Exception as exc:  # non-fatal: a read-only DB user, or DB down at boot
        log.warning("could not ensure admin schema: %s", exc)
