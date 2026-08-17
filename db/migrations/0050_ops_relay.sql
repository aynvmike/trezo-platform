-- 0050: ops relay -- a mailbox between Nova and the engine (2026-08-13)
--
-- WHY (Mike's idea, 8/13 ~01:00): the platform moved to a VM, and Nova
-- lost hands on the box. SSH from the PC is flaky and needs Mike awake at
-- a keyboard. Supabase is the one place BOTH sides already hold keys, so
-- it becomes the mailbox: Nova writes a job, the engine executes it on its
-- next watchdog tick and writes the result back. Nobody needs SSH; nobody
-- needs Mike.
--
-- SAFETY, deliberately narrow:
--   * `kind` is CHECKed against a WHITELIST. This is NOT a shell. A table
--     that runs arbitrary strings would be a back door into the machine
--     holding the broker credentials.
--   * NOTHING here may place an order, change risk/posture, or start a
--     second engine. Operations only -- the one hard rule stays hard.
--   * Every job carries who queued it, when, its result, and its output.
--   * `attempts` caps retries so a poisonous job can't loop forever.
--
-- The reverse direction (engine -> Nova) is `ops_log_tail`: the engine
-- posts recent activity-log lines so Nova can read the SERVER's log from
-- anywhere, restoring the visibility lost in the migration.

CREATE TABLE IF NOT EXISTS ops_tasks (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind         text NOT NULL CHECK (kind IN (
                 'restart_service',   -- args: {"service":"TrezoAgents|TrezoApi|TrezoWeb"}
                 'pip_install',       -- args: {"package":"mem0ai"}  (name only, validated)
                 'git_pull_restart',  -- args: {}  pull repo, restart agents
                 'web_rebuild',       -- args: {}  npm run build + restart TrezoWeb
                 'report_status',     -- args: {}  services + health + versions
                 'tail_log'           -- args: {"lines":200}
               )),
  args         jsonb NOT NULL DEFAULT '{}'::jsonb,
  status       text NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued','running','done','failed','skipped')),
  requested_by text NOT NULL DEFAULT 'nova',
  note         text,
  result       text,
  attempts     int  NOT NULL DEFAULT 0,
  created_at   timestamptz NOT NULL DEFAULT now(),
  started_at   timestamptz,
  finished_at  timestamptz
);

CREATE INDEX IF NOT EXISTS ops_tasks_queued_idx
  ON ops_tasks (status, created_at) WHERE status = 'queued';

-- Engine -> Nova: the server's activity log, readable from anywhere.
CREATE TABLE IF NOT EXISTS ops_log_tail (
  id         bigserial PRIMARY KEY,
  ts         timestamptz NOT NULL DEFAULT now(),
  host       text,
  line       jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS ops_log_tail_ts_idx ON ops_log_tail (ts DESC);

-- Service-role only. These tables are operator plumbing, not user data:
-- RLS on with no policies = the anon/authenticated web client can never
-- read or write them, while the engine's service-role key still can.
ALTER TABLE ops_tasks    ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops_log_tail ENABLE ROW LEVEL SECURITY;

SELECT 'ops relay ready' AS status;
