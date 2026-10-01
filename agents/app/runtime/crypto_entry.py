"""Fresh execution quote and cost evidence for new Alpaca spot crypto buys.

No network or trading at import time. Current bid/ask is a cost estimate;
it cannot predict the exit spread or guarantee a positive outcome.
"""
from datetime import datetime, timezone
import math


def evaluate_quote(quote, target_fraction, fee_bps, *, now=None, max_age=120):
    if quote is None:
        return None, "crypto_quote_unavailable"
    try:
        bid, ask = float(quote.bid), float(quote.ask)
        target, fee = float(target_fraction), float(fee_bps)
        if not all(math.isfinite(x) for x in (bid, ask, target, fee)):
            raise ValueError
        if bid <= 0 or ask < bid or target <= 0 or fee < 0:
            raise ValueError
        timestamp = datetime.fromisoformat(str(quote.ts).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError
        age = ((now or datetime.now(timezone.utc)) - timestamp).total_seconds()
        if age < -5 or age > max_age:
            return None, "crypto_quote_stale_or_future"
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None, "crypto_quote_invalid"
    # Entry is sized at the executable ask. Full current spread estimates
    # immediate liquidation friction; add the existing per-side fee and
    # 5 bps per side for additional slippage, matching the audit defaults.
    spread = (ask - bid) / ask
    cost = spread + 2 * fee / 10000 + 10 / 10000
    evidence = {"provider": "alpaca", "quote_ts": quote.ts,
                "age_seconds": round(age, 3), "bid": bid, "ask": ask,
                "round_trip_cost_fraction": cost,
                "target_fraction": target, "fee_bps_per_side": fee,
                "additional_slippage_bps_per_side": 5}
    if target <= cost:
        return evidence, "crypto_target_below_estimated_cost"
    return evidence, None


async def entry_quote(ticker, target_fraction):
    from app.brokers.alpaca_data import get_crypto_quote
    from app.paper.engine import CRYPTO_COMMISSION_BPS
    quote = await get_crypto_quote(ticker)
    return evaluate_quote(quote, target_fraction, CRYPTO_COMMISSION_BPS)
