"""Guards for two broker-read findings from the 2026-09-01 audit.

OG-9 / PM-4 / G2 / G1 -- the option lane's phantom close. The Wheel
reconciler and the options scanner asked get_option_positions() what
the broker held and got [] on a 429/timeout, indistinguishable from a
flat account, then settled and closed modeled rows the broker was still
holding. This is the same asymmetry test_broker_read_strict.py pins for
equities: an answerless read must never be readable as an answer.

SY-02 -- the crypto forced exit that never fired. liquidate_position's
pre-cancel probe asked GET /v2/orders?symbols=DOTUSD (the POSITIONS
spelling) while Alpaca files crypto orders under DOT/USD. The filter
matched nothing, the resting stop-limit kept the units reserved, and
every DELETE /v2/positions/DOTUSD 403'd "available: 0". The fix routes
crypto through the base-matched helpers (open_crypto_orders /
cancel_crypto_exits) that already learned this lesson on 8/20.

Deliberately dependency-free (no pytest, no .env, no network) so the
deploy guard can run them in a bare checkout. Only the HTTP seams
(_get/_delete/_post) and the upstream strict read are stubbed; the code
under test is the real module.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
alp = load_module("app.brokers.alpaca")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and always put the originals back."""
    old = {k: getattr(mod, k, None) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                if hasattr(mod, k):
                    delattr(mod, k)
            else:
                setattr(mod, k, v)


_OPT_ROW = {"symbol": "AAPL260918C00200000", "asset_class": "us_option",
            "qty": "-1"}
_EQ_ROW = {"symbol": "AAPL", "asset_class": "us_equity", "qty": "10"}


# --- OG-9 / PM-4: the strict option read --------------------------------

def test_a_failed_option_read_is_none_not_empty():
    async def _fail(token=None):
        return None                  # what get_positions_strict yields on 429
    with _patched(alp, get_positions_strict=_fail):
        assert _run(alp.get_option_positions_strict()) is None


def test_a_real_answer_is_filtered_to_options_only():
    async def _ok(token=None):
        return [_EQ_ROW, _OPT_ROW]
    with _patched(alp, get_positions_strict=_ok):
        got = _run(alp.get_option_positions_strict())
    assert got == [_OPT_ROW], got


def test_a_flat_account_is_still_an_empty_list():
    """Flat is an ANSWER. Only a failure is answerless."""
    async def _flat(token=None):
        return []
    with _patched(alp, get_positions_strict=_flat):
        assert _run(alp.get_option_positions_strict()) == []


def test_the_display_read_keeps_its_old_shape():
    """get_option_positions stays [] on failure for display-only callers,
    and still filters the same way -- one filter, two tolerances."""
    async def _fail(token=None):
        return None

    async def _ok(token=None):
        return [_EQ_ROW, _OPT_ROW]
    with _patched(alp, get_positions_strict=_fail):
        assert _run(alp.get_option_positions()) == []
    with _patched(alp, get_positions_strict=_ok):
        assert _run(alp.get_option_positions()) == [_OPT_ROW]


def test_the_strict_read_is_driven_by_the_real_http_seam():
    """Drive the whole chain from _get so the strict variant cannot be
    quietly detached from get_positions_strict later."""
    async def _http_fail(path, token=None):
        return None
    with _patched(alp, _get=_http_fail):
        assert _run(alp.get_option_positions_strict()) is None


# --- SY-02: crypto forced exit cancels through the base-matched path -----

def _seams():
    """_get/_delete/_post stubs that record what the venue was asked.
    The unfiltered orders listing holds a DOT/USD stop-limit (the venue's
    own spelling) plus an unrelated BTC leg; a symbols= probe for the
    positions spelling would answer nothing, exactly as live."""
    seen = {"get": [], "delete": [], "post": []}

    async def _get(path, token=None):
        seen["get"].append(path)
        if "symbols=" in path:
            return []                # the wrong question, answered empty
        if path.startswith("/v2/orders?status=open"):
            return [
                {"id": "stop-dot", "symbol": "DOT/USD",
                 "type": "stop_limit", "side": "sell"},
                {"id": "stop-btc", "symbol": "BTC/USD",
                 "type": "stop_limit", "side": "sell"},
            ]
        return None

    async def _delete(path, token=None):
        seen["delete"].append(path)
        return {}, None

    async def _post(path, body, token=None):
        seen["post"].append(path)
        raise AssertionError(f"liquidate must never place an order: {path}")

    return seen, _get, _delete, _post


def test_a_crypto_liquidate_cancels_by_base_not_by_symbols_filter():
    seen, g, d, p = _seams()
    with _patched(alp, _get=g, _delete=d, _post=p):
        res, err = _run(alp.liquidate_position("DOT", asset_type="crypto"))
    assert err is None, err
    assert not any("symbols=" in x for x in seen["get"]), seen["get"]
    assert any(x.startswith("/v2/orders?status=open") for x in seen["get"]), seen
    assert seen["delete"] == ["/v2/orders/stop-dot", "/v2/positions/DOTUSD"], seen
    assert seen["post"] == []


def test_a_pair_spelled_row_routes_as_crypto_even_with_the_stock_default():
    """Adoption writes the broker's naming ('DOTUSD') and some callers
    never pass asset_type. The spelling alone is enough to route."""
    for spelling in ("DOTUSD", "DOT/USD"):
        seen, g, d, p = _seams()
        with _patched(alp, _get=g, _delete=d, _post=p):
            _run(alp.liquidate_position(spelling))
        assert not any("symbols=" in x for x in seen["get"]), (spelling, seen)
        assert seen["delete"] == ["/v2/orders/stop-dot",
                                  "/v2/positions/DOTUSD"], (spelling, seen)


def test_a_failed_crypto_listing_still_attempts_the_liquidate():
    """Best-effort is preserved: when the listing cannot be read the
    DELETE goes out anyway and the venue's 403, if any, is surfaced
    honestly rather than us guessing that nothing rests."""
    seen = {"delete": []}

    async def _get(path, token=None):
        return None

    async def _delete(path, token=None):
        seen["delete"].append(path)
        return {}, None

    async def _post(path, body, token=None):
        raise AssertionError("no orders")
    with _patched(alp, _get=_get, _delete=_delete, _post=_post):
        _run(alp.liquidate_position("DOT", asset_type="crypto"))
    assert seen["delete"] == ["/v2/positions/DOTUSD"], seen


def test_an_equity_liquidate_keeps_the_symbols_filter():
    """Equity behaviour is unchanged: probe symbols=GM, cancel what it
    lists, then DELETE the bare symbol."""
    seen = {"get": [], "delete": []}

    async def _get(path, token=None):
        seen["get"].append(path)
        if "symbols=GM" in path:
            return [{"id": "leg-1"}]
        raise AssertionError(f"equity must not list unfiltered: {path}")

    async def _delete(path, token=None):
        seen["delete"].append(path)
        return {}, None

    async def _post(path, body, token=None):
        raise AssertionError("no orders")
    with _patched(alp, _get=_get, _delete=_delete, _post=_post):
        res, err = _run(alp.liquidate_position("GM"))
    assert err is None, err
    assert seen["get"] == ["/v2/orders?status=open&symbols=GM"], seen
    assert seen["delete"] == ["/v2/orders/leg-1", "/v2/positions/GM"], seen


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
