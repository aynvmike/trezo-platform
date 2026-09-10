"""Offline proof of the composed-rule research cycle and durable queue."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config

stub_config()
core = load_module("app.research.core")
storage = load_module("app.research.store")
cycle = load_module("app.research.cycle")


@contextmanager
def _patched(target, **attrs):
    previous = {key: getattr(target, key) for key in attrs}
    try:
        for key, value in attrs.items():
            setattr(target, key, value)
        yield
    finally:
        for key, value in previous.items():
            setattr(target, key, value)


def _candles(count=500, drift=0.006):
    out = []
    price = 100.0
    start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    for index in range(count):
        opening = price
        price *= 1 + drift
        out.append({"timestamp": (start + timedelta(days=index)).isoformat(),
                    "open": opening, "high": max(opening, price) * 1.003,
                    "low": min(opening, price) * 0.997, "close": price})
    return out


def _run(path, **overrides):
    args = {"book_id": "book-a", "symbol": "AMD", "candles": _candles(),
            "starting_capital": 1000, "commission_bps": 10, "slippage_bps": 5,
            "cycle_key": "day-one"}
    args.update(overrides)
    return cycle.run_cycle(path, **args)


def _snapshot(equity=1000, **overrides):
    snapshot = {"book_id": "book-a", "source": "alpaca_paper_account", "currency": "USD",
                "equity_usd": equity, "observed_at": "2026-01-01T12:00:00+00:00",
                "account_fingerprint": "a" * 64}
    snapshot.update(overrides)
    return snapshot


def _dynamic(path, equity=1000, **overrides):
    args = {"starting_capital": equity, "capital_basis": "broker_equity",
            "capital_snapshot": _snapshot(equity)}
    args.update(overrides)
    return _run(path, **args)


def _assert_raises(kind, fn):
    try:
        fn()
    except kind:
        return
    raise AssertionError(f"expected {kind.__name__}")


def _query(path, sql):
    # WINDOWS GATE TRUTH (2026-09-08): `with sqlite3.connect(...)` commits
    # on exit but does NOT close, so every query here left the database
    # file open. Linux happily deletes an open file, so the suite was
    # green in the container that wrote it -- and RED on the server,
    # where TemporaryDirectory cleanup cannot remove a file a handle
    # still locks. That one leak rolled back a whole deploy. The store
    # under test closes its own connections (store.py, finally: close);
    # the suite must hold itself to the same standard.
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def test_actual_cycle_records_all_variants_and_repeated_cycle_is_idempotent():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "nested" / "research.sqlite3"
        first = _run(path)
        assert first["status"] == "completed", first
        assert len(first["trials"]) == 4
        assert len({trial["candidate_id"] for trial in first["trials"]}) == 4
        assert first["execution_enabled"] is False
        assert first["forward_evidence_required"] is True
        assert first["profitability_verified"] is False
        second = _run(path)
        assert second["cached"] is True
        assert {**second, "cached": False} == first
        assert _query(path, "SELECT COUNT(*) FROM research_jobs") == [(1,)]
        assert _query(path, "SELECT COUNT(*) FROM research_trials") == [(4,)]
        assert _query(path, "SELECT attempts FROM research_jobs") == [(1,)]
        json.dumps(first, allow_nan=False)


def test_scope_separates_books_capital_and_cost_assumptions():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.sqlite3"
        results = [_run(path), _run(path, book_id="book-b"),
                   _run(path, starting_capital=5000), _run(path, commission_bps=20)]
        assert all(result["status"] == "completed" for result in results)
        assert len({result["job_id"] for result in results}) == 4
        assert _query(path, "SELECT COUNT(*) FROM research_trials") == [(16,)]
        a_ids = {trial["candidate_id"] for trial in results[0]["trials"]}
        b_ids = {trial["candidate_id"] for trial in results[1]["trials"]}
        assert not a_ids & b_ids


def test_same_cycle_key_keeps_first_snapshot_immutable():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.sqlite3"
        first = _run(path)
        second = _run(path, candles=_candles(drift=-0.003))
        assert second["dataset_hash"] == first["dataset_hash"]
        assert second["cached"] is True
        assert second["trials"] == first["trials"]


def test_next_cycle_continues_training_lineage_and_mutates_real_rules():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.sqlite3"
        first = _run(path)
        second = _run(path, cycle_key="day-two")
        assert second["status"] == "completed", second
        assert second["continuation"]["source_job_id"] == first["job_id"]
        prior_ids = {trial["candidate_id"] for trial in first["trials"]}
        assert second["continuation"]["candidate_id"] in prior_ids
        assert len(second["trials"]) == 4
        for result in (first, second):
            specs = {trial["candidate_id"]: trial["spec"] for trial in result["trials"]}
            for trial in result["trials"][2:]:
                assert trial["parent_id"] in specs
                parent = dict(specs[trial["parent_id"]])
                child = dict(trial["spec"])
                parent.pop("parent_id")
                child.pop("parent_id")
                assert parent != child, "a lineage-only hash is not a changed rule"
        assert _query(path, "SELECT COUNT(*) FROM research_trials") == [(8,)]


def test_validation_changes_cannot_change_generated_candidates():
    original = _candles()
    changed = _candles()
    split = int(len(changed) * 0.7)
    # Radically different holdout, byte-identical training window.
    price = changed[split - 1]["close"]
    for bar in changed[split:]:
        opening = price
        price *= 0.94
        bar.update(open=opening, high=opening * 1.001, low=price * 0.999, close=price)
    with tempfile.TemporaryDirectory() as directory:
        first = _run(Path(directory) / "first.sqlite3", candles=original)
        second = _run(Path(directory) / "second.sqlite3", candles=changed)
        assert first["status"] == second["status"] == "completed"
        assert [t["spec"] for t in first["trials"]] == [t["spec"] for t in second["trials"]]
        assert [t["train"] for t in first["trials"]] == [t["train"] for t in second["trials"]]


def test_refinement_rejects_holdout_evidence_and_changes_saturated_rules():
    parent = core.Candidate("book-a", "AMD", "breakout_high", trend_bars=60, entry_bars=30)
    evidence = {"phase": "train", "candidate_id": parent.candidate_id, "net_pnl_usd": 20}
    children = core.refine(parent, evidence)
    for child in children:
        assert child.parent_id == parent.candidate_id
        assert replace(child, parent_id=parent.parent_id) != parent
    _assert_raises(ValueError, lambda: core.refine(parent, {**evidence, "phase": "validation"}))
    _assert_raises(FrozenInstanceError, lambda: setattr(parent, "entry_rule", "anything"))
    _assert_raises(ValueError, lambda: core.Candidate("book-a", "AMD", "eval_python"))


def test_invalid_data_fails_before_creating_a_job():
    cases = [_candles(100)]
    duplicate = _candles()
    duplicate[21]["timestamp"] = duplicate[20]["timestamp"]
    cases.append(duplicate)
    naive = _candles()
    naive[0]["timestamp"] = "2022-01-01T00:00:00"
    cases.append(naive)
    bad_price = _candles()
    bad_price[1]["close"] = float("nan")
    cases.append(bad_price)
    bad_range = _candles()
    bad_range[2]["low"] = bad_range[2]["high"] + 1
    cases.append(bad_range)
    future = _candles()
    future[-1]["timestamp"] = "2999-01-01T00:00:00+00:00"
    cases.append(future)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.sqlite3"
        for candles in cases:
            _assert_raises(ValueError, lambda: _run(path, candles=candles))
        assert not path.exists()
        _assert_raises(ValueError, lambda: _run(path, commission_bps=-1))
        _assert_raises(ValueError, lambda: _run(path, starting_capital=True))


def test_next_bar_fills_costs_and_marked_equity_are_account_level():
    bars = core.normalize_candles(_candles())
    candidate = core.propose("book-a", "AMD")[0]
    free = core.replay(bars, candidate, core.Assumptions(1000, 0, 0), start=0, end=350, phase="train")
    cost = core.replay(bars, candidate, core.Assumptions(1000, 20, 5), start=0, end=350, phase="train")
    assert cost["trades"] > 3
    for trade in cost["trade_log"]:
        assert trade["entry_index"] == trade["decision_index"] + 1
        assert trade["entry_at"] > trade["decision_at"]
        assert trade["exit_index"] >= trade["entry_index"]
        assert trade["entry_fee"] > 0 and trade["exit_fee"] > 0
        expected = (trade["qty"] * (trade["exit_price"] - trade["entry_price"])
                    - trade["entry_fee"] - trade["exit_fee"])
        assert abs(expected - trade["net_pnl_usd"]) < 1e-9
    assert cost["net_pnl_usd"] < free["net_pnl_usd"]
    assert abs(cost["ending_equity"] - (1000 + sum(t["net_pnl_usd"] for t in cost["trade_log"]))) < 1e-7
    assert any(point["position_qty"] > 0 and point["equity"] > point["cash"] for point in cost["equity_curve"])
    assert cost["drawdown_basis"] == "marked_end_of_bar_equity"


def test_gap_stop_fills_at_opening_gap_not_the_unavailable_stop_price():
    bars = core.normalize_candles(_candles())
    candidate = core.propose("book-a", "AMD")[0]
    costs = core.Assumptions(1000, 10, 5)
    baseline = core.replay(bars, candidate, costs, start=0, end=350, phase="train")
    first = baseline["trade_log"][0]
    index = first["entry_index"] + 1
    opening = first["entry_price"] * 0.80
    bars[index].update(open=opening, high=opening * 1.01, low=opening * 0.99, close=opening)
    result = core.replay(bars, candidate, costs, start=0, end=350, phase="train")
    trade = result["trade_log"][0]
    assert trade["exit_reason"] == "gap_stop"
    assert abs(trade["exit_price"] - opening * 0.9995) < 1e-9
    assert trade["net_pnl_usd"] < 0
    assert result["max_drawdown_pct"] > 3


def test_losing_or_empty_results_never_activate():
    with tempfile.TemporaryDirectory() as directory:
        result = _run(Path(directory) / "research.sqlite3", candles=_candles(drift=-0.004))
        assert result["status"] == "completed"
        assert len(result["trials"]) == 4
        assert all(trial["state"] == "rejected" for trial in result["trials"]
                   if trial["spec"]["direction"] == "long")
        assert any(trial["train"]["net_pnl_usd"] > 0 for trial in result["trials"]
                   if trial["spec"]["direction"] == "short")
        assert all(trial["execution_enabled"] is False and trial["forward_evidence_required"]
                   for trial in result["trials"])


def test_atomic_claim_lease_recovery_and_bounded_retries():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.Store(Path(directory) / "research.sqlite3", lease_seconds=1, max_attempts=2)
        clock = type("Clock", (), {"time": staticmethod(lambda: 100.0)})
        with _patched(storage, time=clock):
            first = store.claim("job", "book-a", {"first": True})
            assert first["status"] == "claimed"
            assert store.claim("job", "book-a", {"first": False})["status"] == "busy"
            clock.time = staticmethod(lambda: 102.0)
            second = store.claim("job", "book-a", {"first": False})
            assert second["status"] == "claimed" and second["attempts"] == 2
            assert second["request"] == {"first": True}
            _assert_raises(storage.LeaseLost, lambda: store.fail("job", first["token"], "old worker"))
            store.fail("job", second["token"], "test failure")
            assert store.claim("job", "book-a", {})["status"] == "failed"
            _assert_raises(ValueError, lambda: store.claim("job", "book-b", {}))


def test_partial_cycle_failure_is_durable_and_retries_without_overwriting_trials():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.sqlite3"
        actual = cycle.replay
        calls = {"validation": 0}
        def fail_second_validation(*args, **kwargs):
            if kwargs["phase"] == "validation":
                calls["validation"] += 1
                if calls["validation"] == 2:
                    raise RuntimeError("deliberate test outage")
            return actual(*args, **kwargs)
        with _patched(cycle, replay=fail_second_validation):
            failed = _run(path)
        assert failed["status"] == "failed"
        assert _query(path, "SELECT COUNT(*) FROM research_trials") == [(1,)]
        first_trial = _query(path, "SELECT result_json FROM research_trials")[0][0]
        retried = _run(path)
        assert retried["status"] == "completed", retried
        assert _query(path, "SELECT COUNT(*) FROM research_trials") == [(4,)]
        assert first_trial in {row[0] for row in _query(path, "SELECT result_json FROM research_trials")}
        assert _query(path, "SELECT attempts FROM research_jobs") == [(2,)]


def test_holdout_is_not_used_to_select_cross_cycle_parent():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.sqlite3"
        first = _run(path)
        # Read-only assertion from stored results: continuation must be
        # the train winner even if the historical screen rejected it.
        expected = max(first["trials"], key=lambda trial: (trial["train"]["net_pnl_usd"], trial["candidate_id"]))
        second = _run(path, cycle_key="day-two")
        assert second["continuation"]["candidate_id"] == expected["candidate_id"]


def test_fixed_scenario_identity_and_legacy_completed_evidence_remain_compatible():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.sqlite3"
        first = _run(path)
        original_lineage = {"book_id": "book-a", "symbol": "AMD", "assumptions": first["assumptions"],
                            "policy_version": core.POLICY_VERSION}
        assert first["job_id"] == core.digest({**original_lineage, "cycle_key": "day-one"})
        assert first["capital_basis"] == "fixed_scenario" and first["capital_snapshot"] is None
        request = json.loads(_query(path, "SELECT request_json FROM research_jobs")[0][0])
        assert request["lineage_scope"] == core.digest(original_lineage)
        # Model a database written by the pre-metadata version. The new
        # reader must not alter its already completed historical evidence.
        legacy_result = {key: value for key, value in first.items()
                         if key not in {"capital_basis", "capital_snapshot"}}
        legacy_request = {key: value for key, value in request.items()
                          if key not in {"capital_basis", "capital_snapshot"}}
        connection = sqlite3.connect(path)   # closed below: see _query's note
        try:
            with connection:
                connection.execute(
                    "UPDATE research_jobs SET request_json=?, result_json=?",
                    (json.dumps(legacy_request), json.dumps(legacy_result)))
        finally:
            connection.close()
        cached = _run(path, capital_basis="fixed_scenario")
        assert {**cached, "cached": False} == legacy_result
        second = _run(path, cycle_key="day-two")
        assert second["continuation"]["source_job_id"] == first["job_id"]


def test_sqlite_inspections_close_handles_before_temporary_directory_cleanup():
    """Exercise the actual read/update tests with Windows handle semantics."""
    original_connect = sqlite3.connect
    original_tempdir = tempfile.TemporaryDirectory
    opened = {}
    counts = {"connections": 0, "cleanups": 0}

    class TrackedConnection(sqlite3.Connection):
        def __init__(self, path, *args, **kwargs):
            super().__init__(path, *args, **kwargs)
            counts["connections"] += 1
            self.handle_id = counts["connections"]
            opened[self.handle_id] = str(path)

        def close(self):
            super().close()
            opened.pop(self.handle_id, None)

    def connect(path, *args, **kwargs):
        return original_connect(path, *args, factory=TrackedConnection, **kwargs)

    class CheckedTemporaryDirectory(original_tempdir):
        def __exit__(self, *args):
            counts["cleanups"] += 1
            outstanding = [path for path in opened.values()
                           if Path(self.name) in Path(path).parents]
            try:
                assert not outstanding, "SQLite handles must close before directory cleanup"
            finally:
                super().__exit__(*args)

    with _patched(sqlite3, connect=connect), _patched(
            tempfile, TemporaryDirectory=CheckedTemporaryDirectory):
        test_actual_cycle_records_all_variants_and_repeated_cycle_is_idempotent()
        test_fixed_scenario_identity_and_legacy_completed_evidence_remain_compatible()
    assert counts["connections"] > 0 and counts["cleanups"] == 2
    assert not opened


def test_dynamic_same_key_freezes_equity_observation_and_all_completed_evidence():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.sqlite3"
        first = _dynamic(path)
        assert first["status"] == "completed", first
        frozen_request = _query(path, "SELECT request_json FROM research_jobs")[0][0]
        second = _dynamic(path, equity=1800, capital_snapshot=_snapshot(
            1800, observed_at="2026-01-01T16:00:00+00:00"), candles=_candles(drift=-0.003))
        assert second["cached"] is True
        assert {**second, "cached": False} == first
        assert second["assumptions"]["starting_capital"] == 1000
        assert second["capital_snapshot"] == _snapshot()
        assert _query(path, "SELECT request_json FROM research_jobs") == [(frozen_request,)]
        assert _query(path, "SELECT COUNT(*) FROM research_trials") == [(4,)]


def test_dynamic_new_cycles_retest_at_rising_and_falling_equity_with_train_lineage():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.sqlite3"
        previous = None
        for index, equity in enumerate((1000, 1800, 700)):
            result = _dynamic(path, equity=equity, cycle_key=f"day-{index}")
            assert result["status"] == "completed", result
            assert result["assumptions"]["starting_capital"] == equity
            assert result["capital_basis"] == "broker_equity"
            assert result["capital_snapshot"]["equity_usd"] == equity
            assert result["execution_enabled"] is False
            assert result["profitability_verified"] is False
            assert result["assumptions"]["position_fraction"] == 0.25
            for trial in result["trials"]:
                assert trial["train"]["starting_capital"] == equity
                assert trial["validation"]["starting_capital"] == equity
                assert trial["execution_enabled"] is False
            if previous is not None:
                expected = max(previous["trials"], key=lambda trial:
                               (trial["train"]["net_pnl_usd"], trial["candidate_id"]))
                assert result["continuation"]["source_job_id"] == previous["job_id"]
                assert result["continuation"]["candidate_id"] == expected["candidate_id"]
                replayed = next(trial for trial in result["trials"]
                                if trial["candidate_id"] == expected["candidate_id"])
                # Reused rule, new experiment: quantities scale down as well
                # as up, without increasing the allocation percentage.
                old_qty = expected["train"]["trade_log"][0]["qty"]
                new_qty = replayed["train"]["trade_log"][0]["qty"]
                old_capital = previous["assumptions"]["starting_capital"]
                ratio = equity / old_capital
                # Trade-log quantities are rounded to six decimal places.
                assert abs(new_qty - old_qty * ratio) < 1e-6 * (1 + ratio)
            previous = result
        assert _query(path, "SELECT COUNT(*) FROM research_jobs") == [(3,)]
        assert _query(path, "SELECT COUNT(*) FROM research_trials") == [(12,)]


def test_dynamic_lineage_isolates_account_book_symbol_costs_and_fixed_scenarios():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.sqlite3"
        first = _dynamic(path)
        variants = [
            {"capital_snapshot": _snapshot(account_fingerprint="b" * 64)},
            {"book_id": "book-b", "capital_snapshot": _snapshot(book_id="book-b")},
            {"symbol": "SPY"}, {"commission_bps": 20}, {"slippage_bps": 15},
            {"fixed_cost_usd": 5},
        ]
        results = [_dynamic(path, cycle_key="day-two", **variant) for variant in variants]
        results.append(_run(path, cycle_key="day-two"))
        assert len({result["job_id"] for result in [first, *results]}) == 8
        for result in results:
            assert result["status"] == "completed", result
            assert result["continuation"] is None
        assert _query(path, "SELECT COUNT(*) FROM research_trials") == [(32,)]


def test_dynamic_invalid_snapshots_fail_before_creating_any_job():
    snapshots = [None, [], {}, _snapshot(book_id="book-b"),
                 _snapshot(source="alpaca_live_account"), _snapshot(source="internal_ledger"),
                 _snapshot(currency="EUR"), _snapshot(equity=1200),
                 _snapshot(equity=True), _snapshot(equity=float("nan")),
                 _snapshot(equity=float("inf")), _snapshot(account_fingerprint=""),
                 _snapshot(account_fingerprint="broker-account-id"),
                 _snapshot(account_fingerprint="a" * 65),
                 _snapshot(account_fingerprint="a" * 63 + "G"),
                 _snapshot(observed_at="invalid"), _snapshot(observed_at="2026-01-01T12:00:00"),
                 _snapshot(observed_at="2999-01-01T12:00:00+00:00"),
                 _snapshot(observed_at=1234), _snapshot(account_id="raw-account-id")]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.sqlite3"
        for snapshot in snapshots:
            _assert_raises(ValueError, lambda: _dynamic(path, capital_snapshot=snapshot))
        for key in (None, "", " "):
            _assert_raises(ValueError, lambda: _dynamic(path, cycle_key=key))
        _assert_raises(ValueError, lambda: _run(path, capital_basis="projected_profit"))
        _assert_raises(ValueError, lambda: _run(path, capital_snapshot=_snapshot()))
        assert not path.exists()


def test_dynamic_retry_uses_original_capital_and_does_not_overwrite_partial_trials():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.sqlite3"
        actual = cycle.replay
        calls = {"validation": 0}
        def fail_second_validation(*args, **kwargs):
            if kwargs["phase"] == "validation":
                calls["validation"] += 1
                if calls["validation"] == 2:
                    raise RuntimeError("deliberate dynamic test outage")
            return actual(*args, **kwargs)
        with _patched(cycle, replay=fail_second_validation):
            failed = _dynamic(path)
        assert failed["status"] == "failed"
        assert failed["capital_snapshot"]["equity_usd"] == 1000
        first_trial = _query(path, "SELECT result_json FROM research_trials")[0][0]
        retried = _dynamic(path, equity=800)
        assert retried["status"] == "completed", retried
        assert retried["assumptions"]["starting_capital"] == 1000
        assert retried["capital_snapshot"]["equity_usd"] == 1000
        assert first_trial in {row[0] for row in _query(path, "SELECT result_json FROM research_trials")}
        assert _query(path, "SELECT attempts FROM research_jobs") == [(2,)]


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
