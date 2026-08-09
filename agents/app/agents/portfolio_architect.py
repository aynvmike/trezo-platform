"""Portfolio Architect -- the agent that uses what the library taught us.

Built 2026-08-10 after Mike asked whether the agents are aware of the new
strategies, and whether an agent could "formulate more plans and strategies".

The honest finding behind it: of the six modules distilled from the books,
three had ZERO callers. optimal_f, hrp and structural_break were libraries
nobody could reach -- the agents owned the tools and could not pick them up.
This agent picks them up.

WHAT IT ASKS, DAILY
-------------------
Three questions nothing in Trezo currently answers:

  1. HOW MUCH should each lane bet?      (Vince, runtime/optimal_f)
  2. HOW should capital be SPLIT?        (de Prado ch.16, runtime/hrp)
  3. HAS THE MARKET CHANGED underneath?  (de Prado ch.17, runtime/structural_break)

WHY IT PROPOSES RATHER THAN INVENTS
-----------------------------------
Mike's instinct was an agent that formulates new strategies. Generating
strategies is easy; the hard part -- and the lesson of the whole library
exercise -- is knowing whether one is real. An agent that invents freely
would manufacture exactly the false discoveries chapter 11 warns about, and
it would do it faster than anyone could check.

So this one is deliberately narrow. It reasons only about lanes that already
exist, using measurements already verified against published examples, and it
writes proposals rather than changes. Its job is to make the platform's own
evidence legible -- which is the thing that was missing, not ideas.

THE ORDERING IT ENFORCES
------------------------
Expectancy first, then sizing, then allocation. A lane with no edge is not
given a bet size, and is excluded from the allocation entirely -- because HRP
allocates by risk and would happily hand everything to a lane that does
nothing (it gave forex 99.8% on Trezo's real data, for earning $3.97 in three
weeks). That ordering is the guard against the method's own blind spot.

NEVER CHANGES A RULE. Writes to the activity log and the proposals document.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .base import Agent, AgentMessage

# One pass a day is the right cadence: these are structural questions, and
# re-asking them hourly would invite acting on noise.
TICK_SECONDS = 6 * 3600
MIN_TRADES_FOR_SIZING = 8       # below this, any f is arithmetic on noise


def _log_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", ".."))
    return os.getenv("TREZO_ACTIVITY_LOG_DIR") or os.path.join(
        os.path.dirname(root), "logs")


_PNL = re.compile(r"(?:pnl|realized)\s+\$?(-?\+?[\d.]+)")
_CLOSE_EVENTS = {"fill_close_modeled", "reconcile_close"}


def _read_closes(days: int = 30) -> dict[str, list[float]]:
    """Closed-trade P&L by lane, from the activity log.

    Filtered on the close EVENTS and the declared asset_type, deliberately.
    A looser regex once matched the word "realized" inside a variance-premium
    note and invented a $15,171 lane out of a volatility percentage.
    """
    out: dict[str, list[float]] = defaultdict(list)
    for i in range(days):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        path = os.path.join(_log_dir(), f"activity-{day}.jsonl")
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    if '"fill_close_modeled"' not in ln and '"reconcile_close"' not in ln:
                        continue
                    try:
                        r = json.loads(ln.strip())
                    except Exception:  # noqa: BLE001
                        continue
                    if r.get("event") not in _CLOSE_EVENTS:
                        continue
                    at = str(r.get("asset_type") or "").lower()
                    if at not in ("crypto", "forex", "stock", "option"):
                        continue
                    m = _PNL.search(r.get("reason") or "")
                    if m:
                        try:
                            out[at].append(float(m.group(1).replace("+", "")))
                        except ValueError:
                            continue
        except Exception:  # noqa: BLE001
            continue
    return dict(out)


class PortfolioArchitectAgent(Agent):
    """Daily structural review: edge, size, allocation, regime."""

    name = "portfolio_architect"
    tick_interval_seconds = TICK_SECONDS

    async def tick(self) -> list[AgentMessage]:
        try:
            return await self._review()
        except Exception as e:  # noqa: BLE001
            return [AgentMessage(agent=self.name, kind="error",
                                 payload={"error": str(e)[:200]})]

    async def _review(self) -> list[AgentMessage]:
        from app.agents.activity_log import record as _rec
        from app.runtime.r_multiples import expectancy
        from app.runtime.optimal_f import optimal_f, simulate_drawdown
        from app.runtime.significance import bootstrap_mean_test

        lanes = _read_closes(30)
        if not lanes:
            return []

        out: list[AgentMessage] = []
        qualified: dict[str, list[float]] = {}
        findings: dict[str, Any] = {}

        # ---- STEP 1: does this lane have an edge at all? ----------------
        for lane, pnls in lanes.items():
            if len(pnls) < 3:
                continue
            bt = bootstrap_mean_test(pnls, iterations=3000)
            mean = sum(pnls) / len(pnls)
            has_edge = bool(mean > 0 and bt and bt.get("conclusive"))
            findings[lane] = {"trades": len(pnls), "net": round(sum(pnls), 2),
                              "mean_per_trade": round(mean, 3),
                              "conclusive": bool(bt and bt.get("conclusive")),
                              "has_edge": has_edge}
            if has_edge:
                qualified[lane] = pnls

            # ---- STEP 2: what size does the evidence support? -----------
            # GATED ON EDGE, and it must be. A first version computed a bet
            # size for any lane with enough trades, and produced f = 0.554
            # with an 80% drawdown for a forex lane whose edge was
            # inconclusive on 18 trades worth $4.97. An optimal fraction
            # derived from a sample that cannot distinguish profit from
            # noise is not a recommendation, it is a dare -- and the
            # docstring above already promised not to do this.
            if not has_edge:
                findings[lane]["optimal_f"] = None
                findings[lane]["sizing_note"] = (
                    "no bet size computed: this lane has not shown a "
                    "measurable edge, and sizing a coin-flip is how a small "
                    "sample becomes a large loss")
                continue
            if len(pnls) >= MIN_TRADES_FOR_SIZING:
                f = optimal_f(pnls)
                if f and f.get("geometric_mean", 0) > 1.0:
                    dd = simulate_drawdown(pnls, f["optimal_f"])
                    findings[lane]["optimal_f"] = f["optimal_f"]
                    findings[lane]["drawdown_at_f"] = dd["max_drawdown_pct"] if dd else None
                    _rec("architect_sizing", lane.upper(), strategy=lane,
                         reason=(f"optimal f {f['optimal_f']:.3f} on {len(pnls)} "
                                 f"trades, geometric mean {f['geometric_mean']:.5f}, "
                                 f"drawdown at that size "
                                 f"{dd['max_drawdown_pct'] if dd else '?'}% -- "
                                 f"growth stops entirely at twice this fraction"),
                         extra={"observe_only": True, **f})
                else:
                    findings[lane]["optimal_f"] = None
                    _rec("architect_sizing", lane.upper(), strategy=lane,
                         reason=("no fraction makes this lane compound upward -- "
                                 "bet sizing cannot rescue a negative edge, only "
                                 "change how fast it arrives"),
                         extra={"observe_only": True, "trades": len(pnls)})

        # ---- STEP 3: split capital, but only among lanes that earned it --
        if len(qualified) >= 2:
            from app.runtime.hrp import hrp_weights
            n = min(len(v) for v in qualified.values())
            series = {k: v[-n:] for k, v in qualified.items()}
            w = hrp_weights(series)
            if w:
                findings["allocation"] = w["weights"]
                _rec("architect_allocation", "PORTFOLIO",
                     reason=(f"across {w['n_assets']} lanes with a measured edge: "
                             + ", ".join(f"{k} {v*100:.0f}%"
                                         for k, v in w["weights"].items())
                             + f"; equal weighting would be "
                               f"{w['equal_weight']*100:.0f}% each -- "
                             + w["note"]),
                     extra={"observe_only": True, **w})
        else:
            _rec("architect_allocation", "PORTFOLIO",
                 reason=(f"only {len(qualified)} lane(s) show a measurable edge, "
                         f"so there is nothing to allocate between yet. Risk "
                         f"parity would hand everything to the quietest lane "
                         f"regardless of whether it earns -- expectancy has to "
                         f"qualify a lane before allocation can size it"),
                 extra={"observe_only": True,
                        "qualified": sorted(qualified),
                        "examined": sorted(lanes)})

        # ---- STEP 4: did the market move underneath a lane? --------------
        await self._check_regimes(findings)

        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={"event": "architect_review", "lanes": findings}))
        return out

    async def _check_regimes(self, findings: dict) -> None:
        """Structural-break test on the names Trezo actually trades."""
        from app.agents.activity_log import record as _rec
        from app.runtime.structural_break import sup_cusum, regime_note
        try:
            from app.data.candles import fetch_crypto_ohlc
            from app.strategies.crypto import CRYPTO_WATCHLIST
        except Exception:  # noqa: BLE001
            return
        for sym in list(CRYPTO_WATCHLIST)[:6]:
            try:
                candles = await fetch_crypto_ohlc(sym, days=90)
                if not candles or len(candles) < 30:
                    continue
                res = sup_cusum([float(c.close) for c in candles])
                if res and res["break_detected"]:
                    _rec("architect_regime", sym, strategy="crypto",
                         reason=regime_note(res, "the crypto lanes")[:280],
                         extra={"observe_only": True, **res})
            except Exception:  # noqa: BLE001
                continue
