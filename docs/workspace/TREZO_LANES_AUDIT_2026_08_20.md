# Trezo Lanes Audit — Stocks, Options, Futures
**2026-08-20 · data-first review, nothing changed** — same method as the crypto rung replay: read what actually happened, name the gate, propose options, decide from evidence.

## The day in numbers (entries opened today, per book)

| Book | Crypto | Stock | Options | Futures | Realized today |
|---|---|---|---|---|---|
| 75k (49acafdd) | 22 | **0** | 0 | 0 | +$2,221 (crypto) |
| 25k (6ce61054) | 20 | **0** | 0 | 0 | +$658 (crypto) |
| 5k (cf1b0460) | 12 | **13** | 0 | 0 | +$211 crypto, −$27 stock |

*Caveat: crypto realized totals include the in-app exits from the ledger/venue drift found earlier today — read the magnitudes, not the cents.*

So the question isn't "why so few" in general — it's three separate questions with three separate answers.

---

## Lane 1 — Stocks: the big books have no eyes

**Root cause (25k & 75k): no watchlist.** Watchlists exist for exactly two users — the 5k book (50 symbols) and the main login (64 symbols). The 25k and 75k books have **none**. The stock pipeline is watchlist-driven: `pattern_detection` scores watchlist symbols → `risk_manager` approves/vetoes → `trade_execution` fires. With zero symbols, those agents never wake: the big books logged **zero** pattern_detection and zero risk_manager messages all day, every day. When the 25k/75k books were seeded from the 5k, `bot_settings` were copied — the watchlist was not.

**The 5k's stock lane is alive but throttled.** Today: 6,630 hold decisions, **1,090 vetoes vs 172 approvals** (86% kill rate), 13 entries. The observed veto driver is *crowding*: with 11+ positions open the effective TCS bar rises (e.g., threshold 44 against signals scoring 37–40). Crypto occupies most of the 14 `max_open_positions` slots, so stock signals compete with crypto for slots — and usually lose. The −$27 on 13 trades also says the survivors were marginal.

## Lane 2 — Options: works until the last mile, then the venue says no

The wheel is enabled on all books (`wheel_auto_execute = true`) and the scanner runs daily (33–36 messages per book). Auto-fire is genuinely attempted — and blocked, audibly, in today's 11:21 batch:

- **5k:** `wheel_auto_blocked — "Alpaca options approval level…"` → the trezo_claudecowork paper account doesn't have options trading enabled at Alpaca. Every attempt blocks, cools down, falls back to a suggestion.
- **25k:** `wheel_auto_blocked — "No listed put contract near…"` ×5 → contract discovery finds no listed put near its target strike/DTE (`options_min_dte = 7`). Either the filters are too tight for these underlyings or the chain lookup runs thin.
- **75k:** same batch ends in "Suggestion:" messages (AGNC, BMY, CSCO, F, HPQ, INTC) — same blocked/cooldown class.

Nothing is broken in the decision chain; the venue-side account permission and the contract-selection tolerance stop the fire.

## Lane 3 — Futures: the lane doesn't exist yet, by design

There is no futures scanner agent, and `asset_policy.py` declares futures `venue="external"` — Alpaca offers no futures venue. The policy exists as scaffolding so the lane can switch on when a broker supports it. Zero trades here is correct behavior, not a defect. (Forex is in the identical state.)

## The 5k's "constant strategy transferring"

Only the 5k switches because only the 5k has a running pattern engine (see Lane 1). Today it changed strategy **16 times against 6,630 holds** (0.2%), friction mode `adaptive` at 15% advantage on every book. The pattern in the flips: `stms → extended` four times between 18:21–19:26 UTC (TCS 57–69), `→ orb` twice around 14:40 — two strategies trading the lead near the friction boundary, each flip re-crossed within the hour. Not runaway behavior, but boundary thrash worth a replay before touching the dial.

---

## Options on the table (decisions yours, nothing done)

**A. Give the big books eyes** — copy or curate a watchlist for 25k and 75k (one insert per book). Decision: mirror the 5k's 50 symbols, use the main account's 64, or curate per posture (the 25k is set to `growth`, the others `auto`).

**B. Un-throttle the 5k's stock lane** — candidates: reserve slots per asset class (e.g., 4 of 14 for stocks), raise `max_open_positions`, or trim crypto appetite on that book. **Replay first:** run the 1,090 vetoes back through each candidate rule and count what changes — same as the rung replay.

**C. Options last mile** — (1) enable options trading on the paper accounts in the Alpaca dashboard (an account setting, not code — likely minutes); (2) replay the "no listed contract" misses against real chains to see whether a wider DTE/strike tolerance would have found tradable contracts, before loosening anything.

**D. Futures/FX** — park until a broker with those venues is connected. No action.

**Suggested order:** C1 (a click), then A (after you pick symbols), then the B and C2 replays — all after Friday's clean ladder read, so this week's measurement stays one-variable.
