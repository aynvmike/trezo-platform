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

import os
import re

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
    # USD actually spendable on CRYPTO (non-marginable). Options
    # collateral pledges drain this to 0 while margin BP can still
    # read positive -- crypto orders 403 unless THIS bucket has money.
    # (2026-07-24 HOTFIX: this field MUST live in the defaulted tail --
    # placing it above 'cash' broke the dataclass at import and took
    # down every alpaca-touching path for a morning.)
    non_marginable_buying_power: float = 0.0
    # Account identity (2026-06-16): lets the bot prove WHICH Alpaca
    # account it is bound to and never silently trade the wrong one.
    account_number: str = ""
    account_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _account_ctx():
    """The broker account this task is bound to, or None.

    Returns None -- meaning "behave exactly as before" -- in two cases:

    * LIVE MODE. The account registry holds PAPER credentials only, so it
      must never be allowed to redirect a live call. Live keeps its
      existing single-account path until live multi-account is a
      deliberate, separately-reviewed decision.
    * SINGLE ACCOUNT. When only the primary account is enabled there is
      nothing to route, so every call takes the original code path and
      this whole mechanism is inert.

    Set by app.brokers.accounts.use_account(), which is a ContextVar --
    so concurrent per-account cycles cannot leak into each other's calls.
    """
    if _live_active():
        return None
    try:
        from app.brokers.accounts import current_account, multi_account_active
        if not multi_account_active():
            return None
        return current_account()
    except Exception:  # noqa: BLE001
        return None


def alpaca_configured() -> bool:
    """True when both Alpaca API keys are present for the active account."""
    a = _account_ctx()
    if a is not None:
        return bool(a.key_id and a.secret)
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
    a = _account_ctx()
    if a is not None:
        return a.base_url
    return get_settings().alpaca_base_url or PAPER_BASE_URL


def _headers() -> dict:
    s = get_settings()
    if _live_active():
        return {
            "APCA-API-KEY-ID": s.alpaca_live_api_key,
            "APCA-API-SECRET-KEY": s.alpaca_live_secret_key,
        }
    a = _account_ctx()
    if a is not None:
        return a.headers()
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


async def _patch(path: str, body: dict,
                 token: Optional["UserToken"] = None) -> tuple[Optional[dict], Optional[str]]:
    """PATCH an Alpaca endpoint -- used to AMEND a resting order in place
    rather than cancelling and re-placing it.

    WHY THIS EXISTS (2026-08-18): nothing in this codebase had ever
    modified a live order. Moving a stop meant cancel-then-place, which
    opens a window where the position has no protection at all -- and
    that window is exactly how the profit step kept leaving remainders
    naked when the second leg failed. Amending is atomic at the venue:
    the order either moves or it doesn't, and the old one stays in force
    until it does."""
    if token is None and not alpaca_configured():
        return None, "Alpaca is not configured"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.patch(_base_url() + path, json=body,
                                      headers={**_headers_for(token),
                                               "Content-Type": "application/json"})
            if resp.status_code >= 400:
                return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
            try:
                return resp.json(), None
            except Exception:  # noqa: BLE001
                return {}, None
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:200]


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
        non_marginable_buying_power=_f("non_marginable_buying_power"),
        cash=_f("cash"),
        buying_power=_f("buying_power"),
        currency=str(data.get("currency") or "USD"),
        status=str(data.get("status") or "UNKNOWN"),
        pattern_day_trader=bool(data.get("pattern_day_trader")),
        daytrade_count=int(data.get("daytrade_count") or 0),
        trading_blocked=bool(data.get("trading_blocked")),
        options_approved_level=int(data.get("options_approved_level") or 0),
        options_trading_level=int(data.get("options_trading_level") or 0),
        account_number=str(data.get("account_number") or ""),
        account_id=str(data.get("id") or ""),
    )


async def account_self_check() -> dict:
    """Account-identity guard (2026-06-16). Confirms the bot is bound to a
    real, tradable Alpaca account and surfaces WHICH one (account number +
    buying power + options approval). If settings.alpaca_expected_account is
    set and the live account differs, flags a mismatch so the bot never
    silently trades the wrong account. Uses the env keys (the single-tenant
    source of truth). Read-only; never raises."""
    s = get_settings()
    out = {
        "ok": False, "configured": alpaca_configured(), "venue": broker_venue(),
        "account_number": "", "buying_power": 0.0, "status": "",
        "options_approved_level": 0, "trading_blocked": True,
        "expected": (s.alpaca_expected_account or ""), "mismatch": False,
        "note": "",
    }
    try:
        if not alpaca_configured():
            out["note"] = "Alpaca env keys not configured."
            return out
        acct = await get_account()
        if acct is None:
            out["note"] = "Alpaca account unreachable (keys invalid or API down)."
            return out
        out.update({
            "ok": True,
            "account_number": acct.account_number,
            "buying_power": acct.buying_power,
            "status": acct.status,
            "options_approved_level": acct.options_approved_level,
            "trading_blocked": acct.trading_blocked,
        })
        exp = (s.alpaca_expected_account or "").strip()
        if exp and acct.account_number and exp != acct.account_number:
            out["mismatch"] = True
            out["note"] = (
                f"ACCOUNT MISMATCH: bound to {acct.account_number} but expected "
                f"{exp}. Check ALPACA_API_KEY / ALPACA_SECRET_KEY in agents/.env."
            )
        elif acct.trading_blocked:
            out["note"] = "Account trading_blocked=true at Alpaca."
        elif acct.options_approved_level < 1:
            out["note"] = (
                "Options approval level 0 - the Wheel cannot sell CSPs/CCs "
                "until options trading is enabled on this Alpaca account."
            )
        else:
            out["note"] = "Account healthy."
    except Exception as e:  # noqa: BLE001
        out["note"] = f"Self-check error: {e}"
    return out


_CRYPTO_ASSETS: dict = {"ts": 0.0, "syms": frozenset()}


