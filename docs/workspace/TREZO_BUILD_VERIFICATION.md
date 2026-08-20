# Trezo — Build Verification

An end-to-end check of everything built since the last verification
(the agent/auth/sitemap pass). Run 2026-05-22.

Scope of this stretch: Phase 9.5b/9.5c (Tax Strategy), the adjustable
losing-streak limit, Phase 10a (paper/live switch), the seven quick
wins, the live market-data feed, the #119-122 backlog (multi-user, LLM
sentiment, backtest, options engine), the small-items sweep, Phase 11
(Budget Mirror — all three parts), and the dividend DRIP.

## Automated checks — all passed

| Check | Result |
|-------|--------|
| Agent code parses (78 Python files) | All clean |
| Agent count — defined vs. registered | 16 = 16, consistent |
| Web source — null bytes | None in any file |
| Web source — brace balance | Every file balanced |
| Database migrations present | 21 (0001-0021) |
| Leaked API keys in the repo | None found |
| New files present (18) and wired in | All present |
| Navigation, bootstrap, imports | All wired correctly |

Nothing in the build is broken or half-applied. Every new module is
referenced by the code that should use it — no orphans.

## What you need to do before testing

1. **Apply the database migrations** from this stretch in Supabase, in
   order, if you have not already: `0018_tax_strategy.sql`,
   `0019_loss_limit_setting.sql`, `0020_quick_wins.sql`,
   `0021_dividend_drip.sql`.
2. **Restart the agents.** The bootstrap line should now read
   **count=16** (the Dividend Manager is the 16th agent).
3. **Restart the web app.**
4. Confirm the Anthropic key is in `agents/.env` — it powers the LLM
   sentiment read. Without it, sentiment falls back to the keyword
   pass; nothing breaks.

## New in the app since you last tested

- Sidebar: **Backtest** and **Budget Mirror** pages.
- Tax page: a Tax Strategy section; closed options now count in the
  estimate.
- Bot Tuning: a Losing-streak limit slider; a Trading-mode banner.
- Paper Trading: a "Close now" button per open position.
- Strategy page: Approve / Dismiss buttons on suggested scope changes.
- KINDRIP page: live ETF values and a "This quarter" panel.
- Dividends page: a per-holding DRIP toggle and distributions total.
- Footer: working Privacy, Terms, and Contact pages.

## Honest limitations (unchanged, by design)

- All trading is still paper/modeled — Phase 10b wires real money,
  gated by `GO_LIVE_CHECKLIST.md`.
- The LLM guardrails are a lightweight, inspectable layer, not the full
  NeMo Guardrails library.
- Budget Mirror's savings routing is a guided hand-off, not silent
  auto-wiring of a recurring contribution.
- Live options pricing and the market-data feed are best-effort — they
  fall back to modeled data when a provider is unreachable.

## Verdict

The build is sound and ready for your end-to-end test run. Work
through `trezo-platform/TEST_CHECKLIST.md` once the migrations are
applied and both services are restarted.
