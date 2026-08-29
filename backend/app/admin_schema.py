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
CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders (status);

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
