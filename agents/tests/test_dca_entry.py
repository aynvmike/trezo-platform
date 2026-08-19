"""Guard tests: DCA buys the bounce, not the knife.

Why these exist (2026-08-19). Every crypto mode earns its entry -- SWING
needs expanding bands AND healthy RSI AND volume; SCALP needs a calm
range; HODL demands RSI under 25 -- except DCA, whose entire condition
was one comparison: rsi < 40. RSI under 40 means the coin is FALLING.
Buying on that alone bought the third hour of waterfalls, and the month
priced it: 29 closes, -$738, most never bouncing even +0.8% after entry,
because the bounce had not started when we bought.

The fix adds one word: bounce. Oversold AND turning up (RSI above its
previous bar, close above the previous close). Mike's lane, his rule,
stated back to him: "we need to get those trades better."

Run: python -m agents.tests.test_dca_entry   (or pytest)
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()

cx = load_module("app.strategies.crypto")
from app.patterns import Candle  # noqa: E402


def _candles(closes_seq, start_price=None):
    """Build minimal OHLCV bars from a close series (1h bars, no volume --
    volume is optional in every mode, which these tests inherit)."""
    t0 = datetime(2026, 8, 19, tzinfo=timezone.utc)
    out = []
    prev = closes_seq[0] if start_price is None else start_price
    for i, c in enumerate(closes_seq):
        hi, lo = max(prev, c) * 1.001, min(prev, c) * 0.999
        out.append(Candle(timestamp=t0 + timedelta(hours=i),
                          open=prev, high=hi, low=lo, close=c, volume=0.0))
        prev = c
    return out


def _falling_knife():
    """A realistic knife: mostly red with small green relief bars, ending
    on a red bar. Net decline, RSI in the 25-40 DCA window (asserted in
    the tests via a precondition, so a drift in the fixture fails loudly
    instead of silently testing the wrong mode). The old code bought this."""
    seq = [100.0]
    for i in range(44):
        seq.append(seq[-1] * (1.004 if i % 4 == 3 else 0.996))
    seq.append(seq[-1] * 0.996)  # end on a red bar: RSI ~25.5, falling
    assert seq[-1] < seq[-2], "fixture must end falling"
    return _candles(seq)


def _knife_then_bounce():
    """The same chop-down, then two green bars: RSI turns up, close > prev."""
    seq = [100.0]
    for i in range(44):
        seq.append(seq[-1] * (1.004 if i % 4 == 3 else 0.996))
    seq.append(seq[-1] * 0.996)
    seq += [seq[-1] * 1.003, seq[-1] * 1.005]  # RSI 29.4 -> 32.0, turning up
    return _candles(seq)


def _rsi_window_check(candles):
    """Precondition: the fixture really sits in DCA's claim (25 <= RSI < 40).
    Below 25 is HODL's; at/above 40 nothing here applies."""
    from app.patterns.indicators import rsi, closes
    r = rsi(closes(candles), 14)[-1]
    assert 25 <= r < 40, f"fixture RSI {r:.1f} is outside the DCA window"
    return r


def test_dca_buys_the_bounce_not_the_knife():
    """The month's -$738 in one assertion: a coin that is oversold and
    STILL FALLING must produce no DCA entry."""
    kn = _falling_knife()
    _rsi_window_check(kn)
    sig = cx.detect_mode("BTC", kn)
    assert sig is None or sig.mode != "dca", (
        f"bought a falling knife: {sig and sig.reason}")


def test_dca_still_fires_once_the_bounce_starts():
    """The gate must not kill the lane -- the same oversold coin with two
    green bars IS the DCA trade, and the reason says why."""
    sig = cx.detect_mode("BTC", _knife_then_bounce())
    assert sig is not None and sig.mode == "dca", (
        f"bounce not bought: {sig and (sig.mode, sig.reason)}")
    assert "bounce" in sig.reason.lower()


def test_a_stalled_knife_is_not_yet_a_bounce():
    """A flat bar after a fall (close == prev close) is indecision, not
    recovery. cl[-1] > cl[-2] is strict on purpose."""
    seq = [100.0 * (0.996 ** i) for i in range(39)]
    seq.append(seq[-1])  # exactly flat
    sig = cx.detect_mode("BTC", _candles(seq))
    assert sig is None or sig.mode != "dca", (
        f"bought a flat bar as a bounce: {sig and sig.reason}")


def test_the_knife_does_not_leak_into_scalp():
    """When DCA holds off, the coin must not fall through and get bought
    by SCALP instead -- RSI under 40 mid-fall is not a calm range coin.
    The old if/elif shape made this leak impossible; the return None
    keeps it impossible, and this test keeps the return None."""
    kn = _falling_knife()
    _rsi_window_check(kn)
    sig = cx.detect_mode("BTC", kn)
    assert sig is None, (
        f"knife leaked past DCA into another mode: {sig and (sig.mode, sig.reason)}")


def test_hodl_still_takes_the_deepest_value_before_the_gate():
    """RSI under 25 is HODL's claim and it outranks DCA -- the bounce gate
    must not have moved that boundary. A crash hard enough to push RSI
    under 25 goes to HODL, falling or not (its catastrophe stop is the
    protection there)."""
    crash = _candles([100.0 * (0.984 ** i) for i in range(40)])
    sig = cx.detect_mode("BTC", crash)
    assert sig is not None and sig.mode == "hodl", (
        f"deep value no longer routes to HODL: {sig and (sig.mode, sig.reason)}")


def test_the_off_switch_restores_the_old_behavior():
    """TREZO_CRYPTO_DCA_REQUIRE_BOUNCE=0 must bring back the one-line
    entry, so a rollback is an env var, not a revert."""
    old = cx.DCA_REQUIRE_BOUNCE
    try:
        cx.DCA_REQUIRE_BOUNCE = False
        sig = cx.detect_mode("BTC", _falling_knife())
        assert sig is not None and sig.mode == "dca", (
            "off switch did not restore the old entry")
    finally:
        cx.DCA_REQUIRE_BOUNCE = old


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
