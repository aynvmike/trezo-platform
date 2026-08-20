# Checkpoint — Connections by category + Bot settings panel

Date: 2026-05-26

## What changed
- web/src/lib/broker-providers.ts (expanded)
  - Added `ProviderCategory` (brokerage / crypto / banking) and
    CATEGORY_LABEL / CATEGORY_BLURB maps.
  - Top 3 per category, 10 providers total:
      brokerage: Alpaca (Paper) [available], Alpaca Live [planned],
                  Interactive Brokers [planned], Charles Schwab [planned]
      crypto:    Coinbase [planned], Kraken [planned], Gemini [planned]
      banking:   Plaid [planned], MX [planned], Yodlee [planned]
    Each planned provider already has its OAuth URLs + scopes wired
    where they exist publicly — flipping to "available" is one env-var
    registration on the provider's developer portal.
  - New providersByCategory() helper.

- web/src/app/dashboard/settings/connections/page.tsx (rewritten)
  - Grouped sections by category with a short blurb each.
  - Shows the count + category headers.

- web/src/components/dashboard/bot-settings-panel.tsx (new)
  - Server widget on the Paper Trading page that reads the user's
    bot_settings row and shows EXACTLY what the bot is using right now:
    TCS, risk/trade, stop %, target %, max open, streak limit,
    autonomy, posture, plus four strategy on/off pills.
  - "Updated <timestamp>" line so the user can confirm the save
    landed in the DB.
  - beginner-only caption explains the agents' ~30s cache so a fresh
    save needs one tick to take effect.

- web/src/app/dashboard/paper/page.tsx — BotSettingsPanel rendered
  right after ScannerPulse.

## Why
Mike: "the trades are working but the settings do not change". The
BotSettingsPanel removes ambiguity — if the panel shows what you
saved, the save was good; the agents pick it up within ~30s. If it
doesn't, the save failed and you try again. The Scanner pulse above
shows the next tick's read against those settings.

## Open follow-up
- Register OAuth apps on each "planned" provider's developer portal,
  set the env vars below, flip status to "available":
    ALPACA_LIVE_OAUTH_CLIENT_ID / ALPACA_LIVE_OAUTH_CLIENT_SECRET
    IBKR_OAUTH_CLIENT_ID / IBKR_OAUTH_CLIENT_SECRET
    SCHWAB_OAUTH_CLIENT_ID / SCHWAB_OAUTH_CLIENT_SECRET
    COINBASE_OAUTH_CLIENT_ID / COINBASE_OAUTH_CLIENT_SECRET
  Plus the matching redirect URL on each provider:
    ${NEXT_PUBLIC_BASE_URL}/api/brokers/{key}/callback
- Wire the agents service to read per-user tokens from
  broker_connections (replaces the env ALPACA_API_KEY fallback for
  connected users).
