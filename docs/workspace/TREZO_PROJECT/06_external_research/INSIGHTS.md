# External Strategy Insights — Distilled for Trezo

5 strategies analyzed (2026-05-29). Each row below is a discrete
trading idea, the author whose code carries it, the Trezo agent it
maps to, and a concrete code-change proposal. Where an idea is
already partially built, we note what's there and what to harden.

---

## 1. Macro-factor regime allocation (FRED data)
**Source:** Derek Melchin — `derek_melchin_macro_factor_rotation.py`

**Idea:** Use VIX (`VIXCLS`), the 10y-3m Treasury spread (`T10Y3M`),
and the Fed Funds rate (`DFF`) from FRED as features to predict
21-day forward returns across SPY / GLD / BND / BTC, then weight by
predicted return. A DecisionTreeRegressor on 4-year lookback.

**Why it works:** Macro factors compress regime. A flat/inverted
yield curve + rising VIX + tight Fed = stocks should de-risk into
bonds. The tree learns the joint regime instead of single-factor
rules.

**Maps to:** Market Horizon agent (already does cross-asset reads
for stocks/crypto/gold/USD/bonds/income-ETFs every 15 min) +
Adaptive Scope (sets regime posture).

**Trezo enhancement:**
- Add FRED as a data source in `agents/app/data/` — pull VIX,
  T10Y3M, DFF daily, cache 24h.
- Market Horizon emits a `macro_regime` payload field
  (growth/neutral/risk-off) from a simple rule set initially:
  - VIX > 25 AND T10Y3M < 0 → risk-off
  - VIX < 16 AND T10Y3M > 1.0 → growth
  - otherwise → neutral
- Adaptive Scope reads `macro_regime`; in risk-off, raise the TCS
  floor by +50 and pause `crypto_scalp`/`crypto_swing`.
- (Phase 13/14, alongside the outcome learning loop) — train a
  light DecisionTree on (VIX, T10Y3M, DFF, 5d SPY return) →
  next-21d SPY return. Use prediction to bias allocation between
  the Woven Basket layers.

**Priority:** HIGH — costs almost nothing (FRED is free), doesn't
require live brokerage, immediately enriches Adaptive Scope's
decisions.

---

## 2. VIX-regime equity weighting + staged trailing stops
**Source:** Grant Forman — `grant_forman_vix_regime_ml_longshort.py`

**Idea A — VIX regime allocation:**
- High VIX (>80th %ile) + SPY down >3% over 5d → 85-100% equity
  (mean-reversion buy the dip; ML upgrades to 100% if it agrees)
- VIX < 13 + SPY > 50-SMA × 1.05 → 40% equity, 40% gold
  (overheated, defensive)
- 20 < VIX < 20-day SMA → 70-85% equity
- VIX > 20-day SMA × 1.2 → 0% equity, 50% gold (spike, exit)

**Why it works:** VIX is the cleanest single number for fear.
Buying high VIX after a drop is a real edge (mean reversion). Low
VIX with SPY extended is the textbook complacency trap.

**Maps to:** Adaptive Scope (regime) + Risk Manager
(position sizing) + Strategy Engine (posture).

