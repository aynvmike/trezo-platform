"""Guard tests: a crypto row must book the coin that ARRIVED.

WHY THESE EXIST (2026-09-03). Alpaca takes its crypto commission in the
COIN, not in cash. The executor booked the quantity it asked the venue
for; the wallet was credited less. From the primary book's own records:

    row a001bd8a, XRP, primary cf1b0460
      order b0fe65b6   buy 23.326114883, filled_qty 23.326114883,
                       filled_avg_price 1.363, status filled
      FILL activity    23.326114883 @ 1.363    (agrees with the order)
      POSITION         23.27479743
      gap              0.051317453

Both broker paperwork records agreed with each other and BOTH disagreed
with the wallet, so no amount of receipt-matching could ever have caught
it -- only the wallet knows. Confirmed on the same night on BTC, ETH,
SOL, LTC, DOGE and DOT across all three books. One bug, six symptoms.

The rule these tests hold the code to:

  * a BUY books the wallet's own DELTA (after - before), never the order
  * an ADD subtracts the prior holding, so it books this fill only
  * a wallet read that FAILS books the receipt and flags -- never a zero,
    never an assumed fee, never the whole snapshot
  * a SELL is not adjusted at all
  * a STOCK fill is not touched -- equities are commission-free at Alpaca
    and the 720h window arithmetic on every book confirms it

Run: python -m agents.tests.test_crypto_fee_in_kind   (or pytest)
"""

from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
# Pre-stub app.runtime so alpaca's lazy `from app.runtime.asset_policy
# import ...` does not trigger the real app/runtime/__init__.py.
load_module("app.runtime.asset_policy")
alp = load_module("app.brokers.alpaca")
cs = load_module("app.paper.crypto_settle")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---- the real records, verbatim -------------------------------------------

XRP_ORDER_ID = "b0fe65b6-16c2-4ba3-b964-b01c7923e163"
XRP_GROSS = "23.326114883"     # order.filled_qty
XRP_ARRIVED = "23.27479743"    # position.qty
XRP_FEE = "0.051317453"

XRP_ORDER = {
    "id": XRP_ORDER_ID, "symbol": "XRP/USD", "asset_class": "crypto",
    "side": "buy", "qty": XRP_GROSS, "filled_qty": XRP_GROSS,
    "filled_avg_price": "1.363", "status": "filled", "order_type": "market",
}


def _pos(symbol: str, qty: str) -> dict:
    return {"symbol": symbol, "asset_class": "crypto", "qty": qty,
            "avg_entry_price": "1.363", "side": "long"}


# ---- a fake venue for the two seams crypto_settle reads through -----------

class FakeVenue:
    """Stubs crypto_settle._read_positions / _read_order / _sleep / _log.

    Patches ATTRIBUTES on the module and puts every one of them back --
    all the suites share one process, so a leaked patch is another
    suite's mystery failure."""

    def __init__(self, *, positions, order=XRP_ORDER, order_err=None,
                 closed_orders=None, closed_raises=False):
        # positions: a list of snapshots, consumed one per read; the last
        # one repeats. None as a snapshot means the READ FAILED.
        self.snapshots = list(positions)
        self.order = order
        self.order_err = order_err
        # Other CLOSED orders for the symbol. Default: none -- ours is the
        # only fill, which is the normal case. A test that wants a rival
        # fill passes one (review 2026-09-03).
        self.closed_orders = list(closed_orders or [])
        self.closed_raises = closed_raises
        self.pos_reads = 0
        self.order_reads = 0
        self.sleeps = 0
        self.logged: list = []

    def install(self):
        self._real = (cs._read_positions, cs._read_order, cs._sleep,
                      cs._log, cs._read_error, cs._read_closed_orders)

        async def fake_positions(token=None):
            i = min(self.pos_reads, len(self.snapshots) - 1)
            self.pos_reads += 1
            return self.snapshots[i]

        async def fake_order(order_id, token=None):
            self.order_reads += 1
            if self.order_err:
                return None, self.order_err
            return self.order, None

        async def fake_closed(symbol, token=None, limit=8):
            if self.closed_raises:
                raise RuntimeError("closed-orders read failed")
            return list(self.closed_orders)

        async def fake_sleep(seconds):
            self.sleeps += 1

        def fake_log(event, ticker, *, reason, extra):
            self.logged.append((event, ticker, reason, extra))

        def fake_err():
            return "stubbed read failure"

        cs._read_positions = fake_positions
        cs._read_order = fake_order
        cs._sleep = fake_sleep
        cs._log = fake_log
        cs._read_error = fake_err
        cs._read_closed_orders = fake_closed
        return self

    def restore(self):
        (cs._read_positions, cs._read_order, cs._sleep, cs._log,
         cs._read_error, cs._read_closed_orders) = self._real

    def __enter__(self):
        return self.install()

    def __exit__(self, *a):
        self.restore()
        return False


