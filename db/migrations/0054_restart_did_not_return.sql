-- 0054 -- catch a restart that never came back (2026-08-18)
--
-- WHY, from this morning:
-- A git_pull_restart job ran at 12:19:35, wrote status 'done', restarted
-- TrezoAgents, and the engine did not return. The row said done. The
-- service said stopped. Nobody looked for an hour, into the open.
--
-- The relay CANNOT verify its own restart -- it marks the row done
-- before it dies, because a process about to be killed cannot report on
-- what happens next. So "restarted fine" and "restarted and died" are
-- indistinguishable from inside. The check has to live out here.
--
-- The generic 15-minute silence alarm would have caught it eventually.
-- But a DELIBERATE restart is different: we know the exact moment the
-- engine was told to come back, so we can be far stricter. Five minutes
-- after a self-kill job completes, the heartbeat must have moved past
-- it. If it has not, the restart failed.

create or replace function public.ops_heartbeat_check()
returns void
language plpgsql
security definer
set search_path = public
as $fn$
declare
  v_age      interval;
  v_url      text;
  v_after    interval;
  v_last     timestamptz;
  v_beat     timestamptz;
  v_restart  timestamptz;
  v_quiet    constant interval := interval '30 minutes';
  v_title    text;
  v_body     text;
  v_key      text;
begin
  select webhook_url, silent_after into v_url, v_after
  from ops_alert_config where id = 1;
  if v_url is null or v_url = '' then
    return;
  end if;

  select max(ts) into v_beat from ops_log_tail;
  v_age := now() - v_beat;

  -- A restart we ASKED for, that finished more than 5 minutes ago.
  select max(finished_at) into v_restart
  from   ops_tasks
  where  status = 'done'
    and  kind in ('git_pull_restart', 'restart_service')
    and  finished_at > now() - interval '2 hours';

  if v_restart is not null
     and now() - v_restart > interval '5 minutes'
     and (v_beat is null or v_beat < v_restart) then
    -- Told to restart, finished, and has not spoken since. It did not
    -- come back. This is the specific, fast alarm.
    v_key   := 'restart_did_not_return';
    v_title := '🔴 Restart did not come back';
    v_body  := format(
      'A restart job completed at %s and the engine has not posted since. '
      || 'The row says done; the process is not running. Nothing is '
      || 'enforcing a stop on any book.' || chr(10) || chr(10)
      || 'On the server:' || chr(10)
      || 'nssm status TrezoAgents' || chr(10)
      || 'nssm start TrezoAgents' || chr(10) || chr(10)
      || 'If it will not start, roll back -- old code beats no engine:'
      || chr(10) || 'git reset --hard 58d1954',
      to_char(v_restart, 'HH24:MI:SS UTC'));
  elsif v_age is null or v_age < v_after then
    -- Healthy. Drop both latches so the next fault reports at once.
    delete from ops_alert_state
     where key in ('engine_silent', 'restart_did_not_return');
    return;
  else
    v_key   := 'engine_silent';
    v_title := '🔴 Engine silent';
    v_body  := format(
      'No heartbeat for **%s**. The engine has stopped posting, which '
      || 'means it is not ticking -- no stops, no targets and no profit '
      || 'ladder on any book. Alpaca holds no bracket on crypto, so those '
      || 'positions are unprotected outright.' || chr(10) || chr(10)
      || 'Check the service first: nssm status TrezoAgents.',
      date_trunc('second', v_age));
  end if;

  select last_sent_at into v_last from ops_alert_state where key = v_key;
  if v_last is not null and (now() - v_last) < v_quiet then
    return;
  end if;

  perform net.http_post(
    url     := v_url,
    headers := '{"Content-Type": "application/json"}'::jsonb,
    body    := jsonb_build_object(
      'username', 'Trezo',
      'embeds', jsonb_build_array(jsonb_build_object(
        'title', v_title, 'description', v_body, 'color', 14690869)))
  );

  insert into ops_alert_state (key, last_sent_at)
  values (v_key, now())
  on conflict (key) do update set last_sent_at = excluded.last_sent_at;
end;
$fn$;

select 'restart-did-not-return guard installed' as status;
