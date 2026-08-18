-- 0052 -- the dead man's switch. Supabase watches the engine.
--
-- WHY (2026-08-18)
-- On 8/17 the engine stopped at 15:30 ET. It was found 15 hours later,
-- by accident, while looking at something else. Three books ran through
-- a full overnight crypto session with nothing enforcing a stop.
--
-- Everything else we are adding runs INSIDE the engine, which is fine
-- for "a book stopped adding up" and useless for "the engine stopped",
-- because a dead process cannot report its own death. That check has to
-- live somewhere the engine cannot take down with it. Supabase already
-- holds the heartbeat (ops_log_tail) and can make outbound HTTP calls,
-- so it is the natural watcher.
--
-- The result is a closed loop with no single point of silence:
--   the engine watches the books, the database watches the engine.
--
-- SETUP (one time, after running this):
--   insert into ops_alert_config (id, webhook_url)
--   values (1, 'https://discord.com/api/webhooks/...')
--   on conflict (id) do update set webhook_url = excluded.webhook_url;

create extension if not exists pg_cron;
create extension if not exists pg_net;

create table if not exists ops_alert_config (
  id          int primary key default 1,
  webhook_url text not null default '',
  -- How long the engine may be silent before we shout. The engine posts
  -- its log tail every few minutes, so 15 is comfortably past normal
  -- jitter without letting an outage run for an hour.
  silent_after interval not null default interval '15 minutes',
  updated_at  timestamptz not null default now(),
  constraint ops_alert_config_singleton check (id = 1)
);

-- Latch, so a persistent outage does not repeat every five minutes.
-- Cleared the moment the engine speaks again, so the NEXT outage alerts
-- immediately rather than waiting out a stale quiet period.
create table if not exists ops_alert_state (
  key          text primary key,
  last_sent_at timestamptz not null
);

create or replace function public.ops_heartbeat_check()
returns void
language plpgsql
security definer
set search_path = public
as $fn$
declare
  v_age    interval;
  v_url    text;
  v_after  interval;
  v_last   timestamptz;
  v_quiet  constant interval := interval '30 minutes';
begin
  select webhook_url, silent_after into v_url, v_after
  from ops_alert_config where id = 1;

  if v_url is null or v_url = '' then
    return;                       -- not configured: stay silent
  end if;

  select now() - max(ts) into v_age from ops_log_tail;

  if v_age is null or v_age < v_after then
    -- Healthy. Drop the latch so a future outage is reported at once.
    delete from ops_alert_state where key = 'engine_silent';
    return;
  end if;

  select last_sent_at into v_last
  from ops_alert_state where key = 'engine_silent';
  if v_last is not null and (now() - v_last) < v_quiet then
    return;
  end if;

  perform net.http_post(
    url     := v_url,
    headers := '{"Content-Type": "application/json"}'::jsonb,
    body    := jsonb_build_object(
      'username', 'Trezo',
      'embeds', jsonb_build_array(jsonb_build_object(
        'title', '🔴 Engine silent',
        'description', format(
          'No heartbeat for **%s**. The engine has stopped posting to '
          || 'ops_log_tail, which means it is not ticking -- no stops, no '
          || 'targets and no profit ladder are being enforced on any book. '
          || 'Alpaca holds no bracket on crypto, so those positions are '
          || 'unprotected outright.' || chr(10) || chr(10)
          || 'Check the service first: nssm status TrezoAgents.',
          date_trunc('second', v_age)),
        'color', 14690869)))
  );

  insert into ops_alert_state (key, last_sent_at)
  values ('engine_silent', now())
  on conflict (key) do update set last_sent_at = excluded.last_sent_at;
end;
$fn$;

-- Every 5 minutes. Worst case an outage is reported ~20 minutes in,
-- against the 15 hours it took on 8/17.
select cron.unschedule('trezo-heartbeat-watch')
where exists (select 1 from cron.job where jobname = 'trezo-heartbeat-watch');

select cron.schedule(
  'trezo-heartbeat-watch',
  '*/5 * * * *',
  $cron$select public.ops_heartbeat_check()$cron$
);

alter table ops_alert_config enable row level security;
alter table ops_alert_state  enable row level security;

select 'dead man switch ready -- now insert your webhook_url into ops_alert_config' as status;
