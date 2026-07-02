# Trezo — Project Status Handoff

> **2026-07-01 review (Nova) — full audit: where trades go, why the pockets are invisible, re-eval status.**
> **Broker truth (Alpaca PA3PR4F6ZFWZ):** equity $4,816 / cash $2,846 / BP $4,670. Open: GM, MRK, SOFI, PYPL-short (DB) + KMI 7/17 30.5 CSP (broker-held). Jun-30 realized -$73 (WMT stop -$61, PYPL -$12); Jul-1 = ZERO broker orders.
> **Findings:** (1) Per-asset ALLOCATION POCKETS are LIVE engine-side (paper/allocation.py, growth posture: stocks $2.17k/crypto $1.69k/options $482/income $482; trade_execution._allocation_gate enforces) but INVISIBLE — the nav "Capital Sleeves" page calls /sleeves/snapshot which no longer exists (sleeves.py = dead code since the 6/18 revert; no backend route). Stocks pocket ~full ($2.09k/$2.17k) = why Jul-1 went quiet; crypto/options/income pockets IDLE for a week (all entries since 6/24 are stocks). (2) ACTIVITY LOG has ZERO call sites since the 6/18 revert (module committed 6/19 but never re-wired; last file logs/activity-2026-06-18.jsonl) — root cause of "can't tell what the agents are doing". (3) RE-EVAL ENGINE is ON (flag loaded at the ~6/30 15:30 restart) but 0 logged actions — correct per its triggers (stale 3d / rotate 7d / tighten-after-peak-giveback; positions were 1d old) AND it does NOT re-score TCS/IV on held trades (feature gap Mike expected); it only logs when it acts. (4) SLIPPAGE: 5bps fill model + crypto net-edge gate LIVE; the rules-doc slippage HALT was deferred in killswitch.py and never built. (5) MEM0 budget HEALTHY — correction: .env caps (1500/day, 10k/wk, 5k searches) ARE loading (week counter 2,551 past the old 2,500 default proves it); usage 2,551/10k wk. A once-a-day warn line now fires if it ever truly exhausts. (6) BUG: closed_manual rows CZR/CSCO 6/30 recorded realized $0.00 (phantom-close pattern lives on in the manual-close path) -> corrupts learning-loop outcomes AND paper_accounts week_realized stayed $0 despite -$48 real => weekly kill-switch can never fire. (7) bot_settings (Mike): tcs_threshold 450, max_open 20 — not the blocker.
> **2026-07-02 build (Nova) — memory efficiency + pockets UI + reconcile P/L fix (on top of the 7/1 visibility pack).**
> **Token-lean memory (Mike's ask):** mem0_client gains (a) a BATCH DIGEST buffer — `queue_note()` collects shorthand observations and flushes them as ONE combined Mem0 add per window (25 items / 15 min, env-tunable); risk-manager vetoes now ride it; (b) client-side DEDUPE — identical (agent,action,ticker) adds within 30 min are skipped before spending budget; (c) SHARED-RECALL CACHE — identical `recall_similar` queries within 180s share one search across agents; (d) compact `_format_decision` (reasoning capped at 200 chars, metadata trimmed). Expected: ~60-80% fewer Mem0 calls/tokens at same or better recall.
> **Pockets UI:** new GET `/allocations/snapshot` (mirrors the trade-execution gate math exactly) + the old dead Capital Sleeves page repointed to it — nav is now "Allocation Pockets", 4 cards (Stocks/Crypto/Options/Income) with budget/deployed/free bars. tsc+eslint 0 errors.
> **Reconcile P/L fix:** stocks_reconcile no longer books $0 — it recovers the TRUE exit fill via new `get_recent_closed_orders()` (brokers/alpaca), computes realized, rolls today/week/ytd counters (cash untouched), and activity-logs each reconcile close. Healed the 6/30 rows live: CZR +$1.21, CSCO +$6.15; week counter backfilled from rows (-$40.85).
> **Known follow-ups:** (1) external-position closes (broker stop fills) still don't roll account counters at close time — RIGHT fix is kill-switch summing the week's rows instead of trusting counters; (2) TCS/IV re-score on held positions NOT built yet — no shared scorer exists (TCS is computed inside pattern_detection picks); design = expose a `rescore_ticker()` from pattern_detection, call from reevaluator with cooldown, act on thesis-collapse; (3) internal-ledger equity (cash+vault $2.8k) drives pockets while Alpaca equity is $4.8k — the pockets page makes this drift VISIBLE now; decide whether pockets should key off broker equity.
> **2026-07-02 pre-market build (Nova) — market-cap formulas + market-first scanners + scalp groundwork + forex foundation (Mike's morning asks).**
> **Cap-tier formulas:** new `strategies/cap_tiers.py` — every stock approval now gets its stop/target scaled by market-cap tier (mega ≥$200B: 0.8x stop / 0.7x target = tight & quick; micro <$300M: 1.6x/1.8x = room to breathe; unknown = neutral). Tier via Finnhub profile2 marketCapitalization (new `fundamentals.market_cap_millions`, 24h cache, fail-open). Wired as the LAST formula step in risk_manager after Adaptive-Scope; payload carries `cap_tier`; every adjust hits the activity log (`cap_tier_adjust`). VERIFIED live: AAPL $4.3T→mega (5/10 → 4/7), SOFI $23.6B→large, CANF $18M→micro (→8/18).
> **Market-first scanning:** ORB + Extended scanners now sweep `expanded_scan_pool` (watchlist first, market fills to 40) — they were watchlist-bound, which is WHY the agents "loved AAPL/WMT/SOFI". `market_universe` upgraded: junk symbols filtered (warrants/units — tonight's log showed KRSP.WS etc. wasting slots), gainers/losers interleaved, and NEW `get_most_actives` (by volume — the liquid scalp fodder) leads the pool; every refresh logs `scan_pool_refresh`. VERIFIED: most-actives endpoint returns liquid names.
> **Scalp groundwork:** position_monitor intraday exits (90-min max hold, 3:45 force-exit, stagnation) now cover `scalp*` strategies; mega/large tiers marked `scalp_ok` in cap_tiers. ORB-on-liquid-movers with mega-tier tight formulas IS the v1 scalp behavior. NOT yet done: "scalp" as a selectable strategy in selector.py (needs a scoring family), partial-take profit stepping (50% at +1R via close_partial_position, trail the rest) — both queued.
> **Forex foundation:** new `data/forex.py` — key-less Kraken public OHLC for 5 majors (VERIFIED: EURUSD 721 bars), returns app Candles. NOT wired to any agent yet; forex engine (both directions, own pocket) = its own part. Alpha Vantage FX rejected (25 req/day cap).
> **Crypto:** deliberately NOT changed this round — the 7/1 visibility pack now logs every crypto veto with its reason; one trading day of `logs/activity-2026-07-02.jsonl` will name the exact gate starving the crypto pocket before we touch it. Universe widening (all Kraken-tradable) queued behind that read.
> **Queued next (Mike to prioritize):** A visibility pack (re-wire activity_log everywhere + re-eval heartbeat + slippage numbers in log), B pockets UI (/allocations endpoint + repoint the sleeves page + Settings dollar-overrides; forex pocket = new engine), C TCS/IV re-score trigger in reevaluator, D slippage halt + fix $0-realized manual closes.

> **2026-06-18 update (Nova) — Capital-Sleeve system + full Neo-Obsidian design overhaul (UNCOMMITTED; verified tsc/eslint + live in Chrome).**
> **Engine:** capital **sleeves** (active / quick-options / holding) with velocity-based per-trade sizing, equity-scaled position cap, and a proven-trade override; **per-sleeve time-exits** (active 5d / options 4d / holding by design) that killed the 90-day GTC holds; options +30% take-profit recycle; broader market-wide scanners; a `/sleeves/snapshot` endpoint — all live (confirmed serving real data).
> **Design:** fonts + obsidian/gold palette; Overview / Trading / Agents redesigned **and wired to real Alpaca data**; `/dashboard` landing IS the redesign Overview (classic kept at `/dashboard/home`); a 5-step animated onboarding wizard at `/onboarding/tour`; the landing hero is a **3D atom**; and a **depth system** (floating cards + ambient backdrops + a parallax landmark) applied across **all** pages.
> The whole web app typechecks at **0 errors**; the agents service is up running the new code. Still **uncommitted** (git lock-fault). Forex sleeve = the only deferred item (no engine yet). Full detail in auto-memory `trezo-project-state` + `design-neo-obsidian-integration`.

**Last updated:** 2026-06-16 ~10 PM ET — large bug-fix + self-healing + learning-loop arc shipped & committed (HEAD `0eb7576` + the commit accompanying this update). Shipped this arc: self-healing integrity sweep (cash<-broker + stock + orphan-option reconcile; runs at startup, ~hourly, and GET /integrity-check); wheel auto-fire cooldown + $0-buying-power quiet-skip; liquidity floor 1M->250k tunable (TREZO_MIN_AVG_VOLUME); account-identity guard + GET /account-check; outcome-weighted strategy selection + per-asset-type learning buckets + suggest_tuning fix; macro fall-through + honest diagnostic (still needs a real VIX/treasury source -- Alpaca-ETF proxy recommended); REAL structure-based risk/reward replacing the old rr=120 placeholder; opt-in experience-driven risk gate (default OFF via TREZO_OUTCOME_GATE_TUNING_ENABLED). Verified live: 0 errors across 23 agents. WARNING: Alpaca account PA3PR4F6ZFWZ buying_power = $0 -> the real gate on NEW trades; reset/grow the paper account to see the fixes produce more activity. Git lock-fault still active (HEAD.lock + index.lock stuck, unlink-EPERM) -> commit via commit-tree + direct ref write. NOTE: clear stale git locks before next git use -- see section 6.A1.
**Maintained by:** Mike (founder/architect) + Nova (Claude collaborator)
**Repo root:** `C:\Trezo\trezo-platform`

This document is the single source of truth for "where are we, what just shipped, what's next." Read this first when picking up the project.

> 🍍 **Pineapple continuity check — 2026-06-13 (Nova):** Cross-session memory is live and honored this session — the auto-memory index and `project_pineapple_test.md` loaded, and the full status below was reviewed and is current as of 2026-06-13. Note: the Mem0 **MCP server** is NOT connected in this Cowork session (no `mcp__mem0__*` tools surfaced); the Trezo agent-side Mem0 brain (status rows 22–28) is a separate Python integration and is unaffected. Pineapple acknowledged. 🍍

> 🍍 **Pineapple continuity check — 2026-06-16 (Nova):** Full session arc (bug fixes, integrity sweep, learning loop, real R/R, opt-in experience gate) captured in the auto-memory pineapple checkpoint `project_checkpoint_2026_06_16.md`. The agent-side Mem0 brain is verified WIRED (17 live add/search call sites). Unwired-feature audit completed — remaining scaffolds: shadow-backtest loop, alpaca_ws, user_support stub. Pineapple acknowledged. 🍍

> 🍍 **Pineapple continuity check — 2026-06-18 (Nova):** Full session arc — capital-sleeve system + per-sleeve time-exits (killed the 90-day GTC holds), then the complete Neo-Obsidian design overhaul (Overview/Trading/Agents wired to REAL Alpaca data, `/dashboard` landing = redesign Overview, 5-step onboarding wizard, **3D atom hero**, and a **depth system across all pages**) — captured in auto-memory `project_checkpoint_2026_06_18.md`. ALL uncommitted on HEAD `3e2032b` (lock-fault still active: HEAD.lock + index.lock + maintenance.lock undeletable, 68 dirty paths). Web app tsc + eslint = **0 errors**; agents up on the new code; verified live in Chrome. New design doc for the Figma bot: `TREZO_PLAN_RESEARCH_DESIGN.md` (the 5 Plan & Research pages). Pineapple acknowledged. 🍍

---

## 1. Goal

Trezo is an **autonomous layered trading platform** for a single operator (Mike) that grows into a multi-user product. The core idea: instead of one strategy, the bot runs concentric **protection rings** (Layers 1-7), each more conservative than the last. Outer layers take aggressive trades; inner layers protect compounded capital.

**Layer ordering (outer → inner):**

1. Layer 1 — Stock Bot (Pattern Detection, ORB, Extended, STMS)
2. Layer 2 — Crypto Bot
3. Layer 3 — Options (directional + wheel)
4. Layer 4 — Dividend Wheel (CSP + CC cycle)
5. Layer 5 — **Dividends** (umbrella; YieldMax is one aggressive sub-strategy)
6. Layer 6 — *reserved*
7. Layer 7 — KINDRIP (innermost, child-account compounding via Future Index Accounts)
- Horizontal: Tax Optimizer (cuts across all layers, not numbered)

**End state vision:** the operator picks how much capital sits in which ring; the bot manages each ring's strategies autonomously with humans only signing off on exception cases.

---

## 2. Current status (2026-06-11 morning)

### Live state

- Bot is **RUNNING LIVE** on Alpaca paper account `trezo_claudecowork (PA3PR4F6ZFWZ)`. Buying Power $20,763; Cash $5,190.
- 19 agents registered (added forex_scanner 6/8, ops_watchdog 6/3).
- Market opens in ~30 minutes. **Mike's plan is to restart agents tonight after close to load the morning's fixes** — not now, because trading-day data collection is in progress.
- Trade-day data has been collecting since 5/31. ~91 prior tasks shipped, +7 today (session 2026-06-11).

### Data spine

- **Macro:** Polygon (priority 1) → Twelve Data → Alpha Vantage → Manual env → Unavailable
- **Stocks + options:** Alpaca paper + Alpha Vantage REST
- **News:** Finnhub (Market Sentiment scoped 08:00-16:00 ET only)
- **Crypto:** `CRYPTO_WATCHLIST` + user crypto-tagged watchlists via `get_crypto_universe(user_id)`
- **Wheel universe (NEW today):** SEED 17 + dividend-tagged watchlists + open option positions + `MARKET_WIDE_DIVIDEND_POOL` (64 cross-sector liquid dividend payers)
- **In-chat MCPs:** Alpha Vantage (110 tools) + FMP (27 tools). Polygon MCP failed SSL during install; abandoned in favor of bot-side Polygon REST.

### What's shipped this session (2026-06-11)

| # | Subject | Status |
|---|---|---|
| 1 | Exit Advisor auto-action toggle (`auto_exit_advisor`) | ✅ |
| 2 | External heartbeat monitor (Windows scheduled task, 15-min) | ✅ |
| 3 | Risk Manager `_recent_approvals` restart-survival (WMT 52-share fix) | ✅ |
| 4 | ORB + Extended + Pattern Detection restart-survival | ✅ |
| 5 | Wheel/options universe opened to broader markets (MARKET_WIDE_DIVIDEND_POOL) | ✅ |
| 6 | Trezo↔Alpaca position mismatch (4 stale "open" rows phantom-direction-2) | ✅ |
| 7 | **Gap 2** — Exit Advisor close must reach Alpaca (`close_position_broker_aware`) | ✅ |
| 8 | **Gap 1** — Intraday time stops apply to Alpaca-routed positions | ✅ |
| 9 | **Gap 3** — Investigated, verified not-a-bug, closed | ✅ |
| 10 | Crypto exit-path audit (follow-up from Gap 3 audit) | ✅ audited — 4 defects found, all latent (zero live crypto rows, Alpaca flat) |
| 11 | Crypto exit fixes: client-side stop/target in Position Monitor, pair-symbol variants (`BTC`↔`BTCUSD`), crypto-aware `liquidate_position`, stocks-reconcile asset_class filter | ✅ |
| 12 | **Task #6 from 6/10** — Wheel universe ceiling = stock-side `market_wide_candidates()` (movers + sector leaders), yield-gated, AV live-lookup budget 5/build | ✅ |
| 13 | **Auto-exit dead-on-arrival** — `trim_position` never existed; shared import killed urgent auto-closes too (Task #92 + Gap 2 were inert). Implemented `trim_position()` in engine | ✅ |
| 14 | **ops_watchdog dead since shipping** — imported nonexistent `scheduler._last_tick_at`; crash-looped every tick since 6/3 era. Now reads `registry` state + NEW "never_ticked" urgent alert | ✅ |
| 15 | **Phantom-close reconcile never worked** — `stocks_reconcile` wrote a `notes` column that doesn't exist on `paper_positions`; PostgREST rejected the whole update silently. Removed | ✅ |
| 16 | **yfinance froze the event loop** — `_yfinance_candles` ran blocking network I/O inline in async; now via `asyncio.to_thread` | ✅ |
| 17 | **Approve-without-fill poisoned dedup** — SOFI approved pre-open 9:16/9:29, skipped (market closed), then vetoed "already approved" all day. Risk Manager now frees the ticker on any trade_execution info/error | ✅ |
| 18 | **Dark agents SOLVED (4th pass)** — live `/agents` dump showed the mechanisms: (a) APScheduler default `misfire_grace_time=1s` + event loop blocked by inline yfinance ⇒ starved jobs silently skipped (crypto_scanner: 0 ticks in 6.4h at a 180s interval); (b) hung ticks + `max_instances=1` ⇒ agents silenced forever with no error (pattern_detection stopped 1:10 PM, exit advisors 1:06 PM). Fixed: `job_defaults` grace=None + per-tick `asyncio.wait_for` timeout in scheduler | ✅ |
| 19 | **Position Monitor crash-looping ALL DAY** — morning `_decide_time_stop` refactor dropped the `strat =` assignment; NameError on every tick after 10:33 AM (`/agents` last_error). No time stops / no reconcile ran today. Assignment restored | ✅ |
| 20 | **`record_external_position` never wrote the `broker` column** — every Alpaca-routed row landed `broker="paper"`, so the WHOLE Alpaca branch (reconcile, time stops, Gap 1/2, crypto exits) skipped them. Column now written. Data repair applied: AAPL + INTC open rows re-tagged `broker="alpaca"` | ✅ |
| 21 | **Naked-position alert** — AAPL found held overnight at Alpaca with NO exit legs (day-TIF bracket died at close, monitor was dead so no time stop). Monitor now raises an hourly alert when an Alpaca stock row has zero open exit orders. ⚠ **AAPL needs manual action — see section 6.A0** | ✅ code / ⚠ AAPL |
| 22 | **Mem0 recall NEVER worked** — mem0ai 2.x search() rejects top-level user_id; every `recall_similar` failed silently since install. Fixed (filters API + client-side metadata filtering). Verified live: XRP crypto_swing recall returns "0 won / 1 lost, median -$112" | ✅ |
| 23 | **Mem0 ADD quota exhausted** — 10,000/10,000 used (resets 2026-07-01) because every routine veto was logged (~120/day of "Neutral direction" noise). Fixed: routine-veto filter in Risk Manager + 6h write-pause on 429 in mem0_client. Reads unaffected; NEW memories resume 7/1 or on plan upgrade | ✅ guards / ⚠ quota |
| 24 | **Mem0 budget governor** (Mike upgraded the plan) — persistent day/week caps in mem0_client: 400 adds/day, 2,500 adds/week, 2,000 searches/day (tunable in `agents/.env`, counters in `app/memory/.usage_budget.json`, surfaced via `health()`). Verified live: write→recall→delete round-trip green | ✅ |
| 25 | **Task #47 CLOSED** — Mem0 v3 adds are async (response = event_id/PENDING, no memory id), so linkage now uses a client-side `decision_key` generated before the fire-and-forget write: approve_payload → source_payload → TradeOutcome.related_decisions. Verified: recall returns the key in metadata | ✅ |
| 26 | **Day-TIF bracket bug (the AAPL incident's root cause)** — exit legs were `tif="day"` for every strategy except `extended`, so any multi-day trade went naked after the close. Now only STMS/ORB (true intraday, with hard time stops) use day legs; everything else gets GTC | ✅ |
| 27 | **Mem0 budget re-tuned** (plan now 50k/month, 10k burned) — 1,500 adds/day, 10,000 adds/week, 5,000 searches/day, set ACTIVE in `agents/.env` | ✅ |
| 29 | **Options delta filter rebuilt** (Mike's feedback via mem0 afa5668c) — two bugs: position-level share-equivalent net_delta (e.g. 14.13) was compared to the 0.45 PER-LEG cap, rejecting essentially every premium sell; and the cap was flat across timeframes. Now: units normalized to per-leg delta, DTE ladder (<=1 DTE no cap / <=45 DTE user cap 0.45 / <=180 DTE 0.75 / LEAPs 1.00), 0.05 floor. `options_max_premium_delta` = leg-delta cap as Mike intended | ✅ |
| 30 | **Delta language translated everywhere** — `leg_delta_of()` helper; every options idea now carries BOTH `net_delta` (tagged `share_equivalent`) and `leg_delta` (the 0.2418-style fraction Mike's settings speak) in the broadcast payload, Mem0 metadata, and filtered-idea logs. Risk Manager + future recall read the proper language (mem0 eb3969af was the example: 24.18 ↔ 0.2418) | ✅ |
| 31 | **Structure-aware delta judgment** (mem0 7c991cc1: O iron condor vetoed for delta — a condor is delta-neutral BY DESIGN) — multi-leg spreads: no 0.05 floor (near-zero tilt is the goal), band cap = directional-tilt guard only; single-leg shorts keep floor + cap. Filtered ideas now log `filter_rule` + `n_legs` + `leg_delta` to Mem0 so the learning loop can mine which rules block winners (Mike: "based on more numbers rather than limited defaults") | ✅ |
| 32 | **Strategy reattribution + tag standard** (mem0 72c35e29: YMAT TCS 670 @ $1.23 died on the $5 DEFAULT floor with strategy='unknown' — STMS's $1 lane fit it perfectly) — liquidity vetoes now compute `profiles_accepting()` and carry `reattribution_candidates`; high-TCS (>=600) cases are preserved in Mem0 as `veto_reattribution_candidate` (exempt from the routine-noise filter) so recurring mislabeled setups can become relabels or NEW strategies. Veto still stands per capital-safety directive. Plus `normalize_tags()` in mem0_client: every memory now guarantees kind/agent/action/ticker/strategy + a flat `tags` list — no more blank tags | ✅ |
| 28 | **Strategy knowledge seeded into Mem0** — new `scripts/seed_strategy_knowledge.py` (idempotent via `knowledge_key`): all 15 StrategyCards + 7 INSIGHTS.md external-research sections now live as kind=`strategy_knowledge`, recallable by every agent through `recall_similar(kind="strategy_knowledge")`. 22 adds spent. Re-run after editing library.py or INSIGHTS.md to pick up new entries | ✅ |

### Outstanding / queued (full inventory, refreshed 6/11 evening)

**Do tonight (manual):**
1. ⚠ Protect/close AAPL (section 6.A0) — naked at Alpaca
2. Restart agents (section 6.A) — loads all 19 of today's fixes
3. Verify dark agents revive: `[PowerShell] Invoke-RestMethod http://localhost:8001/agents | ConvertTo-Json -Depth 4`
4. If not done yet: register heartbeat task (section 6.B)

**Verify at Friday open:**
- options_scanner's first Wheel run (Layers 3-5 alive); crypto_scanner ticking; watchdog alerts working; auto-exit close/trim firing when toggled ON
- market_sentiment: last message 6/5 — if still dark after the scheduler fix, it has its own bug (Finnhub key? time-scope gate)

**Code queue (priority order):**
- ~~#47~~ — CLOSED 6/12 via client-side decision_key (row 25)
- **Mem0 seeding** — plan upgraded, writes work now: `[PowerShell, agents venv] python -m scripts.seed_mem0_from_files --dry-run` first, then without the flag. Costs ~1 add per memory file (~30) — well inside the 400/day budget
- **Trim on Alpaca-routed positions** — bracket cancel → partial sell → re-submit pattern
- **#75** — Alpaca WebSocket full lifecycle (scaffold at `brokers/alpaca_ws.py`)
- **#77** — Forex data source pick (Alpaca FX vs AV FX_DAILY vs Polygon); forex_scanner stays a no-op until wired
- **#45 + #51** — UI passes: Sim Lab trade rows + Wheel universe display (expect >74 names now)
- **Pre-open approve handling** — dedup-release shipped; optionally queue near-open approves instead of dropping (nice-to-have)

**Phase backlog (Mike's roadmap):**
- Phase 5b — NeMo Guardrails on the LLM-using agents
- Phase 9 — KINDRIP / Future Index Accounts build-out
- Phase 13/14 — outcome-aware self-tuning (strategy_discovery consumes Mem0 outcomes + shadow-backtest results to adjust strategy weights; infrastructure now functional)
- Per-stock strategy selection in LIVE trading (done for backtest; live still scanner-routed)
- License-compatible macro source to replace FRED (do NOT re-add FRED)

---

## 2c. Crypto expansion — Part 1 of N (2026-06-13, weekend build)

Mike's direction: take full control of crypto like stocks; cover the whole ISO 20022 ecosystem (XRP/XLM/ALGO/HBAR/QNT/XDC/IOTA/XYO + SOL); add a HODL accumulate-and-hold mode; make untradeable coins doable in code; HODL can "hold and not sell" but must NOT be emotional.

**Part 1 shipped (loads at next restart):**
- **Crypto classification fixed** — `CRYPTO_SYMBOLS` was a hardcoded 4-set (XRP/ETH/SOL/BTC), so the ISO coins were misclassified as STOCKS and routed to Alpaca's stock path. Now derived from `COIN_MAP` (majors + full ISO cluster). Untradeable coins (XLM/HBAR/ALGO/IOTA/QNT/XDC/XYO) now correctly route to the modeled-paper engine on live CoinGecko prices = "doable in code" as Mike asked.
- **HODL mode** added to crypto strategy (deepest-value tier, RSI<25): catastrophe stop -35%, sentinel target +500% (= hold, never auto-sell), small size by construction (wide stop → few coins → can't dominate the book = the anti-emotional discipline). Priority: SWING > HODL > DCA > SCALP.
- **HODL exempt from Exit Advisor** — with auto_exit_advisor now ON, peak-giveback would have force-closed HODLs; exit_advisor now skips any `*hodl*` strategy. Only the catastrophe stop or a manual close exits a HODL.
- Verified: XRP deep-decline → HODL (stop 0.35, target 5.0); HBAR in COIN_PARAMS (modeled); import audit clean.

**Part 2 shipped (2026-06-13; loads at next restart):**
- **Per-coin HODL cap** — Risk Manager caps TOTAL open exposure to any one coin at `hodl_per_coin_cap_pct` (default 10% of equity, summed across all open rows); no approval once a coin reaches the cap. Guards first buys and accumulation alike.
- **Cross-day accumulation** — HODL/DCA may scale in on dips across days: the same-ticker stacking veto is relaxed for those two modes only, gated by a restart-safe cooldown (`crypto_accumulate_cooldown_hours`, default 18h) and the per-coin cap. Each add is its own small row; swing/scalp/stocks stay one-shot.
- **Trail-to-lock** — once a long HODL runs +40%, Position Monitor ratchets its stop UP to lock ~80% of the high (never lowers it, never sets a profit target). Protects a big run without force-selling.
- **SWING step-ladder profit lock (Part 2b, 2026-06-13)** — SWING keeps its fixed +12% target but ratchets a step-ladder stop UP as return-on-capital climbs (+5% -> breakeven, +8% -> +3%, +10% -> +5%; tunable in `SWING_PROFIT_LADDER`), so a reversal before the target still banks the gain. Implements the long-missing SWING "trail after 5%" the spec always intended; same tighten-as-you-profit discipline as the options drawback ladder.
- **Dashboard** — HODL mode badge + four-mode copy + ISO cluster + plain-language HODL explainer on `/dashboard/crypto`.
- **Exchange connector SCAFFOLD** — `brokers/crypto_exchange.py` (Coinbase/Kraken) wired into trade_execution routing but FEATURE-FLAGGED OFF: `is_configured()` is False until `crypto_exchange_enabled=true` AND keys are set in `agents/.env`, so it can never fire by accident; always falls back to the modeled engine. Long-only (crypto short side deliberately deferred).
- **Migration 0044** (optional, non-blocking) adds `hodl_per_coin_cap_pct` + `crypto_accumulate_cooldown_hours` to `bot_settings`; the code already enforces both via graceful defaults, so no paste is required to get the behavior.

**Part 3 shipped (2026-06-13; loads at next restart):**
- **Kraken connector (validate-first)** — `brokers/crypto_exchange.py` does real Kraken auth (HMAC-SHA512, verified offline vs Kraken's official test vector), private `Balance` (`self_test`), and `AddOrder` with `validate=true` (checks orders against the live book, NO funds move). Reads Mike's `Kraken_API_KEY` / `Kraken_Private_Key` from agents/.env via config aliases. `is_configured()` stays OFF until `CRYPTO_EXCHANGE_ENABLED=true`, so adding keys alone never changes routing. Real placement + fill reconciliation is Part 4 (real money — needs explicit go-ahead).
- **Live Kraken market data** — `data/candles.py` `fetch_kraken_ohlc()` pulls Kraken PUBLIC OHLC (no auth, real prices + real volume) for listed coins, CoinGecko fallback otherwise. Fixes the CoinGecko volume=0 blind spot for SCALP/SWING.
- **Step-ladder extended to DCA + Extended** — crypto DCA (`DCA_PROFIT_LADDER`) and the STOCK swing Extended (`EXTENDED_PROFIT_LADDER`) now lock gains on the same return-on-capital ladder. Extended is Alpaca-routed, so the monitor ratchets the DB stop and liquidates client-side (cancel legs + market) when the locked stop is hit — same pattern as the time stops.

**Part 4 queue (real money — needs Mike's explicit go-ahead):** real Kraken order placement (`validate=false`) + live fill recording + Kraken-side exit/reconciliation; optional crypto short side; per-coin cap slider in Bot Tuning UI. NOTE: Kraken Spot has NO paper API (only Kraken Futures demo, a different leveraged product), so paper crypto stays on the modeled engine priced off live Kraken data.

## 2d. Kraken Futures (demo) — Phase 1 shipped (2026-06-13; loads at restart)

Kraken Futures has a REAL demo/paper sandbox (demo-futures.kraken.com, same API as production, only the base URL differs), so the agents can learn futures + build strategies with NO real money. This is the leveraged-futures path, separate from long-only spot.

- `brokers/kraken_futures.py` — public `instruments`/`tickers`, `tradable_symbols()` (widest available, incl. any ISO-cluster futures), private `accounts` `self_test`, Kraken-Futures Authent signing, and `leverage_cap()`/`clamp_leverage()`.
- `strategies/futures.py` — scaffold + a baseline momentum example (long/short, demo) for the agents to iterate on.
- `data/candles.py` `fetch_futures_ohlc()` — public Kraken Futures charts (no auth).
- `config.py` — `kraken_futures_*` (demo default ON), `futures_max_leverage` default 2x.
- **Leverage range 1x–10x (Mike 2026-06-13, revised):** agents choose leverage per strategy from 1x up to 10x so the learning/strategy-strengthening process is not artificially limited; `LEVERAGE_HARD_CAP` is a 10x safety ceiling (his stated max), default setting 10x. (Supersedes the earlier 2–3x posture.)
- Needs a SEPARATE demo API key (demo-futures.kraken.com/settings/api); the spot key won't work.

**Futures Phase 2 (NOT built):** live `futures_scanner` agent + demo order placement (`sendorder`) + futures exit/position management + `strategy_discovery` on futures data. Futures auth is pending live demo self-test verification (no offline vector like spot). SECURITY: the spot API key had Withdraw/Deposit/Earn enabled — minimize to query + order perms.

## 2a. Friday 6/12 POST-MORTEM (6 PM) — what the day taught us

**The day in trades:** AAPL sold at open (+$10.30 banked) then bot SHORTED AAPL (default, GTC bracket, +$2.88). STMS fired GM/CSCO/SOFI at the bell; WMT shorted. **Open-bell phantom-close race** (rows "closed" 6-60s after submit because unfilled orders aren't in the positions API yet) mangled the books; the 30-min reconcile re-imported CSCO/SOFI/WMT as strategy="reconciled" (losing stms tags + time stops). GM re-entered at 9:39 keeping its stms tag — and then **its time stop fired 429 times all day, every one rejected by Alpaca 403 "available: 0"**: the bracket's own sell legs reserved all 30 shares; DELETE /v2/positions does NOT auto-cancel them. The Wheel sold its FIRST REAL option (ARCC 7/17 $18 CSP, premium $20) but the tracking insert failed on nonexistent columns; 190x buying-power + 120x market-closed blocked retries spammed the log. Delta translation verified live (net 39.47 → leg 0.3947 on today's ideas). auto_exit_advisor could never arm: the bot_settings COLUMN never existed.

**Fixed tonight (rows 33-38, load at next restart):**
| 33 | liquidate_position cancels the symbol's open orders BEFORE DELETE /v2/positions (GM 403 root cause) | ✅ |
| 34 | 5-min fresh-row grace in the monitor's reconcile-close (open-bell phantom race) | ✅ |
| 35 | Re-imported rows inherit strategy/stop/target from their <24h closed predecessor (no more lost stms tags) | ✅ |
| 36 | Watchdog exempts event-driven agents (interval<=0) from never_ticked | ✅ |
| 37 | Wheel auto-fire pre-gates: market clock + CSP collateral vs options buying power (no more 422/403 spam) | ✅ |
| 38 | options_positions tracking insert: dropped nonexistent broker_order_id/source_payload columns (folded into notes); ARCC row repaired by hand (id e6812fed) | ✅ |

**Migration 0039 — DONE ✅ (no paste needed).** The auto-exit toggle column was renumbered 0039→0043 (0039 collided with `0039_options_user_filters`) and is already applied in the DB (commit 85ab86c, verified 6/13). The SQL below is kept for history only:
```
[Supabase SQL]  ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS auto_exit_advisor boolean NOT NULL DEFAULT false;
```
Just flip auto_exit_advisor ON in /dashboard/settings/bot when you want auto-exits live — the column already exists.

**Monday open watch:** GM/CSCO/SOFI/WMT exits will finally fire (time stops + brackets now cancellable); confirm closes log Mem0 outcomes with related_decisions.

## 2b. Live watch — Friday 6/12 pre-market sweep (8:30-8:45 AM ET, observation only)

**Confirmed working:** full build live (service records carry decision_key + tags); screener firing 26 signals/tick across 4 lanes (top TCS 670); STMS scanning 15 names/tick; crypto 7-9 coins/tick 24/7; Risk Manager 136 vetoes + 5 approves pre-market; Position Monitor clean (AAPL broker-aware, INTC auto-reconciled closed); dedup-release cycling SOFI pre-open as designed; **the Wheel attempted its first REAL Alpaca option orders overnight** (wheel_csp, e.g. ARCC260717P00018000) — blocked only by "options market orders only during market hours"; it retries every 30 min, first in-hours attempt ~10:00 AM.

**After-close fix queue (DO NOT touch during market hours):**
1. Watchdog `never_ticked` false-alarms on event-driven agents (risk_manager, trade_execution, user_support have tick_interval=0) — exempt interval<=0 agents.
2. Wheel auto-execute should check the market clock before submitting options orders (avoid 422 churn; stocks already do this).
3. `scanner_pulse.scanned` reports 0 while `fired`=26 — counter bug, cosmetic.
4. Verify first TODAY close logs a Mem0 outcome with `related_decisions=[decision_key]` (old INTC outcomes predate the key). If empty, trace `record_paper_close` -> source_payload chain.

## 3. Architecture

### Repo layout
```
C:\Trezo\trezo-platform\
  ├── web/        Next.js 14 + TypeScript (dashboard, /api routes)
  ├── api/        Express + TypeScript (auxiliary REST)
  ├── agents/     Python 3.11 + FastAPI + APScheduler (the bot)
  └── db/         Supabase migrations (38 of them as of 6/8)
```

### Agent topology (`agents/app/agents/`)

**Scanners (emit signals):**
- `pattern_detection` (the stock bot) — market-wide via `expanded_scan_pool()`
- `orb_scanner` — opening range breakouts
- `extended_scanner` — multi-day swings
- `stms_scanner` — small-cap intraday
- `crypto_scanner` — crypto
- `options_scanner` (the Wheel) — calls `get_wheel_universe(user_id)`
- `market_horizon` — macro regime
- `market_sentiment` — news (Finnhub)
- `dividend_manager` — Layer 5
- `forex_scanner` — scaffold only, no data source wired
- `research` — backtest experiments

**Decision + execution:**
- `risk_manager` — vetoes/approves signals; tiered staleness gates
- `trade_execution` — only consumes `kind="approve"`; stock buys go through `submit_bracket_order`
- `position_monitor` — closes on stop/target hit; intraday time stops; reconciles Trezo↔Alpaca
- `exit_advisor` (stocks) — peak-giveback alerts + (when toggle on) auto-close/trim
- `exit_advisor_options` — equivalent for options

**Operational:**
- `ops_watchdog` — silent-failure detector; per-strategy liquidity floors
- `cycle_awareness` — cross-layer awareness
- `adaptive_scope` — regime-driven aggressiveness
- `strategy_discovery` — outcome-based learning loop (scaffolded; not self-tuning yet)

### Data flow

```
Scanner → AgentMessage(kind="signal") → Risk Manager (veto/approve)
                                            ↓
                                    kind="approve" → Trade Execution
                                                          ↓
                                                Alpaca bracket order
                                                (entry + stop_loss + take_profit)
                                                          ↓
                                          paper_positions row created
                                            (broker="alpaca", status="open")

Position Monitor (every 60s):
  - Alpaca branch: get_open_symbols() → reconcile closed positions
                   + intraday time stops (NEW today) → liquidate_position
                   + multi-day Extended swing time stop → liquidate_position
  - Internal branch: stop/target price check → close_position
                     + time stops via _decide_time_stop (NEW today, shared)

Exit Advisor (every 60s):
  - Peak-giveback detection per tier
  - Raises exit_advisor_alerts row (dashboard widget reads this)
  - If auto_exit_advisor=True:
      urgent → close_position_broker_aware (NEW today, hits Alpaca first)
      warn   → trim_position (internal only; alpaca rows alert-only)
```

### Persistence

- **Supabase** Postgres for all state (`paper_accounts`, `paper_positions`, `options_positions`, `agent_messages`, `exit_advisor_alerts`, `watchlists`, `watchlist_items`, `bot_settings`, `ops_health_alerts`, etc.)
- **Mem0 MCP** for agent-level shared brain (`agents/app/memory/` scaffolding shipped 6/1). Vision: agents learn from outcomes across days. Wiring queued.

---

## 4. Key decisions made

### Capital safety (Mike's directive 2026-06-05)

> "We should be using the platform settings for the automation on some of the rule changes not its own interpretation. Anything that would be risky as a trade that is out of the parameters should be used in the strategy labs and back test so we can get data information that way until we can prove a better system."

Enforced via:
- `NOTIONAL_CAP_PCT` reads `bot_settings.max_position_pct` (default 0.25)
- `MIN_REWARD_RISK` reads `bot_settings.min_reward_risk_floor`
- Shadow-backtest queue (`strategies/shadow_backtest.py`) — vetoed signals enqueue for Strategy Lab simulation; Mike reviews weekly
- Tiered staleness in Risk Manager: TCS ≥700 = 60s, 500-699 = 180s, <500 = 300s
- Same-ticker dedup uses a `set`, not a deque (won't lose old tickers); seeded from open positions on restart (Task #3 today)

### Watchlist is personalization, not the universe ceiling

Every new feature must default to a market-wide candidate pool and use the user's watchlist for ranking/personalization, never as a hard filter. Pattern Detection got this via `expanded_scan_pool()`. Options/Wheel partially got it today via `MARKET_WIDE_DIVIDEND_POOL`; full alignment with stock-side `expanded_scan_pool` is queued.

### Per-stock strategy selection

Never force one strategy across a whole watchlist. Test every strategy per stock; pick the best per stock. Done for backtest; live trading still uses scanner-level routing.

### Strategy switching needs friction

Pattern Detection tracks `_prev_strategy[ticker] = (strategy, TCS)` so re-switching strategies for the same ticker requires a measurably better TCS than the last call. Survives restarts as of today (Task #4).

### Edit tool tail-truncation reality

The Edit tool routinely chops 5-20 trailing bytes off files on the `C:\Trezo` mount. Always verify with `tail` + `cat -A` after every Edit on that mount. For risky edits (heredoc rebuilds especially), copy to `/tmp` first as a backup. We lost `paper/page.tsx` once on 6/1 without this guard.

### Neo Obsidian aesthetic

UI design is "sleek near-black obsidian, old-world warmth, sharp/smooth duality." All new UI work should match this — not bright Bootstrap defaults.

### Plain-language explanations

User-facing copy explains the reason in plain English ("KINDRIP deposits trigger because..."). Apply to tax guidance, alerts, all dashboard explainers.

### Command tagging is required

Every command/action Mike runs must carry a `[tag]` showing where to run it (`[PowerShell]`, `[Cowork chat]`, `[Trezo - Agents window]`, `[Browser]`, `[Notepad]`, `[Supabase SQL]`, `[Win+R]`, etc.). Mike defaults to PowerShell when unclear; many things fail silently otherwise. Required from 6/1 onward.

### Pineapple is the cross-session memory marker

When Mike says "pineapple," it's a planted test that the memory file `project_pineapple_test.md` is being honored. Acknowledge memory live, reference current state, do NOT search Mem0 — the pineapple memory file is the canonical answer.

---

## 5. What to avoid

### During trading hours
- Don't restart agents during the trading day. Trade-day data is mid-collection; restarts wipe in-memory state (we've now seeded most of it from DB, but still avoid).
- Don't run heavy migrations or schema changes on `paper_positions` during open hours.
- Don't claim "the bot is working" without first checking `GET /health` AND a recent `agent_messages` row from `pattern_detection` within the last 15 minutes.

### File mechanics
- Don't use the Edit tool blindly on `C:\Trezo`. Tail-truncation is real. Use bash heredoc + verify with `tail -3 | cat -A`.
- Before any large rebuild on a `C:\Trezo` file, `cp` to `/tmp` first as a backup. We lost a page once.

### Reconciliation
- Don't trust in-memory dedup sets to survive restarts. Anything that gates "did I do this already?" must seed from DB on first message after restart (the pattern shipped in Tasks #3 and #4).
- Don't close a Trezo `paper_positions` row optimistically before confirming the broker state changed. Phantom-direction-2 (Trezo says closed, Alpaca still holds) is real — today's Gap 2 fix is the template.

### Trading logic
- Never override platform settings with code constants. The capital safety rule is: read from `bot_settings`, not from Python globals. If a rule should be risk-adjustable, it goes in `bot_settings`, not hardcoded.
- Never auto-trim or auto-close an Alpaca-routed position without first cancelling the bracket legs or calling `liquidate_position(ticker)`. Half-close logic on bracket-attached positions is deferred until the bracket cancel→partial sell→re-submit pattern is properly built and tested.
- Stocks must always go through `submit_bracket_order`. There is no fallback path. If Alpaca rejects, the trade is rejected (verified Gap 3 today).

### Universe ceilings
- Don't ship a feature with a curated whitelist as its hard limit. Watchlist is personalization, universe is market-wide. Pattern Detection gets this right; Wheel is partially there (Task #6 from 6/10 closes the gap fully).

### Memory hygiene
- Don't write to `MEMORY.md` directly with memory content. It's an index only — one line per memory file, kept under 200 lines.
- Don't save protected/financial/health/credential info to memory unless Mike explicitly says "remember X."
- Memory is point-in-time. Before recommending action based on a memory claim, verify the current code/state.

### MCP / tooling
- The Cowork TaskCreate tool can leak phantom records if descriptions are too long. Keep them short and plain (~ ≤200 chars).
- Don't re-add FRED. It was reverted 6/5 because Trezo plans to redistribute → outside personal-use lane. Need a license-compatible source.

---

## 6. Exact next step

Mike's manual checklist for **tonight after market close** (4:00 PM ET):

### A0. AAPL — handled ✅
Mike queued a market sell (3 shares) the evening of 6/11; it fills at Friday's open. Root cause (day-TIF bracket legs) fixed in row 26. Section kept for history:

### A0-old. AAPL was unprotected at Alpaca
AAPL is a legitimate bot trade (Pattern Detection bullish signal, TCS 604, 6/11 9:48 AM — 3 shares @ $292.80, stop $278 / target $322). The BUG was that its bracket exit legs were day-TIF and died at the close (root cause fixed in row 26; new trades get GTC legs). This existing position still needs a one-time manual fix. Pick one:
```
[Browser]   https://app.alpaca.markets (paper)  →  close AAPL manually, or
            place a GTC stop order under it for overnight protection
[Browser]   /dashboard/paper  →  or close it from Trezo AFTER the restart
            (broker-aware close now reaches Alpaca correctly)
```
Until you do one of these, nothing will stop AAPL out if it gaps down at Friday's open. (The new naked-position alert will also nag you about it hourly once agents restart.)

### A1. Git locks — cleared ✅ (nothing to do)
Nova cleared the stale lock files directly on 6/12 night after Mike granted folder delete permission. Git is fully usable.

### A. Restart agents — DONE 6/12 evening ✅ (kept for reference)
```
[Trezo - Agents window]   Ctrl+C  →  Y  →  Enter
[PowerShell]              cd C:\Trezo\trezo-platform
                          .\start-agents.bat
```
Files loaded by restart (morning batch + second pass, same restart covers all):
- `agents/app/paper/engine.py` — new `close_position_broker_aware()`; **2nd pass:** passes `asset_type` to `liquidate_position` so crypto closes use the pair symbol instead of 404ing
- `agents/app/agents/exit_advisor.py` — wired to call broker-aware close; trim gated to internal-paper rows
- `agents/app/agents/position_monitor.py` — new `_decide_time_stop()` shared; Alpaca branch now liquidates on intraday time stop; first-reconcile-after-restart fires on tick 2; **2nd pass:** crypto rows get client-side stop/target enforcement (Alpaca crypto has no bracket) + pair-variant membership check so they never phantom-close
- `agents/app/strategies/wheel_universe.py` — `MARKET_WIDE_DIVIDEND_POOL` source #4; **2nd pass:** source #5 = stock-side `market_wide_candidates()` (Task #6 — Wheel ceiling now tracks the stock agents' universe automatically, yield gate unchanged)
- `agents/app/brokers/alpaca.py` — **2nd pass:** `crypto_symbol_variants()` helper; `liquidate_position(symbol, asset_type=)` crypto-aware
- `agents/app/paper/stocks_reconcile.py` — **2nd pass:** skips non-`us_equity` Alpaca positions so a crypto orphan can never be re-imported as a phantom stock row
- `agents/app/paper/engine.py` — **3rd pass:** NEW `trim_position()` (warn-tier half-trim; books partial P&L into account totals, trim history into `source_payload.trims`)
- `agents/app/agents/ops_watchdog.py` — **3rd pass:** fixed dead import; reads `registry` last_tick_at; NEW urgent `never_ticked` alert
- `agents/app/paper/stocks_reconcile.py` — **3rd pass:** removed nonexistent `notes` column from phantom-close update (it made the whole update silently fail); sets `exit_at` instead
- `agents/app/data/candles.py` — **3rd pass:** yfinance fallback moved off the event loop (`asyncio.to_thread`)
- `agents/app/agents/risk_manager.py` — **3rd pass:** frees `_recent_approvals` ticker when trade_execution reports a non-fill (market closed / budget / sizing / broker reject)
- `agents/app/agents/position_monitor.py` — **4th pass:** restored dropped `strat =` assignment (crash-loop fix) + naked-position alert
- `agents/app/paper/engine.py` — **4th pass:** `record_external_position` writes `broker` + `broker_order_id` columns
- `agents/app/runtime/scheduler.py` — **4th pass:** `job_defaults` misfire grace=None + per-tick timeout (`asyncio.wait_for`)
- `agents/app/brokers/alpaca.py` — **4th pass:** `get_open_orders_for()` helper

### B. (One-time) activate the heartbeat scheduled task
```
[PowerShell as Admin]     cd C:\Trezo\trezo-platform
                          .\register-heartbeat-task.bat
```
After this, every 15 minutes Windows hits `/health` and Pattern Detection recency. Toast notification after 3 consecutive failures.

### C. Toggle settings (optional, your call)
```
[Browser]  /dashboard/paper  →  Bot settings — in force (click to expand)
           Flip auto_exit_advisor: ON if you want the bot to auto-close
           urgent peak-giveback alerts (now properly reaches Alpaca)
```

### D. Verify the Wheel universe expansion
```
[Browser]  /dashboard/wheel
           Expect to see ~74 names instead of 17, with a sky-blue
           "Market" chip count in the universe header.
```

### E2. Third-pass verification (after tonight's restart)
- `[PowerShell]` `Invoke-RestMethod http://localhost:8001/agents | ConvertTo-Json -Depth 4` — every agent should show `tick_count > 0` within ~30 min (slow agents: within 2x their interval). Any `never_ticked` alert in `/dashboard` ops widget names a broken agent.
- Watchdog alive again: expect `ops_health_alerts` rows / watchdog messages instead of the old "watchdog import failed" error.
- Pre-open approves no longer poison the day: if a ticker is approved pre-open and skipped, a fresh post-open signal for the same ticker should be approvable (no "Already approved" veto without an open position).
- First warn-tier peak-giveback with `auto_exit_advisor=ON` on an internal-paper row should HALF-TRIM (quantity drops, `source_payload.trims` appended) instead of silently doing nothing.

### E. First-hour verification at next market open (Friday 9:30 AM ET)

Watch the `[Trezo - Agents window]` log for the new lines proving today's fixes are active:
- `engine.broker_aware_close.alpaca_liquidate_ok` — Exit Advisor successfully sold at Alpaca (only fires if auto-exit triggers; harmless if absent)
- `"Intraday time stop (max_hold_90min) - Alpaca position closed at market"` — time stop firing on an Alpaca row
- `event=stocks_auto_reconcile, closed=N` — first reconcile happens within ~1 min of restart (was 60 min)

### F. After the next session

~~Task #10 + Task #6~~ — both done in the 6/11 second pass. Third-pass readiness audit added rows 13-18 above. Next priorities, in order:
0. ~~Dark-agent diagnosis~~ — SOLVED 4th pass (rows 18-21). After restart, verify with `[PowerShell] Invoke-RestMethod http://localhost:8001/agents | ConvertTo-Json -Depth 4`: every agent should show tick_count > 0 within 2x its interval, and the Wheel (options_scanner) should emit its first-ever message within ~30 min.
1. **Crypto fix live verification** — first Alpaca-routed crypto trade after restart: watch for client-side stop/target close messages (`reason="stop"/"target"`, `broker="alpaca"`, crypto ticker) and confirm no `alpaca_external` phantom close on tick 1.
2. **Trim on Alpaca-routed positions** — bracket cancel → partial sell → re-submit pattern (deferred from Gap 2).
3. **#75** Alpaca WebSocket lifecycle; **#77** forex data source pick.
4. **#45/#51** UI passes (Sim Lab rows + Wheel universe display — expect MORE than ~74 names now that source #5 is live; chip label reuse means no UI change required, but eyeball it).

---

## Quick reference — service health one-liners

```
[PowerShell]  Invoke-RestMethod http://localhost:8001/health
              # 200 OK → bot is alive
              # connection refused → agents service is dead, restart inline

[PowerShell]  Invoke-RestMethod -Method Post -Uri http://localhost:8001/stocks/reconcile | ConvertTo-Json -Depth 5
              # Force a stocks reconcile right now. Use when Trezo shows
              # open positions that aren't on Alpaca (phantom-direction-2).

[Supabase SQL]
  SELECT ticker, side, quantity, entry_price, strategy, status, broker
  FROM paper_positions
  WHERE user_id = (SELECT user_id FROM paper_accounts LIMIT 1)
    AND status = 'open';
              # See what Trezo thinks is open.
```

---

## Glossary

- **Bracket order:** Alpaca order with three legs — entry (market or limit) + take_profit (limit sell) + stop_loss (stop sell). When the entry fills, the two exit legs go live as a one-cancels-other pair. The broker handles the sell side; Trezo just tracks state.
- **Phantom position (direction-1):** Position exists at Alpaca but not in Trezo's `paper_positions`. PositionMonitor inserts it with strategy="reconciled".
- **Phantom position (direction-2):** Position exists in Trezo's `paper_positions` (status="open") but not at Alpaca. PositionMonitor closes it with note "phantom position closed by 30-min stocks reconciliation tick."
- **TCS:** Trezo Confidence Score (0-1000). Pattern Detection emits one per signal. Risk Manager's tiered staleness uses it.
- **Tier:** options trading tier label by contract count — low-tier (≤3) targets 30-50% gain, mid 15-30%, high 15%. Drawback ladder 39→30→25%.
- **Future Index Account:** Trezo's name for the OBBB child account (never call it the "Trump account"). Used for Phase 9 KINDRIP.
- **Layer 5 = Dividends:** umbrella name. YieldMax is one aggressive sub-strategy inside Layer 5. NOT the same as Layer 4 Wheel.

---

*This document supersedes any outdated handoff notes. When in doubt, check `git log` for code reality, and `spaces/.../memory/` for Mike's preferences and prior decisions.*
