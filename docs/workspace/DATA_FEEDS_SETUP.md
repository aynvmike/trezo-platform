# Trezo — Data Feeds Setup

Trezo pulls live information from a handful of outside services — prices,
news, the database, the AI. Each one needs a "key" (think of it as a
username + password Trezo uses to connect). This guide explains every
feed in plain language: what it powers, whether it costs anything, how
to get the key, and where to paste it.

You do not need to be technical. Each feed is: sign up on a website,
copy two values, paste them into a settings file. That's it.

---

## How the settings files work

Real keys live in three hidden files. They are NOT committed to GitHub —
that's deliberate, so your keys stay private:

- `trezo-platform/agents/.env`   — the trading agents (the brain)
- `trezo-platform/web/.env.local` — the website you log into
- `trezo-platform/api/.env`       — the API gateway

There is a template, `trezo-platform/.env.example`, that lists every
setting with a fake placeholder value. The simplest way to start:
copy `.env.example` into each of the three locations above, rename the
copy to `.env` (or `.env.local` for the web one), and then replace the
placeholders with your real keys.

A line in these files looks like:

    FINNHUB_API_KEY=your_finnhub_key

You replace everything after the `=` with the real value. No quotes, no
spaces. Save the file. After changing any of them, restart Trezo
(`start-all.bat`) so the new values are picked up.

---

## The feeds

### 1. Supabase — the database & login   (REQUIRED · free tier)

Powers: every account, every saved setting, the whole database. Trezo
will not run without it.

Get it: go to supabase.com, create a free account, create a new
project. In the project, open Settings -> API. You will see the Project
URL, the `anon` public key, and the `service_role` secret key. Settings
-> API also has the JWT secret; Settings -> Database has the connection
string.

Keys and where they go:
- `NEXT_PUBLIC_SUPABASE_URL` — web/.env.local + agents/.env + api/.env
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` — web/.env.local
- `SUPABASE_SERVICE_ROLE_KEY` — agents/.env + api/.env (never the web)
- `SUPABASE_JWT_SECRET` — api/.env
- `DATABASE_URL` — api/.env

### 2. Alpaca — stock prices & paper trading   (REQUIRED for stocks · free)

Powers: stock quotes, daily price history, the morning "top movers"
list, and the paper-trading account. Used by the Stock Bot, Extended
Strategy, Options Engine, Pattern Engine and backtests.

Get it: go to alpaca.markets and create a free account. You want the
PAPER trading keys (simulated money — exactly what Trezo uses). In the
dashboard, switch to "Paper" and generate an API key. You get a Key ID
and a Secret Key.

Keys and where they go:
- `ALPACA_API_KEY` — agents/.env
- `ALPACA_SECRET_KEY` — agents/.env
- (`ALPACA_LIVE_API_KEY` / `ALPACA_LIVE_SECRET_KEY` — leave blank;
  those are for real-money mode, which stays off until the
  GO_LIVE_CHECKLIST is complete.)

### 3. CoinGecko — crypto prices   (REQUIRED for crypto · free, NO key)

Powers: XRP / ETH / SOL / BTC prices and history for the Crypto Bot and
crypto backtests.

Get it: nothing to do. CoinGecko's public endpoints need no key and no
sign-up. It already works.

### 4. Finnhub — company news & fundamentals   (recommended · free tier)

Powers: company news (the catalyst checks and Market Sentiment),
share-count data (the small-float filter), and the ex-dividend calendar.
Trezo still runs without it — those features just degrade quietly — but
it is worth having.

Get it: go to finnhub.io, create a free account. The dashboard shows
your API key immediately.

Key and where it goes:
- `FINNHUB_API_KEY` — agents/.env + web/.env.local

### 5. Anthropic — the AI   (recommended · pay-as-you-go, low cost)

Powers: the LLM market-sentiment reading, the Budget Mirror receipt /
PDF scanning, and the "Ask Trezo" help chat.

Get it: go to console.anthropic.com, create an account, add a small
amount of credit (pay-as-you-go — the usage here is light and cheap),
and create an API key. Trezo uses the fast, low-cost Haiku model.

Key and where it goes:
- `ANTHROPIC_API_KEY` — agents/.env + web/.env.local

### 6. Upstash Redis — speed cache   (optional · free tier)

Powers: a small cache so repeated price lookups are fast and the free
data tiers are not hammered. Trezo runs fine without it; it just makes
things snappier.

Get it: go to upstash.com, create a free account, create a Redis
database. The database page shows a REST URL and a REST token.

Keys and where they go:
- `UPSTASH_REDIS_REST_URL` — web/.env.local + agents/.env
- `UPSTASH_REDIS_REST_TOKEN` — web/.env.local + agents/.env

### yfinance — backup stock data   (automatic · no key, no setup)

Not a feed you sign up for. If Alpaca is ever unreachable, Trezo falls
back to yfinance automatically. Nothing to configure.

---

## The minimum to get running

To bring Trezo up at all you need **Supabase** (#1). To make the trading
layers work you need **Alpaca** (#2); crypto (#3) needs nothing. Add
**Finnhub** (#4) and **Anthropic** (#5) to light up news, sentiment,
receipt scanning and the help chat. **Upstash** (#6) is a nice-to-have.

A practical order: Supabase first, then Alpaca, then Finnhub and
Anthropic, then Upstash if you want it.

---

## After you add or change a key

1. Save the `.env` / `.env.local` file (plain text, no quotes).
2. Restart Trezo with `start-all.bat`.
3. The agents and the website pick up the new values on restart.

If a feed's key is missing or wrong, Trezo does not crash — that feed
simply returns nothing and the features depending on it stay quiet.
That is by design, so a single missing key never takes the whole
platform down.

_General setup information for the Trezo build. Keep your real keys
private — they belong only in the git-ignored .env files, never in
.env.example or anywhere committed to GitHub._
