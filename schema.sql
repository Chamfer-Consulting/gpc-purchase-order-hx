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

ALTER TABLE line_items ADD COLUMN IF NOT EXISTS changes TEXT;

-- Some vendors (e.g. Get Fresh) print a separate per-line surcharge (freight/adtl.
-- cost) on top of unit_price × quantity, folded into the printed line_total —
-- captured separately so math_check.py can validate qty×price+additional_cost=total
-- instead of flagging a false mismatch.
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS additional_cost NUMERIC;

-- Flags a line item whose price deviates from its (customer, product, size) reference
-- price by more than price_check.PRICE_TOLERANCE_PCT.
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS price_anomaly TEXT;

-- Expected/current price per (customer, product, size) — basis for the price_anomaly
-- flag above. Local SQLite (extract_pos.py) is the auto-refreshed source of truth;
-- edited = TRUE marks a manual override made in the dashboard's Reference Prices tab,
-- which the next sync must never clobber (same guard shape as purchase_orders.edited).
CREATE TABLE IF NOT EXISTS reference_prices (
    id              SERIAL PRIMARY KEY,
    customer_name   TEXT NOT NULL,
    product_name    TEXT NOT NULL,
    container_size  TEXT NOT NULL,
    price           NUMERIC NOT NULL,
    source          TEXT NOT NULL DEFAULT 'auto',
    edited          BOOLEAN NOT NULL DEFAULT FALSE,
    edited_at       TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(customer_name, product_name, container_size)
);

-- Dashboard-side manual edits are permanent: once a PO is edited, sync_dashboard.py
-- must never overwrite its header or line items again (see sync_dashboard.py's
-- ON CONFLICT ... WHERE clause).
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS edited BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ;

-- Link to the original PDF's copy in the Google Shared Drive it was archived to on
-- receipt — drive_file_id IS NULL is the incremental-sync filter (no time cursor needed,
-- a once-found file never needs re-searching).
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS drive_file_id TEXT;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS drive_synced_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_line_items_po_id ON line_items(po_id);
CREATE INDEX IF NOT EXISTS idx_po_po_number ON purchase_orders(po_number);
CREATE INDEX IF NOT EXISTS idx_po_po_date ON purchase_orders(po_date);
CREATE INDEX IF NOT EXISTS idx_po_customer_name ON purchase_orders(customer_name);
CREATE INDEX IF NOT EXISTS idx_line_items_product_name ON line_items(product_name);

-- QuickBooks Online integration (Phase 1: connect + pull raw invoice data).
CREATE TABLE IF NOT EXISTS qbo_connection (
    id                       SERIAL PRIMARY KEY,
    realm_id                 TEXT NOT NULL,
    access_token             TEXT NOT NULL,
    refresh_token            TEXT NOT NULL,
    access_token_expires_at  TIMESTAMPTZ NOT NULL,
    refresh_token_expires_at TIMESTAMPTZ NOT NULL,
    connected_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sync cursor for incremental invoice pulls — NULL means "never synced, pull everything".
ALTER TABLE qbo_connection ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS qbo_invoices (
    id             SERIAL PRIMARY KEY,
    qbo_invoice_id TEXT NOT NULL UNIQUE,
    doc_number     TEXT,
    customer_name  TEXT,
    txn_date       DATE,
    ship_date      DATE,
    due_date       DATE,
    total_amt      NUMERIC,
    private_note   TEXT,
    raw_json       JSONB NOT NULL,
    synced_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- QuickBooks Phase 2: matching PO requests to invoices ("what shipped").
CREATE TABLE IF NOT EXISTS qbo_invoice_items (
    id             SERIAL PRIMARY KEY,
    invoice_id     INTEGER NOT NULL REFERENCES qbo_invoices(id) ON DELETE CASCADE,
    item_raw       TEXT,
    description    TEXT,
    product_name   TEXT,
    container_size TEXT,
    is_sample      BOOLEAN NOT NULL DEFAULT FALSE,
    quantity       NUMERIC,
    unit_price     NUMERIC,
    line_total     NUMERIC
);

-- QuickBooks' own Item list — the product master catalog. Matched to invoice line
-- items by qbo_item_id (QBO's stable Item ID), not fragile name-parsing; see
-- product_catalog.classify_qbo_item(). Always a full re-pull (small table).
CREATE TABLE IF NOT EXISTS qbo_items (
    id             SERIAL PRIMARY KEY,
    qbo_item_id    TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    item_type      TEXT,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    unit_price     NUMERIC,
    sku            TEXT,
    category       TEXT NOT NULL,  -- product | sample | delivery | donation | service | other
    product_name   TEXT,
    container_size TEXT,
    synced_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE qbo_invoice_items ADD COLUMN IF NOT EXISTS qbo_item_id TEXT;
ALTER TABLE qbo_invoice_items ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'product';

CREATE TABLE IF NOT EXISTS po_invoice_links (
    id            SERIAL PRIMARY KEY,
    po_id         INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    invoice_id    INTEGER NOT NULL REFERENCES qbo_invoices(id) ON DELETE CASCADE,
    match_method  TEXT NOT NULL,       -- 'po_number' | 'fuzzy' | 'manual'
    match_score   NUMERIC,             -- for ranking/display of fuzzy candidates
    confirmed     BOOLEAN NOT NULL DEFAULT FALSE,
    rejected      BOOLEAN NOT NULL DEFAULT FALSE,
    linked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(po_id, invoice_id)
);

CREATE INDEX IF NOT EXISTS idx_qbo_invoice_items_invoice_id ON qbo_invoice_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_qbo_invoice_items_product_name ON qbo_invoice_items(product_name);
CREATE INDEX IF NOT EXISTS idx_po_invoice_links_po_id ON po_invoice_links(po_id);
CREATE INDEX IF NOT EXISTS idx_po_invoice_links_invoice_id ON po_invoice_links(invoice_id);

-- Dashboard-side product visibility override — a product listed here is excluded from
-- every reporting surface (charts, tables, filters, exports, picker dropdowns) app-wide,
-- without touching the underlying PO/invoice line-item data. Toggled from the Products
-- report page's "Manage products" section (dashboard/views/reports_products.py); the
-- Edit PO page and the QuickBooks Invoice Explorer/Item Catalog pages intentionally
-- ignore this table, since those are data-correction/inspection tools, not reports.
CREATE TABLE IF NOT EXISTS hidden_products (
    product_name TEXT PRIMARY KEY,
    hidden_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
