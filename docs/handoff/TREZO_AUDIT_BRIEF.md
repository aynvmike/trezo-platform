# Trezo — Audit Brief for Claude Code

**Written 2026-09-01. Companion to `docs/handoff/TREZO_CONTEXT_EXPORT.md` and the root
`CLAUDE.md`. Read both before starting.**

Mike's request, in his words: *audit and review everything, make sure the wiring and
attachments are on, make sure all the logic is going through, so we can have a running
trading site for users.*

This brief turns that into an ordered, checkable plan. Work top-down: each phase's findings
change what matters in the next one. Report findings as **CONFIRMED** (you traced it) or
**SUSPECTED** (it looks wrong but you could not prove it) — never blur the two.

---

## Ground rules for this audit

These come from repeated hard experience on this codebase. They are not style preferences.

1. **BUILT BUT NOT BOUND is what you are hunting.** Code that exists, passes tests, and is
   never reached. It has shipped three times *inside the fixes for itself*. For every
   feature you check, ask: what CALLS this? what values actually ARRIVE? when did this
   guard last FIRE?
2. **Read the resulting file in context, never the diff alone.** A diff that looks correct
   in isolation is how a variable got read 150 lines before it was assigned.
3. **Trust call sites over docstrings.** Docstrings in this repo have been wrong and have
   been fixed as bugs in their own right.
4. **Distinguish "failed" from "empty" in every external read.** Especially broker reads
   that can trigger a destructive action.
5. **Do not change kill-switch knobs, the R:R floor, lane modes, or recovery policy.** Those
   are Mike's decisions. Report, do not resolve.
6. **Run the right gate.** `python3 -m tests.run_all` from `agents/` is what decides
   deploys. pytest is a second opinion, not the gate.
7. Nothing here should place an order or mutate live ledger state. This is a read-and-trace
   audit. If a check would write, describe it and stop.

---

## Phase 0 — Establish the ground truth (do this first)

- [ ] `git log --oneline -30`, confirm HEAD. This export was written at `d9512e1`.
- [ ] `git status` — is the working copy clean? Is it ahead of / behind `origin/main`?
- [ ] `cd agents && python -m tests.run_all` — record the pass/fail of all suites.
      **This is the deploy gate.** Any failure here blocks everything.
- [ ] `pytest` in `agents/` — record differences from the above. Divergence between the two
      gates is itself a finding.
- [ ] `npm run typecheck` (or `tsc -p web/tsconfig.json --noEmit` and the api equivalent) at
      the repo root. Remember: ONE `npm install` at the root, never inside `web/` or `api/`.
- [ ] Confirm the three `.env` files exist and note which keys are MISSING versus
      `.env.example`. Do not print secret values.

Deliverable: a one-paragraph statement of what state the repo is actually in.

---

## Phase 1 — Is the signal path wired end to end?

This is the audit's centre. The path is:

```
scanner → bus "signal" → risk_manager.on_message → "approve"/"veto"
        → trade_execution.on_message → route_guard/bind_for_user → broker
        → position_monitor → paper ledger → dashboard
```

- [ ] **Registry vs reality.** Read `agents/app/runtime/bootstrap.py` lines ~80–120. Confirm
      all 30 registrations resolve to real modules, and that every agent listed in
      `ops_watchdog`'s expected-agent roster is actually registered (and vice versa).
- [ ] **Every scanner's emit path.** For each of `stms_scanner`, `orb_scanner`,
      `extended_scanner`, `crypto_scanner`, `pattern_detection`, `options_scanner`,
      `dividend_lt_agent`, `forex_scanner`: trace from the tick entry point to the bus
      publish. Note any that can return early on every realistic input. `forex_scanner` is
      known-dormant by design — confirm it *skips* rather than emitting doomed signals.
- [ ] **`risk_manager.on_message`, line by line.** Confirm the gate order is:
      kill-switch/per-book gate ABOVE the confidence bar, and that no name used in the bar's
      sum is assigned after it is read. `tests/test_risk_manager_signal_path.py` asserts this
      statically — read the test, then verify the invariant still holds by eye.
- [ ] **The R:R floor.** This is open item (a) and the highest-value finding available.
      Locate the reward:risk floor (0.5) and the learned-target shrinker. Confirm the
      reported behaviour: ~0.6% targets against ~1.5% stops producing R:R 0.4, killing
      every equity approval at execution. **Quantify it** — how many approvals died this way
      over the available history, and which component is out of calibration. Do not change
      either control; produce the numbers Mike needs to decide.
