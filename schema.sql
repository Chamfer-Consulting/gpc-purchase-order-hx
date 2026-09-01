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

-- Admin CRUD (po-dashboard-rebuild): lifecycle status + soft delete. Non-'active'
-- rows are hidden from reports and frozen from the extraction pipeline (they're
-- also marked edited = TRUE on any admin action, which the publish guard honours).
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
  -- active | draft | cancelled | withdrawn | voided | deleted
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS status_reason TEXT;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS status_at TIMESTAMPTZ;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS edited_by TEXT;
-- Optimistic-concurrency counter — bumped on every admin/edit mutation; a stale
-- expected value from the client is rejected as HTTP 409 (0006). NB: po_number is
-- intentionally NOT unique — every revision of a PO is its own active row and
-- qbo_matcher.get_latest_pos() dedupes by po_number at read time.
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders (status);

-- Authorization tiers for the admin surface (0006). No row => 'editor'.
CREATE TABLE IF NOT EXISTS app_users (
    email      TEXT PRIMARY KEY,
    role       TEXT NOT NULL DEFAULT 'editor' CHECK (role IN ('viewer','editor','admin')),
    note       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE line_items ADD COLUMN IF NOT EXISTS voided BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS void_reason TEXT;

-- Line math-check acknowledgement (0009): keep math_mismatch on record but drop
-- the line from the Data Quality fix queue when the arithmetic is genuinely off
-- on the source document (vendor rounding / unmodelled discount).
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS math_ack        BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS math_ack_by     TEXT;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS math_ack_at     TIMESTAMPTZ;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS math_ack_reason TEXT;

-- Who changed what, for the admin CRUD surface. before/after are the row (or the
-- touched slice) as JSON. Written by backend/app/services/audit.py.
CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    actor      TEXT,
    action     TEXT NOT NULL,   -- create | update | status | delete | restore | link | unlink | line_void | customer | revision
    entity     TEXT NOT NULL,   -- purchase_order | line_item | po_invoice_link
    entity_id  TEXT,
    before     JSONB,
    after      JSONB,
    at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log (entity, entity_id, at DESC);
-- (po_documents is defined further down — it FKs qbo_invoices, which is created below.)

-- Dashboard-side manual edits are permanent: once a PO is edited, sync_dashboard.py
-- must never overwrite its header or line items again (see sync_dashboard.py's
-- ON CONFLICT ... WHERE clause).
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS edited BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ;

-- (Original-PDF archival moved to Supabase: the po_documents table holds the
-- captured PO/invoice PDF bytes. The former Google Drive link columns
-- drive_file_id / drive_synced_at were dropped — see supabase/migrations/.)

-- Unlabeled date+time page-header stamp (e.g. Get Fresh's top-right print timestamp),
-- captured as the finest-grained signal for ordering same-po_number revisions/reprints
-- when no explicit revision confirmation exists — see extract_pos.py's _sort_key().
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS document_printed_at TEXT;

-- The Gmail message's own timestamp, for POs/revisions ingested straight from email
-- (attachment or body text) rather than scanned from a local PDF — the cloud-ingestion
-- equivalent of document_printed_at's "when this exact copy was produced" signal, used
-- as the next fallback in _sort_key() when a document has no printed stamp of its own.
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS source_received_at TEXT;

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

-- Heartbeat for the scheduled headless sync (run_qbo_sync.py / .github/workflows/
-- qbo_sync.yml). auto_synced_at is set on every successful run; auto_sync_error
-- holds the last failure message (cleared on the next success) so the dashboard
-- can show "auto-sync failing since ..." and prompt a reconnect.
ALTER TABLE qbo_connection ADD COLUMN IF NOT EXISTS auto_synced_at TIMESTAMPTZ;
ALTER TABLE qbo_connection ADD COLUMN IF NOT EXISTS auto_sync_error TEXT;

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
    match_method  TEXT NOT NULL,       -- po_number | po_number_items | po_number_ambiguous | po_number_review | fuzzy | manual
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

-- Captured source documents for a PO: the emailed PO PDF pulled from Gmail, and the
-- rendered invoice PDF pulled from QuickBooks (its Print/Download output). Bytes are
-- stored inline for now (PDFs are small; ~100 KB typical); storage_path is reserved
-- for a later move to Supabase Storage, at which point content goes NULL.
-- Written by backend/app/services/po_docs.py. Defined here (not up in the Admin-CRUD
-- block) because invoice_id FKs qbo_invoices.
CREATE TABLE IF NOT EXISTS po_documents (
    id           BIGSERIAL PRIMARY KEY,
    po_id        INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    invoice_id   INTEGER REFERENCES qbo_invoices(id) ON DELETE SET NULL,  -- for kind = 'invoice_pdf'
    kind         TEXT NOT NULL,          -- po_pdf | invoice_pdf | email_pdf | other
    source       TEXT NOT NULL,          -- gmail | qbo | upload
    filename     TEXT NOT NULL,
    mime_type    TEXT NOT NULL DEFAULT 'application/pdf',
    byte_size    INTEGER NOT NULL,
    content_hash TEXT NOT NULL,          -- sha256 hex, for dedupe
    content      BYTEA,                  -- inline bytes; NULL once offloaded to storage_path
    storage_path TEXT,
    captured_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    captured_by  TEXT,
    UNIQUE (po_id, kind, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_po_documents_po_id ON po_documents (po_id);

-- One-time cleanup for links created before run_matching() learned to
-- (a) reject the losing siblings of a line-item-disambiguated auto-match, and
-- (b) tag an unresolved same-PO-number tie as 'po_number_ambiguous' rather than
--     'po_number' (which confidence_label() reads as "Certain" and drops in the
--     Quick-confirm queue). Both are idempotent — safe to re-run every apply.
UPDATE po_invoice_links l SET rejected = TRUE
WHERE l.confirmed = FALSE AND l.rejected = FALSE
  AND EXISTS (
    SELECT 1 FROM po_invoice_links w
    WHERE w.po_id = l.po_id AND w.confirmed = TRUE AND w.match_method = 'po_number_items'
  );

UPDATE po_invoice_links l SET match_method = 'po_number_ambiguous'
WHERE l.match_method = 'po_number' AND l.confirmed = FALSE AND l.rejected = FALSE
  AND (
    SELECT COUNT(*) FROM po_invoice_links s
    WHERE s.po_id = l.po_id AND s.match_method = 'po_number'
      AND s.confirmed = FALSE AND s.rejected = FALSE
  ) > 1;

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

-- Same idea for customers (keyed on the invoice customer_name the analytics
-- context groups by). Excluded from every analytics page (0008).
CREATE TABLE IF NOT EXISTS hidden_customers (
    customer_name TEXT PRIMARY KEY,
    hidden_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Gmail OAuth connection for the cloud extraction pipeline (run_cloud_extraction.py,
-- run manually or via a scheduled GitHub Action) — same shape as qbo_connection above,
-- minus a realm_id since Gmail has no equivalent concept. last_synced_at is the
-- incremental-scan cursor; NULL means "never synced, or forced full backlog scan".
CREATE TABLE IF NOT EXISTS gmail_connection (
    id                       SERIAL PRIMARY KEY,
    email_address            TEXT NOT NULL,
    access_token             TEXT NOT NULL,
    refresh_token            TEXT NOT NULL,
    access_token_expires_at  TIMESTAMPTZ NOT NULL,
    connected_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at           TIMESTAMPTZ
);

-- ===== CLOUD-THREAD-SCHEMA (start) =====
-- Everything between these markers is also applied on its own, up front, by
-- postgres_store.ensure_cloud_schema() (the cloud run's thread loop touches these
-- before the full-schema apply at publish time). That function slices this exact
-- region out of this file at runtime — do not copy it elsewhere; edit it here only.

-- Links a purchase_orders row back to the Gmail thread it came from — set for
-- BOTH cloud paths (the text-only thread extraction, where source_file is already
-- "gmail-thread:<id>", and each PDF attachment, where source_file is just the
-- filename and this is the only trail back to the email). NULL for local-PDF rows.
-- Join to gmail_thread_meta on this to show who sent it / when / attachments / a
-- link, especially for rows that errored out ("not a purchase order").
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS gmail_thread_id TEXT;
-- Existing text-thread rows (source_file = "gmail-thread:<id>") are backfilled
-- once by postgres_store.ensure_cloud_schema() at the start of a cloud run;
-- attachment rows (bare filename) get linked by link_thread_rows() on a
-- --full-backlog run. Kept out of this file so it doesn't re-scan on every
-- publish-time apply_schema().

-- Display metadata for a Gmail thread the cloud pipeline has processed — rewritten
-- every run the thread is seen (cheap: built from the thread fetch that
-- _process_thread already does), independent of whether extraction ran, so it
-- backfills naturally (a one-off `--full-backlog` run populates every existing
-- row). Everything here is for humans investigating an extraction result in the
-- dashboard, not used by extraction itself. url is a deep link into the connected
-- mailbox; from_addrs is the customer-side sender(s), comma-joined; attachment_names
-- is comma-joined filenames or NULL.
CREATE TABLE IF NOT EXISTS gmail_thread_meta (
    thread_id         TEXT PRIMARY KEY,
    subject           TEXT,
    from_addrs        TEXT,
    first_message_at  TIMESTAMPTZ,
    last_message_at   TIMESTAMPTZ,
    message_count     INTEGER,
    attachment_names  TEXT,
    url               TEXT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-thread extraction memory for the cloud pipeline's text-only (no-PDF) path.
-- purchase_orders keys on (source_file, file_hash), and a text thread's file_hash
-- is a hash of the WHOLE thread's combined text — so a thread gaining even one
-- chit-chat reply produces a brand-new hash and a full, whole-thread re-extraction
-- next run. This table lets run_cloud_extraction skip that: a thread previously
-- classified NOT a purchase order that has only grown by more non-order messages
-- gets its new messages alone cheaply re-checked, and its state row bumped, with
-- no full re-extraction. last_file_hash is the combined-text hash as of the last
-- time this thread was fully processed; message_count is how many messages that
-- was based on; was_po records whether that extraction produced a real order.
CREATE TABLE IF NOT EXISTS gmail_thread_state (
    thread_id       TEXT PRIMARY KEY,
    message_count   INTEGER NOT NULL,
    last_file_hash  TEXT NOT NULL,
    was_po          BOOLEAN NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Human review decisions that OVERRIDE and TRAIN the PO extractor. One row per
-- reviewed target — a Gmail thread ('thread', target_key = thread_id) or a source
-- file ('file', target_key = source_file). Three consumers:
--   1. The cloud pipeline consults it before every model call: verdict 'not_po'
--      skips extraction entirely; 'is_po' with a `corrected` payload is published
--      verbatim and protected like purchase_orders.edited; revision_of / standalone
--      force or forbid the revision grouping in annotate_revisions().
--   2. build_fewshot_block() turns the most instructive rows into few-shot
--      examples injected back into the extraction + YES/NO gate prompts.
--   3. eval_extraction.py replays every row's content_snapshot through the current
--      prompt/model and scores it — CI fails on a regression.
-- content_hash pins a decision to the exact content it was made on; if the thread
-- later changes, the decision is "stale" (advisory only, re-surfaced for review).
-- content_snapshot is the thread text / PDF text as reviewed (truncated), so the
-- eval can replay without re-fetching from Gmail.
CREATE TABLE IF NOT EXISTS extraction_reviews (
    id               SERIAL PRIMARY KEY,
    target_kind      TEXT NOT NULL,                     -- 'thread' | 'file'
    target_key       TEXT NOT NULL,                     -- gmail thread_id, or source_file
    content_hash     TEXT,                              -- content hash when reviewed; NULL = applies regardless
    content_snapshot TEXT,                              -- thread/PDF text as reviewed (truncated) — for eval replay
    verdict          TEXT NOT NULL,                     -- 'is_po' | 'not_po' | 'needs_fix'
    revision_of      TEXT,                              -- po_number / 'gmail-thread:<id>' this revises
    standalone       BOOLEAN NOT NULL DEFAULT FALSE,    -- TRUE = never group as a revision
    corrected        JSONB,                             -- reviewer's authoritative field values
    fewshot          BOOLEAN NOT NULL DEFAULT TRUE,     -- include in the few-shot block
    reviewer         TEXT,
    note             TEXT,
    decided_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_kind, target_key)
);
CREATE INDEX IF NOT EXISTS idx_extraction_reviews_verdict ON extraction_reviews (verdict);

-- The extracted text the pipeline last saw for a target (thread combined-text, or
-- a PDF attachment's extracted text), truncated. Written by run_cloud_extraction
-- on every extraction. Two readers: the dashboard review queue shows it so a
-- person can judge a borderline call without opening Gmail, and it's copied into
-- an extraction_reviews row when a decision is made so eval_extraction.py can
-- replay that exact content later.
CREATE TABLE IF NOT EXISTS extraction_snapshots (
    target_kind  TEXT NOT NULL,          -- 'thread' | 'file'
    target_key   TEXT NOT NULL,
    content      TEXT NOT NULL,
    content_hash TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_kind, target_key)
);
-- ===== CLOUD-THREAD-SCHEMA (end) =====

-- Named, reusable dashboard configurations (redesign Phase F). `kind` scopes a
-- view to a page (e.g. "explore"); `config` is that page's control state. Created
-- lazily by dashboard/data.py:save_view() too, so it exists even before a sync.
CREATE TABLE IF NOT EXISTS dashboard_saved_views (
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    config      JSONB NOT NULL,
    owner       TEXT NOT NULL DEFAULT '',   -- Supabase email; '' = legacy shared (0007)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner, kind, name)
);
