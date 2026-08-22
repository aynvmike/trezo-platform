# Engine audit — live vs dead
### 2026-08-22. Mike: "keep and move forward what works; log and remove what doesn't, so we save the engine."

Method: AST import-graph over all 156 `.py` files under `agents/app` (44,819
lines), resolving absolute, relative and function-local imports, then
transitive reachability from three seeds — `app.main`, `app.runtime.bootstrap`,
`app.runtime.scheduler`. Cross-checked against `.env` flags, `web/src` and
`api/src` callers, `.bat`/`.ps1` entry points, and `importlib` dynamic
resolution. Nothing below is inferred from naming.

**Nothing has been deleted.** This is the log; removal is a separate,
signed-off commit.

---

## 1. Live and working — keep, move forward

**27 registered agents**, all instantiated in `runtime/bootstrap.py` and
scheduled by `runtime/scheduler.py`:

| tick | agents |
|---|---|
| 60–180s | position_monitor, pattern_detection, stms_scanner, crypto_scanner, forex_scanner\*, orb_scanner (120s) |
| 300s | ops_watchdog, book_health, relay_ingest, exit_advisor |
| 600–900s | adaptive_scope, market_horizon, archivist |
| 1800s | extended_scanner, options_scanner, tax_optimizer, market_sentiment, research |
| 3600s+ | strategy_discovery, dividend_manager (6h), kindrip_agent (6h), cycle_awareness (6h) |
| event-driven | risk_manager, trade_execution, portfolio_architect, exit_advisor_options |

Plus `reevaluator.py` — not registered, but imported by `position_monitor.py`
and **live in production** (`TREZO_REEVAL_ENABLED=true`), actively tightening
stops and rotating positions.

**138 support modules** are reachable from the tick path and genuinely used.
A further 12 are HTTP-only (backtest engine, simulation lab, postmortem,
options trim, position advisor…) with confirmed front-end callers.

---

## 2. Dead — proposed for removal (~734 lines, 5 modules)

Ranked by confidence. Each claim names the check behind it.

| # | module | lines | evidence |
|---|---|---|---|
| 1 | `paper/sleeves.py` | 411 | Zero importers. Superseded by `paper/allocation.py`. `main.py:1890` calls the old endpoint "the **dead** /sleeves/snapshot"; the UI was repointed at `/allocations/snapshot`. Only executable path left is its own `__main__` self-test. |
| 2 | `strategies/shadow_backtest.py` | 61 | Zero importers; `queue_shadow_trade` has zero call sites repo-wide. Docstring says Risk Manager should call it on every veto — it never does. |
| 3 | `strategies/futures.py` | 49 | Zero importers; `baseline_signal` never called. Self-described "Phase 1 scaffold"; Phase 2 never built. |
| 4 | `brokers/kraken_futures.py` | 186 | Only importer is #3 (itself dead). `config.py:204` hard-defaults `kraken_futures_enabled = False` and no `KRAKEN_FUTURES_*` key exists in `.env`. |
| 5 | `brokers/alpaca_ws.py` | 27 | Zero references anywhere. Its one function body is `raise NotImplementedError("Task #75 — real WS lifecycle work pending")`. |

**No test defends any of the five** — none is imported by anything in
`agents/tests/`, so there is no "staged, not abandoned" case for them.

**NOT dead despite zero Python importers:** `integrity/audit.py` (210 lines)
is an operator CLI invoked by `integrity-audit.bat`. Keep.

---

## 3. Bugs found while auditing — worth fixing regardless

**a. The scheduler's intended start path has never once executed.**
`main.py:2101` calls `start_scheduler(app=app, registry=registry)`, but the
only definition in the repo is `def start_scheduler() -> None:` — no
parameters. Every boot raises `TypeError`, the `except` at 2103 catches it,
and the fallback `start_scheduler()` is what actually starts the engine. The
engine works; the log line `agents.scheduler.started` has never fired in
production, and every boot logs `.fallback` instead. Low risk, trivially
fixable, and it means one log signal has been lying since it was written.

**b. The forex lane burns cycles it can never convert.** `forex_scanner`
defaults ON and ticks every 180s, fetching Kraken OHLC across 10 pairs. But
`.env` sets `TREZO_BROKER_ONLY=true` and `TREZO_FOREX_MODELED_OK=false`, and
`risk_manager.py:675` vetoes **every** forex signal under exactly that
combination. Confirmed in the live log: `veto | GBPUSD | Broker-only mode:
Alpaca has no forex venue`. Either turn the scanner off or give it a venue —
running it as-is is pure overhead plus veto noise that hides real rejections.

**c. Two comments assert the opposite of production.**
`position_monitor.py:2024` says the reevaluator is "Master-flagged OFF, so
this is a no-op" — it is ON, and 395 lines of it are live. The forex registry
entry says "Disabled by default until data source is wired" — it defaults ON.

**d. `user_support.py` is a registered agent that does nothing.** Both `tick()`
and `on_message()` `return []`, interval 0. Its docstring explains it exists
"so the agent registry has all 8 entries" — a comment now 19 agents out of
date. Harmless, but it's a listed agent that will never do anything.

**e. 43 public functions defined and never called.** The substantial ones sit
inside otherwise-live modules — most notably
`paper/stocks_reconcile.py:602 detect_option_drift_all_users` (~63 lines, the
largest orphan in the codebase, in a very live file), and 80 of 374 lines in
`runtime/significance.py` (`strategy_risk`, `sharpe_from_geometry`,
`deflated_sharpe_ratio`). Full list in the audit transcript.

**f. Zero commented-out code blocks** across all 156 files. This codebase
deletes rather than comments out — the debt here is orphaned modules and
functions, not commented fragments. Worth noting as a genuine strength.

---

## 4. Uncertain — flagged, not guessed

- **`learning/rule_replay.py` (699 lines)** — the biggest question mark.
  Reachable behind `GET /learning/rule_replay`, so not dead by the graph, but
  the string `rule_replay` appears in **no** front-end, script, doc or batch
  file. Either a curl-only analyst tool or abandoned; code alone can't say.
  There is also an empty `TREZO_RULE_REPLAY.md` (0 bytes) in C:\Trezo.
- **`/broker/snapshot` and `/broker/chain`** → `brokers/active.py`: real
  endpoints, no caller found. `active_broker_name` from the same module IS
  used, so the module loads either way — partially used at minimum.
- **Runtime agent toggles.** `POST /agents/{name}/toggle` and `bot_settings`
  rows can disable a registered agent at tick time. This audit read code and
  `.env` only, not the live database, so it cannot say which agents are
  enabled on the server right now.

---

## 5. Recommended sequence

1. Fix (a) — one-line signature fix, restores an honest boot log.
2. Decide (b) — forex off, or forex given a venue. Currently it is neither.
3. Correct the two lying comments in (c).
4. Remove the five dead modules in §2 as one reviewable commit.
5. Resolve (4) rule_replay with Mike — keep as an analyst tool, or remove
   699 lines.
6. Leave the orphaned functions in (e) alone for now: they are cheap, and
   several look like deliberate groundwork (significance testing, optimal-f
   curves) rather than abandonment.

*— Nova, for Mike and the platform's engineering agent*
