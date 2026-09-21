"""Fresh, sided Alpaca marks for broker decisions; never historical candles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

MAX_QUOTE_AGE_SECONDS = 60.0
MAX_FUTURE_SECONDS = 2.0


@dataclass(frozen=True)
class ExecutionPrice:
    price: float
    timestamp: datetime
    source: str
    symbol: str
    side: str


def _symbol(value: str, asset_type: str) -> str:
    value = str(value or "").upper().strip()
    if asset_type == "crypto":
        value = value.replace("/", "")
        if not value.endswith("USD"):
            value += "USD"
    return value


async def execution_price(ticker: str, asset_type: str, side: str, *,
                          now: datetime | None = None, action: str = "close") -> ExecutionPrice | None:
    """Return executable bid for a long exit or ask for a short exit.

    Source is fixed by the called Alpaca endpoint. A missing, crossed,
    stale or malformed quote supplies no decision price. Unsupported
    asset classes also return None; there is no candle/mid/entry fallback.
    """
    at = str(asset_type or "").lower().strip()
    side = str(side or "").lower().strip()
    if (at not in ("stock", "crypto") or side not in ("long", "short")
            or action not in ("open", "close")):
        return None
    try:
        from app.brokers import alpaca_data
        request_symbol = (_symbol(ticker, at)[:-3] + "/USD") if at == "crypto" else ticker
        quote = await (alpaca_data.get_crypto_quote(request_symbol) if at == "crypto"
                       else alpaca_data.get_quote(ticker))
        if quote is None or _symbol(quote.symbol, at) != _symbol(ticker, at):
            return None
        stamp = datetime.fromisoformat(str(quote.ts).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        clock = now or datetime.now(timezone.utc)
        age = (clock - stamp).total_seconds()
        if not -MAX_FUTURE_SECONDS <= age <= MAX_QUOTE_AGE_SECONDS:
            return None
        if isinstance(quote.bid, bool) or isinstance(quote.ask, bool):
            return None
        bid, ask = float(quote.bid), float(quote.ask)
        if not all(math.isfinite(p) and p > 0 for p in (bid, ask)) or bid > ask:
            return None
        use_bid = (side == "long" and action == "close") or (side == "short" and action == "open")
        return ExecutionPrice(
            bid if use_bid else ask, stamp,
            "alpaca:crypto:us" if at == "crypto" else f"alpaca:stock:{alpaca_data.DATA_FEED}",
            _symbol(ticker, at), side,
        )
    except Exception:  # noqa: BLE001 -- unknown prices cannot trigger an order
        return None
