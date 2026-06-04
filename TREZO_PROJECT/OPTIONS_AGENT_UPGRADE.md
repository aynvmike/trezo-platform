# Options Agent Upgrade — Spec

**Source:** Mike's brain dump on 2026-06-01 evening (captured verbatim in agent memory at `project_options_trading_rules.md`). This doc is the implementation plan that turns Mike's psychology into bot logic.

**Why now:** Tonight (2026-06-01) we wired Mem0 across Risk Manager + TradeOutcomeLogger and shipped Layer B cycle strategy scoring. The agents now have a learning loop. The next step is teaching the OPTIONS-side agents (Options Scanner, Wheel agent, a new Options Exit Advisor) to trade the way Mike actually trades — not generic optimal math.

---

## The Mike Trading Model (the rules to encode)

### Rule 1 — Contract-count drives the profit target
- **1–10 contracts (low):** target 30–50% gain before trimming.
- **>10 contracts (high):** drop target to ~15% (emotion takes over at scale).

### Rule 2 — Capital recovery first
When low-contract position up 50%+, trim to recover cost basis. "House money" pattern — same primitive as the stock trim dialog shipped tonight.

### Rule 3 — Drawback exit ladder
- Drawback ≥ 39% from peak → **defensive trim** (warn).
- Drawback ≥ 30% with position still in profit → **save profit before negative** (warn).
- Drawback ≥ 25% → **drawdown tolerance ceiling** (urgent).

### Rule 4 — Income-style calls: SELL
When the call has time and the plan is income, sell. Don't hope-hold.

### Rule 5 — Hopeful holds: 3% allocation cap
Non-Wheel hopeful calls bucket — max 3% of options allocation. Pre-planned exit. Drawdown tolerance 20%.

### Rule 6 — Scalp preference
Short-DTE, high-IV, fast-resolution setups. Burst trades, not full holds.

### Rule 7 — Greek-aware filtering
- **Theta**: don't recommend long calls within 7 DTE unless setup explicitly accounts for theta burn.
- **Delta**: surface delta in the signal so user knows if it's premium-play or stock-proxy.

---

## Phased implementation plan

### Phase A — Memory wiring on the options side (1 session)
- Wire `options_scanner.py` (`_run_wheel`, `_options_ideas`) to `get_memory().log_decision()` for every options signal emitted. Match the Risk Manager pattern from tonight.
- Add `risk_manager_memory_id` equivalent for options decisions so outcome closes the loop.

### Phase B — Options-side Exit Advisor (1–2 sessions)
- New agent: `ExitAdvisorOptionsAgent`. Ticks every 5 min over open option positions.
- Encodes Rules 1–3 + 5 as alert rules.
- Writes to a new `exit_advisor_alerts` row with `position_type='option'` (or new table if needed).
- UI: new card on Trading page below stock ExitAdvisorAlerts.

### Phase C — Greek-aware Options Scanner filter (1 session)
- Add Bot Tuning toggles: "min DTE", "max delta for premium plays", "min IV rank for scalp setups".
- Options Scanner reads Greeks from broker chain + filters before emitting.

### Phase D — Hopeful-holds bucket (1 session)
- New `option_position_buckets` table or column distinguishing wheel/income/hopeful.
- Allocation gate in Risk Manager: hopeful bucket capped at 3% of options allocation.

### Phase E — Mem0 outcome learning on options (after Phases A–D run for ~1 week)
- Same pattern as stocks: query `memory.recall_similar()` before each new options decision.
- Surface "in 8 of last 11 times this setup played, I sold too late" type hints.

---

## Public references Mike collected (in `reference_options_resources.md`):
- Scalping math: Kinlay, StockGro, Quantra, Investopedia
- Strategy catalog: tastylive 10 strategies
- Index options: Cboe official guide
- Layout/Greek conventions: Lavender docs (concept-only — no copying, no proprietary text)

---

## Hard constraint
Mike's note on Lavender: use as conceptual reference for clear layout only. Do not copy text, do not import code, do not tie any Trezo feature to a Lavender brand or license.
