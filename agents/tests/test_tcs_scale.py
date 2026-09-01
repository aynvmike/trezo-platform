"""Guards for the 0-100 TCS scale where it had not landed (EQ-5, EQ-9, G4).

The platform moved TCS to 0-100 on 2026-07-08. Three places kept the
old 0-1000 numbers:

  * strategies/orb.py and strategies/extended.py hand-built their scores
    from 720/730/740 bases, so every ORB / swing signal cleared every
    per-book floor by ~10x and carried AgentMessage.confidence of 7-9 on
    a field documented as 0..1 (EQ-5).
  * pattern_detection tagged urgency at >= 700 / >= 500 -- unreachable,
    so every pattern signal was "low" and got the slowest staleness
    deadline (EQ-9).
  * reevaluator fell back to a bar of 700 when the settings read FAILED,
    so `fresh_tcs < 350` was always true and a data failure force-closed
    the position (G4).

Deliberately dependency-free (no pytest, no .env, no network): seams
are patched on the REAL modules and always restored.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
orb = load_module("app.strategies.orb")
extended = load_module("app.strategies.extended")
pd_mod = load_module("app.agents.pattern_detection")
reev = load_module("app.agents.reevaluator")
settings = load_module("app.runtime.settings")
import app.data.candles as candles_mod  # noqa: E402  (real package import)
import app.patterns.scoring as scoring  # noqa: E402
import app.agents.activity_log as activity_log  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
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


class _C:
    """A duck-typed OHLCV bar (the strategies only read these fields)."""
    def __init__(self, o, h, l, c, v):
        self.open, self.high, self.low, self.close, self.volume = o, h, l, c, v


# --- ORB (EQ-5) ----------------------------------------------------------

def _orb_bars(confirm_vol):
    opening = [_C(100.5, 101.0, 100.0, 100.5, 1000) for _ in range(5)]
    after = [_C(101.0, 101.3, 100.9, 101.2, confirm_vol),
             _C(101.2, 101.5, 101.1, 101.4, confirm_vol)]
    return opening + after


def test_orb_best_case_scores_86_on_the_0_100_scale():
    # range 1.0 / ATR 2.0 = 0.5 (in the 0.20-0.55 quality band): +4;
    # confirm volume >= opening average: +6; best window: +4 -> 72+14.
    sig = orb.evaluate_orb("SPY", _orb_bars(1500), daily_atr=2.0,
                           sub_window="best")
    assert sig is not None
    assert sig.tcs == 86, sig.tcs
    assert 0 <= sig.tcs <= 100
    assert 0.0 <= sig.tcs / 100.0 <= 1.0       # what the scanner emits


def test_orb_bare_breakout_scores_72():
    sig = orb.evaluate_orb("SPY", _orb_bars(500), daily_atr=1.4,   # ratio .71
                           sub_window="reduced")
    assert sig is not None
    assert sig.tcs == 72, sig.tcs


# --- Extended (EQ-5) -----------------------------------------------------

def _swing_bars():
    """57 flat bars then a 3-bar breakout above the 100 resistance,
    closing at 102 on double volume."""
    bars = [_C(99, 100, 98, 99, 1000) for _ in range(57)]
    bars += [_C(99, 101.5, 99, 101, 1000),
             _C(101, 102.3, 100.8, 102, 1000),
             _C(101.5, 102.5, 101.2, 102, 2000)]
    return bars


def test_extended_breakout_hold_scores_83_and_wins():
    # 74 base + 6 (volume 2000 >= 1.3x the 1000 average) + 3 (within 4%
    # of the level) = 83. The EMA50 pullback detector also fires (81)
    # and loses; gap and stair-stepper do not match this tape.
    sig = extended.evaluate_extended("WMT", _swing_bars())
    assert sig is not None
    assert sig.setup == "breakout_hold", sig.setup
    assert sig.tcs == 83, sig.tcs
    assert 0 <= sig.tcs <= 100
    assert 0.0 <= sig.tcs / 100.0 <= 1.0


def test_extended_catalyst_adds_4_not_40():
    sig = extended.evaluate_extended("WMT", _swing_bars(), has_catalyst=True)
    assert sig is not None and sig.tcs == 87, sig.tcs


def test_extended_every_detector_stays_inside_0_100():
    bars = _swing_bars()
    for det in extended._DETECTORS:
        sig = det("WMT", bars)
        if sig is not None:
            assert 0 <= sig.tcs <= 100, (det.__name__, sig.tcs)
    assert extended.EXTENDED_TCS_MIN == 70


def test_extended_floor_is_a_real_gate_now():
    """A hit at 69 on this scale must NOT be emitted."""
    def _weak(symbol, candles):
        return extended.ExtendedSignal(
            symbol=symbol, setup="stair_stepper", direction="bullish",
            entry_price=1.0, stop_pct=0.07, target_pct=0.10, tcs=69,
            rationale="weak")
    with _patched(extended, _DETECTORS=[_weak]):
        assert extended.evaluate_extended("X", _swing_bars()) is None


# --- pattern urgency (EQ-9) ----------------------------------------------

def test_pattern_urgency_bands_are_reachable_on_the_0_100_scale():
    assert pd_mod._urgency_for(70) == "urgent"
    assert pd_mod._urgency_for(85) == "urgent"
    assert pd_mod._urgency_for(69) == "mixed"
    assert pd_mod._urgency_for(50) == "mixed"
    assert pd_mod._urgency_for(49) == "low"
    assert pd_mod._urgency_for(None) == "low"


# --- reevaluator collapse check (G4) ------------------------------------

def _row(pid="pos-1"):
    entry_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    return {"id": pid, "ticker": "RBLX", "user_id": "book-a",
            "entry_price": 100.0, "entry_at": entry_at,
            "strategy": "stms", "peak_price": 0}


async def _bars(ticker, at):
    return [_C(1, 1, 1, 1, 1)] * 20


class _Score:
    tcs = 10        # far below half of any sane bar


async def _quiet(*a, **k):
    return None


@contextlib.contextmanager
def _reeval_env(settings_read):
    """Master on, every sub-action at its default, fresh TCS = 10, no
    activity-log file writes, no Supabase, no scope read."""
    reev._hb_at.clear()
    reev._last_action.clear()
    try:
        with _patched(reev, reeval_is_enabled=lambda: True,
                      _regime=lambda: "neutral",
                      _low_edge=lambda *a: False,
                      _log=_quiet), \
                _patched(candles_mod, fetch_candles_for=_bars), \
                _patched(scoring, calculate_score=lambda *a, **k: _Score()), \
                _patched(activity_log, record=lambda *a, **k: None), \
                _patched(settings, get_bot_settings=settings_read):
            yield
    finally:
        reev._hb_at.clear()
        reev._last_action.clear()


def test_a_collapsed_thesis_still_rotates_when_the_bar_is_known():
    """The CONTROL: the path is live. Bar 70, fresh 10 < 35 -> close."""
    def _ok(user_id=None):
        return settings.BotSettings(tcs_threshold=70)
    with _reeval_env(_ok):
        emit = []
        out = _run(reev.reevaluate_position(
            _row(), price=95.0, side="long", at="stock", strat="stms",
            stop=None, target=None, emit=emit))
    assert out == {"close": "reeval_tcs_collapse"}, out


def test_a_failed_settings_read_never_closes_a_position():
    """G4: the old fallback was a bar of 700 on a 0-100 scale, so a
    settings outage read as 'thesis collapsed' and closed the trade."""
    def _boom(user_id=None):
        raise RuntimeError("bot_settings unavailable")
    with _reeval_env(_boom):
        emit = []
        out = _run(reev.reevaluate_position(
            _row("pos-2"), price=95.0, side="long", at="stock",
            strat="stms", stop=None, target=None, emit=emit))
    assert out is None, out


def test_the_collapse_bar_is_none_on_a_failed_read_and_70_by_default():
    def _boom(user_id=None):
        raise RuntimeError("down")
    with _patched(settings, get_bot_settings=_boom):
        assert reev._collapse_bar("book-a") is None
    with _patched(settings, get_bot_settings=lambda user_id=None:
                  settings.BotSettings(tcs_threshold=0)):
        assert reev._collapse_bar("book-a") == 70


# --- reevaluator tunables (G19) ------------------------------------------

def test_numeric_tunables_read_settings_first_then_env_then_default():
    import os
    assert reev.tunable("COOLDOWN_SEC") == 900.0          # default
    old = os.environ.get("TREZO_REEVAL_COOLDOWN_SEC")
    os.environ["TREZO_REEVAL_COOLDOWN_SEC"] = "120"
    try:
        assert reev.tunable("COOLDOWN_SEC") == 120.0      # env, per call
    finally:
        if old is None:
            del os.environ["TREZO_REEVAL_COOLDOWN_SEC"]
        else:
            os.environ["TREZO_REEVAL_COOLDOWN_SEC"] = old
    # Settings wins over env once config.py declares the attribute.
    import app.config as cfg
    real = cfg.get_settings

    class _S(type(real())):
        trezo_reeval_cooldown_sec = 45

    with _patched(cfg, get_settings=lambda: _S()):
        assert reev.tunable("COOLDOWN_SEC") == 45.0


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
