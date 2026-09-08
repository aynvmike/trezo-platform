"""Mem0 recall helpers - Phase E.

Both Risk Manager and Options Scanner query Mem0 BEFORE making new
decisions and surface a tiny summary of past similar situations
(outcomes won/lost) so the next decision is informed by history.

Design contract:
  * Memory failures return explicit diagnostic states, not evidence of
    a successful search with no matching memories.
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

    ``available`` remains the legacy client-initialized capability flag
    so existing consumers retain failure diagnostics in their payloads.
    It does NOT mean successfully connected: use retrieval_succeeded,
    retrieval_state, and the per-query receipts to assess actual reads.
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
        from app.memory.mem0_client import RecallResult
        mem = get_memory()
    except Exception:  # noqa: BLE001
        return {
            "available": False, "client_available": False,
            "retrieval_succeeded": False,
            "retrieval_state": "client_unavailable",
            "last_success_at": None,
            "recall_receipts": {},
            "n_decisions": 0, "n_outcomes": 0,
            "wins": 0, "losses": 0,
            "last_pnl_usd": None, "median_pnl_usd": None,
            "summary": "Mem0 client unavailable; recall was not attempted.",
        }

    query = f"{ticker} {strategy} setup"
    if extra_query:
        query = f"{query} {extra_query}"

    results = {}
    for kind in ("decision", "outcome"):
        try:
            results[kind] = mem.recall_similar_result(
                query=query, limit=limit, ticker=ticker, kind=kind,
            )
        except Exception:  # noqa: BLE001
            results[kind] = RecallResult(state="request_failed")
    decisions = results["decision"].rows
    outcomes = results["outcome"].rows

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

    succeeded = all(r.succeeded for r in results.values())
    if succeeded:
        state = "ok" if decisions or outcomes else "ok_empty"
    elif any(r.succeeded for r in results.values()):
        state = "partial"
    else:
        states = {r.state for r in results.values()}
        state = next(iter(states)) if len(states) == 1 else "mixed_failure"
    if not succeeded:
        meanings = {
            "ok": "returned matches", "ok_empty": "returned no matches",
            "client_unavailable": "client unavailable",
            "budget_blocked": "blocked by search budget",
            "request_failed": "request failed",
        }
        summary = ("Memory recall incomplete: " if state == "partial"
                   else "Memory recall unavailable: ") + "; ".join(
                       f"{kind}s {meanings.get(r.state, 'unavailable')}"
                       for kind, r in results.items()) + "."
    successes = [r.last_success_at for r in results.values() if r.last_success_at]

    return {
        # Kept for callers that attach learning_context only when available.
        # Successful retrieval is deliberately a separate field.
        "available": bool(mem.available),
        "client_available": bool(mem.available),
        "retrieval_succeeded": succeeded,
        "retrieval_state": state,
        "last_success_at": max(successes) if successes else None,
        "recall_receipts": {
            kind: {"state": r.state, "source": r.source,
                   "last_success_at": r.last_success_at}
            for kind, r in results.items()
        },
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
