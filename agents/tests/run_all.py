"""Run every guard suite in one command.

Deploys check this before restarting the engine. The suites are
deliberately runnable in a bare checkout -- no .env, no broker keys, no
network -- so there is never a reason to skip them.

Run: python -m agents.tests.run_all
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from _bootstrap import run_tests, stub_config  # noqa: E402

SUITES = sorted(p.stem for p in HERE.glob("test_*.py"))

# GATE-04 (audit 2026-09-01): the gate used to report "all green across N
# suites" for whatever N the glob happened to find. A tests/ directory
# that vanished from a bad checkout, a rename that broke the test_*.py
# glob, or a pull that dropped the new suites would deploy green. Pin the
# floor at the suite count present when this was set (46 on 2026-09-01);
# `>=` because suites are added over time -- each addition may raise this
# number, nothing should ever lower it.
EXPECTED_MIN_SUITES = 46


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
    for name in SUITES:
        print(f"\n=== {name} " + "=" * max(0, 50 - len(name)))
        # Each suite runs in its own process-shared namespace but stubs
        # module attributes; importing them all in one process is fine
        # because every suite resets what it stubs (see _REAL/_reset).
        try:
            mod = importlib.import_module(f"tests.{name}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR importing: {type(e).__name__}: {e}")
            failed.append(name)
            continue
        # GATE-05: run_tests fails a suite that collects zero tests.
        if run_tests(dict(vars(mod))):
            failed.append(name)
    print("\n" + "=" * 60)
    if failed:
        print(f"FAILED suites: {', '.join(failed)}")
        return 1
    print(f"all green across {len(SUITES)} suites "
          f"(floor {EXPECTED_MIN_SUITES})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
