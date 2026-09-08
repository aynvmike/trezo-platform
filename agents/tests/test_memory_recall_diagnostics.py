"""Actual recall consumer diagnostics, with no SDK setup, keys or network."""

from __future__ import annotations

import contextlib
import importlib.util
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import AGENTS_DIR, run_tests  # noqa: E402


def _isolated_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, AGENTS_DIR / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Private module names avoid replacing runtime modules during the sequential gate.
memory = _isolated_module("_trezo_mem0_diagnostics", "app/memory/mem0_client.py")
helpers = _isolated_module("_trezo_recall_diagnostics", "app/learning/recall_helpers.py")


@contextlib.contextmanager
def _patched(obj, **changes):
    missing = object()
    old = {name: getattr(obj, name, missing) for name in changes}
    try:
        for name, value in changes.items():
            setattr(obj, name, value)
        yield
    finally:
        for name, value in old.items():
            if value is missing:
                delattr(obj, name)
            else:
                setattr(obj, name, value)


@contextlib.contextmanager
def _world(search, *, available=True, allow_budget=True):
    # Skip __init__: this test never resolves credentials or imports the SDK.
    mem = object.__new__(memory.TrezoMemory)
    mem.user_id = "test-only"
    mem._available = available
    mem._client = types.SimpleNamespace(search=search)
    env = memory._os.environ
    key = "TREZO_MEM0_RECALL_TTL_SEC"
    old_ttl = env.get(key)
    env[key] = "180"
    replacement = types.ModuleType("app.memory")
    replacement.get_memory = lambda: mem
    replacements = {"app.memory": replacement, "app.memory.mem0_client": memory}
    saved_modules = {name: sys.modules.get(name) for name in replacements}
    sys.modules.update(replacements)
    try:
        with _patched(memory, _SEARCH_CACHE={},
                      _budget_try_spend=lambda kind: allow_budget,
                      _budget_throttle_log=lambda kind: None), \
             _patched(memory.logger, warning=lambda *a, **k: None):
            yield mem
    finally:
        for name, previous in saved_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        if old_ttl is None:
            env.pop(key, None)
        else:
            env[key] = old_ttl


def _context():
    return helpers.recall_decision_context(ticker="TEST", strategy="fixture")


def _failed(**kwargs):
    raise RuntimeError("private error detail must not enter the payload")


def _not_called(**kwargs):
    raise AssertionError("search must not run")


def test_successful_empty_is_verified_empty_in_actual_consumer():
    calls = []

    def search(**kwargs):
        calls.append(kwargs)
        return {"results": []}

    with _world(search):
        result = _context()
    assert len(calls) == 2
    assert result["available"] and result["client_available"]
    assert result["retrieval_succeeded"]
    assert result["retrieval_state"] == "ok_empty"
    assert result["last_success_at"] is not None
    assert result["n_decisions"] == result["n_outcomes"] == 0
    assert result["summary"] == "No similar past setups in memory yet."
    assert all(r["state"] == "ok_empty" and r["source"] == "api"
               for r in result["recall_receipts"].values())


def test_failed_search_is_not_reported_as_no_past_setups():
    with _world(_failed):
        result = _context()
    # Legacy available remains true so Risk Manager includes these diagnostics.
    assert result["available"]
    assert not result["retrieval_succeeded"]
    assert result["retrieval_state"] == "request_failed"
    assert result["last_success_at"] is None
    assert "request failed" in result["summary"]
    assert "No similar past setups" not in result["summary"]
    assert "private error detail" not in str(result)


def test_budget_block_is_visible_without_a_request_or_false_success():
    with _world(_not_called, allow_budget=False):
        result = _context()
    assert result["available"]
    assert not result["retrieval_succeeded"]
    assert result["retrieval_state"] == "budget_blocked"
    assert result["last_success_at"] is None
    assert "search budget" in result["summary"]
    assert all(r["source"] == "none" for r in result["recall_receipts"].values())


def test_unavailable_client_is_distinct_from_empty_and_budget():
    with _world(_not_called, available=False):
        result = _context()
    assert not result["available"]
    assert not result["retrieval_succeeded"]
    assert result["retrieval_state"] == "client_unavailable"
    assert result["last_success_at"] is None


def test_consumer_retains_partial_success_evidence():
    calls = []

    def search(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            return _failed()
        return {"results": [{"metadata": {"ticker": "TEST", "kind": "decision"}}]}

    with _world(search):
        result = _context()
    assert len(calls) == 2
    assert result["retrieval_state"] == "partial"
    assert not result["retrieval_succeeded"]
    assert result["n_decisions"] == 1 and result["n_outcomes"] == 0
    assert result["last_success_at"] is not None
    assert result["recall_receipts"]["decision"]["state"] == "ok"
    assert result["recall_receipts"]["outcome"]["state"] == "request_failed"
    assert "incomplete" in result["summary"]


def test_cached_empty_keeps_original_success_time_and_avoids_requests():
    calls = []

    def search(**kwargs):
        calls.append(kwargs)
        return {"results": []}

    with _world(search):
        first = _context()
        second = _context()
    assert len(calls) == 2
    assert second["retrieval_succeeded"]
    assert second["retrieval_state"] == "ok_empty"
    assert second["last_success_at"] == first["last_success_at"]
    for kind, receipt in second["recall_receipts"].items():
        assert receipt["source"] == "cache"
        assert receipt["last_success_at"] == first["recall_receipts"][kind]["last_success_at"]


def test_failed_refresh_preserves_known_previous_success_without_claiming_success():
    with _world(lambda **kwargs: {"results": []}) as mem:
        _context()
        for key, (_, rows) in list(memory._SEARCH_CACHE.items()):
            memory._SEARCH_CACHE[key] = (1.0, rows)
        mem._client.search = _failed
        result = _context()
    assert result["retrieval_state"] == "request_failed"
    assert not result["retrieval_succeeded"]
    assert result["last_success_at"] == "1970-01-01T00:00:01+00:00"


def test_legacy_list_reader_keeps_contract_and_request_parameters():
    row = {"metadata": {"ticker": "TEST", "kind": "outcome", "pnl_usd": 5}}
    calls = []

    def search(**kwargs):
        calls.append(kwargs)
        return [row]

    with _world(search) as mem:
        result = mem.recall_similar("test", limit=1, ticker="TEST", kind="outcome")
    assert result == [row]
    assert calls == [{"query": "test", "filters": {"user_id": "test-only"}, "limit": 3}]
    with _world(_failed) as mem:
        assert mem.recall_similar("test") == []


def test_invalid_service_response_is_failed_not_successfully_empty():
    for response in ({"unexpected": []}, {"results": "bad"}, {"results": [None]}):
        with _world(lambda **kwargs: response):
            result = _context()
        assert result["retrieval_state"] == "request_failed"
        assert not result["retrieval_succeeded"]
        assert result["last_success_at"] is None


def test_overlapping_searches_return_their_own_status():
    barrier = threading.Barrier(2)

    def search(**kwargs):
        barrier.wait(timeout=5)
        if kwargs["query"] == "failure":
            return _failed()
        return {"results": []}

    with _world(search) as mem:
        with ThreadPoolExecutor(max_workers=2) as pool:
            failed = pool.submit(mem.recall_similar_result, "failure")
            empty = pool.submit(mem.recall_similar_result, "empty")
            failed_result, empty_result = failed.result(), empty.result()
    assert failed_result.state == "request_failed"
    assert not failed_result.succeeded and failed_result.last_success_at is None
    assert empty_result.state == "ok_empty"
    assert empty_result.succeeded and empty_result.last_success_at is not None


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
