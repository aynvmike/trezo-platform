"""Simulation Lab — replay every directional strategy across a watchlist
over a recent window, aggregate the resulting trades into an equity
curve, and report what the agents would have done.

This is the stress-test harness the beta testers will rely on:
- Take a list of tickers (typically the user's default watchlist).
- For each, run compare_strategies (the same one the multi-strategy
  backtest uses) so every strategy is scored and the best one wins.
- Walk every winning strategy's trade_log, keep only the trades whose
  entries fall inside the window of interest, and date them using the
  candle index (last bar of the window = today).
- Size each trade as a fixed fraction of the starting equity. Apply
  trades chronologically to build an equity curve.

The point is to see how the system behaves end-to-end at a chosen
account size over a real recent window — not to replace a backtest.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.data.candles import fetch_candles_for, COIN_MAP
from app.backtest.engine import compare_strategies

import logging

logger = logging.getLogger(__name__)

# Mem0 outcome logging is best-effort - never block a simulation if
# the memory layer is unreachable. Imports are inside the helper to
# defer cost when memory isn't configured.


# Notional fraction of starting equity placed on each trade. Conservative:
# 25% of equity goes into a position, so a 10% gain on the trade lifts
# overall equity by 2.5%. Easy to reason about; not a sizing model.
TRADE_FRACTION = 0.25


def _candle_date(c) -> str:
    ts = getattr(c, "timestamp", None)
    if isinstance(ts, datetime):
        return ts.date().isoformat()
    return ""


async def run_simulation(symbols: list[str], days: int,
                         starting_equity: float,
                         tcs_threshold: int = 650,
                         stop_pct: float = 0.05,
                         target_pct: float = 0.10,
                         compare_all: bool = True) -> dict:
    """Replay the agents over the last `days` of history for `symbols`.

    Returns a dict the Simulation Lab page renders directly."""
    days = max(1, min(int(days), 365))
    starting_equity = float(max(100.0, min(starting_equity, 10_000_000.0)))
    sp = min(0.5, max(0.01, float(stop_pct)))
    tp = min(1.0, max(0.01, float(target_pct)))

    per_symbol: list[dict] = []
    all_trades: list[dict] = []

    for sym in symbols:
        sym_u = sym.strip().upper()
        if not sym_u:
            continue
        try:
            candles = await fetch_candles_for(sym_u, "stock")
        except Exception as e:  # noqa: BLE001
            per_symbol.append({"symbol": sym_u,
                                "error": f"Could not fetch history: {e}"})
            continue
        if not candles or len(candles) < 70:
            per_symbol.append({"symbol": sym_u,
                                "error": "Not enough historical data."})
            continue

        # Cut-off index: only count trades that ENTER within the last `days`
        # bars. Each bar = one trading day on daily candles.
        n = len(candles)
        cutoff_index = max(0, n - days)

        cmp = compare_strategies(sym_u, candles, tcs_threshold=int(tcs_threshold),
                                 stop_pct=sp, target_pct=tp)

        # Track the closest-to-firing strategy across all of them so a
        # zero-trade window still attributes a row to something useful.
        peak_strat: Optional[str] = None
        peak_value: int = -1
        for strat_dict in cmp.get("strategies", []):
            pk = int(strat_dict.get("peak_tcs", 0) or 0)
            if pk > peak_value:
                peak_value = pk
                peak_strat = strat_dict.get("strategy")

        if compare_all:
            # Multi-strategy: keep every strategy's trades in the
            # window. One per_symbol row per strategy that actually
            # produced a trade — so the breakdown by strategy is real.
            per_sym_by_strat: dict[str, dict] = {}
            kept_any = False
            for strat_dict in cmp.get("strategies", []):
                strat_name = strat_dict.get("strategy") or "default"
                in_window = [t for t in strat_dict.get("trade_log", [])
                              if int(t.get("entry_index", 0)) >= cutoff_index]
                if not in_window:
                    continue
                kept_any = True
                bucket = per_sym_by_strat.setdefault(strat_name, {
                    "strategy": strat_name, "trades": 0,
                    "wins": 0, "losses": 0, "pnl_pct": 0.0
                })
                for t in in_window:
                    ei = int(t.get("entry_index", 0))
                    xi = int(t.get("exit_index", 0))
                    ei = max(0, min(ei, n - 1)); xi = max(0, min(xi, n - 1))
                    t["symbol"] = sym_u
                    t["strategy"] = strat_name
                    t["entry_date"] = _candle_date(candles[ei])
                    t["exit_date"] = _candle_date(candles[xi])
                    all_trades.append(t)
                    bucket["trades"] += 1
                    if t.get("outcome") == "win":
                        bucket["wins"] += 1
                    else:
                        bucket["losses"] += 1
                    bucket["pnl_pct"] += float(t.get("pnl_pct", 0.0))
            if not kept_any:
                per_symbol.append({
                    "symbol": sym_u, "strategy": peak_strat,
                    "trades": 0, "wins": 0, "losses": 0, "pnl_pct": 0.0,
                    "peak_tcs": peak_value if peak_value > 0 else 0,
                    "peak_strategy": peak_strat,
                })
            else:
                for b in per_sym_by_strat.values():
                    b["pnl_pct"] = round(b["pnl_pct"], 2)
                    per_symbol.append({
                        "symbol": sym_u, **b,
                        "peak_tcs": peak_value if peak_value > 0 else 0,
                        "peak_strategy": peak_strat,
                    })
        else:
            # Single-strategy: most-trades wins; ties break by total pnl.
            chosen_strat: Optional[str] = None
            chosen_trades: list[dict] = []
            chosen_score = (-1, -1e9)
            for strat_dict in cmp.get("strategies", []):
                in_window = [t for t in strat_dict.get("trade_log", [])
                              if int(t.get("entry_index", 0)) >= cutoff_index]
                pnl_sum = sum(float(t.get("pnl_pct", 0.0)) for t in in_window)
                score = (len(in_window), pnl_sum)
                if score > chosen_score:
                    chosen_score = score
                    chosen_strat = strat_dict.get("strategy")
                    chosen_trades = in_window
            if not chosen_trades and peak_strat:
                chosen_strat = peak_strat
            for t in chosen_trades:
                ei = int(t.get("entry_index", 0))
                xi = int(t.get("exit_index", 0))
                ei = max(0, min(ei, n - 1)); xi = max(0, min(xi, n - 1))
                t["symbol"] = sym_u
                t["strategy"] = chosen_strat
                t["entry_date"] = _candle_date(candles[ei])
                t["exit_date"] = _candle_date(candles[xi])
                all_trades.append(t)
            per_symbol.append({
                "symbol": sym_u,
                "strategy": chosen_strat,
                "trades": len(chosen_trades),
                "wins": sum(1 for t in chosen_trades if t.get("outcome") == "win"),
                "losses": sum(1 for t in chosen_trades if t.get("outcome") == "loss"),
                "pnl_pct": round(sum(float(t.get("pnl_pct", 0.0)) for t in chosen_trades), 2),
                "peak_tcs": peak_value if peak_value > 0 else 0,
                "peak_strategy": peak_strat,
            })

    # Sort trades chronologically by entry date, then exit date.
    all_trades.sort(key=lambda t: (t.get("entry_date") or "", t.get("exit_date") or ""))

    # Build equity curve. Each trade contributes pnl_pct * TRADE_FRACTION
    # of starting equity. Curve is keyed by exit_date — the date the P&L
    # was realised. Multiple closes on the same day combine.
    curve: list[dict] = []
    equity = starting_equity
    by_strategy: dict[str, dict] = {}
    pending_by_date: dict[str, float] = {}
    for t in all_trades:
        gain_usd = (float(t.get("pnl_pct", 0.0)) / 100.0) * starting_equity * TRADE_FRACTION
        ed = t.get("exit_date") or ""
        pending_by_date[ed] = pending_by_date.get(ed, 0.0) + gain_usd
        s = t.get("strategy") or "default"
        b = by_strategy.setdefault(s, {"trades": 0, "wins": 0,
                                        "losses": 0, "pnl_usd": 0.0,
                                        "tcs_sum": 0, "tcs_n": 0,
                                        "tcs_min": None, "tcs_max": None})
        b["trades"] += 1
        if t.get("outcome") == "win":
            b["wins"] += 1
        else:
            b["losses"] += 1
        b["pnl_usd"] += gain_usd
        tcs = int(t.get("entry_tcs") or 0)
        if tcs > 0:
            b["tcs_sum"] += tcs
            b["tcs_n"] += 1
            b["tcs_min"] = tcs if b["tcs_min"] is None else min(b["tcs_min"], tcs)
            b["tcs_max"] = tcs if b["tcs_max"] is None else max(b["tcs_max"], tcs)

    # Anchor the curve at the earliest exit date (start of the realised
    # window) and add a point per realised day.
    if pending_by_date:
        dates = sorted(pending_by_date.keys())
        # First, the starting point.
        curve.append({"date": dates[0], "equity": round(equity, 2),
                       "realized_today": 0.0})
        for d in dates:
            equity += pending_by_date[d]
            curve.append({"date": d, "equity": round(equity, 2),
                           "realized_today": round(pending_by_date[d], 2)})
    else:
        curve.append({"date": datetime.now(timezone.utc).date().isoformat(),
                       "equity": round(equity, 2), "realized_today": 0.0})

    # Round + finalise the per-strategy buckets for the wire.
    for s, b in by_strategy.items():
        b["pnl_usd"] = round(b["pnl_usd"], 2)
        b["avg_tcs"] = round(b["tcs_sum"] / b["tcs_n"], 1) if b["tcs_n"] else None
        b["tcs_min"] = b["tcs_min"] if b["tcs_min"] is not None else None
        b["tcs_max"] = b["tcs_max"] if b["tcs_max"] is not None else None
        # tcs_sum is an internal accumulator — drop from the wire shape.
        b.pop("tcs_sum", None)
        b.pop("tcs_n", None)

    # Phase G: log every simulated trade outcome to Mem0 with
    # metadata.source='simulation' so live agents can recall them
    # alongside real trade history. Best-effort - never blocks.
    _log_sim_outcomes_to_mem0(all_trades, starting_equity)

    return {
        "compare_all": bool(compare_all),
        "starting_equity": round(starting_equity, 2),
        "ending_equity": round(equity, 2),
        "return_pct": round((equity / starting_equity - 1.0) * 100.0, 2),
        "trade_fraction": TRADE_FRACTION,
        "window_days": days,
        "tcs_threshold": int(tcs_threshold),
        "symbols_tested": len([x for x in per_symbol if "error" not in x]),
        "symbols_skipped": len([x for x in per_symbol if "error" in x]),
        "per_symbol": per_symbol,
        "by_strategy": by_strategy,
        "trades": all_trades,
        "equity_curve": curve,
    }


def _log_sim_outcomes_to_mem0(trades: list[dict], starting_equity: float) -> None:
    """Push every simulated round-trip into Mem0 as a TradeOutcome.

    Marks metadata.source='simulation' so live agents can distinguish
    simulated history from realised trades when they recall_similar().
    Silent on any failure - memory is a force multiplier, not a hard
    dependency.
    """
    if not trades:
        return
    try:
        from app.memory import get_memory, TradeOutcome
    except Exception:  # noqa: BLE001
        return
    mem = get_memory()
    if not getattr(mem, "available", False):
        return

    logged = 0
    skipped = 0
    for t in trades:
        try:
            ticker = str(t.get("symbol") or "").upper()
            if not ticker:
                skipped += 1
                continue
            entry_price = float(t.get("entry_price") or 0.0)
            exit_price = float(t.get("exit_price") or 0.0)
            if entry_price <= 0 or exit_price <= 0:
                skipped += 1
                continue

            # Sim engine is long-only today; flag explicitly so the
            # memory record is unambiguous when other strategies start
            # emitting shorts later.
            side = str(t.get("side") or "long").lower()

            # P&L in USD = pnl_pct * 25% of starting equity per the
            # Simulation Lab fixed-fraction sizing model.
            pnl_pct = float(t.get("pnl_pct") or 0.0)
            realized_pnl_usd = (pnl_pct / 100.0) * starting_equity * TRADE_FRACTION

            # Holding days from entry/exit candle indices (each bar = 1d).
            ei = int(t.get("entry_index") or 0)
            xi = int(t.get("exit_index") or 0)
            holding_days = max(0, xi - ei)

            exit_reason = str(t.get("outcome") or "unknown")
            strategy = str(t.get("strategy") or "default")

            outcome = TradeOutcome(
                ticker=ticker,
                side=side,
                entry_price=entry_price,
                exit_price=exit_price,
                realized_pnl_usd=round(realized_pnl_usd, 2),
                holding_days=holding_days,
                exit_reason=exit_reason,
                strategy=strategy,
                metadata={
                    "source": "simulation",
                    "entry_date": t.get("entry_date") or "",
                    "exit_date": t.get("exit_date") or "",
                    "pnl_pct": round(pnl_pct, 2),
                    "entry_tcs": int(t.get("entry_tcs") or 0),
                },
            )
            if mem.log_outcome(outcome):
                logged += 1
            else:
                skipped += 1
        except Exception:  # noqa: BLE001
            skipped += 1

    logger.info(
        "sim.mem0.logged trades=%d logged=%d skipped=%d",
        len(trades), logged, skipped,
    )

