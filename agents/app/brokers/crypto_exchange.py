"""Crypto-exchange connector SCAFFOLD (Coinbase / Kraken).

Crypto Part 2 (Mike 2026-06-13). The ISO 20022 cluster (XLM, HBAR, ALGO,
IOTA, QNT, XDC, XYO) has no venue on Alpaca, so today those coins run on
Trezo's modeled-paper engine. This module is the seam where a REAL
exchange connector slots in once Mike adds API keys, letting the full ISO
list trade with live capital instead of modeled fills.

Status: SCAFFOLD + FEATURE-FLAGGED OFF. ``is_configured()`` returns False
until ``crypto_exchange_enabled=true`` AND a key/secret are set in
agents/.env, so the routing branch in trade_execution can never fire this
path by accident. ``submit_order`` / ``get_positions`` / ``close_position``
are deliberate stubs that raise NotImplementedError -- filling them in is
the Part 3 task. Mirrors the alpaca_crypto feature-flag pattern exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

# Coins this connector is INTENDED to cover once live: the whole ISO 20022
# cluster plus majors. Used only for capability reporting today.
SUPPORTED = frozenset({
    "BTC", "ETH", "SOL", "XRP", "XLM", "HBAR", "ALGO",
    "IOTA", "QNT", "XDC", "XYO", "ADA",
})


@dataclass
class ExchangeConfig:
    enabled: bool = False
    exchange: str = "coinbase"
    api_key: str = ""
    api_secret: str = ""


def _config() -> ExchangeConfig:
    try:
        from app.config import get_settings
        s = get_settings()
        return ExchangeConfig(
            enabled=bool(getattr(s, "crypto_exchange_enabled", False)),
            exchange=str(getattr(s, "crypto_exchange", "coinbase") or "coinbase"),
            api_key=str(getattr(s, "crypto_exchange_api_key", "") or ""),
            api_secret=str(getattr(s, "crypto_exchange_api_secret", "") or ""),
        )
    except Exception:  # noqa: BLE001
        return ExchangeConfig()


def is_configured() -> bool:
    """True ONLY when the flag is on AND both credentials are present.
    Until then the routing branch falls through to the modeled engine."""
    c = _config()
    return bool(c.enabled and c.api_key and c.api_secret)


def exchange_supports(symbol: str) -> bool:
    return (symbol or "").upper().strip() in SUPPORTED


def health() -> dict:
    """Surface connector state for the ops/health endpoint without leaking
    secrets (booleans only)."""
    c = _config()
    return {
        "connector": "crypto_exchange",
        "exchange": c.exchange,
        "enabled": c.enabled,
        "configured": is_configured(),
        "has_key": bool(c.api_key),
        "has_secret": bool(c.api_secret),
        "supported_count": len(SUPPORTED),
        "status": "live" if is_configured() else "scaffold (off - add keys to enable)",
    }


async def submit_order(*args, **kwargs):
    raise NotImplementedError(
        "crypto_exchange.submit_order is a scaffold. Implement the "
        "Coinbase/Kraken REST call in Part 3 once API keys are set.")


async def get_positions(*args, **kwargs):
    raise NotImplementedError(
        "crypto_exchange.get_positions is a scaffold (Part 3).")


async def close_position(*args, **kwargs):
    raise NotImplementedError(
        "crypto_exchange.close_position is a scaffold (Part 3).")