def _arrived(**kw):
    kw.setdefault("symbol", "XRP")
    kw.setdefault("order_id", XRP_ORDER_ID)
    kw.setdefault("submitted_qty", float(XRP_GROSS))
    kw.setdefault("user_id", "cf1b0460-039d-40ac-adc8-7ca3ef17c5bb")
    return _run(cs.arrived_buy_quantity(**kw))


# ---------------------------------------------------------------------------
# 1. THE ACCEPTANCE CASE -- the real XRP order, replayed
# ---------------------------------------------------------------------------


def test_the_xrp_case_books_what_arrived_not_what_filled():
    """order b0fe65b6: filled 23.326114883, wallet credited 23.27479743."""
    with FakeVenue(positions=[[_pos("XRP/USD", XRP_ARRIVED)]]) as v:
        a = _arrived(qty_before=Decimal("0"))
    assert a.source == cs.FROM_ARRIVAL, f"fell back to {a.source}: {a.reason}"
    assert a.settled is True
    assert f"{a.quantity:.9f}" == f"{float(XRP_ARRIVED):.9f}", a.quantity
    assert a.quantity < float(XRP_GROSS), "booked the order, not the wallet"
    assert abs(a.fee_qty - float(XRP_FEE)) < 1e-9, a.fee_qty
    # The gap is 0.22% of the purchase -- the number in the incident note.
    assert 0.0021 < a.fee_frac < 0.0023, a.fee_frac
    assert any(e[0] == "crypto_fee_in_kind" for e in v.logged), v.logged


def test_the_old_behaviour_would_have_overstated_this_row():
    """Names the bug in one assertion, so a regression reads as this bug."""
    over = float(XRP_GROSS) - float(XRP_ARRIVED)
    assert abs(over - float(XRP_FEE)) < 1e-9
    with FakeVenue(positions=[[_pos("XRP/USD", XRP_ARRIVED)]]):
        a = _arrived(qty_before=Decimal("0"))
    assert float(XRP_GROSS) - a.quantity > 0.05, (
        "the fix must move the booked size by the whole fee, not round it")


# ---------------------------------------------------------------------------
# 2. THE ADD -- a buy into a coin the book already holds
# ---------------------------------------------------------------------------


def test_add_to_existing_books_the_delta_not_the_snapshot():
    """The live shape: the wallet held dust before b0fe65b6, so the
    post-fill SNAPSHOT is not this fill's quantity. Working backwards from
    the observed 0.25%, the dust before that order was

        23.27479743 - 23.326114883 x 0.9975 = 0.0069978342075

    and the row must book the DELTA, not the 23.27479743 snapshot."""
    gross = Decimal(XRP_GROSS)
    before = Decimal(XRP_ARRIVED) - gross * Decimal("0.9975")
    after = Decimal(XRP_ARRIVED)
    assert before > 0, before
    with FakeVenue(positions=[[_pos("XRP/USD", str(after))]]):
        a = _arrived(qty_before=before)
    assert a.source == cs.FROM_ARRIVAL, a.reason
    expected = float(after - before)
    assert abs(a.quantity - expected) < 1e-12, (a.quantity, expected)
    assert a.quantity < float(after), (
        "booking the snapshot would fold the prior holding into this fill")
    # and that delta is the gross less exactly the 0.25% observed on 9/2
    assert abs(a.quantity - float(gross * Decimal("0.9975"))) < 1e-9, a.quantity


