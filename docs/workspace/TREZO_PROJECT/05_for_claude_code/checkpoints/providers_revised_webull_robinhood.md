# Checkpoint — Provider list revised

Date: 2026-05-26

## What changed
- web/src/lib/broker-providers.ts
  - Brokerage: dropped Schwab. Added Webull and Robinhood. Final
    list — Alpaca Paper [available], Alpaca Live [planned],
    IBKR [planned], Webull [planned], Robinhood [planned].
  - Crypto: unchanged — Coinbase, Kraken, Gemini [all planned].
  - Banking: dropped MX and Yodlee. Plaid [planned] is now the only
    banking card.

## Honesty in the blurbs
Webull and Robinhood do not publish a public OAuth flow for retail
third-party trading apps right now. Trezo will not ship a
password-based or reverse-engineered path — the framework is OAuth-
only on purpose so the user's credentials never come through Trezo.
Those two cards stay parked until the providers open a partner OAuth
program, at which point they each become a one-row flip. Same for
Kraken and Gemini.

## Status of the OAuth registration friction
Even Alpaca Paper requires the user to register an OAuth app on the
provider side before the Connect button works. The smallest, most
achievable step is to register Alpaca Paper:
  1. https://app.alpaca.markets/oauth/apps → Create app
  2. Redirect URL = ${NEXT_PUBLIC_BASE_URL}/api/brokers/alpaca/callback
  3. Copy the client ID + secret
  4. Set on the web service:
       ALPACA_OAUTH_CLIENT_ID=...
       ALPACA_OAUTH_CLIENT_SECRET=...
       TREZO_TOKENS_KEY=$(openssl rand -hex 32)
       NEXT_PUBLIC_BASE_URL=https://your-trezo-url
  5. Restart the web service.
After that, the Connect button lights up and any user can sign in
through their own Alpaca account.

Everything else (IBKR, Coinbase) follows the same pattern; only the
URLs and env-var names differ.
