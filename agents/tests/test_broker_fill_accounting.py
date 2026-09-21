"""Receipt boundary tests: credential-free and compatible with tests.run_all.

Actual SQL rollback/idempotency cases run separately in
db/tests/broker_close_receipts.mjs using an isolated Postgres/PGlite database.
"""
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from tests._bootstrap import stub_config, load_module

stub_config()
engine = load_module("app.paper.engine")


@contextmanager
def client_patch(client):
    original = engine._supabase
    activity_log = load_module("app.agents.activity_log")
    original_record = activity_log.record
    engine._supabase = lambda: client
    activity_log.record = lambda *args, **kwargs: None
    try:
        yield
    finally:
        engine._supabase = original
        activity_log.record = original_record


class RPCClient:
    def __init__(self, result=None, fail=False):
        self.calls = []
        self.result = result
        self.fail = fail

    def rpc(self, name, args):
        self.calls.append((name, args))
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("a sensitive transport response must not escape")
        return SimpleNamespace(data=self.result)

    def table(self, name):
        raise AssertionError("Atomic receipt handling must never fall back to table writes")


def receipt(**overrides):
    return dict(id="broker-order", symbol="SOL/USD", side="sell", status="filled",
                filled_qty="2", filled_avg_price="105.40",
                filled_at="2026-09-18T13:08:00Z", **overrides)


def settle(data, client):
    with client_patch(client):
        return asyncio.run(engine.record_broker_close("book", "position", data, "stop"))


def test_receipt_forwards_exact_fill_without_modeled_slippage_or_fees():
    c = RPCClient(dict(ok=True, fill_price=105.40, realized_pnl_usd=-1.66,
                       remaining_qty=0, pending=False))
    result = settle(receipt(), c)
    assert result.ok and result.fill_price == 105.40
    assert result.broker_order_id == "broker-order"
    assert c.calls[0][0] == "record_broker_close"
    evidence = c.calls[0][1]["p_receipt"]
    assert evidence["filled_avg_price"] == "105.40"
    assert "fee_usd" not in evidence
    assert result.pnl_provisional and not result.fees_complete


def test_unknown_or_failed_rpc_preserves_pending_and_exposes_no_transport_text():
    for c in (RPCClient(None), RPCClient(fail=True)):
        result = settle(receipt(), c)
        assert not result.ok and result.pending
        assert "sensitive" not in result.error


def test_duplicate_receipt_returns_no_second_profit():
    c = RPCClient(dict(ok=True, duplicate=True, fill_price=105.4,
                       realized_pnl_usd=0, remaining_qty=3, pending=False))
    result = settle(receipt(), c)
    assert result.ok and result.duplicate and result.realized_pnl_usd == 0
    assert result.remaining_qty == 3


def test_confirmed_partial_fill_stays_pending_with_remaining_quantity():
    data = receipt()
    data["status"] = "partially_filled"
    c = RPCClient(dict(ok=True, fill_price=105.4, realized_pnl_usd=10,
                       remaining_qty=3, pending=True))
    result = settle(data, c)
    assert result.ok and result.pending and result.remaining_qty == 3


def test_accepted_order_without_fill_is_not_a_close():
    c = RPCClient()
    for changes in ({"status": "accepted"}, {"filled_qty": "0"}, {"filled_at": None}):
        result = settle({**receipt(), **changes}, c)
        assert not result.ok and result.pending
    assert c.calls == []


def test_nonfinite_negative_or_overprecision_receipts_never_reach_database():
    c = RPCClient()
    for changes in ({"filled_qty": "NaN"}, {"filled_avg_price": "Infinity"},
                    {"fee_usd": "-1"}, {"filled_qty": "0.0000000000001"}, {"filled_qty": "1e100"},
                    {"filled_at": "2026-09-18T13:08:00"}):
        assert not settle({**receipt(), **changes}, c).ok
    assert c.calls == []


def test_actual_cash_fee_is_forwarded_once_and_known_zero_is_not_missing():
    c = RPCClient(dict(ok=True, remaining_qty=0, fees_complete=True, pnl_provisional=False))
    result = settle({**receipt(), "fee_usd": "0"}, c)
    assert c.calls[0][1]["p_receipt"]["fee_usd"] == "0"
    assert result.fees_complete and not result.pnl_provisional


def test_legacy_quote_only_external_writes_fail_closed():
    c = RPCClient()
    with client_patch(c):
        full = asyncio.run(engine.record_external_close("book", "position", 96.87))
        part = asyncio.run(engine.record_external_partial_close("book", "position", 1, 96.87))
    assert not full.ok and not part.ok and full.pending and part.pending
    assert c.calls == []


