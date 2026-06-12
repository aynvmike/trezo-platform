"""Forex Scanner Agent (Task #77).

Mike asked for FX coverage. This scanner watches the major pairs
(EUR/USD, USD/JPY, GBP/USD, USD/CHF) via Alpaca FX (when configured)
or Alpha Vantage FX_DAILY as fallback.

For each pair it fetches daily OHLC, runs the same RSI + Bollinger
mode detection as the crypto scanner, and emits a `signal` tagged
strategy="forex".

Active 24x5 (Sun 17:00 ET to Fri 17:00 ET) - FX never sleeps in the
work week. Per-pair stops are tight (0.5% common); the slider gates.
"""

from __future__ import annotations

from typing import Optional

from app.config import get_settings
from .base import Agent, AgentMessage


# Major pairs. Mike can add minors via a future watchlist hook.
FOREX_WATCHLIST = ["EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF", "AUD/USD"]


class ForexScannerAgent(Agent):
    name = "forex_scanner"
    tick_interval_seconds = 600  # 10 min - FX is slower than equities

    MIN_TCS = 600
    DEFAULT_STOP_PCT = 0.005   # 0.5% - FX moves smaller per unit
    DEFAULT_TARGET_PCT = 0.012 # 1.2%

    async def tick(self) -> list[AgentMessage]:
        from app.runtime.settings import get_bot_settings
        cfg = get_bot_settings()
        # Honor user toggle: forex_enabled in bot_settings (default off).
        if not getattr(cfg, "forex_enabled", False):
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={
                    "note": "Forex strategy DISABLED in Bot Tuning. Toggle 'forex_enabled' ON to enable.",
                    "fix": "Bot Tuning -> Strategies -> Forex: ON",
                },
            )]

        out: list[AgentMessage] = []
        # Skeleton: emit scanner_pulse w/ no signals until a data
        # source is wired. Mike picks: Alpaca FX (paid), Alpha Vantage
        # FX_DAILY (free 25/day), or Polygon (Massive). See Task #80.
        out.append(AgentMessage(
            agent=self.name, kind="scanner_pulse", confidence=1.0,
            payload={
                "scanned": len(FOREX_WATCHLIST),
                "fired": 0,
                "top_tcs": 0,
                "by_strategy": {"forex": 0},
                "note": "Forex scanner scaffold active; data source not yet wired - see Task #77",
            },
        ))
        return out
