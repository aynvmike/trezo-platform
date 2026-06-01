-- =====================================================================
-- Trezo — Phase 13/14 follow-up: trade post-mortem analyzer
-- =====================================================================
-- For each closed trade (bot or manual), replay the candles around the
-- window and compute "what could have been done better." Mike's note:
-- his biggest leak is holding too long. We want the bot to surface that
-- pattern in his own historical data.
--
-- Columns added to trade_outcomes:
--   postmortem            jsonb   - structured analysis blob
--   postmortem_diagnosis  text    - short tag for fast filtering
--   postmortem_ran_at     timestamptz
--
-- Diagnoses (short tags):
--   'optimal'           — exit was within 5% of MFE
--   'held_too_long'     — MFE peaked >2 days before close, gave back >50%
--   'exited_too_early'  — price kept moving in your favor >5% after close
--   'stop_too_tight'    — MAE hit your stop before MFE could develop
--   'late_to_stop'      — stop blew through; you held past the obvious exit
--   'no_signal'         — analyzer couldn't decide cleanly (sparse data, etc.)
-- =====================================================================

alter table public.trade_outcomes
  add column if not exists postmortem jsonb;

alter table public.trade_outcomes
  add column if not exists postmortem_diagnosis text;

alter table public.trade_outcomes
  add column if not exists postmortem_ran_at timestamptz;

create index if not exists trade_outcomes_diag_idx
  on public.trade_outcomes(user_id, postmortem_diagnosis)
  where postmortem_diagnosis is not null;

comment on column public.trade_outcomes.postmortem is
  'Structured replay output: max favorable / max adverse excursion, optimal exit price+date, gave-back %, and a plain-English narrative.';
comment on column public.trade_outcomes.postmortem_diagnosis is
  'One-word diagnosis tag for fast filtering: optimal, held_too_long, exited_too_early, stop_too_tight, late_to_stop, no_signal.';
