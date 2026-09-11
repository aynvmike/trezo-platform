"""Current book equity reaches research without stale, cross-book or cash fallbacks."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, quiet_activity_log, run_tests, stub_config

stub_config()
accounts = load_module("app.brokers.accounts")
alpaca = load_module("app.brokers.alpaca")
capital = load_module("app.research.capital")
bridge = load_module("app.research.bridge")
discovery = load_module("app.agents.strategy_discovery")
performance = load_module("app.paper.performance")
engine = load_module("app.paper.engine")


@contextmanager
def _patched(target, **attrs):
    saved = {name: getattr(target, name) for name in attrs}
    try:
        for name, value in attrs.items():
            setattr(target, name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(target, name, value)


def _book(slot="primary", *, url="https://paper-api.alpaca.markets"):
    marker = "A" if slot == "primary" else "B"
    return accounts.BrokerAccount(slot, slot, "test-owner", "book-" + marker.lower(),
                                  marker * 26, marker.lower() * 44, url)


def _body(book, equity=5000, **changes):
    values = {"id": "test-broker-" + book.account_id, "equity": str(equity),
              "cash": "250", "buying_power": "20000", "currency": "USD",
              "status": "ACTIVE", "trading_blocked": False}
    values.update(changes)
    return values


@contextmanager
def _transport(books, responses, calls, *, on_read=None):
    """Real binding/header/endpoint/parser functions; only HTTP GET is replaced."""
    primary = _book()
    settings = SimpleNamespace(alpaca_api_key=primary.key_id,
                               alpaca_secret_key=primary.secret,
                               alpaca_base_url=primary.base_url,
                               trezo_default_account="primary")

    async def get(path, token=None, **kwargs):
        assert path == "/v2/account", "research may read only its account"
        assert token is None
        headers = alpaca._headers_for(token)
        key = headers["APCA-API-KEY-ID"]
        before = accounts.current_user_id()
        calls.append((before, path, alpaca._base_url()))
        if on_read is not None:
            await on_read(before)
        else:
            await asyncio.sleep(0)
        # Yielding to another book must not change this request's route.
        assert accounts.current_user_id() == before
        assert alpaca._headers_for(token) == headers
        response = responses[key]
        if isinstance(response, Exception):
            raise response
        return response

    with ExitStack() as patches:
        patches.enter_context(_patched(accounts, load_accounts=lambda: list(books),
                                       get_settings=lambda: settings))
        patches.enter_context(_patched(alpaca, get_settings=lambda: settings,
                                       _live_active=lambda: False, _get=get,
                                       _note_read_error=lambda *a, **kw: None))
        yield


def _expect_block(book_id, reason):
    try:
        asyncio.run(capital.read_capital_snapshot(book_id))
    except capital.CapitalUnavailable as exc:
        assert str(exc) == reason, str(exc)
    else:
        raise AssertionError("unusable account data must block research")


def test_concurrent_books_read_distinct_current_equity_and_identity():
    a, b = _book(), _book("acct2")
    calls = []
    responses = {a.key_id: _body(a, 1234.56), b.key_id: _body(b, 8765.43)}

    async def together():
        arrived, both = set(), asyncio.Event()

        async def rendezvous(uid):
            arrived.add(uid)
            if len(arrived) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), timeout=1)

        with _transport([a, b], responses, calls, on_read=rendezvous):
            return await asyncio.gather(capital.read_capital_snapshot(a.account_key),
                                        capital.read_capital_snapshot(b.account_key))

    first, second = asyncio.run(together())
    assert first["equity_usd"] == 1234.56 and second["equity_usd"] == 8765.43
    assert first["book_id"] == a.account_key and second["book_id"] == b.account_key
    assert first["account_fingerprint"] != second["account_fingerprint"]
    assert first["account_fingerprint"] == hashlib.sha256(responses[a.key_id]["id"].encode()).hexdigest()
    assert {c[0] for c in calls} == {a.account_key, b.account_key}
    assert len(calls) == 2
    assert set(first) == {"book_id", "source", "currency", "equity_usd",
                          "observed_at", "account_fingerprint"}
    assert first["source"] == "alpaca_paper_account"
    assert datetime.fromisoformat(first["observed_at"]).utcoffset() is not None


def test_unresolved_book_never_reads_primary_or_parent_binding():
    a, b = _book(), _book("acct2")
    calls = []
    with _transport([a, b], {}, calls), accounts.use_account(b):
        _expect_block("unknown", "research_book_unresolved")
        _expect_block("", "research_book_unresolved")
        assert accounts.current_user_id() == b.account_key
    assert calls == []


def test_lone_secondary_book_refuses_legacy_primary_credential_fallback():
    b = _book("acct2")
    calls = []
    with _transport([b], {}, calls):
        _expect_block(b.account_key, "research_broker_route_mismatch")
    assert calls == []


def test_sole_primary_book_reads_its_real_route():
    a = _book()
    calls = []
    with _transport([a], {a.key_id: _body(a, 6200)}, calls):
        snapshot = asyncio.run(capital.read_capital_snapshot(a.account_key))
    assert snapshot["equity_usd"] == 6200
    assert calls == [(a.account_key, "/v2/account", a.base_url)]


def test_live_and_untrusted_endpoints_are_blocked_before_http():
    calls = []
    for url in ("https://api.alpaca.markets", "https://paper-api.alpaca.markets.invalid",
                "https://paper-api.alpaca.markets/?credential=private"):
        a, b = _book(), _book("acct2", url=url)
        with _transport([a, b], {}, calls):
            _expect_block(b.account_key, "research_paper_endpoint_required")
    assert calls == []


def test_live_venue_cannot_supply_a_paper_research_snapshot():
    a = _book()
    calls = []
    with _transport([a], {}, calls), _patched(alpaca, _live_active=lambda: True):
        _expect_block(a.account_key, "research_broker_route_mismatch")
    assert calls == []


def test_failed_or_malformed_account_reads_never_fall_back_to_internal_cash():
    a = _book()
    calls, fallbacks = [], []

    async def internal(uid):
        fallbacks.append(uid)
        return {"current_cash_usd": 999999, "vault_balance_usd": 999999}

    for bad in (None, RuntimeError("synthetic timeout"), {}, {"cash": "25"},
                _body(a, cash="bad")):
        with _transport([a], {a.key_id: bad}, calls), _patched(engine, get_account=internal):
            _expect_block(a.account_key, "research_equity_read_failed")
    assert len(calls) == 5 and fallbacks == []


def test_nonfinite_zero_negative_or_unsupported_equity_is_not_a_research_base():
    a = _book()
    calls = []
    for value in ("nan", "inf", "-inf", "0", "-500", "1000000001"):
        with _transport([a], {a.key_id: _body(a, value)}, calls):
            _expect_block(a.account_key, "research_equity_snapshot_invalid")
    for value in ("nan", "inf", "-inf"):
        with _transport([a], {a.key_id: _body(a, cash=value)}, calls):
            _expect_block(a.account_key, "research_equity_snapshot_invalid")
    assert len(calls) == 9


def test_currency_status_and_broker_identity_must_be_known():
    a = _book()
    calls = []
    for changes in ({"currency": "EUR"}, {"status": "ACCOUNT_UPDATED"},
                    {"status": None}, {"id": None}, {"id": "   "}):
        with _transport([a], {a.key_id: _body(a, **changes)}, calls):
            _expect_block(a.account_key, "research_equity_snapshot_invalid")
    assert len(calls) == 5


def _research_settings(path):
    # Omit capital mode: the runtime default must use broker equity.
    return SimpleNamespace(trezo_research_enabled=True, trading_mode="paper",
                           trezo_research_symbol="SPY", trezo_research_asset_type="stock",
                           trezo_research_capitals="1000,5000", trezo_research_commission_bps=2,
                           trezo_research_slippage_bps=5, trezo_research_db_path=str(path))


def test_failed_equity_blocks_the_actual_bridge_before_data_or_storage():
    a = _book()
    calls, fetches = [], []

    async def fetch(*args):
        fetches.append(args)
        return []

    with tempfile.TemporaryDirectory() as tmp, _transport([a], {a.key_id: None}, calls), \
            _patched(bridge, _fetch_daily=fetch, _DATA_CACHE={}):
        path = Path(tmp) / "research.sqlite3"
        result = asyncio.run(bridge.research_for_book(a.account_key, settings=_research_settings(path)))
        assert result["status"] == "blocked"
        assert result["reason"] == "research_equity_read_failed"
        assert result["capital_basis"] == "broker_equity"
        assert not path.exists()
    assert len(calls) == 1 and fetches == []


@contextmanager
def _diagnostic_transport(book, outcome, calls):
    """Exercise the actual GET and parser with only the HTTP client replaced."""
    import httpx
    real_get, real_note = alpaca._get, alpaca._note_read_error

    class Client:
        def __init__(self, **kwargs):
            import ssl
            assert set(kwargs) == {"timeout", "verify"}
            assert kwargs["timeout"] == 10.0
            assert isinstance(kwargs["verify"], ssl.SSLContext)
            assert kwargs["verify"].verify_mode == ssl.CERT_REQUIRED
            assert kwargs["verify"].check_hostname is True

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, *, headers):
            assert url == book.base_url + "/v2/account"
            assert headers == book.headers()
            calls.append(url)
            return await outcome()

    with _transport([book], {}, []), quiet_activity_log(), \
            _patched(alpaca, _get=real_get, _note_read_error=real_note,
                     _LAST_READ_ERROR={}, _READ_ERROR_LOGGED_AT={}), \
            _patched(httpx, AsyncClient=Client):
        yield


def test_actual_bridge_receives_sanitized_current_transport_failure():
    import httpx
    a = _book()
    sensitive = "private-account-token-must-not-escape"
    cases = [
        (httpx.Response(401, text=sensitive), "authentication_failed", 401),
        (httpx.Response(429, text=sensitive), "rate_limited", 429),
        (httpx.Response(503, text=sensitive), "broker_unavailable", 503),
        (httpx.ConnectTimeout(sensitive), "connect_timeout", None),
        (httpx.ReadTimeout(sensitive), "read_timeout", None),
        (httpx.ConnectError(sensitive), "connection_failed", None),
        (httpx.Response(200, text=sensitive), "invalid_response", None),
        (httpx.Response(200, json={sensitive: "missing amounts"}), "invalid_response", None),
    ]
    for response, category, status in cases:
        async def outcome():
            if isinstance(response, Exception):
                raise response
            return response

        calls = []
        with tempfile.TemporaryDirectory() as tmp, _diagnostic_transport(a, outcome, calls):
            path = Path(tmp) / "research.sqlite3"
            result = asyncio.run(bridge.research_for_book(a.account_key, settings=_research_settings(path)))
            assert result["status"] == "blocked" and result["reason"] == "research_equity_read_failed"
            expected = {"endpoint": "/v2/account", "category": category}
            if status is not None:
                expected["http_status"] = status
            assert result["capital_read_diagnostic"] == expected, result
            assert sensitive not in json.dumps(result)
            assert result["execution_enabled"] is False and not path.exists()
        assert len(calls) == 1
        assert alpaca._READ_FAILURE_CAPTURE.get() is None


def test_concurrent_same_book_reads_keep_their_own_failure_diagnostics():
    import httpx
    a = _book()
    calls = []

    async def together():
        ready = asyncio.Event()
        count = 0

        async def outcome():
            nonlocal count
            status = 401 if count == 0 else 503
            count += 1
            if count == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), timeout=1)
            return httpx.Response(status, text="private failure detail")

        with _diagnostic_transport(a, outcome, calls):
            return await asyncio.gather(capital.read_capital_snapshot(a.account_key),
                                        capital.read_capital_snapshot(a.account_key), return_exceptions=True)

    results = asyncio.run(together())
    assert all(isinstance(result, capital.CapitalUnavailable) for result in results), results
    assert [result.diagnostic["http_status"] for result in results] == [401, 503]
    assert len(calls) == 2 and alpaca._READ_FAILURE_CAPTURE.get() is None


def test_unclassified_read_does_not_reuse_a_historical_or_other_endpoint_error():
    a = _book()
    calls = []
    real_note = alpaca._note_read_error

    async def other_endpoint(uid):
        # A nested failure for another endpoint is not evidence about account equity.
        real_note("/v2/positions", "HTTP 503: private response", log=False)

    with _transport([a], {a.key_id: None}, calls, on_read=other_endpoint), \
            _patched(alpaca, _LAST_READ_ERROR={"primary": "GET /v2/account: HTTP 401: old failure"}):
        try:
            asyncio.run(capital.read_capital_snapshot(a.account_key))
        except capital.CapitalUnavailable as exc:
            assert exc.diagnostic == {"endpoint": "/v2/account", "category": "unclassified_failure"}
        else:
            raise AssertionError("missing account must block")
    assert len(calls) == 1 and alpaca._READ_FAILURE_CAPTURE.get() is None


def test_outer_read_deadline_is_explicit_and_cancellation_is_not_swallowed():
    a = _book()
    calls = []

    async def expired(awaitable, *, timeout):
        assert timeout == 10
        awaitable.close()
        raise asyncio.TimeoutError("private details")

    async def cancelled(awaitable, *, timeout):
        awaitable.close()
        raise asyncio.CancelledError()

    with _transport([a], {}, calls), \
            _patched(capital, asyncio=SimpleNamespace(wait_for=expired, TimeoutError=asyncio.TimeoutError)):
        try:
            asyncio.run(capital.read_capital_snapshot(a.account_key))
        except capital.CapitalUnavailable as exc:
            assert exc.diagnostic == {"endpoint": "/v2/account", "category": "deadline_exceeded"}
        else:
            raise AssertionError("deadline must block")
    with _transport([a], {}, calls), \
            _patched(capital, asyncio=SimpleNamespace(wait_for=cancelled, TimeoutError=asyncio.TimeoutError)):
        try:
            asyncio.run(capital.read_capital_snapshot(a.account_key))
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("shutdown cancellation must propagate")
    assert calls == [] and alpaca._READ_FAILURE_CAPTURE.get() is None


def test_discovery_freezes_daily_evidence_and_retests_growing_and_shrinking_books():
    a, b = _book(), _book("acct2")
    calls, fetches, actions = [], [], []
    responses = {a.key_id: _body(a, 5000), b.key_id: _body(b, 1000)}
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    clock = {"now": today}

    class ResearchClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    async def data(*args):
        fetches.append(args)
        start = today - timedelta(days=502)
        rows = []
        for i in range(500):
            price = 100 + 0.03 * i + 4 * math.sin(i / 9)
            rows.append(SimpleNamespace(timestamp=start + timedelta(days=i), open=price,
                                        high=price + 1, low=price - 1, close=price + 0.2))
        return rows

    class Client:
        def table(self, name):
            assert name == "paper_accounts"
            return self

        def select(self, fields):
            assert fields == "user_id"
            return self

        def execute(self):
            return SimpleNamespace(data=[{"user_id": a.account_key}, {"user_id": b.account_key}])

    async def report(*args):
        return performance.compute_performance([])

    async def no_recall(*args, **kwargs):
        return []

    async def no_insight(*args, **kwargs):
        return ""

    async def forbidden_action(*args, **kwargs):
        actions.append((args, kwargs))
        raise AssertionError("research cannot execute a broker or ledger mutation")

    def tick():
        messages = asyncio.run(discovery.StrategyDiscoveryAgent().tick())
        assert all(message.kind not in {"signal", "approve", "execute"} for message in messages)
        outputs = {m.payload["user_id"]: m.payload for m in messages
                   if m.payload.get("event") == "internal_research"}
        assert set(outputs) == {a.account_key, b.account_key}
        assert all(output["status"] == "completed" for output in outputs.values()), outputs
        assert all(output["capital_basis"] == "broker_equity" for output in outputs.values())
        assert all(output["execution_enabled"] is False for output in outputs.values())
        return outputs

    with tempfile.TemporaryDirectory() as tmp, ExitStack() as patches:
        path = Path(tmp) / "research.sqlite3"
        patches.enter_context(_transport([a, b], responses, calls))
        patches.enter_context(_patched(bridge, _fetch_daily=data, _DATA_CACHE={}, datetime=ResearchClock,
                                       get_settings=lambda: _research_settings(path)))
        patches.enter_context(_patched(discovery, _supabase=lambda: Client(), performance_for_user=report))
        patches.enter_context(_patched(discovery.StrategyDiscoveryAgent, recall=no_recall,
                                       _backtest_insight=no_insight, remember=forbidden_action))
        patches.enter_context(_patched(alpaca, _post=forbidden_action, _patch=forbidden_action,
                                       _delete=forbidden_action))
        patches.enter_context(_patched(engine, open_position=forbidden_action,
                                       close_position=forbidden_action))
        first = tick()
        originals = {p: p.read_bytes() for p in Path(tmp).rglob("*.json")}
        assert len(originals) == 2
        responses[a.key_id]["equity"], responses[b.key_id]["equity"] = "5100", "1010"
        repeated = tick()
        assert originals == {p: p.read_bytes() for p in Path(tmp).rglob("*.json")}
        for book, old, latest in ((a, 5000, 5100), (b, 1000, 1010)):
            case = repeated[book.account_key]["cases"][0]
            assert case["starting_capital"] == old
            assert case["capital_snapshot"]["equity_usd"] == old
            assert case["job_id"] == first[book.account_key]["cases"][0]["job_id"]
            assert repeated[book.account_key]["latest_capital_snapshot"]["equity_usd"] == latest

        for offset, a_equity, b_equity in ((1, 7000, 1200), (2, 4000, 900)):
            clock["now"] = today + timedelta(days=offset)
            responses[a.key_id]["equity"] = str(a_equity)
            responses[b.key_id]["equity"] = str(b_equity)
            next_day = tick()
            for book, equity in ((a, a_equity), (b, b_equity)):
                output = next_day[book.account_key]
                assert len(output["cases"]) == 1
                case = output["cases"][0]
                assert case["starting_capital"] == equity
                assert case["job_id"] != first[book.account_key]["cases"][0]["job_id"]
                artifact = json.loads(Path(case["artifact_path"]).read_text())
                assert artifact["assumptions"]["starting_capital"] == equity
                assert artifact["capital_snapshot"]["equity_usd"] == equity
                assert artifact["capital_snapshot"]["book_id"] == book.account_key
                assert artifact["continuation"] is not None  # capital changes retain research lineage
                assert len(artifact["trials"]) == 4
                assert all(trial["execution_enabled"] is False for trial in artifact["trials"])
                assert artifact["profitability_verified"] is False
                assert artifact["forward_evidence_required"] is True
        assert all(p.read_bytes() == contents for p, contents in originals.items())
        assert len(list(Path(tmp).rglob("*.json"))) == 6
    assert len(calls) == 8 and len(fetches) == 3 and actions == []


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
