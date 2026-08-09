-- 0045: owner / account split (2026-08-09, multi-account)
-- Every table keyed on user_id, which quietly meant two different things:
-- the PERSON, and the BOOK of positions. That held while each person had
-- exactly one account. It breaks the moment someone holds several --
-- individual, IRA, joint, or three paper books under one broker login.
-- A person's children are not a trading account's children; a person's
-- bank details are not an account's bank details. Keyed to a book, those
-- records orphan the moment the book closes.
--   owner_id            - the PERSON (profile, children, payment details)
--   funding_account_key - the BOOK a KINDRIP contribution is paid FROM
--   trading_accounts    - which books exist and who owns them. Credentials
--                         stay in agents/.env and are NEVER stored here.
-- ADDITIVE ONLY: nothing dropped or renamed, every new column backfilled
-- from user_id. The agent code reads the new columns when present and
-- falls back to user_id when absent, so it is correct before AND after.
-- Safe to re-run. APPLIED to trezo-dev 2026-08-09.

-- 1. KINDRIP children belong to a PERSON, funded FROM a book
ALTER TABLE kindrip_children
  ADD COLUMN IF NOT EXISTS owner_id uuid,
  ADD COLUMN IF NOT EXISTS funding_account_key uuid;

UPDATE kindrip_children SET owner_id            = user_id WHERE owner_id IS NULL;
UPDATE kindrip_children SET funding_account_key = user_id WHERE funding_account_key IS NULL;

CREATE INDEX IF NOT EXISTS kindrip_children_owner_idx ON kindrip_children (owner_id);

-- 2. Payment details belong to a PERSON
ALTER TABLE payment_instructions
  ADD COLUMN IF NOT EXISTS owner_id uuid;

UPDATE payment_instructions SET owner_id = user_id WHERE owner_id IS NULL;

-- 3. The account directory
CREATE TABLE IF NOT EXISTS trading_accounts (
  account_key uuid PRIMARY KEY,
  owner_id    uuid NOT NULL,
  label       text,
  broker      text    NOT NULL DEFAULT 'alpaca',
  is_paper    boolean NOT NULL DEFAULT true,
  is_active   boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS trading_accounts_owner_idx ON trading_accounts (owner_id);

-- 4. Register the three paper books under one owner. The account_key
-- values must match TREZO_ACCOUNT_USER_ID_2/_3 in agents/.env.
INSERT INTO trading_accounts (account_key, owner_id, label, broker, is_paper) VALUES
  ('cf1b0460-039d-40ac-adc8-7ca3ef17c5bb','cf1b0460-039d-40ac-adc8-7ca3ef17c5bb','trezo_claudecowork (primary)','alpaca',true),
  ('6ce61054-7ffd-41b5-80c3-1cd0220c79eb','cf1b0460-039d-40ac-adc8-7ca3ef17c5bb','Trezo Inc. 3 - 25k','alpaca',true),
  ('49acafdd-1c86-4740-a1b1-f94aa7abce08','cf1b0460-039d-40ac-adc8-7ca3ef17c5bb','Trezo Inc. 2 - 75k','alpaca',true)
ON CONFLICT (account_key) DO NOTHING;
