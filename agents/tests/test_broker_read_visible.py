"""Failed Alpaca reads must say WHY, per book -- and a 2xx account body
without cash must never read as $0.00 (2026-09-02).

The blocker these replay: alpaca._get() wrapped the request in
`except Exception: return None` after raise_for_status(), so an HTTP 429
or 5xx, an httpx ReadTimeout / ConnectError and a non-JSON 200 all became
the same bare None with no log and no retained status. Every strict
reader inherited it, so the five "could not read open orders - left
untouched" returns and options_scanner's reconcile_skipped_unreadable had
nothing to report -- eight isolated failures on 2026-09-02 were invisible
beyond "left untouched". Separately, get_account() turned a 2xx dict that
LACKED 'cash' into cash=0.0, which the balance reconcile would have
stamped into a book's ledger -- a failed read reading as empty.

What these pin, on the REAL app.brokers.alpaca (tests/_bootstrap.load_module)
with only httpx.AsyncClient and activity_log.record swapped by ATTRIBUTE
and always put back:

  * _get() still returns None on EVERY failure (strict semantics do not
    change) but retains the reason for the bound book: HTTP 429 / 500 with
    the body, ReadTimeout / ConnectError by class name, a non-JSON 200 as
    JSONDecodeError;
  * ONE broker_read_failed activity row per (book, endpoint) per 60s,
    carrying the symbol, the bound book and its user_id;
  * two bound books keep SEPARATE last errors -- and the wire request for
    each carried that book's own API key;
  * the five "left untouched" sites and the scanner's
    reconcile_skipped_unreadable row carry the detail (values arrive);
  * get_account() refuses a 2xx payload with no parseable cash/equity
    (None -> the balance reconcile skips) while cash "0" still reads as a
    genuine zero;
  * a healthy [] is still [] and leaves no error behind;
  * a logging failure never breaks a read.

Deploy-gate contract: plain zero-arg test_ functions, no fixtures, no .env,
no network, no engine boot.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import types

from tests import _bootstrap

_bootstrap.stub_config()
alp = _bootstrap.load_module("app.brokers.alpaca")
accounts = _bootstrap.load_module("app.brokers.accounts")
alog = _bootstrap.load_module("app.agents.activity_log")
route_guard = _bootstrap.load_module("app.brokers.route_guard")
wt = _bootstrap.load_module("app.integrations.web_tokens")
scanner = _bootstrap.load_module("app.agents.options_scanner")

import httpx  # noqa: E402  -- the real package; only AsyncClient is swapped


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


_MISSING = object()


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and ALWAYS put the originals back."""
    old = {k: getattr(mod, k, _MISSING) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is _MISSING:
                if hasattr(mod, k):
                    delattr(mod, k)
            else:
                setattr(mod, k, v)


# --- seams -------------------------------------------------------------------

class _FakeResp:
    """Just enough of httpx.Response: status_code, text, json()."""

    def __init__(self, status=200, text="", payload=_MISSING):
        self.status_code = status
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is _MISSING:
            # a non-JSON body raises json.JSONDecodeError, as httpx does
            return json.loads(self.text)
        return self._payload

    def raise_for_status(self):
        # Present so a regression back to raise_for_status() would surface
        # as "HTTPStatusError: ..." in the note, not as "HTTP 429: ...".
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"status {self.status_code}",
                                        request=None, response=None)


class _FakeClient:
    def __init__(self, outcome, calls):
        self._outcome = outcome
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, **kw):
        self._calls.append({"url": url, "headers": dict(headers or {})})
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


@contextlib.contextmanager
def _http(outcome):
    """Swap httpx.AsyncClient by attribute on the real module; yield the
    list of GETs the code under test actually made (url + headers)."""
    calls: list[dict] = []
    real = httpx.AsyncClient
    httpx.AsyncClient = lambda *a, **k: _FakeClient(outcome, calls)  # type: ignore
    try:
        yield calls
    finally:
        httpx.AsyncClient = real


@contextlib.contextmanager
def _records():
    """Capture activity_log.record rows (extra merged in, as the real
    record does) and restore the real one after."""
    rows: list[dict] = []

    def _rec(event, ticker, *, reason="", extra=None, **_kw):
        rows.append({"event": event, "ticker": ticker, "reason": reason,
                     **(extra or {})})

    with _patched(alog, record=_rec):
        yield rows


def _fresh():
    """Clear the per-book memory in place (the module holds the dicts)."""
    alp._LAST_READ_ERROR.clear()
    alp._READ_ERROR_LOGGED_AT.clear()


