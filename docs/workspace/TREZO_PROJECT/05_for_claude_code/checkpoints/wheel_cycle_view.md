# Checkpoint — Dividend Wheel cycle view

Date: 2026-05-26
Goal: show where each wheel name is in its 4-stop cycle, surface the
full income picture (premium + dividend + FPSL), and explain the wheel
in plain words.

## What changed
- web/src/app/dashboard/wheel/page.tsx (rebuilt)
  - New per-underlying CycleCard for each name on the wheel watchlist
    (WMT, KO, JNJ, PG, CSCO, VZ, INTC). Each card shows:
      * 4-stop visual strip — Sell put / Wait / Hold & call / Reset.
      * Active stop highlighted; past stops dimmed.
      * Plain-language state ("Sold a cash-secured put. If it expires
        OTM the credit is kept; if it assigns, you own 100 shares.").
      * Next-action hint.
      * Modeled income: premium per cycle, annualised dividend on 100
        shares (using a typical yield map), FPSL income (0.1%).
  - "Where the income comes from" section: 3 cards — Premium at work,
    Realized P&L, Modeled hold income (dividend + FPSL on shares
    currently held).
  - "How the wheel turns" beginner-only walk-through Disclosure: four
    paragraphs walking through every stop, explicitly explaining
    FPSL (Fully Paid Securities Lending) — a small but real rebate
    your broker pays for letting short-sellers borrow your shares.
  - Existing open / settled tables kept.

## Notes
- Dividend yields are a hardcoded table (WMT 1.2%, KO 3.0%, JNJ 2.9%,
  PG 2.4%, CSCO 2.7%, VZ 6.5%, INTC 1.5%). FPSL modeled at 0.1%.
  Real dividend tracking from a live feed is a later phase — flagged
  in the modeled-pricing Disclosure.
- File verified balanced (brace=0/paren=0/bracket=0, no stray strings).

## Still queued
- Future projections for every account, factoring taxes — own section.
- Brokerage connect (Webull / IBKR / Alpaca Live) — planning needed.
- Multi-account-size simulation ($1k / $5k / $10k / $100k).
- Beta-tester onboarding (Mike has 3 users ready).
