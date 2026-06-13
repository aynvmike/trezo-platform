"""Kraken Futures strategy scaffold (Futures Phase 1, 2026-06-13).

A HOME for the agents to build futures strategies -- demo/paper first, under a
conservative leverage cap (<= 3x, hard-capped in app.brokers.kraken_futures).
Phase 1 ships the data type + a baseline trend/momentum example + the leverage
clamp. The live futures_scanner + demo order placement + exit management are
Phase 2. Futures can go SHORT (unlike long-only spot); demo only for now.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.patterns import Candle
from app.patterns.indicators import rsi, closes


@dataclass
class FuturesSignal:
    symbol: str
    direction: str        # 'long' | 'short'
    leverage: float       # already clamped to <= 3x
    stop_pct: float
    target_pct: float
    rsi: float
    reason: str


def baseline_signal(symbol: str, candles: list[Candle],
                    max_leverage: float = 2.0) -> Optional[FuturesSignal]:
    """A conservative trend/momentum STARTER for the agents to iterate on:
    long on healthy momentum, short on clear weakness, leverage clamped to the
    hard 3x cap. Returns None when there is no clean setup. This is a starting
    point, not a tuned strategy -- strategy_discovery / research will evolve it
    against demo data."""
    if len(candles) < 30:
        return None
    from app.brokers.kraken_futures import clamp_leverage
    cl = closes(candles)
    r = rsi(cl, 14)[-1]
    lev = clamp_leverage(max_leverage)
    if r >= 55:
        return FuturesSignal(symbol, "long", lev, 0.03, 0.06, r,
                             f"momentum long (RSI {r:.0f}), {lev:g}x demo")
    if r <= 45:
        return FuturesSignal(symbol, "short", lev, 0.03, 0.06, r,
                             f"momentum short (RSI {r:.0f}), {lev:g}x demo")
    return None
