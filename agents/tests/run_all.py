"""Run every guard suite in one command.

Deploys check this before restarting the engine. The suites are
deliberately runnable in a bare checkout -- no .env, no broker keys, no
network -- so there is never a reason to skip them.

Run: python -m agents.tests.run_all
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

# LEAK NET (2026-09-02). Every app.agents.activity_log.record call appends
# to <repo>/logs/activity-<date>.jsonl, and ops_relay.push_log_tail
# mirrors that file into the live feed. The server runs THIS gate before
# every restart, so a suite that drives a real code path without stubbing
# record writes fabricated rows into the live log. On 2026-09-02 at 14:16
# the feed showed the 12-line burst that proved it: execute_error AGNC,
# route_mismatch 'book-that-does-not-exist', asset_policy_missing
# NONSENSE-CLASS / DOGECOIN_FUTURES_ON_THE_MOON / AUTO, RELAY_BRIEF_*
# from source "s" and regime='bananas' -- all test fixtures. Two nets:
#   1. the log dir is pinned to a fresh temp dir BEFORE any suite (or
#      _bootstrap) imports, so a leak can never reach the live file even
#      when a suite forgets to stub;
#   2. after each suite the temp dir is measured, and ANY growth fails
#      the suite -- so "all green across" (the string ops_relay keys on,
#      not the exit code) is never printed while a suite leaks, and the
#      leak gets fixed instead of quietly redirected forever.
# This assignment must precede the _bootstrap import: _bootstrap defaults
# the same variable for stand-alone runs, and the net has to measure the
# directory IT set.
_ACTIVITY_DIR = tempfile.mkdtemp(prefix="trezo-gate-activity-")
os.environ["TREZO_ACTIVITY_LOG_DIR"] = _ACTIVITY_DIR

from _bootstrap import run_tests, stub_config  # noqa: E402

SUITES = sorted(p.stem for p in HERE.glob("test_*.py"))

# GATE-04 (audit 2026-09-01): the gate used to report "all green across N
# suites" for whatever N the glob happened to find. A tests/ directory
# that vanished from a bad checkout, a rename that broke the test_*.py
# glob, or a pull that dropped the new suites would deploy green. Pin the
# floor at the suite count present when this was set (49 on 2026-09-01;
# it sat at 46 while three suites were added in the same wave --
# vf:gate-harness -- which is precisely the drift GATE-04 exists to catch,
# so RAISE THIS NUMBER in the same commit that adds a suite). `>=` because
# suites are added over time -- nothing should ever lower it.
EXPECTED_MIN_SUITES = 58

# The env vars the leak net depends on. A suite that changes either and
# does not put it back would blind the net for every suite after it
# (TREZO_ACTIVITY_LOG=0 makes record a no-op; a re-pointed dir is one the
# net is not measuring), so drift is a failure of THAT suite.
_NET_ENV = ("TREZO_ACTIVITY_LOG_DIR", "TREZO_ACTIVITY_LOG")
LEAK_HINT = "stub app.agents.activity_log.record"


def _activity_lines() -> list[str]:
    """Every line in the pinned activity dir, in file order. The files are
    append-only and date-named, so a suite's writes are always at the
    tail: slicing past the pre-suite count is exactly what it wrote."""
    out: list[str] = []
    for p in sorted(Path(_ACTIVITY_DIR).glob("*.jsonl")):
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                out.extend(ln.rstrip("\n") for ln in fh if ln.strip())
        except OSError:
            continue
    return out


def _leak_line(name: str, n: int) -> str:
    return f"activity-log leak: {name} wrote {n} line(s) -- {LEAK_HINT}"


def main() -> int:
    if len(SUITES) < EXPECTED_MIN_SUITES:
        print(f"GATE FAILURE: discovered {len(SUITES)} suites, expected at "
              f"least {EXPECTED_MIN_SUITES}. A suite has vanished from "
              f"{HERE} -- refusing to report green on a partial gate.")
        print("discovered: " + ", ".join(SUITES))
        return 1

    # GATE-08: the credential-free app.config stub is installed HERE,
    # unconditionally, before any suite imports. It used to depend on
    # whichever suite sorted first calling stub_config() itself; a suite
    # that imported app.brokers.* first without the stub would read the
    # real settings (and a real .env, if one is present on the host).
    stub_config()

    failed = []
    leaks: list[tuple[str, int]] = []
    for name in SUITES:
        print(f"\n=== {name} " + "=" * max(0, 50 - len(name)))
        # LEAK NET: measured from BEFORE the import -- module-level code
        # (stub_config(); load_module(...); a probe call) can record as
        # easily as a test body can.
        before = len(_activity_lines())
        env_before = {k: os.environ.get(k) for k in _NET_ENV}
        # Each suite runs in its own process-shared namespace but stubs
        # module attributes; importing them all in one process is fine
        # because every suite resets what it stubs (see _REAL/_reset).
        try:
            mod = importlib.import_module(f"tests.{name}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR importing: {type(e).__name__}: {e}")
            failed.append(name)
        else:
            # GATE-05: run_tests fails a suite that collects zero tests.
            if run_tests(dict(vars(mod))):
                failed.append(name)
        for k, v in env_before.items():
            if os.environ.get(k) != v:
                print(f"  FAIL  {name} left {k}={os.environ.get(k)!r} "
                      f"(was {v!r}) -- the leak net is blind after this; "
                      f"restore it in finally")
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
                if name not in failed:
                    failed.append(name)
        wrote = _activity_lines()[before:]
        if wrote:
            print(f"  FAIL  {_leak_line(name, len(wrote))}")
            for ln in wrote[:3]:
                print(f"        {ln[:220]}")
            leaks.append((name, len(wrote)))
            if name not in failed:
                failed.append(name)
    print("\n" + "=" * 60)
    if leaks:
        # Repeated at the tail on purpose: the ops row keeps only the last
        # 4000 chars of gate output, so the verdict must survive truncation.
        print("ACTIVITY-LOG LEAK NET: these suites wrote to the activity log; "
              "on the server those rows land in the live feed. Not green "
              "until fixed.")
        for name, n in leaks:
            print("  " + _leak_line(name, n))
    if failed:
        print(f"FAILED suites: {', '.join(failed)}")
        return 1
    # Final re-measure (review 2026-09-02): a row that lands AFTER the last
    # suite's post-measurement -- a straggling thread or an un-awaited task
    # -- must not slip past the net and let the green line print.
    _late = _activity_lines()
    if _late:
        print(f"  FAIL  activity-log leak: {len(_late)} line(s) landed after the "
              "last suite was measured -- a straggling thread or un-awaited "
              "task called app.agents.activity_log.record")
        return 1
    print(f"activity log: 0 lines written by {len(SUITES)} suites (net armed)")
    print(f"all green across {len(SUITES)} suites "
          f"(floor {EXPECTED_MIN_SUITES})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(_ACTIVITY_DIR, ignore_errors=True)