def test_a_big_prior_holding_is_not_absorbed():
    """DOGE shape from the primary book: 380.929087578 coins held, then a
    1008-coin buy (order 6ed71453). Booking the snapshot would put ~1389
    coins on a row that bought 1008."""
    before = Decimal("380.929087578")
    gross = Decimal("1008.053295855")
    after = before + gross * Decimal("0.9975")
    doge = {"id": "6ed71453", "symbol": "DOGE/USD", "asset_class": "crypto",
            "side": "buy", "qty": str(gross), "filled_qty": str(gross),
            "filled_avg_price": "0.089059", "status": "filled"}
    with FakeVenue(positions=[[_pos("DOGE/USD", str(after))]], order=doge):
        a = _arrived(symbol="DOGE", order_id="6ed71453",
                     submitted_qty=float(gross), qty_before=before)
    assert a.source == cs.FROM_ARRIVAL, a.reason
    assert abs(a.quantity - float(gross * Decimal("0.9975"))) < 1e-9, a.quantity
    assert a.quantity < float(after) - float(before) + 1e-9
    assert a.quantity < float(gross), "the fee was not taken off"


# ---------------------------------------------------------------------------
# 3. HOUSE RULE 3 -- a failed read is never a number
# ---------------------------------------------------------------------------


def test_failed_position_read_books_the_receipt_and_flags():
    """The wallet cannot be read after the fill. The row must be booked
    from the ORDER's filled quantity, be labelled as such, and be left for
    the inspector -- not zero, not an assumed 0.9975."""
    with FakeVenue(positions=[None]) as v:
        a = _arrived(qty_before=Decimal("0"))
    assert a.source == cs.FROM_RECEIPT, a.source
    assert a.settled is False
    assert f"{a.quantity:.9f}" == f"{float(XRP_GROSS):.9f}", a.quantity
    assert a.quantity > 0, "a failed read must never book a zero"
    assert any(e[0] == "crypto_arrival_unresolved" for e in v.logged), v.logged
    assert "qa_quantity_drift" in " ".join(e[2] for e in v.logged), (
        "the fallback must hand the row to the inspector, out loud")


def test_missing_pre_read_books_the_receipt_never_the_snapshot():
    """qty_before=None (the pre-order wallet read failed). The snapshot is
    NOT this fill's arrival, so it must not be booked -- and it must not
    be silently treated as a flat book either."""
    with FakeVenue(positions=[[_pos("XRP/USD", "999.0")]]) as v:
        a = _arrived(qty_before=None)
    assert a.source == cs.FROM_RECEIPT, a.source
    assert f"{a.quantity:.9f}" == f"{float(XRP_GROSS):.9f}", a.quantity
    assert a.quantity != 999.0
    assert v.pos_reads == 0, "no delta is possible; do not even look"


def test_failed_order_read_books_the_submitted_quantity():
    """Bottom rung: no receipt at all. Book what was asked for -- today's
    behaviour, unchanged -- and say so. Never a zero."""
    with FakeVenue(positions=[[_pos("XRP/USD", XRP_ARRIVED)]],
                   order_err="HTTP 429") as v:
        a = _arrived(qty_before=Decimal("0"))
    assert a.source == cs.FROM_REQUEST, a.source
    assert f"{a.quantity:.9f}" == f"{float(XRP_GROSS):.9f}", a.quantity
    assert "429" in a.reason, a.reason
    assert any(e[0] == "crypto_arrival_unresolved" for e in v.logged)


def test_a_flat_wallet_is_zero_and_a_failed_read_is_none():
    """position_qty must keep the two apart. Collapsing them is the
    2026-08-28 phantom-close loop in a new costume."""
    with FakeVenue(positions=[[]]):
        q, why = _run(cs.position_qty("XRP"))
    assert q == Decimal("0") and why == "", (q, why)
    with FakeVenue(positions=[None]):
        q, why = _run(cs.position_qty("XRP"))
    assert q is None and why, (q, why)
    # and a position whose qty is unreadable is ANSWERLESS, not zero
    with FakeVenue(positions=[[{"symbol": "XRP/USD", "asset_class": "crypto",
                                "qty": "not-a-number"}]]):
        q, why = _run(cs.position_qty("XRP"))
    assert q is None, q


