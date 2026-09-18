-- Customer alias audit fix + cleanup (0021)
-- ===========================================================================
-- User-reported: Settings -> Customers showed multiple "spelling" badges
-- under some companies that looked identical. Audited by querying the live
-- data (not just reading the resolver code) — see customer_alias.py for the
-- resolver itself (canonical() / _ci_index: exact match, then a
-- case+whitespace-insensitive fallback; punctuation is NOT normalized).
--
-- Two distinct things came out of that:
--
-- 1. A real bug, not just clutter: "Testa Produce, Inc." (with a comma) had
--    no row in customer_aliases at all, and differs from the canonical
--    "Testa Produce Inc." (no comma) by punctuation only -- which the
--    resolver's case/whitespace-only fallback can't fold. 4 real 2022 POs
--    were sitting under this unresolved spelling, split off from the rest
--    of that customer's history on any page keyed by canonical name.
--
-- 2. Genuine redundancy, safe to remove: "TESTA PRODUCE" (all caps) differs
--    from the already-mapped "Testa Produce" by case ONLY -- identical
--    whitespace structure -- so the resolver's _ci_index already treats any
--    casing of "Testa Produce" as this same customer once ONE row for it
--    exists. The uppercase row adds zero resolution coverage and was pure
--    visual clutter.
--
-- Other near-identical-looking badges found in the same audit (e.g.
-- "Skoufis Food Service" vs "SKOUFIS FOODSERVICE", several "Anthony Marano
-- Co ... (Sean McLaughlin)" punctuation variants) are each genuinely
-- necessary rows, not redundant -- they differ by more than case/whitespace
-- (a missing internal space, different punctuation/separators), so the
-- resolver's narrow case+whitespace-only fallback does NOT already cover
-- them. Deliberately left alone here; folding punctuation more aggressively
-- is a real resolver-behavior change (touches QBO invoice matching too),
-- not a data cleanup -- raise separately if still wanted after seeing this.
--
-- backend/app/services/settings.py's set_customer_alias() now also guards
-- against recreating case/whitespace-only duplicates like TESTA PRODUCE
-- going forward.
--
--   psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/0021_customer_alias_cleanup.sql

BEGIN;

INSERT INTO customer_aliases (alias_name, canonical_name, source)
VALUES ('Testa Produce, Inc.', 'Testa Produce Inc.', 'manual')
ON CONFLICT (alias_name) DO NOTHING;

DELETE FROM customer_aliases WHERE alias_name = 'TESTA PRODUCE';

COMMIT;

-- Rollback (manual) ----------------------------------------------------
--   DELETE FROM customer_aliases WHERE alias_name = 'Testa Produce, Inc.';
--   INSERT INTO customer_aliases (alias_name, canonical_name, source)
--       VALUES ('TESTA PRODUCE', 'Testa Produce Inc.', 'auto')
--       ON CONFLICT (alias_name) DO NOTHING;
