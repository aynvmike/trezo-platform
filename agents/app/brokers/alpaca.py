"""Alpaca paper-trading client.

Phase 8a built the read side — account equity, buying power, positions.
Phase 8b adds the write side — bracket order placement — plus the market
clock. Trezo's trade rules (TREZO_NOVA_BOT_TRADE_RULES.md) target Alpaca's
paper API as the stock execution venue.

Everything is best-effort: with no keys configured, or on any error, the
read functions return None / [] and the write functions return an error
string, so the rest of Trezo can fall back to its internal paper ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from app.config import get_settings


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"


@dataclass
class AlpacaAccount:
    equity: float
    last_equity: float
    cash: float
    buying_power: float
    currency: str
    status: str
    pattern_day_trader: bool
    daytrade_count: int
    trading_blocked: bool
    # Options approval (0 = none, 1 = covered, 2 = long + spreads,
    # 3 = uncovered). Determines what the Wheel and Options Engine
    # can actually fire.
    options_approved_level: int = 0
    options_trading_level: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def alpaca_configured() -> bool:
    """True when both Alpaca API keys are present in settings."""
    s = get_settings()
    return bool(s.alpaca_api_key and s.alpaca_secret_key)


def _live_active() -> bool:
    """True only when the live executor is enabled AND live mode is set.

    Phase 10b groundwork: live_trading_enabled() is False until the
    deliberate go-live flip, so every Alpaca call below stays on the
    paper venue. This is the single switch that turns real money on."""
    try:
        from app.runtime.trading_mode import live_trading_enabled
        return live_trading_enabled()
    except Exception:  # noqa: BLE001
        return False


def broker_venue() -> str:
    """'live' or 'paper' - which venue Alpaca calls currently hit."""
    return "live" if _live_active() else "paper"


def _base_url() -> str:
    if _live_active():
        return LIVE_BASE_URL
    return get_settings().alpaca_base_url or PAPER_BASE_URL


def _headers() -> dict:
    s = get_settings()
    if _live_active():
        return {
            "APCA-API-KEY-ID": s.alpaca_live_api_key,
            "APCA-API-SECRET-KEY": s.alpaca_live_secret_key,
        }
    return {
        "APCA-API-KEY-ID": s.alpaca_api_key,
        "APCA-API-SECRET-KEY": s.alpaca_secret_key,
    }


def _headers_for(token: Optional["UserToken"]) -> dict:
    """Headers for either an OAuth user token or the env fallback."""
    if token is not None and token.access_token:
        # Alpaca's OAuth flow returns a Bearer access token; their REST
        # API accepts it in Authorization, no APCA headers needed.
        return {"Authorization": f"Bearer {token.access_token}"}
    return _headers()


@dataclass
class UserToken:
    """Per-user Alpaca OAuth token wrapper passed through from agents."""
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None


async def _get(path: str, token: Optional["UserToken"] = None):
    """GET an Alpaca endpoint. Returns parsed JSON, or None on any failure.
    When `token` is set, the user's OAuth bearer is used; otherwise the
    env-driven API key falls back."""
    if token is None and not alpaca_configured():
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_base_url() + path, headers=_headers_for(token))
            resp.raise_for_status()
            return resp.json()
    except Exception:  # noqa: BLE001
        return None


async def _post(path: str, body: dict,
                  token: Optional["UserToken"] = None) -> tuple[Optional[dict], Optional[str]]:
    """POST to an Alpaca endpoint. Returns (json, None) on success or
    (None, error_message) on failure — never raises."""
    if token is None and not alpaca_configured():
        return None, "Alpaca is not configured"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _base_url() + path,
                headers={**_headers_for(token), "Content-Type": "application/json"},
                json=body,
            )
            if resp.status_code >= 400:
                msg = resp.text
                try:
                    msg = resp.json().get("message", msg)
                except Exception:  # noqa: BLE001
                    pass
                return None, f"HTTP {resp.status_code}: {msg}"
            return resp.json(), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


async def _delete(path: str,
                    token: Optional["UserToken"] = None) -> tuple[Optional[dict], Optional[str]]:
    """DELETE an Alpaca endpoint. Returns (json, None) on success or
    (None, error_message) on failure - never raises."""
    if token is None and not alpaca_configured():
        return None, "Alpaca is not configured"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.delete(_base_url() + path, headers=_headers_for(token))
            if resp.status_code >= 400:
                return None, f"HTTP {resp.status_code}: {resp.text}"
            try:
                return resp.json(), None
            except Exception:  # noqa: BLE001
                return {}, None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


async def get_account(token: Optional["UserToken"] = None) -> Optional[AlpacaAccount]:
    """Fetch the Alpaca paper account snapshot — equity, buying power,
    day-trade status. None if Alpaca is unconfigured or unreachable."""
    data = await _get("/v2/account", token=token)
    if not isinstance(data, dict):
        return None

    def _f(key: str) -> float:
        try:
            return float(data.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    return AlpacaAccount(
        equity=_f("equity"),
        last_equity=_f("last_equity"),
        cash=_f("cash"),
        buying_power=_f("buying_power"),
        currency=str(data.get("currency") or "USD"),
        status=str(data.get("status") or "UNKNOWN"),
        pattern_day_trader=bool(data.get("pattern_day_trader")),
        daytrade_count=int(data.get("daytrade_count") or 0),
        trading_blocked=bool(data.get("trading_blocked")),
        options_approved_level=int(data.get("options_approved_level") or 0),
        options_trading_level=int(data.get("options_trading_level") or 0),
    )


async def get_positions(token: Optional["UserToken"] = None) -> list[dict]:
    """Open positions on the Alpaca account ([] if none / unconfigured).
    Optional `token` routes the call through the user's OAuth bearer."""
    data = await _get("/v2/positions", token=token)
    return data if isinstance(data, list) else []


