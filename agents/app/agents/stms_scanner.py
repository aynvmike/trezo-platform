"""STMS Scanner Agent.

Ticks every 90 seconds during the 7-11 AM ET window. For each ticker in
the STMS watchlist: evaluates STMS entry filters (price, daily move,
relative volume), computes a Trade Confidence Score, and emits a `signal`
tagged strategy='stms' when all filters pass and TCS >= 750.
"""

from __future__ import annotations

from datetime import date

from app.data.candles import fetch_candles_for
from app.patterns.scoring import calculate_score, MarketContext
from app.strategies.stms import (
    SEED_WATCHLIST,
    TCS_THRESHOLD,
    FLOAT_MAX_MILLIONS,
    evaluate_candidate,
    all_filters_pass,
    stms_chart_setup,
    is_trading_window,
    dynamic_watchlist,
)
from app.data.fundamentals import shares_outstanding_millions
from app.data.news import fetch_company_news

from .base import Agent, AgentMessage


class STMSScannerAgent(Agent):
    name = "stms_scanner"
    tick_interval_seconds = 180  # Throttled 2026-06-05 (was 90) to cut API load

    def __init__(self) -> None:
        self._universe: list[str] = []   # today's dynamic hunting ground
        self._day: str = ""

    async def tick(self) -> list[AgentMessage]:
        from app.runtime.settings import get_bot_settings
        # Honor the user's Bot Tuning TCS slider — lowering it to 500
        # should make STMS fire at 500, not stay stuck on the hardcoded
        # 750 default. The seed value is the fallback if no slider set.
        _cfg = get_bot_settings()
        tcs_floor = int(_cfg.tcs_threshold or TCS_THRESHOLD)
        if not _cfg.stms_enabled:
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"note": "STMS strategy disabled in Bot Tuning settings."},
            )]
        if not is_trading_window():  # 2026-07-13 Mike: STMS runs the FULL session (7 AM-4 PM ET); only ORB keeps a short window
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"note": "Outside STMS trading window (7-11 AM ET). Scanner idle."},
            )]

        # Phase 12 follow-up — refresh the hunting ground once a day
        # from the session's top movers, not a fixed list.
        today = date.today().isoformat()
        if today != self._day:
            self._universe = await dynamic_watchlist()
            self._day = today
        universe = self._universe or list(SEED_WATCHLIST)

        out: list[AgentMessage] = []
        scanned = 0
        candidates = 0

        for ticker in universe:
            try:
                candles = await fetch_candles_for(ticker, "stock")
                if not candles:
                    continue
                scanned += 1
                cand = evaluate_candidate(ticker, candles)
                if not cand:
                    continue
                if not all_filters_pass(cand):
                    continue

                # Phase 13b — cycle awareness. STMS plays small-cap
                # momentum continuations; an earnings-day candidate is a
                # binary event, not a continuation. We skip the trade
                # but EMIT an info event so the future outcome-learning
                # loop still has a record that the bot saw the setup,
                # judged it cycle-unsuitable, and walked away. "Walking
                # away" without leaving a footprint would be amnesia.
                try:
                    from app.data.cycles import get_cycle_position
                    cyc = await get_cycle_position(ticker)
                    if cyc.iv_environment == "earnings_day":
                        out.append(AgentMessage(
                            agent=self.name, kind="info",
                            payload={
                                "event": "stms_cycle_skip",
                                "ticker": ticker,
                                "reason": "earnings_day",
                                "next_earnings_days": cyc.next_earnings_days,
                                "earnings_time": cyc.earnings_time,
                                "filter": {
                                    "price": cand.price,
                                    "daily_move_pct": cand.daily_move_pct,
                                    "relative_volume": cand.relative_volume,
                                },
                                "note": (
                                    f"{ticker} passed STMS filters but it's "
                                    "earnings day — binary event, wrong "
                                    "setup. Logged for the learning loop."
                                ),
                            },
                        ))
                        continue
                except Exception:  # noqa: BLE001
                    pass

                # Small-float filter (Data feed Part 3). A known large
                # share count skips the name; unknown float (free tier
                # gap or API miss) does not block the other filters.
                float_m = await shares_outstanding_millions(ticker)
                if float_m is not None and float_m > FLOAT_MAX_MILLIONS:
                    continue

                # Continuation-setup gate (#130) - the chart-pattern
                # filter: a pole + shallow-pullback structure.
                if not stms_chart_setup(candles):
                    continue

                # Catalyst (#130): recent company news feeds the score.
                news = await fetch_company_news(ticker, days=2)
                has_catalyst = len(news) > 0

                score = calculate_score(
                    candles,
                    MarketContext(catalyst_today=has_catalyst),
                    strategy="stms",
                )
                if score.direction == "bearish":
                    continue
                if score.tcs < tcs_floor:
                    continue

                candidates += 1
                out.append(AgentMessage(
                    agent=self.name,
                    kind="signal",
                    confidence=score.tcs / 100.0,
                    payload={
                        "ticker": ticker,
                        "tcs": score.tcs,
                        "direction": "bullish",
                        "strategy": "stms",
                        "dominant_pattern": score.dominant_pattern,
                        "detected_patterns": score.detected_patterns,
                        "breakdown": score.breakdown,
                        "stms_filters": {
                            "price": cand.price,
                            "daily_move_pct": cand.daily_move_pct,
                            "relative_volume": cand.relative_volume,
                            "float_millions": float_m,
                            "catalyst": has_catalyst,
                        },
                    },
                ))
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(
                    agent=self.name, kind="error",
                    payload={"ticker": ticker, "error": str(e)},
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

        return out + [
            AgentMessage(
                agent=self.name, kind="info",
                payload={
                    "event": "stms_tick",
                    "tickers_scanned": scanned,
                    "candidates_found": candidates,
                },
            )
        ]