- [ ] **`trade_execution`'s whitelist.** `6c7e57f` pushed `max_notional` through the approve
      whitelist. Confirm every field the executor needs actually survives the approve
      message, and that `_lane_cap_f` binds in BOTH Alpaca sizing paths.
- [ ] **Book binding.** Confirm `route_guard` / `bind_for_user` is called before every
      broker call, on every path — including the crypto path and the options path.
- [ ] **Position monitor's fill detection.** Verify both branches treat a `None` positions
      read as do-not-act (the phantom-CLOSE fix). Grep for any *other* caller of
      `get_positions` (non-strict) that can trigger a close.

Deliverable: for each hop, CONFIRMED-WIRED / BROKEN / UNREACHABLE, with the call site.

---

## Phase 2 — Do the guards actually fire?

Every one of these was built after a real incident. Each is worthless if it does not bind.

- [ ] **Net 1 — `handler_failed`.** Read `bootstrap._route` and
      `_announce_handler_failure` (lines ~128–160). Confirm: it publishes AS the failing
      agent (because `_route` skips the sender), every step is try/except-wrapped, and the
      webhook fires once per (agent, error) rather than per message.
- [ ] **Net 2 — approval starvation.** In `ops_watchdog`, confirm `on_message` tallies
      signals/approves/vetoes with no I/O, and `_check_flow()` alarms on the exact condition:
      market hours AND ≥15 signals AND ≥20-minute window AND zero approvals. Confirm the
      alert distinguishes "vetoed" from "no verdict at all".
      **Then check whether it has ever fired** — given open item (a), an equity lane that
      approves nothing should be tripping this. If it is silent while equities approve
      nothing, that is a CONFIRMED defect in Net 2.
- [ ] **Per-agent tick ceilings.** `06ab0ab` replaced a global 900s tick ceiling with
      per-agent `tick_timeout_seconds`; `c0c7666` set honest budgets. Confirm
      `options_scanner`'s budget exceeds its observed runtime, and that
      `tick_cancelled_timeout` / `tick_failed` reach the bus.
- [ ] **`book_health`.** Confirm the unmanaged-notional check runs per book, bound, and that
      its alerts leave through the webhook rather than into a table.
- [ ] **The alert webhook itself.** `4ee6e5b` made `TREZO_ALERT_WEBHOOK` load via Settings.
      Confirm it is set on the server and that `send_test` still returns ok. An alert channel
      that silently no-ops is the failure mode this project has had twice.
- [ ] **`broker_truth_agent`.** Confirm it is registered, ticking, bound per book, and that
      it CLOSES only the unambiguous case. Confirm nothing else closes option rows.
- [ ] **Dead guards.** For each guard you find, note the last time it plausibly fired. Any
      guard with zero call sites is a finding — that is exactly what
      `detect_option_drift_all_users` was.

Deliverable: a table of guards → binds? → last fired → confidence.

---

## Phase 3 — Data and ledger integrity

- [ ] **Option rows live in `paper_positions` with `asset_type='option'`, not
      `options_positions`.** Grep for anything still querying `options_positions` for open
      rows — that table holds zero.
- [ ] **Quantity precision.** The ledger stores 8dp while Alpaca holds 9. This causes 403s
      on crypto stop placement (round-up) and dust crumbs (round-down). The clamp in
      `ratchet_crypto_stop` is a downstream patch; **the source (column or writer) is still
      unfixed.** Locate it and propose the fix.
- [ ] **Alpaca symbol spellings.** ORDERS take `"DOT/USD"`; POSITIONS take `"DOTUSD"`. Grep
      every positions-endpoint call for the wrong spelling — one already shipped green and
      did nothing.
- [ ] **Phantom realized P&L.** ~−$5.8k of DOT losses that never happened are booked into
      the 75k/primary counters. Identify exactly which rows/counters, and what an unwind
      would touch. Do not execute it.
- [ ] **Dust crumbs.** 3e-9 DOGE/LTC/SOL firing "$0 UNMANAGED" alerts. Find the threshold
      that should suppress them.
- [ ] **Migrations vs code.** 58 migrations applied; `schema_migrations` records them since
      0058. Cross-check that every column the code SELECTs exists — the dividend lane read
      `dividend_lane_mode` before any migration defined it and sat silently in one mode for
      weeks.
