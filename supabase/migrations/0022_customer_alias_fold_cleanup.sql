-- Customer alias cleanup, round 2 -- after broadening the resolver (0022)
-- ===========================================================================
-- Follow-on to 0021. customer_alias.py's fallback match now also strips
-- punctuation/separators (not just whitespace runs), so several rows that
-- used to be genuinely necessary (the resolver's old case+whitespace-only
-- fallback couldn't unify them) are now true duplicates of another row
-- pointing at the same canonical -- safe to drop, exactly like TESTA
-- PRODUCE was in 0021.
--
-- Verified before writing this: none of the deleted rows are the sole
-- representative of their fold-group (each group keeps >=1 row), and no
-- fold-group spans two different canonicals anywhere in the table (checked
-- via `GROUP BY lower(regexp_replace(alias_name, '[^a-zA-Z0-9]', '', 'g'))`
-- against the live data before this migration was written).
--
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0022_customer_alias_fold_cleanup.sql

BEGIN;

-- "Skoufis Food Service" / "SKOUFIS FOODSERVICE" -- case + missing internal
-- space; both fold to "skoufisfoodservice" now. Keep the naturally-spaced one.
DELETE FROM customer_aliases WHERE alias_name = 'SKOUFIS FOODSERVICE';

-- "Anthony Marano Co (Sean McLaughlin)" / "... Co / Sean McLaughlin" / "...
-- Co. (Sean McLaughlin)" -- punctuation/separator noise only, all fold to
-- "anthonymaranocoseanmclaughlin". Keep the "Co. (...)" spelling.
DELETE FROM customer_aliases
WHERE alias_name IN ('Anthony Marano Co (Sean McLaughlin)', 'Anthony Marano Co / Sean McLaughlin');

-- "Sean McLaughlin (Anthony Marano Company)" / "Sean McLaughlin / Anthony
-- Marano Company" -- separator noise only, both fold to
-- "seanmclaughlinanthonymaranocompany". Keep the parenthetical spelling
-- (consistent with the row above).
DELETE FROM customer_aliases WHERE alias_name = 'Sean McLaughlin / Anthony Marano Company';

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   INSERT INTO customer_aliases (alias_name, canonical_name, source) VALUES
--     ('SKOUFIS FOODSERVICE', 'Skoufis Food Service', 'manual'),
--     ('Anthony Marano Co (Sean McLaughlin)', 'Anthony Marano Company', 'auto'),
--     ('Anthony Marano Co / Sean McLaughlin', 'Anthony Marano Company', 'auto'),
--     ('Sean McLaughlin / Anthony Marano Company', 'Anthony Marano Company', 'auto')
--   ON CONFLICT (alias_name) DO NOTHING;
