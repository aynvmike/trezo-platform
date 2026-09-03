"""What ACTUALLY arrived in the wallet after a crypto buy.

THE BUG THIS EXISTS FOR (proved from Alpaca's own records, 2026-09-02/03).

Alpaca takes its crypto commission IN THE COIN, not in cash. Trezo booked
the quantity it ASKED FOR; the broker credited the quantity that arrived,
which is net of that fee. Nothing reconciled the two, so every crypto row
had overstated its size since the day it opened, and the P/L on each was
computed against coin the book does not own.

    primary book cf1b0460, row a001bd8a, XRP
      order  b0fe65b6  buy, qty 23.326114883, filled_qty 23.326114883,
                       filled_avg_price 1.363, status filled
      FILL   activity  qty 23.326114883 @ 1.363   (agrees with the order)
      POSITION         qty 23.27479743, avg_entry 1.363
      gap              0.051317453

The FILL activity and the order agree with each other and BOTH disagree
with the wallet. Measured across a 720h window on the primary book, BTC
closes to nine decimals:

      buys 0.090887428 x (1 - 0.0025) - sells 0.081987518
        = 0.008672691   vs   position 0.008672685      (6e-9 apart)

and the single from-flat buy a25d154b lands on the nose:

      0.008694422 x 0.9975 = 0.008672685945  ->  position 0.008672685

So: the deduction is on BUYS ONLY (a sell delivers exactly the coin it
says), it is proportional, and on 2026-09-02 it measured 0.25%.

WHY THIS MODULE DOES NOT MULTIPLY BY 0.9975.

Because 0.25% is not the rate. Measured on the ten open crypto rows on
2026-09-03, order.filled_qty against the wallet:

      primary BTC   a25d154b  31 Aug 18:21   0.250011%
      primary DOGE, ETH, LTC, SOL, XRP        0.220000%
      acct2   BTC, ETH                        0.220008% / 0.220000%
      acct3   BTC, ETH                        0.200000%

Three different rates, by book and by date -- Alpaca's crypto fee is a
published VOLUME TIER. A hard-coded 0.9975 would have been wrong on nine
of those ten rows, and silently.

WHY IT DOES NOT READ THE VENUE'S FEE RECORD EITHER.

Alpaca does publish one. /v2/account/activities?activity_types=CFEE
returns "Coin Pair Transaction Fee (Non USD)" rows carrying the fee as a
negative COIN quantity, and they match the measured shortfalls exactly:

      ETH  -0.000662275 @ 2418.94   (row e075acbc's gap: 0.000662273)
      SOL  -0.00063134  @ 100       (row 7618f33e's gap: 0.000631343)
      XRP  -0.047443116 @ 1.35      = 21.565052681 x 0.0022, to the digit

They also confirm which side pays how: the "(Non USD)" rows carry a coin
qty and pair with BUYS; the "(USD)" rows carry a cash net_amount, no
symbol, and pair with SELLS. That is why a sell is never short in coin.

Two things make them useless AT EXECUTION TIME, both measured:

  * they arrive late. On 2026-09-03 the newest CFEE row on the primary
    book was timestamped 2026-09-02T04:21:57Z. The XRP buy this module
    exists for filled at 2026-09-03T01:40:58Z and had no fee row 21
    hours later. A record that does not exist yet cannot be read.
  * they carry NO order id -- symbol, qty, price, created_at and nothing
    else. Tying one to an order means matching on symbol and time, which
    is a guess the moment two buys of a coin land near each other.

So they are the wrong tool for the executor. They are the RIGHT tool for
a later receipted reconciliation, and that is written up for Mike rather
than half-built here.

WHAT IT DOES INSTEAD: it MEASURES the arrival.

    qty_before   the wallet's own quantity, read BEFORE the order
    qty_after    the wallet's own quantity, read after the fill
    arrived      qty_after - qty_before

A delta, not a snapshot -- which is what makes the add-to-existing case
correct. A book that already holds 0.0069 XRP and buys 23.326114883 more
ends at 23.27479743; the SNAPSHOT is not this fill's quantity, the DELTA
is. Booking the snapshot would have inflated every add by the whole prior
holding, which is a bigger bug than the one being fixed.

HOUSE RULE 3 -- A FAILED READ IS NEVER A NUMBER. There are three rungs and
the module always says which one it stood on:

    1. arrival   qty_after - qty_before, when both reads answered and the
                 delta is inside the plausibility band below
    2. receipt   the ORDER's own filled_qty, when the order read answered
                 terminally but the wallet did not
    3. request   the quantity submitted -- today's behaviour, unchanged

Rungs 2 and 3 log why they were taken and leave the row exactly where the
QA inspector already finds it (qa_quantity_drift / A3). A zero is never
booked, a fee is never assumed, and a number is never invented.

THE PLAUSIBILITY BAND. An accepted arrival must satisfy

    receipt x (1 - max_fee)  <=  arrived  <=  receipt

Upper bound because a buy can never deliver MORE coin than was bought;
lower bound because a delta far below the receipt is not a fee, it is a
concurrent sell, an unsettled read, or a wallet read from the wrong book.
max_fee defaults to 1% -- four times the observed 0.25%, so a tier change
still lands inside it, while a stop-loss firing between the two reads
(which moves the delta by a whole position) lands outside and is refused.

READ-ONLY AT THE VENUE. This module places, cancels and modifies nothing.
It reads /v2/positions and /v2/orders/<id> and returns a number.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

# ---------------------------------------------------------------------------
# Knobs, read at CALL time so ops can change posture without a restart and a
# test can set one.
# ---------------------------------------------------------------------------


def _envf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _envi(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def max_fee_frac() -> float:
    """Largest shortfall that may be called a fee. Default 1% (4x observed)."""
    # REVIEW 2026-09-03: the band is deliberately NOT tightened toward the
    # observed tiers (0.25% / 0.22% / 0.20%). It is a sanity bound, not a
    # fee rate: narrow it to 0.4% and the day Alpaca moves a tier, every
    # crypto entry silently drops to the receipt and this bug comes back
    # quietly. What stops an unrelated credit being read as our arrival is
    # _sole_filled_order, which requires ours to be the only fill in the
    # window -- evidence, not a width.
    v = _envf("TREZO_CRYPTO_MAX_FEE_PCT", 0.01)
    return v if 0.0 < v < 0.5 else 0.01


def settle_attempts() -> int:
    """How many times to look before giving up. Default 4."""
    return max(1, _envi("TREZO_CRYPTO_SETTLE_ATTEMPTS", 4))


def settle_delay_s() -> float:
    """Pause between looks. Default 0.4s -> at most ~1.2s of waiting."""
    v = _envf("TREZO_CRYPTO_SETTLE_DELAY_S", 0.4)
    return v if 0.0 <= v <= 5.0 else 0.4


# ---------------------------------------------------------------------------
# Seams. Patched by the guard suite; lazily imported so this module can be
# loaded in a bare checkout with no credentials.
# ---------------------------------------------------------------------------


async def _read_positions(token=None):
    from app.brokers.alpaca import get_positions_strict
    return await get_positions_strict(token=token)


async def _read_order(order_id: str, token=None):
    from app.brokers.alpaca import get_order_strict
    return await get_order_strict(order_id, token=token)


async def _read_closed_orders(symbol: str, token=None, limit: int = 8):
    """Recent CLOSED orders for one symbol. A module-level seam like the
    two reads above, so the suites can drive it without a network call."""
    from app.brokers.alpaca import get_recent_closed_orders
    return await get_recent_closed_orders(symbol, token=token, limit=limit)


def _read_error() -> str:
    from app.brokers.alpaca import last_read_error
    return last_read_error() or ""


def _non_terminal() -> frozenset:
    from app.brokers.alpaca import NON_TERMINAL_ORDER_STATUSES
    return NON_TERMINAL_ORDER_STATUSES


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _log(event: str, ticker: str, *, reason: str, extra: dict) -> None:
    """LATE import (house rule 4): the activity log must never be a
    top-level dependency of a module the executor imports."""
    try:
        from app.agents.activity_log import record as _rec
        _rec(event, ticker, strategy="crypto_settle", reason=reason,
             extra=extra)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Symbol handling and decimals
# ---------------------------------------------------------------------------


def _base(symbol) -> str:
    """'XRP', 'XRPUSD' and 'XRP/USD' all give 'XRP'. Same rule as
    alpaca._crypto_base -- test_crypto_fee_in_kind asserts the two agree."""
    s = str(symbol or "").upper().strip()
    if "/" in s:
        return s.split("/", 1)[0]
    if s.endswith("USD") and len(s) > 4:
        return s[:-3]
    return s


def _dec(value) -> Optional[Decimal]:
    """Decimal from the venue's own STRING, or None.

    Decimal, not float: DOGE positions run to five figures with nine
    decimals, and the whole answer here is a difference between two nearly
    equal numbers of that size. Binary rounding in that subtraction is the
    same class of error the module exists to remove."""
    if value is None:
        return None
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not d.is_finite():
        return None
    return d


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------

# Which rung the booked quantity came from.
FROM_ARRIVAL = "arrival"    # the wallet's own delta
FROM_RECEIPT = "receipt"    # the order's filled_qty
FROM_REQUEST = "request"    # the quantity submitted (today's behaviour)


@dataclass(frozen=True)
class Arrived:
    """What to book, where the number came from, and why not the better one."""

    quantity: float
    source: str
    reason: str = ""
    receipt_qty: Optional[float] = None
    delta: Optional[float] = None
    fee_qty: Optional[float] = None
    fee_frac: Optional[float] = None

    @property
    def settled(self) -> bool:
        return self.source == FROM_ARRIVAL


async def position_qty(symbol: str, token=None) -> tuple[Optional[Decimal], str]:
    """This book's wallet quantity for one coin.

        (Decimal, "")        an ANSWER -- and Decimal(0) when flat
        (None, reason)       ANSWERLESS -- the read failed

    Flat is zero and a failed read is None, never the other way round
    (house rule 3). The two are not interchangeable here: a None treated
    as flat would make the next buy's delta the WHOLE new position, so an
    add would book as if the book had been empty."""
    rows = await _read_positions(token=token)
    if rows is None:
        return None, (_read_error() or "positions read failed")
    want = _base(symbol)
    total = Decimal(0)
    seen = False
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "")
        ac = str(r.get("asset_class") or "").lower()
        # CRYPTO ONLY, and say why: an equity whose ticker collides with a
        # coin's base ("BTC" the stock) must never be counted as the coin.
        # asset_class is authoritative; the pair spelling is the backstop
        # for a payload that omits it.
        if ac != "crypto" and not (ac == "" and "/" in sym):
            continue
        if _base(sym) != want:
            continue
        q = _dec(r.get("qty"))
        if q is None:
            return None, f"position for {want} has an unreadable qty"
        total += q
        seen = True
    return (total if seen else Decimal(0)), ""


async def _sole_filled_order(symbol: str, oid: str, token=None) -> tuple:
    """Is OUR order the only one for this symbol that filled in the window?

    REVIEW 2026-09-03, BLOCKING (house rule 6). The delta between two
    wallet reads is evidence that SOMETHING arrived -- not that THIS order
    delivered it. Driven against the real executor, a different same-coin
    credit of 23.30 while our order filled 23.326114883 was booked as our
    arrival, stamped qty_source="arrival", and logged an invented
    commission rate of 0.1120%. Another fill's size written as settled
    fact is exactly what house rule 6 forbids.

    So before a delta may be called ours, confirm no OTHER order for the
    symbol filled alongside it. Returns (True, "") when ours is alone,
    (False, why) when it is not or when the question cannot be answered --
    an unanswerable question drops a rung, it does not pass.
    """
    try:
        rows = await _read_closed_orders(symbol, token=token, limit=8)
    except Exception as e:  # noqa: BLE001
        return False, f"could not check for other fills: {type(e).__name__}"
    if not isinstance(rows, list):
        return False, "could not check for other fills: unreadable"
    others = []
    for o in rows:
        if not isinstance(o, dict):
            continue
        if str(o.get("id") or "") == oid:
            continue
        if not o.get("filled_at"):
            continue                       # never filled: cannot have moved the wallet
        if (_dec(o.get("filled_qty")) or Decimal(0)) <= 0:
            continue
        others.append(str(o.get("id"))[:8])
    if others:
        return False, ("another order for this symbol filled in the same "
                       f"window ({', '.join(others[:3])})")
    return True, ""


async def arrived_buy_quantity(
    *,
    symbol: str,
    order_id: Optional[str],
    submitted_qty: float,
    qty_before: Optional[Decimal],
    token=None,
    user_id: str = "",
) -> Arrived:
    """The quantity a crypto BUY actually delivered into this book.

    `qty_before` is the wallet quantity read BEFORE the order was sent --
    Decimal for a real read, None when that read failed. None is honoured:
    without a before there is no delta, and the module drops a rung rather
    than pretending the book was empty.

    Never raises. Never returns zero or a negative."""
    req = _dec(submitted_qty) or Decimal(0)
    fallback = Arrived(quantity=float(submitted_qty), source=FROM_REQUEST)
    if req <= 0:
        return fallback

    oid = str(order_id or "").strip()
    attempts = settle_attempts()
    delay = settle_delay_s()
    band = Decimal(str(max_fee_frac()))

    receipt: Optional[Decimal] = None
    receipt_why = "order not read"
    pos_why = "wallet not read"

    for i in range(attempts):
        # ---- rung 2: the receipt -------------------------------------
        if receipt is None and oid:
            order, oerr = await _read_order(oid, token=token)
            if order is None:
                receipt_why = oerr or "the venue has no such order"
            else:
                status = str(order.get("status") or "").strip().lower()
                fq = _dec(order.get("filled_qty"))
                if status in _non_terminal():
                    # A partially filled order is still delivering. Booking
                    # its filled_qty now UNDER-books the row by whatever
                    # arrives in the next fifty milliseconds, which is the
                    # mirror of the bug being fixed. Wait for terminal.
                    receipt_why = f"order still {status}"
                elif fq is None or fq <= 0:
                    receipt_why = f"order {status or 'unknown'} with no filled qty"
                else:
                    receipt = fq
                    receipt_why = ""

        # ---- rung 1: the arrival -------------------------------------
        if receipt is not None and qty_before is not None:
            after, perr = await position_qty(symbol, token=token)
            if after is None:
                pos_why = perr or "positions read failed"
            else:
                delta = after - qty_before
                floor = receipt * (Decimal(1) - band)
                sole, sole_why = (await _sole_filled_order(symbol, oid, token=token)
                                  if oid else (False, "no order id to check against"))
                if not sole:
                    pos_why = sole_why
                elif floor <= delta <= receipt:
                    fee = receipt - delta
                    frac = float(fee / receipt) if receipt else 0.0
                    if fee > 0:
                        _log("crypto_fee_in_kind", _base(symbol),
                             reason=(f"booked the quantity that ARRIVED: "
                                     f"{delta} of {receipt} filled "
                                     f"({fee} kept by the venue as its "
                                     f"commission in the coin, "
                                     f"{frac * 100:.4f}%). The wallet, not "
                                     f"the order, is what this book owns."),
                             extra={"user_id": str(user_id),
                                    "symbol": _base(symbol),
                                    "order_id": oid, "filled_qty": str(receipt),
                                    "arrived_qty": str(delta),
                                    "qty_before": str(qty_before),
                                    "fee_qty": str(fee)})
                    return Arrived(quantity=float(delta), source=FROM_ARRIVAL,
                                   receipt_qty=float(receipt),
                                   delta=float(delta), fee_qty=float(fee),
                                   fee_frac=frac)
                else:
                    # REVIEW 2026-09-03: this was UNCONDITIONAL, so it
                    # overwrote the exclusivity reason set two lines above
                    # and a demotion caused by a rival fill was reported as
                    # a band failure. The reason a rung was dropped has to
                    # be the reason it was actually dropped.
                    pos_why = (f"wallet moved {delta} against a filled "
                               f"{receipt} -- outside the "
                               f"{float(band) * 100:g}% band, so it is not "
                               f"this fill's arrival")
        elif receipt is not None and qty_before is None:
            pos_why = ("no pre-order wallet read, so there is no delta to "
                       "measure this fill's arrival with")
            break

        if i < attempts - 1:
            await _sleep(delay)

    # ---- rung 2 or 3, and say which ----------------------------------
    if receipt is not None:
        why = (f"booked the ORDER's filled quantity {receipt}, not the "
               f"wallet's: {pos_why}. The venue's crypto commission comes "
               f"out of the coin, so this row may be up to "
               f"{float(band) * 100:g}% larger than what the book holds -- "
               f"the QA inspector's qa_quantity_drift will see it.")
        _log("crypto_arrival_unresolved", _base(symbol), reason=why,
             extra={"user_id": str(user_id), "symbol": _base(symbol),
                    "order_id": oid, "filled_qty": str(receipt),
                    "booked": str(receipt), "rung": FROM_RECEIPT})
        return Arrived(quantity=float(receipt), source=FROM_RECEIPT,
                       reason=pos_why, receipt_qty=float(receipt))

    why = (f"booked the SUBMITTED quantity {req}: {receipt_why}. Nothing "
           f"was invented -- this is what Trezo asked the venue for, and "
           f"the QA inspector will compare it against the wallet.")
    _log("crypto_arrival_unresolved", _base(symbol), reason=why,
         extra={"user_id": str(user_id), "symbol": _base(symbol),
                "order_id": oid, "booked": str(req), "rung": FROM_REQUEST})
    return Arrived(quantity=float(submitted_qty), source=FROM_REQUEST,
                   reason=receipt_why)
