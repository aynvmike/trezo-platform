"""Active-broker adapter — single front door for every broker query.

Today only Alpaca is implemented. Webull, Robinhood, IBKR, etc. plug in
by implementing the same `BrokerAdapter` shape and registering in the
factory below. The rest of Trezo (Wheel, Options Scanner, dashboard
snapshots) only ever calls the active broker — no hardcoded Alpaca
imports leak into business logic anymore.

Snapshot selection order:
  1. An explicit registered paper book's own credentials.
  2. The user's connected OAuth broker (broker_connections table).
  3. Env-key Alpaca for requests without an explicit user/book.
  4. None when an explicit snapshot route cannot be verified.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
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
    book_key: str | None = None      # explicit registry binding, never a guessed owner


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

    Returns None when configuration, routing or the broker read is unavailable.
    An explicit registered book takes its own registry route; it is not
    interchangeable with an OAuth owner's identity or the default book.
    """
    try:
        if user_id:
            from app.brokers.accounts import account_for_user
            if account_for_user(user_id) is not None:
                return await _alpaca_snapshot(user_id)
        name = await active_broker_name(user_id)
        if name == "alpaca":
            return await _alpaca_snapshot(user_id)
        if name == "webull":
            return await _webull_snapshot(user_id)
        if name == "robinhood":
            return await _robinhood_snapshot(user_id)
        return None
    except Exception:  # noqa: BLE001
        # Failed or malformed reads are unavailable, never a zero balance.
        # asyncio cancellation still propagates and releases the binding.
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
    from app.brokers.accounts import (
        account_for_user, bind_for_user, multi_account_active,
    )
    book_key = None
    token = None
    if user_id:
        try:
            account = account_for_user(user_id)
        except Exception:  # noqa: BLE001
            return None
        if account is not None:
            # The existing Alpaca transport deliberately ignores registry
            # bindings in live mode and single-account mode. Never label
            # an unsupported secondary route with the primary's equity.
            if broker_venue() != "paper":
                return None
            if not multi_account_active() and account.account_id != "primary":
                return None
            with bind_for_user(user_id) as bound:
                if bound is None or bound.account_key != user_id:
                    return None
                acct = await get_account()
                book_key = user_id
        else:
            # A user outside the paper registry may have an OAuth account.
            # If lookup fails or no token exists, the answer is unknown;
            # explicit requests must never fall through to env credentials.
            try:
                from app.integrations.web_tokens import get_user_broker_token
                bt = await get_user_broker_token(user_id, "alpaca")
                if not bt or not bt.access_token:
                    return None
                token = UserToken(
                    access_token=bt.access_token,
                    refresh_token=bt.refresh_token,
                    expires_at=bt.expires_at,
                )
            except Exception:  # noqa: BLE001
                return None
            acct = await get_account(token=token)
    else:
        acct = await get_account()
    if not acct:
        return None
    try:
        amounts = {key: float(getattr(acct, key)) for key in
                   ("equity", "last_equity", "cash", "buying_power")}
        if not all(math.isfinite(value) for value in amounts.values()):
            return None
    except (AttributeError, TypeError, ValueError):
        return None
    return BrokerSnapshot(
        name="alpaca",
        venue=broker_venue(),
        **amounts,
        options_approved_level=int(acct.options_approved_level),
        trading_blocked=bool(acct.trading_blocked),
        raw=acct.to_dict(),
        book_key=book_key,
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