def test_an_equity_with_a_coins_ticker_is_not_the_coin():
    """A stock called BTC must never be counted as the coin -- that would
    make the next BTC buy's delta the whole equity holding."""
    equity = {"symbol": "BTC", "asset_class": "us_equity", "qty": "500"}
    with FakeVenue(positions=[[equity]]):
        q, why = _run(cs.position_qty("BTC"))
    assert q == Decimal("0"), q
    coin = {"symbol": "BTC/USD", "asset_class": "crypto", "qty": "0.5"}
    with FakeVenue(positions=[[equity, coin]]):
        q, why = _run(cs.position_qty("BTC"))
    assert q == Decimal("0.5"), q


def test_an_implausible_delta_is_refused_not_booked():
    """A stop firing between the two reads moves the wallet by a whole
    position. That is not a fee and must never be booked as this fill."""
    with FakeVenue(positions=[[_pos("XRP/USD", "1.0")]]) as v:
        a = _arrived(qty_before=Decimal("0"))
    assert a.source == cs.FROM_RECEIPT, a.source
    assert f"{a.quantity:.9f}" == f"{float(XRP_GROSS):.9f}"
    assert "band" in a.reason, a.reason
    # ...and a wallet that GREW by more than was bought is refused too:
    # a buy can never deliver more coin than it filled.
    with FakeVenue(positions=[[_pos("XRP/USD", "40.0")]]):
        a = _arrived(qty_before=Decimal("0"))
    assert a.source == cs.FROM_RECEIPT, a.source


def test_the_band_is_not_a_hidden_fee_rate():
    """0.9975 must appear nowhere as an assumption: a fee twice the
    observed rate is still accepted, because the number comes from the
    wallet and not from the code."""
    gross = Decimal(XRP_GROSS)
    for rate in ("0.0025", "0.005", "0.009"):
        after = gross * (Decimal(1) - Decimal(rate))
        with FakeVenue(positions=[[_pos("XRP/USD", str(after))]]):
            a = _arrived(qty_before=Decimal("0"))
        assert a.source == cs.FROM_ARRIVAL, (rate, a.reason)
        assert abs(a.fee_frac - float(rate)) < 1e-9, (rate, a.fee_frac)


# ---------------------------------------------------------------------------
# 4. AN ORDER STILL WORKING -- do not under-book a partial
# ---------------------------------------------------------------------------


def test_a_partially_filled_order_is_waited_for_not_booked():
    """DOT 2ba3e5d6 partial-filled 800 of 888 and completed 50ms later.
    Booking the partial under-books the row by 88 coins -- the mirror of
    the bug. Non-terminal means look again."""
    working = dict(XRP_ORDER, status="partially_filled",
                   filled_qty="10.0", qty=XRP_GROSS)
    with FakeVenue(positions=[[_pos("XRP/USD", XRP_ARRIVED)]],
                   order=working) as v:
        a = _arrived(qty_before=Decimal("0"))
    assert a.source == cs.FROM_REQUEST, a.source
    assert a.quantity == float(XRP_GROSS), a.quantity
    assert a.quantity != 10.0, "a partial fill must not become the row"
    assert v.order_reads == cs.settle_attempts(), v.order_reads
    assert v.sleeps == cs.settle_attempts() - 1, v.sleeps


def test_it_retries_until_the_wallet_settles():
    """The first wallet read comes back pre-settlement; the second has the
    coin. The retry is what makes rung 1 reachable in production."""
    with FakeVenue(positions=[[], [_pos("XRP/USD", XRP_ARRIVED)]]) as v:
        a = _arrived(qty_before=Decimal("0"))
    assert a.source == cs.FROM_ARRIVAL, a.reason
    assert v.pos_reads == 2, v.pos_reads
    assert v.sleeps == 1, v.sleeps


# ---------------------------------------------------------------------------
# 5. WHAT MUST NOT CHANGE -- sells, stocks, options
# ---------------------------------------------------------------------------


def test_the_executor_adjusts_buys_only():
    """A SELL must not be adjusted. The evidence says the shortfall is on
    buys alone, and Alpaca does not permit crypto shorts anyway."""
    src = (Path(__file__).resolve().parents[1]
           / "app" / "agents" / "trade_execution.py").read_text(encoding="utf-8")
    i = src.index("async def _execute_alpaca_crypto")
    body = src[i:i + 14000]
    assert 'if order_side == "buy":' in body, (
        "the arrival adjustment must be gated on the BUY side")
    j = body.index('if order_side == "buy":')
    k = body.index("arrived_buy_quantity")
    assert j < k, "arrived_buy_quantity is reached outside the buy gate"
    assert "quantity=_book_qty" in body, (
        "record_external_position must receive the booked arrival")
    assert "quantity=plan.quantity" not in body, (
        "the crypto row is still booking the requested quantity")


