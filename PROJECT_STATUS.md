# Trezo — Project Status Handoff

> **2026-07-01 review (Nova) — full audit: where trades go, why the pockets are invisible, re-eval status.**
> **Broker truth (Alpaca PA3PR4F6ZFWZ):** equity $4,816 / cash $2,846 / BP $4,670. Open: GM, MRK, SOFI, PYPL-short (DB) + KMI 7/17 30.5 CSP (broker-held). Jun-30 realized -$73 (WMT stop -$61, PYPL -$12); Jul-1 = ZERO broker orders.
> **Findings:** (1) Per-asset ALLOCATION POCKETS are LIVE engine-side (paper/allocation.py, growth posture: stocks $2.17k/crypto $1.69k/options $482/income $482; trade_execution._allocation_gate enforces) but INVISIBLE — the nav "Capital Sleeves" page calls /sleeves/snapshot which no longer exists (sleeves.py = dead code since the 6/18 revert; no backend route). Stocks pocket ~full ($2.09k/$2.17k) = why Jul-1 went quiet; crypto/options/income pockets IDLE for a week (all entries since 6/24 are stocks). (2) ACTIVITY LOG has ZERO call sites since the 6/18 revert (module committed 6/19 but never re-wired; last file logs/activity-2026-06-18.jsonl) — root cause of "can't tell what the agents are doing". (3) RE-EVAL ENGINE is ON (flag loaded at the ~6/30 15:30 restart) but 0 logged actions — correct per its triggers (stale 3d / rotate 7d / tighten-after-peak-giveback; positions were 1d old) AND it does NOT re-score TCS/IV on held trades (feature gap Mike expected); it only logs when it acts. (4) SLIPPAGE: 5bps fill model + crypto net-edge gate LIVE; the rules-doc slippage HALT was deferred in killswitch.py and never built. (5) MEM0 budget HEALTHY — correction: .env caps (1500/day, 10k/wk, 5k searches) ARE loading (week counter 2,551 past the old 2,500 default proves it); usage 2,551/10k wk. A once-a-day warn line now fires if it ever truly exhausts. (6) BUG: closed_manual rows CZR/CSCO 6/30 recorded realized $0.00 (phantom-close pattern lives on in the manual-close path) -> corrupts learning-loop outcomes AND paper_accounts week_realized stayed $0 despite -$48 real => weekly kill-switch can never fire. (7) bot_settings (Mike): tcs_threshold 450, max_open 20 — not the blocker.
> **2026-07-02 build (Nova) — memory efficiency + pockets UI + reconcile P/L fix (on top of the 7/1 visibility pack).**
> **Token-lean memory (Mike's ask):** mem0_client gains (a) a BATCH DIGEST buffer — `queue_note()` collects shorthand observations and flushes them as ONE combined Mem0 add per window (25 items / 15 min, env-tunable); risk-manager vetoes now ride it; (b) client-side DEDUPE — identical (agent,action,ticker) adds within 30 min are skipped before spending budget; (c) SHARED-RECALL CACHE — identical `recall_similar` queries within 180s share one search across agents; (d) compact `_format_decision` (reasoning capped at 200 chars, metadata trimmed). Expected: ~60-80% fewer Mem0 calls/tokens at same or better recall.
> **Pockets UI:** new GET `/allocations/snapshot` (mirrors the trade-execution gate math exactly) + the old dead Capital Sleeves page repointed to it — nav is now "Allocation Pockets", 4 cards (Stocks/Crypto/Options/Income) with budget/deployed/free bars. tsc+eslint 0 errors.
> **Reconcile P/L fix:** stocks_reconcile no longer books $0 — it recovers the TRUE exit fill via new `get_recent_closed_orders()` (brokers/alpaca), computes realized, rolls today/week/ytd counters (cash untouched), and activity-logs each reconcile close. Healed the 6/30 rows live: CZR +$1.21, CSCO +$6.15; week counter backfilled from rows (-$40.85).
> **Known follow-ups:** (1) external-position closes (broker stop fills) still don't roll account counters at close time — RIGHT fix is kill-switch summing the week's rows instead of trusting counters; (2) TCS/IV re-score on held positions NOT built yet — no shared scorer exists (TCS is computed inside pattern_detection picks); design = expose a `rescore_ticker()` from pattern_detection, call from reevaluator with cooldown, act on thesis-collapse; (3) internal-ledger equity (cash+vault $2.8k) drives pockets while Alpaca equity is $4.8k — the pockets page makes this drift VISIBLE now; decide whether pockets should key off broker equity.
> **2026-07-14 #6 (Nova) — SAME-DAY OPTIONS lane (Mike: "bought early enough I would make the 30 percent really quickly; if not I would have to sell because it would reverse way too fast").**
> Split-brain design: ENTRIES in options_scanner `_run_same_day` (tick step 7; its 30-min heartbeat is fine for a morning-only window) — 9:35–11:30 ET only (13.58–16.5 UTC union, DST-naive), candidates = SPY/QQQ (true same-day expiries) + top-8 generals ranked by TODAY's move (forming daily bar), require |move| ≥0.8% (TREZO_DAY_OPT_MIN_MOVE) + volume pace ≥0.4× avg20, strike leans ITM ("at the line"), pick must be ≤5 DTE, budget = min($100 TREZO_DAY_OPT_USD, 2.5% eq) up to 2 contracts, ≤1 open (TREZO_DAY_OPT_OPEN), ≤2 entries/day, **PDT-aware: under $25k equity, skips when daytrade_count ≥3 (never spends the last slot; `option_day_skip` logged)**. EXITS in position_monitor `_manage_day_options()` on its 60-SECOND tick (options scanner too slow for 0-DTE): +30% fast take (TREZO_DAY_OPT_TP), −25% reversal cut (TREZO_DAY_OPT_CUT, "no comeback hoping"), 3:45 PM ET force-close (19.75 UTC; closes blind at entry if quote gone), one-shot per row with retry-on-error; realized books via the reconcile fill-recovery within 30 min. Rows: strategy `option_day`, notes carry the rule + entry stats. Knowledge note + docx gain the Same-Day card (LIVE). Kill switch TREZO_DAY_OPTIONS=0.
> **2026-07-14 #5 (Nova) — GOAL-AWARE EXITS (Mike's correction: "the credit has to be worth the profit, not the 22 percent... I go for the daily goal of making money instead of a percentage").**
> (1) SPREAD GATE now DOLLARS: credit ≥ TREZO_SPREAD_MIN_CREDIT ($20 — a real bite of the $50 rung) + 10% pennies-vs-wing sanity floor (22% ratio test removed); live-net must also clear ~$16. (2) LONG take-profit is COMPUTED, not fixed: tp% = (daily goal − realized today) / position cost, clamped 10–40% (TREZO_OPT_TP_MIN/MAX) — 3 contracts need ~⅓ the percent of 1; goal_state() feeds it live. (3) STEP-DOWN scale-out: multi-contract winners sell half (round up) at the goal-aware target — ROI banked, row shrinks (contracts + net_premium rescaled), slice booked as closed_partial at the limit price, remainder reaches for a higher % (harvest key includes contract count so each step re-arms). Cuts/-50%/DTE≤3/Greek-turn exit IN FULL. (4) GREEK-TURN rule: profitable (≥+5%) long whose underlying moves ≥0.5% AGAINST it that day → bank immediately ("when the Greeks start to turn in drawdown I take the profit and look for the next trades"). Knowledge note + docx doctrine rewritten to match. Env: TREZO_OPT_FAST_CT retired in favor of the computed tp.
> **2026-07-14 #4 (Nova) — MULTI-LEG EXECUTION LIVE + Mike's day-trade doctrine (15% fast-take, volume lens, multi-contract).**
> **Spreads fire for real now:** new `submit_mleg_order` (brokers/alpaca, order_class=mleg, one ticket; limit negative=credit per Alpaca convention) + options_scanner `_run_spreads` (tick step 6): credit spread WITH the trend on the strongest general (bull put if leading up, bear call if down, |3d|≥2.5%) or IRON CONDOR on SPY when the tape is quiet. Guardrails: Level 3 required, market-clock gate, max loss ≤ TREZO_SPREAD_RISK_USD ($150 — wings are the stop), ≤1 open (TREZO_SPREAD_OPEN), 1 new/day (`_spread_fired`), credit ≥ ~22% of wing, every leg resolved to a REAL listed contract via live_option_pick and the LIVE net must still be a credit; butterfly ratio legs merge (1-2-1). Rows: full legs json; hourly re-score SKIPS multi-leg rows (expiry-managed by design); reconcile books realized from fills. `option_spread_open/blocked` activity. Butterfly + bull call spread (debit plays) stay proposal-only. (2) **15% FAST-TAKE:** re-score long exits now +15% when holding ≥3 contracts (TREZO_OPT_FAST_CT; Mike: "3 contracts × $15 = $45, close to the 1% needed") else +40%; −50%/DTE≤3 unchanged. (3) **VOLATILITY+VOLUME lens (Mike: "I usually purchase based on the volatility and volume"):** directional candidates ranked by |3d| across ALL generals (down-leaders reachable for puts), REQUIRE volume ≥1.2× 20-day avg (TREZO_LONG_OPT_VOL_RATIO); activity lines cite the volume ratio. (4) **MULTI-CONTRACT:** cheap contracts buy up to 3 (TREZO_LONG_OPT_CT_MAX) inside the same $120/3%-equity budget — feeds the fast-take. Docx status chips refreshed (spreads/condor now LIVE).
> **2026-07-14 #3 (Nova) — the OPTIONS STRATEGY MENU completed (Mike: "I do not see iron condor, naked calls or butterflies").**
> Truth found: build_iron_condor / bull_put_spread / bull_call_spread already existed in `strategies/options_strategies.py` but never reached the reference doc, and `_options_ideas` only surfaced five builders. ADDED: `build_butterfly` (1-2-1 call fly, debit = max loss, max gain = wing − debit), `build_bear_call_spread` (the DEFINED-RISK expression of a naked-call thesis), `build_long_put`; ideas feed now surfaces the FULL menu (8 builders) with credit/debit, max gain/loss + Greeks; Greek filter treats bear_call_spread as premium-sell. Smoke-tested with synthetic candles (condor $77 credit/$409 wing risk; fly $65 debit/$226 max — coherent). NAKED CALLS: Alpaca tops out at Level 3 (defined-risk spreads; no uncovered calls at retail) — documented, not traded; bear call spread is the sanctioned twin. Knowledge note `research--options-strategy-formulas.txt` (force-added past the library gitignore; Nova-authored) gives agents citable formulas + exit doctrine. NEW DOC: `C:\Trezo\TREZO_OPTIONS_STRATEGY_REFERENCE.docx` (4 pages: how-to-read, 5 income + 4 directional strategies w/ formula blocks + LIVE/PROPOSAL status, naked-call note, comparison table). Multi-leg EXECUTION (spreads/condors/flies as real orders) = next options phase. Main formula docx refresh still queued.
> **2026-07-14 #2 (Nova) — the FULL OPTIONS DESK (Mike: "not just cash-secured puts... collect the premium and avoid waiting for the contract to complete") + the $0-realized answer + generals to 10.**
> **Why every settled row said $0:** options reconcile closed any leg missing at the broker with hardcoded `realized: 0.0` — so the 7/7 wipe ghosts AND the real 7/8 buy-backs all booked zero, and repeated wipe/restore cycles left 93 DUPLICATE ghost rows. FIXED in code (reconcile now recovers the closing fill via get_recent_closed_orders(OCC) and books credit−debit for shorts / proceeds−debit for longs) and HEALED in DB (108 $0 rows → 15; real buy-backs backfilled: HPQ 20.5P −$5, F 13P −$24).
> **New desk capabilities (options_scanner):** (1) EARLY PREMIUM HARVEST — hourly re-score now FIRES real buy-to-close limits when a short leg has earned ≥60% of max profit (TREZO_OPT_HARVEST_AT 0.40 ratio) or ≥35% inside 5 DTE; reconcile books exact realized when it clears; activity `option_harvest`; one-shot guard per row id (in-proc set `_harvested`). (2) LONG CALLS/PUTS (`_run_directional`, tick step 5): buys 1 ~ATM ~30-DTE contract on sector GENERALS moving ≥2.5%/3d — debit ≤ min(TREZO_LONG_OPT_USD $120, 3% equity) = defined max loss; ≤2 open (TREZO_LONG_OPT_OPEN), 1/underlying/day, 1 new/tick, needs Alpaca options level ≥2, kill switch TREZO_LONG_OPTIONS=0; rows strategy long_call/long_put with net_premium_usd NEGATIVE (settle-at-expiry books −debit naturally); activity `option_long_open`. (3) Long exits in the same re-score: +40% harvest / −50% cut / DTE≤3 time exit (sell-to-close limit). Covered calls: wheel_cc lane already exists, fires on assignment. (4) GENERALS ×10 per sector (Mike: "just two keeps the agents narrow") — full curated benches for all 14 ETFs; compass measures the leading-3 sectors' entire benches daily; top 6 generals ride every scan pool.
> **2026-07-14 (Nova) — BREAKOUT PROBATION (never paused again), regime-bump rescale bug, and the sector GENERALS.**
> Mike saw "PAUSE: Breakout" on the Regime playbook card and asked for it active ("it helps with the opening of the market and gives a foundation"). (1) NEW PROBATION TIER: RegimePlay gains `probation` — breakout moved out of `pause` in ALL four regimes that blocked it (choppy, high_volatility, trending_down, risk_off). Probation = never vetoed: +10 TCS bar + HALF size (risk_manager parses playbook by scope.regime → probation_bump into effective_min_tcs, `size_scale: 0.5` on the approval; trade_execution honors size_scale after the coverage cap; veto reasons show "breakout probation +10 half-size"). Other family pauses (momentum/income/event_driven in downtrend/risk-off) unchanged. Web mirror updated (strategy-library.ts + 4-column playbook card: Favor / Trade smaller / Probation — half size / Pause). (2) **BUG FOUND: `_REGIME_POSTURE` tcs bumps were still 1000-scale** (choppy +25, risk_off +150 on a 0-100 bar — missed in the 7/11 sweep; part of Monday's veto flood). Rescaled: 0/0/3/5/8/15, MAX_TCS_BUMP 150→15, fallback (0.85,3). (3) GENERALS: SECTOR_GENERALS map (2 megacaps per sector ETF); sector_compass computes 1d+3d moves for the leading 3 sectors' generals → SECTOR_BIAS["generals"], daily "generals of the leading sectors" activity line, and the top 4 generals ride the scan pool right behind the sector ETFs — the agents see what the industry leaders are doing and evaluate them for entries. Restart loads it.
> **2026-07-13 #3 (Nova) — the KNOWLEDGE LIBRARY (Mike: "resources for the agents so they do not have to figure out everything on their own").**
> New `app/knowledge/library.py`: local, free, instant full-text search over `agents/knowledge/library/` (page-tagged chunks, token-overlap scoring + phrase boost, auto-reindex when the folder changes). `scripts/build_library.py` downloads the manifest (Rockwell Complete Guide to Day Trading, MarketTraders Ultimate Checklist, Aziz Advanced Techniques — publisher-hosted copies only; the epdf/archive.org "Trading for a Living" mirror was EXCLUDED as pirated — if Mike owns it he can drop his own PDF in the folder) and pypdf-extracts every PDF in the folder, so Mike grows the library by dropping files + rerunning the script. Wire-ins: (1) every APPROVAL's thesis card gains `playbook_note` — one cited line ("<book> (p.N): …") from the best-matching passage; (2) GET `/knowledge/search?q=`. Deliberately NOT Mem0 (books are static reference; would torch the budget). Books gitignored (script rebuilds). Mike's paste: pip install pypdf → `-m scripts.build_library` → restart. Verified: sample doc indexed/searched/ranked correctly in-sandbox; downloads must run on Mike's box (sandbox egress is allowlisted).
> **2026-07-13 #2 (Nova) — the DAILY INCOME GOAL ladder (Mike: "try to make 50 bucks a day as a goal, then move to standard averages of working employees").**
> New `paper/daily_goal.py`: rungs $50 grind → $110 steady (~$28k/yr) → $225 living wage (~$58k/yr) → $293 six-figure pace (Mike's marker) → $480 comfortable (~$125k/yr). Active rung = highest rung ≤ equity × TREZO_GOAL_MAX_PCT (default 1.5%/day — Mike's stated safe band; verified: $4.7k→$50 @1.05%, $15k→$225 @1.5%, $20k→$293 @1.47%, $32k→$480). TREZO_DAILY_GOAL forces a number. Realized-today from the kill-switch's 30s row-sum cache (fallback: own query, 60s cache); equity via allocation.effective_equity (broker truth). **BEHAVIORAL CONTRACT (never weaken): the goal never loosens a gate.** Two hooks only: (1) risk_manager — once today's goal is banked, `goal_bump = +5` TCS on new entries ("protect the paycheck"; one clean `daily_goal_hit` activity line, veto reasons show "goal-banked +5"); (2) position_monitor `_step_check` — behind goal after 2 PM ET → first profit-step trigger ×0.85 (bank a touch earlier; never later, never bigger). No revenge pressure by design. New GET `/goal/today`; Overview hero (atom card) gains a third stat: realized/$goal with progress bar + rung label (emerald when hit). tsc+eslint+py_compile clean.
> **2026-07-13 (Nova) — live-Monday batch: atom hero, STMS full session, Sector Compass, wider crypto/forex — and the ETH orphan incident (found + fixed).**
> **CRYPTO SUBMIT BUG (the day's real find):** brokers/alpaca `submit_crypto_order` compared `_post`'s whole `(json, error)` TUPLE to a dict → every ACCEPTED Alpaca crypto order was mislabelled `unexpected_response` = broker reject. Today: 3 ETH/USD buys all FILLED (13:24/13:26/13:29Z, ~$708 each) while the engine logged 3 rejects → session kill-switch halted the whole desk (the TSLA/NOK/MIMI "held back" lines) AND the retries stacked an untracked 1.199 ETH (~$2,120 ≈ 45% of equity, no stop, no book row; a 4th try died on real 403 insufficient-balance). **Fixed** (`9930c3b`: unpack the tuple; success now flows to record_external_position) and **orphan flattened at the broker** by Nova: sold 1.199212818 ETH @ $1,769.48 (~+$1 realized; buys avg ~$1,768.6). Broker again holds only tracked names (BITO, SPDN, F 12.5P short). Restart clears the in-process reject counter.
> **Batch (`3f3a807`):** (1) OVERVIEW ATOM — the landing CSS-3D atom replaces the flat-ring hero, driven by live layer state: lit shell + two counter-orbiting electrons = lane holds a position; idle = faint ring + one slow ember; chips/count now /L.length. FUTURE (Mike): orbs become clickable navigation replacing the side column. (2) STMS = FULL SESSION 7:00 AM–4:00 PM ET (Mike: "up till 4 when the market closes") — proper window restored in stms.py (11–21 UTC) + scanner/selector gates re-enabled (the 7/11 `if False` hack retired); /paper Strategy-windows card matches. (3) SECTOR COMPASS — daily 3-day industry movers, Mondays add the 5-day weekly read, ~every 21 days a monthly market update (ops_watchdog daily block; 14 sector ETFs incl. SMH/XBI/GDX via fetch_stock_candles). Lands in activity log (`sector_compass`) + Mem0 queue_note; SECTOR_BIAS leaders ride the front of every expanded_scan_pool so scanners look where the market is moving (breakdown gains `sector_leaders`). (4) FOREX +5 crosses (USDCHF/EURGBP/EURJPY/EURCAD/EURAUD — Kraken OHLC). (5) CRYPTO +5 liquid majors (DOGE/LTC/LINK/DOT/AVAX; COIN_PARAMS tuned, CoinGecko ids, Kraken XDGUSD). Answered Mike: modeled crypto/forex fills already price from LIVE Kraken OHLC (venue-true prices, modeled fills w/ fee+slippage) — accuracy was never the gap, breadth was.
> **2026-07-11 (Nova) — ONE SCALE (TCS 0–100), quick-take tiers, STMS all-day.**
> **TCS converted 1000→100 platform-wide** (Mike: "keep all the scaling and scoring to 100 so we don't have to figure out why some stuff is at 1000"): scoring.py divides at the source (components now 30/25/20/15/10); every floor ÷10 — Bot Tuning default 70, STMS 75, Extended 70, pattern 70, crypto 65, coverage 40 (.env updated), rotation <55, cycle bumps 5/15, friction 80/threshold, reeval bar 70, confidence /100 (9 sites); scope-adjustment tcs_bump rows ÷10 (12 rescaled). ⚠️ bot_settings has a CHECK constraint rejecting values <100 — **Mike must run the one-paste SQL** (drops/re-adds constraint AND converts his saved 500/450 → 50/45 in the same stroke) BEFORE restarting, or thresholds stay impossible on the new scale. Historical rows' stored tcs stay 1000-scale (transitional: rotation/learned reads treat them as strong until they close).
> **5.1 tier table compressed to quick-take** (Mike: "2% of $1,200 taken beats waiting on 7%"): targets ×0.65 mega / 0.70 ETF / 0.75 large / 0.80 mid+small+micro / 0.85 unknown; stops keep protective width; NEW global R:R harmonizer in risk_manager (after ALL target compression, stop follows to keep R:R ≥ floor — 7/6 lesson enforced on every path). **Scalp eligibility extended to mid+small** (ATR geometry covers the spread toll; micro stays with STMS). **STMS runs ALL DAY** (window gate + 11AM force-stop + selector eligibility gate retired; only ORB keeps a time window per Mike). Reference docx REGENERATED to match.
> **2026-07-08 #4 (Nova) — the ACCOUNT-SIZE POSITION CURVE (Mike's correction: don't ENTER big trades small).**
> "I do not want the agents taking big trades — a small account can not afford that move for long; with $20k it can rely on 1-2% profits on $5-10k trades." New `allocation.position_pct_for_equity`: per-trade notional cap = 15% of equity under $10k (≈$710 on today's account — no more $1k-heavy entries), 30% at $10-25k (the $20k account's $5-6k quick plays), 25% to $100k, 15% beyond. Wired as the DEFAULT in sizing.plan_position (user's bot_settings.max_position_pct slider still overrides) + the trade_execution broker-armor cap. The 7/8 big-trade velocity EXIT profile stays as the safety net for anything that grows past $900 notional. TREZO_MAX_POSITION_PCT forces a flat cap.
> **2026-07-08 #3 (Nova) — big-trade VELOCITY profile on the profit ladder.**
> Mike: "a $1k trade waiting on 10% locks $100 of probability -- take 5%, free the capital, catch the next 3%: ~$80 REALIZED in a day beats $100 maybe." Positions with notional ≥ TREZO_BIG_TRADE_USD ($900) now step EARLIER (first bank at 40% of the run vs 60%) and BIGGER (60% of remaining vs 50%) on BOTH the modeled and Alpaca ladders (`_step_profile`; per-position at0 override in `_step_check`; fraction threaded through `_alpaca_profit_step`). Small positions keep the standard ladder. Freed capital recycles through the pockets automatically. Env: TREZO_BIG_TRADE_USD / _STEP_AT / _STEP_FRACTION.
> **2026-07-08 #2 (Nova) — SELF-CALIBRATING TARGETS + rotating market universe (Mike's evening asks).**
> **Learned targets:** new `learning/target_calibration.py` — per (strategy) lane, the median PEAK move (max favorable excursion, from the rows' peak_price) across the last 20 closed trades becomes a target CAP in the risk manager's formula layer: if trades have only been reaching ~2%, the 10% ask compresses to the earned number (then the stop re-scales via the existing R:R-consistency step). Fail-open under 5 samples; 1h cache; env TREZO_LEARNED_TARGET_* ; approval reasons say "learned from N recent trades".
> **Rotating universe:** market_universe now pulls most-actives DEEP (top 60), keeps the head 12 + an hour-rotating 13-name window from the tail — different liquid names cycle through the scan pool all day instead of the same leaders every refresh (Mike: "I see the same stocks keep getting triggered"). Watchlist staleness ruled out: scanners ride the live movers/actives pool + cf's own watchlists; the recurrence was the static top-of-book. RESTART to load.
> **2026-07-08 (Nova) — Alpaca RESTORED the wiped positions + Mike's concentration rules + modeled lanes visible.**
> **Morning:** Alpaca reversed the 7/7 wipe (same entries restored); reconciler re-imported CSCO/BITO 8:49 AM; 3 CSP rows reopened; SNDQ 265@3.57 = the engine's own 7/7 buy. Books = broker 6/6. Healed: zeroed phantom realized on 4 stock + 6 option wipe-day rows. **Midday:** SNDQ stopped out (+50 gave back) → daily kill-switch -3.2% halted the day correctly. Mike's directives → (1) BOUGHT BACK HPQ 20.5P + F 13P (limit orders queued for 9:30 open; frees ~$3,350 collateral, leaves only F 12.5P); (2) **posture-scaled WHEEL LIMITS** in options_scanner: growth = 25% collateral / 1 CSP / ≤21 DTE, balanced 40%/2/35d, income 50%/3/45d (env: TREZO_WHEEL_COLLATERAL_PCT/_MAX_OPEN_CSP/_MAX_DTE; `wheel_limit` logged) — "a small account should not lock capital 30 days across 3 trades"; (3) **modeled lanes visible on Overview**: forex → new layer-8 card, layer cards now show "N open · (modeled)" even at $0 P&L (they used to hide as "No position today"), forex rows no longer lump into Stock. tsc+eslint clean. NEXT per Mike: outcome-weighted pockets (allocation follows strategies with proven positive results) — designed, needs sim-lab data.
> **2026-07-07 #2 (Nova) — Supabase diet: 266k → 14k rows + the regrowth can't happen again.**
> Mike's infra screenshot showed the nano instance pinned (CPU ~100% spikes, RAM 50-75%). Root cause = the June-4 disease regrown: agent_messages at 266,874 rows (252k older than 48h; the TTL janitor was queued as Task #56 on 6/4 and never built). PURGED live in batches to 14,106 rows. Permanent fixes: (1) ops_watchdog now runs a DAILY janitor (delete >48h, logs `db_janitor`); (2) telemetry DIET in persistence.persist_message — idle heartbeat rows (scanner pulses with 0 fires, "Position check", "scan complete" notes) persist 1-in-5 per agent, real news always persists; (3) kill-switch row-truth sums CACHED 30s/user (check_all runs per signal — during the 7/7 veto storm the uncached sums hammered the DB). Forex constraint SQL was RUN by Mike (success) — forex can now persist. RESTART still pending (no orders since the halt; restart resets the reject counter AND loads 7/7 armor + diet).
> **2026-07-07 (Nova) — the "vanished positions" morning: diagnosis + armor.**
> **What happened (broker truth):** overnight, Alpaca paper PA3PR4F6ZFWZ WIPED all positions with ZERO closing orders/activities — cash preserved to the penny ($3,791.54); the "-$1,066" was just the mark value of wiped holdings (CSCO/BITO/OPEN + 3 short puts) evaporating, NOT trading losses (realized from cleanup: ~-$5 total). Then at the open: SOXS 422 (take-profit rounded INTO base price) + SOXS/TZA 403s → 3 rejects → session kill-switch → 4,091 noise vetoes all day. Reconciler cleaned the ghost rows at 10:11 with recovered prices (the 7/1 fix worked).
> **Armor shipped:** (1) bracket sanity clamps — TP ≥ base+max(0.01,0.1%), stop ≤ base−tick (no more 422 storms); (2) notional cap at max_position_pct×equity AND 90% of BP (tight ATR stops had exploded risk-based sizing past buying power); (3) ghost-reconcile now RESETS the broker-reject counter (`halt_cleared` logged) — the halt clears the moment its cause is cleaned; (4) `POST /admin/clear-session-halt` for one-click manual recovery (day/week capital halts untouched); (5) kill-switch veto LOGGING throttled to 1/10min (veto still enforced — the feed stays readable).
> **Found: forex trades were never persisting** — paper_positions CHECK constraint rejects asset_type='forex' (Postgres 23514 on USDCAD). Mike must run the one-paste SQL (Supabase SQL editor) to widen the constraint; until then forex signals approve but can't book.
> **2026-07-06 #3 (Nova) — the WHEEL IS ALIVE (3 real CSPs!) + options join the Overview + collateral cap.**
> After the R:R fix + identity migration the platform TRADED: CSCO/BITO/OPEN stocks + THREE cash-secured puts (F 7/31 12.5P, HPQ 7/31 20.5P, F 8/7 13P) — fill_slippage lines (+20bps/-3bps) and the AAL 403 visible end-to-end in the feed. Remaining gaps fixed: (1) **Overview now folds options_positions in** (they were invisible — the page only read paper_positions): OCC-matched against Alpaca's positions for mark-to-market P/L, wheel_* → layer 5, directional → layer 3, collateral counted in open risk (tsc clean). (2) **Wheel collateral allowance** (decision made live — 3 CSPs had reserved ~95% of equity, $0 BP, stocks 403ing): total open CSP collateral capped at TREZO_WHEEL_COLLATERAL_PCT (50%) of equity; skips log `wheel_collateral_cap` + agent message; client scope via runtime settings _supabase. NOTE: existing 3 CSPs stay (over the cap already) — the cap prevents NEW ones until they roll off.
> **2026-07-06 #2 (Nova) — the approve→execute KILLER + ONE-IDENTITY migration (UI finally = engine).**
> **R:R collision (my bug, found via Mike's screenshot):** the 7/2 realistic-target cap shrank targets to ~1.5x ATR but left stops at strategy defaults → reward:risk ~0.9 < the 1.5 sizing floor → **every approval since 7/2 died in sizing** ("Reward:risk 0.91 below your 1.5 floor"), invisible to the activity feed (execution errors weren't logged). FIXED: when realism caps the target, the stop scales to keep R:R >= cfg.min_reward_risk (floored at 0.5x ATR + 0.4% so noise can't wick it) — tight target ⇒ tight stop, Mike's geometry; and BOTH _err closures now log `execute_error` to the activity feed so the approve→outcome chain can never go dark again.
> **IDENTITY UNIFIED:** engine data migrated fd5292e9 → cf1b0460 (the web login) while the book was flat: paper_accounts 1, paper_positions 79, options_positions 80, trade_outcomes 62 rows moved; watchlists hit a 409 name-conflict (cf already owns watchlists — fd's 6 remain dormant; merge later if wanted). With settings single-row (cf) + data on cf, the UI (RLS as cf) now sees EVERYTHING the engine does: Overview week P&L, layers, positions all light up. The engine iterates users from paper_accounts → now trades AS cf.
> **2026-07-06 (Nova) — SETTINGS DRIFT solved: one settings row, sync-with-reasons, audit tells the truth.**
> **Root causes from Mike's audit screenshot:** (1) the web app saves the SIGNED-IN user's bot_settings row (`cf1b0460…`) while engine signals carry the paper-engine user (`fd5292e9…`) — per-user consumers read the OLD row, so Bot Tuning edits never reached the trades; (2) the audit's "agent" side sits behind the 30s settings cache, so auditing right after saving shows phantom drift everywhere.
> **Fixes:** SINGLE-ROW MODE — `TREZO_PRIMARY_USER_ID` (agents/.env, set to the web user's row) + TREZO_SETTINGS_SINGLE_ROW (default on) make EVERY get_bot_settings() call resolve to that one row; `clear_settings_cache()` added; the audit endpoint now compares against the SAME primary row; NEW `POST /admin/settings-sync` clears the cache, re-audits, and explains residual drift ("survives sync = env override or hardcode — report the field"); Bot Tuning page gains a **"Sync agents now"** button beside Run audit (tsc+eslint clean). Bot Tuning saves now reach every agent within one tick / 30s automatically — no restart needed for settings anymore. RESTART needed once to load this code (task: Stop/Start-ScheduledTask TrezoAgents).
> **2026-07-02 afternoon #3 (Nova) — STRATEGY COVERAGE MODE + trade THESIS cards (Mike's test plan).**
> **Coverage mode (ON via TREZO_COVERAGE_MODE=1 in agents/.env):** TCS floor drops to 400 (TREZO_COVERAGE_TCS); a strategy with NO paper_positions row EVER gets its first signal tagged `coverage_trade` → exempt from pocket skips and sized tiny (~TREZO_COVERAGE_TRADE_USD $150: whole-share cap on Alpaca stocks, fractional on crypto/exchange, risk-shrunk in the modeled engine) → every strategy gets ONE small live labeled trade instead of waiting. Logged as `coverage_trade`; flip the env to 0 after the lanes have data.
> **Thesis cards (ALL approvals, not just coverage):** approve_payload["thesis"] = {why (strategy/TCS/pattern/tier), exit_watch (target/stop + intraday rules or hourly re-score), if_with_us (profit-step ladder + trail), if_against_us (hard stop, TCS-collapse rotation, -3% daily kill-switch)} — persists on the position row via source_payload (Trading page "why held" can render it) + one `thesis` activity-log line per trade. RESTART to load.
> **2026-07-02 afternoon #2 (Nova) — PRIORITY CAPITAL: trades compete for scarce room (Mike's direction).**
> (1) **Small-account soft pockets:** below TREZO_HARD_POCKET_MIN_EQUITY ($25k) every lane's budget stretches by TREZO_SMALL_ACCT_POCKET_STRETCH (1.75x, capped 60% equity/lane) — pockets act as WEIGHTS at low equity and harden to exact fractions at size (matches the original vision: small = aggressive income grind, large = conservative structure). Stacks with the intraday overflow. (2) **Priority rotation:** when live demand keeps hitting a FULL lane, the lane's weakest stale hold (36h+, entry TCS <550) gets close_requested (the existing manual-close flow position_monitor honors) — capital recycles to stronger fresh signals; income lanes never rotated for fast lanes; max 2/day; logs `priority_rotation`. (3) **Forex refresh 600s → 180s** (= crypto cadence). STILL DESIGNED-NOT-CODED: account-size strategy-preference curve (fast-lane weighting at low equity, conservative at size) — wire after sim-lab data accumulates; wheel CSP collateral allowance awaits Mike's sign-off.
> **2026-07-02 MIDDAY LIVE-TAPE FIXES (Nova) — why no scalps/options + the Overview finally tells the agents' story.**
> **Live diagnosis (DB truth; the sandbox's file-mount view went STALE ~5:34 AM — use Supabase/Alpaca for intraday truth, files after close):** restart CONFIRMED (approve payloads carry cap_tier; forex scans 5 pairs; crypto scanning). Agents approved TSLL/BITO/TZA/PYPL repeatedly all morning — every one skipped: "stocks budget used up under growth posture" (GM+MRK+SOFI swing holds fill the $2k stocks pocket 100%). Options: ideas scored WITH Greeks + wheel_auto_execute=true, but 10% pockets ($482) can't fund any CSP collateral. So: agents fine, POCKET SIZING starves intraday + options lanes on a small account.
> **Fixes shipped:** (1) INTRADAY OVERFLOW — scalp/orb/stms entries may run the stocks pocket over by TREZO_INTRADAY_OVERFLOW_PCT (25%) since they self-liquidate by 3:45; (2) liquid ETFs (SPY/QQQ/TQQQ/SOXL/BITO/TSLL/TZA... 30 names) now tier "etf" = scalp_ok with 0.85/0.75 mults (they had NO Finnhub cap → "unknown" → scalp-ineligible, yet they dominate most-actives); (3) NEW GET /activity/today + the Overview gets an "Agent Activity Today" card — live counts (approvals/vetoes/pocket-skips/steps) + last 8 decisions with reasons, straight from the activity log (the Overview was position-derived and agent-blind; `agents: count>0?1:0` was a fake). tsc+eslint clean.
> **OPEN DECISION for Mike:** wheel CSP collateral on a small account — recommend a dedicated cash-secured allowance (collateral is reserved, not spent; e.g. up to 50% equity) instead of the 10% income pocket; needs his sign-off. RESTART required to load.
> **2026-07-02 close-out (Nova) — pockets size from BROKER truth + sim-lab pocket experiments + forex = Layer 6.**
> **Equity source decided:** new `allocation.effective_equity(user_id)` — pockets (gate + /allocations/snapshot) now size from the BROKER's equity when Alpaca is configured (falls back to internal cash+vault). The internal ledger's drift ($2.8k vs broker $4.8k) had been silently shrinking every pocket ~40%.
> **Sim lab:** `agents/scripts/sim_pocket_experiments.py` — reads REAL closed trades, reports per-lane P/L / win% / return-per-$-traded, projects candidate pocket splits (linear, caveated). First run (68 trades since 6/1): stocks +$54.63 on $60k traded (34% win), crypto 1 trade -$112 — history too thin to move pockets; rerun weekly.
> **Forex labeled Layer 6** (the reserved slot) on the pockets page.
> **2026-07-02 late (Nova) — options IV re-score (advisory) + the slippage HALT ships (rules doc §1 complete).**
> **Held-option re-score:** options_scanner now re-measures every open non-expired option HOURLY from live data — current premium via get_option_quote (OCC built from row) vs entry credit (the practical IV read for short premium), moneyness vs strike, DTE. Logs `reeval_option` per contract ("premium 2.3x entry, spot -1.2% vs strike, DTE 4 — RISK: thesis deteriorating" / "healthy"); emits an ADVISORY alert on risk (premium ≥2x entry, or near/in the money with DTE ≤5). No auto-close — the drawback ladder + expiry flow keep control (Mike's options psychology).
> **Slippage halt:** the reconciler's entry-drift check (decision price vs broker avg fill) now MEASURES realized slippage per fill, logs `fill_slippage` (+bps adverse), and feeds killswitch.record_fill_slippage — 3 fills past TREZO_SLIPPAGE_HALT_BPS (75) in one session = session execution-quality halt (same family as the broker-reject halt). The last deferred rule from TREZO_NOVA_BOT_TRADE_RULES.md §1 is now live.
> **2026-07-02 evening (Nova) — FOREX ENGINE LIVE (modeled): the last asset-class gap closed.**
> forex_scanner rewritten from data-less scaffold to live scanner: 5 majors (EURUSD/GBPUSD/USDJPY/AUDUSD/USDCAD) on Kraken 4h candles (key-less, all 5 VERIFIED serving ~720 bars), scored by the shared TCS machinery (strategy=forex_swing), LONG and SHORT, ATR-realistic geometry (stop 1.0x / target 1.2x 4h-ATR, floors 0.2/0.3%), max 2 fires/tick, hourly `forex_scan` heartbeat. Wiring: signals declare asset_type=forex → risk_manager skips US-session/stock-liquidity gates (kill-switches + TCS still apply, `_is_forex`) and passes asset_type through the approve payload → trade_execution honors declared asset_type → falls to the INTERNAL MODELED engine (no broker) → position_monitor prices rows via fetch_candles_for's new forex dispatch (exits + trails + profit-step ladder all work). NEW 'forex' allocation pocket (growth 6%, balanced/income 5%, carved from stocks+crypto; sums still 1.0) + market_type_for maps it + Allocation Pockets page shows the 5th card (Globe icon; tsc+eslint 0 errors). Toggle: bot_settings.forex_enabled if present else TREZO_FOREX_ENABLED=1 default ON.
> **2026-07-02 afternoon (Nova) — Alpaca partial-sell profit stepping (the careful one).**
> **LADDER UPGRADE (same day, per Mike: "it should be able to do it multiple times, stepping out over time"):** the once-per-position guard became a STEP LADDER — each step banks TREZO_PROFIT_STEP_FRACTION (50%) of the REMAINING shares as the run advances another TREZO_PROFIT_STEP_GAP (20%): fires at 60%, 80%, 100% of the way to target, max TREZO_PROFIT_STEP_MAX (3) steps, TREZO_PROFIT_STEP_COOLDOWN_S (900s) between steps. Restart-proof: first sight of a position asks `engine.count_profit_steps` (trade_outcomes, exit_reason='profit_step') how many steps already banked. Both modeled + Alpaca paths use the same `_step_check`/`_step_mark`; every step logs "step N: banked …".
> Broker-held stock LONGS now profit-step like modeled rows: at 60% of the run to target, `_alpaca_profit_step` runs the verified sequence — (1) cancel bracket legs via new `cancel_open_orders_for` and POLL until the open-order list is actually empty (cancel-legs-first, 6/12 GM lesson), (2) `submit_market_sell` the slice; if REJECTED, immediately restore full protection and abort, (3) re-protect the remainder with new `submit_oco_sell` (target limit + stop, one-cancels-other; retries once; if still failing the naked-guard enforcement takes over and the log says so LOUDLY), (4) book via new `engine.record_external_partial_close` — writes a `closed_partial` row (feeds the row-truth kill-switch + learning loop via record_paper_close) and shrinks the open row. Guards: stocks only, longs only, ≥2 shares, usable stop/target, once per position, both env flags (TREZO_PROFIT_STEP_ALPACA + _ENABLED). Every attempt logs `profit_step` / `profit_step_abort` with the full story. Mike's rationale: partial selling controls drawdown and loss.
> **2026-07-02 continuation (Nova) — TCS re-score on held trades + scalp selectable + kill-switch row-truth + formula-layer hole closed.**
> **TCS re-score (Mike's original experiment, now real):** reevaluator's hourly per-position check now refetches candles and re-scores the held strategy's TCS; logs `reeval_check` with "fresh TCS X vs bar Y"; if the fresh score falls below TREZO_REEVAL_TCS_COLLAPSE_FRAC (0.5) of the entry threshold and the position is ≥1d old, it rotates out (`rotate_tcs_collapse`, respects the rotate flag). IV re-score for options = still open (options_scanner owns those).
> **Scalp is now a first-class strategy:** in selector STOCK_STRATEGIES + scoring momentum family; risk_manager gates it to scalp_ok tiers (mega/large only, veto otherwise) and shapes its geometry from the tape: stop 0.8x ATR%, target 1.0x ATR% (then tier + realism layers). Intraday exits (90-min/3:45/stagnation) already cover it.
> **Formula-layer hole closed:** pattern/default signals carried NO stop/target and picked up raw bot defaults at execution, silently skipping the tier+ATR layer — risk_manager now fills defaults from bot settings BEFORE scaling, so EVERY stock trade passes through the formulas.
> **Kill-switch row-truth:** check_all now SUMS this week's closed paper_positions rows per user (week + today + loss streak computed from rows, newest-first) instead of trusting the drift-prone account counters — WMT's unrolled -$61 can never blind it again.
> **2026-07-02 mid-morning build (Nova, Mike waived market-hours rule) — realistic targets + crypto revival + profit stepping + playbook codified.**
> **Realistic-move targets:** risk_manager now caps every stock target at 1.5x the name's 14-day ATR% (floored at 0.6%) AFTER tier scaling — Mike's "barcode days" insight: a big defined target on an idle tape is waiting money. Logged as `realistic_target`; knobs TREZO_TARGET_ATR_MULT / TREZO_TARGET_MIN_PCT. (Also fixed: risk_manager lacked `import os` — the block would have silently no-op'd.)
> **CRYPTO ROOT CAUSES FOUND + FIXED:** scanner ran every 3 min all along but could never fire: (1) SCALP_BB_MAX=2.2 vs real daily bb_width readings 17-36% — SCALP was mathematically DEAD (units bug); (2) SWING demanded 1.1x volume expansion on a quiet tape (SOL missed on vol alone at 0.58x); (3) CoinGecko /ohlc days=90 returns 4-DAY candles = 23 bars < the 25-bar minimum — HBAR/QNT/XDC/IOTA/XYO permanently frozen. Fixes: recalibrated env-tunable thresholds (SCALP_BB_MAX 25.0, SCALP_VOL_MIN 0.4, SWING_VOL_MIN 0.8) in strategies/crypto.py; CoinGecko auto-refetch days=180 when <25 bars in data/candles.py; hourly `crypto_scan` heartbeat in the activity log. Entries stay gated by TCS + net-edge + per-coin cap + pocket. With these, last night's ETH/SOL reads would have fired SCALP.
> **Profit stepping v1 (modeled rows):** position_monitor banks TREZO_PROFIT_STEP_FRACTION (50%) via close_partial_position once a long covers TREZO_PROFIT_STEP_AT (60%) of its run to target; rest rides the trail; logs `profit_step`. Alpaca partials deliberately deferred (bracket-leg renegotiation, 6/12 cancel-legs lesson). In-process once-per-position guard; restart edge case documented in code.
> **Playbook codified:** TREZO_TRADING_PHILOSOPHY.md (account-size playbook, realistic-vs-defined wins, price-agnostic setups) + 7 Mem0 seeds (agent=mike_playbook) + rerunnable evidence script agents/scripts/sim_realistic_targets.py. Sim verdict (7.5mo, $10k/trade, 5bps slip): quick-realistic LOSES on calm megas (stop wick-outs; AAPL -$462) but WINS on high-ATR movers (SNDK +$11,657 at 55% win) — so: signal-gated entries, hunt the moving liquid end, ATR-fit targets, roomier stops, step profits.
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

**Last updated:** 2026-07-13 ~6 PM ET (auto-snapshot) — .gitignore repaired: a literal-\n write bug had left the `agents/knowledge/library/` ignore rule inert (31MB of books/PDFs were about to be committable); rule rewritten as real lines and `logs/` added. Knowledge-library code itself (app/knowledge/library.py + scripts/build_library.py) was committed in today's earlier session — see the 2026-07-13 #3 note at top. Previous update (2026-06-16): large bug-fix + self-healing + learning-loop arc shipped & committed (HEAD `0eb7576` + the commit accompanying this update). Shipped this arc: self-healing integrity sweep (cash<-broker + stock + orphan-option reconcile; runs at startup, ~hourly, and GET /integrity-check); wheel auto-fire cooldown + $0-buying-power quiet-skip; liquidity floor 1M->250k tunable (TREZO_MIN_AVG_VOLUME); account-identity guard + GET /account-check; outcome-weighted strategy selection + per-asset-type learning buckets + suggest_tuning fix; macro fall-through + honest diagnostic (still needs a real VIX/treasury source -- Alpaca-ETF proxy recommended); REAL structure-based risk/reward replacing the old rr=120 placeholder; opt-in experience-driven risk gate (default OFF via TREZO_OUTCOME_GATE_TUNING_ENABLED). Verified live: 0 errors across 23 agents. WARNING: Alpaca account PA3PR4F6ZFWZ buying_power = $0 -> the real gate on NEW trades; reset/grow the paper account to see the fixes produce more activity. Git lock-fault still active (HEAD.lock + index.lock stuck, unlink-EPERM) -> commit via commit-tree + direct ref write. NOTE: clear stale git locks before next git use -- see section 6.A1.
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
