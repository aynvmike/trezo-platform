"""Guard tests: the resting crypto take-profit, and the units it holds.

Why (2026-08-18): Alpaca gives crypto no bracket and no stop order, so a
coin's stop AND target both lived only in our ledger, enforced by the
monitor watching the tape. On 8/17 the monitor stopped watching for
fifteen hours. The stop half still cannot be fixed -- the venue has no
crypto stop. The target half can: a resting GTC limit sell fills whether
or not this process is alive.

The new hazard is the flip side of the same fact: a resting sell RESERVES
the units, so every other crypto sell path now has to release them first.
Half of what is below guards the placement; the other half guards that
release, because a partial that cannot sell is a profit step that never
takes profit.

Run: python -m agents.tests.test_crypto_tp   (or pytest)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()          # alpaca.py reads settings at import
alp = load_module("app.brokers.alpaca")
ap = load_module("app.runtime.asset_policy")

_REAL = {n: getattr(alp, n) for n in
         ("get_open_orders_for", "replace_order", "_post", "_delete")}


def _reset():
    for n, fn in _REAL.items():
        setattr(alp, n, fn)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _orders(rows):
    async def _f(symbol):
        return list(rows)
    alp.get_open_orders_for = _f


def _capture():
    posted, deleted, replaced = [], [], []

    async def _p(path, body, token=None):
        posted.append((path, body))
        return {"id": "new"}, None

    async def _d(path, token=None):
        deleted.append(path)
        return {}, None

    async def _r(order_id, **kw):
        replaced.append((order_id, kw))
        return {"id": "amended"}, None

    alp._post, alp._delete, alp.replace_order = _p, _d, _r
    return posted, deleted, replaced


TP = {"id": "tp-1", "type": "limit", "side": "sell",
      "limit_price": "1.2000", "qty": "714.7"}


# --- placing and moving the target ---------------------------------------

def test_a_naked_coin_gets_a_resting_target():
    _reset()
    _orders([])
    posted, _d, _r = _capture()
    changed, note = _run(alp.ensure_crypto_take_profit("XRPUSD", 714.7, 1.20))
    assert changed is True, note
    assert len(posted) == 1
    _path, body = posted[0]
    assert body["side"] == "sell" and body["type"] == "limit"
    assert body["time_in_force"] == "gtc", (
        "a day order on a 24/7 venue is rejected, and worse, silently "
        "leaves the coin with no target overnight")
    assert body["symbol"] == "XRP/USD", "crypto is addressed as a pair"
    assert float(body["limit_price"]) == 1.20


def test_an_unchanged_target_is_not_rewritten():
    """Re-sending the same order every tick would churn the venue and
    burn rate limit for nothing."""
    _reset()
    _orders([TP])
    posted, deleted, replaced = _capture()
    changed, _ = _run(alp.ensure_crypto_take_profit("XRPUSD", 714.7, 1.20))
    assert changed is False
    assert not posted and not deleted and not replaced


def test_a_moved_target_is_amended_in_place():
    _reset()
    _orders([TP])
    posted, deleted, replaced = _capture()
    changed, _ = _run(alp.ensure_crypto_take_profit("XRPUSD", 714.7, 1.31))
    assert changed is True
    assert len(replaced) == 1 and replaced[0][0] == "tp-1"
    assert abs(replaced[0][1]["limit_price"] - 1.31) < 1e-9
    assert not posted, "amending must not ALSO place a second order"


def test_a_refused_amend_falls_back_to_cancel_and_place():
    """Unlike a stop, a target that briefly does not exist risks nothing
    -- so if the venue will not amend, replace it the blunt way rather
    than leaving the coin with a stale number."""
    _reset()
    _orders([TP])
    posted, deleted, _r = _capture()

    async def _refuse(order_id, **kw):
        return None, "HTTP 422: crypto orders cannot be replaced"
    alp.replace_order = _refuse

    changed, note = _run(alp.ensure_crypto_take_profit("XRPUSD", 714.7, 1.31))
    assert changed is True, note
    assert deleted == ["/v2/orders/tp-1"], "the stale order must be cancelled"
    assert len(posted) == 1 and float(posted[0][1]["limit_price"]) == 1.31


def test_a_failed_order_read_places_nothing():
    """None means 'could not check'. Placing anyway is how you end up
    with two resting sells for one position."""
    _reset()

    async def _none(symbol):
        return None
    alp.get_open_orders_for = _none
    posted, deleted, replaced = _capture()
    changed, note = _run(alp.ensure_crypto_take_profit("XRPUSD", 714.7, 1.31))
    assert changed is False
    assert not posted and not deleted and not replaced
    assert "could not read" in note


def test_every_spelling_of_a_coin_reaches_the_same_venue_symbol():
    """Found writing these: rows hold BOTH 'XRP' (our entries) and
    'XRPUSD' (adoption, which reads the broker's naming), and the pair
    helper only handled the bare form -- 'XRPUSD' became 'XRPUSD/USD'.
    That symbol exists nowhere, so liquidate_position() 404s and a
    stopped-out coin stays open and keeps falling."""
    _reset()
    for spelling in ("XRP", "XRPUSD", "XRP/USD"):
        assert alp._crypto_pair(spelling) == "XRP/USD", spelling
    assert alp._crypto_pair("USDCUSD") == "USDC/USD", (
        "a coin whose own name ends in USD must not be truncated twice")
    assert alp._crypto_pair("USDT") == "USDT/USD"


def test_a_resting_buy_is_not_mistaken_for_our_target():
    _reset()
    assert alp._is_sell_limit(TP) is True
    assert alp._is_sell_limit(
        {"type": "limit", "side": "buy", "limit_price": "1.0"}) is False
    assert alp._is_sell_limit(
        {"type": "market", "side": "sell"}) is False


# --- releasing the units it reserves --------------------------------------

def test_cancelling_reports_a_failed_listing_rather_than_zero():
    """The caller is about to sell. It must be able to tell 'nothing was
    resting' apart from 'I could not find out' -- returning 0 for both
    is how a sell walks into an insufficient-balance reject."""
    _reset()

    async def _none(symbol):
        return None
    alp.get_open_orders_for = _none
    n, err = _run(alp.cancel_crypto_take_profit("XRPUSD"))
    assert n == 0 and err, "a failed listing must surface as an error"


def test_cancelling_releases_only_our_sell():
    _reset()
    _orders([TP, {"id": "buy-9", "type": "limit", "side": "buy",
                  "limit_price": "0.90", "qty": "100"}])
    _p, deleted, _r = _capture()
    n, err = _run(alp.cancel_crypto_take_profit("XRPUSD"))
    assert err is None and n == 1
    assert deleted == ["/v2/orders/tp-1"], (
        "cancelling a resting BUY would silently abandon an entry")


def test_the_policy_tells_sell_paths_to_release_first():
    """This flag is the only thing standing between a resting TP and a
    partial sell that gets rejected for insufficient balance."""
    _reset()
    assert ap.policy_for("crypto").resting_exits is True
    assert ap.policy_for("crypto").holds_orders is True
    assert ap.policy_for("stock").resting_exits is False
    assert ap.policy_for("stock").holds_orders is True, (
        "stocks rest bracket legs, which must be cancelled too")
    assert ap.policy_for("bond").holds_orders is False


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
