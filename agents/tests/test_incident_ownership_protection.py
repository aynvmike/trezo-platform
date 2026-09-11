"""Incident regressions: Wheel ownership and stale short protection."""
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from tests._bootstrap import stub_config, load_module, quiet_activity_log

stub_config()
alp = load_module("app.brokers.alpaca")
qa = load_module("app.paper.trade_qa")
own = load_module("app.paper.option_ownership")
ad = load_module("app.paper.adoption")
bh = load_module("app.agents.book_health")

@contextmanager
def patch(mod, **values):
    old = {key: getattr(mod, key) for key in values}
    try:
        for key, value in values.items():
            setattr(mod, key, value)
        yield
    finally:
        for key, value in old.items():
            setattr(mod, key, value)

def run(coro):
    return asyncio.run(coro)

OCC = "LULG260918P00004000"
WHEEL = dict(id="wheel", user_id="B", underlying="LULG", strike=4,
             expiration="2026-09-18", option_type="put", status="open",
             strategy="wheel_csp", contracts=1,
             notes="Placed via Alpaca; occ=" + OCC)
POSITION = dict(symbol=OCC, asset_class="us_option", qty="-1",
                avg_entry_price="0.1", current_price="0.3", market_value="-30")

class Client:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
    def table(self, name):
        client = self
        class Query:
            def __init__(self):
                self.filters = {}
            def select(self, *a): return self
            def eq(self, key, val):
                self.filters[key] = val
                return self
            def limit(self, *a): return self
            def execute(self):
                client.calls.append((name, dict(self.filters)))
                if name == "options_positions" and client.fail:
                    raise RuntimeError("ledger unavailable")
                rows = [WHEEL] if name == "options_positions" else []
                return SimpleNamespace(data=[r for r in rows if all(r.get(k) == v for k,v in self.filters.items())])
        return Query()

def test_ownership_is_the_same_book_and_short_side():
    c = Client()
    assert run(own.managed_option_keys(c, "B")) == {(OCC, "short")}
    assert run(own.managed_option_keys(c, "A")) == set()
    assert c.calls[0][1] == {"user_id": "B", "status": "open"}

def test_modeled_or_closed_wheel_rows_cannot_claim_broker_positions():
    assert own.broker_option_keys([{**WHEEL, "notes": "modeled"}]) == set()
    assert own.broker_option_keys([{**WHEEL, "status": "closed_manual"}]) == set()

def test_failed_ownership_read_is_unknown():
    assert run(own.managed_option_keys(Client(fail=True), "B")) is None

def test_adoption_does_not_create_a_second_wheel_manager():
    async def positions(uid, **kw):
        assert uid == "B"
        return [POSITION]
    with patch(ad, _supabase=lambda: Client()), patch(ad.book_scope, positions=positions), quiet_activity_log():
        result = run(ad.adopt_for_book("B"))
    assert result["adopted"] == []
    assert result["skipped"][0]["why"] == "managed by the Wheel ledger"

def test_adoption_does_not_guess_when_ownership_read_fails():
    async def positions(uid, **kw): return [POSITION]
    with patch(ad, _supabase=lambda: Client(True)), patch(ad.book_scope, positions=positions), quiet_activity_log():
        result = run(ad.adopt_for_book("B"))
    assert result["adopted"] == []
    assert "unreadable" in result["skipped"][0]["why"]

def test_health_counts_the_wheel_row_as_a_manager():
    async def positions(uid, **kw): return [POSITION]
    async def notify(*args, **kw):
        raise AssertionError("managed option must not alarm")
    with patch(bh.book_scope, positions=positions), patch(bh, notify=notify), \
            patch(qa, shield_due=lambda uid: False, due=lambda uid: False):
        agent = bh.BookHealthAgent()
        agent._open_findings = {}
        findings = run(agent._check_book(Client(), "B", "Book B"))
    assert findings == []

def test_qa_never_autobooks_an_option_owned_by_the_wheel():
    async def empty(*a): return []
    async def options(*a): return [WHEEL]
    async def forbidden(*a, **k): raise AssertionError("second manager attempted")
    with patch(qa, _rows_for_book=empty, _option_rows_for_book=options, _handle_orphan=forbidden), quiet_activity_log():
        report = run(qa._inspect(Client(), "B", [POSITION], [], [], qa.blank_report("B"), dry_run=False))
    assert report["booked"] == 0

def test_qa_defers_when_the_other_ledger_cannot_be_read():
    async def empty(*a): return []
    async def unknown(*a): return None
    with patch(qa, _rows_for_book=empty, _option_rows_for_book=unknown), quiet_activity_log():
        report = run(qa._inspect(Client(), "B", [POSITION], [], [], qa.blank_report("B"), dry_run=False))
    assert "option ownership read failed" in report["skipped_reason"]