def test_the_stock_paths_are_untouched():
    """Equities are commission-free at Alpaca. Measured over 720h on the
    primary book: AMZN 3 bought - 1 sold = 2 held, XLE 17 - 5 = 12, GOOG
    1 - 0 = 1, exactly. Nothing to correct, so nothing may be applied."""
    src = (Path(__file__).resolve().parents[1]
           / "app" / "agents" / "trade_execution.py").read_text(encoding="utf-8")
    ci = src.index("async def _execute_alpaca_crypto")
    outside = src[:ci]
    assert "arrived_buy_quantity" not in outside, (
        "the crypto arrival fix leaked into a stock/option path")
    assert 'asset_type="stock"' in outside
    assert src.count("arrived_buy_quantity") == 1, (
        "exactly one call site: the crypto buy")


def test_a_sell_side_call_is_a_no_op_by_construction():
    """Belt and braces: even if something did call it for a sell, the
    delta would be negative and the module refuses rather than booking a
    negative or a zero quantity."""
    with FakeVenue(positions=[[_pos("XRP/USD", "1.0")]]):
        a = _arrived(qty_before=Decimal("24.0"))
    assert a.quantity > 0, a.quantity
    assert a.source != cs.FROM_ARRIVAL, "a shrinking wallet is not an arrival"


# ---------------------------------------------------------------------------
# 6. WIRING AND SHARED RULES
# ---------------------------------------------------------------------------


def test_symbol_normalisation_agrees_with_the_broker_module():
    """_base must be alpaca._crypto_base's rule. Two spellings of one coin
    is how the ledger grew duplicate rows before."""
    for s in ("XRP", "xrp", "XRP/USD", "XRPUSD", "BTC/USD", "DOGEUSD",
              "ETH", " sol/usd "):
        assert cs._base(s) == alp._crypto_base(s), s


def test_the_pre_order_wallet_read_happens_before_the_order():
    """A delta needs a BEFORE. If the read moved after submit_crypto_order
    the module would be measuring the wrong interval."""
    src = (Path(__file__).resolve().parents[1]
           / "app" / "agents" / "trade_execution.py").read_text(encoding="utf-8")
    i = src.index("async def _execute_alpaca_crypto")
    body = src[i:i + 14000]
    before = body.index("crypto_settle.position_qty")
    submit = body.index("order, err = await submit_crypto_order")
    after = body.index("arrived_buy_quantity")
    assert before < submit < after, (before, submit, after)


def test_a_failed_pre_read_is_reported_not_swallowed():
    src = (Path(__file__).resolve().parents[1]
           / "app" / "agents" / "trade_execution.py").read_text(encoding="utf-8")
    assert "crypto_prefill_read_failed" in src
    assert "if _qty_before is None:" in src


def test_the_knobs_are_read_at_call_time():
    """Captured-at-import knobs cannot be changed without a restart, and a
    test that sets one would silently do nothing."""
    old = os.environ.get("TREZO_CRYPTO_MAX_FEE_PCT")
    try:
        os.environ["TREZO_CRYPTO_MAX_FEE_PCT"] = "0.02"
        assert cs.max_fee_frac() == 0.02
        os.environ["TREZO_CRYPTO_MAX_FEE_PCT"] = "nonsense"
        assert cs.max_fee_frac() == 0.01, "a bad value must fall back, not raise"
        os.environ["TREZO_CRYPTO_MAX_FEE_PCT"] = "0.9"
        assert cs.max_fee_frac() == 0.01, "an absurd band must be refused"
    finally:
        if old is None:
            os.environ.pop("TREZO_CRYPTO_MAX_FEE_PCT", None)
        else:
            os.environ["TREZO_CRYPTO_MAX_FEE_PCT"] = old


