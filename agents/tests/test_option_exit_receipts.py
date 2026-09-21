"""Option exits persist intent and only account broker-confirmed executions."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config

stub_config()
exits = load_module("app.paper.option_exit")
alpaca = load_module("app.brokers.alpaca")
accounts = load_module("app.brokers.accounts")
route = load_module("app.brokers.route_guard")
broker_exit = load_module("app.paper.broker_exit")
NOW = datetime(2026, 9, 18, 14, tzinfo=timezone.utc)
OCC = "AGNC261016P00009500"


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def _row(**changes):
    return {"id": "option-1", "user_id": "book-3", "contracts": 2,
            "net_premium_usd": 80, "opened_at": "2026-09-10T14:00:00Z",
            "broker_exit_pending": None, **changes}


def _order(**changes):
    return {"id": "exit-1", "symbol": OCC, "side": "buy", "status": "accepted",
            "filled_qty": "0", "filled_avg_price": None,
            "created_at": NOW.isoformat(), "filled_at": None, **changes}


class Database:
    def __init__(self, *, fail_claim=False, fail_record=False):
        self.pending = None
        self.calls = []
        self.fail_claim, self.fail_record = fail_claim, fail_record

    def rpc(self, name, args):
        def execute():
            self.calls.append((name, deepcopy(args)))
            if name == "claim_option_broker_exit":
                if self.fail_claim:
                    raise RuntimeError("schema unavailable")
                claimed = self.pending == args["p_expected_pending"]
                if claimed:
                    self.pending = deepcopy(args["p_pending"])
                return SimpleNamespace(data={"ok": True, "claimed": claimed})
            assert name == "record_option_broker_close"
            if self.fail_record:
                raise RuntimeError("transaction unavailable")
            receipt = args["p_receipt"]
            terminal = receipt["status"] in ("filled", "canceled", "expired")
            if terminal:
                self.pending = None
            return SimpleNamespace(data={"ok": True, "pending": not terminal,
                                         "fill_price": float(receipt["filled_avg_price"]),
                                         "realized_pnl_usd": 20})
        return SimpleNamespace(execute=execute)


@contextmanager
def _seams(submission=None, poll=None, held_quantity=-2):
    seen = {"submits": 0, "reads": 0, "bound": None}
    @contextmanager
    def bind(uid):
        prior = seen["bound"]
        seen["bound"] = uid
        try:
            yield object()
        finally:
            seen["bound"] = prior
    async def submit(*args, **kwargs):
        assert seen["bound"] == "book-3"
        seen["submits"] += 1
        if isinstance(submission, Exception):
            raise submission
        return _order() if submission is None else submission, None
    async def read(order_id, **kwargs):
        assert seen["bound"] == "book-3" and order_id == "exit-1"
        seen["reads"] += 1
        if isinstance(poll, Exception):
            raise poll
        return _order() if poll is None else poll, None
    async def holdings(**kwargs):
        return None if held_quantity is None else [{"symbol": OCC, "qty": str(held_quantity)}]
    with ExitStack() as stack:
        for mod, changes in (
            (exits, {"datetime": Clock}),
            (accounts, {"bind_for_user": bind, "should_skip_unresolved": lambda uid: False}),
            (route, {"check_route": lambda uid: (True, "okay")}),
            (broker_exit, {"_bound_book_verified": lambda uid, account: True}),
            (alpaca, {"submit_option_order": submit, "get_order_strict": read,
                      "get_option_positions_strict": holdings}),
        ):
            for key, value in changes.items():
                stack.enter_context(patch.object(mod, key, value))
        yield seen


def _request(db, row):
    return asyncio.run(exits.settle_or_request_option_close(
        db, row, symbol=OCC, side="buy", quantity=1, limit_price=.11))


def _poll(db):
    row = _row(broker_exit_pending=deepcopy(db.pending))
    return asyncio.run(exits.settle_or_request_option_close(db, row))


def test_accepted_option_exit_does_not_book_a_fill_and_restart_never_resubmits():
    db = Database()
    with _seams() as seen:
        result = _request(db, _row())
        assert result.pending and not result.ok
        assert db.pending["order_id"] == "exit-1"
        result = _poll(db)
        assert result.pending and seen["submits"] == 1 and seen["reads"] == 1
    assert all(name == "claim_option_broker_exit" for name, _ in db.calls)


def test_actual_option_fill_price_reaches_atomic_recorder_not_submission_limit():
    db = Database()
    filled = _order(status="filled", filled_qty="1", filled_avg_price="0.08", filled_at=NOW.isoformat())
    with _seams(poll=filled):
        _request(db, _row())
        result = _poll(db)
    assert result.ok and not result.pending and result.fill_price == .08
    records = [args for name, args in db.calls if name == "record_option_broker_close"]
    assert records[0]["p_receipt"]["filled_avg_price"] == "0.08"
    assert db.pending is None


def test_missing_atomic_schema_prevents_option_submission():
    db = Database(fail_claim=True)
    with _seams() as seen:
        result = _request(db, _row())
    assert seen["submits"] == 0 and not result.ok


def test_drifted_quantity_or_direction_cannot_expand_option_exposure():
    for qty in (None, 1, 2, -1, float("nan")):
        db = Database()
        with _seams(held_quantity=qty) as seen:
            result = _request(db, _row())
        assert not result.ok and seen["submits"] == 0
        assert db.pending is None


def test_submission_timeout_keeps_unknown_intent_and_never_retries():
    db = Database()
    with _seams(submission=RuntimeError("timeout")) as seen:
        _request(db, _row())
        result = _poll(db)
    assert db.pending["order_id"] is None
    assert result.pending and seen["submits"] == 1 and seen["reads"] == 0


def test_receipt_read_failure_keeps_pending_option_intent():
    db = Database()
    with _seams(poll=RuntimeError("unavailable")) as seen:
        _request(db, _row())
        result = _poll(db)
    assert result.pending and db.pending["order_id"] == "exit-1"
    assert seen["submits"] == 1


def test_rejected_unfilled_option_close_releases_intent_without_a_profit():
    db = Database()
    with _seams(poll=_order(status="rejected", filled_qty="0.000000")):
        _request(db, _row())
        result = _poll(db)
    assert not result.ok and not result.pending and db.pending is None
    assert all(name == "claim_option_broker_exit" for name, _ in db.calls)


def test_done_for_day_is_pending_and_cannot_submit_another_option_exit():
    db = Database()
    with _seams(poll=_order(status="done_for_day")) as seen:
        _request(db, _row())
        result = _poll(db)
    assert result.pending and db.pending and seen["submits"] == 1


def test_wrong_option_receipt_or_excess_quantity_never_reaches_accounting():
    for changes in ({"id": "wrong"}, {"symbol": "WRONG"}, {"side": "sell"},
                    {"filled_qty": "2"}, {"filled_qty": "NaN"},
                    {"filled_at": "2026-09-17T14:00:00Z"}):
        db = Database()
        order = _order(status="filled", filled_qty="1", filled_avg_price=".08",
                       filled_at=NOW.isoformat())
        order.update(changes)
        with _seams(poll=order):
            _request(db, _row())
            result = _poll(db)
        assert not result.ok and result.pending
        assert not [name for name, _ in db.calls if name == "record_option_broker_close"]


def test_failed_accounting_keeps_exact_option_order_id_for_retry():
    db = Database(fail_record=True)
    filled = _order(status="filled", filled_qty="1", filled_avg_price=".08", filled_at=NOW.isoformat())
    with _seams(poll=filled) as seen:
        _request(db, _row())
        result = _poll(db)
    assert not result.ok and result.pending and db.pending["order_id"] == "exit-1"
    assert seen["submits"] == 1


def test_record_result_preserves_duplicate_and_remaining_inventory():
    async def duplicate_rpc(*args):
        return {"ok": True, "duplicate": True, "remaining_qty": 1,
                "fill_price": .08, "realized_pnl_usd": 0,
                "pending": True, "pnl_provisional": True}
    filled = _order(status="partially_filled", filled_qty="1", filled_avg_price=".08",
                    filled_at=NOW.isoformat())
    with patch.object(exits, "_rpc", duplicate_rpc):
        result = asyncio.run(exits.record_option_receipt(Database(), _row(), filled))
    assert result.ok and result.duplicate and result.pending
    assert result.remaining_qty == 1 and result.pnl_provisional
    assert result.broker_order_id == "exit-1"


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
