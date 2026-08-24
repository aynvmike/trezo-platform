"""Guards for the forex data feed (Twelve Data primary, Kraken fallback).

The three failure modes these tests exist to prevent:

  1. TIME-REVERSED TAPE. Twelve Data returns values newest-first; the
     engine expects oldest-first. Unreversed, every breakout reads as a
     breakdown and the scorer confidently trades the mirror image.
  2. RATE-LIMIT BLOCKING. The free tier is 8 credits/min and the
     scanner bursts 10 pairs per tick. The budget guard must FALL
     THROUGH to Kraken, never sleep -- an agent tick that waits out a
     rate limit stalls the whole scheduler lane.
  3. SOURCE FLAPPING. A cached result must be served regardless of
     which source produced it, so the scorer never sees two slightly
     different tapes for the same bars inside one window.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.data.forex as fx  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _td_payload(rows):
    return {"meta": {"symbol": "EUR/USD"}, "status": "ok",
            "values": [{"datetime": d, "open": o, "high": h,
                        "low": lo, "close": c}
                       for d, o, h, lo, c in rows]}


class _Resp:
    def __init__(self, payload):
        self._p = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self._p


class _Client:
    """Stub httpx.AsyncClient returning a canned payload."""
    def __init__(self, payload):
        self._p = payload
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def get(self, url, params=None):
        return _Resp(self._p)


def _with_stub(payload, fn):
    import httpx
    real = httpx.AsyncClient
    httpx.AsyncClient = lambda *a, **k: _Client(payload)  # type: ignore
    try:
        return fn()
    finally:
        httpx.AsyncClient = real


def _fresh():
    fx._cache.clear()
    fx._td_calls.clear()


# --- 1. the time-reversed tape ------------------------------------------

def test_twelve_data_newest_first_is_reversed():
    _fresh()
    payload = _td_payload([
        ("2026-08-24 08:00:00", 1.10, 1.11, 1.09, 1.105),   # newest
        ("2026-08-24 04:00:00", 1.09, 1.10, 1.08, 1.10),
        ("2026-08-24 00:00:00", 1.08, 1.09, 1.07, 1.09),    # oldest
    ])
    fx._td_key = lambda: "test-key"
    candles = _with_stub(payload, lambda: _run(
        fx._fetch_twelve_data("EURUSD", 240, 10)))
    assert len(candles) == 3
    assert candles[0].timestamp < candles[-1].timestamp, \
        "tape is time-reversed -- every breakout would read as a breakdown"
    assert candles[-1].close == 1.105


def test_fx_candles_carry_zero_volume_not_garbage():
    """No consolidated FX tape exists; 0.0 is the honest value. The
    scoring engine's volume criterion needs avg20 > 0, so these candles
    simply earn no volume points rather than fake ones."""
    _fresh()
    payload = _td_payload([("2026-08-24 00:00:00", 1.1, 1.2, 1.0, 1.15)])
    fx._td_key = lambda: "test-key"
    candles = _with_stub(payload, lambda: _run(
        fx._fetch_twelve_data("EURUSD", 240, 10)))
    assert candles and candles[0].volume == 0.0


# --- 2. the budget guard -------------------------------------------------

def test_budget_guard_falls_through_never_waits():
    _fresh()
    started = time.time()
    for _ in range(fx._TD_BUDGET_PER_MIN):
        fx._td_calls.append(started)
    fx._td_key = lambda: "test-key"
    candles = _run(fx._fetch_twelve_data("EURUSD", 240, 10))
    assert candles == [], "over budget must return [], not call out"
    assert time.time() - started < 1.0, "the guard must never sleep"


def test_budget_window_rolls_off():
    _fresh()
    old = time.time() - 61.0
    for _ in range(fx._TD_BUDGET_PER_MIN):
        fx._td_calls.append(old)
    assert fx._td_budget_ok() is True, "calls older than 60s still counted"


def test_budget_leaves_headroom_under_the_real_limit():
    """The real limit is 8/min and the macro module shares the key. A
    budget of 8 here is a budget of 9+ in production."""
    assert fx._TD_BUDGET_PER_MIN < 8


# --- 3. source selection and the cache ----------------------------------

def test_no_key_means_kraken_path():
    _fresh()
    fx._td_key = lambda: ""
    candles = _run(fx._fetch_twelve_data("EURUSD", 240, 10))
    assert candles == []


def test_unmapped_interval_stays_off_twelve_data():
    """Kraken accepts arbitrary minute intervals; Twelve Data does not.
    An unmapped interval must not burn a TD credit on a guaranteed 4xx."""
    _fresh()
    fx._td_key = lambda: "test-key"
    candles = _run(fx._fetch_twelve_data("EURUSD", 7, 10))
    assert candles == []
    assert len(fx._td_calls) == 0, "an unmapped interval burned a credit"


def test_unknown_pair_is_refused():
    _fresh()
    assert _run(fx.fetch_forex_candles("XAUXAG", 240)) == []


def test_cache_serves_whichever_source_filled_it():
    _fresh()
    sentinel = ["CANDLE"]
    fx._cache[("EURUSD", 240)] = (sentinel, time.time())
    got = _run(fx.fetch_forex_candles("EURUSD", 240))
    assert got is sentinel, "a fresh cache entry must short-circuit both sources"


def test_expired_cache_is_not_served():
    _fresh()
    fx._cache[("EURUSD", 240)] = (["STALE"], time.time() - fx._CACHE_TTL_S - 1)

    async def _no_td(*a, **k):
        return []
    async def _no_kraken(*a, **k):
        return []
    real_td, real_kr = fx._fetch_twelve_data, fx._fetch_kraken
    fx._fetch_twelve_data, fx._fetch_kraken = _no_td, _no_kraken
    try:
        got = _run(fx.fetch_forex_candles("EURUSD", 240))
    finally:
        fx._fetch_twelve_data, fx._fetch_kraken = real_td, real_kr
    assert got == [], "an expired cache entry was served as fresh"


def test_kraken_is_the_fallback_when_td_empty():
    _fresh()
    async def _no_td(*a, **k):
        return []
    async def _kraken(*a, **k):
        return ["KRAKEN_CANDLE"]
    real_td, real_kr = fx._fetch_twelve_data, fx._fetch_kraken
    fx._fetch_twelve_data, fx._fetch_kraken = _no_td, _kraken
    try:
        got = _run(fx.fetch_forex_candles("GBPUSD", 240))
    finally:
        fx._fetch_twelve_data, fx._fetch_kraken = real_td, real_kr
    assert got == ["KRAKEN_CANDLE"]
    assert fx._cache[("GBPUSD", 240)][0] == ["KRAKEN_CANDLE"]