def _protect(sequence, fail_oco=False):
    answers = iter(sequence)
    posted, deleted = [], []
    async def get(path, **kw):
        if path.startswith("/v2/positions/"):
            return next(answers)
        return []
    async def post(path, body, **kw):
        posted.append(body)
        return (None, "OCO refused") if fail_oco else ({"id": "protection"}, None)
    async def delete(path, **kw): deleted.append(path)
    with patch(alp, _get=get, _post=post, _delete=delete), quiet_activity_log():
        result = run(alp.ensure_short_protection("XOM", 5, 166.2, target=162.25))
    return result, posted, deleted

def test_xom_flat_or_long_or_unknown_never_arms_a_buy():
    for position in (None, {}, {"qty": "0"}, {"qty": "5"}, {"qty": "NaN"}, {"qty": "bad"}):
        result, posted, deleted = _protect([position])
        assert not result[0] and not posted and not deleted, (position, result)

def test_short_fills_before_oco_submission_no_order_is_created():
    result, posted, deleted = _protect([{"qty": "-5"}, None, None, None])
    assert not result[0] and posted == []

def test_oco_refusal_followed_by_a_flat_position_never_places_fallback():
    result, posted, deleted = _protect([{"qty": "-5"}, {"qty": "-5"}, None], fail_oco=True)
    assert not result[0] and len(posted) == 1
    assert posted[0]["order_class"] == "oco"

def test_short_protection_clamps_to_remaining_available_quantity():
    result, posted, deleted = _protect([{"qty": "-5"}, {"qty": "-3", "qty_available": "-2"}])
    assert result[0] and posted[0]["qty"] == "2"

def test_short_protection_does_not_cancel_a_target_on_unknown_position():
    touched = []
    async def get(path, **kw):
        if path.startswith("/v2/orders"):
            return [{"id": "target", "type": "limit", "side": "buy"}]
        return None
    async def delete(path, **kw): touched.append(path)
    with patch(alp, _get=get, _delete=delete), quiet_activity_log():
        result = run(alp.ensure_short_protection("XOM", 5, 166.2, target=162.25))
    assert not result[0] and touched == []



def test_isolated_server_diagnostics_use_each_books_binding():
    relay = load_module("app.runtime.ops_relay")
    accounts = load_module("app.brokers.accounts")
    current, calls = [], []
    @contextmanager
    def bound(uid):
        current.append(uid)
        try: yield
        finally: current.pop()
    async def read():
        calls.append(current[-1])
        return []
    books = [SimpleNamespace(account_key="A", account_id="first"),
             SimpleNamespace(account_key="B", account_id="second")]
    with patch(accounts, load_accounts=lambda: books, bind_for_user=bound), \
            patch(alp, get_positions_strict=read, get_open_orders_all_strict=read):
        result = relay._read_diagnostics()
    assert calls == ["A", "A", "B", "B"]
    assert "first positions: rows=0" in result
    assert "second open_orders: rows=0" in result

def test_isolated_diagnostics_preserve_failed_read_as_unknown():
    relay = load_module("app.runtime.ops_relay")
    accounts = load_module("app.brokers.accounts")
    @contextmanager
    def bound(uid): yield
    async def read(): return None
    books = [SimpleNamespace(account_key="B", account_id="second")]
    with patch(accounts, load_accounts=lambda: books, bind_for_user=bound), \
            patch(alp, get_positions_strict=read, get_open_orders_all_strict=read,
                  last_read_error=lambda: "ConnectTimeout"):
        result = relay._read_diagnostics()
    assert "unreadable: ConnectTimeout" in result
    assert "rows=0" not in result



def test_broker_tls_setup_is_off_loop_cached_and_still_verified():
    import httpx
    import threading
    calls, contexts = [], []
    main_thread = threading.get_ident()
    context = object()
    def build(**kwargs):
        assert threading.get_ident() != main_thread, "certificate loading blocked the engine"
        assert kwargs == {"verify": True, "trust_env": True}
        calls.append(kwargs)
        return context
    class Client:
        def __init__(self, **kwargs):
            contexts.append(kwargs["verify"])
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, *a, **k):
            return SimpleNamespace(status_code=200, json=lambda: [])
    async def reads():
        return await asyncio.gather(*(alp._get("/v2/positions") for _ in range(5)))
    with patch(httpx, create_ssl_context=build, AsyncClient=Client), \
            patch(alp, _TLS_CONTEXT=None, alpaca_configured=lambda: True,
                  _headers_for=lambda token: {}, _base_url=lambda: "https://paper-api.alpaca.markets"):
        assert run(reads()) == [[], [], [], [], []]
    assert len(calls) == 1
    assert contexts == [context] * 5

def test_tls_setup_failure_is_a_failed_read_not_empty_or_unverified():
    import httpx
    def build(**kwargs): raise RuntimeError("certificate configuration unavailable")
    def client(**kwargs): raise AssertionError("must not connect without verified TLS")
    with patch(httpx, create_ssl_context=build, AsyncClient=client), \
            patch(alp, _TLS_CONTEXT=None, alpaca_configured=lambda: True), quiet_activity_log():
        assert run(alp._get("/v2/positions")) is None

if __name__ == "__main__":
    from tests._bootstrap import run_tests
    raise SystemExit(run_tests(globals()))
