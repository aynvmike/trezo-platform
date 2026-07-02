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
    tick_interval_seconds = 120  # Throttled 2026-06-05 (was 60) to cut API load

    def __init__(self) -> None:
        self._alerted: set[str] = set()   # symbols alerted today
        self._day: str = ""
        # Patched 2026-06-10 (WMT-stacking class of bug): seed _alerted
        # from today's signal history so restarts don't re-alert.
        self._seeded_alerted: bool = False

    async def _maybe_seed_alerted(self) -> None:
        if self._seeded_alerted:
            return
        self._seeded_alerted = True
        try:
            from app.runtime.restart_state import seed_today_signal_tickers
            self._alerted = await seed_today_signal_tickers("orb_scanner")
        except Exception:
            pass

    async def tick(self) -> list[AgentMessage]:
        await self._maybe_seed_alerted()
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

        # Market-first (2026-07-02): the watchlist leads, the live
        # market fills the rest -- the watchlist is NOT the universe.
        try:
            from app.data.market_universe import expanded_scan_pool
            scan_pool, _pool_info = await expanded_scan_pool(
                list(ORB_WATCHLIST), limit=40)
        except Exception:  # noqa: BLE001
            scan_pool, _pool_info = list(ORB_WATCHLIST), {}
        for symbol in scan_pool:
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
                "pool_size": len(scan_pool),
                "pool_market_wide": int(_pool_info.get("market_wide", 0)),
            },
        ))
        # Task #60 (2026-06-05): scanner_pulse summary emission.
        try:
            _signals = [m for m in out if getattr(m, "kind", None) == "signal"]
            if _signals:
                _tcss = []
                for s in _signals:
                    t = (s.payload or {}).get("tcs")
                    if isinstance(t, (int, float)):
                        _tcss.append(int(t))
                _top_tcs = max(_tcss) if _tcss else 0
                _by_strategy = {}
                for s in _signals:
                    st = (s.payload or {}).get("strategy") or "default"
                    _by_strategy[st] = _by_strategy.get(st, 0) + 1
                _scanned = 0
                try:
                    _scanned = len(symbols)  # type: ignore[name-defined]
                except Exception:
                    _scanned = len(_signals)
                out.append(AgentMessage(
                    agent=self.name,
                    kind="scanner_pulse",
                    confidence=1.0,
                    payload={
                        "scanned": _scanned,
                        "fired": len(_signals),
                        "top_tcs": _top_tcs,
                        "by_strategy": _by_strategy,
                    },
                ))
        except Exception:
            pass

        return out
