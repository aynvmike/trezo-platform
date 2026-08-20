# Checkpoint — CapitalAllocator + Strategy Engine purpose

Date: 2026-05-26

## A. Profile · Capital section is now broker-aware
- web/src/components/dashboard/capital-allocator.tsx (new)
  - Two modes: "Total + split" (default when capital already exists)
    and "Manual dollars" (the original behaviour).
  - Live banner at the top: when an Alpaca account is connected, it
    shows the equity and a one-tap "Sync the Total to this" link so
    the user lines capital to the broker's reality with one click.
  - Three AI presets — aggressive (50/30/20), balanced (70/15/15),
    conservative (85/10/5) — pick a stock / crypto / options split
    based on posture. The user can then tweak the percentages.
  - The form still submits stock_capital_usd / crypto_capital_usd /
    options_capital_usd via hidden inputs — existing save action
    untouched.
- web/src/app/dashboard/settings/profile/_profile-form.tsx
  - The 3-input Capital section was replaced by <CapitalAllocator />.
  - ProfileForm signature now accepts liveEquity + liveLabel props.
- web/src/app/dashboard/settings/profile/page.tsx
  - Fetches the Alpaca snapshot once and threads liveEquity through.

## B. Strategy Engine — purpose + proposals feed
- web/src/app/dashboard/strategy/page.tsx
  - Always-visible 1-line purpose under the title (was beginner-only,
    so Pro mode gutted it). Now:
    "The page where the bot tells you which strategies it wants to
    favour, trim, or pause — and when it wants to change its mind."
  - Beginner-only longer explainer kept.
  - Inserts the new proposals feed right after Current posture.
- web/src/components/dashboard/strategy-proposals.tsx (new)
  - Reads agent_messages from strategy_discovery + adaptive_scope
    (alerts / metrics / info). Per-row plain-language description:
    "25-trade performance review due — N trades logged",
    "Performance report — win rate X%, profit factor Y",
    "Weakest strategy this window: Z."
  - Empty state explains the cadence (discovery hourly, scope every
    10 min) so the user knows when more rows will appear.

## What got addressed
- "Capital should follow the live or paper account" → CapitalAllocator
  reads the connected Alpaca equity and lets the user sync it as the
  total in one tap.
- "Add total amount + percentage allocation" → mode = Total + split,
  three percent inputs with live USD preview, sum-to-100 indicator.
- "Or AI helps with the focus" → three AI preset buttons that pre-fill
  the split based on user posture.
- "Strategy Engine purpose + proposals" → always-visible purpose
  line; proposals feed surfacing every agent change request with
  reason + timestamp.

## Verified
All 5 touched / new files compile / balance.

## Still queued
- Beginner / Pro tone audit (Pro shouldn't gut operational hints).
