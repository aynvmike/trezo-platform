"""ORB Scanner Agent.

Phase 8f. Ticks every 60 seconds during the ORB auto-trade window
(9:35-11:30 AM ET). For each name in the ORB watchlist it pulls today's
1-minute bars, detects a confirmed opening-range breakout, and emits a
`signal` tagged strategy='orb'. One alert per stock per day.

ORB signals flow through the Risk Manager like any other - they pick up
the market filter, overextension, kill-switch and sizing rules - and the
Position Monitor's day-trade management (Phase 8e) closes them out.
"""

from __future__ import annotations

from datetime import date

from app.data.candles import fetch_candles_for, fetch_stock_candles
from app.strategies.market_filter import atr
from app.strategies.orb import ORB_WATCHLIST, orb_window, evaluate_orb

from .base import Agent, AgentMessage


class ORBScannerAgent(Agent):
    name = "orb_scanner"
    tick_interval_seconds = 60

    def __init__(self) -> None:
        self._alerted: set[str] = set()   # symbols alerted today
        self._day: str = ""

    async def tick(self) -> list[AgentMessage]:
        from app.runtime.settings import get_bot_settings
        if not get_bot_settings().stms_enabled:
            # ORB shares the stock day-trade toggle with STMS.
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "Stock strategies disabled in Bot Tuning."})]

        in_window, sub_window = orb_window()
        if not in_window:
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "Outside the ORB window (8:30 AM-12:00 PM ET). Scanner idle."})]

        today = date.today().isoformat()
        if today != self._day:
            self._alerted.clear()
            self._day = today

        out: list[AgentMessage] = []
        scanned = 0
        breakouts = 0

        for symbol in ORB_WATCHLIST:
            if symbol in self._alerted:
                continue
            try:
                candles_1m = await fetch_stock_candles(symbol, period="1d", interval="1m")
                if not candles_1m or len(candles_1m) < 7:
                    continue
                scanned += 1
                daily = await fetch_candles_for(symbol, "stock")
                daily_atr = atr(daily, 14) if daily else 0.0
                sig = evaluate_orb(symbol, candles_1m, daily_atr, sub_window)
                if not sig:
                    continue
                self._alerted.add(symbol)
                breakouts += 1
                out.append(AgentMessage(
                    agent=self.name,
                    kind="signal",
                    confidence=sig.tcs / 1000.0,
                    payload={
                        "ticker": sig.symbol,
                        "tcs": sig.tcs,
                        "direction": sig.direction,
                        "strategy": "orb",
                        "stop_pct": sig.stop_pct,
                        "target_pct": sig.target_pct,
                        "orb": {
                            "range_high": sig.range_high,
                            "range_low": sig.range_low,
                            "breakout_price": sig.breakout_price,
                            "atr_ratio": sig.atr_ratio,
                            "volume_ok": sig.volume_ok,
                            "window": sig.sub_window,
                        },
                    },
                ))
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(agent=self.name, kind="error",
                                        payload={"ticker": symbol, "error": str(e)}))

        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={
                "note": "ORB scan complete",
                "window": sub_window,
                "scanned": scanned,
                "breakouts": breakouts,
                "watchlist_size": len(ORB_WATCHLIST),
            },
        ))
        return out
