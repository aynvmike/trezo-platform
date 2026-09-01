"""Guards for BI-03 / BI-09: a shared scanner gate is EVERY book's question.

The scanners (stms / orb / extended / crypto / forex) asked a bare
get_bot_settings() "is this lane on?" and "what is the TCS floor?". With
TREZO_PRIMARY_USER_ID set that bare call is the PRIMARY book's row, so
turning a lane off on the primary silenced the scanner for every book,
and the primary's slider became everyone's floor. The producer must be
as permissive as the most permissive enabled book; the fan-out
(book_gate) prunes per book.

Same disease in target_calibration (BI-09): the query was filtered by
user_id but the cache was keyed by lane alone, so whichever book asked
first set every other book's learned target for an hour.

Deliberately dependency-free (no pytest, no .env, no network): the
module seams are patched on the REAL modules and always restored.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
settings = load_module("app.runtime.settings")
orb_scanner = load_module("app.agents.orb_scanner")
extended_scanner = load_module("app.agents.extended_scanner")
stms_scanner = load_module("app.agents.stms_scanner")
target_cal = load_module("app.learning.target_calibration")

BotSettings = settings.BotSettings


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and always put the originals back."""
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


@contextlib.contextmanager
def _books(rows: dict, primary: str, enumerate_ok=True):
    """A fake multi-book settings source: `rows` is book -> BotSettings.
    A bare get_bot_settings() resolves to `primary`, exactly as the
    anchor-row logic does in production."""
    def _get(user_id=None):
        return rows[user_id or primary]

    def _ids():
        if enumerate_ok is None:
            raise RuntimeError("accounts unavailable")
        return list(rows) if enumerate_ok else []

    with _patched(settings, _enabled_book_ids=_ids, get_bot_settings=_get):
        yield


_PRIMARY_OFF = {
    "book-a": BotSettings(stms_enabled=False, extended_enabled=False,
                          crypto_enabled=False, tcs_threshold=80),
    "book-b": BotSettings(stms_enabled=True, extended_enabled=True,
                          crypto_enabled=True, tcs_threshold=55),
}
_ALL_OFF = {
    "book-a": BotSettings(stms_enabled=False, extended_enabled=False,
                          crypto_enabled=False, tcs_threshold=80),
    "book-b": BotSettings(stms_enabled=False, extended_enabled=False,
                          crypto_enabled=False, tcs_threshold=55),
}


# --- the helpers ---------------------------------------------------------

def test_a_lane_on_for_a_secondary_book_keeps_the_lane_alive():
    """THE BUG: primary off used to mean everyone off."""
    with _books(_PRIMARY_OFF, primary="book-a"):
        assert settings.lane_enabled_any("stms_enabled") is True
        assert settings.lane_enabled_any("extended_enabled") is True
        assert settings.lane_enabled_any("crypto_enabled") is True


def test_a_lane_off_on_every_book_is_off():
    with _books(_ALL_OFF, primary="book-a"):
        assert settings.lane_enabled_any("stms_enabled") is False


def test_the_floor_is_the_lowest_enabled_books_floor():
    with _books(_PRIMARY_OFF, primary="book-a"):
        assert settings.min_tcs_floor_across_books() == 55


def test_single_account_falls_back_to_the_bare_read():
    """No multi-account -> today's behaviour, byte for byte."""
    with _books(_PRIMARY_OFF, primary="book-a", enumerate_ok=False):
        assert settings.lane_enabled_any("stms_enabled") is False
        assert settings.min_tcs_floor_across_books() == 80


def test_an_enumeration_failure_fails_open_to_the_bare_read():
    with _books(_PRIMARY_OFF, primary="book-a", enumerate_ok=None):
        assert settings.lane_enabled_any("stms_enabled") is False
        assert settings.min_tcs_floor_across_books() == 80


def test_a_field_no_row_has_uses_the_callers_default():
    """forex has no bot_settings toggle yet: the env default decides."""
    with _books(_ALL_OFF, primary="book-a"):
        assert settings.lane_enabled_any("forex_enabled", default=True) is True
        assert settings.lane_enabled_any("forex_enabled", default=False) is False


# --- the scanners actually ask the new question --------------------------

def _note(out):
    return " | ".join(str((m.payload or {}).get("note", "")) for m in out)


def test_orb_scanner_runs_when_only_a_secondary_book_wants_it():
    a = orb_scanner.ORBScannerAgent()
    a._seeded_alerted = True                     # no restart-state read
    with _books(_PRIMARY_OFF, primary="book-a"), \
            _patched(orb_scanner, orb_window=lambda: (False, "")):
        out = _run(a.tick())
    note = _note(out)
    assert "disabled" not in note.lower(), note
    assert "Outside the ORB window" in note, note   # got PAST the gate


def test_orb_scanner_still_idles_when_every_book_is_off():
    a = orb_scanner.ORBScannerAgent()
    a._seeded_alerted = True
    with _books(_ALL_OFF, primary="book-a"), \
            _patched(orb_scanner, orb_window=lambda: (True, "best")):
        out = _run(a.tick())
    assert "disabled" in _note(out).lower(), _note(out)


def test_extended_scanner_runs_when_only_a_secondary_book_wants_it():
    a = extended_scanner.ExtendedScannerAgent()
    a._seeded_signalled = True
    with _books(_PRIMARY_OFF, primary="book-a"), \
            _patched(extended_scanner, fomc_blackout=lambda: True):
        out = _run(a.tick())
    note = _note(out)
    assert "disabled" not in note.lower(), note
    assert "FOMC" in note, note                     # got PAST the gate


def test_stms_scanner_runs_when_only_a_secondary_book_wants_it():
    a = stms_scanner.STMSScannerAgent()
    with _books(_PRIMARY_OFF, primary="book-a"), \
            _patched(stms_scanner, is_trading_window=lambda: False):
        out = _run(a.tick())
    note = _note(out)
    assert "disabled" not in note.lower(), note
    assert "Outside STMS trading window" in note, note


# --- BI-09: learned-target cache is per (lane, book) ---------------------

class _Query:
    def __init__(self, log):
        self._log = log
        self.filters = {}

    def select(self, *a, **k):
        return self

    def eq(self, k, v):
        self.filters[k] = v
        return self

    def like(self, *a):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        self._log.append(dict(self.filters))
        return types.SimpleNamespace(data=[])


class _Client:
    def __init__(self, log):
        self._log = log

    def table(self, name):
        return _Query(self._log)


def test_learned_target_cache_keeps_books_apart():
    log = []
    target_cal._CACHE.clear()
    try:
        with _patched(settings, _supabase=lambda: _Client(log)), \
                _patched(target_cal, enabled=lambda: True):
            _run(target_cal.achieved_move_pct("stms", "stock", "book-a"))
            _run(target_cal.achieved_move_pct("stms", "stock", "book-b"))
            # book-a again: served from ITS cache entry, not re-queried
            _run(target_cal.achieved_move_pct("stms", "stock", "book-a"))
        assert [q.get("user_id") for q in log] == ["book-a", "book-b"], log
        assert "stms|stock|book-a" in target_cal._CACHE
        assert "stms|stock|book-b" in target_cal._CACHE
    finally:
        target_cal._CACHE.clear()


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
