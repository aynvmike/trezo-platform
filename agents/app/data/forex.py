"""Forex data feed -- Twelve Data primary, Kraken public OHLC fallback.

HISTORY. v1 (2026-07-02) was Kraken-only: free and key-less, but a
crypto exchange's fiat book, not the FX market. Its "volume" was
Kraken's own book only, and its bar timestamps drifted from true FX
sessions. v2 (2026-08-24, Mike: "for the data information") puts
Twelve Data first:

    - real FX aggregate data, 1000+ pairs
    - 4h bars back to ~2023, DAILY bars back to 2007 -- the first lane
      in the engine with a real backtest window
    - free tier, key already in .env (TWELVE_DATA_API_KEY -- probed
      2026-08-24: time_series works for FX; the 2026-08-22 "retire this
      key" verdict tested dividends/earnings endpoints only and was
      wrong about forex)

THE RATE LIMIT IS THE DESIGN CONSTRAINT. Free tier = 8 API credits per
MINUTE (verified live: burst of 9 -> HTTP 429). The scanner ticks 10
pairs every 180s, which averages ~3.3/min but BURSTS 10 in one tick.
Two defenses, both required:

    1. a per-pair candle cache (10 min TTL -- a 4h bar does not need
       refreshing every 3 minutes), and
    2. a rolling 60s call budget of 7 (headroom under 8). When the
       budget is spent, that call falls through to Kraken instead of
       waiting -- an agent tick must never sleep its way past a rate
       limit, and stale-but-real Kraken data beats blocking the loop.

Twelve Data reports NO volume for FX (there is no consolidated FX
tape; nobody has real volume). Candles carry volume=0.0, so the
scoring engine's volume criterion (needs avg20 > 0) simply earns no
points -- which is more honest than the Kraken-book volume it replaces.

Both sources fail to []; callers must stay fail-open.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Optional

# Canonical pair names the scanner uses. Kraken accepts these directly;
# Twelve Data wants BASE/QUOTE.
FOREX_MAJORS: dict[str, str] = {
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "AUDUSD": "AUDUSD",
    "USDCAD": "USDCAD",
    # 2026-07-13 (Mike): five liquid crosses so the forex desk trains on
    # more than the majors.
    "USDCHF": "USDCHF",
    "EURGBP": "EURGBP",
    "EURJPY": "EURJPY",
    "EURCAD": "EURCAD",
    "EURAUD": "EURAUD",
}

_KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
_TD_URL = "https://api.twelvedata.com/time_series"

# Twelve Data interval strings, keyed by minutes. Anything unmapped
# falls back to Kraken, which accepts arbitrary minute intervals.
_TD_INTERVALS: dict[int, str] = {
    1: "1min", 5: "5min", 15: "15min", 30: "30min", 45: "45min",
    60: "1h", 120: "2h", 240: "4h", 480: "8h", 1440: "1day",
}

# Rolling 60-second call budget. 7, not 8: the macro module shares this
# key, and a shared limit with zero headroom is a limit already blown.
_TD_BUDGET_PER_MIN = 7
_td_calls: deque = deque(maxlen=32)

# (pair, interval_min) -> (candles, fetched_at). A 4h bar refreshed
# every 10 minutes is still the same bar 96% of the time.
_CACHE_TTL_S = 600.0
_cache: dict[tuple, tuple[list, float]] = {}


def _td_key() -> str:
    try:
        from app.config import get_settings
        return (getattr(get_settings(), "twelve_data_api_key", "") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _td_budget_ok(now: Optional[float] = None) -> bool:
    """True if a Twelve Data call fits in the rolling 60s budget."""
    t = time.time() if now is None else now
    while _td_calls and t - _td_calls[0] > 60.0:
        _td_calls.popleft()
    return len(_td_calls) < _TD_BUDGET_PER_MIN


def _td_symbol(pair: str) -> str:
    p = (pair or "").upper().replace("/", "")
    return f"{p[:3]}/{p[3:]}" if len(p) == 6 else ""


async def _fetch_twelve_data(pair: str, interval_min: int, limit: int) -> list:
    """Candles from Twelve Data, oldest->newest. [] on any failure.

    NB: Twelve Data returns values NEWEST FIRST. Forgetting to reverse
    hands the scoring engine a time-reversed tape in which every
    breakout is a breakdown. The test file pins this.
    """
    interval = _TD_INTERVALS.get(int(interval_min))
    symbol = _td_symbol(pair)
    key = _td_key()
    if not interval or not symbol or not key:
        return []
    if not _td_budget_ok():
        return []
    _td_calls.append(time.time())
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_TD_URL, params={
                "symbol": symbol, "interval": interval,
                "outputsize": str(int(limit)),
                "timezone": "UTC",           # default is exchange-local
                "apikey": key,
            })
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, dict) or str(data.get("status", "ok")).lower() == "error":
        return []
    values = data.get("values") or []
    if not values:
        return []
    try:
        from app.patterns import Candle
    except Exception:  # noqa: BLE001
        return []
    from datetime import datetime, timezone
    out = []
    for v in reversed(values):               # newest-first -> oldest-first
        try:
            ts = datetime.fromisoformat(str(v["datetime"])).replace(
                tzinfo=timezone.utc)
            out.append(Candle(
                timestamp=ts,
                open=float(v["open"]), high=float(v["high"]),
                low=float(v["low"]), close=float(v["close"]),
                volume=0.0,                  # FX has no consolidated tape
            ))
        except Exception:  # noqa: BLE001
            continue
    return out


async def _fetch_kraken(pair: str, interval_min: int, limit: int) -> list:
    """The v1 path, unchanged: Kraken public OHLC. [] on any failure."""
    name = FOREX_MAJORS.get((pair or "").upper().replace("/", ""))
    if not name:
        return []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_KRAKEN_OHLC_URL,
                                    params={"pair": name,
                                            "interval": str(int(interval_min))})
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, dict) or data.get("error"):
        return []
    result = data.get("result") or {}
    rows = None
    for k, v in result.items():
        if k != "last" and isinstance(v, list):
            rows = v
            break
    if not rows:
        return []
    try:
        from app.patterns import Candle
    except Exception:  # noqa: BLE001
        return []
    from datetime import datetime, timezone
    out = []
    for r in rows[-int(limit):]:
        try:
            out.append(Candle(
                timestamp=datetime.fromtimestamp(float(r[0]), tz=timezone.utc),
                open=float(r[1]), high=float(r[2]),
                low=float(r[3]), close=float(r[4]),
                volume=float(r[6]),
            ))
        except Exception:  # noqa: BLE001
            continue
    return out


async def fetch_forex_candles(pair: str, interval_min: int = 60,
                              limit: int = 200) -> list:
    """OHLC candles for a major pair, oldest->newest, as app Candle
    objects. Twelve Data when the key and budget allow, Kraken
    otherwise. Empty list on total failure -- callers stay fail-open.

    The result is cached whichever source produced it; a Kraken-fed
    cache entry is NOT retried against Twelve Data until it expires,
    because flapping between sources mid-window would hand the scorer
    two slightly different tapes for the same bars.
    """
    p = (pair or "").upper().replace("/", "")
    if p not in FOREX_MAJORS:
        return []
    now = time.time()
    hit = _cache.get((p, int(interval_min)))
    if hit and (now - hit[1]) < _CACHE_TTL_S:
        return hit[0]

    candles = await _fetch_twelve_data(p, interval_min, limit)
    source = "twelve_data"
    if not candles:
        candles = await _fetch_kraken(p, interval_min, limit)
        source = "kraken"
    if candles:
        _cache[(p, int(interval_min))] = (candles, now)
        try:
            import structlog
            structlog.get_logger("trezo.forex_data").debug(
                "forex_candles.fetched", pair=p, source=source,
                n=len(candles))
        except Exception:  # noqa: BLE001
            pass
    return candles
