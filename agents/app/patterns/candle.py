"""Candle dataclass — the core type the pattern library operates on."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class Candle:
    """OHLCV candle for a single bar.

    Fields use the standard names so we can plug any data source.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    # ---- helpers ----

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    # ---- constructors ----

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Candle":
        """Tolerant constructor for JSON/dict shapes from any data source."""
        ts_raw = d.get("timestamp") or d.get("time") or d.get("t")
        if isinstance(ts_raw, (int, float)):
            ts = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
        elif isinstance(ts_raw, str):
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                ts = datetime.now(timezone.utc)
        elif isinstance(ts_raw, datetime):
            ts = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.now(timezone.utc)

        return cls(
            timestamp=ts,
            open=float(d.get("open", d.get("o", 0.0))),
            high=float(d.get("high", d.get("h", 0.0))),
            low=float(d.get("low", d.get("l", 0.0))),
            close=float(d.get("close", d.get("c", 0.0))),
            volume=float(d.get("volume", d.get("v", 0.0))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }
