# Trezo Memory Layer

The shared brain across all Trezo agents. Built on [Mem0](https://mem0.ai)
— a semantic memory store that lets agents log decisions + outcomes
and query past situations BEFORE making new decisions.

## Why this exists

Without shared memory every trading day starts from zero. The agents
don't remember which signals worked, which vetoes were wrong, which
regimes mattered. Mem0 closes that loop.

## What's here

- `mem0_client.py` — `TrezoMemory` wrapper with three methods:
  - `log_decision(AgentDecision)` — persist a structured decision
  - `log_outcome(TradeOutcome)` — persist a closed trade with the
    decisions that led to it
  - `recall_similar(query, ...)` — semantic search past memories

- `__init__.py` — exports `get_memory()` (singleton accessor),
  `TrezoMemory`, `AgentDecision`, `TradeOutcome`.

## Setup

```
cd C:\Trezo\trezo-platform\agents
.venv\Scripts\activate
pip install mem0ai
```

`MEM0_API_KEY` must be set in `agents/.env` (already done 2026-06-01).

## Usage from an agent

```python
from app.memory import get_memory, AgentDecision

memory = get_memory()  # singleton, safe to call from anywhere

# Before deciding, check past similar situations
past = memory.recall_similar(
    query=f"{ticker} setup TCS {tcs} {strategy}",
    ticker=ticker,
    limit=5,
)
# past is a list of dicts; each has 'memory', 'metadata', 'score', etc.
# Use past to inform the current decision.

# After deciding, log it
memory_id = memory.log_decision(AgentDecision(
    agent="risk_manager",
    action="veto",
    ticker=ticker,
    reasoning=f"Daily loss limit ${loss_limit} would be breached.",
    metadata={"tcs": tcs, "strategy": strategy, "side": side},
))
# Stash memory_id with the signal so the OutcomeLogger can reference it.
```

## Graceful degradation

The client NEVER raises to the calling agent. If `MEM0_API_KEY` is
missing, or the Mem0 SDK is uninstalled, or the network is down:

- `log_decision()` returns `None`
- `log_outcome()` returns `None`
- `recall_similar()` returns `[]`

Agents must treat memory as a force multiplier, never a hard dep.

## The loop, in one sentence

Risk Manager logs vetoes -> Exit Advisor logs alerts -> Trade
Outcome Logger logs realized P&L referencing those decision IDs ->
next session the agents query memory and avoid repeating bad calls.

## Status (2026-06-01)

- [x] `TrezoMemory` client wrapper shipped (this file)
- [ ] `pip install mem0ai` in agents venv
- [ ] Risk Manager wired (task #14)
- [ ] TradeOutcomeLogger wired (task #15)
- [ ] Seed from accumulated file memory (task #16)
