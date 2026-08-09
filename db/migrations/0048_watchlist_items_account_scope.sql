-- 0048: watchlist_items policy -> account scope (2026-08-09, multi-account)
--
-- 0047 rewrote 19 policies by matching the simple `auth.uid() = user_id`
-- form. watchlist_items does not use that form: it reaches the book
-- INDIRECTLY, through watchlists.watchlist_id -> watchlists.user_id. So
-- the sweep could not see it, and it was left comparing a book key to a
-- person's uid. Effect: a person's SECOND book's watchlist items become
-- invisible to them. Fails closed -- no data leak -- but silently wrong.
--
-- This is the only genuine leftover. strategy_scope_adjustments also
-- survived the sweep, but its predicate is `auth.uid() IS NOT NULL` --
-- not book-scoped at all, pre-dates this work, and is deliberately left
-- alone rather than changed inside an unrelated migration.

BEGIN;

DROP POLICY IF EXISTS watchlist_items_self_all ON public.watchlist_items;

CREATE POLICY watchlist_items_self_all ON public.watchlist_items
  FOR ALL
  USING (EXISTS (
    SELECT 1 FROM public.watchlists w
    WHERE w.id = watchlist_items.watchlist_id
      AND w.user_id IN (SELECT public.my_account_keys())))
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.watchlists w
    WHERE w.id = watchlist_items.watchlist_id
      AND w.user_id IN (SELECT public.my_account_keys())));

COMMIT;

-- Confirmation: no book-scoped policy should still compare to auth.uid().
SELECT tablename, policyname,
       coalesce(qual::text, with_check::text) AS predicate
FROM pg_policies
WHERE schemaname = 'public'
  AND coalesce(qual::text, with_check::text) ILIKE '%auth.uid()%'
  AND coalesce(qual::text, with_check::text) NOT ILIKE '%my_account_keys%'
  AND tablename NOT IN ('profiles','payment_instructions','broker_connections',
                        'broker_token_refresh_log','ethical_filter_settings',
                        'ethical_overrides','risk_profile_audit',
                        'kindrip_children','kindrip_holdings',
                        'kindrip_transactions','trading_accounts',
                        'strategy_scope_adjustments')
ORDER BY tablename;
