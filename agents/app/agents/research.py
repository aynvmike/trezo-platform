"""Research Agent.

Phase 7.5 — activated (was a Phase 5 stub). Every 10 minutes it sweeps
the active watchlist for upcoming corporate events — earnings reports
and ex-dividend dates — and emits advance-warning `event` messages so
the Adaptive Scope engine and the income strategies can prepare.

An imminent earnings report is binary risk: the Adaptive Scope engine
treats a high-severity earnings warning as a reason to tighten or pause
entries on that name until the report is out.
"""

from __future__ import annotations

from app.data.calendar_events import fetch_earnings_calendar, fetch_ex_dividends
from app.strategies.wheel import WHEEL_WATCHLIST

from .base import Agent, AgentMessage


RESEARCH_WATCHLIST: list[str] = list(dict.fromkeys(
    WHEEL_WATCHLIST + ["AMD", "INTC", "CZR", "AMSC"]
))
EARNINGS_HORIZON_DAYS = 10
DIVIDEND_HORIZON_DAYS = 14
EARNINGS_ALERT_WITHIN = 5  # days — closer than this counts as material


class ResearchAgent(Agent):
    name = "research"
    tick_interval_seconds = 600  # every 10 minutes

    async def tick(self) -> list[AgentMessage]:
        out: list[AgentMessage] = []

        try:
            earnings = await fetch_earnings_calendar(
                RESEARCH_WATCHLIST, EARNINGS_HORIZON_DAYS)
        except Exception as e:  # noqa: BLE001
            earnings = []
            out.append(AgentMessage(agent=self.name, kind="error",
                                    payload={"stage": "earnings", "error": str(e)}))
        try:
            ex_divs = await fetch_ex_dividends(
                RESEARCH_WATCHLIST, DIVIDEND_HORIZON_DAYS)
        except Exception as e:  # noqa: BLE001
            ex_divs = []
            out.append(AgentMessage(agent=self.name, kind="error",
                                    payload={"stage": "dividends", "error": str(e)}))

        for ev in earnings:
            if ev.days_until <= 1:
                severity = "high"
            elif ev.days_until <= EARNINGS_ALERT_WITHIN:
                severity = "medium"
            else:
                severity = "low"
            out.append(AgentMessage(
                agent=self.name,
                kind="event",
                confidence=0.8 if severity != "low" else 0.5,
                payload={
                    "ticker": ev.symbol,
                    "event_type": "earnings_upcoming",
                    "event_date": ev.event_date,
                    "days_until": ev.days_until,
                    "severity": severity,
                    "headline": f"{ev.symbol}: {ev.detail}",
                    "detected_by": "research",
                },
            ))

        for ev in ex_divs:
            out.append(AgentMessage(
                agent=self.name,
                kind="event",
                confidence=0.5,
                payload={
                    "ticker": ev.symbol,
                    "event_type": "ex_dividend_upcoming",
                    "event_date": ev.event_date,
                    "days_until": ev.days_until,
                    "severity": "low",
                    "headline": f"{ev.symbol}: {ev.detail}",
                    "detected_by": "research",
                },
            ))

        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={
                "note": "Calendar sweep complete",
                "earnings_upcoming": len(earnings),
                "ex_dividends_upcoming": len(ex_divs),
                "watchlist_size": len(RESEARCH_WATCHLIST),
            },
        ))
        return out
