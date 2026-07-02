"""Per-stock strategy selection (#121 follow-up).

No single strategy suits every stock. When Trezo scans a watchlist for
trading, it scores each stock under every eligible directional strategy
and trades the strongest one *for that stock* — quality-gated by how each
strategy has performed on it in past backtests (the backtest_runs log).

This is the trading-side counterpart of the /backtest/compare endpoint:
the backtest tells you which strategy did best on history; this picks the
strategy with the best read right now, with history as the quality gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.patterns.scoring import calculate_score, MarketContext

# Directional strategies that can be auto-selected, by asset type.
# Options and the Dividend Wheel are not stop/target directional trades,
# so they are not part of the selection pool.
STOCK_STRATEGIES = ["default", "pattern", "stms", "orb", "extended", "scalp"]
CRYPTO_STRATEGIES = ["default", "pattern", "crypto", "extended"]

# Cycle-aware strategies (Phase 13a). These ONLY appear in the
# eligible pool when the symbol's cycle position matches:
#   iv_crush_short    : 1-7 days before earnings (sell rich premium)
#   dividend_capture  : -2 to +5 days from ex-div (collect dividend +
#                       price recovery)
# When matched, they bypass the Risk Manager's earnings-day TCS bump
# because they're INTENDED for that window. See risk_manager.py for
# the bypass logic.
CYCLE_STRATEGIES = ["iv_crush_short", "dividend_capture_long"]


@dataclass
class StrategyPick:
    strategy: str
    tcs: int
    score: int
    direction: str
    dominant_pattern: Optional[str] = None
    detected_patterns: list = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)
    considered: list = field(default_factory=list)
    reason: str = ""


def eligible_strategies(asset_type: str, *, in_stms_window: bool = True,
                        in_orb_window: bool = True,
                        in_swing_window: bool = True,
                        iv_environment: str = "normal",
                        days_until_earnings: Optional[int] = None,
                        days_until_exdiv: Optional[int] = None) -> list[str]:
    """The strategies worth scoring right now.

    Window-bound strategies (STMS in the morning, ORB during the opening
    range, Extended during its swing window) drop out when their window
    is closed — so the bot never picks a strategy that could not
    legitimately trade at this moment.

    Cycle-aware strategies (Phase 13a) appear in the pool ONLY when the
    symbol's cycle position matches:
      iv_crush_short      : 1-7 days before earnings (high IV env).
      dividend_capture    : -2 to +5 days from ex-div (dividend window).
    """
    base = CRYPTO_STRATEGIES if asset_type == "crypto" else STOCK_STRATEGIES
    out: list[str] = []
    for s in base:
        if s == "stms" and not in_stms_window:
            continue
        if s == "orb" and not in_orb_window:
            continue
        if s == "extended" and not in_swing_window:
            continue
        out.append(s)

    # Cycle strategies bolt on when conditions match. Stocks only -
    # crypto has no earnings or dividends.
    if asset_type != "crypto":
        if iv_environment == "high" or (
            isinstance(days_until_earnings, int) and 1 <= days_until_earnings <= 7
        ):
            out.append("iv_crush_short")
        if iv_environment == "dividend_window" or (
            isinstance(days_until_exdiv, int) and -2 <= days_until_exdiv <= 5
        ):
            out.append("dividend_capture_long")

    return out or ["default"]


def select_strategy(candles, *, ctx: Optional[MarketContext] = None,
                    history: Optional[dict] = None,
                    strategies: Optional[list] = None,
                    outcome_edge: Optional[dict] = None) -> StrategyPick:
    """Score `candles` under each strategy and pick the best for this
    stock right now.

    `history` is {strategy: avg_backtest_return_pct} for this ticker — it
    drops strategies that have a net-loss record on the stock and breaks
    ties between equally-confident strategies.
    """
    ctx = ctx or MarketContext()
    strategies = strategies or STOCK_STRATEGIES
    history = history or {}

    edge = outcome_edge or {}
    rows: list[dict] = []
    for strat in strategies:
        sc = calculate_score(candles, ctx, strategy=strat)
        e = edge.get(strat) or {}
        rows.append({"strategy": strat, "score": sc, "tcs": int(sc.tcs),
                     "direction": sc.direction,
                     "hist": history.get(strat),
                     "verdict": e.get("verdict", "insufficient_data"),
                     "expectancy": float(e.get("expectancy_usd") or 0.0)})

    # Long-only bot: prefer bullish reads. Drop strategies with a
    # net-loss backtest history on this stock from the running.
    bull = [r for r in rows if r["direction"] == "bullish"]
    healthy = [r for r in bull if (r["hist"] is None or r["hist"] >= 0)]
    # Outcome-weighted (2026-06-16): when alternatives exist, drop the
    # strategies the user's LIVE record says to avoid (negative realized
    # expectancy over a meaningful sample). Falls back to `healthy` when
    # that would empty the pool, so a thin / all-avoid record never
    # strands the selector.
    not_avoid = [r for r in healthy if r["verdict"] != "avoid"]
    pool = not_avoid or healthy or bull or rows

    # Highest live TCS wins; then a proven live edge ("favor"); then
    # realized expectancy; then backtest history as the final tiebreak.
    pool.sort(key=lambda r: (
        r["tcs"],
        1 if r["verdict"] == "favor" else 0,
        r["expectancy"],
        r["hist"] or 0.0,
    ), reverse=True)
    win = pool[0]
    sc = win["score"]

    considered = sorted(
        [{"strategy": r["strategy"], "tcs": r["tcs"],
          "direction": r["direction"], "backtest_return_pct": r["hist"],
          "live_verdict": r["verdict"]}
         for r in rows],
        key=lambda d: d["tcs"], reverse=True)

    return StrategyPick(
        strategy=win["strategy"], tcs=int(sc.tcs), score=int(sc.score),
        direction=sc.direction, dominant_pattern=sc.dominant_pattern,
        detected_patterns=list(sc.detected_patterns or []),
        breakdown=dict(sc.breakdown or {}),
        considered=considered,
        reason=_reason(win, len(strategies)))


def _reason(win: dict, n_tested: int) -> str:
    name = win["strategy"]
    bits = [f"Tested {n_tested} strategies; '{name}' gave the strongest "
            f"read (TCS {win['tcs']})."]
    h = win["hist"]
    if h is not None:
        if h >= 0:
            bits.append(f"It also leads this stock's backtests ({h:+.1f}%).")
        else:
            bits.append("Other strategies have a weaker backtest record here.")
    v = win.get("verdict")
    if v == "favor":
        bits.append(f"Live record favors it (avg ${win.get('expectancy', 0):+.0f}/trade).")
    elif v == "avoid":
        bits.append("Note: its live record is weak; kept only for lack of a better fit.")
    return " ".join(bits)