async def get_option_positions(token: Optional["UserToken"] = None) -> list[dict]:
    """Just the open OPTION positions on the Alpaca account. Returns the
    raw position dicts (symbol field is the OCC code). Used by the Wheel
    reconciler to settle stale modeled rows when the broker shows nothing
    matching anymore."""
    rows = await get_positions(token=token)
    out: list[dict] = []
    for r in rows:
        ac = str(r.get("asset_class") or "").lower()
        sym = str(r.get("symbol") or "")
        # us_option = Alpaca's marker; the OCC format also disambiguates
        # (>= 15 chars, contains a 6-digit YYMMDD chunk) as a backup.
        is_opt = ac == "us_option" or (len(sym) >= 15 and any(c.isdigit() for c in sym))
        if is_opt:
            out.append(r)
    return out


async def get_clock(token: Optional["UserToken"] = None) -> Optional[dict]:
    """Market clock — {is_open, next_open, next_close}. None on failure."""
    data = await _get("/v2/clock", token=token)
    return data if isinstance(data, dict) else None


async def get_order(order_id: str) -> Optional[dict]:
    """Fetch a single order by id. None if not found / unconfigured."""
    data = await _get(f"/v2/orders/{order_id}")
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Phase F (2026-06-04) - Alpaca crypto support, additive + removable.
# ---------------------------------------------------------------------------

# Alpaca paper crypto allowlist. Edit to add/remove the symbols you want
# to route through Alpaca. Symbols NOT in this set fall through to the
# internal modeled paper engine even when the feature flag is ON.
ALPACA_CRYPTO_SYMBOLS = frozenset({
    "BTC", "ETH", "SOL", "AVAX", "LINK", "LTC", "BCH",
    "MATIC", "USDT", "USDC", "AAVE", "UNI", "DOGE", "SHIB",
    "DOT", "XRP", "ADA",
})


def alpaca_crypto_supports(symbol: str) -> bool:
    """True when the symbol is in the Alpaca crypto allowlist."""
    return (symbol or "").upper().strip() in ALPACA_CRYPTO_SYMBOLS


def _crypto_pair(symbol: str) -> str:
    """Convert a bare ticker like 'BTC' to Alpaca's crypto pair format
    'BTC/USD'. Already-paired inputs pass through."""
    s = (symbol or "").upper().strip()
    if "/" in s:
        return s
    return f"{s}/USD"


