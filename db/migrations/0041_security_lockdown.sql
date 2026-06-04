-- 0041 - Security lockdown for SECURITY DEFINER functions.
-- Mike 2026-06-03: Supabase linter flagged 12 warnings across 4 functions:
--   - function_search_path_mutable (4)
--   - anon_security_definer_function_executable (4)
--   - authenticated_security_definer_function_executable (4)
--
-- Fix strategy:
--   1. Revoke EXECUTE from anon and authenticated roles - these functions
--      are called internally by triggers and by the service_role key from
--      the agents server. They should never be reachable via the public
--      REST API. This single change closes the external attack surface.
--
--   2. ALTER each function to SET search_path = pg_catalog, public so the
--      SECURITY DEFINER path can't be hijacked by an attacker placing a
--      same-named object earlier in their search_path.
--
-- After applying, the function bodies are unchanged - they still work
-- for the trigger and service_role callers. They are simply no longer
-- callable by anon or authenticated via /rest/v1/rpc/*.

-- ---- Revoke external EXECUTE on the 4 flagged functions -----------------

revoke execute on function public.handle_new_user()       from anon, authenticated, public;
revoke execute on function public.rls_auto_enable()       from anon, authenticated, public;
revoke execute on function public.seed_bot_settings()     from anon, authenticated, public;
revoke execute on function public.seed_paper_account()    from anon, authenticated, public;

-- set_updated_at is a trigger helper - never called via RPC, but revoke
-- defensively in case something gets re-granted later.
revoke execute on function public.set_updated_at()        from anon, authenticated, public;

-- ---- Pin the search_path on all 5 functions -----------------------------
-- Prevents search_path hijack attacks against SECURITY DEFINER bodies.

do $$
begin
  if exists (select 1 from pg_proc p
             join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = 'public' and p.proname = 'handle_new_user') then
    alter function public.handle_new_user()      set search_path = pg_catalog, public;
  end if;
  if exists (select 1 from pg_proc p
             join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = 'public' and p.proname = 'rls_auto_enable') then
    alter function public.rls_auto_enable()      set search_path = pg_catalog, public;
  end if;
  if exists (select 1 from pg_proc p
             join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = 'public' and p.proname = 'seed_bot_settings') then
    alter function public.seed_bot_settings()    set search_path = pg_catalog, public;
  end if;
  if exists (select 1 from pg_proc p
             join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = 'public' and p.proname = 'seed_paper_account') then
    alter function public.seed_paper_account()   set search_path = pg_catalog, public;
  end if;
  if exists (select 1 from pg_proc p
             join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = 'public' and p.proname = 'set_updated_at') then
    alter function public.set_updated_at()       set search_path = pg_catalog, public;
  end if;
end $$;