_A2 = accounts.BrokerAccount(account_id="acct2", label="Two", owner_id="mike",
                             account_key="U-acct2", key_id="2" * 26, secret="S" * 44)
_A3 = accounts.BrokerAccount(account_id="acct3", label="Three", owner_id="mike",
                             account_key="U-acct3", key_id="3" * 26, secret="S" * 44)


@contextlib.contextmanager
def _two_books():
    """Make the registry hold two books so multi_account_active() is True
    and bind_for_user resolves them -- through the REAL binder."""
    with _patched(accounts, load_accounts=lambda: [_A2, _A3]):
        yield


# --- each failure class -> None + a retained, book-keyed reason ----------

def test_a_429_is_none_and_names_the_status_and_body():
    _fresh()
    body = '{"code":42910000,"message":"too many requests"}'
    with _records() as rows, _http(_FakeResp(429, body)) as calls:
        out = _run(alp.get_open_orders_for("AAPL"))
    assert out is None, "strict semantics: a failed read is None, never []"
    assert len(calls) == 1 and "/v2/orders?" in calls[0]["url"], calls
    err = alp.last_read_error()
    assert err.startswith("GET /v2/orders: HTTP 429:") and "too many requests" in err, err
    assert alp._read_book() == "primary", "unbound single-account reads file under 'primary'"
    assert alp._LAST_READ_ERROR == {"primary": err}, alp._LAST_READ_ERROR
    assert len(rows) == 1 and rows[0]["event"] == "broker_read_failed", rows
    assert rows[0]["ticker"] == "AAPL" and rows[0]["account"] == "primary", rows
    assert rows[0]["reason"].startswith("HTTP 429:"), rows
    assert rows[0]["reason"].endswith(" on GET /v2/orders"), rows


def test_a_500_is_none_and_the_row_is_account_level():
    _fresh()
    with _records() as rows, _http(_FakeResp(500, "<html>upstream error</html>")):
        out = _run(alp.get_positions_strict())
    assert out is None
    err = alp.last_read_error()
    assert err.startswith("GET /v2/positions: HTTP 500: <html>upstream error"), err
    assert rows and rows[0]["ticker"] == "ACCOUNT", rows


def test_a_read_timeout_is_named_by_class():
    _fresh()
    with _records() as rows, _http(httpx.ReadTimeout("timed out")):
        out = _run(alp.get_positions_strict())
    assert out is None
    assert alp.last_read_error() == "GET /v2/positions: ReadTimeout: timed out"
    assert rows[0]["reason"] == "ReadTimeout: timed out on GET /v2/positions", rows


def test_a_connect_error_is_named_by_class():
    _fresh()
    with _records() as rows, _http(httpx.ConnectError("nodename nor servname provided")):
        out = _run(alp.get_all_open_orders())
    assert out is None
    err = alp.last_read_error()
    assert err.startswith("GET /v2/orders: ConnectError: nodename"), err
    assert rows and rows[0]["event"] == "broker_read_failed", rows


def test_a_non_json_200_is_none_and_names_json_decode_error():
    _fresh()
    with _records() as rows, _http(_FakeResp(200, "<html>sign in</html>")):
        out = _run(alp.get_open_orders_for("MSFT"))
    assert out is None, "a 200 whose body is not JSON is still a failed read"
    err = alp.last_read_error()
    assert err.startswith("GET /v2/orders: JSONDecodeError:"), err
    assert rows and rows[0]["ticker"] == "MSFT", rows


def test_an_unconfigured_book_says_so_and_never_calls_out():
    _fresh()
    with _records() as rows, _patched(alp, alpaca_configured=lambda: False), \
         _http(_FakeResp(200, payload=[])) as calls:
        out = _run(alp.get_open_orders_for("AAPL"))
    assert out is None and calls == [], calls
    assert rows == [], "not-configured is a state, not a failure -- no activity row"
    assert alp.last_read_error() == "GET /v2/orders: Alpaca not configured for this book"


# --- throttle: one row per (book, endpoint) per minute --------------------

