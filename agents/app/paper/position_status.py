"""The statuses a paper_positions row may hold -- one source of truth.

WHY (2026-08-17)
The profit-step ladder wrote status 'closed_partial'. The database's
CHECK constraint, written eight months earlier, had never heard of it.
Every partial booking was rejected for six weeks, the exception was
swallowed, and the only trace was the words "booking failed" in a log
line. The slice had really sold at the broker; only the record of it
was lost.

The lesson is not "add closed_partial" -- that is migration 0051. The
lesson is that the list of legal statuses lived in exactly one place,
the database, where Python could not see it. Now it lives here, the
migration quotes it, and a guard test compares the two. Drift becomes a
failing test instead of a silent write rejection.

ADDING A STATUS
1. Add it here, in the right bucket.
2. Add it to a new migration's CHECK constraint.
3. Run the tests. If you did one and not the other, they fail.
"""

from __future__ import annotations

OPEN = "open"

# A closed row is terminal: its quantity is gone from the book.
CLOSED_STATUSES: frozenset = frozenset({
    "closed_stop",       # protective stop hit
    "closed_target",     # take-profit hit
    "closed_manual",     # closed by hand, or reconciled against the broker
    "closed_time",       # time stop / max hold
    "closed_eod",        # end-of-day flatten
    "closed_partial",    # a banked SLICE of a position that stays open
    "closed_expired",    # option expired worthless
    "closed_assigned",   # option assigned or exercised
    "closed_adopted",    # superseded by an adopted broker-truth row
})

ALL_STATUSES: frozenset = frozenset({OPEN}) | CLOSED_STATUSES

# Statuses that do NOT mean the whole position went away. A partial is
# the only one today, and treating it as a full close is how a banked
# slice would wrongly zero out an open row.
PARTIAL_STATUSES: frozenset = frozenset({"closed_partial"})


def is_valid(status: str) -> bool:
    return (status or "") in ALL_STATUSES


def is_open(status: str) -> bool:
    return (status or "") == OPEN


def is_partial(status: str) -> bool:
    return (status or "") in PARTIAL_STATUSES


def assert_valid(status: str, where: str = "") -> str:
    """Fail loudly at the call site rather than quietly at the database."""
    if not is_valid(status):
        raise ValueError(
            f"[{where or 'paper_positions'}] status {status!r} is not in "
            f"position_status.ALL_STATUSES. Add it there AND in a "
            f"migration's CHECK constraint -- writing it now would be "
            f"rejected by the database and swallowed by the caller.")
    return status
