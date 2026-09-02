"""Load one runtime module without booting the whole agent runtime.

`app/runtime/__init__.py` wires the bus, the registry, the scheduler and
the agent base class together, so a plain `from app.runtime import
book_scope` drags in most of the platform -- and a guard test that needs
the platform to start is a guard test nobody runs.

These loaders register a stub package and exec the single module under
test straight from its file, so the guards run in a bare checkout: in a
pre-commit hook, in CI, on a laptop with no .env and no broker keys.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parents[1]

# 2026-09-02 (leak net, see run_all.py): activity_log.record appends to
# <repo>/logs/activity-<date>.jsonl unless TREZO_ACTIVITY_LOG_DIR points
# elsewhere, and ops_relay.push_log_tail mirrors that file into the live
# feed. run_all pins the dir to a fresh temp dir before anything imports;
# this covers the OTHER ways a suite runs (pytest on one file, `python -m
# tests.test_x`), so a suite that forgot to stub record writes to scratch
# on a laptop too, never to the checkout's live log. An operator who set
# the variable on purpose keeps it (a plain guard, not setdefault, so no
# stray temp dir is created when it is already set).
if "TREZO_ACTIVITY_LOG_DIR" not in os.environ:
    import atexit
    import shutil
    _scratch_activity_dir = tempfile.mkdtemp(prefix="trezo-tests-activity-")
    os.environ["TREZO_ACTIVITY_LOG_DIR"] = _scratch_activity_dir
    # Removed when the process ends: a stand-alone run must not litter the
    # temp dir any more than it may write the live log. run_all cleans the
    # one it makes itself.
    atexit.register(shutil.rmtree, _scratch_activity_dir, ignore_errors=True)


def _stub_package(name: str, path: Path) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = mod
    return mod


def stub_config(**overrides) -> types.ModuleType:
    """Install a credential-free `app.config` BEFORE anything imports it.

    Several modules under test (`app.brokers.*`) read settings at import
    time, so on a machine without pydantic-settings or a .env the import
    dies and the guard never runs. Call this first in any test file that
    touches a broker module."""
    if "app.config" in sys.modules:
        return sys.modules["app.config"]
    _stub_package("app", AGENTS_DIR / "app")
    cfg = types.ModuleType("app.config")

    class _Settings:
        alpaca_api_key = "K" * 26
        alpaca_secret_key = "S" * 44
        alpaca_base_url = "https://paper-api.alpaca.markets"
        trezo_live_trading = False
        supabase_url = "https://stub.supabase.co"
        supabase_service_role_key = "stub"
        supabase_anon_key = "stub"

    for k, v in overrides.items():
        setattr(_Settings, k, v)
    cfg.get_settings = lambda: _Settings()
    cfg.settings = _Settings()
    sys.modules["app.config"] = cfg
    return cfg


def load_module(dotted: str) -> types.ModuleType:
    """load_module('app.runtime.book_scope') -> the module object."""
    if str(AGENTS_DIR) not in sys.path:
        sys.path.insert(0, str(AGENTS_DIR))
    if dotted in sys.modules:
        return sys.modules[dotted]
    parts = dotted.split(".")
    here = AGENTS_DIR
    for i in range(1, len(parts)):
        here = here / parts[i - 1]
        _stub_package(".".join(parts[:i]), here)
    target = AGENTS_DIR.joinpath(*parts).with_suffix(".py")
    spec = importlib.util.spec_from_file_location(dotted, target)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {dotted} from {target}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = mod
    spec.loader.exec_module(mod)
    parent = sys.modules.get(".".join(parts[:-1]))
    if parent is not None:
        setattr(parent, parts[-1], mod)
    return mod


def run_tests(namespace: dict) -> int:
    """Tiny runner so these files work with or without pytest.

    GATE-05 (audit 2026-09-01): a suite that collects ZERO test_ callables
    is a FAILURE, not a green. A renamed helper, tests hidden behind a bad
    `if`, or a file emptied by a merge used to print 'all green (0
    failures)' and let the deploy through. The collected count is printed
    per suite so the gate log shows what actually ran."""
    tests = [(name, fn) for name, fn in sorted(namespace.items())
             if name.startswith("test_") and callable(fn)]
    print(f"  collected {len(tests)} tests")
    if not tests:
        print("  FAIL  NO TESTS COLLECTED -- an empty suite is not a green suite")
        print("\nFAILED (1 failures)")
        return 1
    fails = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{'FAILED' if fails else 'all green'} ({fails} failures)")
    return 1 if fails else 0


@contextlib.contextmanager
def quiet_activity_log(*bound):
    """Capture app.agents.activity_log.record for ONE block instead of
    letting it append to the activity file; the real function goes back
    in `finally`.

    2026-09-02: five suites drove real code paths -- trade_execution's
    fail-closed branch, route_guard.record_mismatch, asset_policy's
    unknown-class receipt, relay_ingest's ingested/rejected lines --
    whose late `from app.agents.activity_log import record` resolved
    against the REAL module, so every deploy-gate run appended a 12-line
    burst of fixtures (AGNC execute_error, a book that does not exist,
    regime='bananas') to logs/activity-<date>.jsonl, the file ops_relay
    mirrors into the live feed. run_all.py now fails any suite that grows
    that file; this is the one-line fix for a suite it names.

    Yields the captured calls as (event, ticker, kwargs), the ticker
    normalised exactly as record() writes it (upper-cased), so a test can
    assert the row it EXPECTS was said -- a silent refusal is its own
    bug:

        with quiet_activity_log() as said:
            ...
        assert ("route_mismatch", "-") in [(e, t) for e, t, _ in said]

    Every call site in app/ imports record late, inside the function, so
    swapping the module attribute reaches all of them. A consumer that
    bound the name at import time (`from ... import record` at module
    level -- none exist today) is not reached that way; pass it as
    (module, "attr") in `bound` and it is swapped and restored too."""
    alog = load_module("app.agents.activity_log")
    said: list = []
    import inspect as _inspect
    _real_sig = _inspect.signature(getattr(alog, "record"))

    def _capture(*a, **kw):
        # Mirror the REAL signature (review 2026-09-02): a call that the real
        # record(event, ticker, *, tcs, strategy, reason, iv_rank, extra)
        # would reject with TypeError is rejected here too -- otherwise a
        # bad call site passes in tests and silently drops its row in prod
        # (every caller swallows the TypeError).
        bound_args = dict(_real_sig.bind(*a, **kw).arguments)
        event = bound_args.pop("event")
        ticker = bound_args.pop("ticker")
        said.append((str(event), str(ticker or "").upper(), bound_args))

    targets = [(alog, "record")] + [(m, a) for m, a in bound]
    saved = [(m, a, getattr(m, a)) for m, a in targets]
    try:
        for m, a, _ in saved:
            setattr(m, a, _capture)
        yield said
    finally:
        for m, a, real in saved:
            setattr(m, a, real)