def test_two_failures_inside_a_minute_log_once_per_book_and_endpoint():
    _fresh()
    with _records() as rows, _http(_FakeResp(429, "slow down")):
        _run(alp.get_open_orders_for("AAPL"))
        _run(alp.get_open_orders_for("MSFT"))    # same endpoint: throttled
        _run(alp.get_positions_strict())          # other endpoint: own row
        alp._READ_ERROR_LOGGED_AT[("primary", "/v2/orders")] -= 61.0
        _run(alp.get_open_orders_for("NVDA"))     # window elapsed: logs again
    assert [r["ticker"] for r in rows] == ["AAPL", "ACCOUNT", "NVDA"], rows
    # the retained reason is refreshed on EVERY failure, throttled or not
    assert alp.last_read_error().startswith("GET /v2/orders: HTTP 429: slow down")


# --- per-book: separate errors, separate keys on the wire -----------------

def test_two_bound_books_keep_separate_errors_and_send_their_own_keys():
    _fresh()
    with _two_books(), _records() as rows:
        with accounts.bind_for_user("U-acct2"), _http(_FakeResp(429, "too many")) as c2:
            assert _run(alp.get_open_orders_for("AAPL")) is None
            e2 = alp.last_read_error()
        with accounts.bind_for_user("U-acct3"), _http(httpx.ReadTimeout("timed out")) as c3:
            assert _run(alp.get_open_orders_for("AAPL")) is None
            e3 = alp.last_read_error()
        with accounts.bind_for_user("U-acct2"):
            assert alp.last_read_error() == e2, "acct3's failure overwrote acct2's reason"
    assert e2.startswith("GET /v2/orders: HTTP 429: too many"), e2
    assert e3 == "GET /v2/orders: ReadTimeout: timed out", e3
    assert alp._LAST_READ_ERROR == {"acct2": e2, "acct3": e3}, alp._LAST_READ_ERROR
    # the binding reached the wire: each read went out under its own key
    assert c2[0]["headers"]["APCA-API-KEY-ID"] == _A2.key_id, c2
    assert c3[0]["headers"]["APCA-API-KEY-ID"] == _A3.key_id, c3
    by = {r["account"]: r for r in rows}
    assert set(by) == {"acct2", "acct3"}, rows
    assert by["acct2"]["user_id"] == "U-acct2" and by["acct3"]["user_id"] == "U-acct3", rows
    # unbound again: nothing is filed under the fallback key
    assert alp.last_read_error() == ""


# --- the five "left untouched" sites carry the reason ----------------------

def test_the_five_left_untouched_sites_say_why():
    _fresh()
    with _records(), _http(_FakeResp(429, '{"message":"too many requests"}')):
        notes = {
            "ratchet_stop": _run(alp.ratchet_stop("AAPL", 100.0, qty=10)),
            "ensure_stock_protection": _run(alp.ensure_stock_protection("AAPL", 10, 95.0, 120.0)),
            "ensure_crypto_take_profit": _run(alp.ensure_crypto_take_profit("BTCUSD", 0.1, 70000.0)),
            "ratchet_crypto_stop": _run(alp.ratchet_crypto_stop("BTCUSD", 60000.0, qty=0.1)),
            "ensure_short_protection": _run(alp.ensure_short_protection("XLF", 100, 58.0, 55.0)),
        }
    assert len(notes) == 5
    for name, (changed, note) in notes.items():
        assert changed is False, (name, note)
        assert note.startswith("could not read open orders (GET /v2/orders: HTTP 429:"), (name, note)
        assert "too many requests" in note and note.endswith("- left untouched"), (name, note)


# --- options scanner: reconcile_skipped_unreadable names the cause --------

class _Q:
    def __init__(self, rows):
        self._rows = rows

    def __getattr__(self, name):
        def _chain(*a, **k):
            return self
        return _chain

    def execute(self):
        return types.SimpleNamespace(data=list(self._rows))


class _Client:
    def __init__(self, open_rows):
        self._open = open_rows

    def table(self, name):
        return _Q(self._open if name == "options_positions" else [])


def test_the_scanner_reconcile_skip_names_the_read_failure():
    _fresh()
    row = {"id": "row-1", "user_id": "U2", "underlying": "XYZ", "strategy": "csp",
           "option_type": "put", "strike": 10.0, "expiration": "2026-12-18",
           "contracts": 1, "notes": "", "net_premium_usd": 50.0}
    bound: list[str] = []

    async def _strict(token=None):
        # what the real strict reader does on a 429: note, then answer None
        alp._note_read_error("/v2/positions", "HTTP 429: too many requests")
        return None

    async def _token(uid, broker):
        return None

    def _bind(uid):
        bound.append(str(uid))
        return True

    with _records() as rows, _patched(scanner, _primary_book=lambda: ""), \
         _patched(alp, get_option_positions_strict=_strict, alpaca_configured=lambda: True), \
         _patched(accounts, set_account_for_user=_bind, clear_account=lambda: None), \
         _patched(route_guard, check_route=lambda uid: (True, "ok")), \
         _patched(wt, get_user_broker_token=_token):
        out = _run(scanner.OptionsScannerAgent()._reconcile_with_broker(_Client([row])))
    assert out == [] and bound == ["U2"], (out, bound)
    skip = [r for r in rows if r["event"] == "reconcile_skipped_unreadable"]
    assert skip and skip[0]["user_id"] == "U2", rows
    assert "HTTP 429: too many requests" in skip[0]["reason"], skip
    assert "GET /v2/positions" in skip[0]["reason"], skip
    assert skip[0]["reason"].endswith("no row closed or adopted this tick"), skip


