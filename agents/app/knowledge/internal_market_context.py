"""Source-timed equity benchmark context from one existing Alpaca data call.

This is a SPY/QQQ price-versus-provider-daily-VWAP proxy, not a news report or a
full-market regime estimate. No account, order, memory or relay writes occur.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
import math
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SYMBOLS = ("SPY", "QQQ")
MAX_SOURCE_AGE_SECONDS = 300
PROXY_VERSION = "equity-benchmarks-vwap-v1"
SOURCE = "alpaca_stock_snapshots"
MISSING_FIELDS = ("vix", "breadth", "news", "social", "movers", "catalysts")


class TimezoneUnavailable(ValueError):
    pass


def _new_york_timezone():
    try:
        return ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:
        # Windows may lack the system IANA database. pytz is already a
        # dependency of the engine's pinned APScheduler 3.10.4; it supplies
        # the same DST-aware zone without requiring a deployment install.
        try:
            import pytz
            return pytz.timezone("America/New_York")
        except (ImportError, KeyError) as exc:
            raise TimezoneUnavailable("new_york_timezone_unavailable") from exc


@dataclass(frozen=True)
class ContextResult:
    status: Literal["ready", "unavailable", "invalid"]
    reason: str
    feed: str
    payload: dict | None = None
    symbol: str | None = None
    error_type: str | None = None

    def receipt(self) -> dict:
        provenance = (self.payload or {}).get("provenance", {})
        return {"event": "internal_market_context", "status": self.status,
                "reason": self.reason, "source": SOURCE, "feed": self.feed,
                "proxy_version": PROXY_VERSION, "symbol": self.symbol,
                "error_type": self.error_type, "as_of": (self.payload or {}).get("as_of"),
                "snapshot_id": provenance.get("snapshot_id"),
                "missing_fields": list(MISSING_FIELDS), "llm_calls": 0,
                "execution_enabled": False, "account_scope": "none"}


def _stamp(value) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("invalid_timestamp")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid_timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("naive_timestamp")
    return stamp.astimezone(timezone.utc)


def _positive(value) -> float:
    if isinstance(value, bool):
        raise ValueError("invalid_price_or_volume")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid_price_or_volume") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError("invalid_price_or_volume")
    return number


def _bar(raw, *, vwap=False) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("missing_bar")
    bar = {key: _positive(raw.get(key)) for key in ("o", "h", "l", "c", "v")}
    if not bar["l"] <= min(bar["o"], bar["c"]) <= max(bar["o"], bar["c"]) <= bar["h"]:
        raise ValueError("inconsistent_bar_prices")
    if vwap:
        bar["vw"] = _positive(raw.get("vw"))
        if not bar["l"] <= bar["vw"] <= bar["h"]:
            raise ValueError("inconsistent_bar_vwap")
    bar["t"] = _stamp(raw.get("t")).isoformat()
    return bar


def _session(now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("aware_clock_required")
    local = now.astimezone(_new_york_timezone())
    # The close's last completed minute remains useful only within its TTL.
    # Holidays and early closes require actual fresh bars; no calendar is guessed.
    if local.weekday() >= 5 or not time(9, 31) <= local.time() <= time(16, 5):
        raise ValueError("outside_regular_equity_context_window")
    return local


def build_context(raw, *, feed: str, now: datetime) -> ContextResult:
    """Validate both symbols before exposing any directional inference."""
    symbol = None
    try:
        local = _session(now)
        if feed not in {"iex", "sip"}:
            raise ValueError("unsupported_feed")
        if not isinstance(raw, dict):
            raise ValueError("invalid_snapshot_response")
        evidence = {}
        for symbol in SYMBOLS:
            snapshot = raw.get(symbol)
            if not isinstance(snapshot, dict):
                raise ValueError("missing_benchmark_snapshot")
            minute = _bar(snapshot.get("minuteBar"))
            daily = _bar(snapshot.get("dailyBar"), vwap=True)
            previous = _bar(snapshot.get("prevDailyBar"))
            minute_at, daily_at, previous_at = [_stamp(b["t"]) for b in (minute, daily, previous)]
            age = (now - minute_at).total_seconds()
            if age < 0 or daily_at > now or previous_at > now:
                raise ValueError("future_bar")
            if minute_at + timedelta(minutes=1) > now:
                raise ValueError("unfinished_minute_bar")
            if age > MAX_SOURCE_AGE_SECONDS:
                raise ValueError("stale_minute_bar")
            minute_local = minute_at.astimezone(local.tzinfo)
            if (minute_local.date() != local.date()
                    or daily_at.astimezone(local.tzinfo).date() != local.date()
                    or not time(9, 30) <= minute_local.time() < time(16)):
                raise ValueError("cross_session_bar")
            previous_day = previous_at.astimezone(local.tzinfo).date()
            if not 1 <= (local.date() - previous_day).days <= 10:
                raise ValueError("invalid_previous_session")
            evidence[symbol] = {"minute_bar": minute, "session_bar": daily,
                                "previous_session_bar": previous,
                                "price_basis": "completed_minute_close",
                                "below_session_vwap": minute["c"] < daily["vw"],
                                "above_session_vwap": minute["c"] > daily["vw"]}
        oldest = min(_stamp(e["minute_bar"]["t"]) for e in evidence.values())
        below = all(e["below_session_vwap"] for e in evidence.values())
        above = all(e["above_session_vwap"] for e in evidence.values())
        regime = "risk_off" if below else ("risk_on" if above else "mixed")
        indices = {s: (e["minute_bar"]["c"] / e["previous_session_bar"]["c"] - 1) * 100
                   for s, e in evidence.items()}
        if not all(math.isfinite(change) for change in indices.values()):
            raise ValueError("nonfinite_index_change")
        provenance = {"proxy_version": PROXY_VERSION, "feed": feed,
                      "feed_scope": "single_exchange_iex" if feed == "iex" else "consolidated_sip",
                      "context_scope": "SPY_QQQ_equity_benchmark_direction_only",
                      "session_date": local.date().isoformat(), "session_timezone": "America/New_York",
                      "regime_basis": "both_completed_minute_closes_vs_provider_current_day_bar_vwap",
                      "daily_vwap_scope": "provider_aggregate; exact_trade_condition_and_session_inclusion_not_independently_verified",
                      "previous_session_basis": "provider_reported_previous_daily_bar; calendar_not_independently_verified",
                      "source_as_of": oldest.isoformat(), "max_source_age_seconds": MAX_SOURCE_AGE_SECONDS,
                      "missing_fields": list(MISSING_FIELDS), "benchmarks": evidence}
        provenance["snapshot_id"] = hashlib.sha256(json.dumps(
            provenance, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        payload = {"as_of": oldest.isoformat(), "slot": "internal-equity-benchmarks",
                   "source": SOURCE, "regime": regime,
                   "indices": indices,
                   "summary": (f"SPY/QQQ direction proxy: {regime}; completed minute closes versus "
                               f"provider current-day bar VWAP on {feed.upper()}. "
                               "Benchmark prices only; news, VIX, breadth and movers are unavailable."),
                   "provenance": provenance}
        return ContextResult("ready", "validated_benchmark_proxy", feed, payload)
    except TimezoneUnavailable:
        return ContextResult("unavailable", "new_york_timezone_unavailable", feed)
    except ValueError as exc:
        return ContextResult("invalid", str(exc), feed, symbol=symbol)


async def fetch_context(*, now: datetime | None = None) -> ContextResult:
    """One batch GET, explicit existing feed, and no modeled-data fallback."""
    from app.brokers import alpaca_data
    current = now if now is not None else datetime.now(timezone.utc)
    feed = alpaca_data.DATA_FEED
    try:
        _session(current)
    except TimezoneUnavailable:
        return ContextResult("unavailable", "new_york_timezone_unavailable", feed)
    except ValueError as exc:
        return ContextResult("unavailable", str(exc), feed)
    try:
        raw = await alpaca_data._data_get("/v2/stocks/snapshots",
                                          {"symbols": ",".join(SYMBOLS), "feed": feed})
    except Exception as exc:
        return ContextResult("unavailable", "snapshot_request_failed", feed,
                             error_type=type(exc).__name__)
    if raw is None:
        return ContextResult("unavailable", "snapshot_data_unavailable", feed)
    return build_context(raw, feed=feed, now=current)
