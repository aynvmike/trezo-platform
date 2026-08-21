-- 0056: relay briefings -- Nova's skills feed the engine context (2026-08-21)
--
-- WHY (Mike, 8/21): the authored skills (market-report, market-movers-
-- report, trezo-daily-wrap, trezo-midday-snapshot, trezo-server-sentinel)
-- already produce a structured read of the tape, the book and the box --
-- but only Mike reads it. This table is the second copy, addressed to the
-- engine. A skill finishes its run by posting ONE row here; the
-- relay_ingest agent drains it on its next tick and files it into shared
-- agent memory so every agent can recall "what did Nova see at 3:30?".
--
-- SAFETY -- context only, deliberately:
--   * A briefing is INFORMATION. Nothing in it is executed, nothing here
--     may place an order, change scope/posture/sizing, or touch a
--     setting. relay_ingest writes memory + an `info` bus message and
--     stops. Anything more is a later, separate decision.
--   * `kind` is CHECKed against a short whitelist and every payload is
--     validated against a per-kind schema on the engine. An unknown or
--     malformed briefing is marked `rejected` WITH the reason -- never
--     silently skipped (a brief that vanishes is a brief you think
--     landed).
--   * Every row carries who posted it, when, and what the engine did
--     with it.

CREATE TABLE IF NOT EXISTS relay_briefings (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source       text NOT NULL,                 -- skill name, e.g. 'market-report'
  kind         text NOT NULL CHECK (kind IN (
                 'market_context',   -- tape read: indices, regime, movers, earnings
                 'daily_wrap',       -- end-of-day book analytics
                 'health'            -- midday snapshot / server sentinel verdict
               )),
  slot         text,                          -- 'pre-market' | 'open' | 'midday' | 'pre-close' | 'post-close' | date
  payload      jsonb NOT NULL,
  posted_by    text NOT NULL DEFAULT 'nova',
  status       text NOT NULL DEFAULT 'new'
                 CHECK (status IN ('new','ingested','rejected')),
  result       text,                          -- what the engine did, or why it refused
  created_at   timestamptz NOT NULL DEFAULT now(),
  ingested_at  timestamptz
);

CREATE INDEX IF NOT EXISTS relay_briefings_new_idx
  ON relay_briefings (status, created_at) WHERE status = 'new';
CREATE INDEX IF NOT EXISTS relay_briefings_kind_idx
  ON relay_briefings (kind, created_at DESC);

-- Service-role only, same as ops_tasks: RLS on with no policies.
ALTER TABLE relay_briefings ENABLE ROW LEVEL SECURITY;

SELECT 'relay briefings ready' AS status;
