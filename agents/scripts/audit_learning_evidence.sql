-- Read-only diagnostic, not an account-return calculation or reconciliation.
-- Run through an authorized Supabase SQL connection. No credentials belong here.
-- Owner/admin scope: examines every paper book visible to the caller. Do not expose
-- this query as an unscoped customer endpoint or commit its private output to git.
-- One statement gives the aggregates a common database snapshot. It cannot verify
-- broker fills, current marked equity, external cash flows, or deployed engine SHA.
WITH position_totals AS (
    SELECT user_id,
           count(*) FILTER (WHERE status = 'open') AS open_rows,
           count(*) FILTER (WHERE status <> 'open') AS closed_rows,
           count(*) FILTER (WHERE status <> 'open' AND realized_pnl_usd IS NULL)
               AS closed_rows_missing_pnl,
           count(*) FILTER (WHERE status <> 'open' AND realized_pnl_usd > 0)
               AS winning_rows,
           count(*) FILTER (WHERE status <> 'open' AND realized_pnl_usd = 0)
               AS breakeven_rows,
           sum(realized_pnl_usd) FILTER (WHERE status <> 'open')
               AS recorded_closed_pnl_usd,
           min(exit_at) AS first_recorded_close,
           max(exit_at) AS latest_recorded_close,
           count(*) FILTER (WHERE status <> 'open' AND source_payload ? 'adopted')
               AS closed_rows_with_adoption_tag,
           count(*) FILTER (WHERE status <> 'open' AND source_payload ? 'phantom_unwind')
               AS closed_rows_with_phantom_unwind_tag,
           count(*) FILTER (WHERE status <> 'open' AND broker = 'alpaca'
                            AND broker_order_id IS NULL)
               AS alpaca_closed_rows_without_entry_order_id
    FROM public.paper_positions
    GROUP BY user_id
), books AS (
    SELECT ta.label AS book, ta.is_paper,
           pa.starting_capital_usd,
           pa.ytd_realized_pnl_usd AS account_ytd_counter_usd,
           pa.updated_at AS account_counter_updated_at,
           coalesce(pt.open_rows, 0) AS open_rows,
           coalesce(pt.closed_rows, 0) AS closed_rows,
           pt.closed_rows_missing_pnl,
           pt.recorded_closed_pnl_usd,
           pt.first_recorded_close, pt.latest_recorded_close,
           pt.closed_rows_with_adoption_tag,
           pt.closed_rows_with_phantom_unwind_tag,
           pt.alpaca_closed_rows_without_entry_order_id,
           round(100.0 * pt.winning_rows / nullif(pt.closed_rows, 0), 2)
               AS recorded_closed_row_win_rate_pct,
           pt.breakeven_rows,
           NULL::numeric AS verified_account_return_pct,
           false AS sufficient_for_strategy_promotion
    FROM public.paper_accounts pa
    LEFT JOIN public.trading_accounts ta ON ta.account_key = pa.user_id
    LEFT JOIN position_totals pt ON pt.user_id = pa.user_id
), outcome_shapes AS (
    SELECT source_table, status, count(*) AS outcome_rows,
           count(DISTINCT position_id) AS distinct_position_ids,
           count(*) FILTER (WHERE position_id IS NULL) AS missing_position_ids,
           min(closed_at) AS first_close, max(closed_at) AS latest_close
    FROM public.trade_outcomes
    GROUP BY source_table, status
), backtests AS (
    SELECT strategy, count(*) AS saved_runs,
           count(*) FILTER (WHERE trades > 0) AS runs_with_trades,
           min(created_at) AS first_saved_run,
           max(created_at) AS latest_saved_run
    FROM public.backtest_runs
    GROUP BY strategy
), discovery_events AS (
    SELECT kind, payload->>'event' AS event,
           count(*) AS saved_messages, max(created_at) AS latest_saved_message
    FROM public.agent_messages
    WHERE agent_name = 'strategy_discovery'
    GROUP BY kind, payload->>'event'
)
SELECT jsonb_build_object(
    'observed_at', now(),
    'report_kind', 'learning_evidence_diagnostic',
    'account_returns_verified', false,
    'interpretation', jsonb_build_array(
        'Recorded closed-position P&L is not marked account return.',
        'Counter and ledger dates, resets and corrections must be reconciled before comparison.',
        'Fee treatment differs between existing writers; do not subtract all fees again.',
        'Partial exits are rows/events, not independent complete trade lifecycles.',
        'Multiple outcomes per position may be legitimate slices; do not deduplicate blindly.',
        'Provenance tags or missing IDs flag investigation, not automatic deletion.',
        'Missing saved backtests does not establish whether an external test was performed.',
        'A review alert does not establish that a retest was queued or completed.'
    ),
    'books', coalesce((SELECT jsonb_agg(to_jsonb(b) ORDER BY b.book) FROM books b), '[]'::jsonb),
    'outcome_shapes', coalesce((SELECT jsonb_agg(to_jsonb(o) ORDER BY o.source_table, o.status)
                               FROM outcome_shapes o), '[]'::jsonb),
    'saved_backtests', coalesce((SELECT jsonb_agg(to_jsonb(b) ORDER BY b.strategy)
                                FROM backtests b), '[]'::jsonb),
    'discovery_events', coalesce((SELECT jsonb_agg(to_jsonb(d) ORDER BY d.kind, d.event)
                                 FROM discovery_events d), '[]'::jsonb)
) AS diagnostic;
