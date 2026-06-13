"""Kraken Futures connector — DEMO / paper first (Futures Phase 1, 2026-06-13).

Kraken Futures has a full demo/sandbox (demo-futures.kraken.com) that mirrors
production over the SAME API (only the base URL differs), so the agents can
LEARN futures and paper-trade strategies with NO real money. This is the
leveraged-futures path, distinct from the long-only spot connector.

SAFETY:
  * Default base = DEMO. Live futures requires kraken_futures_demo=false AND is
    a separate, explicit step (real money).
  * Leverage range 1x-10x (Mike 2026-06-13): agents choose leverage per
    strategy so the learning / strategy-strengthening process is NOT
    artificially limited. leverage_cap() clamps only at the 10x safety
    ceiling (the stated max); default setting is 10x.
  * Phase 1 is DATA + ACCOUNT READ only. Order placement (even on demo) is
    Phase 2, once strategies exist.
  * Needs a SEPARATE demo API key (demo-futures.kraken.com/settings/api); the
    spot key does NOT work here.

Public market data uses production (futures.kraken.com) -- the market is the
same; only the private/account base switches to demo.
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

DATA_BASE = "https://futures.kraken.com"        # public market data
DEMO_BASE = "https://demo-futures.kraken.com"   # paper account / trading
LIVE_BASE = "https://futures.kraken.com"        # real account (much later)

LEVERAGE_HARD_CAP = 10.0  # safety ceiling (stated max 10x); agents range 1x-10x freely


@dataclass
class FuturesConfig:
    enabled: bool = False
    demo: bool = True
    api_key: str = ""
    api_secret: str = ""
    max_leverage: float = 2.0


def _config() -> FuturesConfig:
    try:
        from app.config import get_settings
        s = get_settings()
        return FuturesConfig(
            enabled=bool(getattr(s, "kraken_futures_enabled", False)),
            demo=bool(getattr(s, "kraken_futures_demo", True)),
            api_key=str(getattr(s, "kraken_futures_api_key", "") or ""),
            api_secret=str(getattr(s, "kraken_futures_api_secret", "") or ""),
            max_leverage=float(getattr(s, "futures_max_leverage", 2.0) or 2.0),
        )
    except Exception:  # noqa: BLE001
        return FuturesConfig()


def _api_base() -> str:
    return DEMO_BASE if _config().demo else LIVE_BASE


def has_credentials() -> bool:
    c = _config()
    return bool(c.api_key and c.api_secret)


def is_configured() -> bool:
    c = _config()
    return bool(c.api_key and c.api_secret and c.enabled)


def leverage_cap() -> float:
    """Effective max leverage: the user's setting, capped at the 10x ceiling."""
    return max(1.0, min(LEVERAGE_HARD_CAP, _config().max_leverage))


def clamp_leverage(x) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        x = 1.0
    return max(1.0, min(leverage_cap(), x))


# ---- public market data (no auth, no money) -------------------------------
def _get_public(url: str, timeout: float = 12.0) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Trezo/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def list_instruments() -> dict:
    return _get_public(f"{DATA_BASE}/derivatives/api/v3/instruments")


def tradable_symbols() -> list[str]:
    """Every tradeable futures contract Kraken lists (widest available, incl.
    whatever ISO-cluster futures exist). Empty on failure."""
    data = list_instruments()
    out = []
    for it in (data.get("instruments") or []):
        if it.get("tradeable") and it.get("symbol"):
            out.append(it["symbol"])
    return out


def get_tickers() -> dict:
    return _get_public(f"{DATA_BASE}/derivatives/api/v3/tickers")


# ---- private (Kraken Futures Authent signing) ------------------------------
def _sign(endpoint_path: str, post_data: str, nonce: str, secret: str) -> str:
    """Kraken Futures Authent: base64( HMAC-SHA512( SHA256(postData + nonce +
    endpointPath), base64decode(secret) ) )."""
    msg = (post_data + nonce + endpoint_path).encode()
    sha = hashlib.sha256(msg).digest()
    mac = hmac.new(base64.b64decode(secret), sha, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def _private_get(method_path: str, params: dict | None = None,
                 timeout: float = 15.0) -> dict:
    c = _config()
    if not (c.api_key and c.api_secret):
        return {"result": "error", "error": "no Kraken Futures credentials"}
    endpoint = f"/derivatives/api/v3/{method_path}"
    post_data = urllib.parse.urlencode(params or {})
    nonce = str(int(time.time() * 1000))
    try:
        sig = _sign(endpoint, post_data, nonce, c.api_secret)
    except Exception as e:  # noqa: BLE001
        return {"result": "error", "error": f"sign failed: {e}"}
    url = f"{_api_base()}{endpoint}"
    if post_data:
        url = f"{url}?{post_data}"
    req = urllib.request.Request(url, headers={
        "APIKey": c.api_key, "Nonce": nonce, "Authent": sig,
        "User-Agent": "Trezo/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        return {"result": "error", "error": f"HTTP: {e}"}


def get_accounts() -> dict:
    """Private account/balance read (demo). Used by self_test."""
    return _private_get("accounts")


def self_test() -> dict:
    """Prove the DEMO futures keys authenticate (read-only accounts call).
    No funds move. If this returns an auth error, the likely cause is the
    signing endpointPath form -- easy to adjust."""
    if not has_credentials():
        return {"ok": False, "reason": "no Kraken Futures demo creds in agents/.env"}
    r = get_accounts()
    if str(r.get("result")) == "success" or r.get("accounts"):
        return {"ok": True, "base": _api_base(),
                "note": "futures demo keys authenticate"}
    return {"ok": False, "reason": str(r.get("error") or r)}


def health() -> dict:
    c = _config()
    return {
        "connector": "kraken_futures",
        "base": _api_base(),
        "demo": c.demo,
        "has_credentials": bool(c.api_key and c.api_secret),
        "enabled": c.enabled,
        "is_configured": is_configured(),
        "leverage_cap": leverage_cap(),
        "mode": "DEMO/paper" if c.demo else "LIVE (real money!)",
    }
