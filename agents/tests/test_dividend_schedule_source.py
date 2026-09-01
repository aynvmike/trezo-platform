"""Source-order and cache guards for app/dividends/schedule.py
(audit 2026-09-01: AV-2, AV-3, AV-4).

  AV-2  the ex-date calendar must read Alpaca corporate actions FIRST --
        the in-repo source the entry screen and wheel universe already
        use -- not Finnhub (endpoint not on this tier) then Alpha Vantage.
  AV-3  Alpha Vantage (25 calls/day) is the LAST fallback and is only
        spent when the sources ahead of it produced nothing.
  AV-4  a FAILED read is not cached as the day's answer. The old code
        stored [] for (symbol, today) whatever happened, so one
        rate-limited AV reply meant "this symbol pays nothing" until
        midnight.

Plain zero-arg test_ functions, no pytest, no fixtures, no network, no
.env -- this file must run under tests/run_all.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
sched = load_module("app.dividends.schedule")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@contextlib.contextmanager
def _patched(mod, **attrs):
    missing = object()
    old = {k: getattr(mod, k, missing) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is missing:
                delattr(mod, k)
            else:
                setattr(mod, k, v)


class _Settings:
    def __init__(self, av="AVKEY", finnhub=""):
        self.alpha_vantage_api_key = av
        self.finnhub_api_key = finnhub


class _Src:
    """A scripted source: counts calls, returns what it was told to."""
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def alpaca(self, sym):
        self.calls += 1
        return self.result

    async def http(self, url, params):
        self.calls += 1
        return self.result


_ALPACA_ROWS = [
    {"ex_date": "2026-03-19", "rate": 0.55, "adj_rate": 0.55, "special": False},
    {"ex_date": "2026-06-18", "rate": 0.57, "adj_rate": 0.57, "special": False},
]
_AV_OK = {"symbol": "KO", "data": [
    {"ex_dividend_date": "2026-06-12", "amount": "0.51"},
    {"ex_dividend_date": "2026-03-13", "amount": "0.51"},
]}
_AV_LIMITED = {"Information": "Thank you for using Alpha Vantage! "
                              "Our standard API rate limit is 25 requests per day."}


def _fresh():
    sched.clear_cache()


# --- AV-2: Alpaca first -------------------------------------------------------

def test_corporate_actions_is_the_first_source_and_av_is_not_spent():
    _fresh()
    alpaca = _Src(_ALPACA_ROWS)
    av = _Src(_AV_OK)
    with _patched(sched, _alpaca_rows=alpaca.alpaca, _get_json=av.http,
                  get_settings=lambda: _Settings(finnhub="FHKEY")):
        rows = _run(sched.ex_dividend_history("ko"))
    assert alpaca.calls == 1
    assert av.calls == 0, "Alpha Vantage/Finnhub were spent despite Alpaca answering"
    assert [r.ex_date for r in rows] == ["2026-06-18", "2026-03-19"], rows
    assert all(r.source == "alpaca:corporate_actions" for r in rows), rows
    assert abs(rows[0].amount - 0.57) < 1e-9
    assert rows[0].symbol == "KO"


def test_a_successful_read_is_cached_for_the_day():
    _fresh()
    alpaca = _Src(_ALPACA_ROWS)
    with _patched(sched, _alpaca_rows=alpaca.alpaca,
                  _get_json=_Src(None).http, get_settings=lambda: _Settings()):
        first = _run(sched.ex_dividend_history("KO"))
        second = _run(sched.ex_dividend_history("KO"))
    assert alpaca.calls == 1, "a cached day was re-fetched"
    assert first == second


# --- AV-3: Alpha Vantage last -----------------------------------------------------

def test_alpha_vantage_is_used_only_when_alpaca_has_nothing():
    _fresh()
    alpaca = _Src([])
    av = _Src(_AV_OK)
    with _patched(sched, _alpaca_rows=alpaca.alpaca, _get_json=av.http,
                  get_settings=lambda: _Settings()):
        rows = _run(sched.ex_dividend_history("KO"))
    assert alpaca.calls == 1 and av.calls == 1
    assert [r.ex_date for r in rows] == ["2026-06-12", "2026-03-13"], rows
    assert all(r.source == "alpha_vantage" for r in rows)
    assert ("KO", sched.date.today().isoformat()) in sched._CACHE


def test_alpha_vantage_is_not_called_without_a_key():
    _fresh()
    av = _Src(_AV_OK)
    with _patched(sched, _alpaca_rows=_Src([]).alpaca, _get_json=av.http,
                  get_settings=lambda: _Settings(av="")):
        rows = _run(sched.ex_dividend_history("KO"))
    assert av.calls == 0
    assert rows == []


# --- AV-4: a failed read is not the day's answer --------------------------------

def test_a_failed_read_is_not_cached():
    _fresh()
    av = _Src(None)                       # transport failure
    with _patched(sched, _alpaca_rows=_Src([]).alpaca, _get_json=av.http,
                  get_settings=lambda: _Settings(), _FAIL_BACKOFF_SECONDS=0):
        assert _run(sched.ex_dividend_history("KO")) == []
        assert ("KO", sched.date.today().isoformat()) not in sched._CACHE
        # The next caller tries again rather than inheriting the failure.
        assert _run(sched.ex_dividend_history("KO")) == []
    assert av.calls == 2, av.calls


def test_a_rate_limited_alpha_vantage_reply_is_a_failure_not_an_empty_calendar():
    """HTTP 200 with an Information body and no `data` used to parse as
    'no dividends' and get cached until midnight."""
    _fresh()
    av = _Src(_AV_LIMITED)
    with _patched(sched, _alpaca_rows=_Src([]).alpaca, _get_json=av.http,
                  get_settings=lambda: _Settings(), _FAIL_BACKOFF_SECONDS=0):
        assert _run(sched.ex_dividend_history("KO")) == []
        assert ("KO", sched.date.today().isoformat()) not in sched._CACHE
    assert sched._alpha_vantage_ok(_AV_LIMITED) is False
    assert sched._alpha_vantage_ok(_AV_OK) is True


def test_a_failed_read_backs_off_briefly_then_retries():
    _fresh()
    av = _Src(None)
    with _patched(sched, _alpaca_rows=_Src([]).alpaca, _get_json=av.http,
                  get_settings=lambda: _Settings(), _FAIL_BACKOFF_SECONDS=900):
        _run(sched.ex_dividend_history("KO"))
        _run(sched.ex_dividend_history("KO"))      # inside the backoff window
    assert av.calls == 1, "backoff did not hold"
    assert "KO" in sched._FAILED_UNTIL
    # ...and a later success clears the failure marker.
    sched._FAILED_UNTIL["KO"] = 0.0
    with _patched(sched, _alpaca_rows=_Src(_ALPACA_ROWS).alpaca,
                  _get_json=av.http, get_settings=lambda: _Settings()):
        rows = _run(sched.ex_dividend_history("KO"))
    assert rows and "KO" not in sched._FAILED_UNTIL


def test_a_genuinely_empty_answer_is_still_cached():
    """Alpaca says nothing, AV answers with an empty data list: that IS
    the day's answer -- a non-payer -- and must not burn the budget again."""
    _fresh()
    av = _Src({"symbol": "BRK.B", "data": []})
    with _patched(sched, _alpaca_rows=_Src([]).alpaca, _get_json=av.http,
                  get_settings=lambda: _Settings()):
        assert _run(sched.ex_dividend_history("BRK.B")) == []
        assert _run(sched.ex_dividend_history("BRK.B")) == []
    assert av.calls == 1


def test_latest_unpaid_ex_reads_through_the_same_chain():
    _fresh()
    with _patched(sched, _alpaca_rows=_Src(_ALPACA_ROWS).alpaca,
                  _get_json=_Src(None).http, get_settings=lambda: _Settings()):
        ex = _run(sched.latest_unpaid_ex("KO", "2026-04-01",
                                         sched.date(2026, 7, 1)))
    assert ex is not None and ex.ex_date == "2026-06-18", ex
    assert ex.source == "alpaca:corporate_actions"


def test_parse_corporate_actions_uses_declared_rate():
    rows = sched.parse_corporate_actions("ko", [
        {"ex_date": "2020-01-10", "rate": 1.00, "adj_rate": 0.25},
        {"ex_date": "not-a-date", "rate": 1.00},
        "junk",
    ])
    assert len(rows) == 1 and rows[0].amount == 1.00 and rows[0].symbol == "KO"


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
