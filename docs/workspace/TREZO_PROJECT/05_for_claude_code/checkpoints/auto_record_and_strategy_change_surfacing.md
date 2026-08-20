# Auto-record Wheel placements + Strategy Engine change surfacing

Three pieces of work landed in this batch:

## 1. Auto-record placed Wheel legs into `options_positions`

When you click **Place CSP** or **Place CC** on the Wheel page, the
order now does two things instead of one:

1. Lands a real sell-to-open on Alpaca paper (per-user OAuth, env-key
   fallback) — same as before.
2. **New:** inserts a row into Trezo's own `options_positions` table
   so the modeled Wheel planner stays coherent with what was actually
   placed.

The button now shows a third state: `✓ Placed · accepted · logged`
when both the order and the local record landed, or `✓ Placed ·
accepted · log failed` if Alpaca took the order but Trezo could not
write the row (rare; usually only if the table is missing). Hover
the badge for the OCC, Alpaca order id, and any record-error reason.

Files touched:
- `web/src/app/api/wheel/place-leg/route.ts` — inserts into
  `options_positions` after a successful agents reply.
- `web/src/components/dashboard/wheel-place-button.tsx` — surfaces
  `recorded` / `record_error` in the post-place badge.

The insert maps:

| options_positions column | source                                 |
| ------------------------ | -------------------------------------- |
| underlying               | response.underlying                    |
| strategy                 | "wheel_csp" or "wheel_cc"              |
| direction                | "income"                               |
| option_type              | "put" (csp) / "call" (cc)              |
| strike, expiration       | real listed contract from Alpaca       |
| contracts                | what you clicked (default 1, max 50)   |
| net_premium_usd          | premium × 100 × contracts (positive = credit) |
| status                   | "open"                                 |
| notes                    | Alpaca order id + status + OCC + routed |

Nothing about the old modeled planner changed — the new row just
sits alongside the modeled ones so the page stays consistent.

## 2. Strategy Engine change events on the dashboard

The per-stock strategy selector picks the best strategy for each
ticker every 60s. Until now, when the pick flipped between ticks
(e.g. AMD switches from `pattern` to `orb` because the ORB window
opened) it lived buried in the activity feed.

Now Pattern Detection:

- Remembers the previous chosen strategy per `(user, ticker)`.
- When the pick flips, emits a discrete `strategy_change` agent
  message AND folds the switch into the next scan summary's
  `strategy_changes` array.
- The Scanner Pulse widget on Paper / dashboard pages renders the
  switches as chips: `AMD pattern → orb`, `INTC default → stms`,
  etc. The card shows up only on ticks where a flip happened, with a
  short beginner-mode paragraph explaining what the chips mean.

Files touched:
- `agents/app/agents/pattern_detection.py` — `_prev_strategy` map +
  emit + summary fields `strategy_changes` and `strategy_change_count`.
- `web/src/components/dashboard/scanner-pulse.tsx` — chip row with
  beginner-mode explanation.

## 3. Test-run-of-today checkpoint

Companion file `test_run_today_market.md` walks through the full
test path in 10 minutes — connection → markets read → broad scan →
sim → live Wheel placement → sanity check. Use it the next time you
want to put today's tape through the bot end-to-end.

## Status: ready to test

All three pieces compile (Python `ast.parse` + Next.js TS shapes
checked). Nothing requires a fresh migration — `options_positions`
has been in place since migration 0012.
