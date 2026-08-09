-- 0047: point the BOOK tables at trading_accounts, not auth.users
--                                          (2026-08-09, multi-account)
--
-- WHY THIS SHAPE
-- 0046 failed on paper_accounts_user_id_fkey: user_id is bound to
-- auth.users, so a book id must be a real person. 25 tables carry that
-- constraint, all ON DELETE CASCADE. Two ways out were considered:
--   * mint a fake auth user per book -- fast, but every real customer's
--     second account becomes a fake login and auth.uid() based RLS stops
--     meaning anything. Rejected.
--   * add an account_key column to ~20 tables and rewrite engine.py's 46
--     user_id references. Correct, but it renames a column to say what it
--     already says.
-- This does neither. It repoints the FK: book tables -> trading_accounts,
-- trading_accounts -> auth.users. Person, accounts, books: a proper chain.
-- CASCADE survives transitively (delete a person -> their accounts go ->
-- their books' data goes), the column keeps its name, and NO application
-- code changes -- the engine already treats user_id as the account key,
-- which is why it is being made official rather than replaced.
--
-- WHAT CHANGES FOR RLS
-- `auth.uid() = user_id` stops matching a person's SECOND book. The 25
-- book policies become "is this book one of mine". The 14 person policies
-- (profiles, payments, broker connections, ethical settings, risk audit)
-- are NOT touched -- they are genuinely about the person.
--
-- REVERSIBLE and TRANSACTIONAL: wrapped in BEGIN/COMMIT, so any failure
-- rolls the whole thing back and leaves you exactly where you started.

BEGIN;

-- 1. Every existing book must be registered BEFORE it can be referenced.
-- ADD CONSTRAINT ... FOREIGN KEY validates every existing row, so a single
-- user_id anywhere in any book table that is missing from trading_accounts
-- fails the whole migration. Sweep them ALL, not just paper_accounts --
-- agent_messages and trades in particular can hold ids that never got a
-- paper_accounts row. Books predating trading_accounts are owned by
-- themselves, which preserves today's meaning exactly.
DO $seed$
DECLARE
  book_tables text[] := ARRAY[
    'paper_accounts','paper_positions','paper_vault_transactions',
    'options_positions','user_positions','trades','trade_outcomes',
    'bot_settings','backtest_runs','watchlists','stock_disabled',
    'stock_strategy_overrides','pattern_detections','exit_advisor_alerts',
    'agent_logs','agent_messages','agent_state'
  ];
  t text;
  n bigint;
BEGIN
  FOREACH t IN ARRAY book_tables LOOP
    IF to_regclass('public.' || t) IS NULL THEN CONTINUE; END IF;
    -- skip tables that have no user_id column at all
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=t
                     AND column_name='user_id') THEN CONTINUE; END IF;

    EXECUTE format(
      'INSERT INTO trading_accounts (account_key, owner_id, label, broker, is_paper) '
      'SELECT DISTINCT x.user_id, x.user_id, %L, ''alpaca'', true '
      'FROM public.%I x WHERE x.user_id IS NOT NULL '
      'ON CONFLICT (account_key) DO NOTHING',
      'Imported from ' || t, t);
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n > 0 THEN RAISE NOTICE 'registered % book(s) found in %', n, t; END IF;
  END LOOP;
END
$seed$;

-- 2. "Which books are mine?" -- one definition, used by every policy.
-- STABLE so Postgres evaluates it once per query rather than per row.
-- SECURITY DEFINER so a policy on a book table can read trading_accounts
-- without needing its own policy to be satisfied first (which would
-- recurse). search_path pinned, per the security-definer lockdown.
CREATE OR REPLACE FUNCTION public.my_account_keys()
RETURNS SETOF uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $fn$
  SELECT account_key FROM public.trading_accounts
  WHERE owner_id = (SELECT auth.uid());
$fn$;

REVOKE ALL ON FUNCTION public.my_account_keys() FROM public;
GRANT EXECUTE ON FUNCTION public.my_account_keys() TO authenticated;

-- 3. trading_accounts itself: a person sees only their own accounts.
ALTER TABLE trading_accounts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS trading_accounts_self_all ON trading_accounts;
CREATE POLICY trading_accounts_self_all ON trading_accounts
  FOR ALL USING ((SELECT auth.uid()) = owner_id)
  WITH CHECK ((SELECT auth.uid()) = owner_id);

