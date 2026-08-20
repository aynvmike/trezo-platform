# Phase 6c — Crypto Bot + Bot Tuning Settings — COMPLETE

> Built by Nova, 2026-05-20.

## What shipped

### Crypto strategy (`agents/app/strategies/crypto.py`)
- Per-coin params: XRP (3% stop / 6% target), ETH (2.5% / 5%), SOL (4% / 8%).
- `detect_mode()` picks one of three adaptive modes per coin:
  - **SWING** — Bollinger width > 2.5% + RSI 50-70 + volume → 5% stop, 12% target
  - **DCA** — RSI < 35 (oversold accumulation) → wider stop, per-coin target
  - **SCALP** — RSI 40-68 + volume ≥ 1.2× → tight 1.5% stop, 3% target
  - Priority SWING > DCA > SCALP. Long-only for Phase 6c.

### Crypto Scanner Agent (`agents/app/agents/crypto_scanner.py`)
- The **11th** agent. Ticks every 60 seconds, 24/7 (crypto never closes).
- Scans XRP/ETH/SOL, runs `detect_mode`, scores TCS. Emits a `signal`
  carrying `mode`, `stop_pct`, `target_pct`, and `strategy="crypto_<mode>"`
  when TCS ≥ 650.

### Strategy-specific risk geometry now flows end-to-end
- Signals carry `stop_pct` / `target_pct`. Risk Manager forwards them on
  `approve`. Trade Execution reads them and passes to `open_position()`.
- So each strategy uses its own geometry: STMS uses 5%/10%, crypto SCALP
  uses 1.5%/3%, crypto SWING uses 5%/12%, etc. — instead of one global default.

### Bot Tuning settings (`db/migrations/0010_bot_settings.sql`)
- New `bot_settings` table: tcs_threshold, max_open_positions,
  risk_per_trade_pct, default_stop_pct, default_target_pct, and per-strategy
  enable toggles (pattern/stms/crypto). Range-checked via CHECK constraints.
- Seeded for existing onboarded users + trigger to seed on future onboarding.

### Bot settings read by the agents (`agents/app/runtime/settings.py`)
- `get_bot_settings()` reads the most-recent `bot_settings` row, cached 30s.
- **Risk Manager** now reads `tcs_threshold` + `max_open_positions` from
  settings instead of hardcoded constants.
- **STMS / Crypto / Pattern Detection scanners** check their enable toggle
  and skip signal emission (still heartbeat) when their strategy is off.
- Single-user assumption for now; per-user settings come with Phase 5b runtime.

### Web UI
- **`/dashboard/settings/bot`** — the Bot Tuning page Mike asked for. Five
  live-readout sliders (TCS threshold 300-1000, max positions 1-20, risk per
  trade 0.5-25%, default stop 1-50%, default target 1-100%) plus three
  strategy toggles. Saves to `bot_settings`; agents pick up changes within 30s.
- **`/dashboard/crypto`** — rebuilt from a static price view into a real bot
  page: live prices, recent crypto signals table (coin, mode badge, RSI, BB
  width, TCS), open crypto positions table, mode legend.
- Sidebar: "Bot Tuning" added to Settings group.

## Decisions made (worth remembering)

1. **Strategy geometry travels on the message.** Rather than the paper engine
   guessing stop/target per strategy, the scanner that knows the strategy
   sets `stop_pct`/`target_pct` on the signal and it rides through to the fill.
2. **Bot settings are global (single-user).** `get_bot_settings()` reads the
   newest row. Correct while Mike is the only user. Per-user enforcement is
   the same Phase 5b deferral as everything else multi-tenant.
3. **30-second settings cache.** Agents don't hit Supabase every tick. A
   slider change is live within 30s — fast enough to feel responsive, slow
   enough to not hammer the DB.
4. **Crypto is long-only in 6c.** Short crypto + the 4-entry DCA laddering
   from the spec are deferred — Phase 6c proves the mode-detection + paper
   loop; laddering is a refinement.
5. **Two layers of on/off for a strategy.** The Agents page toggle stops the
   *scanner* entirely; the Bot Tuning toggle lets the scanner run but emit no
   signals. Documented on the Bot Tuning page so it's not confusing.

## What the user needs to do

1. **Apply migration:** `db/migrations/0010_bot_settings.sql` in Supabase SQL editor.
2. **Restart agents:** `nuke-agent-cache.bat`. Bootstrap line should read **`count=11`** (added `crypto_scanner`).
3. **Restart web:** close Web window, run `start-web.bat`.
4. Hard-refresh. New pages to try:
   - **Settings → Bot Tuning** — drag the sliders, toggle a strategy, save.
   - **Crypto Bot** (Layer 1 in sidebar) — now shows signals + positions, not just prices. Because crypto runs 24/7, you can watch this one work any time of day, unlike STMS.

## Known limitations / open items

- Crypto long-only; no DCA laddering yet.
- Bot settings global, not per-user (Phase 5b).
- No manual position-close button anywhere yet.
- Daily per-coin loss limits from the spec (10% per coin, 10% total halt) not
  yet enforced — only the account-wide daily loss limit is.

## Next phase options

- **Phase 6d: Dividend Wheel** — covered calls + cash-secured puts.
- **Phase 6e: Options strategies** — 3 of 14 to start.
- **Phase 7: Tax Optimizer** — real cost-basis ledger, wash-sale detection,
  quarterly estimates (the Tax Optimizer Agent currently just heartbeats).
- **Phase 5b: per-user agent runtime** — would make bot settings, watchlists,
  and daily limits all properly per-user. Worth doing before real money (Phase 9).
