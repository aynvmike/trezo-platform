"""Drive mirrored prices through the real scorer, selector and scanner tick.

The pre-fix scanner scored the bullish fixture at 70 and its exact bearish
mirror at 68. Both must now clear the same unchanged floor, while a different
book's higher floor and intentionally long-only lanes remain independent.
No broker, database, environment credentials, network or pytest fixtures.
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config

stub_config()
scanner = load_module("app.agents.pattern_detection")
scoring = load_module("app.patterns.scoring")
selector = load_module("app.strategies.selector")
settings = load_module("app.runtime.settings")
edges = load_module("app.learning.strategy_weighting")
cycles = load_module("app.data.cycles")
overrides = load_module("app.runtime.overrides")
from app.patterns.candle import Candle
from app.patterns.confluence import confluence_bonus


@contextmanager
def _patched(target, **attrs):
    old = {key: getattr(target, key) for key in attrs}
    try:
        for key, value in attrs.items():
            setattr(target, key, value)
        yield
    finally:
        for key, value in old.items():
            setattr(target, key, value)


def _fixture(breakout=False):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    price = 100.0
    n, body = (60, 0.3) if breakout else (117, 0.16)
    for i in range(n):
        opened = price
        price += (0.18 if i % 3 else -0.1) if breakout else 0.05 + 0.8 * math.sin(i / 5)
        wick = 0.03 if breakout else body * 0.02
        candles.append(Candle(start + timedelta(days=i), opened,
            max(opened, price) + wick, min(opened, price) - wick, price, 1_000_000))
    for i in range(3):
        opened = price - body * 0.2
        price = opened + body
        wick = 0.01 if breakout else body * 0.02
        candles.append(Candle(start + timedelta(days=n + i), opened,
            price + wick, opened - wick, price, 2_000_000))
    return candles


def _mirror(candles):
    pivot = 2 * candles[-1].close
    return [Candle(c.timestamp, pivot - c.open, pivot - c.low,
                   pivot - c.high, pivot - c.close, c.volume) for c in candles]


def _context(candles):
    # The real pattern scanner uses these slices and supplies no IV/catalyst.
    conf = confluence_bonus({"recent_15": candles[-15:],
                             "recent_30": candles[-30:], "full": candles})
    return scoring.MarketContext(confluence_bonus=conf["bonus"])


def test_mirrored_price_paths_clear_the_same_unchanged_confidence_floor():
    up = _fixture()
    down = _mirror(up)
    long = selector.select_strategy(up, ctx=_context(up))
    short = selector.select_strategy(down, ctx=_context(down))
    assert long.direction == "bullish" and short.direction == "bearish"
    # Pin the original bullish control as well as the repaired bearish case.
    assert long.tcs == short.tcs == 70
    assert long.score == short.score == 100
    assert long.breakdown == short.breakdown
    assert long.breakdown["reward_risk_ratio"] == 5.4
    assert "trend" in short.breakdown and "momentum" in short.breakdown


def test_bearish_breakdown_earns_macd_and_breakout_for_its_own_direction():
    up = _fixture(breakout=True)
    down = _mirror(up)
    long = scoring.calculate_score(up)
    short = scoring.calculate_score(down)
    assert long.direction == "bullish" and short.direction == "bearish"
    assert long.score == short.score == 64
    assert long.tcs == short.tcs == 49
    assert long.breakdown == short.breakdown
    assert {"trend", "macd", "breakout"} <= set(short.breakdown)
    # Passing bullish direction on a bearish tape must not gain those points.
    assert not scoring._criteria_trend(down, "bullish")
    assert not scoring._criteria_macd(down, "bullish")
    assert not scoring._criteria_breakout(down, "bullish")


def test_structural_reward_risk_mirrors_support_and_resistance():
    for breakout in (False, True):
        up = _fixture(breakout=breakout)
        down = _mirror(up)
        old_long = scoring._reward_risk_ratio(up)
        long = scoring._reward_risk_ratio(up, "bullish")
        short = scoring._reward_risk_ratio(down, "bearish")
        assert old_long == long and math.isclose(long, short, rel_tol=1e-10)
    assert scoring._reward_risk_ratio([], "bearish") is None


def test_market_bonus_rewards_alignment_on_either_side():
    up = scoring.MarketContext(spy_trending_up=True)
    down = scoring.MarketContext(spy_trending_up=False)
    tcs = scoring.scale_to_tcs
    assert tcs(50, up, 2) == tcs(50, up, 2, "bullish")  # old bullish API
    assert tcs(50, up, 2, "bullish") == tcs(50, down, 2, "bearish")
    assert tcs(50, down, 2, "bullish") == tcs(50, up, 2, "bearish")
    assert tcs(50, down, 2, "bearish") - tcs(50, up, 2, "bearish") == 3
    assert tcs(50, up, 2, "neutral") == tcs(50, down, 2, "neutral")


def test_selector_ranks_bearish_and_bullish_candidates_by_quality_not_side():
    def score(candles, context, strategy):
        return scoring.Score(score=80, tcs={"default": 75, "pattern": 85,
                             "orb": 99}[strategy],
                             direction={"default": "bullish", "pattern": "bearish",
                                        "orb": "neutral"}[strategy])
    with _patched(selector, calculate_score=score):
        pick = selector.select_strategy([], strategies=["default", "pattern", "orb"])
        assert (pick.strategy, pick.direction, pick.tcs) == ("pattern", "bearish", 85)
        # The same existing history/realized-loss preference applies to shorts.
        pick = selector.select_strategy([], strategies=["default", "pattern"],
                                        history={"pattern": -2})
        assert pick.strategy == "default"
        pick = selector.select_strategy([], strategies=["default", "pattern"],
                           outcome_edge={"pattern": {"verdict": "avoid"}})
        assert pick.strategy == "default"


def test_selector_cannot_invent_shorts_for_long_only_lanes_or_spot_crypto():
    down = _mirror(_fixture())
    for strategy in ("stms", "extended", "crypto", "dividend_capture_long"):
        pick = selector.select_strategy(down, ctx=_context(down), strategies=[strategy])
        assert pick.direction == "neutral", (strategy, pick)
        assert pick.considered[0]["direction_supported"] is False
    pick = selector.select_strategy(down, ctx=_context(down),
             strategies=selector.CRYPTO_STRATEGIES, asset_type="crypto")
    assert pick.direction == "neutral"
    assert not any(row["direction_supported"] for row in pick.considered)


def test_real_scanner_emits_both_sides_and_reports_each_books_own_floor():
    up = _fixture()
    down = _mirror(up)
    agent = scanner.PatternDetectionAgent()
    agent._seeded_prev_strategy = True

    async def targets():
        return [(uid, ["UP", "DOWN", "BTC"]) for uid in ("book-a", "book-b")]

    async def pool(tickers, limit):
        return list(tickers), {"watchlist": len(tickers), "market_wide": 0}

    async def candles(ticker, asset_type):
        return up if ticker == "UP" else down

    async def empty(uid):
        return {}

    async def no_override(uid, symbol):
        return None

    async def cycle(symbol):
        return SimpleNamespace(iv_environment="normal", days_until_earnings=None,
                               days_until_exdiv=None, earnings_time=None)

    with ExitStack() as patches:
        patches.enter_context(_patched(agent, _scan_targets=targets, _backtest_history=empty))
        patches.enter_context(_patched(scanner, fetch_candles_for=candles,
            expanded_scan_pool=pool, _stms_window=lambda: True,
            _orb_window=lambda: (True, "best"), _swing_window=lambda: True))
        patches.enter_context(_patched(settings, get_bot_settings=lambda uid:
            settings.BotSettings(tcs_threshold=70 if uid == "book-a" else 71,
                                 pattern_enabled=True)))
        patches.enter_context(_patched(edges, get_live_strategy_edge=empty))
        patches.enter_context(_patched(cycles, get_cycle_position=cycle))
        patches.enter_context(_patched(overrides, get_strategy_override=no_override))
        messages = asyncio.run(agent.tick())

    assert not [m for m in messages if m.kind == "error"], messages
    signals = [m for m in messages if m.kind == "signal"]
    assert {(m.payload["ticker"], m.payload["direction"], m.payload["user_id"])
            for m in signals} == {("UP", "bullish", "book-a"),
                                  ("DOWN", "bearish", "book-a")}
    assert all(m.payload["tcs"] == 70 and m.confidence == 0.7 for m in signals)
    summaries = {m.payload["user_id"]: m.payload for m in messages
                 if m.kind == "info" and "tickers_scanned" in m.payload}
    for uid, summary in summaries.items():
        assert summary["bullish_count"] == summary["bearish_count"] == 1
        assert summary["neutral_count"] == 1  # bearish spot crypto excluded
        assert summary["signals_by_direction"] == dict.fromkeys(
            ("bullish", "bearish"), 1 if uid == "book-a" else 0)
        assert summary["below_threshold_by_direction"] == dict.fromkeys(
            ("bullish", "bearish"), 0 if uid == "book-a" else 1)
    pulse = next(m.payload for m in messages if m.kind == "scanner_pulse")
    assert pulse["by_direction"] == {"bullish": 1, "bearish": 1}


def _friction_tick(incumbent_tcs=75, pool_strategies=None):
    agent = scanner.PatternDetectionAgent()
    agent._seeded_prev_strategy = True
    for uid in ("book-a", "book-b"):
        agent._prev_strategy[f"{uid}:AMD"] = ("default", 80)

    async def targets():
        return [(uid, ["AMD"]) for uid in ("book-a", "book-b")]

    async def pool(tickers, limit):
        return list(tickers), {"watchlist": len(tickers), "market_wide": 0}

    async def candles(*args):
        return _fixture()

    async def empty(uid):
        return {}

    async def no_override(uid, symbol):
        return None

    async def cycle(symbol):
        return SimpleNamespace(iv_environment="normal", days_until_earnings=None,
                               days_until_exdiv=None, earnings_time=None)

    def score(candles, context, strategy):
        value = incumbent_tcs if strategy == "default" else 85
        return scoring.Score(score=value, tcs=value, direction="bullish")

    with ExitStack() as patches:
        patches.enter_context(_patched(agent, _scan_targets=targets, _backtest_history=empty))
        patches.enter_context(_patched(scanner, fetch_candles_for=candles,
            expanded_scan_pool=pool, eligible_strategies=lambda *a, **k:
                pool_strategies or ["default", "pattern"]))
        patches.enter_context(_patched(selector, calculate_score=score))
        patches.enter_context(_patched(settings, get_bot_settings=lambda uid:
            settings.BotSettings(tcs_threshold=70, pattern_enabled=True,
                switching_mode="fixed", switching_advantage_pct=10 if uid == "book-a" else 2)))
        patches.enter_context(_patched(edges, get_live_strategy_edge=empty))
        patches.enter_context(_patched(cycles, get_cycle_position=cycle))
        patches.enter_context(_patched(overrides, get_strategy_override=no_override))
        messages = asyncio.run(agent.tick())
    assert not [m for m in messages if m.kind == "error"], messages
    return agent, messages


def test_strategy_held_message_matches_actual_selected_signal_for_its_book():
    agent, messages = _friction_tick()
    signals = {m.payload["user_id"]: m for m in messages if m.kind == "signal"}
    assert signals["book-a"].payload["strategy"] == "default"
    assert signals["book-a"].payload["tcs"] == 75
    assert signals["book-a"].payload["strategy_selection"]["chosen"] == "default"
    assert len(signals["book-a"].payload["strategy_selection"]["considered"]) == 2
    assert signals["book-b"].payload["strategy"] == "pattern"
    held = next(m for m in messages if m.kind == "strategy_held")
    assert held.payload["user_id"] == "book-a"
    assert (held.payload["held"], held.payload["held_tcs"],
            held.payload["challenger"], held.payload["challenger_tcs"]) == (
                "default", 75, "pattern", 85)
    assert held.confidence == signals["book-a"].confidence == 0.75
    assert agent._prev_strategy["book-a:AMD"] == ("default", 75)
    assert agent._prev_strategy["book-b:AMD"] == ("pattern", 85)


def test_held_strategy_cannot_use_its_old_score_to_bypass_current_entry_floor():
    _, messages = _friction_tick(incumbent_tcs=60)
    signals = [m for m in messages if m.kind == "signal"]
    assert len(signals) == 1 and signals[0].payload["user_id"] == "book-b"
    held = next(m for m in messages if m.kind == "strategy_held")
    assert held.payload["prev_tcs"] == 80 and held.payload["held_tcs"] == 60


def test_switching_friction_cannot_reinstate_an_ineligible_strategy():
    _, messages = _friction_tick(pool_strategies=["pattern"])
    assert not [m for m in messages if m.kind == "strategy_held"]
    signals = [m for m in messages if m.kind == "signal"]
    assert len(signals) == 2
    assert all(m.payload["strategy"] == "pattern" for m in signals)
    assert all("no longer eligible" in m.payload["strategy_selection"]["reason"] for m in signals)


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