def test_legacy_external_receipt_uses_same_transaction():
    c = RPCClient(dict(ok=True, remaining_qty=1, fill_price=105.4))
    with client_patch(c):
        result = asyncio.run(engine.record_external_partial_close(
            "book", "position", 999, 1, receipt=receipt()))
    assert result.ok
    assert c.calls[0][1]["p_receipt"]["filled_avg_price"] == "105.40"


class PositionClient:
    def table(self, name): return self
    def select(self, *args): return self
    def eq(self, *args): return self
    def maybe_single(self): return self
    def execute(self):
        return SimpleNamespace(data=dict(id="position", user_id="book", broker="alpaca", status="open"))
    def update(self, *args): raise AssertionError("Simulated broker update")


def test_simulation_full_partial_and_trim_paths_reject_broker_rows():
    with client_patch(PositionClient()):
        results = [asyncio.run(engine.close_position("book", "position", 96.87)),
                   asyncio.run(engine.close_partial_position("book", "position", 0.5, 96.87)),
                   asyncio.run(engine.trim_position("book", "position", 0.5, 96.87))]
    assert all(not result.ok for result in results)


class MergeClient:
    def __init__(self, old, conflict=False):
        self.old = old
        self.patch = None
        self.conflict = conflict
    def table(self, *args): return self
    def select(self, *args): return self
    def eq(self, *args): return self
    def is_(self, *args): return self
    def order(self, *args, **kwargs): return self
    def limit(self, *args): return self
    def execute(self): return SimpleNamespace(data=[] if self.patch and self.conflict else [self.old])
    def update(self, patch):
        self.patch = patch
        return self
    def insert(self, *args): raise AssertionError("Expected existing position merge")


def test_merge_cannot_certify_provisional_add_using_old_verified_flags():
    for old_verified, add_verified, expected in [(True,False,False),(False,True,False),(True,True,True)]:
        c = MergeClient(dict(id="position",quantity=2,entry_price=100,source_payload={
            "broker_order_id":"original-entry", "entry_basis_verified":old_verified,
            "entry_fees_known":old_verified,"entry_status":"filled",
            "broker_entry_notional":200}))
        with client_patch(c):
            result = asyncio.run(engine.record_external_position(
                "book","SOL","crypto","long",1,110,None,None,"crypto",source_payload={
                    "entry_basis_verified":add_verified,"entry_fees_known":add_verified,
                    "entry_status":"filled","broker_entry_notional":110},
                broker="alpaca",broker_order_id="new-entry"))
        assert result.ok
        payload = c.patch["source_payload"]
        assert payload["entry_basis_verified"] is expected
        assert payload["entry_fees_known"] is expected
        assert "broker_entry_notional" not in payload
        assert [r["broker_order_id"] for r in payload["broker_entry_components"]] == ["original-entry","new-entry"]


def test_merge_conflict_does_not_fall_back_to_duplicate_insert():
    c = MergeClient(dict(id="position",quantity=2,entry_price=100,source_payload={}), conflict=True)
    with client_patch(c):
        result = asyncio.run(engine.record_external_position(
            "book","SOL","crypto","long",1,110,None,None,"crypto",broker="alpaca",broker_order_id="add-order"))
    assert not result.ok and result.pending


class OutcomeClient:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.bounds = rows, fail, None
    def table(self, *args): return self
    def select(self, *args): return self
    def eq(self, *args): return self
    def order(self, *args): return self
    def range(self, start, end):
        self.bounds = start, end
        return self
    def execute(self):
        if self.fail: raise RuntimeError("query failed")
        if self.rows is None: return SimpleNamespace(data=None)
        start, end = self.bounds
        return SimpleNamespace(data=self.rows[start:end+1])


def test_profit_steps_count_unique_orders_and_all_pages_with_legacy_rows():
    rows = [dict(id=str(n), entry_payload={"broker_accounting":{"exit_order_id":"same-order"}}) for n in range(501)]
    rows.extend([dict(id="legacy"),dict(id="next",entry_payload={"broker_accounting":{"exit_order_id":"next-order"}})])
    with client_patch(OutcomeClient(rows)):
        assert asyncio.run(engine.count_profit_steps("book","position")) == 3


def test_profit_step_read_failure_is_unknown_not_zero():
    for client in (None, OutcomeClient(), OutcomeClient(fail=True)):
        with client_patch(client):
            assert asyncio.run(engine.count_profit_steps("book","position")) is None


if __name__ == "__main__":
    from tests._bootstrap import run_tests
    run_tests(globals())
