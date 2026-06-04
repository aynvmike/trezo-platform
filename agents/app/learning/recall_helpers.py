"""Mem0 recall helpers - Phase E.

Both Risk Manager and Options Scanner query Mem0 BEFORE making new
decisions and surface a tiny summary of past similar situations
(outcomes won/lost) so the next decision is informed by history.

Design contract:
  * NEVER raises. Memory failures return an empty hint dict.
  * Returns a structured dict the callers can attach to their payload
    so the UI can render "11 similar setups in memory; 7 won, 4 lost".
  * Limits to top-N most-similar memories to keep query cost bounded.

Wired by Nova for Mike on 2026-06-02 (Phase E).
"""

from __future__ import annotations

from typing import Any


def recall_decision_context(*, ticker: str, strategy: str,
                            extra_query: str = "",
                            limit: int = 5) -> dict[str, Any]:
    """Query Mem0 for similar past decisions+outcomes on this ticker /
    strategy. Returns a dict with summary stats the caller can attach
    to their decision payload.

    Empty dict on Mem0 unavailable.
    Shape:
      {
        "available": True,
        "n_decisions": int,
        "n_outcomes": int,
        "wins": int,
        "losses": int,
        "last_pnl_usd": float | None,
        "median_pnl_usd": float | None,
        "summary": "string",   # plain-English hint for UI
      }
    """
    try:
        from app.memory import get_memory
    except Exception:  # noqa: BLE001
        return {"available": False}

    mem = get_memory()
    if not mem.available:
        return {"available": False}

    query = f"{ticker} {strategy} setup"
    if extra_query:
        query = f"{query} {extra_query}"

    try:
        decisions = mem.recall_similar(
            query=query, limit=limit, ticker=ticker, kind="decision",
        )
    except Exception:  # noqa: BLE001
        decisions = []

    try:
        outcomes = mem.recall_similar(
            query=query, limit=limit, ticker=ticker, kind="outcome",
        )
    except Exception:  # noqa: BLE001
        outcomes = []

    pnls: list[float] = []
    wins = losses = 0
    for o in outcomes:
        md = (o or {}).get("metadata") or {}
        pnl = md.get("pnl_usd")
        if isinstance(pnl, (int, float)):
            pnls.append(float(pnl))
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1

    median = None
    if pnls:
        pnls_sorted = sorted(pnls)
        mid = len(pnls_sorted) // 2
        if len(pnls_sorted) % 2:
            median = pnls_sorted[mid]
        else:
            median = (pnls_sorted[mid - 1] + pnls_sorted[mid]) / 2.0

    summary = _build_summary(
        n_decisions=len(decisions), n_outcomes=len(outcomes),
        wins=wins, losses=losses, median=median,
    )

    return {
        "available": True,
        "n_decisions": len(decisions),
        "n_outcomes": len(outcomes),
        "wins": wins,
        "losses": losses,
        "last_pnl_usd": pnls[0] if pnls else None,
        "median_pnl_usd": median,
        "summary": summary,
    }


def _build_summary(*, n_decisions: int, n_outcomes: int,
                   wins: int, losses: int, median: float | None) -> str:
    """Plain-English version the UI can show inline."""
    if n_decisions == 0 and n_outcomes == 0:
        return "No similar past setups in memory yet."
    if n_outcomes == 0:
        return (
            f"Found {n_decisions} similar decision(s) but no closed "
            f"outcomes yet - learning baseline still forming."
        )
    pieces = [f"{n_outcomes} similar closed setup(s)"]
    if wins + losses > 0:
        pieces.append(f"{wins} won / {losses} lost")
    if median is not None:
        pieces.append(f"median P&L ${median:+.0f}")
    return "; ".join(pieces) + "."
