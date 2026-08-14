-- Postgres schema for the hosted PO dashboard (Neon).
-- Mirrors db.py's local SQLite schema; applied once via the sync script's
-- --init-schema flag or manually with psql.

CREATE TABLE IF NOT EXISTS purchase_orders (
    id                 SERIAL PRIMARY KEY,
    source_file        TEXT NOT NULL,
    file_hash          TEXT NOT NULL,
    extraction_method  TEXT,
    error              TEXT,
    po_number          TEXT,
    po_date            DATE,
    sent_date          TEXT,
    delivery_date      DATE,
    revision_number    TEXT,
    revision_label     TEXT,
    is_revision        BOOLEAN NOT NULL DEFAULT FALSE,
    version_label      TEXT,
    customer_name      TEXT,
    customer_id        TEXT,
    subtotal           NUMERIC,
    tax                NUMERIC,
    total              NUMERIC,
    notes              TEXT,
    math_check_failed  BOOLEAN NOT NULL DEFAULT FALSE,
    math_check_detail  TEXT,
    extracted_at       TIMESTAMPTZ NOT NULL,
    UNIQUE(source_file, file_hash)
);

CREATE TABLE IF NOT EXISTS line_items (
    id              SERIAL PRIMARY KEY,
    po_id           INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    product_raw     TEXT,
    sku             TEXT,
    quantity        NUMERIC,
    unit_price      NUMERIC,
    line_total      NUMERIC,
    product_name    TEXT,
    container_size  TEXT,
    is_sample       BOOLEAN NOT NULL DEFAULT FALSE,
    needs_review    BOOLEAN NOT NULL DEFAULT FALSE,
    math_mismatch   TEXT,
    revision_status TEXT,
    is_removed      BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_line_items_po_id ON line_items(po_id);
CREATE INDEX IF NOT EXISTS idx_po_po_number ON purchase_orders(po_number);
CREATE INDEX IF NOT EXISTS idx_po_po_date ON purchase_orders(po_date);
CREATE INDEX IF NOT EXISTS idx_po_customer_name ON purchase_orders(customer_name);
CREATE INDEX IF NOT EXISTS idx_line_items_product_name ON line_items(product_name);
