"""DU-01: book_health's unmanaged-notional check and the dust floor.

The invariant is blunt on purpose -- every broker position must have an
open ledger row -- but a fractional close leaves crumbs (a $0.40 sliver
of ETH, 0.0001 of a share) that are not positions anyone should manage.
Before the floor those crumbs kept a book permanently "broken" and the
channel that reports real unmanaged notional got tuned out.

The asymmetry that matters (house rule 3): a row whose market_value is
MISSING or unparseable is not "small". It is unknown, and unknown must
still flag. Only a present, parseable value below DUST_MIN_USD is dust.

Drives the REAL _check_book: the module is loaded from its file and only
its two seams -- book_scope.positions and alerts.notify -- are stubbed,
always restored.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
bh = load_module("app.agents.book_health")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and ALWAYS put the originals back."""
    old = {k: getattr(mod, k, None) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                if hasattr(mod, k):
                    delattr(mod, k)
            else:
                setattr(mod, k, v)


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Any chain of .select/.eq/.limit ends in .execute() -> rows."""

    def __init__(self, rows):
        self._rows = rows

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        return _Result(list(self._rows))


class _Client:
    """paper_positions -> open ledger rows; paper_accounts -> none."""

    def __init__(self, open_rows):
        self._open = open_rows

    def table(self, name):
        return _Query(self._open if name == "paper_positions" else [])


def _check(broker_rows, open_rows=(), *, uid="book-1"):
    """Run the real _check_book with the two seams stubbed."""
    sent = []

    async def _positions(user_id, **_kw):
        assert user_id == uid, "book_scope must be asked for THIS book"
        return list(broker_rows)

    async def _notify(title, body="", **kw):
        sent.append({"title": title, "body": body, **kw})
        return True

    agent = bh.BookHealthAgent()
    type(agent)._open_findings = {}            # class-level; isolate
    with _patched(bh.book_scope, positions=_positions), \
            _patched(bh, notify=_notify):
        findings = _run(agent._check_book(_Client(list(open_rows)), uid, "Book"))
    return findings, sent


def _row(sym, mv, qty="1", **extra):
    r = {"symbol": sym, "qty": qty, "asset_class": "us_equity", **extra}
    if mv is not ...:
        r["market_value"] = mv
    return r


# --- the floor ------------------------------------------------------------

def test_the_floor_is_a_dollar_by_default_and_env_tunable_by_name():
    if "TREZO_HEALTH_DUST_USD" not in os.environ:
        assert bh.DUST_MIN_USD == 1.0
    src = (Path(bh.__file__)).read_text(encoding="utf-8")
    assert '_f("TREZO_HEALTH_DUST_USD"' in src
    assert "QUIET_GATE_HOURS" not in src, "the dead knob is back"


def test_dust_rows_are_skipped_but_a_missing_market_value_still_flags():
    """THE CASE: five broker rows, no ledger rows. The $0.42 crumb is
    dust; the row with no market_value, the row with market_value None
    and the row with junk are UNKNOWN and must flag; the $250 row is a
    real unmanaged position."""
    broker = [
        _row("AAPL", "0.42"),                 # dust -> skipped
        _row("MSFT", None),                   # present-but-None -> flags
        _row("NVDA", ...),                    # key absent -> flags
        _row("TSLA", "n/a"),                  # unparseable -> flags
        _row("KO", "250"),                    # real -> flags
    ]
    findings, sent = _check(broker)
    assert len(findings) == 1, findings
    f = findings[0]
    assert f["finding"] == "unmanaged_positions"
    assert f["count"] == 4, f
    assert f["notional_usd"] == 250.0, f
    assert sent and sent[0]["key"] == "unmanaged:book-1"
    body = sent[0]["body"]
    assert "AAPL" not in body, "dust leaked into the alert"
    for sym in ("MSFT", "NVDA", "TSLA", "KO"):
        assert sym in body, (sym, body)
    assert "no market value" in body, "an unknown value must be SAID, not shown as $0"


def test_a_row_exactly_at_the_floor_is_not_dust():
    findings, _ = _check([_row("AAPL", str(bh.DUST_MIN_USD))])
    assert findings and findings[0]["count"] == 1


def test_a_negative_market_value_is_measured_by_magnitude():
    """A short's market_value comes back negative; -$300 is not dust."""
    findings, _ = _check([_row("GME", "-300", qty="-3")])
    assert findings and findings[0]["notional_usd"] == 300.0
    findings, _ = _check([_row("GME", "-0.30", qty="-3")])
    assert findings == []


def test_a_book_of_nothing_but_dust_is_healthy():
    findings, sent = _check([_row("AAPL", "0.42"), _row("ETH/USD", "0.07",
                                                        asset_class="crypto")])
    assert findings == [] and sent == []


def test_a_ledger_matched_row_never_counts_whatever_its_value():
    broker = [_row("KO", "250"), _row("PEP", None)]
    ledger = [{"id": 1, "ticker": "KO", "side": "long", "stop_price": 0},
              {"id": 2, "ticker": "PEP", "side": "long", "stop_price": 0}]
    findings, sent = _check(broker, ledger)
    assert findings == [] and sent == []


def test_a_failed_broker_read_says_nothing_rather_than_all_clear():
    """book_scope.positions returning None = could not check. That must
    not be read as 'no unmanaged positions' (house rule 3)."""
    sent = []

    async def _none(user_id, **_kw):
        return None

    async def _notify(title, body="", **kw):
        sent.append(title)
        return True

    agent = bh.BookHealthAgent()
    type(agent)._open_findings = {"unmanaged:book-1": "unmanaged"}
    with _patched(bh.book_scope, positions=_none), _patched(bh, notify=_notify):
        findings = _run(agent._check_book(_Client([]), "book-1", "Book"))
    assert findings == []
    assert sent == [], "a failed read announced a recovery"
    assert type(agent)._open_findings == {"unmanaged:book-1": "unmanaged"}


def test_the_floor_is_bound_at_the_call_site_not_just_defined():
    """BUILT BUT NOT BOUND guard: the constant must be consulted inside
    the invariant-1 loop, and the skip must be conditional on the value
    being present and parseable."""
    src = (Path(bh.__file__)).read_text(encoding="utf-8")
    loop = src[src.index("INVARIANT 1"):src.index("INVARIANT 2")]
    assert "DUST_MIN_USD" in loop
    assert "mv is not None and mv < DUST_MIN_USD" in loop


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
