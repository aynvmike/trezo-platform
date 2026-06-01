"""Active-broker adapter — single front door for every broker query.

Today only Alpaca is implemented. Webull, Robinhood, IBKR, etc. plug in
by implementing the same `BrokerAdapter` shape and registering in the
factory below. The rest of Trezo (Wheel, Options Scanner, dashboard
snapshots) only ever calls the active broker — no hardcoded Alpaca
imports leak into business logic anymore.

Selection order (per user, then global):
  1. The user's connected OAuth broker (broker_connections table).
  2. Env-key Alpaca (single-tenant fallback).
  3. None — pure modeled mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class BrokerSnapshot:
    """Normalised broker snapshot — same shape regardless of provider."""
    name: str                        # 'alpaca' | 'webull' | 'robinhood' | ...
    venue: str                       # 'paper' | 'live'
    equity: float = 0.0
    last_equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    options_approved_level: int = 0
    trading_blocked: bool = False
    raw: dict | None = None          # provider-specific blob for debugging


@dataclass
class BrokerQuote:
    """One option quote — same shape across providers."""
    underlying: str
    occ: str
    type: str                        # 'call' | 'put'
    strike: float
    expiration: str                  # ISO yyyy-mm-dd
    bid: float = 0.0
    ask: float = 0.0
    mid: float = 0.0
    iv: float = 0.0
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None


async def active_broker_name(user_id: Optional[str] = None) -> str:
    """Which broker is currently routing for this user?

    Today's logic: per-user Alpaca OAuth wins; env-key Alpaca next;
    'modeled' if nothing's configured. The string return is used by the
    Wheel UI ("routed via alpaca · live") and by analytics."""
    if user_id:
        try:
            from app.integrations.web_tokens import get_user_broker_token
            for b in ("alpaca", "webull", "robinhood"):
                bt = await get_user_broker_token(user_id, b)
                if bt and bt.access_token:
                    return b
        except Exception:  # noqa: BLE001
            pass
    try:
        from app.brokers.alpaca import alpaca_configured
        if alpaca_configured():
            return "alpaca"
    except Exception:  # noqa: BLE001
        pass
    return "modeled"


async def active_broker_snapshot(user_id: Optional[str] = None) -> Optional[BrokerSnapshot]:
    """Normalised account snapshot from whichever broker is active.

    Returns None when in pure modeled mode (nothing configured)."""
    name = await active_broker_name(user_id)
    if name == "alpaca":
        return await _alpaca_snapshot(user_id)
    if name == "webull":
        return await _webull_snapshot(user_id)
    if name == "robinhood":
        return await _robinhood_snapshot(user_id)
    return None


async def active_broker_option_chain(
    underlying: str,
    user_id: Optional[str] = None,
) -> list[BrokerQuote]:
    """Live option chain for `underlying`, near-the-money, normalised.
    Empty list when broker unconfigured or no chain available."""
    name = await active_broker_name(user_id)
    if name == "alpaca":
        return await _alpaca_chain(underlying, user_id)
    # Future: webull / robinhood option chains
    return []


# ---- Provider adapters --------------------------------------------------
# Each adapter takes/returns the normalised types above. Adding a new
# broker = adding a new adapter pair (snapshot + chain) here.

async def _alpaca_snapshot(user_id: Optional[str]) -> Optional[BrokerSnapshot]:
    from app.brokers.alpaca import get_account, broker_venue, UserToken
    token = None
    if user_id:
        try:
            from app.integrations.web_tokens import get_user_broker_token
            bt = await get_user_broker_token(user_id, "alpaca")
            if bt and bt.access_token:
                token = UserToken(
                    access_token=bt.access_token,
                    refresh_token=bt.refresh_token,
                    expires_at=bt.expires_at,
                )
        except Exception:  # noqa: BLE001
            pass
    acct = await get_account(token=token)
    if not acct:
        return None
    return BrokerSnapshot(
        name="alpaca",
        venue=broker_venue(),
        equity=float(acct.equity),
        last_equity=float(acct.last_equity),
        cash=float(acct.cash),
        buying_power=float(acct.buying_power),
        options_approved_level=int(acct.options_approved_level),
        trading_blocked=bool(acct.trading_blocked),
        raw=acct.to_dict(),
    )


async def _alpaca_chain(underlying: str, user_id: Optional[str]) -> list[BrokerQuote]:
    """Pull the near-the-money chain via the existing live_option_pick
    helpers, normalise into BrokerQuote shape."""
    try:
        from app.brokers.alpaca_data import (
            get_option_contracts, get_option_quote,
        )
    except Exception:  # noqa: BLE001
        return []
    try:
        contracts = await get_option_contracts(underlying.upper())
    except Exception:  # noqa: BLE001
        return []
    out: list[BrokerQuote] = []
    for c in (contracts or [])[:30]:  # cap so we don't hammer the chain
        occ = str(c.get("symbol") or "")
        if not occ:
            continue
        q = None
        try:
            q = await get_option_quote(occ)
        except Exception:  # noqa: BLE001
            q = None
        bid = float((q or {}).get("bp") or 0)
        ask = float((q or {}).get("ap") or 0)
        mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else max(bid, ask)
        out.append(BrokerQuote(
            underlying=underlying.upper(),
            occ=occ,
            type=str(c.get("type") or "").lower(),
            strike=float(c.get("strike_price") or 0),
            expiration=str(c.get("expiration_date") or ""),
            bid=bid, ask=ask, mid=round(mid, 4),
        ))
    return out


# ---- Stub adapters for future brokers -----------------------------------
# These return None / [] until the integrations are wired. Having them
# named here makes adding the new broker a self-contained PR — no other
# file needs to change.

async def _webull_snapshot(user_id: Optional[str]) -> Optional[BrokerSnapshot]:
    return None  # TODO: implement when Webull OAuth lands


async def _robinhood_snapshot(user_id: Optional[str]) -> Optional[BrokerSnapshot]:
    return None  # TODO: implement when Robinhood OAuth lands
