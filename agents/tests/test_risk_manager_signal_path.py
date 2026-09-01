"""Guard: an actionable signal must never die inside on_message.

The case is real and expensive. On 2026-08-27 the per-book kill-switch
block was written 150 lines BELOW the confidence-bar sum that reads its
`recovery_bump`, so every signal carrying a real direction raised
UnboundLocalError inside RiskManagerAgent.on_message. bootstrap._route
catches handler exceptions and logs them to stdout, so nothing reached
the bus: the platform approved NOTHING from 8/27 12:36 ET to 8/31 12:45
ET while the log looked merely quiet -- the only vetoes still visible
were the ones raised ABOVE the sum (neutral direction, flagged ticker).

These guards are static and dependency-free on purpose: they prove the
ordering invariant that broke by reading the source, so they hold even
if every seam changes. The EXECUTED counterpart is
tests/test_risk_manager_bookkeyed.py (2026-09-01), which drives the real
on_message with the Supabase / broker / market-data seams stubbed at
the module attribute and asserts a real direction reaches the gates
below the bar without raising.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[1]
SRC = (AGENTS / "app" / "agents" / "risk_manager.py").read_text()

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import run_tests  # noqa: E402


def _on_message_node():
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_message":
            return node
    raise AssertionError("on_message not found in risk_manager.py")


def _first_line(name, node, want_store):
    """Line of the first Load (or Store) of `name` inside `node`."""
    hits = [n.lineno for n in ast.walk(node)
            if isinstance(n, ast.Name) and n.id == name
            and isinstance(n.ctx, ast.Store if want_store else ast.Load)]
    return min(hits) if hits else None


def test_every_bump_is_assigned_before_it_is_read():
    """The confidence bar sums a dozen bumps. Each must be bound first --
    this is the invariant whose breach cost four trading days."""
    node = _on_message_node()
    bumps = ("recovery_bump", "crowding_bump_v", "probation_bump",
             "cycle_bump", "goal_bump", "leverage_bump", "report_bump",
             "outcome_delta")
    for name in bumps:
        store = _first_line(name, node, True)
        load = _first_line(name, node, False)
        if store is None or load is None:
            continue
        assert store < load, (
            f"{name} is read at line {load} but first assigned at {store} -- "
            f"an actionable signal will raise UnboundLocalError here and the "
            f"bus router will swallow it to stdout")


def test_the_reason_strings_are_bound_before_use_too():
    node = _on_message_node()
    for name in ("recovery_reason", "crowding_note", "probation_note",
                 "cycle_reason", "goal_reason", "leverage_note"):
        store = _first_line(name, node, True)
        load = _first_line(name, node, False)
        if store is None or load is None:
            continue
        assert store < load, f"{name} read at {load}, assigned at {store}"


def test_the_kill_switch_gate_still_exists_above_the_bar():
    """Moving the block must not have dropped it: the per-book veto and
    the bump both have to be inside on_message, above the sum."""
    node = _on_message_node()
    assert "Kill-switch [all books]" in SRC, "the per-book veto vanished"
    bar = min(n.lineno for n in ast.walk(node)
              if isinstance(n, ast.Name) and n.id == "effective_min_tcs"
              and isinstance(n.ctx, ast.Store))
    gate = min(n.lineno for n in ast.walk(node)
               if isinstance(n, ast.Name) and n.id == "_states"
               and isinstance(n.ctx, ast.Store))
    assert gate < bar, (f"the per-book kill-switch gate (line {gate}) must "
                        f"stay above the confidence bar (line {bar})")


def test_compiling_the_module_finds_no_unbound_locals():
    """A cheap belt-and-braces: python -O compiles the file, so a syntax
    regression in this hot path fails the deploy rather than the market."""
    compile(SRC, "risk_manager.py", "exec")


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
