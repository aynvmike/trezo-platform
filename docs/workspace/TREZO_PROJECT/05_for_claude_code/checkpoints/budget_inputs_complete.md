# Budget Mirror — expanded inputs — COMPLETE

Completed 2026-05-22, from testing feedback. Budget Mirror is no longer
CSV-only.

## What was built

- **`_input-panel.tsx`** — one panel, three ways in:
  - CSV upload (read in the browser, as before).
  - **Manual entry** — a date / merchant / amount form; each entry is
    added to the running transaction set.
  - **Receipt & PDF scan** — upload an image or PDF, or take a photo;
    the file goes to `/api/budget/scan`.
  Transactions from all three sources accumulate together, and the
  dashboard, simulator, and planner all recompute from the combined set.
- **`/api/budget/scan`** — an auth-guarded route that sends a receipt
  image or PDF to Claude (vision), which extracts the date, merchant,
  and amount of each line. The file is used for one read and not
  stored. Needs `ANTHROPIC_API_KEY` in `web/.env.local`; without it the
  route returns a clear message and CSV + manual entry still work.
- `_budget-mirror.tsx` reworked to hold the transaction set and derive
  the analysis from it (`analyze(txns)`), so every input method feeds
  the same pipeline.
- The data-export guide moved into a collapsed **Help** disclosure
  instead of a wall of text at the page bottom.

## Privacy

CSV and manual entry stay 100% in the browser. Only the receipt/PDF
scan sends the file out — to the AI, for one read, then discarded. The
UI says so plainly.

## What the user needs to do

For receipt scanning: add `ANTHROPIC_API_KEY` to `web/.env.local`, then
restart the web app. CSV and manual entry need nothing.

## Verification

All Budget Mirror files brace/paren-balanced, no null bytes. CSV
parsing logic unchanged (previously tested).