# --- get_account: a 2xx without cash is None, not a zeroed account --------

def test_get_account_without_cash_is_none_not_a_zeroed_account():
    _fresh()
    no_cash = {"id": "abc", "account_number": "PA1", "status": "ACTIVE",
               "currency": "USD", "equity": "9000.10"}
    with _records() as rows, _http(_FakeResp(200, payload=no_cash)):
        acct = _run(alp.get_account())
    assert acct is None, "a 2xx payload lacking 'cash' must not read as cash=0.0"
    err = alp.last_read_error()
    assert err.startswith("GET /v2/account: 2xx payload without parseable cash/equity"), err
    assert rows and rows[0]["ticker"] == "ACCOUNT" and rows[0]["event"] == "broker_read_failed", rows

    nothing = {"message": "forbidden"}
    with _records(), _http(_FakeResp(200, payload=nothing)):
        assert _run(alp.get_account()) is None

    unparseable = dict(no_cash, cash="n/a")
    with _records(), _http(_FakeResp(200, payload=unparseable)):
        assert _run(alp.get_account()) is None


def test_get_account_with_a_genuine_zero_still_reads_zero():
    _fresh()
    flat = {"id": "abc", "account_number": "PA1", "status": "ACTIVE", "currency": "USD",
            "cash": "0", "equity": "0", "last_equity": "0", "buying_power": "0"}
    with _records() as rows, _http(_FakeResp(200, payload=flat)):
        acct = _run(alp.get_account())
    assert acct is not None and acct.cash == 0.0 and acct.equity == 0.0, acct
    assert rows == [] and alp.last_read_error() == ""


def test_get_account_healthy_payload_reads_cash():
    _fresh()
    ok = {"id": "abc", "account_number": "PA1", "status": "ACTIVE", "currency": "USD",
          "cash": "5123.45", "equity": "9000.10", "last_equity": "8990.00",
          "buying_power": "10246.90", "options_approved_level": "2"}
    with _records() as rows, _http(_FakeResp(200, payload=ok)):
        acct = _run(alp.get_account())
    assert acct is not None and acct.cash == 5123.45 and acct.equity == 9000.10, acct
    assert acct.account_number == "PA1" and acct.options_approved_level == 2
    assert rows == [] and alp._LAST_READ_ERROR == {}


# --- success paths untouched; logging can never break a read --------------

def test_a_healthy_empty_list_is_still_empty_and_leaves_no_error():
    _fresh()
    with _records() as rows, _http(_FakeResp(200, payload=[])):
        assert _run(alp.get_open_orders_for("AAPL")) == []
        assert _run(alp.get_positions_strict()) == []
        assert _run(alp.get_all_open_orders()) == []
        assert _run(alp.get_option_positions_strict()) == []
    assert rows == [] and alp.last_read_error() == "" and alp._LAST_READ_ERROR == {}


def test_a_logging_failure_never_breaks_the_read():
    _fresh()

    def _boom(*a, **k):
        raise RuntimeError("disk full")

    with _patched(alog, record=_boom), _http(_FakeResp(503, "unavailable")):
        assert _run(alp.get_positions_strict()) is None
    assert alp.last_read_error().startswith("GET /v2/positions: HTTP 503: unavailable")


def test_zz_leave_the_module_as_found():
    """Runs last (run_tests sorts by name). Review 2026-09-02: a fresh
    throttle stamp left in alpaca's per-book memory could mask a later
    suite's leak on the same (book, endpoint) for 60s -- clear it."""
    _fresh()
    assert alp._LAST_READ_ERROR == {} and alp._READ_ERROR_LOGGED_AT == {}


if __name__ == "__main__":
    sys.exit(_bootstrap.run_tests(dict(vars())))