**Trezo enhancement:**
- Extend Adaptive Scope to read VIX (once #1 ships) and emit a
  `vix_state` of {dip-buy, complacent, normal, spike}.
- Strategy Engine reads `vix_state` and adjusts posture:
  - dip-buy → growth posture, +100 TCS bump on bullish signals
  - complacent → income posture, halve risk_per_trade_pct
  - spike → balanced posture, pause STMS + crypto_scalp
- Surface as a chip on the Strategy Windows panel so Mike can see
  why posture changed.

**Idea B — Staged trailing stops:**
- Drawdown 9.5% from new high → trim to 2/3 of original target
- Further drawdown 7% from new high (after stage 1) → trim to 1/3
- Further drawdown 4.85% → full exit

**Why it works:** Lock in profits without abandoning the trend.
The first trim is generous (catches whipsaws), each subsequent
trim is tighter because the trend is breaking.

**Maps to:** Position Monitor.

**Trezo enhancement:**
- Add a `staged_stop_state` JSON field to `paper_positions` rows.
- Position Monitor checks dd-from-peak each tick; on stage
  triggers, calls a new `paper.engine.scale_position(id, new_qty)`
  that closes a partial.
- Make the 9.5%/7%/4.85% thresholds bot_settings dials so Mike
  can dial in his own conviction.

**Idea C — Hurst-like exponent for short selection:**
- Compute the Hurst-like ratio `H = (log(span) - log(ATR)) / log(N)`
  on multiple lookbacks (10/40/60/90/100). Mean above 0.6 = strong
  trend. Then short the names with extended momentum *and* high
  Hurst (mean-reversion candidates after exhaustion).

**Maps to:** Pattern Engine (factor) + new "extended" sub-pattern.

**Trezo enhancement:**
- Add `hurst_like` as a new Pattern Engine factor with 10-pt weight.
- Combine with extension-vs-ATR and momentum-vs-ATR filters in a
  new `EXTENDED_REVERSAL` pattern type.

**Priority:** Idea A = HIGH (regime is foundational). Idea B =
MEDIUM (real edge but needs migration + paper-engine surgery). Idea
C = LOW (specialized, can wait until after #1 ships).

---

## 3. Multifractal / Hurst regime classifier + ML trade filter
**Source:** HennyQuant — `hennyquant_mandelbrot_swing_options.py`

**Idea A — Regime classification via multifractal features:**
Mandelbrot's MF width, tail index, and Hurst at short/med/long scales
classify into 5 regimes (1=quiet → 5=crisis). Each regime has its
own exit rules:
- Regime ≥ 4 (crisis) + days_held ≥ 2 + pnl < 0 → CRISIS_EXIT
- Regime ≥ 4 + days_held ≥ 2 + pnl > 50% → CRISIS_TRAIL (lock it)
- Regime ≥ 3 + pnl < -15% + days_held ≥ 3 → ELEVATED_STOP

**Why it works:** A trade that worked in regime 2 may not survive
regime 4. Tighten the leash automatically when chaos rises.

**Maps to:** Adaptive Scope (regime) + Position Monitor (exit).

**Trezo enhancement:**
- Add a `market_regime` int 1-5 to Adaptive Scope's output (it
  currently emits text like "Broad uptrend" — keep that for the
  banner, add the 1-5 number for code paths).
- Position Monitor reads `market_regime` and applies tighter exit
  rules at ≥3 as above. Same fix shape as Grant's staged stops but
  driven by regime instead of drawdown.

**Idea B — ML trade filter (the outcome learning loop, ready-made):**
After every trade closes, record features + outcome (win/loss). When
≥30 samples accumulated, train a RandomForest. Filter future trades
by predicted win probability ≥ 0.45 threshold. Retrain every 20
new samples.

**Why it works:** This is EXACTLY the [[outcome-aware-learning-loop]]
Mike already queued (Phase 13/14). HennyQuant's `MLTradeFilter` and
`TradeDataCollector` are the implementation blueprint.

**Maps to:** Strategy Discovery (new module: outcome learning).

**Trezo enhancement (Phase 13/14):**
- Migration: `pattern_outcome_stats` table with (pattern, ticker,
  strategy, features_blob, pnl, win_int) per closed trade.
- New `agents/app/learning/outcome_filter.py` with `train()`,
  `predict_win_probability()`, `should_take_trade()`,
  `maybe_retrain()` — direct adaptation of HennyQuant's filter.
- Risk Manager calls `outcome_filter.predict(signal)` BEFORE
  approving; vetos low-win-prob signals after the model has 30+
  samples.
- Surface in UI: "ML BLOCK: ticker X · P(win)=0.34" in the veto
  panel so Mike sees the model in action.

**Priority:** Idea A = MEDIUM. Idea B = HIGH — this is the
flagship "evolving strategy" feature Mike asked for. The
HennyQuant filter is a ready-made template.

---

## 4. Risk-adjusted weighted momentum + vol targeting + switching friction
**Source:** Naitik Gupta — `naitik_gupta_leveraged_etf_rotation.py`

**Idea A — Weighted multi-horizon momentum:**
`momentum = 0.5*ROC(9d) + 0.3*ROC(21d) + 0.2*ROC(63d)` then divide
by 21-day stddev for risk adjustment. Add a 50-SMA trend filter
(0.5x penalty if below) and RSI extremes penalty (0.9x at >85 or
<30).

**Why it works:** Single-horizon momentum gets whipsawed.
Multi-horizon catches both fresh and durable trends; risk adjustment
prevents chasing high-vol garbage.

**Maps to:** Pattern Engine (new scoring factor) + Strategy Engine
(per-stock pick).

**Trezo enhancement:**
- Add `weighted_momentum_score` to the 10-factor Pattern Engine
  scorecard at weight 8 (out of 100 total). Compute as above.
- Strategy Engine uses this score to break ties between strategies
  when their TCS scores are within 50 of each other.

**Idea B — Volatility targeting:**
`weight = target_vol / current_vol` clipped to 1.0. With
`target_vol = 0.80`, a 40% annualized vol stock gets weight 0.80/0.40
= 2.0 → clipped to 1.0. A 20% vol stock gets 0.80/0.20 = 4.0 →
also 1.0. Real effect: low-vol stocks get full size, high-vol
stocks get partial.

**Maps to:** Risk Manager (sizing).

**Trezo enhancement:**
- Trezo currently sizes from `risk_per_trade_pct` × equity ÷
  stop_distance. Vol targeting is a different lens.
- Add an opt-in `risk_mode` setting: "fixed_risk" (today's
  default) vs "vol_target". When vol_target chosen, position size
  becomes `min(equity * target_vol / realized_vol, fixed_risk_size)`.
- Default `target_vol = 0.15` (15% annualized) for paper. Mike can
  dial it on Bot Tuning.

**Idea C — Confidence threshold for switching (anti-whipsaw):**
Only flip from current pick to new candidate if new score
> current * (1 + threshold), e.g. 1.10x. Otherwise hold the
current pick even if marginally beaten.

**Maps to:** Strategy Engine (per-stock pick switching).

**Trezo enhancement:**
- The scanner already records `strategy_changes` events. Add a
  `min_switch_advantage_pct` bot_setting (default 10%).
- Before recording a flip, check: `new.tcs > prev.tcs * (1 + adv)`.
  If not, suppress the change and emit a "held current strategy"
  note instead.
- This directly addresses Mike's concern about TCS-driven
  whipsaws when threshold is lowered.

**Priority:** Idea C = HIGH (cheap, addresses today's whipsaw
problem). Idea A = MEDIUM. Idea B = MEDIUM (real edge but requires
sizing-mode UI).

---

## 5. Alpha-classifier with benchmark fallback
**Source:** Zheng Tian — `zheng_tian_ir_alpha_classifier.py`

**Idea A — Alpha-relative ML labels:**
Train a classifier where the label is "stock beats QQQ over next 5
days" (not "stock has positive return"). Features are the stock's
own return + its 10-day alpha vs benchmark. Forces the model to
learn alpha extraction, not market beta.

**Why it works:** Most "wins" in a bull market are just beta. An
alpha-relative label filters those out — a stock with +3% in a +5%
market is NOT a win.

**Maps to:** Outcome learning loop (same as #3 Idea B), but with
a smarter label.

**Trezo enhancement:**
- When the outcome learning loop ships (Phase 13/14), label
  trades as "win = realized_pnl_pct > SPY_pct over the holding
  period" instead of "win = realized_pnl_pct > 0".
- For options/Wheel trades, use SPY or QQQ as the relevant
  benchmark depending on underlying.

**Idea B — Benchmark fallback when no signal:**
When the model has no high-confidence (>70%) pick, default to
holding QQQ (the benchmark). This makes the "no opinion" state
match the benchmark, so the Information Ratio doesn't decay during
uncertain times.

**Why it works:** Cash is a bet against the benchmark. If you
benchmark against SPY, sitting in cash IS active risk. Holding the
benchmark at zero conviction is the only true neutral state.

**Maps to:** Risk Manager (default state) + KINDRIP (already
holds index funds — same principle).

**Trezo enhancement:**
- This conflicts slightly with Trezo's design: STMS / ORB /
  Extended are intentionally market-timing strategies. Falling
  back to SPY when no signal would make them indistinguishable
  from buy-and-hold.
- Better fit: surface "no high-confidence pick today" as an
  explicit Adaptive Scope state with the suggestion "consider
  manual SPY buy" — but DON'T auto-allocate. Trezo's posture is
  active by design.
- The PRINCIPLE worth taking: when the bot's win rate over 50
  trades drops below the SPY benchmark return over the same
  window, alert Mike. That's a real signal that the strategies
  are not adding alpha and need review.

**Priority:** Idea A = HIGH (free upgrade to the outcome loop's
labels). Idea B = LOW for auto-allocation, MEDIUM as an alert
("strategies underperforming benchmark — review").

---

## Consolidated queue (priority-ordered)

Sorted by (value to Mike) × (ease of implementation):

1. **Switching friction on per-stock strategy picks** (Naitik 4C) —
   trivial Risk Manager / Pattern Detection change. Solves today's
   TCS-lowering whipsaw worry directly. **1-2 hours.**
2. **VIX-regime posture in Adaptive Scope** (Grant 2A) — requires
   FRED data first, then Adaptive Scope reads VIX state. **Half day.**
3. **Macro-factor regime in Market Horizon** (Derek 1) — FRED
   integration, three-rule classifier. **Half day.**
4. **Staged trailing stops in Position Monitor** (Grant 2B) — real
   edge, but needs `staged_stop_state` migration + paper-engine
   `scale_position()`. **1 day.**
5. **Outcome-aware ML trade filter** (HennyQuant 3B + Zheng 5A) —
   the flagship "evolving" feature. Already queued as Phase 13/14.
   **2-3 days when prioritized.**
6. **Volatility targeting as a sizing mode** (Naitik 4B) — adds a
   new risk_mode dial; real edge but more UI than agent work.
   **Half day.**
7. **Multifractal regime exits** (HennyQuant 3A) — combine with #2.
   **Half day after #5.**
8. **Weighted momentum scoring** (Naitik 4A) — Pattern Engine
   factor addition. **2-3 hours.**
9. **Underperformance alert vs SPY** (Zheng 5B) — Strategy
   Discovery surfaces a banner if 50-trade win rate < SPY return.
   **2 hours.**
10. **Hurst-like extended-reversal pattern** (Grant 2C) — niche;
    bolted on after #1-8 land. **1 day.**

---

## What Mike is buying

If we ship #1-3 this week, Trezo gains:
- A regime sense that survives crashes (VIX + macro).
- A scanner that doesn't whipsaw when he lowers the TCS dial.
- Cross-asset reads that match what professional macro funds use.

If we ship #4-5 in Phase 13, Trezo gains:
- Position management that protects gains.
- A bot that genuinely learns from its own outcomes.

Everything else is a follow-on. The full set in priority order is
what an evolving, professional-grade automated wealth platform
looks like — and it's all derived from strategies professionals
actually run.
