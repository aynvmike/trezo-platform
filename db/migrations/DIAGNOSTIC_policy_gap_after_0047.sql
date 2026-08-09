-- DIAGNOSTIC (read-only) -- run after 0047.
-- 0047 rewrote 19 policies; the estimate was ~25. This finds the rest.
-- A BOOK-table policy still written as `auth.uid() = user_id` no longer
-- matches a person's SECOND book, so their own data goes invisible. That
-- fails CLOSED (no leak) but it is still broken, and silent.

-- A. book tables whose FK now points at trading_accounts, but whose
--    policy still compares against auth.uid() directly. These are the gap.
SELECT p.tablename, p.policyname, p.cmd,
       coalesce(p.qual::text, p.with_check::text) AS predicate
FROM pg_policies p
WHERE p.schemaname = 'public'
  AND coalesce(p.qual::text, p.with_check::text) ILIKE '%auth.uid()%'
  AND coalesce(p.qual::text, p.with_check::text) NOT ILIKE '%my_account_keys%'
  AND p.tablename IN (
      SELECT con.conrelid::regclass::text
      FROM pg_constraint con
      WHERE con.contype='f'
        AND con.confrelid='public.trading_accounts'::regclass)
ORDER BY p.tablename, p.policyname;

-- B. indirect policies -- they reach a book through another table, so the
--    simple-form filter never saw them. watchlist_items is the known one.
SELECT tablename, policyname, cmd,
       coalesce(qual::text, with_check::text) AS predicate
FROM pg_policies
WHERE schemaname='public'
  AND coalesce(qual::text, with_check::text) ILIKE '%auth.uid()%'
  AND coalesce(qual::text, with_check::text) NOT ILIKE '%my_account_keys%'
  AND coalesce(qual::text, with_check::text) ILIKE '%SELECT%'
  AND tablename NOT IN ('profiles','payment_instructions','broker_connections',
                        'broker_token_refresh_log','ethical_filter_settings',
                        'ethical_overrides','risk_profile_audit',
                        'kindrip_children','kindrip_holdings',
                        'kindrip_transactions','trading_accounts')
ORDER BY tablename;
