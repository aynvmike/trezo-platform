# Phase 10a — Paper/Live Trading-Mode Switch — COMPLETE

Completed 2026-05-22. The groundwork for Phase 10 (live brokerage),
built with no real money involved. Phase 10a installs the master
paper/live switch and the safety design around it; it does NOT enable
live trading.

## What was built

- **`TRADING_MODE` environment variable** — `paper` (default) or `live`.
  Documented in `.env.example`. Missing or unrecognised = `paper`.
- **`agents/app/config.py`** — gains a `trading_mode` setting.
- **`agents/app/runtime/trading_mode.py`** — the single chokepoint:
  - `get_trading_mode()` — the mode, always valid, defaults to paper.
  - `live_requested()` — true if the env asks for live.
  - `live_trading_enabled()` — true ONLY if live is requested AND
    `_LIVE_EXECUTOR_AVAILABLE` is True. That constant is `False` in
    Phase 10a, so this always returns False — setting the env var alone
    changes nothing real. Phase 10b flips it as its final step.
  - `mode_banner()` — a plain-language status line.
- **`trade_execution.py`** — imports the mode module; the vestigial
  `paper_mode` attribute was removed; each `execute` message now stamps
  `trading_mode` so the dashboard can show paper vs live per trade.
- **Bot Tuning page** — a read-only trading-mode banner (green "PAPER"
  / amber "LIVE requested"). The switch is deliberately NOT a one-click
  UI control.
- **`C:\Trezo\GO_LIVE_CHECKLIST.md`** — the full readiness gate that
  must be complete before `TRADING_MODE` is ever set to `live`.

## Security fix bundled in

While editing `.env.example`, a real Anthropic API key was found
committed in that file (in a malformed "Phase-gated" section). It was
removed and the file rewritten to placeholders only. **The exposed key
must be rotated** — see the note to Mike. `.env.example` now passes a
clean secret scan.

## What the user needs to do

1. (Optional) add `TRADING_MODE=paper` to `agents/.env` and
   `web/.env.local`. If absent, paper is the default anyway.
2. Restart the agents and web app to pick up the new module.
3. Rotate the Anthropic API key that was exposed in `.env.example`.

## Design notes

- Two independent conditions gate real money: the env var AND the
  `_LIVE_EXECUTOR_AVAILABLE` constant. One alone does nothing.
- Every future execution path must check `live_trading_enabled()`,
  never the raw mode string.

## Next

- **Phase 10b** — build the live executor (real Alpaca live wiring
  behind `live_trading_enabled()`), only after `GO_LIVE_CHECKLIST.md`
  is satisfied.
