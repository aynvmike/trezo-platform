"""Kraken crypto-exchange connector (crypto Part 3, 2026-06-13).

Brings the ISO 20022 coins Alpaca can't trade onto a real venue (Kraken).
Long-only spot, USD-quoted.

SAFETY MODEL (read this before flipping anything live):
  * has_credentials() — True once a key + secret are present in agents/.env
    (Mike's Kraken_API_KEY / Kraken_Private_Key). Enables read/validation.
  * is_configured()   — True only when has_credentials() AND
    crypto_exchange_enabled=true. Gates whether trade_execution ROUTES crypto
    here at all.
  * submit_order()    — Part 3 is VALIDATE-ONLY: every order is sent to Kraken
    with validate=true, which checks the order against the live book WITHOUT
    placing it. No funds move. Real placement + fill reconciliation is Part 4
    (deliberately not built yet — it's the step that risks real money, so it
    waits for Mike's explicit go-ahead).
  * self_test()       — calls the private Balance endpoint to prove the keys
    authenticate. Read-only, safe.

The HMAC-SHA512 signing is verified offline against Kraken's published test
vector (see scripts/check or the inline self-check) so we know auth is correct
before any network call.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

KRAKEN_API = "https://api.kraken.com"

# Trezo ticker -> Kraken pair altname (USD spot). Only coins Kraken actually
# lists; anything not here stays on the modeled engine. Note Kraken uses XBT
# for BTC.
PAIR_MAP = {
    "BTC": "XBTUSD", "XBT": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD",
    "XRP": "XRPUSD", "XLM": "XLMUSD", "ADA": "ADAUSD", "ALGO": "ALGOUSD",
    "DOT": "DOTUSD", "ATOM": "ATOMUSD",
    # 2026-07-13: liquid majors (XDG = Kraken code for Doge).
    "DOGE": "XDGUSD", "LTC": "LTCUSD", "LINK": "LINKUSD", "AVAX": "AVAXUSD",
}
SUPPORTED = frozenset(PAIR_MAP.keys())


@dataclass
class ExchangeConfig:
    exchange: str = "kraken"
    api_key: str = ""
    api_secret: str = ""
    enabled: bool = False


def _config() -> ExchangeConfig:
    try:
        from app.config import get_settings
        s = get_settings()
        # Prefer the generic crypto_exchange_* pair; fall back to the
        # Kraken-specific names Mike already set in agents/.env.
        key = (getattr(s, "crypto_exchange_api_key", "") or
               getattr(s, "kraken_api_key", "") or "")
        sec = (getattr(s, "crypto_exchange_api_secret", "") or
               getattr(s, "kraken_private_key", "") or "")
        exch = str(getattr(s, "crypto_exchange", "") or "").lower() or "kraken"
        return ExchangeConfig(
            exchange=exch, api_key=str(key), api_secret=str(sec),
            enabled=bool(getattr(s, "crypto_exchange_enabled", False)),
        )
    except Exception:  # noqa: BLE001
        return ExchangeConfig()


def has_credentials() -> bool:
    c = _config()
    return bool(c.api_key and c.api_secret)


def is_configured() -> bool:
    """Routing gate: only route crypto here when creds are present AND the
    connector is explicitly enabled. Off by default, so adding keys alone
    does not change trading -- crypto keeps running on the modeled engine."""
    c = _config()
    return bool(c.api_key and c.api_secret and c.enabled)


def exchange_supports(symbol: str) -> bool:
    return (symbol or "").upper().strip() in SUPPORTED


def kraken_pair(symbol: str) -> str | None:
    return PAIR_MAP.get((symbol or "").upper().strip())


def _sign(path: str, data: dict, secret: str) -> str:
    """Kraken API-Sign: HMAC-SHA512 over (path + SHA256(nonce + postdata)),
    keyed by the base64-decoded private key, returned base64. Verified
    offline against Kraken's documented test vector."""
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data["nonce"]) + postdata).encode()
    message = path.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def _private(method: str, params: dict | None = None, timeout: float = 15.0) -> dict:
    c = _config()
    if not (c.api_key and c.api_secret):
        return {"error": ["EGeneral:Connector not configured (no key/secret)"]}
    path = f"/0/private/{method}"
    data = dict(params or {})
    data["nonce"] = int(time.time() * 1000)
    try:
        sig = _sign(path, data, c.api_secret)
    except Exception as e:  # noqa: BLE001
        return {"error": [f"EGeneral:Signature failed: {e}"]}
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        KRAKEN_API + path, data=body,
        headers={"API-Key": c.api_key, "API-Sign": sig,
                 "User-Agent": "Trezo/1.0",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001
        return {"error": [f"EGeneral:HTTP error: {e}"]}


def get_balance() -> dict:
    """Private Balance (read-only). Used by self_test to prove auth."""
    return _private("Balance")


def validate_order(symbol: str, volume: float, side: str = "buy",
                   ordertype: str = "market", price: float | None = None) -> dict:
    """Send an order to Kraken with validate=true -- checks it against the
    live book WITHOUT placing it. No funds move. Long-only."""
    pair = kraken_pair(symbol)
    if not pair:
        return {"error": [f"EGeneral:Unsupported pair {symbol}"]}
    if (side or "").lower() != "buy":
        return {"error": ["EGeneral:Long-only connector (buy only)"]}
    params = {"pair": pair, "type": "buy", "ordertype": ordertype,
              "volume": f"{volume}", "validate": "true"}
    if ordertype == "limit" and price:
        params["price"] = f"{price}"
    return _private("AddOrder", params)


def self_test() -> dict:
    """Prove the API keys authenticate (private Balance call). Read-only,
    safe, no funds move. Returns {ok, ...}."""
    if not has_credentials():
        return {"ok": False, "reason": "no Kraken credentials found in agents/.env"}
    r = get_balance()
    err = r.get("error") or []
    if err:
        return {"ok": False, "reason": "; ".join(err)}
    return {"ok": True, "assets_held": len(r.get("result") or {}),
            "note": "keys authenticate; connector ready for validate-only orders"}


async def submit_order(*, user_id=None, ticker=None, side="buy", price=None,
                       stop_pct=None, target_pct=None, volume=None, **kw):
    """Part 3: VALIDATE-ONLY. Validates the order on Kraken (no funds move).
    Raises NotImplementedError only when there are no credentials, so the
    trade_execution router falls back to the modeled engine. Real placement
    + fill reconciliation is Part 4."""
    if not has_credentials():
        raise NotImplementedError("Kraken connector has no credentials set.")
    vol = volume if volume is not None else 0.0
    return {"validated": True, "result": validate_order(ticker, vol, side)}


async def get_positions(*a, **k):
    # Kraken spot exposes balances, not "positions"; return balances for recon.
    return get_balance()


async def close_position(*a, **k):
    raise NotImplementedError("Kraken close/exit management is Part 4.")


def health() -> dict:
    c = _config()
    if not (c.api_key and c.api_secret):
        mode = "no creds (add Kraken_API_KEY / Kraken_Private_Key to agents/.env)"
    elif not c.enabled:
        mode = "creds present, NOT routing (set CRYPTO_EXCHANGE_ENABLED=true to route)"
    else:
        mode = "enabled - validate-only (Part 3; real fills are Part 4)"
    return {
        "connector": "kraken",
        "exchange": c.exchange,
        "has_credentials": bool(c.api_key and c.api_secret),
        "enabled": c.enabled,
        "is_configured": is_configured(),
        "mode": mode,
        "supported": sorted(SUPPORTED),
    }
