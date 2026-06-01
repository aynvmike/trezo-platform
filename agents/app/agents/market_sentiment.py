"""Market Sentiment Agent.

Phase 7.5 — activated (was a Phase 5 stub). Every 5 minutes it pulls
company news for Trezo's active equity watchlist, classifies each
headline (event type + sentiment + severity), and emits:

  - an `event` message for every material event — the Adaptive Scope
    engine consumes these to decide whether to adjust strategy scope;
  - an `info` summary of the scan (net sentiment, headlines seen).

Classification (#120): each headline is read by an LLM (Claude Haiku)
through the input/output guardrails in app/llm/. A per-tick budget caps
the number of LLM calls; beyond it, and whenever the LLM is unavailable
or a guardrail rejects a reply, classification falls back to the fast
deterministic keyword pass in app/data/news.py. Finnhub's /company-news
endpoint is equities-only, so crypto names are not scanned here.
"""

from __future__ import annotations

from app.data.news import fetch_company_news, assess, assess_llm
from app.strategies.wheel import WHEEL_WATCHLIST

from .base import Agent, AgentMessage


# Active equity watchlist for news. Wheel names + the founder equities
# the other scanners watch, de-duplicated, order-preserving.
NEWS_WATCHLIST: list[str] = list(dict.fromkeys(
    WHEEL_WATCHLIST + ["AMD", "CZR", "AMSC"]
))

# How many of the most recent headlines to assess per ticker per tick.
MAX_HEADLINES_PER_TICKER = 8

# Cap on LLM classification calls per tick — bounds cost. Headlines
# beyond the budget use the keyword pass.
LLM_BUDGET_PER_TICK = 30


class MarketSentimentAgent(Agent):
    name = "market_sentiment"
    tick_interval_seconds = 300  # every 5 minutes

    async def tick(self) -> list[AgentMessage]:
        out: list[AgentMessage] = []
        scanned = 0
        headlines = 0
        material = 0
        llm_used = 0
        sentiment_sum = 0.0
        sentiment_n = 0

        for symbol in NEWS_WATCHLIST:
            try:
                items = await fetch_company_news(symbol, days=2)
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(
                    agent=self.name, kind="error",
                    payload={"ticker": symbol, "error": str(e)},
                ))
                continue
            if not items:
                continue
            scanned += 1

            for item in items[:MAX_HEADLINES_PER_TICKER]:
                # LLM classification within budget; keyword pass otherwise
                # or whenever a guardrail rejects the LLM reply.
                a = None
                if llm_used < LLM_BUDGET_PER_TICK:
                    a = await assess_llm(item)
                    if a is not None:
                        llm_used += 1
                if a is None:
                    a = assess(item)

                headlines += 1
                if a.sentiment != "neutral":
                    sentiment_sum += a.sentiment_score
                    sentiment_n += 1
                if a.is_material:
                    material += 1
                    out.append(AgentMessage(
                        agent=self.name,
                        kind="event",
                        confidence=min(abs(a.sentiment_score) + 0.4, 1.0),
                        payload={
                            "ticker": a.symbol,
                            "event_type": a.event_type,
                            "sentiment": a.sentiment,
                            "sentiment_score": a.sentiment_score,
                            "severity": a.severity,
                            "headline": a.headline,
                            "url": a.url,
                            "published": a.published,
                            "detected_by": "market_sentiment",
                        },
                    ))

        net = round(sentiment_sum / sentiment_n, 2) if sentiment_n else 0.0
        mood = ("positive" if net > 0.15
                else "negative" if net < -0.15
                else "neutral")
        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={
                "note": "Sentiment scan complete",
                "tickers_scanned": scanned,
                "headlines_seen": headlines,
                "llm_classified": llm_used,
                "material_events": material,
                "net_sentiment": net,
                "mood": mood,
                "watchlist_size": len(NEWS_WATCHLIST),
            },
        ))
        return out