- [ ] **Alpha Vantage.** `dividends/schedule.py` is still on AV (25 calls/day). The rest of
      the codebase moved off it. Confirm whether this path can ever succeed.

---

## Phase 4 — Book isolation (the standing architecture rule)

Read §4 of the context export first. Then:

- [ ] Grep for module-level mutable state across `agents/app/`. For each, answer: **whose is
      this?** Anything not keyed by `user_id`/book is suspect.
- [ ] Audit every counter, cache, halt, gate and settings read for the
      *measure-per-book, enforce-globally* shape. It has been found five times.
- [ ] Confirm `get_bot_settings()` has no book-less fallback path remaining.
- [ ] Confirm open-signal capacity, consecutive-loss, broker-reject and slippage counters
      are all book-keyed.
- [ ] Confirm the weekly limit triggers RECOVERY mode (not a hard stop) and that daily 3%,
      streak, reject and slippage remain hard stops **for their own book only**.

---

## Phase 5 — The user-facing site

Read §12 of the context export. The honest position is that the platform has run for one
owner across three of his own books, so treat this phase as a gap analysis, not a bug hunt.

- [ ] **Auth and RLS.** Verify RLS is enabled on every table holding user data, and that
      policies key on the session user. Migrations 0002, 0041, 0042, 0045, 0047, 0048 are the
      relevant history.
- [ ] **Admin routes.** `/api/admin/diagnose|manual-trade|scope-adjustments|settings-audit|
      settings-sync` — verify the authorization check on each against a non-owner session.
- [ ] **`/api/internal/broker-token`** — verify it is not reachable without auth.
- [ ] **Broker OAuth.** Trace `authorize → callback → disconnect` and the token-refresh
      cron. Where are tokens stored and how are they encrypted (`FERNET_ENCRYPTION_KEY`)?
- [ ] **Engine fan-out.** The engine resolves books from env-var slots
      (`primary`/`acct2`/`acct3`), not from a users table. Describe precisely what would have
      to change for user #2 to exist. This is the largest single gap.
- [ ] **The ~40 dashboard pages.** Identify which are real, which are previews
      (`agents-preview`, `overview-preview`, `trading-preview`), and which render placeholder
      data. A page that looks live and shows modeled numbers is a user-trust defect.
- [ ] **Payments.** `agents/app/payments/` + migration 0036 exist. Is there a real billing
      path, or scaffolding?
- [ ] **Deployment.** There is no public deployment; the dashboard is Tailscale-only.
      `api.trezo.app` is aspirational. Note what a public deployment would require.
- [ ] **Live trading.** Confirm `TRADING_MODE=live` remains inert everywhere and that no
      code path can reach a real-money order. `GO_LIVE_CHECKLIST.md` is the gate.

---

## Phase 6 — Test coverage of the paths that broke

The dominant defect class here is *green tests, dead pipeline.* The 10 tests shipped with
`8c6c5ea` pinned kill-switch policy as a pure function and never ran a signal through
`on_message` — the platform then stopped trading for four days.

- [ ] For each agent with an `on_message` handler, ask: **is there a test that drives a
      message through the real handler?** List the ones with no such test.
- [ ] Confirm every suite in `agents/tests/` runs under `run_all.py`'s contract (no
      fixtures, no pytest, no network, no `.env`). Any suite that only works under pytest is
      invisible to the deploy gate.
- [ ] Note where a static/`ast`-based guard is the right answer (the deploy gate cannot boot
      the real engine — it would wire 30 agents to live broker keys) versus where a real
      execution test is possible and missing.

---

## Phase 7 — Report

Produce one document with:

1. **What is CONFIRMED broken**, ranked by consequence, each with file, line, and the
   failure scenario in concrete terms.
2. **What is SUSPECTED**, with what evidence would settle it.
3. **What binds correctly** — say so explicitly. After the history in §10, "verified
   working" is as valuable as a defect.
4. **Decisions for Mike** — anything that is two legitimate controls disagreeing rather
   than a bug. Open item (a), the R:R floor, is the live example.
5. **The path to a user-facing site**, as a program with phases, not a checklist.

Do not fix as you go beyond trivial, obviously-correct repairs. Mike wants the picture
first. When you do fix something that repairs an observable live symptom, **watch the
server log until the symptom stops** before reporting it as working — a green deploy is not
a working fix, and this project has three commits proving it.
