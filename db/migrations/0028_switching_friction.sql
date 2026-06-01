-- 0028 — Strategy switching friction (per-stock anti-whipsaw).
--
-- Background. The Strategy Engine picks the best strategy per stock
-- every Pattern Detection tick. When Mike lowers the TCS threshold
-- (more permissive), small score differences flip the pick. That is
-- the whipsaw he wants to prevent. This migration adds the two dials
-- that drive the switching-friction logic in pattern_detection.py.
--
-- switching_mode:
--   off       — every tick can flip (legacy behavior).
--   fixed     — new strategy needs score > prev * (1 + advantage/100).
--   adaptive  — advantage scales inversely with the TCS threshold.
--               At TCS 500 the floor is 16%; at TCS 800 it's 10%.
--               Lower TCS = noisier signals = bigger gap to flip.
--   tiered    — three explicit bands: TCS >= 700 needs 5%,
--               500-699 needs 10%, < 500 needs 20%.
--
-- switching_advantage_pct: the base advantage in fixed + adaptive
-- modes (default 10). Tiered mode ignores this field.

alter table bot_settings
  add column if not exists switching_mode text not null default 'adaptive',
  add column if not exists switching_advantage_pct int not null default 10;

alter table bot_settings
  drop constraint if exists bot_settings_switching_mode_chk;
alter table bot_settings
  add constraint bot_settings_switching_mode_chk
  check (switching_mode in ('off', 'fixed', 'adaptive', 'tiered'));

alter table bot_settings
  drop constraint if exists bot_settings_switching_advantage_pct_chk;
alter table bot_settings
  add constraint bot_settings_switching_advantage_pct_chk
  check (switching_advantage_pct between 0 and 50);

comment on column bot_settings.switching_mode is
  'Per-stock strategy switching friction mode: off / fixed / adaptive / tiered. See 0028 migration for the math.';
comment on column bot_settings.switching_advantage_pct is
  'Base advantage (%) the new strategy must beat the current pick by, before the Strategy Engine flips. Used in fixed + adaptive modes.';