def test_the_qa_inspector_still_owns_the_existing_rows():
    """This fix is for NEW rows. The already-open overstated rows are the
    inspector's A3 correction, and its autofix must stay OFF by default --
    that is Mike's call, not the executor's."""
    qa = load_module("app.paper.trade_qa")
    old = os.environ.get("TREZO_QA_AUTOFIX")
    try:
        os.environ.pop("TREZO_QA_AUTOFIX", None)
        assert qa.autofix_on() is False, "autofix must ship OFF"
    finally:
        if old is not None:
            os.environ["TREZO_QA_AUTOFIX"] = old
    # the 0.22% XRP drift is far outside the crypto tolerance, so A3 sees it
    assert qa._qty_matches(float(XRP_GROSS), float(XRP_ARRIVED),
                           "crypto") is False
    # ...and an equity round number still matches itself
    assert qa._qty_matches(12.0, 12.0, "stock") is True



# --- REVIEW 2026-09-03: a delta is not evidence that OUR order caused it ---
# The band accepted any wallet movement inside it as this fill's arrival.
# Driven against the real executor, an unrelated same-coin credit of 23.30
# while our order filled 23.326114883 was booked as ours, stamped
# qty_source="arrival", and logged a commission rate of 0.1120% that never
# happened. Another fill's size written as settled fact is the house-rule-6
# edge, so the arrival now also requires ours to be the only fill.

def _rival(order_id="rival-1", qty="5", filled_at="2026-09-03T01:41:00Z"):
    return {"id": order_id, "symbol": "XRP/USD", "side": "buy",
            "filled_qty": qty, "filled_at": filled_at, "status": "filled"}


def test_a_rival_fill_in_the_window_refuses_the_arrival():
    """The exact case the reviewer drove: someone else's credit must not be
    booked as ours, however plausible its size looks."""
    with FakeVenue(positions=[[_pos("XRP/USD", XRP_ARRIVED)]],
                   closed_orders=[_rival()]) as v:
        a = _arrived(qty_before=Decimal("0"))
    assert a.source == cs.FROM_RECEIPT, f"booked {a.source}, not the receipt"
    assert f"{a.quantity:.9f}" == f"{float(XRP_GROSS):.9f}", a.quantity
    assert "another order" in (a.reason or ""), a.reason
    assert not any(e[0] == "crypto_fee_in_kind" for e in v.logged), (
        "a commission was reported for a fill we cannot prove was ours")


def test_an_unfilled_rival_order_does_not_block_the_arrival():
    """Only a FILL can move the wallet. A resting order must not demote us."""
    resting = _rival(order_id="resting-1", qty="0", filled_at=None)
    with FakeVenue(positions=[[_pos("XRP/USD", XRP_ARRIVED)]],
                   closed_orders=[resting]) as v:
        a = _arrived(qty_before=Decimal("0"))
    assert a.source == cs.FROM_ARRIVAL, f"fell back to {a.source}: {a.reason}"
    assert any(e[0] == "crypto_fee_in_kind" for e in v.logged), v.logged


def test_our_own_order_is_not_mistaken_for_a_rival():
    """The exclusivity check must skip OUR id, or nothing ever settles."""
    ours = _rival(order_id=XRP_ORDER_ID, qty=str(XRP_GROSS))
    with FakeVenue(positions=[[_pos("XRP/USD", XRP_ARRIVED)]],
                   closed_orders=[ours]):
        a = _arrived(qty_before=Decimal("0"))
    assert a.source == cs.FROM_ARRIVAL, f"fell back to {a.source}: {a.reason}"


def test_an_unanswerable_exclusivity_check_drops_a_rung():
    """Cannot check is not permission -- house rule 3, again."""
    with FakeVenue(positions=[[_pos("XRP/USD", XRP_ARRIVED)]],
                   closed_raises=True) as v:
        a = _arrived(qty_before=Decimal("0"))
    assert a.source == cs.FROM_RECEIPT, a.source
    assert "could not check" in (a.reason or ""), a.reason
    assert not any(e[0] == "crypto_fee_in_kind" for e in v.logged)


def test_the_band_is_a_sanity_bound_not_a_fee_rate():
    """It must stay well clear of the observed tiers. Tightening it toward
    them would mean a tier change silently reintroduces the bug; the guard
    against a foreign credit is the exclusivity check, not the width."""
    band = cs.max_fee_frac()
    assert band >= 0.008, (band, "too tight: a tier change would demote every entry")

if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
