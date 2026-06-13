-- 0043: auto_exit_advisor toggle (renumbered from 0039 — collision with 0039_options_user_filters) (2026-06-12)
-- Task #92 wired the Exit Advisor to auto-close/trim on peak-giveback
-- when bot_settings.auto_exit_advisor is ON -- but this column was
-- never created, so getattr() always defaulted to False and the
-- feature could never arm. Found during the GM post-mortem.
ALTER TABLE bot_settings
  ADD COLUMN IF NOT EXISTS auto_exit_advisor boolean NOT NULL DEFAULT false;
