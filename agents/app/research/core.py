"""Deterministic rule composition and historical screening, research only.

This small grammar composes approved trend and entry rules. It does not
invent arbitrary indicators or Python. A passing historical screen only
creates a candidate for forward testing, never permission to trade.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

POLICY_VERSION = "restricted-research-v1"
MIN_BARS = 180
MAX_BARS = 1200
MAX_CANDIDATES = 4


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def normalize_candles(candles: list) -> list[dict]:
    if not isinstance(candles, (list, tuple)) or not MIN_BARS <= len(candles) <= MAX_BARS:
        raise ValueError(f"research requires {MIN_BARS} to {MAX_BARS} completed bars")
    out = []
    previous = None
    now = datetime.now(timezone.utc)
    for raw in candles:
        def field(name):
            return raw.get(name) if isinstance(raw, dict) else getattr(raw, name, None)
        stamp = field("timestamp")
        if isinstance(stamp, str):
            try:
                stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("invalid candle timestamp") from exc
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("candle timestamp must include a timezone")
        stamp = stamp.astimezone(timezone.utc)
        if stamp > now or (previous is not None and stamp <= previous):
            raise ValueError("candle timestamps must be increasing, unique and not future-dated")
        previous = stamp
        bar = {name: finite(field(name), name) for name in ("open", "high", "low", "close")}
        if (min(bar.values()) <= 0 or bar["low"] > min(bar["open"], bar["close"])
                or bar["high"] < max(bar["open"], bar["close"]) or bar["low"] > bar["high"]):
            raise ValueError("candle OHLC prices are inconsistent")
        out.append({"timestamp": stamp.isoformat(), **bar})
    return out


@dataclass(frozen=True)
class Assumptions:
    starting_capital: float
    commission_bps: float
    slippage_bps: float
    fixed_cost_usd: float = 0.0
    position_fraction: float = 0.25

    def __post_init__(self):
        for key, value in asdict(self).items():
            finite(value, key)
        if not 1 <= self.starting_capital <= 1_000_000_000:
            raise ValueError("starting capital is outside research bounds")
        if not 0 <= self.commission_bps <= 200 or not 0 <= self.slippage_bps <= 200:
            raise ValueError("cost assumptions must be between 0 and 200 bps per leg")
        if not 0 <= self.fixed_cost_usd <= self.starting_capital:
            raise ValueError("fixed cost must be nonnegative and no greater than capital")
        if self.position_fraction != 0.25:
            raise ValueError("this research policy fixes position allocation at 25 percent")


@dataclass(frozen=True)
class Candidate:
    book_id: str
    symbol: str
    entry_rule: str
    trend_bars: int = 20
    entry_bars: int = 10
    stop_pct: float = 0.03
    target_pct: float = 0.06
    max_hold_bars: int = 12
    parent_id: str | None = None
    policy_version: str = POLICY_VERSION

    def __post_init__(self):
        if not self.book_id or not self.symbol or self.policy_version != POLICY_VERSION:
            raise ValueError("candidate scope or policy is invalid")
        if self.entry_rule not in {"breakout_high", "pullback_recovery"}:
            raise ValueError("entry rule is not in the approved grammar")
        for name, lo, hi in (("trend_bars", 10, 60), ("entry_bars", 2, 30),
                             ("max_hold_bars", 2, 30)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                raise ValueError(f"{name} is outside the approved bounds")
        if not 0.01 <= finite(self.stop_pct, "stop_pct") <= 0.08:
            raise ValueError("stop is outside the approved bounds")
        if not 0.02 <= finite(self.target_pct, "target_pct") <= 0.16:
            raise ValueError("target is outside the approved bounds")

    def spec(self) -> dict:
        return {**asdict(self), "entry_rules": ["close_above_trend_sma", self.entry_rule],
                "direction": "long", "execution": "next_bar_open",
                "exit_rules": ["gap_aware_stop", "target", "maximum_hold", "window_end"],
                "position_policy": "quarter_equity_fractional_simulation"}

    @property
    def candidate_id(self) -> str:
        return digest(self.spec())


def propose(book_id: str, symbol: str) -> list[Candidate]:
    return [Candidate(book_id, symbol, "breakout_high"),
            Candidate(book_id, symbol, "pullback_recovery", entry_bars=3)]


def refine(parent: Candidate, train_result: dict) -> list[Candidate]:
    """Only training evidence is accepted; validation never enters this API."""
    if train_result.get("phase") != "train":
        raise ValueError("refinement requires training evidence")
    if train_result.get("candidate_id") != parent.candidate_id:
        raise ValueError("training evidence does not belong to the parent")
    favorable = finite(train_result.get("net_pnl_usd"), "training P&L") > 0
    if parent.trend_bars < 60:
        trend_child = replace(parent, parent_id=parent.candidate_id,
                              trend_bars=min(60, parent.trend_bars + (10 if favorable else 20)))
    else:
        trend_child = replace(parent, parent_id=parent.candidate_id,
                              max_hold_bars=parent.max_hold_bars + 2 if parent.max_hold_bars <= 28 else 4)
    if parent.entry_bars < 30:
        entry_child = replace(parent, parent_id=parent.candidate_id,
                              entry_bars=min(30, parent.entry_bars + (2 if favorable else 5)))
    else:
        entry_child = replace(parent, parent_id=parent.candidate_id,
                              target_pct=0.08 if parent.target_pct != 0.08 else 0.06)
    return [trend_child, entry_child]


def _entry(candles: list[dict], index: int, candidate: Candidate) -> bool:
    needed = max(candidate.trend_bars, candidate.entry_bars + 1)
    if index + 1 < needed:
        return False
    current = candles[index]
    trend = sum(bar["close"] for bar in candles[index + 1 - candidate.trend_bars:index + 1]) / candidate.trend_bars
    if current["close"] <= trend:
        return False
    prior = candles[index - candidate.entry_bars:index]
    if candidate.entry_rule == "breakout_high":
        return current["close"] > max(bar["high"] for bar in prior)
    return (min(bar["low"] for bar in prior) <= trend
            and current["close"] > candles[index - 1]["close"])


def replay(candles: list[dict], candidate: Candidate, assumptions: Assumptions,
           *, start: int, end: int, phase: str) -> dict:
    """Replay one independent window, with earlier bars usable as warmup.

    Positions always start flat. At most one position and 25% equity is
    used; remaining cash is included in returns. Drawdown uses marked
    end-of-bar account equity. Intrabar equity minima are not measured.
    """
    if phase not in {"train", "validation"} or not 0 <= start < end <= len(candles):
        raise ValueError("invalid replay window")
    capital = assumptions.starting_capital
    cash = capital
    fee = assumptions.commission_bps / 10_000
    slip = assumptions.slippage_bps / 10_000
    position = None
    pending = None
    trades = []
    equity_curve = []
    peak = capital
    max_dd = 0.0
    total_fees = 0.0

    for index in range(start, end):
        bar = candles[index]
        if pending is not None:
            entry_price = bar["open"] * (1 + slip)
            budget = cash * assumptions.position_fraction
            qty = math.floor(budget / (entry_price * (1 + fee)) * 1_000_000) / 1_000_000
            if qty > 0:
                entry_fee = qty * entry_price * fee
                cash -= qty * entry_price + entry_fee
                total_fees += entry_fee
                position = {"entry_index": index, "entry_at": bar["timestamp"],
                            "decision_index": pending, "decision_at": candles[pending]["timestamp"],
                            "entry_price": entry_price, "qty": qty, "entry_fee": entry_fee}
            pending = None

        if position is not None:
            stop = position["entry_price"] * (1 - candidate.stop_pct)
            target = position["entry_price"] * (1 + candidate.target_pct)
            exit_raw, reason = None, None
            if bar["open"] <= stop:
                exit_raw, reason = bar["open"], "gap_stop"
            elif bar["open"] >= target:
                exit_raw, reason = bar["open"], "gap_target"
            elif bar["low"] <= stop:
                exit_raw, reason = stop, "stop"
            elif bar["high"] >= target:
                exit_raw, reason = target, "target"
            elif index - position["entry_index"] + 1 >= candidate.max_hold_bars:
                exit_raw, reason = bar["close"], "maximum_hold"
            if index == end - 1 and exit_raw is None:
                exit_raw, reason = bar["close"], "window_end"
            if exit_raw is not None:
                exit_price = exit_raw * (1 - slip)
                exit_fee = position["qty"] * exit_price * fee
                cash += position["qty"] * exit_price - exit_fee
                total_fees += exit_fee
                pnl = (position["qty"] * (exit_price - position["entry_price"])
                       - position["entry_fee"] - exit_fee)
                trades.append({**position, "exit_index": index, "exit_at": bar["timestamp"],
                               "exit_price": exit_price, "exit_fee": exit_fee,
                               "net_pnl_usd": pnl, "exit_reason": reason})
                position = None

        equity = cash + (position["qty"] * bar["close"] if position else 0.0)
        # Fixed research-period costs are charged proportionally to each
        # time window, at its end. They never become trading income.
        if index == end - 1:
            window_cost = assumptions.fixed_cost_usd * (end - start) / len(candles)
            cash -= window_cost
            equity -= window_cost
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        equity_curve.append({"index": index, "timestamp": bar["timestamp"],
                             "equity": equity, "cash": cash,
                             "position_qty": position["qty"] if position else 0.0})
        if position is None and index < end - 1 and _entry(candles, index, candidate):
            pending = index

    net = cash - capital
    wins = sum(trade["net_pnl_usd"] > 0 for trade in trades)
    gross_wins = sum(max(0, trade["net_pnl_usd"]) for trade in trades)
    gross_losses = -sum(min(0, trade["net_pnl_usd"]) for trade in trades)
    benchmark_qty = capital * assumptions.position_fraction / (candles[start]["open"] * (1 + slip) * (1 + fee))
    benchmark_cash = capital * (1 - assumptions.position_fraction)
    benchmark_end = (benchmark_cash + benchmark_qty * candles[end - 1]["close"] * (1 - slip) * (1 - fee)
                     - assumptions.fixed_cost_usd * (end - start) / len(candles))
    return {"candidate_id": candidate.candidate_id, "phase": phase,
            "start_index": start, "end_index_exclusive": end,
            "start_at": candles[start]["timestamp"], "end_at": candles[end - 1]["timestamp"],
            "starting_capital": capital, "ending_equity": cash, "net_pnl_usd": net,
            "net_return_pct": net / capital * 100, "trades": len(trades),
            "win_rate": wins / len(trades) if trades else 0.0,
            "profit_factor": gross_wins / gross_losses if gross_losses > 0 else None,
            "max_drawdown_pct": max_dd * 100, "commission_usd": total_fees,
            "fixed_cost_usd": assumptions.fixed_cost_usd * (end - start) / len(candles),
            "benchmark_net_return_pct": (benchmark_end - capital) / capital * 100,
            "benchmark": "25_percent_buy_and_hold_plus_cash",
            "drawdown_basis": "marked_end_of_bar_equity",
            "timestamp_semantics": "input_bar_labels; decisions_at_close_and_entries_at_next_open",
            "trade_log": trades, "equity_curve": equity_curve}


def screen(train: dict, validation: dict) -> tuple[str, list[str]]:
    reasons = []
    if train["trades"] < 3 or validation["trades"] < 3:
        reasons.append("fewer_than_three_trades_in_a_window")
    if train["net_pnl_usd"] <= 0 or validation["net_pnl_usd"] <= 0:
        reasons.append("nonpositive_net_result_in_a_window")
    if validation["net_return_pct"] <= validation["benchmark_net_return_pct"]:
        reasons.append("validation_did_not_exceed_passive_comparator")
    if max(train["max_drawdown_pct"], validation["max_drawdown_pct"]) > 10:
        reasons.append("historical_drawdown_exceeds_research_screen")
    return ("rejected", reasons) if reasons else ("shadow_candidate", ["preliminary_historical_screen_passed"])
