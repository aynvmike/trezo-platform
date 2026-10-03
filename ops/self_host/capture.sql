-- psql input, NOT a Supabase migration. Read-only consistent inventory.
-- This deliberately fails if a required table is absent or unreadable.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '120s';
SET LOCAL timezone = 'UTC';
SELECT json_build_object('kind', 'meta', 'server_version_num', current_setting('server_version_num'));
SELECT json_build_object('kind', 'book', 'account_key', a.account_key,
  'owner_id', a.owner_id, 'is_paper', a.is_paper, 'is_active', a.is_active,
  'broker', a.broker,
  'owner_count', (SELECT count(*) FROM auth.users u WHERE u.id = a.owner_id),
  'settings_count', (SELECT count(*) FROM public.bot_settings b WHERE b.user_id = a.account_key),
  'account_count', (SELECT count(*) FROM public.paper_accounts p WHERE p.user_id = a.account_key))
FROM public.trading_accounts a ORDER BY a.account_key;

-- Hash all public table rows, including budgets, risk counters, positions,
-- migrations and audit history; never print their contents or auth hashes.
-- Row hashes are sorted so physical row order does not matter. MD5 here is a
-- consistency fingerprint, not an adversarial integrity/security signature.
SELECT format(
  'SELECT json_build_object(''kind'',''table'',''name'',%L,''rows'',count(*),''fingerprint'',md5(coalesce(string_agg(h, '''' ORDER BY h),''''))) FROM (SELECT md5(to_jsonb(t)::text) h FROM %I.%I t) row_hashes;',
  n.nspname || '.' || c.relname, n.nspname, c.relname)
FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p') AND (
  n.nspname = 'public' OR
  (n.nspname = 'auth' AND c.relname IN ('users', 'identities')) OR
  (n.nspname = 'storage' AND c.relname IN ('buckets', 'objects')))
ORDER BY n.nspname, c.relname
\gexec
COMMIT;
