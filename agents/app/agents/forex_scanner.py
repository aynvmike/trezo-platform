"""Forex Scanner Agent -- LIVE (2026-07-02; was a data-less scaffold, Task #77).

Watches the major fiat pairs via Kraken public OHLC (data/forex.py --
key-less, the same venue the crypto side trusts), scores each on 4-hour
candles with the shared pattern/TCS machinery, and emits LONG or SHORT
signals (fiat pairs are symmetric -- every position is long one currency,
short the other).

Stops/targets are ATR-realistic per Mike's playbook: fit the trade to what
the pair ACTUALLY moves (majors drift ~0.3-0.8% per session; a fat equity-
style target would be waiting money).

Execution is MODELED (internal paper engine; no forex broker wired). The
Risk Manager skips the US-equity session/liquidity gates for these but
keeps TCS + kill-switches; capital comes from the dedicated 'forex'
allocation pocket. Toggle: bot_settings.forex_enabled when present, else
TREZO_FOREX_ENABLED (default ON).
"""

from __future__ import annotations

import os
import time as _time

from .base import Agent, AgentMessage

# Query names data/forex.py accepts (Kraken pair codes).
FOREX_WATCHLIST = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]

_ATR_STOP_MULT = 1.0    # stop  = 1.0x 4h-ATR%
_ATR_TARGET_MULT = 1.2  # target= 1.2x 4h-ATR%
_MIN_STOP = 0.002       # never tighter than 0.2%
_MIN_TARGET = 0.003     # always clears round-trip slippage (0.1%) + cushion
_MAX_FIRES_PER_TICK = 2


class ForexScannerAgent(Agent):
    name = "forex_scanner"
    tick_interval_seconds = 180  # crypto cadence (Mike 2026-07-02): market data matters in FX too
    _last_hb: float = 0.0

    async def tick(self) -> list[AgentMessage]:
        from app.runtime.settings import get_bot_settings
        cfg = get_bot_settings()
        _setting = getattr(cfg, "forex_enabled", None)
        enabled = (bool(_setting) if _setting is not None
                   else os.getenv("TREZO_FOREX_ENABLED", "1") != "0")
        if not enabled:
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={
                    "note": ("Forex DISABLED (bot_settings.forex_enabled / "
                             "TREZO_FOREX_ENABLED)."),
                },
            )]

        from app.data.forex import FOREX_MAJORS, fetch_forex_candles
        from app.patterns.scoring import calculate_score, MarketContext
        from app.strategies.market_filter import atr as _atr

        out: list[AgentMessage] = []
        scanned = 0
        fired = 0
        top_tcs = 0
        detail: list[dict] = []
        tcs_floor = int(getattr(cfg, "tcs_threshold", 70) or 70)

        for pair in FOREX_WATCHLIST:
            if pair not in FOREX_MAJORS:
                continue
            try:
                candles = await fetch_forex_candles(pair, interval_min=240)
                if not candles or len(candles) < 30:
                    detail.append({"ticker": pair, "result": "no_data"})
                    continue
                scanned += 1
                score = calculate_score(candles, MarketContext(),
                                        strategy="forex_swing")
                tcs = int(score.tcs)
                top_tcs = max(top_tcs, tcs)
                direction = score.direction
                if direction not in ("bullish", "bearish"):
                    detail.append({"ticker": pair, "result": "neutral",
                                   "tcs": tcs})
                    continue
                if tcs < tcs_floor:
                    detail.append({"ticker": pair, "result": "low_tcs",
                                   "tcs": tcs, "tcs_floor": tcs_floor})
                    continue
                last = float(candles[-1].close)
                atr_abs = float(_atr(candles) or 0.0)
                atr_pct = (atr_abs / last) if last > 0 else 0.0
                if atr_pct <= 0:
                    detail.append({"ticker": pair, "result": "no_atr"})
                    continue
                stop_pct = round(max(_MIN_STOP, _ATR_STOP_MULT * atr_pct), 5)
                target_pct = round(max(_MIN_TARGET,
                                       _ATR_TARGET_MULT * atr_pct), 5)
                fired += 1
                detail.append({"ticker": pair, "result": "FIRED", "tcs": tcs,
                               "direction": direction,
                               "atr_pct": round(atr_pct * 100, 3)})
                out.append(AgentMessage(
                    agent=self.name, kind="signal",
                    confidence=tcs / 100.0,
                    payload={
                        "ticker": pair,
                        "asset_type": "forex",
                        "tcs": tcs,
                        "direction": direction,
                        "strategy": "forex_swing",
                        "stop_pct": stop_pct,
                        "target_pct": target_pct,
                        "forex_signal": {
                            "atr_pct": round(atr_pct * 100, 3),
                            "bars": len(candles),
                            "interval_min": 240,
                        },
                    },
                ))
                if fired >= _MAX_FIRES_PER_TICK:
                    break
            except Exception as e:  # noqa: BLE001
                detail.append({"ticker": pair, "result": "error",
                               "error": str(e)[:100]})

        # Hourly visibility heartbeat (same pattern as the crypto scanner).
        try:
            if (_time.time() - ForexScannerAgent._last_hb) >= 3600.0:
                ForexScannerAgent._last_hb = _time.time()
                from app.agents.activity_log import record as _arec
                _summary = ", ".join(
                    f"{d.get('ticker')}:{d.get('result')}" for d in detail[:5])
                _arec("forex_scan", "FOREX",
                      reason=f"{scanned} scanned, {fired} fired -- {_summary}",
                      extra={"fired": fired})
        except Exception:  # noqa: BLE001
            pass

        out.append(AgentMessage(
            agent=self.name, kind="scanner_pulse", confidence=1.0,
            payload={
                "scanned": scanned,
                "fired": fired,
                "top_tcs": top_tcs,
                "by_strategy": {"forex_swing": fired},
                "detail": detail,
            },
        ))
        return out
