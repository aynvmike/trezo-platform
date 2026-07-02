# Trezo Trading Philosophy — Mike's Playbook (codified 2026-07-02)

The founder's lived trading logic, written down so every agent, formula, and
future feature can be checked against it. Mechanical pieces are enforced in
code (cap-tier formulas, ATR-realistic targets, profit stepping, net-edge
gates); judgment pieces are seeded into the agents' Mem0 brain
(agent="mike_playbook").

## The account-size playbook

- **Under ~$25k: income first.** Quick-turnaround trades (scalps, momentum,
  small-cap movers) grind the account up. Capital waiting weeks in a position
  is capital not compounding.
- **As equity grows, the SAME quick-turnaround thinking scales** — bigger
  notional on stable, expensive names. A $10-15k position in a mega-cap
  (BRK.B-class) needs ~1% to pay $100-150. Take it, exit, repeat. 2% is a
  bonus, never the plan.
- **The strategy doesn't change with the price of the stock** — a setup on a
  $30 name is the same setup on a $700 name; only share count differs.

## Realistic moves beat defined wins

- On an idle tape a big defined target is **waiting money**: the position
  barcodes between green and red and never fills. Targets must fit what the
  name ACTUALLY moves — the engine caps targets near 1.5x the 14-day ATR
  (TREZO_TARGET_ATR_MULT).
- **Quick profit stepping**: once a trade covers ~60% of its run to target,
  bank half and trail the rest (TREZO_PROFIT_STEP_AT / _FRACTION). Never
  round-trip a green trade to red.

## What the simulation said (2026-07-02, ~7.5 months daily bars, $10k/trade, 5bps slip/side)

| Symbol | A: defined-win 8.5%/4.5%, max 10d | B: realistic 1.2xATR target, quick out |
|--------|-----------------------------------|----------------------------------------|
| AAPL   | +$708 (50% win, 8.8d hold)        | -$462 (46% win, 1.7d hold)             |
| MSFT   | -$2,428 (29%)                     | -$1,801 (38%)                          |
| WMT    | +$120 (50%)                       | -$490 (42%)                            |
| BRK.B  | -$190 (60%)                       | -$961 (41%)                            |
| NVDA   | +$125 (40%)                       | -$1,642 (41%)                          |
| SNDK   | **+$9,485 (44%)**                 | **+$11,657 (55%)**                     |

**Read it honestly:** random-entry quick scalping on CALM megas bleeds — tight
stops get wicked out. Quick realistic targets EXCEL on names that actually
move (SNDK: best P/L + best win rate on the board). Baked into the build:
gate entries on signals (TCS), hunt the moving/liquid end of the market
(most-actives + movers pool), fit the target to the name's real range (ATR
cap), keep stops roomier than the sim's worst case, and step profits out.
Rerun anytime: `agents/scripts/sim_realistic_targets.py`.

## The knobs (agents/.env)

- `TREZO_TARGET_ATR_MULT` (1.5) / `TREZO_TARGET_MIN_PCT` (0.006) — target realism
- `TREZO_PROFIT_STEP_ENABLED` (1) / `TREZO_PROFIT_STEP_AT` (0.6) / `TREZO_PROFIT_STEP_FRACTION` (0.5)
- `TREZO_CRYPTO_SCALP_BB_MAX` (25.0) / `TREZO_CRYPTO_SCALP_VOL_MIN` (0.4) / `TREZO_CRYPTO_SWING_VOL_MIN` (0.8) / `TREZO_CRYPTO_DCA_RSI_MAX` (40)
- Cap-tier multipliers: `agents/app/strategies/cap_tiers.py` (TIER_PROFILES)
