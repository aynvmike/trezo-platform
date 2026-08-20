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
         ("get_open_orders_for", "get_all_open_orders", "replace_order",
          "_post", "_delete")}


def _reset():
    for n, fn in _REAL.items():
        setattr(alp, n, fn)


def _run(coro):
    # Close the loop each time: leaking one per call makes CPython spew
    # a GC traceback AFTER the results print, which reads like a failure
    # in a suite that passed.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _orders(rows):
    """Feed the venue's open-order list. Since 2026-08-20 crypto reads
    ALL open orders and matches by base client-side, so rows given here
    should carry venue-shaped symbols (XRP/USD) to stay honest."""
    asked = []

    async def _all():
        asked.append("*all*")
        return list(rows)
    async def _f(symbol):
        asked.append(symbol)
        return list(rows)
    alp.get_all_open_orders = _all
    alp.get_open_orders_for = _f
    return asked


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


# Venue-shaped: real orders come back with the slashed pair symbol, and
# since 2026-08-20 the matcher keys on it. A fixture without a symbol is
# a fixture for the bug.
TP = {"id": "tp-1", "symbol": "XRP/USD", "type": "limit", "side": "sell",
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

    async def _none(symbol=None):
        return None
    alp.get_open_orders_for = _none
    alp.get_all_open_orders = _none
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


def test_a_coin_is_never_asked_about_through_a_symbol_filter():
    """REWRITTEN 2026-08-20, and the old version of this test is the
    lesson: it asserted that crypto queried the venue with
    symbols=XRPUSD -- pinning the exact bug that froze Mike's stops.
    The venue files the order under XRP/USD, the XRPUSD filter matched
    nothing, every caller read [] as "nothing resting", and each push
    became a fresh placement that 403'd against the invisible old order.
    A test can encode a wrong belief as confidently as a right one; this
    one did, with a docstring that described the trap while asserting we
    walk into it. Crypto now reads ALL open orders and matches by base
    client-side."""
    _reset()
    asked = _orders([])
    _capture()
    _run(alp.ensure_crypto_take_profit("XRP", 714.7, 1.20))
    _run(alp.cancel_crypto_take_profit("XRP"))
    assert asked and all(a == "*all*" for a in asked), asked


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

    async def _none(symbol=None):
        return None
    alp.get_open_orders_for = _none
    alp.get_all_open_orders = _none
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


# --- the resting STOP, which is the half that actually protects --------
# Corrected 2026-08-18. This file used to encode "Alpaca holds no stop
# for crypto" as settled fact. It holds no *stop* and no bracket -- but
# a stop_limit rests fine on gtc, and Mike had one on BTCUSD at 65,000
# while the code was insisting otherwise. Alpaca's docs: crypto gets
# market/limit (gtc, ioc) and stop_limit (gtc only).

STOP_LEG = {"id": "sl-1", "symbol": "BTC/USD", "type": "stop_limit",
            "side": "sell", "stop_price": "60000.00",
            "limit_price": "59700.00", "qty": "0.1"}


def test_a_crypto_stop_is_sent_as_the_only_type_the_venue_takes():
    _reset()
    _orders([])
    posted, _d, _r = _capture()
    changed, note = _run(alp.ratchet_crypto_stop(
        "BTCUSD", 60000.0, qty=0.1, offset_profile="balanced"))
    assert changed is True, note
    body = posted[0][1]
    assert body["type"] == "stop_limit", (
        "a plain stop is rejected for crypto -- it is equities-only")
    assert body["time_in_force"] == "gtc", "crypto stop_limit is gtc-only"
    assert body["symbol"] == "BTC/USD"
    assert float(body["stop_price"]) == 60000.0
    assert float(body["limit_price"]) == 59700.0, (
        "the limit must sit UNDER the stop or it cannot fill on the way down")


def test_a_crypto_stop_is_never_moved_down():
    """The invariant the whole trail rests on. A stop that fails to
    tighten costs upside; one that loosens costs the position."""
    _reset()
    _orders([STOP_LEG])
    posted, deleted, replaced = _capture()
    changed, note = _run(alp.ratchet_crypto_stop("BTCUSD", 55000.0, qty=0.1))
    assert changed is False
    assert not posted and not deleted and not replaced
    assert "already at" in note


def test_a_crypto_stop_ratchets_up_in_place():
    """This is the trailing stop: as the ladder walks the stop up, the
    lock-in walks up AT THE VENUE, so a good run stays banked even if
    the engine is not running."""
    _reset()
    _orders([STOP_LEG])
    posted, _deleted, replaced = _capture()
    changed, _ = _run(alp.ratchet_crypto_stop(
        "BTCUSD", 63000.0, qty=0.1, offset_profile="balanced"))
    assert changed is True
    assert len(replaced) == 1 and replaced[0][0] == "sl-1"
    assert replaced[0][1]["stop_price"] == 63000.0
    assert abs(replaced[0][1]["limit_price"] - 62685.0) < 1e-6
    assert not posted, "amending must not also place a second stop"


def test_a_refused_amend_re_places_the_stop_rather_than_dropping_it():
    """Unlike a target, a stop may not simply be abandoned. If even the
    re-place fails the note has to SAY the position is unprotected."""
    _reset()
    _orders([STOP_LEG])
    posted, deleted, _r = _capture()

    async def _refuse(order_id, **kw):
        return None, "HTTP 422: order cannot be replaced"
    alp.replace_order = _refuse

    changed, _ = _run(alp.ratchet_crypto_stop("BTCUSD", 63000.0, qty=0.1))
    assert changed is True
    assert deleted == ["/v2/orders/sl-1"]
    assert posted and posted[0][1]["type"] == "stop_limit"

    # ...and when the re-place ALSO fails, say so loudly.
    _reset()
    _orders([STOP_LEG])
    alp.replace_order = _refuse

    async def _no(path, body, token=None):
        return None, "HTTP 403: insufficient balance"

    async def _del(path, token=None):
        return {}, None
    alp._post, alp._delete = _no, _del
    changed2, note2 = _run(alp.ratchet_crypto_stop("BTCUSD", 63000.0, qty=0.1))
    assert changed2 is False
    assert "STOP IS GONE" in note2, note2


def test_a_resting_target_does_not_block_the_stop():
    """The live hazard on 2026-08-19, caught before restarting onto this
    code. The previous build rested crypto take-profits by default; this
    one stands them down -- but standing down only stops NEW ones. The
    orders already at the venue keep holding the coins, so with no OCO
    every stop placement is rejected for insufficient balance, on
    precisely the rows we are adding stops to protect.

    Stop wins: cancel the target, place the stop, and SAY the target
    went. Losing upside is the price of having a floor; it should be
    visible in the note, not silent."""
    _reset()
    _orders([TP])                      # a target rests; no stop leg
    posted, deleted, _r = _capture()

    calls = {"n": 0}

    async def _post(path, body, token=None):
        calls["n"] += 1
        posted.append((path, body))
        if calls["n"] == 1:
            return None, "HTTP 403: insufficient balance for XRP"
        return {"id": "sl-new"}, None
    alp._post = _post

    changed, note = _run(alp.ratchet_crypto_stop("XRPUSD", 0.9, qty=714.7))
    assert changed is True, note
    assert deleted == ["/v2/orders/tp-1"], "the target must be released"
    assert len(posted) == 2, "and the stop retried once it is free"
    assert posted[1][1]["type"] == "stop_limit"
    assert "cancelled the resting target" in note, (
        "a silently sacrificed target is how you find out weeks later")


def test_a_stop_that_cannot_be_placed_at_all_says_so_plainly():
    _reset()
    _orders([TP])
    _p, _d, _r = _capture()

    async def _never(path, body, token=None):
        return None, "HTTP 403: insufficient balance"
    alp._post = _never

    changed, note = _run(alp.ratchet_crypto_stop("XRPUSD", 0.9, qty=714.7))
    assert changed is False
    # Wording shifted 2026-08-20 when the clear-every-sell fallback went
    # in; what must survive is that the note says the target WAS freed
    # and it still failed -- not a bare venue error.
    assert "could not place crypto stop" in note and "freeing the target" in note, note


def test_releasing_units_clears_the_stop_and_the_target_together():
    """No OCO means they are two independent orders reserving the same
    coins. Cancelling one leaves the other holding them, and the sell
    that follows gets an insufficient-balance reject."""
    _reset()
    btc_tp = dict(TP, symbol="BTC/USD")   # TP fixture is XRP; this test is BTC
    _orders([STOP_LEG, btc_tp,
             {"id": "buy-9", "symbol": "BTC/USD", "type": "limit",
              "side": "buy", "limit_price": "50000", "qty": "0.1"}])
    _p, deleted, _r = _capture()
    n, err = _run(alp.cancel_crypto_exits("BTCUSD"))
    assert err is None and n == 2
    assert set(deleted) == {"/v2/orders/sl-1", "/v2/orders/tp-1"}
    assert "/v2/orders/buy-9" not in deleted, (
        "cancelling a resting BUY would silently abandon an entry")


def test_the_offset_scale_is_the_one_mike_named():
    _reset()
    from importlib import import_module  # noqa: F401
    assert round(ap.stop_limit_offset("conservative"), 5) == 0.0015
    assert round(ap.stop_limit_offset("balanced"), 5) == 0.0050
    assert round(ap.stop_limit_offset("aggressive"), 5) == 0.0075
    assert round(ap.stop_limit_offset("tolerant"), 5) == 0.0100
    assert round(ap.stop_limit_offset("high"), 5) == 0.0150
    # bot_settings speaks risk_profile; it maps rather than duplicating.
    assert ap.stop_limit_offset("expert") == ap.stop_limit_offset("balanced")
    # Never zero. A limit AT the stop is the one setting guaranteed to
    # miss in the fast market a stop exists for.
    assert ap.stop_limit_offset("nonsense") > 0


def test_a_coin_that_is_not_trailing_still_gets_a_stop():
    """The gap found on 2026-08-19, minutes after shipping the feature.

    Mirroring a crypto stop happened ONLY from the three ratchet sites,
    which fire when a stop moves UP. A coin sitting still never called
    them, so it never got a venue-side stop at all -- the feature
    protected exactly the positions already doing well and nothing else.
    Five live coins had no broker stop while the log looked healthy.

    Arming must therefore place at the CURRENT ledger stop, with no
    ratchet required. ratchet_crypto_stop does that when no leg rests,
    which is why it is the arming call too."""
    _reset()
    _orders([])                        # nothing resting: the naked case
    posted, _d, _r = _capture()
    changed, note = _run(alp.ratchet_crypto_stop(
        "LINKUSD", 9.4, qty=133.7, offset_profile="balanced"))
    assert changed is True, note
    assert len(posted) == 1
    assert posted[0][1]["type"] == "stop_limit"
    assert float(posted[0][1]["stop_price"]) == 9.4, (
        "arming places at the ledger stop -- it must not wait for a ratchet")


def test_the_policy_names_the_order_type_each_venue_takes():
    _reset()
    assert ap.policy_for("crypto").stop_order_type == "stop_limit"
    assert ap.policy_for("stock").stop_order_type == "stop"
    assert ap.policy_for("crypto").holds_stop is True, (
        "this was False until 8/18 and it was costing real protection")
    # Fails CLOSED: a venue we have not confirmed must not be assumed.
    assert ap.policy_for("option").holds_stop is False
    assert ap.policy_for("nonsense-class").holds_stop is False


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
