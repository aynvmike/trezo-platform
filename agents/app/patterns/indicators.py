"""Technical indicators used by the 10-factor scoring engine.

Pure-Python implementations (no numpy dependency required) for portability.
Each function takes a list of Candle objects with the most-recent candle last.
"""

from __future__ import annotations

from .candle import Candle


# ---- helpers ---------------------------------------------------------------


def closes(candles: list[Candle]) -> list[float]:
    return [c.close for c in candles]


def highs(candles: list[Candle]) -> list[float]:
    return [c.high for c in candles]


def lows(candles: list[Candle]) -> list[float]:
    return [c.low for c in candles]


def volumes(candles: list[Candle]) -> list[float]:
    return [c.volume for c in candles]


# ---- EMA -------------------------------------------------------------------


def ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average. Returns a list the same length as input."""
    if not values:
        return []
    if period <= 1:
        return values[:]
    k = 2.0 / (period + 1)
    out: list[float] = []
    prev = values[0]
    out.append(prev)
    for v in values[1:]:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


# ---- SMA -------------------------------------------------------------------


def sma(values: list[float], period: int) -> list[float]:
    """Simple moving average. Pads with first available average at front."""
    if not values:
        return []
    out: list[float] = []
    window: list[float] = []
    for v in values:
        window.append(v)
        if len(window) > period:
            window.pop(0)
        out.append(sum(window) / len(window))
    return out


# ---- RSI -------------------------------------------------------------------


def rsi(values: list[float], period: int = 14) -> list[float]:
    """Wilder's RSI."""
    n = len(values)
    if n < 2:
        return [50.0] * n
    gains = [0.0]
    losses = [0.0]
    for i in range(1, n):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    out: list[float] = [50.0]
    if n < period + 1:
        return [50.0] * n

    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    for _ in range(1, period):
        out.append(50.0)
    rs = (avg_gain / avg_loss) if avg_loss > 0 else float("inf")
    out.append(100.0 - (100.0 / (1.0 + rs)) if avg_loss > 0 else 100.0)

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out.append(100.0)
        else:
            rs = avg_gain / avg_loss
            out.append(100.0 - (100.0 / (1.0 + rs)))
    return out


# ---- MACD ------------------------------------------------------------------


def macd(
    values: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> dict[str, list[float]]:
    """MACD line, signal line, histogram."""
    if not values:
        return {"macd": [], "signal": [], "hist": []}
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return {"macd": macd_line, "signal": signal_line, "hist": hist}


# ---- Bollinger Bands -------------------------------------------------------


def bollinger(
    values: list[float], period: int = 20, std: float = 2.0
) -> dict[str, list[float]]:
    """Bollinger bands (upper, mid, lower) using SMA + population stddev."""
    if not values:
        return {"upper": [], "mid": [], "lower": []}
    upper: list[float] = []
    mid: list[float] = []
    lower: list[float] = []
    window: list[float] = []
    for v in values:
        window.append(v)
        if len(window) > period:
            window.pop(0)
        avg = sum(window) / len(window)
        var = sum((x - avg) ** 2 for x in window) / len(window)
        sd = var ** 0.5
        mid.append(avg)
        upper.append(avg + std * sd)
        lower.append(avg - std * sd)
    return {"upper": upper, "mid": mid, "lower": lower}


# ---- VWAP ------------------------------------------------------------------


def vwap(candles: list[Candle]) -> list[float]:
    """Volume-weighted average price (running, intraday or full-window)."""
    out: list[float] = []
    cum_pv = 0.0
    cum_v = 0.0
    for c in candles:
        typical = (c.high + c.low + c.close) / 3.0
        cum_pv += typical * c.volume
        cum_v += c.volume
        if cum_v > 0:
            out.append(cum_pv / cum_v)
        else:
            out.append(c.close)
    return out


# ---- volume helpers --------------------------------------------------------


def avg_volume(candles: list[Candle], period: int = 20) -> float:
    if not candles:
        return 0.0
    window = [c.volume for c in candles[-period:]]
    return sum(window) / len(window) if window else 0.0


def highest_high(candles: list[Candle]) -> float:
    return max((c.high for c in candles), default=0.0)
