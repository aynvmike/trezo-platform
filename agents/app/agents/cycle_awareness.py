"""Cycle Awareness Agent - the bot's calendar reader.

Phase 13a (2026-05-30). Mike's "think like a human" push: the bot
should know that AAPL with earnings in 3 days is a different stock
from AAPL with earnings in 30 days, even when their TCS scores
match. Reads upcoming earnings + ex-dividend dates from Finnhub
once a day and exposes the cycle position per ticker.

Other agents consume this in two ways:
  1. Pattern Detection tags every emitted signal with the symbol's
     cycle position (next_earnings_days, next_exdiv_days, iv_env).
     So every downstream agent sees cycle context for free.
  2. The Strategy Engine selector can use iv_env to bias strategy
     choice (e.g. prefer iv_crush_short when iv_env == "high").

Daily tick cadence: cycles change at most daily, so the agent ticks
every 6 hours. The underlying cache is 24h, so re-ticks are cheap.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from .base import Agent, AgentMessage
from app.config import get_settings
from app.data.cycles import (
    CyclePosition, get_cycle_positions,
)


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def _summary_for(pos: CyclePosition) -> str:
    """One-line plain-English describing where a stock sits in its
    cycle. Used in the activity feed digest."""
    parts = []
    if pos.days_until_earnings is not None:
        if pos.days_until_earnings == 0:
            parts.append(f"{pos.ticker}: earnings TODAY")
        elif pos.days_until_earnings > 0:
            parts.append(
                f"{pos.ticker}: earnings in {pos.days_until_earnings}d"
            )
    if pos.days_until_exdiv is not None and 0 <= pos.days_until_exdiv <= 14:
        amt = (
            f" (${pos.next_dividend_amount:.2f})"
            if pos.next_dividend_amount else ""
        )
        if pos.days_until_exdiv == 0:
            parts.append(f"ex-div TODAY{amt}")
        else:
            parts.append(f"ex-div in {pos.days_until_exdiv}d{amt}")
    return ", ".join(parts)


class CycleAwarenessAgent(Agent):
    """The 18th agent. Pulls earnings + ex-div calendars for every
    user's watchlist on a 6-hour cadence; in-memory cached for
    consumers to read cheaply via `get_cycle_position()`."""

    name = "cycle_awareness"
    tick_interval_seconds = 6 * 60 * 60  # 6 hours

    async def _scan_targets(self) -> list[tuple[Optional[str], list[str]]]:
        """[(user_id, [tickers])] from each user's default watchlist.
        Falls back to the Wheel watchlist when there are no users so
        the agent always has work."""
        client = _supabase()
        if not client:
            # No DB; rely on a static fallback so the digest is non-empty
            from app.agents.options_scanner import WHEEL_WATCHLIST
            return [(None, list(WHEEL_WATCHLIST))]
        try:
            def _accts():
                return client.table("paper_accounts").select("user_id").execute()
            accts = await asyncio.to_thread(_accts)
            users = [a["user_id"] for a in (accts.data or []) if a.get("user_id")]
            if not users:
                from app.agents.options_scanner import WHEEL_WATCHLIST
                return [(None, list(WHEEL_WATCHLIST))]

            out: list[tuple[Optional[str], list[str]]] = []
            for uid in users:
                def _wl(u=uid):
                    return (client.table("watchlists").select("id")
                            .eq("user_id", u).eq("is_default", True)
                            .limit(1).execute())
                wl = await asyncio.to_thread(_wl)
                wl_rows = wl.data or []
                if not wl_rows:
                    continue

                def _items(w=wl_rows[0]["id"]):
                    return (client.table("watchlist_items").select("ticker")
                            .eq("watchlist_id", w).execute())
                items = await asyncio.to_thread(_items)
                tickers = [
                    it["ticker"] for it in (items.data or [])
                    if it.get("ticker")
                ]
                if tickers:
                    out.append((uid, tickers))
            if not out:
                from app.agents.options_scanner import WHEEL_WATCHLIST
                return [(None, list(WHEEL_WATCHLIST))]
            return out
        except Exception:  # noqa: BLE001
            from app.agents.options_scanner import WHEEL_WATCHLIST
            return [(None, list(WHEEL_WATCHLIST))]

    async def tick(self) -> list[AgentMessage]:
        out: list[AgentMessage] = []
        targets = await self._scan_targets()

        for user_id, tickers in targets:
            try:
                positions = await get_cycle_positions(tickers)
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(
                    agent=self.name, kind="error",
                    payload={
                        "user_id": user_id,
                        "error": f"Cycle fetch failed: {e}",
                    },
                ))
                continue

            # Surface tickers with NOTABLE cycle context only - earnings
            # within 7 days OR ex-div within 5 days. The full payload
            # still carries every ticker's position so downstream agents
            # can read it; the human-facing note only lists the urgent.
            notable_lines: list[str] = []
            iv_high: list[str] = []
            iv_postearn: list[str] = []
            div_window: list[str] = []
            earnings_today: list[str] = []

            for sym, pos in positions.items():
                line = _summary_for(pos)
                if line:
                    notable_lines.append(line)
                if pos.iv_environment == "high":
                    iv_high.append(sym)
                elif pos.iv_environment == "earnings_day":
                    earnings_today.append(sym)
                elif pos.iv_environment == "post_earnings":
                    iv_postearn.append(sym)
                elif pos.iv_environment == "dividend_window":
                    div_window.append(sym)

            note_bits: list[str] = []
            if earnings_today:
                note_bits.append(f"Earnings TODAY: {', '.join(earnings_today)}.")
            if iv_high:
                note_bits.append(
                    f"Pre-earnings IV ramp: {', '.join(iv_high)} - "
                    f"sellers' window."
                )
            if iv_postearn:
                note_bits.append(
                    f"Post-earnings IV crushed: {', '.join(iv_postearn)} - "
                    f"long premium less expensive."
                )
            if div_window:
                note_bits.append(
                    f"Dividend window: {', '.join(div_window)}."
                )
            if not note_bits:
                note_bits.append(
                    "No notable cycle events on the watchlist this week."
                )

            payload = {
                "note": " ".join(note_bits),
                "positions": {
                    sym: {
                        "next_earnings_date": p.next_earnings_date,
                        "days_until_earnings": p.days_until_earnings,
                        "earnings_time": p.earnings_time,
                        "next_exdiv_date": p.next_exdiv_date,
                        "days_until_exdiv": p.days_until_exdiv,
                        "next_dividend_amount": p.next_dividend_amount,
                        "iv_environment": p.iv_environment,
                    }
                    for sym, p in positions.items()
                },
                "summary_lines": notable_lines,
            }
            if user_id:
                payload["user_id"] = user_id

            out.append(AgentMessage(
                agent=self.name, kind="info", payload=payload,
            ))

        return out
