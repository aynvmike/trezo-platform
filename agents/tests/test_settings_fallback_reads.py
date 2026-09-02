"""Reviewer minors from the 2026-09-01 audit (rv:scanners-scale).

reevaluator.py:215  get_bot_settings() never raises -- on a missing
    client, a failed query or a book with no row it caches and returns
    the shared _DEFAULTS (bar 70). So the reevaluator's `except` never
    fired and a DB blip judged a book at 50 against 70, closing a
    position on a TCS its real bar would have kept. settings now says
    when an answer is the fallback (is_fallback_settings), and
    _collapse_bar returns None -- "bar UNKNOWN, do not judge" -- for it.

settings.py:378  min_tcs_floor_across_books() took the minimum over
    every enabled book, so a book with a lane switched OFF still lowered
    that lane's producer bar for everyone. With `lane_field` a book whose
    toggle is off does not count; without it the behaviour is unchanged.

Plain zero-arg test_ functions, no pytest, no fixtures, no network, no
.env -- runs under tests/run_all.py. Module attributes are patched
through a contextmanager that always restores them.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
settings = load_module("app.runtime.settings")
reeval = load_module("app.agents.reevaluator")

BotSettings = settings.BotSettings


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and ALWAYS put the originals back; a
    sentinel (not None) marks 'was absent'."""
    _missing = object()
    old = {k: getattr(mod, k, _missing) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is _missing:
                if hasattr(mod, k):
                    delattr(mod, k)
            else:
                setattr(mod, k, v)


@contextlib.contextmanager
def _clean_cache():
    saved = dict(settings._cache)
    settings._cache.clear()
    try:
        yield
    finally:
        settings._cache.clear()
        settings._cache.update(saved)


# --- a Supabase double for get_bot_settings -------------------------------

class _Res:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        return _Res(list(self._rows))


class _Client:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        return _Query(self._rows)


# =======================================================================
# reevaluator.py:215 -- a fallback read is UNKNOWN, not 70
# =======================================================================

def test_a_missing_client_hands_back_the_fallback_and_says_so():
    with _clean_cache(), _patched(settings, _supabase=lambda: None):
        bs = settings.get_bot_settings("book-x")
        assert settings.is_fallback_settings(bs) is True
        assert bs.tcs_threshold == 70, "the fallback is still usable"


def test_a_failed_query_and_a_missing_row_are_fallbacks_too():
    class _Boom:
        def table(self, name):
            raise RuntimeError("db down")

    with _clean_cache(), _patched(settings, _supabase=lambda: _Boom()):
        assert settings.is_fallback_settings(settings.get_bot_settings("book-x"))
    with _clean_cache(), _patched(settings, _supabase=lambda: _Client([])):
        assert settings.is_fallback_settings(settings.get_bot_settings("book-x"))


def test_a_real_row_is_not_a_fallback_even_at_the_default_number():
    """The book's own row saying 70 is an ANSWER; identity, not value,
    tells it from the fallback."""
    row = {"user_id": "book-x", "tcs_threshold": 70}
    with _clean_cache(), _patched(settings, _supabase=lambda: _Client([row])):
        bs = settings.get_bot_settings("book-x")
        assert settings.is_fallback_settings(bs) is False
        assert bs.tcs_threshold == 70
        assert bs is not settings._DEFAULTS


def test_the_fallback_survives_the_cache():
    """The cache stores what it returned, so a second read inside the TTL
    is still recognisable as the fallback."""
    with _clean_cache(), _patched(settings, _supabase=lambda: None):
        settings.get_bot_settings("book-x")
        again = settings.get_bot_settings("book-x")
        assert settings.is_fallback_settings(again)


def test_collapse_bar_is_unknown_on_a_fallback_and_the_books_bar_otherwise():
    """Drives the REAL _collapse_bar with only get_bot_settings swapped
    (the reevaluator imports it at call time from app.runtime.settings)."""
    with _patched(settings, get_bot_settings=lambda uid=None: settings._DEFAULTS):
        assert reeval._collapse_bar("book-x") is None, (
            "a fallback read must be UNKNOWN, not the default 70")
    with _patched(settings, get_bot_settings=lambda uid=None: BotSettings(tcs_threshold=50)):
        assert reeval._collapse_bar("book-x") == 50
    with _patched(settings, get_bot_settings=lambda uid=None: BotSettings(tcs_threshold=0)):
        assert reeval._collapse_bar("book-x") == 70, "a real row with no bar -> 70"

    def _raise(uid=None):
        raise RuntimeError("settings exploded")
    with _patched(settings, get_bot_settings=_raise):
        assert reeval._collapse_bar("book-x") is None


def test_collapse_bar_is_bound_through_the_fallback_check():
    """BUILT BUT NOT BOUND guard: the helper exists AND the reevaluator
    consults it before trusting the number."""
    src = Path(reeval.__file__).read_text(encoding="utf-8", errors="replace")
    fn = src[src.index("def _collapse_bar"):src.index("async def reevaluate_position")]
    assert "is_fallback_settings(bs)" in fn, fn


# =======================================================================
# settings.py:378 -- a book with the lane OFF does not set the floor
# =======================================================================

@contextlib.contextmanager
def _books(rows: dict, primary: str, enumerate_ok=True):
    """A fake multi-book settings source: `rows` is book -> BotSettings
    (the same shape test_scanner_gates_bookkeyed uses)."""
    def _get(user_id=None):
        return rows[user_id or primary]

    def _ids():
        if enumerate_ok is None:
            raise RuntimeError("accounts unavailable")
        return list(rows) if enumerate_ok else []

    with _patched(settings, _enabled_book_ids=_ids, get_bot_settings=_get):
        yield


_MIXED = {
    "book-a": BotSettings(stms_enabled=False, crypto_enabled=True, tcs_threshold=40),
    "book-b": BotSettings(stms_enabled=True, crypto_enabled=True, tcs_threshold=70),
}
_ALL_OFF = {
    "book-a": BotSettings(stms_enabled=False, tcs_threshold=40),
    "book-b": BotSettings(stms_enabled=False, tcs_threshold=70),
}


def test_without_a_lane_field_every_enabled_book_counts_as_before():
    with _books(_MIXED, primary="book-b"):
        assert settings.min_tcs_floor_across_books() == 40


def test_a_book_with_the_lane_off_does_not_lower_that_lanes_floor():
    """THE FINDING: book-a has STMS off and a 40 slider; it will never
    take an STMS signal, so 40 is not the STMS floor. It IS still the
    crypto floor, where its lane is on."""
    with _books(_MIXED, primary="book-b"):
        assert settings.min_tcs_floor_across_books(lane_field="stms_enabled") == 70
        assert settings.min_tcs_floor_across_books(lane_field="crypto_enabled") == 40


def test_a_lane_off_everywhere_falls_back_to_every_book():
    """'Nobody wants this lane' is lane_enabled_any()'s call, not the
    floor's: with no book on, every book counts again rather than the
    floor inventing a number."""
    with _books(_ALL_OFF, primary="book-b"):
        assert settings.min_tcs_floor_across_books(lane_field="stms_enabled") == 40


def test_a_field_no_row_has_counts_every_book():
    """forex has no bot_settings toggle: an absent field is not 'off'."""
    with _books(_MIXED, primary="book-b"):
        assert settings.min_tcs_floor_across_books(lane_field="forex_enabled") == 40


def test_single_account_and_enumeration_failure_still_fall_back_to_the_bare_read():
    with _books(_MIXED, primary="book-b", enumerate_ok=False):
        assert settings.min_tcs_floor_across_books(lane_field="stms_enabled") == 70
    with _books(_MIXED, primary="book-b", enumerate_ok=None):
        assert settings.min_tcs_floor_across_books(lane_field="stms_enabled") == 70


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
