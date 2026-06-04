-- 0042 - RLS performance optimization: wrap auth.uid() in (select auth.uid())
-- so Postgres caches the value per query instead of re-evaluating per row.
--
-- Linter category: PERFORMANCE (not security). Policy semantics are
-- preserved exactly - row-level filtering still works the same way.
-- Only the query plan changes.
--
-- Mike 2026-06-04 (6:41 AM): 41 policies flagged by Supabase linter.
-- Single migration handles all of them programmatically by reading the
-- current policy text from pg_catalog and rewriting in place.

do $$
declare
  pol record;
  new_qual text;
  new_check text;
  cmd_clause text;
  permissive_clause text;
  using_clause text;
  check_clause text;
  roles_clause text;
  full_sql text;
  fixed_count int := 0;
begin
  for pol in
    select
      p.polname,
      p.polrelid::regclass::text as table_full,
      n.nspname as schema_name,
      c.relname as table_name,
      p.polcmd,
      p.polpermissive,
      pg_catalog.pg_get_expr(p.polqual, p.polrelid) as qual_text,
      pg_catalog.pg_get_expr(p.polwithcheck, p.polrelid) as check_text,
      array(
        select quote_ident(rolname) from pg_authid where oid = any(p.polroles)
      ) as roles_arr
    from pg_policy p
    join pg_class c on c.oid = p.polrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and (
        coalesce(pg_catalog.pg_get_expr(p.polqual,      p.polrelid), '') ~ 'auth\.uid\(\)'
        or coalesce(pg_catalog.pg_get_expr(p.polwithcheck, p.polrelid), '') ~ 'auth\.uid\(\)'
      )
  loop
    -- 1) Substitute auth.uid() -> (select auth.uid()) in both clauses.
    -- The second replace fixes any accidental double-wrap so the
    -- migration is idempotent if re-run.
    new_qual := regexp_replace(
      coalesce(pol.qual_text, ''),
      'auth\.uid\(\)',
      '(select auth.uid())',
      'g'
    );
    new_qual := regexp_replace(
      new_qual,
      '\(select \(select auth\.uid\(\)\)\)',
      '(select auth.uid())',
      'g'
    );

    new_check := regexp_replace(
      coalesce(pol.check_text, ''),
      'auth\.uid\(\)',
      '(select auth.uid())',
      'g'
    );
    new_check := regexp_replace(
      new_check,
      '\(select \(select auth\.uid\(\)\)\)',
      '(select auth.uid())',
      'g'
    );

    -- 2) Reconstruct the policy clauses.
    permissive_clause := case
      when pol.polpermissive then 'AS PERMISSIVE'
      else 'AS RESTRICTIVE'
    end;

    cmd_clause := case pol.polcmd
      when 'r' then 'FOR SELECT'
      when 'a' then 'FOR INSERT'
      when 'w' then 'FOR UPDATE'
      when 'd' then 'FOR DELETE'
      when '*' then 'FOR ALL'
      else 'FOR ALL'
    end;

    if pol.roles_arr is not null and array_length(pol.roles_arr, 1) > 0 then
      roles_clause := 'TO ' || array_to_string(pol.roles_arr, ', ');
    else
      roles_clause := 'TO PUBLIC';
    end if;

    using_clause := case
      when new_qual is not null and new_qual <> '' then
        format('USING (%s)', new_qual)
      else ''
    end;

    check_clause := case
      when new_check is not null and new_check <> '' then
        format('WITH CHECK (%s)', new_check)
      else ''
    end;

    -- 3) Drop the existing policy and recreate with the rewritten clauses.
    execute format('DROP POLICY IF EXISTS %I ON %s', pol.polname, pol.table_full);

    full_sql := format(
      'CREATE POLICY %I ON %s %s %s %s %s %s',
      pol.polname,
      pol.table_full,
      permissive_clause,
      cmd_clause,
      roles_clause,
      using_clause,
      check_clause
    );

    -- Defensive: collapse any double spaces from empty clauses.
    full_sql := regexp_replace(full_sql, '\s+', ' ', 'g');

    raise notice 'Rewriting %.% -> %', pol.schema_name, pol.polname, full_sql;
    execute full_sql;
    fixed_count := fixed_count + 1;
  end loop;

  raise notice 'Migration 0042 done: % policies rewritten', fixed_count;
end $$;
