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
    role       TEXT NOT NULL DEFAULT 'editor' CHECK (role IN ('viewer','editor','admin')),
    note       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO app_users (email, role, note) VALUES ('jcaternolo@gmail.com', 'admin', 'seed: repo owner')
ON CONFLICT (email) DO NOTHING;

ALTER TABLE line_items ADD COLUMN IF NOT EXISTS voided BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS void_reason TEXT;

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
