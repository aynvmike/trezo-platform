"""Backtest engine - replay historical candles through Trezo's scoring.

#121. Walks a candle series bar by bar, scores each bar with the same
calculate_score() the live agents use, simulates long entries when the
Trade Confidence Score crosses threshold, and exits each trade at its
stop or target. Reports win rate, profit factor, drawdown and more, so
a strategy can be judged on history before it ever trades live.

Long-only and single-position (one open trade at a time) - a faithful,
contained model of how Trezo's scanners actually trade.

Each trade also records the TCS and dominant candlestick pattern at the
moment it was opened, so the UI can show *why* a trade was taken.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from app.patterns.scoring import calculate_score, MarketContext

WARMUP_BARS = 60          # bars of history the indicators need before scoring


@dataclass
class BacktestTrade:
    entry_index: int
    entry_price: float
    exit_index: int
    exit_price: float
    pnl_pct: float
    outcome: str           # 'win' | 'loss'
    bars_held: int
    exit_reason: str       # 'target' | 'stop' | 'end'
    entry_tcs: int = 0     # Trade Confidence Score at entry
    entry_pattern: Optional[str] = None  # dominant candle pattern at entry


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    bars: int
    trades: int
    wins: int
    losses: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    expectancy_pct: float
    total_return_pct: float
    max_drawdown_pct: float
    tcs_threshold: int
    trade_log: list = field(default_factory=list)
    candles: list = field(default_factory=list)  # [{c}] close series, for the chart
    # Diagnostic: the highest TCS seen during the run, even if nothing
    # crossed threshold. Lets the UI suggest a sensible threshold when
    # no trades fired (#121 follow-up).
    peak_tcs: int = 0
    peak_tcs_index: int = -1
    peak_tcs_direction: str = "neutral"


    def to_dict(self) -> dict:
        return asdict(self)


def run_backtest(symbol: str, candles: list, strategy: str = "default",
                 tcs_threshold: int = 700, stop_pct: float = 0.05,
                 target_pct: float = 0.10) -> BacktestResult:
    """Replay `candles` through the scorer and simulate the trades."""
    n = len(candles)
    trades: list[BacktestTrade] = []
    open_trade: Optional[dict] = None
    peak_tcs = 0
    peak_idx = -1
    peak_dir = "neutral"

    for i in range(WARMUP_BARS, n):
        bar = candles[i]

        if open_trade is not None:
            entry = open_trade["entry_price"]
            stop = entry * (1.0 - stop_pct)
            target = entry * (1.0 + target_pct)
            exit_price: Optional[float] = None
            reason = ""
            # If both stop and target fall inside the bar, assume the
            # stop hit first - the conservative read.
            if float(bar.low) <= stop:
                exit_price, reason = stop, "stop"
            elif float(bar.high) >= target:
                exit_price, reason = target, "target"
            if exit_price is not None:
                pnl = (exit_price - entry) / entry
                trades.append(BacktestTrade(
                    entry_index=open_trade["entry_index"],
                    entry_price=round(entry, 4),
                    exit_index=i, exit_price=round(exit_price, 4),
                    pnl_pct=round(pnl * 100, 2),
                    outcome="win" if pnl >= 0 else "loss",
                    bars_held=i - open_trade["entry_index"],
                    exit_reason=reason,
                    entry_tcs=open_trade["entry_tcs"],
                    entry_pattern=open_trade["entry_pattern"]))
                open_trade = None
            continue

        # Flat - score this bar and look for a long entry.
        score = calculate_score(candles[:i + 1], MarketContext(),
                                strategy=strategy)
        if int(score.tcs) > peak_tcs:
            peak_tcs = int(score.tcs)
            peak_idx = i
            peak_dir = score.direction
        if score.tcs >= tcs_threshold and score.direction == "bullish":
            open_trade = {"entry_index": i, "entry_price": float(bar.close),
                          "entry_tcs": int(score.tcs),
                          "entry_pattern": score.dominant_pattern}

    # Close any still-open trade at the final bar.
    if open_trade is not None and n > 0:
        entry = open_trade["entry_price"]
        last = float(candles[-1].close)
        pnl = (last - entry) / entry
        trades.append(BacktestTrade(
            entry_index=open_trade["entry_index"], entry_price=round(entry, 4),
            exit_index=n - 1, exit_price=round(last, 4),
            pnl_pct=round(pnl * 100, 2),
            outcome="win" if pnl >= 0 else "loss",
            bars_held=n - 1 - open_trade["entry_index"], exit_reason="end",
            entry_tcs=open_trade["entry_tcs"],
            entry_pattern=open_trade["entry_pattern"]))

    chart_pts = [{"c": round(float(c.close), 4)} for c in candles]
    return _summarize(symbol, strategy, n, tcs_threshold, trades, chart_pts,
                       peak_tcs=peak_tcs, peak_idx=peak_idx, peak_dir=peak_dir)


def _summarize(symbol: str, strategy: str, bars: int, tcs_threshold: int,
               trades: list, chart_pts: list, *, peak_tcs: int = 0,
               peak_idx: int = -1, peak_dir: str = "neutral") -> BacktestResult:
    wins = [t for t in trades if t.outcome == "win"]
    losses = [t for t in trades if t.outcome == "loss"]
    nt = len(trades)
    win_rate = round(len(wins) / nt, 3) if nt else 0.0
    avg_win = round(sum(t.pnl_pct for t in wins) / len(wins), 2) if wins else 0.0
    avg_loss = round(sum(t.pnl_pct for t in losses) / len(losses), 2) if losses else 0.0

    gross_win = sum(t.pnl_pct for t in wins)
    gross_loss = abs(sum(t.pnl_pct for t in losses))
    if gross_loss > 0:
        profit_factor = round(gross_win / gross_loss, 2)
    else:
        profit_factor = 999.0 if gross_win > 0 else 0.0
    expectancy = round(sum(t.pnl_pct for t in trades) / nt, 2) if nt else 0.0

    # Compounded equity curve -> total return + worst drawdown.
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for t in trades:
        equity *= (1.0 + t.pnl_pct / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    total_return = round((equity - 1.0) * 100, 2)

    return BacktestResult(
        symbol=symbol, strategy=strategy, bars=bars, trades=nt,
        wins=len(wins), losses=len(losses), win_rate=win_rate,
        avg_win_pct=avg_win, avg_loss_pct=avg_loss,
        profit_factor=profit_factor, expectancy_pct=expectancy,
        total_return_pct=total_return,
        max_drawdown_pct=round(max_dd * 100, 2),
        tcs_threshold=tcs_threshold,
        trade_log=[asdict(t) for t in trades[-50:]],
        candles=chart_pts,
        peak_tcs=peak_tcs,
        peak_tcs_index=peak_idx,
        peak_tcs_direction=peak_dir,
    )


# Every directional strategy Trezo can backtest. Options and the Dividend
# Wheel are not stop/target directional trades, so they are excluded.
BACKTEST_STRATEGIES = ["default", "pattern", "stms", "orb", "crypto", "extended"]


def compare_strategies(symbol: str, candles: list, tcs_threshold: int = 700,
                        stop_pct: float = 0.05,
                        target_pct: float = 0.10) -> dict:
    """Run every strategy over the same candles and pick the best one.

    'Best' = among strategies that actually traded, the one with the
    highest total return, favouring a profit factor of at least 1.0
    (won more than it lost). Returns one shared candle series plus a
    per-strategy result list, so the front-end draws one chart per pick.
    """
    results: list[dict] = []
    for strat in BACKTEST_STRATEGIES:
        res = run_backtest(symbol, candles, strategy=strat,
                           tcs_threshold=tcs_threshold,
                           stop_pct=stop_pct, target_pct=target_pct)
        d = res.to_dict()
        d.pop("candles", None)        # candles are shared at the top level
        results.append(d)

    traded = [r for r in results if r["trades"] > 0]
    best: Optional[str] = None
    if traded:
        traded.sort(
            key=lambda r: (r["profit_factor"] >= 1.0,
                           r["total_return_pct"],
                           r["profit_factor"]),
            reverse=True)
        best = traded[0]["strategy"]

    # Across-strategy peak — useful when nothing crossed threshold.
    peak_overall = max((int(r.get("peak_tcs", 0)) for r in results), default=0)
    peak_strat = None
    if peak_overall > 0:
        for r in results:
            if int(r.get("peak_tcs", 0)) == peak_overall:
                peak_strat = r["strategy"]
                break

    return {
        "symbol": symbol,
        "candles": [{"c": round(float(c.close), 4)} for c in candles],
        "strategies": results,
        "best_strategy": best,
        "peak_tcs": peak_overall,
        "peak_strategy": peak_strat,
    }
