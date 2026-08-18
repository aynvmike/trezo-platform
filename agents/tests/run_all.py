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

SUITES = sorted(p.stem for p in HERE.glob("test_*.py"))


def main() -> int:
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
        from _bootstrap import run_tests
        if run_tests(dict(vars(mod))):
            failed.append(name)
    print("\n" + "=" * 60)
    if failed:
        print(f"FAILED suites: {', '.join(failed)}")
        return 1
    print(f"all green across {len(SUITES)} suites")
    return 0


if __name__ == "__main__":
    sys.exit(main())
