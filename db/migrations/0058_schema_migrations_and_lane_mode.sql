-- 0058: a migrations ledger, and the column the dividend lane's mode
-- switch has been silently missing.
--
-- TWO THINGS, one migration:
--
-- 1. schema_migrations — until now nothing recorded which of these
--    files had been applied. Mike applies migrations by hand in the
--    Supabase SQL editor; with no ledger, "did 00NN run?" was answered
--    by memory or by probing for its side effects. The ledger makes the
--    question a SELECT. Files 0001–0057 are seeded as assumed=true:
--    they were applied before the ledger existed (the platform they
--    built is running), but the ledger did not witness them.
--
-- 2. bot_settings.dividend_lane_mode — the AUDIT 2026-08-27 finding:
--    dividend_lt_agent reads row.get("dividend_lane_mode") and no
--    migration defines that column anywhere, so the read has returned
--    NULL on every call and the lane is permanently ACCUMULATE. The
--    INCOME branch (§6: draw = min(actual distributions, 90% of
--    trailing total return)) could never execute. The companion code
--    change makes the agent's SELECT actually fetch the two columns.
--
-- Apply by hand in the Supabase SQL editor (whole file at once).

-- ---------------------------------------------------------------------
-- 1) The ledger.
create table if not exists public.schema_migrations (
    version     text primary key,          -- e.g. '0058_schema_migrations_and_lane_mode'
    applied_at  timestamptz not null default now(),
    assumed     boolean not null default false,  -- true = predates the ledger; not witnessed
    notes       text
);

comment on table public.schema_migrations is
    'Which db/migrations files have been applied. assumed=true rows '
    'predate this ledger (0058) and were inferred, not witnessed.';

alter table public.schema_migrations enable row level security;

-- Service-role only: engine-owned bookkeeping, not user data.
drop policy if exists schema_migrations_service on public.schema_migrations;
create policy schema_migrations_service
    on public.schema_migrations
    for all
    using (auth.role() = 'service_role')
    with check (auth.role() = 'service_role');

insert into public.schema_migrations (version, assumed, notes) values
    ('0001_initial_schema', true, 'pre-ledger'),
    ('0002_rls_policies', true, 'pre-ledger'),
    ('0003_user_positions', true, 'pre-ledger'),
    ('0004_watchlists_and_ethical', true, 'pre-ledger'),
    ('0005_seed_ethical_exclusions', true, 'pre-ledger'),
    ('0006_pattern_detections', true, 'pre-ledger'),
    ('0007_agents', true, 'pre-ledger'),
    ('0008_paper_trading', true, 'pre-ledger'),
    ('0009_daily_loss_limit', true, 'pre-ledger'),
    ('0010_bot_settings', true, 'pre-ledger'),
    ('0011_tax_fields', true, 'pre-ledger'),
    ('0012_options_positions', true, 'pre-ledger'),
    ('0013_adaptive_scope', true, 'pre-ledger'),
    ('0014_broker_routing', true, 'pre-ledger'),
    ('0015_account_posture', true, 'pre-ledger'),
    ('0016_killswitches', true, 'pre-ledger'),
    ('0017_kindrip', true, 'pre-ledger'),
    ('0018_tax_strategy', true, 'pre-ledger'),
    ('0019_loss_limit_setting', true, 'pre-ledger'),
    ('0020_quick_wins', true, 'pre-ledger'),
    ('0021_dividend_drip', true, 'pre-ledger'),
    ('0022_extended_strategy', true, 'pre-ledger'),
    ('0023_backtest_runs', true, 'pre-ledger'),
    ('0024_agent_memory', true, 'pre-ledger'),
    ('0025_pattern_weights', true, 'pre-ledger'),
    ('0026_broker_connections', true, 'pre-ledger'),
    ('0027_risk_profile', true, 'pre-ledger'),
    ('0028_switching_friction', true, 'pre-ledger'),
    ('0029_wheel_auto_execute', true, 'pre-ledger'),
    ('0030_expert_overrides', true, 'pre-ledger'),
    ('0031_broker_token_refresh', true, 'pre-ledger'),
    ('0032_trade_outcomes', true, 'pre-ledger'),
    ('0033_manual_trade_import', true, 'pre-ledger'),
    ('0034_trade_postmortem', true, 'pre-ledger'),
    ('0035_exit_advisor', true, 'pre-ledger'),
    ('0036_payment_instructions', true, 'pre-ledger'),
    ('0037_terse_format', true, 'pre-ledger'),
    ('0038_auto_trade_toggle', true, 'pre-ledger'),
    ('0039_options_user_filters', true, 'pre-ledger'),
    ('0040_ops_health_alerts', true, 'pre-ledger'),
    ('0041_security_lockdown', true, 'pre-ledger'),
    ('0042_rls_initplan_optimization', true, 'pre-ledger'),
    ('0043_auto_exit_advisor', true, 'pre-ledger'),
    ('0044_crypto_hodl_cap', true, 'pre-ledger'),
    ('0045_owner_account_split', true, 'pre-ledger'),
    ('0046_seed_new_account_state', true, 'pre-ledger'),
    ('0047_repoint_book_tables_to_accounts', true, 'pre-ledger'),
    ('0048_watchlist_items_account_scope', true, 'pre-ledger'),
    ('0049_per_account_risk_targets', true, 'pre-ledger'),
    ('0050_ops_relay', true, 'pre-ledger'),
    ('0051_position_status_partial', true, 'pre-ledger'),
    ('0052_engine_dead_man_switch', true, 'pre-ledger'),
    ('0053_archive_bucket', true, 'pre-ledger'),
    ('0054_restart_did_not_return', true, 'pre-ledger'),
    ('0055_heartbeat_reads_a_continuous_signal', true, 'pre-ledger'),
    ('0056_relay_briefings', true, 'pre-ledger'),
    ('0057_dividend_lane', true, 'pre-ledger'),
    ('0058_schema_migrations_and_lane_mode', false,
     'applied with the ledger itself')
on conflict (version) do nothing;

-- ---------------------------------------------------------------------
-- 2) The lane-mode switch (spec DIVIDEND_LT §1, modes §6).
alter table public.bot_settings
    add column if not exists dividend_lane_mode text
        not null default 'ACCUMULATE'
        check (dividend_lane_mode in ('ACCUMULATE', 'INCOME', 'PARTIAL')),
    add column if not exists dividend_lane_partial_pct numeric
        not null default 0
        check (dividend_lane_partial_pct >= 0
               and dividend_lane_partial_pct <= 100);

comment on column public.bot_settings.dividend_lane_mode is
    'DIVIDEND_LT §1 mode: ACCUMULATE (reinvest everything) | INCOME '
    '(draw per §6: min(actual distributions, 90% of trailing TR)) | '
    'PARTIAL (draw dividend_lane_partial_pct% of the §6 draw).';

comment on column public.bot_settings.dividend_lane_partial_pct is
    'Only read in PARTIAL mode: percent (0-100) of the §6 income draw '
    'taken as income; the rest reinvests.';
