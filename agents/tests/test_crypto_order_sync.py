"""Guard tests: the venue's stop must FOLLOW the ledger's stop.

Why these exist (2026-08-20). Mike, on the dashboard: "the stop limit
was 1.04 and the current price was 1.21... I have to manually adjust
them." He was right. The ledger's trail had ratcheted XRP's lock to
1.147 -- and the venue copy had fossilized at its first level, because
open_crypto_orders() queried Alpaca with symbols=XRPUSD while the venue
files crypto orders under XRP/USD. The filter matched nothing, every
caller read the empty list as "nothing resting", tried to place a
FRESH stop, and the invisible old order rejected it: HTTP 403
insufficient balance, every tick, all morning. The function's own
docstring warned that an empty answer meaning "wrong question" is the
most dangerous value in the system -- then asked the wrong question.

The fix stops asking the venue to filter at all: fetch every open
order, match client-side by normalized base. XRP == XRP/USD == XRPUSD.

Run: python -m agents.tests.test_crypto_order_sync   (or pytest)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
# Pre-stub app.runtime so alpaca's lazy `from app.runtime.asset_policy
# import ...` doesn't trigger the real app/runtime/__init__.py, which
# drags in apscheduler (absent in a bare checkout).
ap = load_module("app.runtime.asset_policy")
alp = load_module("app.brokers.alpaca")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---- fake venue -----------------------------------------------------------

class FakeVenue:
    """Stub _get/_post/_delete/replace_order and record every call."""

    def __init__(self, open_orders):
        self.open_orders = list(open_orders)
        self.posts, self.deletes, self.replaces = [], [], []
        self.post_err = None

    def install(self):
        self._real = (alp._get, alp._post, alp._delete, alp.replace_order)

        async def fake_get(path, **kw):
            assert "symbols=" not in path, (
                "the fix forbids venue-side symbol filters: " + path)
            return self.open_orders
        async def fake_post(path, body, **kw):
            self.posts.append(body)
            return (None, self.post_err) if self.post_err else ({"id": "new"}, None)
        async def fake_delete(path, **kw):
            self.deletes.append(path)
            return {}, None
        async def fake_replace(order_id, **kw):
            self.replaces.append((order_id, kw))
            return {"id": "replaced"}, None

        alp._get, alp._post, alp._delete = fake_get, fake_post, fake_delete
        alp.replace_order = fake_replace

    def restore(self):
        alp._get, alp._post, alp._delete, alp.replace_order = self._real


SLASHED_STOP = {"id": "o1", "symbol": "XRP/USD", "side": "sell",
                "type": "stop_limit", "stop_price": "1.04", "qty": "500"}


def test_a_slashed_venue_symbol_is_still_our_order():
    """The bug in one assertion: an order filed as XRP/USD must be found
    when we ask about XRP. This is Mike's 1.04 stop."""
    v = FakeVenue([SLASHED_STOP]); v.install()
    try:
        found = _run(alp.open_crypto_orders("XRP"))
    finally:
        v.restore()
    assert found and found[0]["id"] == "o1", (
        f"XRP/USD order invisible to open_crypto_orders('XRP'): {found}")


def test_other_coins_orders_do_not_leak_in():
    """Base matching must not become 'return everything'."""
    v = FakeVenue([SLASHED_STOP,
                   {"id": "o2", "symbol": "BTC/USD", "side": "sell",
                    "type": "stop_limit", "stop_price": "70000"}])
    v.install()
    try:
        found = _run(alp.open_crypto_orders("XRP"))
    finally:
        v.restore()
    assert [o["id"] for o in found] == ["o1"]


def test_the_ratchet_now_moves_the_stale_stop_instead_of_colliding():
    """End-to-end shape of Mike's morning: ledger says 1.147, venue holds
    1.04 under XRP/USD. Before the fix: place-new -> 403 loop. After: the
    leg is FOUND and replaced upward. No new order, no collision."""
    v = FakeVenue([SLASHED_STOP]); v.install()
    try:
        changed, note = _run(alp.ratchet_crypto_stop("XRP", 1.147, qty=500))
    finally:
        v.restore()
    assert changed, note
    assert v.replaces and v.replaces[0][0] == "o1", (
        f"expected a replace of o1, got replaces={v.replaces} posts={v.posts}")
    assert not v.posts, "should amend in place, not place a fresh order"


def test_a_ratchet_below_the_resting_stop_is_refused():
    """Never down -- including now that we can actually SEE the leg."""
    v = FakeVenue([SLASHED_STOP]); v.install()
    try:
        changed, note = _run(alp.ratchet_crypto_stop("XRP", 1.01, qty=500))
    finally:
        v.restore()
    assert not changed and "already" in note
    assert not v.replaces and not v.posts


def test_a_hand_placed_sell_is_cleared_when_it_blocks_the_stop():
    """Mike edits orders from the dashboard; a sell we did not place can
    hold the units. Stop wins over ALL resting sells: after the target
    is freed and the venue still says no, clear the rest and retry."""
    foreign = {"id": "x9", "symbol": "XRP/USD", "side": "sell",
               "type": "market", "qty": "500"}   # shape we never place
    v = FakeVenue([foreign]); v.install()
    v.post_err = "HTTP 403: insufficient balance"

    real_post = alp._post
    calls = {"n": 0}
    async def flaky_post(path, body, **kw):
        calls["n"] += 1
        if calls["n"] >= 2:      # succeeds once the foreign sell is gone
            v.post_err = None
        return await real_post(path, body, **kw)
    alp._post = flaky_post
    try:
        changed, note = _run(alp.ratchet_crypto_stop("XRP", 1.147, qty=500))
    finally:
        alp._post = real_post
        v.restore()
    assert changed, note
    assert any("x9" in d for d in v.deletes), (
        f"foreign sell not cleared: deletes={v.deletes}")


# ---- the QYLD fractional fix ----------------------------------------------

def test_fractional_equity_protection_goes_day_not_gtc():
    """QYLD, 2026-08-20: Alpaca refuses GTC on fractional equity orders,
    so a fractional position's protection 422'd every tick and the
    position sat naked. Fractional -> DAY; whole shares keep GTC."""
    assert alp._equity_sell_tif(74.5045) == "day"
    assert alp._equity_sell_tif(74.0) == "gtc"
    assert alp._equity_sell_tif(1) == "gtc"


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
