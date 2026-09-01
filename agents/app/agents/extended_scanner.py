"""Extended Strategy Scanner Agent.

Phase 10c. The 17th agent. Layer 4 of the Woven Basket — the multi-day
swing layer.

Sweeps the Extended watchlist mid-session (roughly 10 AM-3:30 PM ET).
For each name it pulls daily candles, runs the four swing-setup
detectors (EMA50 pullback, breakout hold, gap continuation, stair
stepper), and emits a `signal` tagged strategy='extended' for the best
qualifying setup. One signal per stock per day.

Section 7C event gate: on an FOMC decision day the scanner sits out
until 2 PM ET — no new entries before the rate announcement.

Extended signals flow through the Risk Manager like any other signal.
The Position Monitor holds them for up to ~5 trading days (it does NOT
apply the intraday 3:45 PM force-exit that STMS / ORB positions get).
"""

from __future__ import annotations

from datetime import date

from app.data.candles import fetch_candles_for
from app.data.news import fetch_company_news
from app.strategies.extended import (
    EXTENDED_WATCHLIST,
    evaluate_extended,
    fomc_blackout,
    swing_window,
)

from .base import Agent, AgentMessage


class ExtendedScannerAgent(Agent):
    name = "extended_scanner"
    tick_interval_seconds = 1800  # every 30 min — swing entries are not urgent

    def __init__(self) -> None:
        self._signalled: set[str] = set()   # symbols signalled today
        self._day: str = ""
        # Patched 2026-06-10 (same class of bug as WMT stacking): seed
        # _signalled from today's signal history so restarts don't
        # re-emit signals for tickers already handled today.
        self._seeded_signalled: bool = False

    async def _maybe_seed_signalled(self) -> None:
        if self._seeded_signalled:
            return
        self._seeded_signalled = True
        try:
            from app.runtime.restart_state import seed_today_signal_tickers
            self._signalled = await seed_today_signal_tickers("extended_scanner")
        except Exception:
            pass

    async def tick(self) -> list[AgentMessage]:
        await self._maybe_seed_signalled()
        from app.runtime.settings import lane_enabled_any
        # BI-03: a bare get_bot_settings() is the PRIMARY book's opinion;
        # this scanner feeds every book, and the fan-out prunes per book.
        if not lane_enabled_any("extended_enabled"):
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "Extended Strategy disabled in Bot Tuning (every book)."})]

        if fomc_blackout():
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "FOMC decision day - no new swing entries until 2 PM ET."})]

        if not swing_window():
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "Outside the swing scan window (8:30 AM-6:30 PM ET). Scanner idle."})]

        today = date.today().isoformat()
        if today != self._day:
            self._signalled.clear()
            self._day = today

        out: list[AgentMessage] = []
        scanned = 0
        signals = 0

        # Market-first (2026-07-02): watchlist leads, market fills.
        try:
            from app.data.market_universe import expanded_scan_pool
            scan_pool, _pool_info = await expanded_scan_pool(
                list(EXTENDED_WATCHLIST), limit=60)
        except Exception:  # noqa: BLE001
            scan_pool, _pool_info = list(EXTENDED_WATCHLIST), {}
        for symbol in scan_pool:
            if symbol in self._signalled:
                continue
            try:
                candles = await fetch_candles_for(symbol, "stock")
                if not candles or len(candles) < 60:
                    continue
                scanned += 1

                # Catalyst (Section 7C): recent company news lifts the score.
                news = await fetch_company_news(symbol, days=3)
                has_catalyst = len(news) > 0

                sig = evaluate_extended(symbol, candles, has_catalyst=has_catalyst)
                if not sig:
                    continue
                self._signalled.add(symbol)
                signals += 1
                out.append(AgentMessage(
                    agent=self.name,
                    kind="signal",
                    # EQ-5: sig.tcs is 0-100 (extended.py rescaled), so
                    # this lands in the 0..1 range AgentMessage documents.
                    confidence=sig.tcs / 100.0,
                    payload={
                        "ticker": sig.symbol,
                        "tcs": sig.tcs,
                        "direction": sig.direction,
                        "strategy": "extended",
                        "stop_pct": sig.stop_pct,
                        "target_pct": sig.target_pct,
                        "extended": {
                            "setup": sig.setup,
                            "entry_price": sig.entry_price,
                            "rationale": sig.rationale,
                            "catalyst": has_catalyst,
                        },
                    },
                ))
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(agent=self.name, kind="error",
                                        payload={"ticker": symbol, "error": str(e)}))

        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={
                "note": "Extended scan complete",
                "scanned": scanned,
                "signals": signals,
                "watchlist_size": len(EXTENDED_WATCHLIST),
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
                # EQ-10/NEQ-02: `symbols` was never defined here, so the
                # pulse always reported the signal count as "scanned".
                _scanned = scanned
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
