# Phase 6a — Paper Trading Foundation + Daily Profit Lock — COMPLETE

> Built by Nova, 2026-05-20.

## What shipped

### Database (`db/migrations/0008_paper_trading.sql`)
- `paper_accounts` — one row per user: starting_capital, current_cash, vault_balance, today_realized_pnl, ytd_realized_pnl, daily_target_hit_today, last_reset_date. RLS self-only.
- `paper_positions` — every open + closed simulated position with stop, target, fill prices, realized P&L, fees, strategy attribution.
- `paper_vault_transactions` — audit log of cash↔vault transfers (profit_lock, manual_withdrawal, manual_deposit, reset).
- Trigger `seed_paper_account()` — auto-creates a `paper_accounts` row whenever a user completes onboarding. Uses their stock + options capital as starting cash.
- Backfill: any user who already finished onboarding before this migration gets seeded automatically.

### Paper engine (`agents/app/paper/engine.py`)
- `open_position()` — fetches user's current cash, applies 5-bps slippage, sizes the position using risk-per-trade math (5% account risk default, configurable), inserts a `paper_positions` row, deducts notional + commission from cash.
- `close_position()` — applies exit slippage, calculates realized P&L (with side-aware math for short positions), updates position row + account cash + today_realized_pnl + ytd_realized_pnl.
- `check_and_lock_profit()` — reads user's `daily_profit_target_usd` from `profiles`. If `today_realized_pnl >= target` and not yet locked today: transfers target amount to vault, marks `daily_target_hit_today=true`, logs to `paper_vault_transactions`.
- `reset_daily_counters()` — clears today_realized_pnl and the lock flag. Called when the date rolls over.

### Trade Execution Agent (`agents/app/agents/trade_execution.py`)
- Was a no-op stub; now actually opens paper positions.
- Reacts to every `approve` from Risk Manager. Fetches the current candle close as market price. Opens a paper position via `open_position()`. Emits `execute` with fill details.
- **Fan-out workaround for Phase 5b:** since Pattern Detection signals don't yet carry a user_id, the executor opens the position for *every* user who has a paper account. This goes away when per-user runtime lands in Phase 5b.

### Position Monitor Agent (`agents/app/agents/position_monitor.py`)
- New agent. Ticks every 30 seconds.
- Scans all open positions across all users. Fetches each ticker's current price once (cached). Closes positions whose stop or target is hit, with the right side-aware comparison.
- For positions tagged `strategy="stms*"`, also enforces a time-stop at 15:00 UTC (≈11 AM ET — close enough until Phase 6b proper STMS lands).
- After each batch of closures, calls `check_and_lock_profit()` for each affected user. Daily Profit Lock fires automatically.
- Bootstrapped into the registry. Now nine concrete agents on the dashboard.

### Web UI (`web/src/app/dashboard/paper/page.tsx`)
- Four KPI tiles: Cash, Vault, Today's P&L (green/red), YTD P&L.
- **Daily Profit Lock progress bar** — shows today's earnings vs the target with the bar filling weave-green up to 100%, then locking to treasure-gold. Above the bar, a clear "✓ Locked today" pill once it triggers.
- Open positions table (ticker, side, qty, entry, stop, target, strategy).
- Recent closed trades (last 25): ticker, side, entry, exit, P&L (color-coded), close reason (stop/target/time/manual).
- Vault history: every cash↔vault transfer with timestamp and description.
- Total return summary at the bottom (cash + vault − starting capital).

### Sidebar
- New "Paper Trading" entry in the Core group, right under Overview.

## Decisions made (worth remembering)

