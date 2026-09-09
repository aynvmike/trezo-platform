"""Read a book's current broker equity for research; never infer missing NAV.

This is a fresh paper-account read, not a trade budget or a verified return.
Internal modeled positions are not added to broker equity: they may represent
the same assets, and a consolidated valuation needs separate reconciliation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import math


class CapitalUnavailable(ValueError):
    """A stable, non-secret reason why dynamic research cannot proceed."""

    def __init__(self, reason: str, *, diagnostic: dict | None = None):
        super().__init__(reason)
        self.diagnostic = diagnostic


async def read_capital_snapshot(book_id: str) -> dict:
    from app.brokers.accounts import bind_for_user
    from app.brokers import alpaca
    from app.brokers.endpoints import paper_base_url

    with bind_for_user(book_id) as bound:
        # An unresolved binding normally falls back to primary downstream.
        # Never let that behavior size research for an unknown/sibling book.
        if bound is None or bound.account_key != book_id:
            raise CapitalUnavailable("research_book_unresolved")
        try:
            endpoint = paper_base_url(bound.base_url)
        except ValueError as exc:
            raise CapitalUnavailable("research_paper_endpoint_required") from exc
        # The legacy transport ignores registry bindings in single-account
        # mode. Check the credentials it will actually use before any I/O;
        # a lone acct2 must never silently read primary's account instead.
        try:
            correct_route = (bool(bound.key_id and bound.secret)
                             and alpaca.broker_venue() == "paper"
                             and alpaca._base_url() == endpoint
                             and alpaca._headers_for(None) == bound.headers())
        except Exception:
            correct_route = False
        if not correct_route:
            raise CapitalUnavailable("research_broker_route_mismatch")
        # Keep the diagnostic attached to THIS read. last_read_error() is a
        # per-book historical slot and can describe another concurrent read.
        with alpaca.capture_read_failure("/v2/account") as capture:
            try:
                account = await asyncio.wait_for(alpaca.get_account(), timeout=10)
            except asyncio.TimeoutError as exc:
                raise CapitalUnavailable("research_equity_read_failed", diagnostic={
                    "endpoint": "/v2/account", "category": "deadline_exceeded"}) from exc
            except Exception as exc:
                raise CapitalUnavailable("research_equity_read_failed", diagnostic={
                    "endpoint": "/v2/account",
                    **alpaca._safe_read_failure(type(exc).__name__ + ":")}) from exc
            if account is None:
                raise CapitalUnavailable("research_equity_read_failed", diagnostic=(
                    capture.failure or {"endpoint": "/v2/account", "category": "unclassified_failure"}))
    try:
        if isinstance(account.equity, bool) or isinstance(account.cash, bool):
            raise ValueError("invalid account amounts")
        equity, cash = float(account.equity), float(account.cash)
        if not math.isfinite(equity) or not math.isfinite(cash) or not 1 <= equity <= 1_000_000_000:
            raise ValueError("invalid account amounts")
        if account.currency != "USD" or account.status != "ACTIVE":
            raise ValueError("unsupported account state")
        identity = account.account_id
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError("missing broker identity")
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise CapitalUnavailable("research_equity_snapshot_invalid") from exc
    return {"book_id": book_id, "source": "alpaca_paper_account",
            "currency": "USD", "equity_usd": equity,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "account_fingerprint": hashlib.sha256(identity.encode()).hexdigest()}
