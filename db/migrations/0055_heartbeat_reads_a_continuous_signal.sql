-- 0055 -- the dead-man switch was watching the wrong clock (2026-08-19)
--
-- WHY, from this morning:
-- 10:25 EDT, Discord: "Engine silent -- no heartbeat for 00:15:11 ...
-- positions are unprotected outright." The engine was fine. It had been
-- writing continuously the entire time; positions entered and exited at
-- 14:09 UTC, inside the window the alarm was complaining about. Over the
-- whole preceding 24 hours there was exactly ONE real gap in engine
-- activity: yesterday's 16:15->22:02 UTC outage.
--
-- The bug is the signal, not the threshold. ops_heartbeat_check read
-- `max(ts) from ops_log_tail`, and ops_log_tail is not a heartbeat -- it
-- is a BATCHED rolling copy of the activity log that the engine uploads
-- every ten minutes or so. Its freshest timestamp therefore advances in
-- jumps. Observed directly today while the engine was demonstrably
-- alive: 14:30:30 -> 14:46:19, a 15.8 minute step. silent_after sits at
-- roughly fifteen minutes. Ordinary upload jitter trips it.
--
-- WHY THIS MATTERS MORE THAN THE NUISANCE:
-- Yesterday's alert was REAL -- five hours and forty-six minutes with
-- unprotected crypto, since Alpaca holds no bracket for us. An alarm
-- that fires on nothing teaches you to swipe past the one that isn't
-- nothing. A monitor you have learned to ignore is worse than no
-- monitor, because you believe you are covered.
--
-- THE FIX: read a signal that is actually continuous.
-- agent_messages is written ONLY by the engine (app/runtime/persistence.py
-- flush_buffer; the web tier and API only ever SELECT from it), and the
-- flush loop drains every 1 second, so it tracks liveness in near real
-- time rather than in ten-minute batches.
--
-- WHY GREATEST() OF BOTH AND NOT A SWAP: every input here is written
-- exclusively by the engine, so adding one can only make "alive" easier
-- to see -- it cannot mask a death. If the engine stops, both freeze
-- together. This trade never buys quiet at the cost of a false green,
-- which is the only failure mode that would actually cost money.
--
-- AND THE SIGNAL WE WOULD OTHERWISE HAVE SILENCED:
-- once the alarm no longer depends on ops_log_tail, an ops_log_tail
-- uploader that quietly dies would never be noticed -- and that upload
-- is how we read the engine's logs without being at the machine. So a
-- separate, lower-priority alert now fires when the engine is provably
-- alive but the log tail has gone stale. Removing a reason to look is
-- not the same as removing the problem.

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
  v_msgs     timestamptz;
  v_tail     timestamptz;
  v_restart  timestamptz;
  v_quiet    constant interval := interval '30 minutes';
  -- The log tail uploads on a ~10 minute cadence, so it is only
  -- genuinely stuck well past that. Deliberately loose: this alert is
  -- about losing remote visibility, not about losing protection.
  v_tail_max constant interval := interval '45 minutes';
  v_title    text;
  v_body     text;
  v_key      text;
begin
  select webhook_url, silent_after into v_url, v_after
  from ops_alert_config where id = 1;
  if v_url is null or v_url = '' then
    return;
  end if;

  -- Both are engine-only writes. agent_messages is the continuous one
  -- (1s flush loop); ops_log_tail is the batched one kept as a
  -- belt-and-braces second opinion.
  select max(created_at) into v_msgs from agent_messages;
  select max(ts)         into v_tail from ops_log_tail;
  v_beat := greatest(v_msgs, v_tail);   -- greatest() ignores NULLs
  v_age  := now() - v_beat;

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

  -- A NULL heartbeat means COULD NOT CHECK, not "nothing wrong". The
  -- previous version read `v_age is null` as healthy and returned, so a
  -- heartbeat that was never recorded looked exactly like one that was
  -- recorded a second ago. That is the most dangerous value a monitor
  -- can hold. Null now falls through to the alarm.
  elsif v_beat is not null and v_age < v_after then
    -- The engine is alive. Drop the protection latches so the next real
    -- fault reports immediately.
    delete from ops_alert_state
     where key in ('engine_silent', 'restart_did_not_return');

    -- Alive, but are we still able to SEE it? If the log tail has not
    -- uploaded in 45 minutes while the engine is clearly running, the
    -- uploader is stuck and we have lost remote logs without being told.
    if v_tail is null or (now() - v_tail) > v_tail_max then
      v_key   := 'log_tail_stale';
      v_title := '🟠 Log upload stuck (engine is fine)';
      v_body  := format(
        'The engine is alive -- it last wrote %s ago -- but the activity '
        || 'log has not uploaded for **%s**. Trading is unaffected and '
        || 'stops are still being enforced. What is lost is the ability '
        || 'to read the engine logs remotely, which is exactly what we '
        || 'need during the NEXT incident.' || chr(10) || chr(10)
        || 'No rush, but do not leave it: restart the service when '
        || 'convenient -- nssm restart TrezoAgents.',
        date_trunc('second', now() - v_msgs),
        coalesce(date_trunc('second', now() - v_tail)::text, 'ever'));
    else
      delete from ops_alert_state where key = 'log_tail_stale';
      return;
    end if;

  else
    v_key   := 'engine_silent';
    v_title := '🔴 Engine silent';
    v_body  := format(
      'No heartbeat for **%s**. The engine has stopped posting, which '
      || 'means it is not ticking -- no stops, no targets and no profit '
      || 'ladder on any book. Alpaca holds no bracket on crypto, so those '
      || 'positions are unprotected outright.' || chr(10) || chr(10)
      || 'Check the service first: nssm status TrezoAgents.',
      coalesce(date_trunc('second', v_age)::text,
               'EVER - no heartbeat has ever been recorded'));
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
        'title', v_title, 'description', v_body,
        'color', case when v_key = 'log_tail_stale'
                      then 15895619 else 14690869 end)))
  );

  insert into ops_alert_state (key, last_sent_at)
  values (v_key, now())
  on conflict (key) do update set last_sent_at = excluded.last_sent_at;
end;
$fn$;

select 'heartbeat now reads agent_messages (continuous), not ops_log_tail (batched)'
       as status;
