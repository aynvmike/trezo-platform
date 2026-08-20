# Trezo — Go-Live Checklist

The readiness gate before Trezo trades real money. Phase 10a built the
paper/live switch; this checklist is what must be true before that switch
is ever set to `live`.

**Rule:** do not set `TRADING_MODE=live` until every box below is checked.
Even then, live execution stays inert until Phase 10b wires the live
executor — the switch alone places no real orders.

---

## 1. The paper system is proven

- [ ] The full end-to-end test (`trezo-platform/TEST_CHECKLIST.md`) has
      been run and passed.
- [ ] Paper trading has run for a meaningful stretch with no crashes.
- [ ] The performance page shows a track record you are comfortable with
      (win rate, profit factor, drawdown).
- [ ] You have watched the agents make decisions and understand why they
      did what they did.

## 2. Safety rails verified on paper

- [ ] The daily loss limit halts new trades when hit.
- [ ] The losing-streak limit pauses the day at your chosen number.
- [ ] The daily profit lock vaults gains as expected.
- [ ] The Risk Manager vetoes trades in a bad market regime.
- [ ] Kill-switches (daily/weekly drawdown, broker rejects) all trip
      correctly in testing.

## 3. Brokerage account

- [ ] A real (funded) brokerage account exists, separate from the paper
      account.
- [ ] Live API keys are issued and stored only in `agents/.env` — never
      in `.env.example` or any committed file.
- [ ] The amount funded is money you can genuinely afford to lose.
- [ ] You understand the broker's fees, margin terms, and settlement.

## 4. The live executor is built (Phase 10b)

- [ ] A live execution path exists and has been code-reviewed.
- [ ] `_LIVE_EXECUTOR_AVAILABLE` in `runtime/trading_mode.py` is flipped
      to `True` only as the deliberate final step.
- [ ] Live orders route through the same Risk Manager, kill-switches,
      and allocation gates as paper.
- [ ] A clear "live" indicator shows on every screen when live is active.

## 5. Security

- [ ] A live penetration test has been completed.
- [ ] Rate-limiting is in place on auth and trading endpoints.
- [ ] All API keys have been rotated and old ones revoked.
- [ ] No secret appears in any committed file (re-scan `.env.example`).

## 6. Legal & compliance

- [ ] You have confirmed the regulatory position of running an automated
      trading system for yourself (and anyone else, if multi-user).
- [ ] Tax handling for real trades is understood (the Tax Optimizer is
      an estimate, not a filing).
- [ ] Disclaimers shown in-app are accurate for real-money trading.

## 7. Staged rollout

- [ ] First live run uses the smallest position sizes possible.
- [ ] One strategy is enabled live before the rest.
- [ ] You watch the first live session in real time, start to finish.
- [ ] A documented way to stop everything fast is in place and tested.

---

## The actual switch (only after everything above)

1. Confirm Phase 10b shipped the live executor and it was reviewed.
2. Set `TRADING_MODE=live` in `agents/.env` and `web/.env.local`.
3. Restart the agents and the web app.
4. Confirm the Bot Tuning page shows the live indicator.
5. Place one smallest-size trade and verify it end-to-end with the broker.

To return to safety at any time: set `TRADING_MODE=paper` and restart.
