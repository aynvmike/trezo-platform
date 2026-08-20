# External Strategy Research — Trezo Knowledge Base

Mike collects strategies from researchers/quants whose work has merit.
This folder is the consolidated "what we learned and what to do about
it" view that the Trezo agents (and future Nova sessions) can pull
from.

The originals live under `strategies/` as their authors wrote them.
The distillation lives in `INSIGHTS.md` — one row per idea, mapped
to a Trezo agent and a concrete enhancement proposal.

## When the agents should consult this

- **Adaptive Scope** — when deciding regime and which strategies to
  pause/scale. The VIX-regime and macro-factor work here is directly
  relevant.
- **Risk Manager** — when sizing positions and setting stops. Vol
  targeting and staged trailing stops are queued enhancements.
- **Strategy Engine** — when picking the per-stock best strategy.
  Switching friction (confidence threshold to flip) prevents
  whipsaws.
- **Strategy Discovery** — when training the outcome-aware learning
  loop. The ML-filter pattern here is the implementation blueprint.
- **Market Horizon** — when reading cross-asset relationships. The
  macro factors (VIX, T10Y3M, DFF) add to the existing 6-asset read.

## Workflow for new strategies

1. Drop the original file in `strategies/` named
   `<author>_<short_description>.py` (or `.md`).
2. Add a row to `INSIGHTS.md` per distinct idea, mapped to a Trezo
   agent and an action.
3. Queue the high-value items in the project queue
   (`project_trezo.md` memory entry).
4. The agents themselves don't read this folder at runtime — it's
   a design-time knowledge base. Concrete code changes are what
   carry the ideas into the bot.
