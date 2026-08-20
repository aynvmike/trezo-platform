# Test-run today's market — 10 minute walkthrough

You finished a stack of new wiring this week. This is the dead-simple
order to put it through a live market session, top to bottom, in one
sitting. Nothing here costs real money — Alpaca is on the paper
account. Everything you click here will write a real row somewhere
Trezo can read back.

Open one browser tab on http://localhost:3000/dashboard and one on
http://localhost:8001/docs (the agents API page — used twice as a
fallback). Make sure both services and your Supabase project are up.

---

## Step 1 — Confirm the broker connection (30 sec)

1. Open **Settings → Brokers & banks**.
2. Look at the Alpaca row: it should say **Connected · paper** with
   your account ID. If it doesn't, click **Connect** and walk through
   the OAuth screen once.
3. The same screen now shows the green dot next to Alpaca paper. If
   you see it, every action below routes through that connection
   (per-user OAuth, no env-key leak).

If anything looks off, open `web/.env.local` and confirm:
- `ALPACA_OAUTH_CLIENT_ID`
- `ALPACA_OAUTH_CLIENT_SECRET`
- `ALPACA_OAUTH_REDIRECT_URI` (matches what's set in the Alpaca dev
  portal)
- `TREZO_TOKENS_KEY` (32-byte hex — the encryption key)
- `AGENTS_SHARED_SECRET` (matches `agents/.env` value)

---

## Step 2 — Check the cross-asset market read (1 min)

1. Open **Dashboard → Markets**.
2. Look at the **Market Horizons** card. Six asset tiles — SPY, BTC,
   GLD, UUP, TLT, JEPI. Each one shows today's percent move and the
   short prose read.
3. The **Cross-asset read** panel underneath tells you whether stocks,
   bonds, the dollar, gold and crypto are pulling in the same
   direction or pulling apart.
4. Read the one-line **net stance** at the top. That's the bot's
   single sentence about what today looks like before it places
   anything.

This is the Phase-9 "Market Horizons" piece — it should now feed every
agent the same cross-asset context so a bond-rally day doesn't get
treated like an equity rip.

---

## Step 3 — Run the broad scanner (2 min)

1. Open **Dashboard → Pattern Detection**.
2. Confirm the **Scan universe** caption shows
   `watchlist + market-wide candidates` and a number like
   `~50 symbols scanned`.
3. The TCS threshold slider — leave it at whatever your bot setting
   has it on (default 700, lowered to 650 for paper exploration is
   fine for this run).
4. Click **Run scan now**. Wait 5–10 seconds.
5. The **Scan summary** ribbon should fill in. Two numbers matter:
   - **from_watchlist** — how many of the 14-ish watchlist names
     scored above the threshold.
   - **from_market_wide** — how many of the broader gainers/losers
     and sector ETFs scored.

If either number is zero, lower the TCS to 600 and run again. The
shape you're checking for: the watchlist is no longer the universe.
Some watchlist names will score; some market-wide names will too.

---

## Step 4 — Simulation Lab against today's tape (3 min)

1. Open **Dashboard → Simulation Lab**.
2. Pick **Watchlist: Core Winners** (your default) — Sim Lab will
   internally expand to the market-wide pool the same way Pattern
   Detection does.
3. **Lookback**: 5 days.
4. **Starting equity**: $5,000.
5. **Signal TCS**: 650.
6. **Stop**: 2%. **Target**: 4%.
7. **Compare all strategies**: ON.
8. Click **Run simulation**.

What to read in the results:

- The **per-strategy** rows give you the average TCS of the trades
  each strategy fired this week, side by side.
- The **per-symbol** table shows you which name traded under which
  strategy — that's the per-stock pick-the-best-strategy rule
  working.
- The **Net P&L** column at the bottom of each per-strategy block is
  your reference number for the real run.

---

## Step 5 — Place one Wheel leg on Alpaca paper (2 min)

1. Open **Dashboard → Wheel**.
2. Scroll to the **Live pricing** table.
3. Pick the lowest-priced underlying you actually hold 100 shares of
   (or any name for a CSP — the cash gets reserved on Alpaca paper).
4. In the row's premium cell, click **Place CSP** (or **Place CC** if
   you hold the shares).
5. The button switches to **Confirm**. Click it.
6. After ~5 seconds you should see **✓ Placed · accepted · logged**.
   - `accepted` = Alpaca took the order.
   - `logged` = Trezo wrote a row into `options_positions` so the
     planner stays coherent with the broker.
7. Below the table, the **Wheel live positions** panel refreshes — the
   new leg should show up there pulled fresh from Alpaca.
8. The **Wheel planner** cards above it should now show one more open
   leg in the count.

If you get **✗ Failed** instead, hover the badge — the tooltip carries
the Alpaca rejection reason verbatim (most common: market closed,
options approval level too low, no buying power, contract not
found).

---

## Step 6 — Sanity check (1 min)

1. Open **Dashboard → Paper trading**.
2. The KPI tiles (Equity, Cash, Buying Power) should match the Alpaca
   account snapshot at the top of the page — they read from one
   shared fetch now so they cannot disagree.
3. Open **Settings → Profile**. The **Capital available** number
   should mirror the live broker, with the percent / dollar slider
   showing how much the bot is allowed to actually deploy.
4. Open **Agents** page. All 17 agents should show **active** with
   recent heartbeat. Pattern Detection's last-tick line should
   reference the broader pool.

---

## What this test exercises end-to-end

| Layer / piece           | Action above           | Exercises                          |
| ----------------------- | ---------------------- | ---------------------------------- |
| Brokers framework       | Step 1                 | OAuth + per-user token             |
| Markets Horizons        | Step 2                 | Cross-asset awareness              |
| Pattern Detection       | Step 3                 | Watchlist + market-wide pool       |
| Strategy selector       | Step 4                 | Per-stock best-strategy            |
| Simulation Lab          | Step 4                 | compare_all + TCS-per-strategy     |
| Wheel CSP/CC placement  | Step 5                 | Real Alpaca order + planner log    |
| Capital / equity sync   | Step 6                 | Single-fetch parity                |
| All 17 agents           | Step 6                 | Bus/scheduler health               |

You can run this every morning the same way. The whole thing takes
under 10 minutes once the muscles are built.

---

## If something stalls

- **Agents service unreachable** — start it: `cd agents && uv run uvicorn app.main:app --port 8001`.
- **Web app build errors** — `cd web && pnpm dev`.
- **Supabase auth blank** — re-sign in; the session cookie expires after a week.
- **Alpaca says "trading_blocked"** — Alpaca's paper account flips that on Sundays / holidays; check the **clock** card on the Markets page.
- **A button stays stuck on "Placing…"** — the 20-second timeout
  hasn't fired yet; if it goes longer, refresh the page (your
  placement already went through if Alpaca accepted it).
