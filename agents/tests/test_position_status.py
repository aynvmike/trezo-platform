"""Guard test: code and schema must agree on what a status may be.

The bug (2026-07-02 -> 2026-08-17): the profit-step ladder booked a
banked slice with status 'closed_partial'. The CHECK constraint from
migration 0008 did not include it, so every insert was rejected, the
exception was swallowed, and the log said only "booking failed". Six
weeks of banked slices left the broker with no record of the gain.

Run: pytest agents/tests/test_position_status.py
 or: python -m agents.tests.test_position_status
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests  # noqa: E402

ps = load_module("app.paper.position_status")

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "db" / "migrations"


def _schema_statuses() -> set:
    """The statuses the LATEST paper_positions CHECK constraint allows."""
    best = None
    for path in sorted(MIGRATIONS.glob("*.sql")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
                r"check\s*\(\s*status\s+in\s*\(([^)]*)\)", text, re.I | re.S):
            block = m.group(1)
            # only the constraint that belongs to paper_positions
            window = text[max(0, m.start() - 2000):m.end()]
            if "paper_positions" not in window:
                continue
            vals = set(re.findall(r"'([a-z_]+)'", block))
            if vals:
                best = vals
    return best or set()


def test_a_paper_positions_status_constraint_exists():
    assert _schema_statuses(), (
        "no CHECK constraint for paper_positions.status found in "
        "db/migrations -- this test cannot protect anything")


def test_every_status_the_code_uses_is_allowed_by_the_schema():
    allowed = _schema_statuses()
    missing = sorted(ps.ALL_STATUSES - allowed)
    assert not missing, (
        f"position_status.py declares {missing} but the database CHECK "
        f"constraint would REJECT them. Add a migration. Writing one of "
        f"these today fails silently at the DB and the caller swallows "
        f"the error -- exactly the closed_partial failure.")


def test_closed_partial_is_specifically_allowed():
    """The regression itself."""
    assert "closed_partial" in ps.ALL_STATUSES
    assert "closed_partial" in _schema_statuses(), (
        "migration 0051 is missing or was not applied -- every profit "
        "step will bank at the broker and record nothing")


def test_partial_is_not_treated_as_a_full_close():
    assert ps.is_partial("closed_partial") is True
    assert ps.is_partial("closed_stop") is False
    assert ps.is_open("open") is True


def test_writing_an_unknown_status_raises_at_the_call_site():
    raised = False
    try:
        ps.assert_valid("closed_partail", "typo test")   # deliberate typo
    except ValueError:
        raised = True
    assert raised, (
        "an unknown status must fail loudly in Python, not quietly at "
        "the database where the caller throws the reason away")


def test_the_engine_uses_the_shared_constant():
    src = (REPO / "trezo-platform" / "agents" / "app" / "paper" / "engine.py")
    if not src.exists():
        src = REPO / "agents" / "app" / "paper" / "engine.py"
    text = src.read_text(encoding="utf-8", errors="replace")
    assert '"status": "closed_partial"' not in text, (
        "engine.py should reference the validated constant, not a bare "
        "string the schema has never heard of")


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
