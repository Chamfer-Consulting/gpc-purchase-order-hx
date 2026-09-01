-- Re-point stale-revision matches (0010)
-- =====================================
-- A confirmed po_invoice_links row can sit on an OLD revision of its PO number:
-- get_latest_pos() used to pick the canonical revision by sent_date/po_date, so a
-- re-extraction that happened to carry a sent_date beat a genuinely-newer revision
-- whose only timestamp is document_printed_at / source_received_at. Result: Order
-- Lifecycle read "requested" off the wrong (usually smaller) version — e.g. PO
-- 00583741, link on the qty-120 row while the real final order was qty 205.
--
-- This moves each confirmed link to the newest revision of its po_number, using
-- the same recency order the code now uses (qbo_matcher.po_recency):
--   document_printed_at  >  source_received_at  >  sent_date  >  po_date
--
-- One-off data fix. NOT self-applied by admin_schema (it's a data migration, not
-- DDL) — run once:
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0010_repoint_stale_revision_links.sql

BEGIN;

WITH po_rec AS (
  SELECT id, po_number,
    COALESCE(
      CASE WHEN document_printed_at ~* '^\s*\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[ap]\s*$'
           THEN to_timestamp(
                  regexp_replace(regexp_replace(btrim(document_printed_at), '\s*a\s*$', ' AM', 'i'),
                                 '\s*p\s*$', ' PM', 'i'),
                  'MM/DD/YY HH12:MI AM') END,
      CASE WHEN source_received_at ~ '^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}' THEN source_received_at::timestamp END,
      CASE WHEN sent_date ~ '^\d{4}-\d{2}-\d{2}$' THEN sent_date::timestamp END,
      po_date::timestamp,
      '1900-01-01'::timestamp
    ) AS recency
  FROM purchase_orders
  WHERE error IS NULL AND po_number IS NOT NULL
    AND COALESCE(status, 'active') = 'active'
),
target AS (  -- newest active revision per po_number
  SELECT DISTINCT ON (po_number) po_number, id AS target_id
  FROM po_rec
  ORDER BY po_number, recency DESC, id DESC
),
moves AS (
  SELECT l.po_id AS from_id, l.invoice_id, t.target_id
  FROM po_invoice_links l
  JOIN purchase_orders cur_po ON cur_po.id = l.po_id
  JOIN target t ON t.po_number = cur_po.po_number
  WHERE l.confirmed
    AND t.target_id <> l.po_id
    -- don't clobber a target that's already confirmed against a different invoice
    AND NOT EXISTS (
      SELECT 1 FROM po_invoice_links x
      WHERE x.po_id = t.target_id AND x.invoice_id <> l.invoice_id AND x.confirmed
    )
    -- no (target_id, invoice_id) row yet -> plain UPDATE won't hit the unique key
    AND NOT EXISTS (
      SELECT 1 FROM po_invoice_links x
      WHERE x.po_id = t.target_id AND x.invoice_id = l.invoice_id
    )
)
UPDATE po_invoice_links l
SET po_id = m.target_id
FROM moves m
WHERE l.po_id = m.from_id AND l.invoice_id = m.invoice_id AND l.confirmed;

COMMIT;

-- After this, run matching once (dashboard "Run matching" or run_qbo_sync.py) so
-- unconfirmed candidate rows are regenerated against the corrected canonical POs.