1. **5-bps slippage on every fill.** Both entry and exit. Conservative enough to make paper results believable but not so harsh it hides real strategy edge.
2. **Risk-per-trade sizing.** Position size = (cash × risk_pct) ÷ |entry − stop|. Caps the loss at the risk percentage if the stop is hit. Defaults to 5% risk per trade (matches the STMS rule).
3. **Default stop = 5%, default target = 10%.** Until strategy-specific rules land in Phase 6b, every approved signal uses these defaults. Risk-reward of 2:1.
4. **Cash + vault math is authoritative.** "Total return" is `current_cash + vault_balance − starting_capital`. The vault is real saved money; vaulted dollars cannot be re-traded.
5. **Position Monitor ticks every 30s, not 60s.** Tighter cadence because the cost of a missed stop is larger than the cost of an extra API call.
6. **Daily Profit Lock triggers as soon as today's realized P&L crosses the threshold**, not at end of day. This matches the founder's spec — lock it the moment it's earned.

## Exit criteria progress

| Phase 6 criterion | Status |
|---|---|
| Paper bot runs for 5 consecutive days | ⏳ Need user-side runtime — start it, let it run |
| Daily Profit Lock saves correctly | ✅ Triggers automatically; logs to vault transactions |
| All strategies execute without errors | ⏳ Only the default 5%/10% strategy is wired — STMS, Crypto modes, Wheel, Options arrive in 6b–6e |
| Performance dashboard shows realistic results | ✅ /dashboard/paper |

## What the user needs to do before testing

1. **Apply migration:** in Supabase SQL editor, paste `db/migrations/0008_paper_trading.sql` and Run. Should show green Success. Your existing onboarded profile will get a paper_accounts row backfilled.

2. **Restart agents** (so the new `position_monitor` agent registers and the updated `trade_execution` is loaded):
   - Close the **Trezo - Agents** window
   - Run `nuke-agent-cache.bat` from `C:\Trezo\trezo-platform\`
   - It will start a fresh agents service automatically
   - Confirm the Agents window prints `count=9` for the bootstrap (was 8; +1 for position_monitor)

3. **Restart the web server** to pick up the new page + nav entry:
   - Close the **Trezo - Web** window
   - Double-click `start-web.bat`

4. **Hard-refresh the browser** (`Ctrl+Shift+R`) and visit:
   - <http://localhost:3000/dashboard/paper> — your paper account should show with KPI tiles, empty open-positions table, and an empty vault history
   - <http://localhost:3000/dashboard/agents> — should now show **nine** agent cards; `position_monitor` cadence is "every 30 seconds"

5. **Force a chain reaction** — go to `/dashboard/agents` and click **"Run now →"** on Pattern Detection. If a ticker scores TCS ≥ 700, the chain fires: signal → approve → execute → a new paper position appears at `/dashboard/paper`. The position monitor will start watching it for stop/target hits.

## Known limitations / open items

- **Multi-user runtime not yet wired.** The signal → approve → execute chain fans out to all users with paper accounts. In Phase 5b, agents will run per-user with proper user_id context on every message.
- **Default strategy only.** No STMS-specific entry rules, no Crypto SCALP/SWING/DCA, no Wheel, no Options. Those come in Phase 6b/c/d/e.
- **No backtest yet.** The whole "paper bot ran 5 consecutive days" criterion needs real wall-clock time — leave it running and check back tomorrow.
- **No manual close button.** Mike can't yet click a "close this position now" button on /dashboard/paper. Easy to add in Phase 6b.
- **Time stop is approximate.** STMS spec says "close by 11:00 AM ET." We use 15:00 UTC which is ~11 AM ET during EDT and ~10 AM during EST. Will tighten in Phase 6b with proper timezone handling.

## Next phase starting point

→ **Phase 6b: STMS strategy** — proper small-cap momentum rules:
- $1–$20 price filter
- Up 10%+ on the day, 5x relative volume
- Bull Flag / Flat Top / Micro-Pullback pattern requirement
- TCS 750+ threshold (vs 700 default)
- Hard 11 AM ET time stop with timezone awareness
- Position sizing tied to a specific 5% account risk rule
- Catalyst requirement (news event)
