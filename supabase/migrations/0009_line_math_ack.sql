-- Line math-check acknowledgement (0009)
-- ======================================
-- A line whose printed arithmetic genuinely doesn't add up on the SOURCE document
-- (vendor rounding, an unmodelled discount line) can't be "fixed" by editing the
-- numbers without misrepresenting the order. Acknowledging it keeps line_items
-- .math_mismatch for the record but drops the line out of the Data Quality fix
-- queue (routers/quality.py) and the Reconcile / Overview counts.
--
-- Idempotent; also self-applied on API boot (backend/app/admin_schema.py).
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0009_line_math_ack.sql

BEGIN;

ALTER TABLE line_items ADD COLUMN IF NOT EXISTS math_ack        BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS math_ack_by     TEXT;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS math_ack_at     TIMESTAMPTZ;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS math_ack_reason TEXT;

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   ALTER TABLE line_items DROP COLUMN IF EXISTS math_ack, DROP COLUMN IF EXISTS math_ack_by,
--     DROP COLUMN IF EXISTS math_ack_at, DROP COLUMN IF EXISTS math_ack_reason;
