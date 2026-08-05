"""Trade geometry -- the shape of a trade's risk and reward, made visible.

Mike 2026-08-05, after we traced four identical stop-outs to a rescale
nobody could see: "we can make sure it does not happen again... I also
like how the geometry sounds, would it be possible to make the geometry
a visible thing?"

GEOMETRY is two numbers: how far the trade can go against you before the
stop, and how far it can run in your favour before the target. Their
ratio -- reward-to-risk -- decides how often you must be right to make
money. At 1:2 you can be wrong most of the time and still profit. At
1:1 you need better than half your trades to win. Below 1:1 the arithmetic
is against you regardless of how good the entry was.

The bug this module exists to prevent: the crypto SCALP branch rescaled
the stop by 0.6 and the target by 0.5. Both are reasonable-looking
numbers. Because they DIFFER, a designed 1:2 silently became 1:1.67 --
and the only trace was four stop-outs clustering at -1.9% weeks later.
Nothing compared the ratio before against the ratio after, so nothing
noticed.

Rescaling geometry is legitimate; a scalp SHOULD trade tighter than a
swing. Silently changing the RATIO while rescaling is the error. Scale
both legs by the same factor and the ratio survives:

    0.6 / 0.6  ->  1.8% and 3.6%   still 1:2
    0.5 / 0.5  ->  1.5% and 3.0%   still 1:2
    0.6 / 0.5  ->  1.8% and 3.0%   now    1:1.67   <- the leak
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Below this, the arithmetic needs an implausible win rate to profit.
MIN_HEALTHY_RR = 1.5
# Ratio drift smaller than this is rounding, not a change worth reporting.
_RR_NOISE = 0.02


def reward_risk(stop_pct: Optional[float],
                target_pct: Optional[float]) -> Optional[float]:
    """Reward-to-risk as a single number. 2.0 means 'risk 1 to make 2'."""
    try:
        s, t = float(stop_pct or 0), float(target_pct or 0)
    except (TypeError, ValueError):
        return None
    if s <= 0 or t <= 0:
        return None
    return t / s


def describe(stop_pct: Optional[float], target_pct: Optional[float]) -> str:
    """One plain-English line. Written for a human, not a log parser."""
    rr = reward_risk(stop_pct, target_pct)
    if rr is None:
        return "geometry unknown"
    s, t = float(stop_pct) * 100, float(target_pct) * 100
    verdict = ("healthy" if rr >= 2.0
               else "workable" if rr >= MIN_HEALTHY_RR
               else "thin" if rr >= 1.0
               else "UPSIDE DOWN")
    return (f"risk {s:.1f}% to make {t:.1f}% — 1:{rr:.2f} ({verdict})")


def needed_win_rate(stop_pct: Optional[float],
                    target_pct: Optional[float]) -> Optional[float]:
    """The break-even win rate this geometry demands, as a percentage.

    The number that makes a ratio concrete: at 1:2 you need to be right
    33% of the time; at 1:0.35 -- what the scalp lane was actually
    realising -- you need 74%.
    """
    rr = reward_risk(stop_pct, target_pct)
    if rr is None or rr <= 0:
        return None
    return 100.0 / (1.0 + rr)


def check_rescale(ticker: str, strategy: str,
                  base_stop: Optional[float], base_target: Optional[float],
                  new_stop: Optional[float], new_target: Optional[float],
                  note: str = "") -> Optional[dict]:
    """Compare the geometry before and after a rescale, and SAY SO when
    the ratio moved. Returns the finding, or None when the ratio held.

    Never raises and never blocks a trade -- a reporting guard that can
    stop a trade is a new failure mode. It exists so a silent change
    becomes a loud one.
    """
    try:
        before = reward_risk(base_stop, base_target)
        after = reward_risk(new_stop, new_target)
        if before is None or after is None:
            return None
        if abs(after - before) <= _RR_NOISE:
            return None
        worse = after < before
        finding = {
            "ticker": ticker, "strategy": strategy,
            "rr_before": round(before, 3), "rr_after": round(after, 3),
            "stop_before": base_stop, "stop_after": new_stop,
            "target_before": base_target, "target_after": new_target,
            "degraded": worse,
            "needed_win_rate_before": round(needed_win_rate(base_stop, base_target) or 0, 1),
            "needed_win_rate_after": round(needed_win_rate(new_stop, new_target) or 0, 1),
        }
        try:
            from app.agents.activity_log import record as _arec
            direction = "DEGRADED" if worse else "improved"
            _arec("geometry_rescale", ticker, strategy=strategy,
                  reason=(f"reward:risk {direction} 1:{before:.2f} -> 1:{after:.2f} "
                          f"({describe(base_stop, base_target)} became "
                          f"{describe(new_stop, new_target)}); break-even win rate "
                          f"moves {finding['needed_win_rate_before']}% -> "
                          f"{finding['needed_win_rate_after']}%"
                          + (f"; {note}" if note else "")),
                  extra=finding)
        except Exception:  # noqa: BLE001
            pass
        return finding
    except Exception:  # noqa: BLE001
        return None
