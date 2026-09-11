-- Product Yields (0014)
-- =====================
-- A second domain alongside PO/QBO sales: field employees log harvested
-- weight/counts per crop on a shared tablet, tracked long-term.
--
-- yield_products is a standalone crop/variety catalog, decoupled from sales
-- SKU names (line_items.product_name / qbo_invoice_items.product_name — there
-- is no normalized products table on that side, see
-- backend/app/services/settings.py:list_products()).
--
-- yield_product_sales_links maps yield products to sales SKU names as a
-- genuine many-to-many join, NOT the customer_aliases shape (alias PK -> one
-- canonical). That's strict N:1, correct for "many spellings, one company" —
-- wrong here, since a yield product can feed several sold SKUs and a blend
-- SKU pulls from several yield products. A composite-UNIQUE join table
-- supports 1:1, N:1 (blend), and 1:N without forcing a direction.
--
-- yield_entries has no daily-uniqueness constraint — multiple entries per
-- product per day are expected (separate packing runs). harvested_by is the
-- individual worker (free text, autocompleted client-side); submitted_by is
-- the signed-in kiosk account's email — the kiosk login is shared across
-- workers on a tablet, not per-employee, so it's an audit trail, not the
-- worker's identity.
--
-- Also extends app_users.role with a new 'field' role (kiosk-only, ranked
-- below 'viewer' in backend/app/auth.py's _ROLE_RANK) — never a default,
-- only ever an explicit grant via Settings -> Team.
--
-- Table DDL is also in backend/app/admin_schema.py (runs on API boot).
--
-- RLS is auto-enabled by the 0005 event trigger (deny-all, backend-only).
--
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0014_yields.sql

BEGIN;

ALTER TABLE app_users DROP CONSTRAINT IF EXISTS app_users_role_check;
ALTER TABLE app_users ADD CONSTRAINT app_users_role_check
    CHECK (role IN ('field', 'viewer', 'editor', 'admin'));

CREATE TABLE IF NOT EXISTS yield_products (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_yield_products_active ON yield_products (active);

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
    storage_bin            TEXT,
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

CREATE TABLE IF NOT EXISTS yield_notes (
    id                BIGSERIAL PRIMARY KEY,
    yield_product_id  INTEGER REFERENCES yield_products(id) ON DELETE SET NULL,
    note_date         DATE NOT NULL DEFAULT CURRENT_DATE,
    note              TEXT NOT NULL,
    submitted_by      TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_yield_notes_product ON yield_notes (yield_product_id, note_date);

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   DROP TABLE IF EXISTS yield_notes;
--   DROP TABLE IF EXISTS yield_entries;
--   DROP TABLE IF EXISTS yield_product_sales_links;
--   DROP TABLE IF EXISTS yield_products;
--   ALTER TABLE app_users DROP CONSTRAINT IF EXISTS app_users_role_check;
--   ALTER TABLE app_users ADD CONSTRAINT app_users_role_check
--       CHECK (role IN ('viewer', 'editor', 'admin'));
