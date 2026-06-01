"""Cross-asset market awareness.

Trezo's specialist scanners hunt within their own universes — but the
user trades inside a much wider market. This module gives the agents a
view of the whole landscape: stocks, crypto, gold, the dollar, bonds,
and covered-call income ETFs. The same helper backs both the
market_horizon agent (so it can emit cross-asset insights) and the
/markets/pulse HTTP endpoint that the Market Horizons page reads.

Each asset class is represented by a single liquid proxy that any
brokerage can quote, so the snapshot stays cheap and reliable:

    stocks -> SPY      (S&P 500)
    crypto -> BTC      (Bitcoin via CoinGecko)
    gold   -> GLD      (Gold ETF)
    usd    -> UUP      (US Dollar bullish ETF — proxy for DXY)
    bonds  -> TLT      (20+ year Treasuries)
    income -> JEPI     (Covered-call income ETF — same family as the
                        REX-style products FEPI / NVDY / MSFY / YMAX)
"""

from __future__ import annotations

import time
from typing import Optional

from app.data.candles import fetch_candles_for

# Mike feedback 2026-05-30: the Market Horizons card was loading
# inconsistently — sometimes full, sometimes empty. Root cause was
# yfinance/finnhub timeouts on individual asset fetches. With this
# 60-second cache, every browser refresh inside the window reads
# the same snapshot, so partial-failure runs never overwrite a
# previously-good one in the user's view.
_SNAPSHOT_TTL = 60.0
_snapshot_cache: dict[int, tuple[dict, float]] = {}


UNIVERSE: dict[str, tuple[str, str]] = {
    "stocks": ("SPY",  "U.S. stocks"),
    "crypto": ("BTC",  "Crypto"),
    "gold":   ("GLD",  "Gold"),
    "usd":    ("UUP",  "US dollar"),
    "bonds":  ("TLT",  "Long bonds"),
    "income": ("JEPI", "Income ETFs"),
}

# Cross-asset relationships worth highlighting. The classic pairs:
# Gold tends to move opposite the dollar; Bitcoin behaves like a risk
# asset (often inverse to the dollar in macro regimes); bonds rally
# when stocks come under pressure.
PAIRS: list[tuple[str, str, str]] = [
    ("gold",   "usd",    "Gold typically moves opposite the dollar."),
    ("crypto", "usd",    "Crypto tends to weaken when the dollar firms."),
    ("bonds",  "stocks", "Bonds and stocks often pull in opposite directions."),
]


def _returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev:
            out.append(closes[i] / prev - 1.0)
    return out


def _correlation(a: list[float], b: list[float]) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 5:
        return None
    a = a[-n:]; b = b[-n:]
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / n
    va  = sum((x - ma) ** 2 for x in a) / n
    vb  = sum((x - mb) ** 2 for x in b) / n
    if va <= 0 or vb <= 0:
        return None
    return cov / ((va ** 0.5) * (vb ** 0.5))


async def compute_snapshot(corr_window: int = 30) -> dict:
    """Pulse + recent correlations across the six proxy assets.

    Returns a JSON-shaped dict the agent emits in messages and the web
    page renders as cards. Missing data (a feed gap on one asset) does
    not break the rest — that asset is simply absent from `assets`.

    60-second in-memory cache (Mike 2026-05-30): the underlying
    fetch_candles_for() can timeout on yfinance/finnhub, and a partial
    snapshot would replace a previously-good one in the UI. The cache
    keeps the last good payload in front of the user during transient
    outages. The TTL is short enough that fresh data takes over within
    a minute when the feeds recover.
    """
    now = time.time()
    cached = _snapshot_cache.get(corr_window)
    if cached is not None and (now - cached[1]) < _SNAPSHOT_TTL:
        return cached[0]

    closes_by_key: dict[str, list[float]] = {}
    assets: dict[str, dict] = {}

    for key, (ticker, label) in UNIVERSE.items():
        try:
            candles = await fetch_candles_for(ticker)
        except Exception:
            continue
        if not candles or len(candles) < 6:
            continue
        closes = [float(c.close) for c in candles]
        last = closes[-1]
        back5 = closes[-6] if len(closes) >= 6 else closes[0]
        pct = (last / back5 - 1.0) * 100.0 if back5 else 0.0
        spark = closes[-min(60, len(closes)):]
        assets[key] = {
            "ticker": ticker,
            "label": label,
            "price": round(last, 2),
            "change_5d_pct": round(pct, 2),
            "sparkline": [round(p, 2) for p in spark],
        }
        closes_by_key[key] = closes

    correlations: list[dict] = []
    for a_key, b_key, note in PAIRS:
        if a_key not in closes_by_key or b_key not in closes_by_key:
            continue
        a_ret = _returns(closes_by_key[a_key])[-corr_window:]
        b_ret = _returns(closes_by_key[b_key])[-corr_window:]
        rho = _correlation(a_ret, b_ret)
        if rho is None:
            continue
        correlations.append({
            "a": a_key,
            "b": b_key,
            "a_label": assets[a_key]["label"],
            "b_label": assets[b_key]["label"],
            "rho": round(rho, 2),
            "window_bars": min(len(a_ret), len(b_ret)),
            "note": note,
        })

    snapshot = {"assets": assets, "correlations": correlations}

    # Only cache when we got something useful. If every external feed
    # failed and assets is empty, fall through so the next call gets
    # a fresh attempt instead of holding an empty payload for 60s.
    if assets:
        _snapshot_cache[corr_window] = (snapshot, now)
    return snapshot


def summarise_snapshot(snap: dict) -> str:
    """One plain-language sentence about today's cross-asset state."""
    assets = snap.get("assets") or {}
    if not assets:
        return "No market data yet — feeds may still be warming up."
    items = sorted(
        assets.items(),
        key=lambda kv: -float(kv[1].get("change_5d_pct", 0.0)),
    )
    top_key, top = items[0]
    bot_key, bot = items[-1]
    parts = [
        f"{top['label']} leads the past 5 days at {top['change_5d_pct']:+.1f}%; "
        f"{bot['label']} trails at {bot['change_5d_pct']:+.1f}%."
    ]
    for c in snap.get("correlations") or []:
        rho = c["rho"]
        if abs(rho) >= 0.4:
            shape = "negative" if rho < 0 else "positive"
            parts.append(
                f"{c['a_label']}/{c['b_label']} correlation {rho:+.2f} "
                f"({shape} — {c['note'].lower()})"
            )
    return " ".join(parts)
