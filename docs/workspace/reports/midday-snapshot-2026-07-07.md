# Trezo Midday Snapshot — Tuesday, July 7, 2026 (~12:10 PM ET)

## Market clock
🟢 Open. Normal session 9:30 AM – 4:00 PM ET, no holidays or early closes this week.

## Account health (Alpaca paper)
- Status: ACTIVE — no trading, account, or transfer blocks.
- Equity: $3,791.54 | Cash: $3,791.54 | Buying power: $15,166 | Options buying power: $3,791.
- Options approval: Level 3. Day-trade count: not reported by Alpaca today.
- Buying power is NOT the problem today — the account has room.
- Note: equity is down ~$1,044 vs yesterday's close. That is the leftover mark of the overnight Alpaca paper-account wipe (positions vanished, cash stayed intact) — it is NOT today's trading losses.

## Today's orders & fills
- Broker order log: **0 orders** — nothing filled, nothing pending, nothing canceled.
- But the engine DID try. 9 submissions were rejected at Alpaca's door (HTTP rejects never create order records):
  - 9:30 AM — SOXS: take-profit price rounded into the entry price (bracket formatting).
  - 9:36 AM — SOXS and TZA: order sized too big for the account ("insufficient buying power" — sizing used stale/pre-wipe equity).
  - 11:33–11:55 AM — CSCO (x5) and PYPL (x1): take-profit and stop-loss prices on the wrong sides of each other (a second bracket-formatting variant, on short-side orders).

## Open positions
- Alpaca shows **zero positions** — stocks and options both. The 3 wheel CSPs (F, HPQ) and all stock holdings from yesterday are gone (overnight wipe; ghosts were reconciled ~10:11 AM).
- Engine agrees the wheel lane has $0 collateral reserved — so books match on that.
- Watch item: the engine still carries session markers for CSCO / BITO / OPEN / INTC ("already approved") that no longer correspond to any broker position. Harmless dedup logic, but worth confirming the paper book shows them closed.

## Today's P&L
- Realized today: ~$0 (no fills, no activities at the broker).
- Unrealized: n/a (no open positions).
- The -$1,044 vs yesterday's close is the wipe artifact described above, not P&L from trading.

## Why so quiet? (one line)
Order rejects — bracket-price formatting bugs tripped the session kill-switch (3-reject rule), so approvals stopped converting into orders; it is not buying power, PDT, or market conditions.

## Scan / gate detail (activity ledger)
- 4,498 ledger events today; engine has been scanning continuously since midnight and is still alive (last event 12:10 PM ET).
- **27 approvals** (SOXS pattern repeatedly pre-open, CSCO/PYPL pattern late morning, AUDUSD/USDCAD forex swings — the 2 forex ones filled as modeled paper trades).
- **4,186 vetoes.** Top reasons: kill-switch active (2,338 — throttling clearly not fully in effect yet), neutral direction/no bias (635), session stacking skips for CSCO/BITO/OPEN/INTC (~1,032 combined), thin-liquidity pattern candidates (~35), wheel CSPs skipped by the 50%-of-equity collateral cap (76 — at $3.8k equity, normal CSPs don't fit).
- Cross-check flag: approvals ARE happening but NONE became broker fills — every real submission was rejected. The kill-switch re-engaged after the 11:55 AM CSCO reject and was still vetoing at 12:06 PM.

## Verdict
The bot is in state (c) — running but effectively unable to trade stocks today. The scanners, approvals, and forex/crypto modeled lanes are healthy, but every real Alpaca submission was rejected by two bracket-price bugs plus one oversizing, and the session kill-switch is now (correctly) holding everything back. The fixes for exactly these bugs (bracket clamps + notional cap) were already coded this morning but the agents haven't been restarted, so they aren't loaded yet.

**Next action (after 4:00 PM ET close, per the no-changes-during-market-hours rule):** [PowerShell] `Restart-ScheduledTask -TaskName "TrezoAgents"` — this loads the bracket-clamp and sizing fixes and resets the session kill-switch for tomorrow. Leaving the kill-switch alone until then is correct; clearing it now would just generate more rejects.
