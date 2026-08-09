-- DIAGNOSTIC 2 (read-only, changes nothing).
--
-- Repointing the user_id foreign keys from auth.users to
-- trading_accounts costs no application code -- but any RLS policy of the
-- form `auth.uid() = user_id` stops matching for a person's SECOND book,
-- because their auth uid is not that book's key. Those policies become:
--     user_id IN (SELECT account_key FROM trading_accounts
--                 WHERE owner_id = auth.uid())
--
-- This counts and shows them, so the rewrite is sized from fact.

-- A. how many policies, and how many mention auth.uid() on user_id
SELECT
  count(*)                                                      AS total_policies,
  count(*) FILTER (WHERE qual::text  ILIKE '%auth.uid()%'
                      OR with_check::text ILIKE '%auth.uid()%') AS uses_auth_uid,
  count(DISTINCT tablename)                                     AS tables_covered
FROM pg_policies
WHERE schemaname = 'public';

-- B. the ones that will actually need rewriting, by table
SELECT tablename, policyname, cmd,
       coalesce(qual::text, with_check::text) AS predicate
FROM pg_policies
WHERE schemaname = 'public'
  AND (qual::text ILIKE '%auth.uid()%' OR with_check::text ILIKE '%auth.uid()%')
ORDER BY tablename, policyname;
