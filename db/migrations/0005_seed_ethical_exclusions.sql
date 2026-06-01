-- =====================================================================
-- Trezo — Seed: ethical exclusions
--
-- These are user-toggleable categories (tier 4) preloaded so the filter
-- works on day one. Tier 1-3 default exclusions (SAM.gov / OFAC / SEC)
-- are populated by a daily sync job — Phase 5+. For now we seed a
-- representative set so the filter is functional.
-- =====================================================================

-- ---- Weapons manufacturers (user-toggleable) ----
insert into public.ethical_exclusions (ticker, category, tier, source, evidence) values
  ('LMT', 'weapons', 4, 'static-list', 'Lockheed Martin — major defense contractor'),
  ('RTX', 'weapons', 4, 'static-list', 'RTX Corp (Raytheon) — defense contractor'),
  ('NOC', 'weapons', 4, 'static-list', 'Northrop Grumman — defense contractor'),
  ('GD',  'weapons', 4, 'static-list', 'General Dynamics — defense contractor'),
  ('LHX', 'weapons', 4, 'static-list', 'L3Harris Technologies — defense contractor'),
  ('HII', 'weapons', 4, 'static-list', 'Huntington Ingalls — naval defense'),
  ('TXT', 'weapons', 4, 'static-list', 'Textron — defense systems'),
  ('BA',  'weapons', 4, 'static-list', 'Boeing — defense + commercial aerospace')
on conflict (ticker, category) do nothing;

-- ---- Tobacco (user-toggleable) ----
insert into public.ethical_exclusions (ticker, category, tier, source, evidence) values
  ('MO',  'tobacco', 4, 'static-list', 'Altria Group — Marlboro parent'),
  ('PM',  'tobacco', 4, 'static-list', 'Philip Morris International'),
  ('BTI', 'tobacco', 4, 'static-list', 'British American Tobacco'),
  ('IMBBY', 'tobacco', 4, 'static-list', 'Imperial Brands')
on conflict (ticker, category) do nothing;

-- ---- Fossil fuel majors (user-toggleable) ----
insert into public.ethical_exclusions (ticker, category, tier, source, evidence) values
  ('XOM', 'fossil_fuels', 4, 'static-list', 'ExxonMobil — integrated oil & gas'),
  ('CVX', 'fossil_fuels', 4, 'static-list', 'Chevron — integrated oil & gas'),
  ('SHEL', 'fossil_fuels', 4, 'static-list', 'Shell plc'),
  ('BP',  'fossil_fuels', 4, 'static-list', 'BP plc'),
  ('TTE', 'fossil_fuels', 4, 'static-list', 'TotalEnergies'),
  ('COP', 'fossil_fuels', 4, 'static-list', 'ConocoPhillips'),
  ('OXY', 'fossil_fuels', 4, 'static-list', 'Occidental Petroleum'),
  ('EOG', 'fossil_fuels', 4, 'static-list', 'EOG Resources')
on conflict (ticker, category) do nothing;

-- ---- Private prisons (user-toggleable) ----
insert into public.ethical_exclusions (ticker, category, tier, source, evidence) values
  ('GEO', 'private_prisons', 4, 'static-list', 'GEO Group — private corrections operator'),
  ('CXW', 'private_prisons', 4, 'static-list', 'CoreCivic — private corrections operator')
on conflict (ticker, category) do nothing;

-- ---- Gambling (user-toggleable; founder default OFF) ----
insert into public.ethical_exclusions (ticker, category, tier, source, evidence) values
  ('CZR', 'gambling', 4, 'static-list', 'Caesars Entertainment'),
  ('MGM', 'gambling', 4, 'static-list', 'MGM Resorts'),
  ('DKNG', 'gambling', 4, 'static-list', 'DraftKings'),
  ('PENN', 'gambling', 4, 'static-list', 'Penn Entertainment'),
  ('LVS', 'gambling', 4, 'static-list', 'Las Vegas Sands'),
  ('WYNN', 'gambling', 4, 'static-list', 'Wynn Resorts')
on conflict (ticker, category) do nothing;

-- ---- Adult entertainment (user-toggleable) ----
-- (no major public tickers — placeholder rows kept out)

-- ---- Cannabis (user-toggleable) ----
insert into public.ethical_exclusions (ticker, category, tier, source, evidence) values
  ('TLRY', 'cannabis', 4, 'static-list', 'Tilray Brands'),
  ('CGC',  'cannabis', 4, 'static-list', 'Canopy Growth'),
  ('CRON', 'cannabis', 4, 'static-list', 'Cronos Group'),
  ('ACB',  'cannabis', 4, 'static-list', 'Aurora Cannabis')
on conflict (ticker, category) do nothing;

-- ---- Crypto mining (user-toggleable, energy concerns) ----
insert into public.ethical_exclusions (ticker, category, tier, source, evidence) values
  ('RIOT', 'crypto_mining', 4, 'static-list', 'Riot Platforms — bitcoin mining'),
  ('MARA', 'crypto_mining', 4, 'static-list', 'Marathon Digital — bitcoin mining'),
  ('CLSK', 'crypto_mining', 4, 'static-list', 'CleanSpark — bitcoin mining'),
  ('HUT',  'crypto_mining', 4, 'static-list', 'Hut 8 — bitcoin mining'),
  ('CIFR', 'crypto_mining', 4, 'static-list', 'Cipher Mining')
on conflict (ticker, category) do nothing;
