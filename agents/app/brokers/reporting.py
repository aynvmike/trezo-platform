"""Read-only, paper-only broker evidence; no runtime, OAuth or trading imports.

Transport is GET-only and pinned to Alpaca's paper origin. Missing/invalid or
unexhausted reads are null, never zero/empty. Identity checks establish distinct
returned broker accounts, not an independently verified book-to-account mapping.

API references (verified 2026-09-18):
https://docs.alpaca.markets/us/reference/getallorders-1
https://docs.alpaca.markets/us/reference/getaccountactivities-2
https://docs.alpaca.markets/us/reference/getaccountportfoliohistory-1
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import math
import re

from app.brokers.endpoints import PAPER_BASE_URL, paper_base_url

PATHS = {
    "/v2/account", "/v2/positions", "/v2/orders",
    "/v2/account/activities", "/v2/account/portfolio/history",
}
ACCOUNT_NUMBERS = "equity last_equity cash buying_power non_marginable_buying_power options_approved_level options_trading_level".split()
ACCOUNT_TEXT = "currency status".split()
POSITION_NUMBERS = "qty qty_available avg_entry_price current_price market_value cost_basis unrealized_pl unrealized_intraday_pl".split()
ORDER_NUMBERS = "qty filled_qty filled_avg_price stop_price limit_price notional".split()
ORDER_TEXT = "id symbol asset_class side type order_class time_in_force status submitted_at created_at filled_at canceled_at expired_at".split()
ACTIVITY_NUMBERS = "qty price net_amount cum_qty leaves_qty per_share_amount".split()
ACTIVITY_TEXT = "id activity_type type transaction_time date created_at symbol side order_id status".split()


class ReadFailed(Exception):
    """Only a fixed diagnostic category may leave the transport."""


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _date(value):
    if not isinstance(value, str):
        raise ReadFailed("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ReadFailed("invalid_timestamp") from None


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ReadFailed("invalid_numeric_value")
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise ReadFailed("invalid_numeric_value") from None
    if not math.isfinite(number):
        raise ReadFailed("invalid_numeric_value")
    # Preserve broker decimal strings rather than round quantities through float.
    return value


def _timestamp_key(value):
    """Retain broker nanoseconds that datetime otherwise truncates."""
    parsed = _date(value)
    fraction = re.search(r"T\d{2}:\d{2}:\d{2}\.(\d+)(?:Z|[+-])", value)
    subsecond = Decimal("0." + fraction.group(1)) if fraction else Decimal(0)
    return parsed.replace(microsecond=0), subsecond


def _project(row, texts=(), numbers=(), required=()):
    if not isinstance(row, dict) or any(row.get(k) in (None, "") for k in required):
        raise ReadFailed("invalid_response")
    result = {}
    for key in texts:
        value = row.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 512):
            raise ReadFailed("invalid_response")
        result[key] = value
    result.update((key, _number(row.get(key))) for key in numbers)
    return result


def _rows(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ReadFailed("invalid_response")
    return value


def _order(row, depth=0):
    if depth > 4:
        raise ReadFailed("invalid_order_nesting")
    result = _project(row, ORDER_TEXT, ORDER_NUMBERS, ("id", "status"))
    legs = row.get("legs")
    result["legs"] = None if legs is None else [_order(r, depth + 1) for r in _rows(legs)]
    return result


class PaperReader:
    """One account's direct, verified-TLS, nonredirecting GET transport."""

    def __init__(self, account, client):
        paper_base_url(account.base_url)  # Reject malformed/live/foreign origins.
        self.account, self.client = account, client

    def get(self, path, params=None):
        if path not in PATHS:
            raise ReadFailed("endpoint_refused")
        try:
            response = self.client.get(PAPER_BASE_URL + path, params=params,
                                       headers=self.account.headers())
            status = response.status_code
            if status != 200:
                category = ("authentication_failed" if status in (401, 403) else
                            "rate_limited" if status == 429 else
                            "broker_unavailable" if status >= 500 else "http_error")
                raise ReadFailed(category)
            return response.json()
        except ReadFailed:
            raise
        except Exception as exc:
            category = {
                "ConnectTimeout": "connect_timeout", "ReadTimeout": "read_timeout",
                "PoolTimeout": "pool_timeout", "ConnectError": "connection_failed",
                "JSONDecodeError": "invalid_json",
            }.get(type(exc).__name__, "transport_failed")
            raise ReadFailed(category) from None

    def orders(self, start, end, max_pages, *, open_only=False, page_size=500):
        params = {"status": "open" if open_only else "all", "limit": page_size,
                  "direction": "desc", "nested": "true"}
        if not open_only:
            params.update(after=start.isoformat(), until=end.isoformat())
        collected, seen = [], set()
        previous_time = None
        for _ in range(max_pages):
            page = _rows(self.get("/v2/orders", params))
            crossed_start = False
            for row in page:
                projected = _order(row)
                oid = projected["id"]
                if oid in seen:
                    raise ReadFailed("pagination_no_progress")
                seen.add(oid)
                submitted = _timestamp_key(row.get("submitted_at") or row.get("created_at"))
                if previous_time is not None and submitted > previous_time:
                    raise ReadFailed("invalid_order_sort")
                previous_time = submitted
                if open_only or _timestamp_key(start.isoformat()) < submitted < _timestamp_key(end.isoformat()):
                    collected.append(projected)
                if not open_only and submitted <= _timestamp_key(start.isoformat()):
                    crossed_start = True
            if len(page) < page_size or crossed_start:
                return collected
            # ID cursor avoids losing orders with identical timestamps. Alpaca
            # forbids combining before_order_id with after/until, so subsequent
            # pages are filtered locally against the original fixed window.
            params.pop("after", None)
            params.pop("until", None)
            params["before_order_id"] = page[-1]["id"]
        raise ReadFailed("pagination_limit")

    def activities(self, start, end, max_pages, *, page_size=100):
        params = {"after": start.isoformat(), "until": end.isoformat(),
                  "direction": "desc", "page_size": page_size}
        collected, seen = [], set()
        for _ in range(max_pages):
            page = _rows(self.get("/v2/account/activities", params))
            for row in page:
                projected = _project(row, ACTIVITY_TEXT, ACTIVITY_NUMBERS,
                                     ("id", "activity_type"))
                aid = projected["id"]
                if aid in seen:
                    raise ReadFailed("pagination_no_progress")
                seen.add(aid)
                collected.append(projected)
            if len(page) < page_size:
                return collected
            params["page_token"] = page[-1]["id"]
        raise ReadFailed("pagination_limit")

    def history(self, start, end):
        raw = self.get("/v2/account/portfolio/history", {
            "start": start.isoformat(), "end": end.isoformat(),
            "timeframe": "1D", "cashflow_types": "ALL",
        })
        if not isinstance(raw, dict):
            raise ReadFailed("invalid_response")
        result = _project(raw, ("timeframe",), ("base_value",))
        asof = raw.get("base_value_asof")
        if isinstance(asof, str) and not asof.isdigit():
            _date(asof)
            result["base_value_asof"] = asof
        else:
            result["base_value_asof"] = _number(asof)
        for key in ("timestamp", "equity", "profit_loss", "profit_loss_pct"):
            values = raw.get(key)
            if not isinstance(values, list):
                raise ReadFailed("invalid_history")
            result[key] = [_number(value) for value in values]
        if len({len(result[k]) for k in ("timestamp", "equity", "profit_loss", "profit_loss_pct")}) != 1:
            raise ReadFailed("invalid_history")
        if any(t is None or float(t) != int(float(t)) for t in result["timestamp"]):
            raise ReadFailed("invalid_history")
        cashflow = raw.get("cashflow")
        result["cashflow"] = None
        if cashflow is not None:
            if not isinstance(cashflow, dict):
                raise ReadFailed("invalid_history")
            result["cashflow"] = {}
            for kind, values in cashflow.items():
                if not isinstance(kind, str) or not re.fullmatch(r"[A-Z_]{1,24}", kind) or not isinstance(values, list):
                    raise ReadFailed("invalid_history")
                if len(values) != len(result["timestamp"]):
                    raise ReadFailed("invalid_history")
                result["cashflow"][kind] = [_number(value) for value in values]
        # Daily null observations remain null. Do not calculate any returns.
        return result


