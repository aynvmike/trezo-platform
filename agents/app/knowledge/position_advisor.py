"""Per-position agent recommendations (Mike 2026-07-28).

"I would like to start looking into getting the agents recommendations
in as well on what to change on certain trades or options."

For every open position the agents already know the numbers that matter
-- distance to stop and target, giveback from the peak, days held,
how crowded its risk basket is, and whether it even exists at the
broker. This turns those into ONE plain-English recommendation per
position, in Mike's language, with the reason attached.

Verdicts (deliberately few, so the list is scannable):
  BANK      -- meaningful profit is on the table and fading; take it
  TRIM      -- winner worth keeping, but too big or too crowded
  HOLD      -- thesis intact, protection in place, nothing to do
  TIGHTEN   -- green but under-protected; move the stop up
  CUT       -- thesis broken or dead money; free the capital
  WATCH     -- close to a decision point, no action yet

Nothing here executes. It is advice for Mike and for the UI; the
monitor's own rules still do the acting.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _days_held(entry_at) -> float:
    try:
        t = datetime.fromisoformat(str(entry_at).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds() / 86400.0
    except Exception:  # noqa: BLE001
        return 0.0


def advise(pos: dict, price: float | None = None,
           crowd_read: dict | None = None,
           at_broker: bool | None = None) -> dict:
    """One recommendation for one position. Never raises."""
    tk = str(pos.get("ticker") or "?").upper()
    side = str(pos.get("side") or "long").lower()
    entry = _f(pos.get("entry_price"))
    qty = _f(pos.get("quantity"))
    stop = _f(pos.get("stop_price")) or None
    target = _f(pos.get("target_price")) or None
    peak = _f(pos.get("peak_price")) or None
    cur = _f(price) if price else _f(pos.get("current_price"))
    held = _days_held(pos.get("entry_at"))
    lane = str(pos.get("asset_type") or "stock").lower()

    out = {"ticker": tk, "lane": lane, "verdict": "HOLD", "why": "",
           "action": "", "days_held": round(held, 1),
           "at_broker": at_broker}
    if entry <= 0 or cur <= 0:
        out["verdict"] = "WATCH"
        out["why"] = "No live price to judge against right now."
        return out

    gain_usd = (cur - entry) * qty if side == "long" else (entry - cur) * qty
    gain_pct = ((cur - entry) / entry) if side == "long" else ((entry - cur) / entry)
    out["unrealized_usd"] = round(gain_usd, 2)
    out["unrealized_pct"] = round(gain_pct * 100, 2)

    # How much of the best gain is being handed back?
    giveback = 0.0
    if peak and peak > entry and side == "long":
        pk_gain = peak - entry
        if pk_gain > 0:
            giveback = max(0.0, (peak - cur) / pk_gain)
    out["giveback_pct"] = round(giveback * 100, 1)

    # Room left to the target / cushion above the stop.
    to_target = ((target - cur) / cur) if (target and side == "long") else None
    stop_room = ((cur - stop) / cur) if (stop and side == "long") else None
    out["to_target_pct"] = round(to_target * 100, 2) if to_target is not None else None
    out["stop_room_pct"] = round(stop_room * 100, 2) if stop_room is not None else None

    crowded = False
    crowd_n = 0
    if crowd_read:
        try:
            from app.data.portfolio_risk import basket_of
            b = basket_of(tk, lane, str(pos.get("strategy") or ""))
            crowd_n = int((crowd_read.get("baskets") or {}).get(b, 0))
            crowded = crowd_n >= 6
        except Exception:  # noqa: BLE001
            pass

    # --- the decision ladder, most urgent first -------------------
    if gain_pct > 0.02 and giveback >= 0.35:
        out["verdict"] = "BANK"
        out["why"] = (f"Up {gain_pct*100:.1f}% but already {giveback*100:.0f}% "
                      f"off its best. The profit is walking away.")
        out["action"] = "Take the gain now rather than watch the rest of it go."
    elif stop is not None and side == "long" and stop < entry and gain_pct > 0.03:
        out["verdict"] = "TIGHTEN"
        out["why"] = (f"Up {gain_pct*100:.1f}% but the stop is still BELOW "
                      f"entry — a reversal would turn a winner into a loser.")
        out["action"] = "Raise the stop to at least break-even and lock the trade green."
    elif gain_pct > 0.02 and crowded:
        out["verdict"] = "TRIM"
        out["why"] = (f"Green {gain_pct*100:.1f}%, but this is one of {crowd_n} "
                      f"positions in the same risk basket — they move together.")
        out["action"] = "Take part of it off; keep the runner, cut the correlation."
    elif gain_pct < -0.06:
        out["verdict"] = "CUT"
        out["why"] = (f"Down {abs(gain_pct)*100:.1f}%. The entry thesis has not "
                      f"worked out.")
        out["action"] = "Free the capital for a setup that is working."
    elif held >= 4 and abs(gain_pct) < 0.01:
        out["verdict"] = "CUT"
        out["why"] = (f"Held {held:.0f} days and going nowhere "
                      f"({gain_pct*100:+.1f}%). Dead money still costs.")
        out["action"] = "Rotate it into an active setup."
    elif to_target is not None and to_target <= 0.01:
        out["verdict"] = "WATCH"
        out["why"] = f"Within {to_target*100:.1f}% of target — the exit is close."
        out["action"] = "Let the target do its job; no manual action needed."
    elif stop_room is not None and stop_room <= 0.01:
        out["verdict"] = "WATCH"
        out["why"] = f"Only {stop_room*100:.1f}% above its stop — decision point."
        out["action"] = "The stop will act if it breaks; nothing to do by hand."
    else:
        out["verdict"] = "HOLD"
        out["why"] = (f"{gain_pct*100:+.1f}%, protection in place"
                      + (f", {to_target*100:.1f}% from target" if to_target is not None else "")
                      + ".")
        out["action"] = "Thesis intact — leave it alone."

    if at_broker is False:
        out["why"] += (" NOTE: modeled position — it does not appear in your "
                       "Alpaca screen; the venue does not list it.")
    return out


async def advise_book(client, prices: dict | None = None) -> list[dict]:
    """Recommendations for the whole open book, most urgent first."""
    import asyncio
    if client is None:
        return []

    def _q():
        return (client.table("paper_positions")
                .select("id, ticker, asset_type, strategy, side, entry_price,"
                        " quantity, stop_price, target_price, peak_price, entry_at")
                .eq("status", "open").limit(80).execute())
    try:
        rows = (await asyncio.to_thread(_q)).data or []
    except Exception:  # noqa: BLE001
        return []

    crowd = None
    try:
        from app.data.portfolio_risk import concentration_read
        crowd = concentration_read(rows)
    except Exception:  # noqa: BLE001
        pass

    broker_syms: set[str] = set()
    try:
        from app.brokers.alpaca import get_positions, alpaca_configured
        if alpaca_configured():
            for p in (await get_positions() or []):
                broker_syms.add(str(p.get("symbol", "")).upper().replace("/", ""))
    except Exception:  # noqa: BLE001
        pass

    prices = prices or {}
    out = []
    for r in rows:
        tk = str(r.get("ticker") or "").upper()
        px = prices.get(tk)
        if px is None:
            try:
                from app.data.candles import fetch_candles_for
                c = await fetch_candles_for(tk, str(r.get("asset_type") or "stock"))
                px = float(c[-1].close) if c else None
            except Exception:  # noqa: BLE001
                px = None
        at_b = (tk in broker_syms or (tk + "USD") in broker_syms) if broker_syms else None
        a = advise(r, price=px, crowd_read=crowd, at_broker=at_b)
        a["position_id"] = r.get("id")
        out.append(a)
    order = {"BANK": 0, "TIGHTEN": 1, "CUT": 2, "TRIM": 3, "WATCH": 4, "HOLD": 5}
    out.sort(key=lambda a: (order.get(a["verdict"], 9),
                            -abs(_f(a.get("unrealized_usd")))))
    return out