async def submit_crypto_order(
    symbol: str,
    side: str,
    qty: float,
    token: Optional["UserToken"] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Place a crypto MARKET order at Alpaca paper. Returns (order, error).

    Alpaca crypto does NOT support bracket orders (no native stop/target
    legs), so the stop and target prices are tracked client-side by the
    Position Monitor agent - same shape it already uses for stocks that
    fall back to internal mark-to-market.

    Time-in-force is GTC because crypto trades 24/7; the equity-only
    'day' value is rejected by the crypto endpoint.

    Phase F follow-up: add limit orders (with 'type': 'limit' + 'limit_price')
    once Mike wants to opt into price-protected entries.
    """
    pair = _crypto_pair(symbol)
    body = {
        "symbol": pair,
        "side": side.lower(),
        "type": "market",
        "time_in_force": "gtc",
        "qty": str(qty),
    }
    try:
        order = await _post("/v2/orders", body, token=token)
        if isinstance(order, dict) and order.get("id"):
            return order, None
        return None, f"unexpected_response: {str(order)[:200]}"
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:200]


async def submit_bracket_order(
    symbol: str,
    qty: float,
    side: str,
    take_profit_price: float,
    stop_loss_price: float,
    time_in_force: str = "day",
    token: Optional["UserToken"] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Submit a bracket order (entry + take-profit + stop-loss) to Alpaca
    paper. `side` is 'buy' (long) or 'sell' (short). The bracket means
    Alpaca manages the stop and target server-side once the entry fills.
    Returns (order, None) on success or (None, error_message)."""
    try:
        shares = int(qty)
    except (TypeError, ValueError):
        return None, "Invalid quantity"
    if shares < 1:
        return None, "Quantity rounds to zero shares"
    if side not in ("buy", "sell"):
        return None, f"Invalid order side: {side}"

    body = {
        "symbol": symbol.upper(),
        "qty": str(shares),
        "side": side,
        "type": "market",
        "time_in_force": time_in_force,
        "order_class": "bracket",
        "take_profit": {"limit_price": round(float(take_profit_price), 2)},
        "stop_loss": {"stop_price": round(float(stop_loss_price), 2)},
    }
    return await _post("/v2/orders", body, token=token)


async def submit_option_order(
    occ_symbol: str,
    contracts: int,
    side: str,
    time_in_force: str = "day",
    limit_price: Optional[float] = None,
    token: Optional["UserToken"] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Submit a single-leg options order to Alpaca.

    side = "sell" for sell-to-open (CSP / CC) or sell-to-close.
    side = "buy"  for buy-to-open (long calls / puts) or buy-to-close.

    Type is "limit" when limit_price is given (the safer default for
    options), otherwise "market". Per-user OAuth token threads through
    via the same token argument the other helpers accept."""
    try:
        qty = int(contracts)
    except (TypeError, ValueError):
        return None, "Invalid contracts count"
    if qty < 1:
        return None, "Contracts rounds to zero"
    if side not in ("buy", "sell"):
        return None, f"Invalid options order side: {side}"

    body: dict = {
        "symbol": occ_symbol.upper(),
        "qty": str(qty),
        "side": side,
        "type": "limit" if (limit_price is not None and limit_price > 0) else "market",
        "time_in_force": time_in_force,
    }
    if limit_price is not None and limit_price > 0:
        body["limit_price"] = str(round(float(limit_price), 2))
    return await _post("/v2/orders", body, token=token)


async def get_open_symbols() -> Optional[set]:
    """The set of symbols with an open Alpaca position. Returns None if the
    call failed - so callers can tell 'no positions' from 'could not check'."""
    data = await _get("/v2/positions")
    if not isinstance(data, list):
        return None
    return {str(p.get("symbol", "")).upper() for p in data if p.get("symbol")}


async def liquidate_position(symbol: str) -> tuple[Optional[dict], Optional[str]]:
    """Close an open Alpaca position at market (DELETE /v2/positions/{sym}).
    Used by the Position Monitor's swing time stop (Phase 10c). Best-effort:
    returns (json, None) on success or (None, error_message)."""
    return await _delete(f"/v2/positions/{symbol.upper()}")