def _read(operation):
    result = {"started_at": _stamp(), "data": None, "complete": False}
    try:
        result["data"] = operation()
        result["complete"] = True
    except ReadFailed as exc:
        result["error"] = str(exc)
    except Exception:
        result["error"] = "read_failed"
    result["completed_at"] = _stamp()
    return result


def export_audit(accounts, *, after=None, until=None, max_pages=20, client=None):
    """Collect three books. Dependency injection is for offline tests only."""
    end = _date(until) if until else datetime.now(timezone.utc)
    start = _date(after) if after else end - timedelta(days=1)
    if not start < end or end - start > timedelta(days=3660):
        raise ReadFailed("invalid_window")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= 100:
        raise ReadFailed("invalid_page_limit")
    if len(accounts) != 3 or len({a.account_key for a in accounts}) != 3:
        raise ReadFailed("expected_three_distinct_books")
    if client is None:
        import httpx
        with httpx.Client(timeout=15.0, verify=True, follow_redirects=False) as transport:
            return export_audit(accounts, after=start.isoformat(), until=end.isoformat(),
                                max_pages=max_pages, client=transport)
    readers = [PaperReader(account, client) for account in accounts]
    report = {
        "schema": "trezo.broker-audit.v1", "venue": "paper", "started_at": _stamp(),
        "window": {"after_exclusive": start.isoformat(), "until_exclusive": end.isoformat()},
        "max_pages_per_collection": max_pages, "activity_types": "ALL (no filter)",
        "history": {"timeframe": "1D", "cashflow_types": "ALL"},
        "notes": ["Sequential current snapshots; not atomic or historical account snapshots.",
                  "Orders window uses submission time; activities window uses creation time.",
                  "Daily portfolio points follow broker trading-day boundaries and may be null.",
                  "Broker-reported P/L only; no inferred account-return calculation.",
                  "Distinct identity is not an independent verification of book-to-broker mapping."],
        "books": [],
    }
    identities = []
    for reader in readers:
        identity = []
        def account_read():
            raw = reader.get("/v2/account")
            row = _project(raw, ACCOUNT_TEXT, ACCOUNT_NUMBERS,
                           ("id", "equity", "cash", "buying_power"))
            broker_id = raw["id"]
            if not isinstance(broker_id, str) or not broker_id.strip():
                raise ReadFailed("invalid_broker_identity")
            identity.append(broker_id)
            row["trading_blocked"] = raw.get("trading_blocked") if isinstance(raw.get("trading_blocked"), bool) else None
            return row
        account = _read(account_read)
        broker_id = identity[0] if identity else None
        identities.append(broker_id)
        report["books"].append({
            "slot": reader.account.account_id, "book_key": reader.account.account_key,
            "broker_id_hash": hashlib.sha256(broker_id.encode()).hexdigest() if broker_id else None,
            "account": account,
        })
    verified = all(identities) and len(set(identities)) == 3
    report["distinct_broker_identities_verified"] = bool(verified)
    for reader, book in zip(readers, report["books"]):
        operations = {
            "positions": lambda r=reader: [_project(row, ("symbol", "asset_class", "side"),
                POSITION_NUMBERS, ("symbol", "qty")) for row in _rows(r.get("/v2/positions"))],
            "open_orders": lambda r=reader: r.orders(start, end, max_pages, open_only=True),
            "recent_orders": lambda r=reader: r.orders(start, end, max_pages),
            "activities": lambda r=reader: r.activities(start, end, max_pages),
            "portfolio_history": lambda r=reader: r.history(start, end),
        }
        for label, operation in operations.items():
            book[label] = (_read(operation) if verified else
                           {"data": None, "complete": False, "error": "identity_unverified"})
    report["complete"] = bool(verified) and all(
        book[label]["complete"] for book in report["books"]
        for label in ("account", "positions", "open_orders", "recent_orders", "activities", "portfolio_history"))
    report["completed_at"] = _stamp()
    return report
