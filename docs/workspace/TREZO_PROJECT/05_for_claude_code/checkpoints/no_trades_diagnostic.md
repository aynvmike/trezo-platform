# Checkpoint — Why no paper trades + fix

Date: 2026-05-26

## The bug
Pattern Detection — the agent that scans the user's watchlist for
trade signals — had a hardcoded `signal_threshold = 700` and ignored
the TCS threshold in Bot Tuning. So even when the user dialed Signal
TCS down in Bot Tuning, the live scanner still required TCS ≥ 700 to
fire. Combine with a flat market and zero signals get through →
zero paper trades.

## The fix
- agents/app/agents/pattern_detection.py
  - Reads `bot_settings.tcs_threshold` per user per tick. Falls back
    to 700 if no row is set yet.
  - At the end of every tick, emits one info message per user with a
    scan summary: tickers scanned, signals emitted, max TCS observed
    (with the ticker and direction that produced it), and the
    threshold in force.
- web/src/components/dashboard/scanner-pulse.tsx (new)
  - Server component on the Paper Trading page that surfaces the
    latest scan summary in plain words: "Scanned 14 tickers at TCS
    700; strongest read was AMD at 612 (bullish) — below threshold,
    nothing fired." When the scanner has not been heard from at all,
    explicitly says "agents service may not be running".
  - Suggests a sensible lower threshold when the strongest read is
    below the current threshold.
- web/src/app/dashboard/paper/page.tsx — ScannerPulse rendered just
  above AccountSizeSim, so it is the first thing the user sees.

## How the user diagnoses now
Open Paper Trading. ScannerPulse tells them, in one sentence, why
trades did or did not fire. Lower the TCS in Bot Tuning and the very
next tick reflects the change.

## Worth checking next if trades still don't fire
The chain is signal → approve → execute. The fix above unblocks
signal. If signals fire and trades still do not, look at:
  - Risk Manager vetoes (agent_messages kind="veto" for this user).
  - Trade Execution errors (kind="error" from trade_execution).
  - Allocation gate (market-type budget used up).
