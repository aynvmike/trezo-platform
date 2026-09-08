"""Exercise the real broker transports with fakes: paper must stay paper.

No credentials, network, broker orders, or ledger writes. Compatible with
the bare deploy runner as well as pytest.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
alp = load_module("app.brokers.alpaca")
endpoints = load_module("app.brokers.endpoints")
mode = load_module("app.runtime.trading_mode")
route_guard = load_module("app.brokers.route_guard")
accounts = load_module("app.brokers.accounts")
settings = load_module("app.runtime.settings")

PAPER = endpoints.PAPER_BASE_URL
LIVE = "https://api.alpaca.markets"


@contextlib.contextmanager
def _patched(mod, **attrs):
    old = {k: getattr(mod, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


@contextlib.contextmanager
def _transport_world(url, *, bound):
    import httpx
    sent = []
    cfg = types.SimpleNamespace(alpaca_base_url=url, trading_mode="live")

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def _request(self, target, **kwargs):
            sent.append(target)
            return types.SimpleNamespace(status_code=200, json=lambda: {})

        get = post = patch = delete = _request

    with _patched(httpx, AsyncClient=Client), \
         _patched(mode, get_settings=lambda: cfg), \
         _patched(alp, get_settings=lambda: cfg,
                  _account_ctx=lambda: types.SimpleNamespace(base_url=url) if bound else None,
                  alpaca_configured=lambda: True,
                  _headers_for=lambda token: {"X-Test": "no-credentials"},
                  _note_read_error=lambda *args, **kwargs: None):
        # The REAL two-part gate remains closed even when live is requested.
        assert mode.live_trading_enabled() is False
        yield sent


def _all_transports():
    async def run():
        return [
            await alp._get("/v2/positions"),
            await alp._post("/v2/orders", {"fixture": True}),
            await alp._patch("/v2/orders/test", {"fixture": True}),
            await alp._delete("/v2/orders/test"),
        ]
    return asyncio.run(run())


def test_bound_live_url_never_reaches_any_transport():
    with _transport_world(LIVE, bound=True) as sent:
        answers = _all_transports()
        assert answers[0] is None
        assert all(a[0] is None and "endpoint refused" in a[1] for a in answers[1:])
        assert sent == [], sent


def test_unbound_live_url_never_reaches_any_transport():
    with _transport_world(LIVE, bound=False) as sent:
        answers = _all_transports()
        assert answers[0] is None
        assert all(a[0] is None and a[1] for a in answers[1:])
        assert sent == [], sent


def test_paper_requests_still_reach_the_fake_transport():
    for bound in (True, False):
        with _transport_world(PAPER, bound=bound) as sent:
            answers = _all_transports()
            assert len(sent) == 4, sent
            assert all(url.startswith(PAPER + "/v2/") for url in sent)
            assert answers[0] == {}
            assert all(a == ({}, None) for a in answers[1:])


def test_legacy_paper_suffix_and_empty_default_are_supported():
    for raw in (None, "", PAPER, PAPER + "/", PAPER + "/v2", " " + PAPER + "/v2/ "):
        assert endpoints.paper_base_url(raw) == PAPER, raw


def test_other_hosts_paths_schemes_and_embedded_credentials_are_refused():
    for raw in (LIVE, "http://paper-api.alpaca.markets",
                PAPER + ".example.com", PAPER + "/proxy", PAPER + "?x=1",
                PAPER + "#x", "https://secret@paper-api.alpaca.markets",
                "https://paper-api.alpaca.markets@other.example", 123):
        try:
            endpoints.paper_base_url(raw)
        except ValueError as exc:
            assert "secret" not in str(exc)
        else:
            raise AssertionError(f"unsafe endpoint accepted: {raw!r}")


def test_one_invalid_book_does_not_poison_a_valid_book():
    with _transport_world(LIVE, bound=True) as refused:
        _all_transports()
        assert refused == []
    with _transport_world(PAPER, bound=True) as accepted:
        _all_transports()
        assert len(accepted) == 4


def test_asset_discovery_cannot_send_keys_to_a_live_override():
    import urllib.request
    sent = []

    def fake_open(req, **kwargs):
        sent.append(req.full_url)
        return io.StringIO("[]")

    cfg = types.SimpleNamespace(alpaca_base_url=LIVE,
                                alpaca_api_key="fixture", alpaca_secret_key="fixture")
    with _patched(alp, get_settings=lambda: cfg,
                  _CRYPTO_ASSETS={"syms": frozenset(), "ts": 0}), \
         _patched(urllib.request, urlopen=fake_open):
        assert alp.tradable_crypto_symbols() == frozenset()
        assert sent == []


def test_route_audit_checks_each_books_endpoint_before_sending_keys():
    import urllib.request
    sent = []

    def fake_open(req, **kwargs):
        sent.append(req.full_url)
        return io.StringIO("[]")

    class EmptyLedger:
        def table(self, *args): return self
        def select(self, *args): return self
        def eq(self, *args): return self
        def execute(self): return types.SimpleNamespace(data=[])

    def book(name, url):
        return types.SimpleNamespace(account_id=name, base_url=url,
                                     headers=lambda: {"X-Test": "no-credentials"})

    valid = book("good", PAPER)
    with _patched(route_guard, multi_account_active=lambda: True,
                  load_accounts=lambda: [book("bad", LIVE), valid]), \
         _patched(accounts, primary_account=lambda: valid), \
         _patched(settings, _supabase=lambda: EmptyLedger()), \
         _patched(urllib.request, urlopen=fake_open):
        assert asyncio.run(route_guard.audit_routes()) == []
        assert sent == [PAPER + "/v2/positions"], sent


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
