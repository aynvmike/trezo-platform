"""Counterfactual rule replay -- what a closed trade WOULD have returned.

Mike 2026-08-05, after we found that the crypto scalp lane exits the
moment a gain clears round-trip cost (+0.63%) while its stop sits at
-2.5% to -4.5%:

    "we can not use the banked outcomes, but the probability of what
     the trade could have been if the rule was followed for that trade
     beyond what was closed... we was running on trades that was
     running faulty code and should look at the full 30 day data."

He is right that the banked ledger cannot answer this. Those trades were
closed by a rule he never intended, so their P&L measures the bug, not
the strategy. The only honest way to compare is to take each trade's
REAL entry and REAL subsequent price path and re-run it under each
candidate rule.

WHAT THIS IS NOT
----------------
This is not a promise about the future. It replays trades that were
actually opened, so it inherits whatever entry selection was in force --
it says nothing about trades the scanner never took. It is a controlled
comparison of EXIT rules holding entries fixed, which is exactly the
question on the table and nothing more.

HONESTY RULES BAKED IN
----------------------
1. INTRABAR AMBIGUITY. Within one candle we know the high and the low
   but not their order. When a bar could have hit both the stop and the
   profit exit, the outcome is genuinely unknowable at this resolution.
   Those trades are resolved PESSIMISTICALLY (stop first) and counted
   separately, so the headline can never flatter a rule by assuming the
   lucky ordering.
2. COSTS ALWAYS CHARGED. Every simulated exit pays the same round-trip
   fee + slippage the live engine models, and a laddered exit pays them
   on every rung. A rule that trades more is not allowed to look cheap.
3. SELF-VALIDATION. The `as_run` variant replays the rule that was
   ACTUALLY live. Its simulated P&L is compared against the real banked
   P&L; if they disagree badly the replay is reporting fiction and says
   so instead of quietly publishing numbers.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# Cost model -- mirrors app/paper/engine.py so the replay cannot
# accidentally be cheaper than reality.
try:
    from app.paper.engine import (
        CRYPTO_COMMISSION_BPS as _FEE_BPS,
        SLIPPAGE_BPS as _SLIP_BPS,
    )
except Exception:  # noqa: BLE001
    _FEE_BPS, _SLIP_BPS = 26.0, 5.0

ROUND_TRIP = 2.0 * (float(_FEE_BPS) + float(_SLIP_BPS)) / 10_000.0   # 0.0062
NET_EDGE_FLOOR = ROUND_TRIP + 0.0001                                  # 0.0063

# Ladder rungs: (fraction of position, gain at which it is sold).
# Mike 2026-08-05 asked for step profit taking; these mirror the options
# desk's staged harvest, scaled to a 5% crypto target.
LADDER = ((1 / 3, 0.015), (1 / 3, 0.030))   # remainder rides to target/trail
TIME_STOP_MINUTES = 90   # the live _decide_time_stop max_hold_90min
# The live trail (runtime/capabilities.trailing_profit_stop) does not
# engage until min_gain = 3%. An earlier draft armed it at +0.63% and a
# self-test caught the consequence: on a slow winner a 30% giveback of a
# 0.9% peak is a razor-thin band, so it "trailed out" at +0.01%. Model
# what the engine actually does.
TRAIL_MIN_GAIN = 0.03
TRAIL_GIVEBACK = 0.30    # give back at most 30% of peak gain, matching
                         # the crypto trail doctrine already in the engine


def _supabase():
    try:
        from app.runtime.settings import _supabase as _sb
        return _sb()
    except Exception:  # noqa: BLE001
        return None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def _gain(side: str, entry: float, price: float) -> float:
    """Unrealised gain as a fraction, sign-corrected for shorts."""
    if entry <= 0:
        return 0.0
    return ((price - entry) / entry) if side == "long" else ((entry - price) / entry)


def _price_at(side: str, entry: float, gain: float) -> float:
    return entry * (1 + gain) if side == "long" else entry * (1 - gain)


def _net(gross_gain: float, legs: int = 1) -> float:
    """Gain after costs. `legs` > 1 for laddered exits, which pay the
    exit side of the cost more than once."""
    exit_side = (float(_FEE_BPS) + float(_SLIP_BPS)) / 10_000.0
    entry_side = exit_side
    return gross_gain - entry_side - (exit_side * legs)


def _simulate(side: str, entry: float, stop_pct: float, target_pct: float,
              bars: list, variant: str,
              interval_minutes: int = 60) -> dict[str, Any]:
    """Walk the price path bar by bar under one exit rule.

    Returns {gain, exit_reason, bars_held, ambiguous}. `gain` is NET of
    costs. `ambiguous` marks trades whose outcome depended on intrabar
    ordering we cannot observe.

    Two subtleties that a first draft got wrong, both caught by the
    self-tests and both of which flattered the fancier rules:

    * The trailing stop must be measured against the peak established in
      PRIOR bars. Using the current bar's own high lets any bar with a
      range trigger its own trail, so a trade that ran to +6% "exited"
      at +0.08% on the first bar that ticked up.
    * Ladder rungs must NOT be credited inside a bar that also touched
      the stop. Filling them there quietly assumes the rungs came first,
      which is precisely the lucky ordering this replay refuses to
      assume anywhere else.
    """
    ambiguous = False
    peak = 0.0            # best gain seen in bars STRICTLY BEFORE this one
    remaining = 1.0
    banked = 0.0
    legs = 0
    rungs = list(LADDER) if variant == "step_ladder" else []
    # A 90-minute stop is only ~1-2 bars at hourly resolution. Run the
    # replay with interval_minutes=15 to judge it fairly; the report
    # states the resolution so this limit is never hidden.
    time_stop_bars = (max(1, round(TIME_STOP_MINUTES / max(interval_minutes, 1)))
                      if variant == "trail_plus_timestop" else None)

    for i, b in enumerate(bars):
        hi, lo = float(b.high), float(b.low)
        g_best = _gain(side, entry, hi if side == "long" else lo)
        g_worst = _gain(side, entry, lo if side == "long" else hi)

        # Mike's stated priority (2026-08-05): the 30% giveback trail is
        # the FIRST exit; the +0.63% net-edge level is LAST and exists to
        # PROTECT, not to take a win. Modelled as two stages:
        #   at +0.63%  -> the stop ratchets up to breakeven (protection)
        #   at +3.00%  -> the 30% giveback trail takes over (the exit)
        _staged = variant in ("floor_then_trail", "trail_plus_timestop")
        eff_stop = stop_pct
        if _staged and peak >= NET_EDGE_FLOOR:
            eff_stop = 0.0          # breakeven: it can no longer lose
        stop_hit = g_worst <= -eff_stop

        exit_at = NET_EDGE_FLOOR if variant == "as_run" else target_pct
        profit_hit = g_best >= exit_at

        # Trail is judged on the PRIOR peak, then the peak is updated below.
        trail_level = None
        trail_hit = False
        if _staged and peak >= TRAIL_MIN_GAIN:
            trail_level = peak * (1 - TRAIL_GIVEBACK)
            trail_hit = g_worst <= trail_level

        rung_reachable = bool(rungs) and g_best >= rungs[0][1]

        # ---- the stop and a profitable exit in the SAME bar ----
        if stop_hit and (profit_hit or trail_hit or rung_reachable):
            banked += remaining * -eff_stop        # no rung credit: pessimistic
            return {"gain": _net(banked, max(legs, 1)),
                    "exit_reason": "stop(ambiguous)",
                    "bars_held": i + 1, "ambiguous": True}
        if stop_hit:
            banked += remaining * -eff_stop
            return {"gain": _net(banked, max(legs, 1)),
                    "exit_reason": "breakeven_floor" if eff_stop == 0.0 else "stop",
                    "bars_held": i + 1, "ambiguous": ambiguous}

        # ---- trail strikes before any further upside is credited ----
        if trail_hit and trail_level is not None:
            banked += remaining * trail_level
            return {"gain": _net(banked, legs + 1), "exit_reason": "trail",
                    "bars_held": i + 1, "ambiguous": ambiguous}

        # ---- ladder rungs fill on the way up ----
        if variant == "step_ladder":
            while rungs and g_best >= rungs[0][1]:
                frac, lvl = rungs.pop(0)
                banked += frac * lvl
                remaining -= frac
                legs += 1

        if profit_hit:
            banked += remaining * exit_at
            return {"gain": _net(banked, legs + 1),
                    "exit_reason": "target" if exit_at == target_pct
                                   else "net_edge_floor",
                    "bars_held": i + 1, "ambiguous": ambiguous}

        if time_stop_bars is not None and (i + 1) >= time_stop_bars:
            banked += remaining * _gain(side, entry, float(b.close))
            return {"gain": _net(banked, legs + 1), "exit_reason": "time_stop",
                    "bars_held": i + 1, "ambiguous": ambiguous}

        peak = max(peak, g_best)

    if bars:
        banked += remaining * _gain(side, entry, float(bars[-1].close))
    return {"gain": _net(banked, legs + 1), "exit_reason": "unresolved",
            "bars_held": len(bars), "ambiguous": ambiguous}


VARIANTS = ("as_run", "target_only", "floor_then_trail", "step_ladder",
            "trail_plus_timestop")


async def replay(user_id: str, days: int = 30, interval_minutes: int = 60,
                 max_rows: int = 300) -> dict[str, Any]:
    """Replay every closed crypto trade in the window under each rule."""
    client = _supabase()
    if not client:
        return {"ok": False, "error": "Supabase not configured"}

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    def _q():
        return (client.table("trade_outcomes")
                .select("*")
                .eq("user_id", user_id)
                .gte("closed_at", since)
                .order("closed_at", desc=True)
                .limit(max_rows)
                .execute())

    try:
        res = await asyncio.to_thread(_q)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"query failed: {str(e)[:160]}"}

    rows = res.data or []
    from app.data.candles import fetch_kraken_ohlc
    try:
        from app.strategies.crypto import COIN_PARAMS as CRYPTO_PARAMS
    except ImportError:      # older name
        from app.strategies.crypto import CRYPTO_PARAMS
    try:
        from app.strategies.crypto import CRYPTO_WATCHLIST as _CW
        _CRYPTO_UNIVERSE = set(_CW)
    except Exception:  # noqa: BLE001
        _CRYPTO_UNIVERSE = set()

    trades: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}

    for r in rows:
        strat = str(r.get("strategy") or "")
        tk = str(r.get("ticker") or "").upper()
        # Crypto detection must not rely on the strategy string alone --
        # the live logs carry strategy="unknown" on most of these rows,
        # so a strategy-only filter silently discarded every trade and
        # produced an empty report. Accept the row if ANY signal says
        # crypto: the strategy text, the asset_type column, or the
        # ticker being in the crypto universe we actually trade.
        _at = str(r.get("asset_type") or "").lower()
        _known = tk in CRYPTO_PARAMS or tk in _CRYPTO_UNIVERSE
        if not ("crypto" in strat.lower() or _at == "crypto" or _known):
            skipped["not_crypto"] = skipped.get("not_crypto", 0) + 1
            continue
        side = str(r.get("side") or "long").lower()
        entry = float(r.get("entry_price") or 0)
        qty = float(r.get("quantity") or 0)
        opened = _parse_iso(r.get("opened_at"))
        if entry <= 0 or qty <= 0 or not opened:
            skipped["bad_row"] = skipped.get("bad_row", 0) + 1
            continue

        params = CRYPTO_PARAMS.get(tk) or {}
        stop_pct = float(params.get("stop_pct") or 0.03)
        target_pct = float(params.get("target_pct") or 0.06)

        try:
            candles = await fetch_kraken_ohlc(tk, interval_minutes=interval_minutes)
        except Exception:  # noqa: BLE001
            candles = []
        stamped = [c for c in candles if getattr(c, "timestamp", None)]
        if not stamped:
            skipped["no_price_path"] = skipped.get("no_price_path", 0) + 1
            continue
        # The window MUST reach back to the entry. Kraken returns ~720
        # bars, so at 60 minutes that is 30 days -- a trade older than
        # the window would otherwise be replayed from the middle of its
        # own life and silently report nonsense.
        earliest = min(_as_dt(c.timestamp) for c in stamped)
        if earliest > opened + timedelta(minutes=interval_minutes):
            skipped["entry_predates_candle_window"] = \
                skipped.get("entry_predates_candle_window", 0) + 1
            continue
        fwd = [c for c in stamped if _as_dt(c.timestamp) >= opened]
        if len(fwd) < 3:
            skipped["no_price_path"] = skipped.get("no_price_path", 0) + 1
            continue

        # ---- what the price did AFTER our agent actually sold --------
        # Mike 2026-08-05: "make sure it is looking at the after exit of
        # our agent... it was supposed to protect the money." The whole
        # question is what the trade went on to do once the +0.63% rule
        # closed it, so that move is measured explicitly rather than
        # being buried inside a variant's P&L.
        closed = _parse_iso(r.get("closed_at"))
        real_exit = r.get("exit_price")
        post = {"measured": False}
        if closed and real_exit:
            after = [c for c in fwd if _as_dt(c.timestamp) > closed]
            try:
                rx = float(real_exit)
            except (TypeError, ValueError):
                rx = 0.0
            if after and rx > 0:
                best = max((_gain(side, rx, float(c.high if side == "long"
                                                  else c.low)) for c in after),
                           default=0.0)
                worst = min((_gain(side, rx, float(c.low if side == "long"
                                                   else c.high)) for c in after),
                            default=0.0)
                post = {"measured": True, "bars_after": len(after),
                        "best_move_pct": round(best * 100, 3),
                        "worst_move_pct": round(worst * 100, 3),
                        "left_on_table_usd": round(best * rx * qty, 2),
                        "dodged_usd": round(abs(worst) * rx * qty, 2)}

        real_pnl = r.get("realized_pnl_usd")
        row = {"ticker": tk, "strategy": strat, "side": side, "entry": entry,
               "qty": qty, "notional": entry * qty,
               "opened_at": str(r.get("opened_at")),
               "closed_at": str(r.get("closed_at") or ""),
               "stop_pct": stop_pct, "target_pct": target_pct,
               "bars_available": len(fwd), "after_our_exit": post,
               "real_pnl": (float(real_pnl) if real_pnl is not None else None)}
        for v in VARIANTS:
            sim = _simulate(side, entry, stop_pct, target_pct, fwd, v,
                            interval_minutes=interval_minutes)
            row[v] = {"gain_pct": round(sim["gain"] * 100, 3),
                      "pnl_usd": round(sim["gain"] * entry * qty, 2),
                      "exit_reason": sim["exit_reason"],
                      "bars_held": sim["bars_held"],
                      "ambiguous": sim["ambiguous"]}
        trades.append(row)

    return {"ok": True, "days": days, "interval_minutes": interval_minutes,
            "trades": trades, "skipped": skipped,
            "summary": _summarise(trades)}


def _as_dt(ts: Any) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    d = _parse_iso(str(ts))
    return d or datetime.fromtimestamp(0, timezone.utc)


def _summarise(trades: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {"n": len(trades)}
    real = [t["real_pnl"] for t in trades if t.get("real_pnl") is not None]
    out["real_net_usd"] = round(sum(real), 2) if real else None
    out["real_n"] = len(real)
    for v in VARIANTS:
        vals = [t[v]["pnl_usd"] for t in trades]
        wins = [x for x in vals if x > 0]
        losses = [x for x in vals if x < 0]
        amb = len([t for t in trades if t[v]["ambiguous"]])
        gw, gl = sum(wins), abs(sum(losses))
        out[v] = {
            "net_usd": round(sum(vals), 2),
            "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(100 * len(wins) / len(vals), 1) if vals else 0.0,
            "avg_win": round(gw / len(wins), 2) if wins else 0.0,
            "avg_loss": round(gl / len(losses), 2) if losses else 0.0,
            "profit_factor": round(gw / gl, 2) if gl > 0 else None,
            "ambiguous_trades": amb,
        }
    # What happened AFTER our agent sold -- the heart of Mike's question.
    post = [t["after_our_exit"] for t in trades
            if (t.get("after_our_exit") or {}).get("measured")]
    if post:
        kept_running = [p for p in post if p["best_move_pct"] > 0.63]
        out["after_our_exit"] = {
            "trades_measured": len(post),
            "kept_running_past_our_exit": len(kept_running),
            "total_left_on_table_usd": round(sum(p["left_on_table_usd"] for p in post), 2),
            "total_dodged_usd": round(sum(p["dodged_usd"] for p in post), 2),
            "avg_best_move_after_exit_pct": round(
                sum(p["best_move_pct"] for p in post) / len(post), 2),
        }
    else:
        out["after_our_exit"] = {"trades_measured": 0}

    # Self-validation: does the replayed live rule match what was banked?
    if out["real_net_usd"] is not None and out["real_n"] >= 3:
        sim = out["as_run"]["net_usd"]
        realv = out["real_net_usd"]
        denom = max(abs(realv), 1.0)
        out["validation"] = {
            "replayed_as_run_usd": sim, "actually_banked_usd": realv,
            "abs_gap_usd": round(sim - realv, 2),
            "gap_pct_of_real": round(100 * (sim - realv) / denom, 1),
            "trustworthy": abs(sim - realv) <= max(0.5 * denom, 10.0),
        }
    else:
        out["validation"] = {"trustworthy": False,
                             "why": "too few banked P&L values to check against"}
    return out


def _doc_path() -> Path:
    base = os.getenv("TREZO_DOC_DIR") or r"C:\Trezo"
    return Path(base) / "TREZO_RULE_REPLAY.md"


_LABEL = {
    "as_run": "AS RUN (the rule that was live: exit at +0.63%)",
    "target_only": "TARGET ONLY (let it run to the designed target)",
    "floor_then_trail": "FLOOR THEN TRAIL (arm a trail at +0.63%, give back 30% of peak)",
    "step_ladder": "STEP LADDER (a third at +1.5%, a third at +3%, rest to target)",
    "trail_plus_timestop": "TRAIL + 90-MIN TIME STOP (Mike's order, with the clock ON)",
}


def render(result: dict[str, Any]) -> str:
    """Write the human-facing replay report. Returns the path."""
    s = result.get("summary") or {}
    L: list[str] = []
    L.append("# Trezo — Exit Rule Replay\n")
    L.append("_What the trades you actually opened WOULD have returned under "
             "each exit rule, using their real forward price paths. The banked "
             "ledger cannot answer this: those trades were closed by a rule "
             "that was not the intended one, so their P&L measures the bug._\n")
    L.append(f"_Window: last {result.get('days')} days · "
             f"{result.get('interval_minutes')}-minute candles · "
             f"{s.get('n', 0)} crypto trades replayed._\n")

    v = s.get("validation") or {}
    L.append("## Can this replay be trusted\n")
    if v.get("trustworthy"):
        L.append(f"**Yes, within tolerance.** Replaying the rule that was actually "
                 f"live reproduces ${v.get('replayed_as_run_usd')} against "
                 f"${v.get('actually_banked_usd')} truly banked "
                 f"(gap ${v.get('abs_gap_usd')}, {v.get('gap_pct_of_real')}%). "
                 f"The simulator is tracking reality, so the comparisons below "
                 f"are meaningful.\n")
    else:
        L.append(f"**Treat everything below as indicative only.** "
                 f"{v.get('why') or ''} "
                 f"Replaying the live rule gave ${v.get('replayed_as_run_usd')} "
                 f"against ${v.get('actually_banked_usd')} banked — too far apart "
                 f"to certify. Read the direction of the differences, not the "
                 f"absolute dollars.\n")

    L.append("## The comparison\n")
    L.append("| rule | net $ | W/L | win rate | avg win | avg loss | profit factor | unknowable ordering |")
    L.append("|---|---|---|---|---|---|---|---|")
    for key in VARIANTS:
        r = s.get(key) or {}
        pf = r.get("profit_factor")
        L.append(f"| {_LABEL[key]} | **{r.get('net_usd')}** | "
                 f"{r.get('wins')}/{r.get('losses')} | {r.get('win_rate_pct')}% | "
                 f"${r.get('avg_win')} | ${r.get('avg_loss')} | "
                 f"{pf if pf is not None else 'n/a'} | {r.get('ambiguous_trades')} |")
    L.append("")
    L.append("The last column counts trades where a single candle contained both "
             "the stop and the profit exit. At this resolution the order is "
             "genuinely unknowable, so those are all resolved as LOSSES. No rule "
             "is allowed to win by assuming lucky timing.\n")

    ae = s.get("after_our_exit") or {}
    L.append("## What happened AFTER our agent sold\n")
    if ae.get("trades_measured"):
        L.append(f"The +0.63% rule was meant to PROTECT the money, not to take "
                 f"the win. So the fair test is what each trade went on to do "
                 f"once we were already out.\n")
        L.append(f"- Trades where the price kept running in our favour after we "
                 f"sold: **{ae.get('kept_running_past_our_exit')} of "
                 f"{ae.get('trades_measured')}**")
        L.append(f"- Best further move, averaged: **{ae.get('avg_best_move_after_exit_pct')}%**")
        L.append(f"- Value of that unclaimed move: **${ae.get('total_left_on_table_usd')}**")
        L.append(f"- Value of the adverse moves we DID sidestep by selling early: "
                 f"**${ae.get('total_dodged_usd')}**\n")
        L.append("Read those last two together. The first is what exiting early "
                 "cost; the second is what it saved. Selling at +0.63% is only "
                 "the wrong rule if the money left behind exceeds the trouble "
                 "avoided — and that is a measurement, not an opinion.\n")
    else:
        L.append("_No trade had both a recorded exit price and candles after "
                 "its close, so this could not be measured. Usually means the "
                 "window is too short or exit prices were not stored._\n")

    L.append("## What it means\n")
    best = None
    for key in VARIANTS:
        r = s.get(key) or {}
        if r.get("net_usd") is None:
            continue
        if best is None or r["net_usd"] > (s.get(best) or {}).get("net_usd", -1e9):
            best = key
    if best:
        b, a = s.get(best) or {}, s.get("as_run") or {}
        delta = round((b.get("net_usd") or 0) - (a.get("net_usd") or 0), 2)
        L.append(f"On these {s.get('n', 0)} trades the strongest rule was "
                 f"**{_LABEL[best]}**, worth ${delta:+.2f} against the rule that "
                 f"was live.\n")
        if (b.get("win_rate_pct") or 0) < (a.get("win_rate_pct") or 0):
            L.append(f"Note the trade-off: its win rate is LOWER "
                     f"({b.get('win_rate_pct')}% vs {a.get('win_rate_pct')}%) "
                     f"while it makes more money. Exiting at +0.63% converts "
                     f"almost any green tick into a 'win', which flatters the "
                     f"scoreboard and starves the payoff. Expect the win rate to "
                     f"fall if this ships — that is the mechanism working, not a "
                     f"regression.\n")

    L.append("## Trade by trade\n")
    L.append("| opened | coin | strategy | notional | as-run | target | trail | ladder | moved after we sold |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for t in sorted(result.get("trades") or [], key=lambda x: x.get("opened_at") or ""):
        L.append(f"| {str(t.get('opened_at'))[:16]} | {t.get('ticker')} | "
                 f"{t.get('strategy')} | ${t.get('notional'):.0f} | "
                 f"{t['as_run']['pnl_usd']:+.2f} | {t['target_only']['pnl_usd']:+.2f} | "
                 f"{t['floor_then_trail']['pnl_usd']:+.2f} | "
                 f"{t['step_ladder']['pnl_usd']:+.2f} | "
                 + ((f"+{t['after_our_exit']['best_move_pct']}% / "
                     f"{t['after_our_exit']['worst_move_pct']}%")
                    if (t.get('after_our_exit') or {}).get('measured') else "n/a")
                 + " |")
    L.append("")
    sk = result.get("skipped") or {}
    if sk:
        L.append(f"_Skipped: {sk}. 'no_price_path' means Kraken had no candle "
                 f"history covering that entry — usually a coin that was rest-listed._\n")
    L.append("---\n")
    L.append("_This replays EXIT rules with entries held fixed. It says nothing "
             "about trades the scanner never took, and it is not a forecast. It "
             "is the narrowest honest answer to: given the trades we did open, "
             "which exit rule would have served them best._\n")

    doc = "\n".join(L)
    # Write atomically via a temp file. The first run left a ZERO BYTE
    # report on disk, which is the worst possible failure: it looks like
    # an answer. Write to .tmp, verify the byte count, then replace --
    # so the real file is either complete or untouched.
    p = _doc_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(doc, encoding="utf-8")
        if tmp.stat().st_size < 200:
            raise IOError(f"wrote only {tmp.stat().st_size} bytes")
        tmp.replace(p)
    except Exception as e:  # noqa: BLE001
        log.warning("rule_replay: could not write %s: %s", p, e)
        return f"WRITE FAILED ({e}) -- the report is in this response body"
    return str(p)