def tradable_crypto_symbols() -> frozenset:
    """Base symbols Alpaca can trade against USD (cached 6h, sync).

    Broker-only mode uses this so Trezo never opens a crypto position
    the broker cannot hold. Returns an empty set on any failure, and
    callers treat empty as 'unknown -> allow', so a data hiccup can
    never silently empty the universe."""
    import time as _t
    import json as _j
    import urllib.request as _u
    if _CRYPTO_ASSETS["syms"] and (_t.time() - _CRYPTO_ASSETS["ts"]) < 21600:
        return _CRYPTO_ASSETS["syms"]
    try:
        # Deliberately NOT account-scoped: which coins Alpaca lists is a
        # venue fact, identical for every account under one login, and it
        # is cached process-wide for 6h. Any valid key can read it.
        s = get_settings()
        base = (s.alpaca_base_url or PAPER_BASE_URL).rstrip("/")
        req = _u.Request(
            base + "/v2/assets?asset_class=crypto&status=active",
            headers={"APCA-API-KEY-ID": s.alpaca_api_key,
                     "APCA-API-SECRET-KEY": s.alpaca_secret_key})
        data = _j.load(_u.urlopen(req, timeout=20))
        syms = frozenset(
            str(a.get("symbol", "")).split("/")[0].upper()
            for a in data
            if str(a.get("symbol", "")).endswith("/USD") and a.get("tradable"))
        if syms:
            _CRYPTO_ASSETS.update({"ts": _t.time(), "syms": syms})
        return syms
    except Exception:  # noqa: BLE001
        return _CRYPTO_ASSETS["syms"] or frozenset()


async def get_positions_strict(
        token: Optional["UserToken"] = None) -> Optional[list]:
    """Open positions, or None when the read FAILED (timeout, 429, 5xx).

    2026-08-28, the DOT/QYLD/AMZN phantom-close loop: get_positions()
    collapsed every failure into [] -- indistinguishable from a flat
    account -- so one rate-limited read made book_scope cache "holds
    nothing" and Position Monitor closed every broker-held row on the
    book at modeled prices (alpaca_bracket / alpaca_external) while
    Alpaca kept holding them. The reconciler then re-adopted them and
    the loop booked phantom P/L for days. stocks_reconcile (2026-06-15)
    and broker_truth both already learned this lesson; this is the same
    fix at the source: a failed read is an ANSWERLESS read, never an
    empty one. Callers that can act destructively must use this and
    treat None as "do not act"."""
    data = await _get("/v2/positions", token=token)
    return data if isinstance(data, list) else None


async def get_positions(token: Optional["UserToken"] = None) -> list[dict]:
    """Open positions on the Alpaca account ([] if none / unconfigured).
    Optional `token` routes the call through the user's OAuth bearer.
    NOTE: [] here can also mean "the read failed" -- destructive callers
    must use get_positions_strict() and honor its None."""
    data = await get_positions_strict(token=token)
    return data if data is not None else []


async def get_option_positions_strict(
        token: Optional["UserToken"] = None) -> Optional[list]:
    """Open OPTION positions, or None when the read FAILED.

    OG-9 / PM-4 / G2 / G1 (audit 2026-09-01): get_option_positions()
    inherited get_positions()'s [] on failure, so one rate-limited read
    told the Wheel reconciler and the options scanner "the broker holds
    no contracts" and they settled/closed modeled rows the broker was
    still holding -- the option-lane twin of the 2026-08-28 phantom-close
    loop. Same fix, same shape as get_positions_strict: a failed read is
    ANSWERLESS. Anything that can close, settle or re-open a row on this
    answer must call this and take no action on None. Filters exactly as
    get_option_positions does; the raw dicts' symbol is the OCC code."""
    rows = await get_positions_strict(token=token)
    if rows is None:
        return None
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


async def get_option_positions(token: Optional["UserToken"] = None) -> list[dict]:
    """Just the open OPTION positions on the Alpaca account. Returns the
    raw position dicts (symbol field is the OCC code).

    DISPLAY-ONLY. [] here can also mean "the read failed"; destructive
    callers (reconcilers, scanners that settle or close rows) must use
    get_option_positions_strict() and honor its None (OG-9/PM-4)."""
    rows = await get_option_positions_strict(token=token)
    return rows if rows is not None else []


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


async def get_recent_closed_orders(symbol: str,
                                   token: Optional["UserToken"] = None,
                                   limit: int = 8) -> list[dict]:
    """Most recent closed orders for one symbol, newest first. Lets the
    reconciler recover the TRUE exit fill for a position that vanished at
    the broker instead of booking $0 realized (2026-07-02)."""
    try:
        rows = await _get(
            f"/v2/orders?status=closed&symbols={symbol.upper()}"
            f"&limit={int(limit)}&direction=desc",
            token=token,
        )
        return rows if isinstance(rows, list) else []
    except Exception:  # noqa: BLE001
        return []


def alpaca_crypto_supports(symbol: str) -> bool:
    """True when the symbol is in the Alpaca crypto allowlist."""
    return (symbol or "").upper().strip() in ALPACA_CRYPTO_SYMBOLS


def crypto_symbol_variants(symbol: str) -> frozenset:
    """Every spelling Alpaca may use for a crypto ticker, uppercased:
    'BTC' -> {'BTC', 'BTC/USD', 'BTCUSD'}.

    Needed because get_open_symbols() returns crypto in pair format
    ('BTCUSD' or 'BTC/USD') while Trezo paper_positions rows store the
    bare ticker ('BTC'). Membership checks that ignore this mismatch
    phantom-close crypto rows while Alpaca still holds the coins
    (Task #10 audit, 2026-06-11)."""
    s = (symbol or "").upper().strip()
    if "/" in s:
        s = s.split("/", 1)[0]
    elif s.endswith("USD") and len(s) > 4:
        s = s[:-3]
    return frozenset({s, f"{s}/USD", f"{s}USD"})


def _crypto_base(symbol: str) -> str:
    """The bare coin from any spelling Trezo or Alpaca might use:
    'XRP', 'XRPUSD' and 'XRP/USD' all give 'XRP'.

    Fixed 2026-08-18. _crypto_pair() only ever handled the bare form, so
    a row stored as 'XRPUSD' became 'XRPUSD/USD' -- a symbol no venue
    recognises. That silently broke liquidate_position() for any crypto
    row written in pair form, which is the forced-exit path: the stop
    fires, the DELETE 404s, the row stays open and the coin keeps
    falling. Both spellings are in the table because adoption reads the
    broker's naming while our own entries write the bare ticker.
    crypto_symbol_variants() has always normalised this way; this is the
    same rule, applied where it also matters."""
    s = (symbol or "").upper().strip()
    if "/" in s:
        return s.split("/", 1)[0]
    if s.endswith("USD") and len(s) > 4:
        return s[:-3]
    return s


