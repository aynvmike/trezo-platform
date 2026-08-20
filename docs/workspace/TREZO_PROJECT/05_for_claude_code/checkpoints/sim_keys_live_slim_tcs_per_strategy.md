# Checkpoint — Sim fix · Live slim · TCS per strategy

Date: 2026-05-26

## What changed this turn

### 1. Simulation Lab no longer breaks under compare_all
With "Test every strategy" on, per_symbol can contain multiple rows
per ticker (one per strategy that fired). The web table keyed React
rows by ticker only — duplicate keys → silent rendering issues.
Fix:
- web/src/app/dashboard/simulation/_simulation-lab.tsx — rows now
  keyed by `${symbol}__${strategy}__${idx}`. The "Promote →" logic
  still keys on symbol so all of a ticker's strategy rows collapse
  to "On Core" together once promoted.

### 2. TCS per strategy in the analytics
The by-strategy bucket now carries average TCS at entry, plus the
min/max range — so the "which strategies actually fire on strong
reads vs weak" question is answerable from one column, not by
hunting through the trade timeline.
- agents/app/data/simulation_lab.py — bucket accumulates tcs_sum +
  count + min + max from each trade's entry_tcs, finalises to
  avg_tcs + tcs_min + tcs_max on the wire.
- web/src/app/dashboard/simulation/_simulation-lab.tsx — new
  "Avg TCS (range)" column on the by-strategy table.

### 3. Live Trading page slimmed
The 8-item checklist was overwhelming when the answer is "live is
off, paper-only." Replaced with a clean status card (green PAPER /
red LIVE) plus a collapsed "What it takes to go live" Disclosure
for the long form. OptionsApprovalCard surfaced right under the
status card.

## What is queued from Mike's feedback this round
- Strategy Engine page: needs a purpose explainer + an event when
  the agents propose a strategy change (and why). Needs a dedicated
  pass.
- Dividend Wheel: Wheel page reads modeled / Supabase positions;
  should also pull live options positions from Alpaca so it stays
  in sync with the connected account. Larger build.
- Beginner/Pro tone: Pro mode strips too much guidance on some
  pages while leaving the page incomplete. Needs a content audit —
  separate "educational explanation" (hide in Pro) from "core usage
  hint" (keep in Pro at smaller size).

## Verified
All touched files compile / balance.