-- 4. Repoint the BOOK tables. Constraint names vary, so find them rather
-- than assume. Tables absent or already repointed are skipped silently.
DO $repoint$
DECLARE
  book_tables text[] := ARRAY[
    'paper_accounts','paper_positions','paper_vault_transactions',
    'options_positions','user_positions','trades','trade_outcomes',
    'bot_settings','backtest_runs','watchlists','stock_disabled',
    'stock_strategy_overrides','pattern_detections','exit_advisor_alerts',
    'agent_logs','agent_messages','agent_state'
  ];
  t text;
  con_name text;
BEGIN
  FOREACH t IN ARRAY book_tables LOOP
    IF to_regclass('public.' || t) IS NULL THEN CONTINUE; END IF;

    SELECT con.conname INTO con_name
    FROM pg_constraint con
    JOIN pg_attribute a
      ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1]
    WHERE con.contype = 'f'
      AND con.conrelid = ('public.' || t)::regclass
      AND con.confrelid = 'auth.users'::regclass
      AND a.attname = 'user_id'
    LIMIT 1;

    IF con_name IS NULL THEN CONTINUE; END IF;

    EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I', t, con_name);
    EXECUTE format(
      'ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY (user_id) '
      'REFERENCES public.trading_accounts(account_key) ON DELETE CASCADE',
      t, t || '_account_key_fkey');
    RAISE NOTICE 'repointed %', t;
  END LOOP;
END
$repoint$;

-- 5. Rewrite the book policies: "mine" now means "one of my books".
-- Only policies whose predicate is exactly the simple uid = user_id form
-- are touched; anything hand-written is left alone for manual review.
DO $policies$
DECLARE
  r record;
  book_tables text[] := ARRAY[
    'paper_accounts','paper_positions','paper_vault_transactions',
    'options_positions','user_positions','trades','trade_outcomes',
    'bot_settings','backtest_runs','watchlists','stock_disabled',
    'stock_strategy_overrides','pattern_detections','exit_advisor_alerts',
    'agent_logs','agent_messages','agent_state'
  ];
  pred text := 'user_id IN (SELECT public.my_account_keys())';
BEGIN
  FOR r IN
    SELECT tablename, policyname, cmd
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = ANY(book_tables)
      AND coalesce(qual::text, with_check::text) ILIKE '%auth.uid()%'
      AND coalesce(qual::text, with_check::text) ILIKE '%= user_id%'
  LOOP
    EXECUTE format('DROP POLICY %I ON public.%I', r.policyname, r.tablename);
    IF r.cmd = 'INSERT' THEN
      EXECUTE format('CREATE POLICY %I ON public.%I FOR INSERT WITH CHECK (%s)',
                     r.policyname, r.tablename, pred);
    ELSIF r.cmd = 'ALL' THEN
      EXECUTE format('CREATE POLICY %I ON public.%I FOR ALL USING (%s) WITH CHECK (%s)',
                     r.policyname, r.tablename, pred, pred);
    ELSE
      EXECUTE format('CREATE POLICY %I ON public.%I FOR %s USING (%s)',
                     r.policyname, r.tablename, r.cmd, pred);
    END IF;
    RAISE NOTICE 'rewrote %.%', r.tablename, r.policyname;
  END LOOP;
END
$policies$;

COMMIT;

-- 6. Confirmation
SELECT 'books now referencing trading_accounts' AS check,
       count(*) AS n
FROM pg_constraint
WHERE contype='f' AND confrelid='public.trading_accounts'::regclass
UNION ALL
SELECT 'book policies rewritten',
       count(*) FROM pg_policies
WHERE schemaname='public' AND qual::text ILIKE '%my_account_keys%'
UNION ALL
SELECT 'person policies untouched',
       count(*) FROM pg_policies
WHERE schemaname='public' AND tablename IN
  ('profiles','payment_instructions','broker_connections',
   'broker_token_refresh_log','ethical_filter_settings',
   'ethical_overrides','risk_profile_audit')
  AND qual::text ILIKE '%auth.uid()%';