def _crypto_pair(symbol: str) -> str:
    """Any spelling of a coin -> Alpaca's pair format ('BTC/USD')."""
    return f"{_crypto_base(symbol)}/USD"


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
        resp, perr = await _post("/v2/orders", body, token=token)
        if perr:
            return None, perr
        if isinstance(resp, dict) and resp.get("id"):
            return resp, None
        # 2026-07-13: _post returns (json, error) -- the old code compared
        # the whole TUPLE to a dict, so every ACCEPTED crypto order was
        # mislabelled a broker reject. The engine then retried (stacking
        # real fills at Alpaca with no book row) and the false rejects
        # tripped the session kill-switch. Found via the 3x ETH orphan.
        return None, f"unexpected_response: {str(resp)[:200]}"
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:200]


async def submit_mleg_order(
    legs: list[dict],
    qty: int = 1,
    limit_price: Optional[float] = None,
    time_in_force: str = "day",
    token: Optional["UserToken"] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Submit a MULTI-LEG options order (spread / condor / butterfly) as
    ONE ticket (Mike 2026-07-14: trade the whole Level-3 menu). Each leg:
    {"symbol": OCC, "ratio_qty": int, "side": "buy"|"sell",
     "position_intent": "buy_to_open"|"sell_to_open"|"buy_to_close"|
     "sell_to_close"}. limit_price is the NET price per spread:
    positive = debit paid, negative = credit received (Alpaca mleg
    convention)."""
    if not legs or len(legs) < 2:
        return None, "mleg needs at least 2 legs"
    body: dict = {
        "order_class": "mleg",
        "qty": str(int(qty)),
        "type": "limit" if limit_price is not None else "market",
        "time_in_force": time_in_force,
        "legs": [{
            "symbol": str(l["symbol"]).upper(),
            "ratio_qty": str(int(l.get("ratio_qty", 1))),
            "side": str(l["side"]).lower(),
            "position_intent": str(l["position_intent"]).lower(),
        } for l in legs],
    }
    if limit_price is not None:
        body["limit_price"] = str(round(float(limit_price), 2))
    resp, perr = await _post("/v2/orders", body, token=token)
    if perr:
        return None, perr
    if isinstance(resp, dict) and resp.get("id"):
        return resp, None
    return None, f"unexpected_response: {str(resp)[:200]}"


async def submit_bracket_order(
    symbol: str,
    qty: float,
    side: str,
    take_profit_price: float,
    stop_loss_price: float,
    time_in_force: Optional[str] = None,
    token: Optional["UserToken"] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Submit a bracket order (entry + take-profit + stop-loss) to Alpaca
    paper. `side` is 'buy' (long) or 'sell' (short). The bracket means
    Alpaca manages the stop and target server-side once the entry fills.
    Returns (order, None) on success or (None, error_message).

    TIME IN FORCE IS NOW GTC (2026-08-18). It defaulted to `day`, which
    meant the exit legs DIED AT EVERY CLOSE: a position held overnight
    had no stop and no target at the broker until something re-armed it.
    That is the naked-position alert from 2026-06-11, and it is also why
    a server outage leaves stock positions unprotected -- the protection
    was never really at the broker, it just looked like it was until
    16:00.

    The whole point of a bracket is that the venue holds the exits when
    we cannot. `day` gave that up every evening for free.

    Override per call, or globally with TREZO_BRACKET_TIF=day to revert.
    If Alpaca ever rejects gtc on a bracket we retry once as `day`, since
    a protected position on a worse TIF beats no order at all -- and a
    422 here would otherwise count as a broker reject and creep toward
    the kill-switch (the 2026-07-27 XLE lesson)."""
    try:
        shares = int(qty)
    except (TypeError, ValueError):
        return None, "Invalid quantity"
    if shares < 1:
        return None, "Quantity rounds to zero shares"
    if side not in ("buy", "sell"):
        return None, f"Invalid order side: {side}"

    # Orientation guard (Mike 2026-07-27, the XLE 422 storm): Alpaca
    # requires take_profit ABOVE stop_loss for longs and BELOW for
    # shorts. An inverted pair used to travel all the way to the broker,
    # come back 422, and count as a BROKER REJECT -- three of those
    # tripped the kill-switch and silenced every lane, crypto included.
    # Catch it locally: the caller sees a clear error, the broker never
    # sees a bad order, and no reject is charged against the halt.
    _tp = round(float(take_profit_price), 2)
    _sl = round(float(stop_loss_price), 2)
    if side == "buy" and _tp <= _sl:
        return None, (f"Bracket rejected locally: long take-profit ${_tp} "
                      f"must sit ABOVE stop ${_sl} (levels inverted)")
    if side == "sell" and _tp >= _sl:
        return None, (f"Bracket rejected locally: short take-profit ${_tp} "
                      f"must sit BELOW stop ${_sl} (levels inverted)")

    tif = (time_in_force or os.getenv("TREZO_BRACKET_TIF", "gtc")).strip().lower()
    body = {
        "symbol": symbol.upper(),
        "qty": str(shares),
        "side": side,
        "type": "market",
        "time_in_force": tif,
        "order_class": "bracket",
        "take_profit": {"limit_price": _tp},
        "stop_loss": {"stop_price": _sl},
    }
    resp, err = await _post("/v2/orders", body, token=token)
    if err and tif == "gtc" and "time_in_force" in str(err).lower():
        # The venue refused GTC on this bracket. Fall back rather than
        # abandon the trade: an exit pair that expires at the close is
        # far better than an entry with no protection at all.
        body["time_in_force"] = "day"
        resp2, err2 = await _post("/v2/orders", body, token=token)
        if not err2:
            try:
                from app.agents.activity_log import record
                record("bracket_tif_fallback", symbol.upper(),
                       reason=("Alpaca refused GTC on this bracket; placed "
                               "with day TIF instead. The exit legs will "
                               "expire at the close -- the naked-position "
                               "check covers it until re-armed."))
            except Exception:  # noqa: BLE001
                pass
            return resp2, None
    return resp, err


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


async def get_all_open_orders() -> Optional[list]:
    """Every open order, unfiltered (list, possibly empty) or None when
    the call failed. Crypto callers match client-side by base instead of
    trusting a venue-side symbol filter -- see open_crypto_orders."""
    data = await _get("/v2/orders?status=open&limit=500")
    return data if isinstance(data, list) else None


async def get_open_orders_for(symbol: str) -> Optional[list]:
    """Open orders for one symbol (list, possibly empty) or None when the
    call failed. Added 2026-06-11 PM for the naked-position alert: a
    day-TIF bracket's exit legs DIE at the close, so a stock row held
    overnight at Alpaca can sit with no stop and no target (found live
    with AAPL). Callers must treat None as 'could not check'.

    2026-09-01 (audit follow-up, the XLE/BAC re-arm churn): an OCO's stop
    leg is a CHILD order that Alpaca only returns when the listing is
    asked for `nested=true`, and even then it sits under the parent's
    `legs`, not as a top-level row. Read without it, ensure_broker_stop
    saw only the resting sell limit, judged it "a lone resting target",
    cancelled the pair and re-armed it -- every ten minutes, all session,
    leaving the position momentarily unprotected each time. So: ask for
    the nested listing and FLATTEN every child leg into the returned list
    so callers that scan for a resting stop actually see it. Legs carry
    the same order shape (id/type/side/status/qty/prices)."""
    data = await _get(f"/v2/orders?status=open&nested=true&symbols={symbol.upper()}")
    if not isinstance(data, list):
        return None
    return _flatten_order_legs(data)


# Child-leg statuses that mean "this leg is no longer working". A parent
# can still be open while one of its legs has already been replaced
# (ratchet_stop PATCHes the stop leg and Alpaca issues a NEW leg id) or
# cancelled. Such a leg must not be read as resting protection, and it
# must never be the leg ratchet_stop tries to amend.
_DEAD_LEG_STATUSES = frozenset({
    "canceled", "cancelled", "expired", "filled", "rejected", "replaced",
})


def _flatten_order_legs(orders: list) -> list:
    """Top-level orders followed by every nested child leg, recursively.
    A leg's own `legs` (if any) are flattened too; a leg is never
    dropped because its status is `held` -- that IS the resting stop.

    Review 2026-09-01 (R-NESTED-1/2): two guards so the flattened list
    can never be misread by the callers that count or amend legs.
    (1) De-duplicate by order id -- if the venue ever lists a leg both
    at top level and under its parent's `legs`, ratchet_stop would
    otherwise amend one id and ensure_stock_protection would cancel the
    same id twice. (2) Skip child legs in a terminal status (see
    _DEAD_LEG_STATUSES): a `replaced` stop leg under a still-open OCO
    parent is not protection, and picking it as stop_legs[0] would make
    every ratchet 'amend failed' while the live leg sat untouched.
    Top-level rows are not status-filtered -- the venue's status=open
    filter already did that -- and legs with no status are kept."""
    out: list = []
    seen: set = set()

    def _walk(items: list, is_leg: bool) -> None:
        for o in items:
            if not isinstance(o, dict):
                continue
            if is_leg and (str(o.get("status") or "").lower()
                           in _DEAD_LEG_STATUSES):
                continue
            oid = o.get("id")
            if oid:
                if oid in seen:
                    continue
                seen.add(oid)
            out.append(o)
            legs = o.get("legs")
            if isinstance(legs, list) and legs:
                _walk(legs, True)

    _walk(orders, False)
    return out


async def replace_order(order_id: str, *, qty: Optional[float] = None,
                        limit_price: Optional[float] = None,
                        stop_price: Optional[float] = None,
                        time_in_force: Optional[str] = None
                        ) -> tuple[Optional[dict], Optional[str]]:
    """Amend a resting order in place. Only the fields you pass change.

    Alpaca returns a NEW order id for the replacement; the old one is
    cancelled by the venue as part of the same operation, so there is no
    unprotected gap."""
    body: dict = {}
    if qty is not None:
        body["qty"] = str(int(qty)) if float(qty).is_integer() else str(qty)
    if limit_price is not None:
        body["limit_price"] = str(round(float(limit_price), 2))
    if stop_price is not None:
        body["stop_price"] = str(round(float(stop_price), 2))
    if time_in_force is not None:
        body["time_in_force"] = time_in_force
    if not body:
        return None, "replace_order called with nothing to change"
    return await _patch(f"/v2/orders/{order_id}", body)


def _is_stop_leg(order: dict) -> bool:
    t = str(order.get("type") or order.get("order_type") or "").lower()
    return "stop" in t and str(order.get("side") or "").lower() == "sell"


async def ratchet_stop(symbol: str, new_stop: float, *,
                       qty: Optional[float] = None,
                       target_price: Optional[float] = None
                       ) -> tuple[bool, str]:
    """Move the resting stop for `symbol` UP to `new_stop`, or place one
    if none exists. Returns (changed, note). Never raises.

    This is the piece that makes a trailing stop real. Until now the
    ladder ratcheted a number in OUR ledger and enforced it by watching
    the tape -- which works only while the engine is alive. On 2026-08-17
    the engine was not alive for fifteen hours. A stop that lives at the
    venue keeps working while we are down, restarting, or locked out.

    RATCHET ONLY: it will never move a long's stop DOWN. A bug that
    loosens protection is far worse than one that fails to tighten it."""
    sym = symbol.upper().strip()
    orders = await get_open_orders_for(sym)
    if orders is None:
        return False, "could not read open orders - left untouched"

    stop_legs = [o for o in orders if _is_stop_leg(o)]
    if stop_legs:
        leg = stop_legs[0]
        try:
            current = float(leg.get("stop_price") or 0)
        except (TypeError, ValueError):
            current = 0.0
        if current and new_stop <= current + 0.004:
            return False, f"broker stop already at {current:g}"
        _res, err = await replace_order(str(leg.get("id")), stop_price=new_stop)
        if err:
            return False, f"amend failed: {err}"
        return True, f"broker stop {current:g} -> {new_stop:g}"

    # No stop at the venue at all. This is the naked case -- place
    # protection rather than reporting it and moving on.
    if target_price and qty:
        _o, err = await submit_oco_sell(sym, qty, target_price, new_stop)
        if not err:
            return True, f"no broker stop existed - placed OCO at {new_stop:g}"
    if qty:
        _o, err = await submit_stop_sell(sym, qty, new_stop)
        if not err:
            return True, f"no broker stop existed - placed stop at {new_stop:g}"
        return False, f"could not place protection: {err}"
    return False, "no stop leg and no quantity to protect"


async def _clamp_to_venue_qty(symbol: str, qty):
    """Never ask the venue to sell more than it says it holds.

    2026-09-02 (QYLD): the ledger stored 103.72347444 (8 dp, rounded UP
    from the venue's 103.723474436), and the protective OCO 403'd with
    "insufficient qty available" -- the QP-01 funnel on the STOCK side,
    the same disease the crypto ratchet already guards against. Read the
    position and, when the ledger asks for more than the venue holds,
    submit the venue's OWN quantity string verbatim (no float re-round).
    A failed read leaves qty untouched (the order then surfaces its own
    error, honestly)."""
    try:
        bp = await _get(f"/v2/positions/{str(symbol).upper()}")
        if isinstance(bp, dict) and bp.get("qty") is not None:
            vq_s = str(bp.get("qty")).lstrip("-")
            vq = float(vq_s)
            if vq > 0 and float(qty) > vq:
                return vq_s
    except Exception:  # noqa: BLE001
        pass
    return qty


async def ensure_stock_protection(
    symbol: str, qty: float, stop: float, target: Optional[float] = None,
) -> tuple[bool, str]:
    """Make sure an equity position actually has a STOP at the venue.

    Mike, 2026-08-18, looking at the 25k book: "I see GDX but in a sell
    order for 94, why not put in a stop loss and a take profit". He was
    right, and the existing naked-position check could not see it. That
    check fires only when a symbol has ZERO open orders -- the day-TIF
    case, where both bracket legs died at the close. GDX had ONE order,
    a resting sell limit, so it read as protected. It was not: a lone
    target is upside with no floor under it.

    So the test here is not "are there orders" but "is one of them a
    stop". If a target rests alone we cancel it and place a proper OCO,
    because the shares it reserves are the same shares the stop needs.
    Losing a target for a few seconds risks nothing; going a day without
    a stop is how a book bleeds.

    Falls back to a plain stop when the OCO is refused -- protection
    first, the 2026-07-15 PYPL lesson. Returns (changed, note); never
    raises."""
    sym = symbol.upper().strip()
    if not (qty and qty > 0 and stop and stop > 0):
        return False, "no quantity or stop to protect"

    orders = await get_open_orders_for(sym)
    if orders is None:
        return False, "could not read open orders - left untouched"
    if any(_is_stop_leg(o) for o in orders):
        return False, "stop already resting at the broker"

    resting_sells = [o for o in orders if _is_sell_limit(o)]
    for o in resting_sells:
        if o.get("id"):
            await _delete(f"/v2/orders/{o.get('id')}")
    lost_target = bool(resting_sells)

    # QP-01 (stock side): clamp to what the venue actually holds.
    qty = await _clamp_to_venue_qty(sym, qty)

    if target and target > 0:
        _o, err = await submit_oco_sell(sym, qty, target, stop)
        if not err:
            return True, (f"no broker stop existed - placed OCO "
                          f"{stop:g}/{target:g}"
                          + (" (replaced a lone resting target)"
                             if lost_target else ""))
    _o2, err2 = await submit_stop_sell(sym, qty, stop)
    if not err2:
        return True, (f"no broker stop existed - placed stop at {stop:g}"
                      + (" (target NOT restored - OCO refused)"
                         if lost_target else ""))

    # Both attempts failed -- most likely the ledger quantity is larger
    # than what the broker actually holds, so every sell is rejected for
    # insufficient shares. We have already cancelled the target by this
    # point, and walking away here would leave the position with NOTHING
    # resting: strictly worse than the lone target we set out to improve
    # on. Put it back and report, rather than "improving" a position into
    # having no orders at all.
    restored = ""
    for o in resting_sells:
        try:
            _q = float(o.get("qty") or 0)
            _px = float(o.get("limit_price") or 0)
        except (TypeError, ValueError):
            continue
        if _q > 0 and _px > 0:
            _r, _rerr = await _post("/v2/orders", {
                "symbol": sym, "qty": str(_q), "side": "sell",
                "type": "limit", "limit_price": str(round(_px, 2)),
                "time_in_force": "gtc",
            })
            restored = (" - original target restored" if not _rerr
                        else f" - AND THE TARGET IS GONE: {_rerr}")
    return False, f"could not place protection: {err2}{restored}"


# --------------------------------------------------------------------------
# Crypto take-profit: the half of the exit Alpaca WILL hold for us.
# --------------------------------------------------------------------------
# Alpaca gives crypto no bracket and no stop order, so for two months a
# coin's target and stop both lived only in the ledger, enforced by the
# monitor watching the tape. On 2026-08-17 the monitor stopped watching
# for fifteen hours and every crypto row rode it out unprotected.
#
# The stop half cannot be fixed here -- the venue has no crypto stop, and
# no amount of code invents one. The TARGET half can: a resting GTC limit
# sell is a plain order type crypto supports, and it keeps working while
# we are down, restarting, or locked out. It is half a seatbelt, and half
# is what is on offer.
#
# The cost: a resting sell RESERVES the units. Every other sell path must
# cancel it first (see AssetPolicy.resting_exits).


async def open_crypto_orders(symbol: str) -> Optional[list]:
    """Open orders for a coin, addressed the way the venue addresses it.

    get_open_orders_for() passes the symbol through untouched, which is
    right for equities and wrong for crypto: a row stored as 'XRP' would
    query symbols=XRP and come back EMPTY while an order rests under
    XRPUSD. An empty answer that means 'wrong question' is worse than an
    error, because callers read it as 'nothing is resting' and sell.

    2026-08-20, Mike's stale-stop report: the first version of this
    function knew all of that and then asked the wrong question anyway --
    it queried symbols=XRPUSD while the venue files the order under
    XRP/USD. The filter matched nothing, every caller read "nothing
    resting", tried to PLACE a fresh stop, and the invisible old order
    rejected it with 403 insufficient balance -- every tick, all morning,
    while the venue stop fossilized at its first level (1.04 on an XRP
    whose ledger lock had climbed to 1.147). Mike found it by eye on the
    Alpaca dashboard before any of our checks did.

    So: no symbol filter at all. Fetch every open order and match
    client-side by normalized BASE (XRP == XRP/USD == XRPUSD). A slash
    convention can change under us again; base-matching cannot be blinded
    by it. None still means "could not check"; callers must not treat it
    as empty."""
    data = await get_all_open_orders()
    if data is None:
        return None
    want = _crypto_base(symbol)
    return [o for o in data
            if _crypto_base(str(o.get("symbol") or "")) == want]


def _is_sell_limit(order: dict) -> bool:
    t = str(order.get("type") or order.get("order_type") or "").lower()
    return t == "limit" and str(order.get("side") or "").lower() == "sell"


async def ensure_crypto_take_profit(
    symbol: str, qty: float, target: float,
) -> tuple[bool, str]:
    """Keep exactly one resting GTC limit sell at `target` for `symbol`.

    Places one when none rests, moves the existing one when the target
    has changed, and does nothing when it is already right. Returns
    (changed, note) and never raises.

    Unlike ratchet_stop this is NOT one-directional: a target may legally
    move down (the ladder tightens toward a trailing exit) as well as up.
    Nothing here can lose the position -- the worst case of a wrong
    target is a fill at a price we chose. That is why a cancel-and-place
    fallback is acceptable here and is not acceptable for a stop.
    """
    sym = symbol.upper().strip()
    pair = _crypto_pair(sym)
    if not (qty and qty > 0 and target and target > 0):
        return False, "no quantity or target to rest"

    orders = await open_crypto_orders(sym)
    if orders is None:
        return False, "could not read open orders - left untouched"

    resting = [o for o in orders if _is_sell_limit(o)]
    body = {
        "symbol": pair,
        "qty": str(qty),
        "side": "sell",
        "type": "limit",
        "limit_price": str(round(float(target), 6)),
        "time_in_force": "gtc",
    }

    if resting:
        leg = resting[0]
        try:
            cur_px = float(leg.get("limit_price") or 0)
            cur_qty = float(leg.get("qty") or 0)
        except (TypeError, ValueError):
            cur_px, cur_qty = 0.0, 0.0
        px_same = cur_px and abs(cur_px - target) <= max(1e-6, target * 0.0005)
        qty_same = cur_qty and abs(cur_qty - qty) <= max(1e-8, qty * 0.001)
        if px_same and qty_same:
            return False, f"crypto TP already resting at {cur_px:g}"
        # Amend in place if the venue allows it; a rejected PATCH is not
        # a failure worth aborting on, because unlike a stop, briefly
        # having no target risks nothing.
        _res, err = await replace_order(
            str(leg.get("id")), qty=qty, limit_price=target)
        if not err:
            return True, f"crypto TP {cur_px:g} -> {target:g}"
        for o in resting:
            if o.get("id"):
                await _delete(f"/v2/orders/{o.get('id')}")
        _o2, err2 = await _post("/v2/orders", body)
        if err2:
            return False, f"crypto TP re-place failed after amend {err}: {err2}"
        return True, f"crypto TP re-placed at {target:g} (amend refused: {err})"

    _o, err = await _post("/v2/orders", body)
    if err:
        return False, f"crypto TP place failed: {err}"
    return True, f"crypto TP resting at {target:g}"


def _is_crypto_stop_leg(order: dict) -> bool:
    t = str(order.get("type") or order.get("order_type") or "").lower()
    return t == "stop_limit" and str(order.get("side") or "").lower() == "sell"


async def ratchet_crypto_stop(
    symbol: str, new_stop: float, *, qty: Optional[float] = None,
    offset_profile: Optional[str] = None,
) -> tuple[bool, str]:
    """Move a coin's resting STOP-LIMIT up to `new_stop`, or place one.

    Added 2026-08-18. For two months this codebase asserted that Alpaca
    holds no stop for crypto, so every coin's stop lived only in our
    ledger and died with the engine -- fifteen hours of it on 8/17. The
    assertion was half wrong: no *stop* and no bracket, but a stop_limit
    rests fine on gtc. Mike had one on BTCUSD at 65,000 while the code
    was still calling it impossible.

    RATCHET ONLY, same rule as equities: a long's stop never moves down.
    That is what makes this a trailing stop rather than just protection
    -- as the ladder walks the stop up, the lock-in walks up WITH IT at
    the venue, so a good run is banked even if we are not running.

    The limit rides below the stop by the book's offset (see
    asset_policy.STOP_LIMIT_OFFSETS). Returns (changed, note); never
    raises."""
    from app.runtime.asset_policy import stop_limit_price

    sym = symbol.upper().strip()
    pair = _crypto_pair(sym)
    if not new_stop or new_stop <= 0:
        return False, "no stop to place"

    orders = await open_crypto_orders(sym)
    if orders is None:
        return False, "could not read open orders - left untouched"

    limit_px = stop_limit_price(new_stop, "long", offset_profile)
    legs = [o for o in orders if _is_crypto_stop_leg(o)]

    if legs:
        leg = legs[0]
        try:
            current = float(leg.get("stop_price") or 0)
        except (TypeError, ValueError):
            current = 0.0
        # Never down. A bug that loosens a stop costs the position; one
        # that fails to tighten costs some upside.
        if current and new_stop <= current * 1.0004:
            return False, f"crypto stop already at {current:g}"
        _res, err = await replace_order(
            str(leg.get("id")), stop_price=new_stop, limit_price=limit_px)
        if not err:
            return True, f"crypto stop {current:g} -> {new_stop:g}"
        # Amend refused. Unlike a target, a stop must not simply be
        # dropped -- cancel and re-place, then say so if even that fails,
        # because the position is unprotected until it succeeds.
        for o in legs:
            if o.get("id"):
                await _delete(f"/v2/orders/{o.get('id')}")
        _o2, err2 = await _post("/v2/orders", {
            "symbol": pair, "qty": str(qty or leg.get("qty")), "side": "sell",
            "type": "stop_limit", "stop_price": str(new_stop),
            "limit_price": str(limit_px), "time_in_force": "gtc",
        })
        if err2:
            return False, (f"STOP IS GONE - amend refused ({err}) and "
                           f"re-place failed ({err2})")
        return True, f"crypto stop re-placed at {new_stop:g} (amend refused: {err})"

    if not qty or qty <= 0:
        return False, "no resting stop and no quantity to protect"

    # QTY PRECISION (2026-08-28, the DOT 403 loop): the ledger stores
    # quantity at 8 decimals while Alpaca holds 9 -- the ledger's
    # round-UP asked to sell 3e-9 more DOT than existed and every stop
    # placement 403'd "insufficient balance", leaving $10.9k of coin
    # with no floor for days (and the round-DOWN twin left dust crumbs
    # on the other books). Ask the venue what it actually holds and use
    # ITS quantity string verbatim whenever ours differs by a hair; if
    # ours is outright larger, clamp to the venue's. Total position qty
    # on purpose, not qty_available: units parked under a resting target
    # are freed by the cancel-and-retry below, and a stop clamped to
    # qty_available would silently under-protect.
    # NOTE the spelling: ORDERS take "DOT/USD", the POSITIONS endpoint
    # takes "DOTUSD" (probed 2026-08-29 -- the slashed and %2F forms both
    # 404, and a 404 here silently left the ledger quantity in place,
    # which is how the first version of this fix shipped and changed
    # nothing).
    _qty_s = str(qty)
    _pos_sym = pair.replace("/", "")
    try:
        _bp = await _get(f"/v2/positions/{_pos_sym}")
        _bq_raw = (_bp or {}).get("qty")
        _bq = float(_bq_raw) if _bq_raw is not None else 0.0
        if _bq > 0 and (abs(qty - _bq) / _bq < 1e-3 or qty > _bq):
            _qty_s = str(_bq_raw)
    except Exception:  # noqa: BLE001
        pass

    body = {
        "symbol": pair, "qty": _qty_s, "side": "sell",
        "type": "stop_limit", "stop_price": str(new_stop),
        "limit_price": str(limit_px), "time_in_force": "gtc",
    }
    _o, err = await _post("/v2/orders", body)
    if err and "insufficient balance" in str(err).lower():
        # Alpaca states the exact holdable amount in the rejection --
        # "requested: 13060.38462492, available: 13060.384624917". Take
        # the venue at its word and retry once. This is the last line of
        # defence behind the position probe above: between them, a
        # rounding hair can no longer leave a coin with no floor.
        _m = re.search(r"available:\s*([0-9.]+)", str(err))
        if _m and _m.group(1) != body["qty"]:
            body["qty"] = _m.group(1)
            _o, err = await _post("/v2/orders", body)
            if not err:
                return True, (f"crypto stop resting at {new_stop:g} (limit "
                              f"{limit_px:g}) - quantity taken from the "
                              f"venue's own balance ({body['qty']})")
    if not err:
        return True, f"crypto stop resting at {new_stop:g} (limit {limit_px:g})"

    # Rejected. The overwhelmingly likely reason is that a resting
    # TAKE-PROFIT limit is holding the coins: crypto has no OCO, so the
    # two orders compete for the same units and whichever is already
    # there wins by default.
    #
    # Found 2026-08-19 before restarting onto this code. The engine had
    # spent the evening on the previous build, which rested crypto
    # take-profits by default. This build stands them down -- but
    # standing down only stops NEW ones; the orders already at the venue
    # sit there holding inventory forever. Every stop would have been
    # rejected, on exactly the rows we were adding stops to protect, and
    # the note would have read like a venue problem.
    #
    # Mike's rule decides it: stop wins. Cancel the target, place the
    # stop, and say in the note that the target went -- losing upside is
    # the price of having a floor, and it should be visible, not silent.
    targets = [o for o in orders if _is_sell_limit(o)]
    if targets:
        for o in targets:
            if o.get("id"):
                await _delete(f"/v2/orders/{o.get('id')}")
        _o2, err2 = await _post("/v2/orders", body)
        if not err2:
            return True, (f"crypto stop resting at {new_stop:g} (limit "
                          f"{limit_px:g}) - cancelled the resting target "
                          f"to free the units")
        err = f"{err2} (after freeing the target; first attempt: {err})"
    # Still blocked (or no target existed to free): something sell-side
    # we did not classify is holding the units -- a hand-placed or
    # hand-edited order, and Mike adjusts stops from the dashboard,
    # which is allowed. 2026-08-20: the no-target early-return here was
    # exactly how those hand-edited orders became permanent blockers.
    # Stop wins over ALL of it: clear every remaining sell on the coin
    # and try once more.
    others = [o for o in orders
              if str(o.get("side") or "").lower() == "sell"
              and o.get("id")
              and o not in targets]
    if not others:
        return False, f"could not place crypto stop: {err}"
    for o in others:
        await _delete(f"/v2/orders/{o.get('id')}")
    _o3, err3 = await _post("/v2/orders", body)
    if not err3:
        return True, (f"crypto stop resting at {new_stop:g} - cleared "
                      f"{len(others)} other resting sell(s) to free the units")
    return False, (f"could not place crypto stop even after clearing every "
                   f"resting sell: {err3} (first attempt: {err})")


async def cancel_crypto_exits(symbol: str) -> tuple[int, Optional[str]]:
    """Release EVERY resting sell on a coin -- stop-limit and target
    alike -- so another sell can use the units.

    Alpaca gives crypto no OCO, so protection and target are two
    independent orders and each reserves inventory separately. Anything
    about to sell must clear both; clearing only one leaves the other
    holding the coins and the sell gets an insufficient-balance reject.
    Error ONLY when the LISTING failed, so a caller can tell "nothing
    was resting" from "I could not find out"."""
    orders = await open_crypto_orders(symbol)
    if orders is None:
        return 0, "could not list open crypto orders"
    n = 0
    for o in orders:
        if (_is_sell_limit(o) or _is_crypto_stop_leg(o)) and o.get("id"):
            await _delete(f"/v2/orders/{o.get('id')}")
            n += 1
    return n, None


async def cancel_crypto_take_profit(symbol: str) -> tuple[int, Optional[str]]:
    """Release the units a resting TP is holding. Returns (cancelled,
    error) -- error ONLY when the listing failed, because a caller that
    is about to sell must be able to tell 'nothing was resting' apart
    from 'I could not find out'."""
    orders = await open_crypto_orders(symbol)
    if orders is None:
        return 0, "could not list open crypto orders"
    n = 0
    for o in orders:
        if _is_sell_limit(o) and o.get("id"):
            await _delete(f"/v2/orders/{o.get('id')}")
            n += 1
    return n, None


async def cancel_open_orders_for(symbol: str) -> tuple[int, Optional[str]]:
    """Cancel every open order on one symbol (the cancel-legs-first
    pattern from the 6/12 GM fix, as a reusable primitive). Returns
    (count_requested, error) -- error only when the LISTING failed."""
    sym = symbol.upper()
    orders = await _get(f"/v2/orders?status=open&symbols={sym}")
    if not isinstance(orders, list):
        return 0, "could not list open orders"
    n = 0
    for o in orders:
        oid = o.get("id")
        if oid:
            await _delete(f"/v2/orders/{oid}")
            n += 1
    return n, None


async def submit_market_sell(
    symbol: str, qty: float,
) -> tuple[Optional[dict], Optional[str]]:
    """Plain market sell (profit-stepping slice, 2026-07-02)."""
    return await _post("/v2/orders", {
        "symbol": symbol.upper(),
        "qty": str(qty),
        "side": "sell",
        "type": "market",
        "time_in_force": "day",
    })


async def submit_market_buy(
    symbol: str, qty: float, *, time_in_force: str = "day",
    token: Optional["UserToken"] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Plain market BUY -- NO bracket legs (NEQ-05 / G3, 2026-09-01).

    The dividend-ladder lane holds through drawdowns by design: its exits
    are the spec's (cut, payout breach, recycling ratio), not a price. A
    bracket would plant a stop and a target the lane never asked for, so
    its entries go in as a bare market buy and position_monitor honours
    the row's no_price_stop. The mirror of submit_market_sell above, with
    the per-user token the stock path resolves. Whole shares only; DAY
    time-in-force (a resting GTC market buy is never wanted). Returns
    (order, None) or (None, error) -- never raises."""
    try:
        shares = int(qty)
    except (TypeError, ValueError):
        return None, "Invalid quantity"
    if shares < 1:
        return None, "Quantity rounds to zero shares"
    return await _post("/v2/orders", {
        "symbol": symbol.upper(),
        "qty": str(shares),
        "side": "buy",
        "type": "market",
        "time_in_force": (time_in_force or "day").strip().lower(),
    }, token=token)


def _equity_sell_tif(qty: float) -> str:
    """GTC for whole shares; DAY when the quantity is fractional.

    2026-08-20, the QYLD 422s: Alpaca refuses GTC on fractional equity
    orders outright -- "fractional orders must be DAY orders" -- so a
    fractional position's protection was being rejected EVERY tick and
    the position sat naked at the venue. DAY protection that dies at the
    close and is re-placed on the next tick after the open beats no
    protection at all; the naked-position check covers the overnight gap
    it creates, and that gap is Alpaca's rule, not our choice."""
    try:
        q = float(qty)
    except (TypeError, ValueError):
        return "gtc"
    return "gtc" if q == int(q) else "day"


async def submit_stop_sell(
    symbol: str, qty: float, stop_price: float,
) -> tuple[Optional[dict], Optional[str]]:
    """Plain stop sell — the protection-first fallback when an OCO is
    refused (2026-07-15, the PYPL naked-4 incident). GTC for whole
    shares, DAY for fractional (see _equity_sell_tif)."""
    return await _post("/v2/orders", {
        "symbol": symbol.upper(),
        "qty": str(qty),
        "side": "sell",
        "type": "stop",
        "stop_price": str(round(float(stop_price), 2)),
        "time_in_force": _equity_sell_tif(qty),
    })


async def submit_oco_sell(
    symbol: str, qty: float, limit_price: float, stop_price: float,
) -> tuple[Optional[dict], Optional[str]]:
    """OCO exit pair for an existing LONG: take-profit limit + stop, one
    cancels the other. Re-protects a remainder after a partial sell
    (2026-07-02). Prices rounded to pennies (Alpaca sub-penny rule).
    GTC for whole shares, DAY for fractional (see _equity_sell_tif)."""
    return await _post("/v2/orders", {
        "symbol": symbol.upper(),
        "qty": str(qty),
        "side": "sell",
        "type": "limit",
        "time_in_force": _equity_sell_tif(qty),
        "order_class": "oco",
        "take_profit": {"limit_price": str(round(float(limit_price), 2))},
        "stop_loss": {"stop_price": str(round(float(stop_price), 2))},
    })


async def liquidate_position(
    symbol: str, asset_type: str = "stock",
) -> tuple[Optional[dict], Optional[str]]:
    """Close an open Alpaca position at market (DELETE /v2/positions/{sym}).
    Used by the Position Monitor's swing time stop (Phase 10c) and the
    crypto client-side exits (Task #10, 2026-06-11). Best-effort:
    returns (json, None) on success or (None, error_message).

    Crypto rows store the bare ticker ('BTC') but Alpaca's positions
    endpoint addresses crypto by pair without the slash ('BTCUSD'), so
    pass asset_type='crypto' to translate; a symbol already spelled as a
    known pair ('BTCUSD', 'BTC/USD') is treated as crypto regardless.
    Bare stock symbols are passed through unchanged."""
    sym = symbol.upper().strip()
    # SY-02: a row can arrive as a pair spelling with asset_type left at
    # the 'stock' default (adoption writes the broker's naming). Route it
    # as crypto anyway, or the cancel below asks the wrong question.
    is_crypto = (
        asset_type == "crypto"
        or "/" in sym
        or (sym.endswith("USD") and len(sym) > 4
            and _crypto_base(sym) in ALPACA_CRYPTO_SYMBOLS)
    )
    if is_crypto:
        sym = _crypto_pair(sym).replace("/", "")
    # Fixed 2026-06-12 evening (the GM incident): DELETE /v2/positions
    # returns 403 "available: 0" when ALL shares are reserved by open
    # orders -- e.g. the position's own bracket sell legs. GM's stms
    # time stop fired 429 times today and every liquidate was rejected,
    # so the position rode all day. Cancel the symbol's open orders
    # FIRST, then liquidate. Cancelling exit legs is always correct
    # here: every caller is a forced exit that replaces them.
    try:
        if is_crypto:
            # SY-02 (audit 2026-09-01): the symbols= filter below is the
            # POSITIONS spelling (DOTUSD) while Alpaca files crypto orders
            # under the slashed pair (DOT/USD). It matched nothing, so the
            # resting stop-limit kept the units reserved and every forced
            # crypto exit 403'd "available: 0" -- the stop fired and the
            # coin rode. Use the base-matched helper (XRP == XRP/USD ==
            # XRPUSD), the same lesson open_crypto_orders learned on 8/20.
            # A failed listing is still best-effort here: the DELETE
            # below surfaces the 403 honestly instead of us guessing.
            await cancel_crypto_exits(sym)
        else:
            orders = await _get(f"/v2/orders?status=open&symbols={sym}")
            if isinstance(orders, list):
                for o in orders:
                    oid = o.get("id")
                    if oid:
                        await _delete(f"/v2/orders/{oid}")
    except Exception:  # noqa: BLE001
        pass  # best effort; the liquidate below surfaces any real error
    return await _delete(f"/v2/positions/{sym}")
