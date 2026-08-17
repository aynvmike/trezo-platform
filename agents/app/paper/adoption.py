"""Adopt broker positions the ledger has lost sight of.

WHY (2026-08-17)
Position Monitor asked one account which symbols it held and then judged
every book against that answer, so nine real positions in the 75k book
and eight in the 25k were closed in the ledger as phantoms while Alpaca
went on holding them. The scoping bug is fixed in runtime/book_scope.py.
This module cleans up after it -- and, more usefully, keeps cleaning up
after anything else that can separate broker truth from our record:
a crashed process mid-fill, a manual trade placed in Alpaca's own UI,
a restore from an older snapshot.

The principle, which is not new here: THE BROKER IS THE TRUTH about what
is held. Our row is a claim about it. When the two disagree about
EXISTENCE, the broker wins and we write a row -- because a position we
do not have a row for is a position nothing is managing, and on a venue
with no native brackets (crypto) that means no stop at all.

WHAT IT WILL NOT DO
- It will not adopt into a book it cannot resolve and bind. Guessing the
  book is how a stranger's position lands in someone else's ledger.
- It will not adopt an asset class whose policy says adoptable=False.
- It will not invent a realized P&L. An adopted row starts from the
  broker's own average entry, so the unrealized number is true from the
  first tick and nothing fake enters the learning loop.
- It will not touch a position that already has an open row. Merging is
  record_external_position's job and it does the weighted average.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.runtime import book_scope
from app.runtime.asset_policy import ALIASES, policy_for


def _supabase():
    from app.config import get_settings
    s = get_settings()
    if not (s.supabase_url and s.supabase_service_role_key):
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def _asset_type_of(broker_row: dict) -> str:
    """Alpaca's asset_class -> Trezo's asset_type, via the registry's
    alias table so a new spelling is one line in one place."""
    ac = str(broker_row.get("asset_class") or "").strip().lower()
    if ac in ALIASES:
        return ALIASES[ac]
    if ac in ("crypto", "stock", "option", "forex", "future", "bond", "fund"):
        return ac
    sym = str(broker_row.get("symbol") or "")
    if "/" in sym or sym.upper().endswith("USD"):
        return "crypto"
    if len(sym) >= 15 and any(c.isdigit() for c in sym):
        return "option"
    return "stock"


def _ledger_ticker(broker_row: dict, asset_type: str) -> str:
    """How Trezo stores this symbol. Coins are kept bare ('BTC'), which
    is why every membership check needs the variants helper."""
    sym = str(broker_row.get("symbol") or "").upper().strip()
    if asset_type == "crypto":
        if "/" in sym:
            return sym.split("/", 1)[0]
        if sym.endswith("USD") and len(sym) > 4:
            return sym[:-3]
    return sym


def _default_geometry(ticker: str, asset_type: str, side: str,
                      entry: float, price: float | None = None) -> tuple[float, float]:
    """A stop and target for a position we are meeting for the first
    time. Per-coin parameters where we have them, otherwise a plain
    percentage -- deliberately WIDE, because an adopted position's real
    entry may be days old and a tight stop would sell it on contact.

    THE TRAP (caught 2026-08-17 before this ever ran): these percentages
    are measured from ENTRY, and an adopted position's entry may be days
    old. A coin already up 20% would get a target at +8% -- i.e. BELOW
    the live price -- and the monitor's very next tick would read that
    as "target hit" and liquidate at market. Adopting a book would have
    become a mass sell of its winners.

    So both levels are clamped against the CURRENT price when we know
    it: the target is pushed above the market, and the stop is pulled
    below it. Adoption exists to put a position back under management.
    It must never, by itself, be a trading decision.
    """
    stop_pct, target_pct = 0.05, 0.10
    if asset_type == "crypto":
        try:
            from app.strategies.crypto import COIN_PARAMS
            p = COIN_PARAMS.get(ticker.upper())
            if p:
                stop_pct = float(p.get("stop_pct", stop_pct))
                target_pct = float(p.get("target_pct", target_pct))
        except Exception:  # noqa: BLE001
            pass
    elif asset_type == "stock":
        stop_pct, target_pct = 0.04, 0.08
    if side == "long":
        stop = entry * (1 - stop_pct)
        target = entry * (1 + target_pct)
        if price and price > 0:
            # Target must sit ABOVE the market, stop BELOW it, or the
            # act of adopting fires an exit on the next tick.
            target = max(target, price * (1 + target_pct))
            stop = min(stop, price * (1 - stop_pct))
        return (round(stop, 6), round(target, 6))
    stop = entry * (1 + stop_pct)
    target = entry * (1 - target_pct)
    if price and price > 0:
        target = min(target, price * (1 - target_pct))
        stop = max(stop, price * (1 + stop_pct))
    return (round(stop, 6), round(target, 6))


async def _last_price(ticker: str, asset_type: str) -> Optional[float]:
    """What the position is worth right now, or None. Best-effort: with
    no price we simply skip the clamp and keep entry-based levels, which
    is the pre-2026-08-17 behaviour."""
    # The broker position itself is the cheapest quote we have -- Alpaca
    # returns current_price on every position row -- but adoption also
    # runs for rows the caller did not pass, so fall back to candles.
    try:
        from app.data.candles import fetch_candles_for
        candles = await fetch_candles_for(
            ticker, asset_type if asset_type != "option" else "stock")
        if candles:
            return float(candles[-1].close)
    except Exception:  # noqa: BLE001
        pass
    return None


async def _inherit(client, user_id: str, ticker: str,
                   side: str) -> Optional[dict]:
    """If this book closed the same ticker on the same side in the last
    72 hours, the position at the broker is almost certainly that trade,
    wrongly closed. Take back its strategy, stop and target rather than
    filing it as a stranger with default geometry -- otherwise an
    adopted swing loses its time stop and rides forever (the 2026-06-12
    CSCO/SOFI lesson, in a new place)."""
    try:
        def _q():
            return (client.table("paper_positions")
                    .select("strategy, stop_price, target_price, side, "
                            "entry_at, status")
                    .eq("user_id", user_id).eq("ticker", ticker)
                    .neq("status", "open")
                    .order("entry_at", desc=True).limit(6).execute())
        rows = (await asyncio.to_thread(_q)).data or []
    except Exception:  # noqa: BLE001
        return None
    now = datetime.now(timezone.utc)
    strategy = stop = target = None
    for row in rows:
        if (row.get("side") or side) != side:
            continue
        ts = str(row.get("entry_at") or "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
        except Exception:  # noqa: BLE001
            dt = None
        if not dt or (now - dt) >= timedelta(hours=72):
            continue
        if strategy is None:
            cand = str(row.get("strategy") or "").strip()
            if cand and cand.lower() not in ("reconciled", "adopted"):
                strategy = row.get("strategy")
        if stop is None and row.get("stop_price"):
            stop = row.get("stop_price")
        if target is None and row.get("target_price"):
            target = row.get("target_price")
    if strategy is None and stop is None and target is None:
        return None
    return {"strategy": strategy, "stop_price": stop, "target_price": target}


async def adopt_for_book(user_id: str, *, dry_run: bool = False) -> dict:
    """Bring one book's ledger back in line with its broker. Returns a
    report; never raises."""
    out: dict[str, Any] = {"user_id": str(user_id), "adopted": [],
                           "skipped": [], "ok": True}
    client = _supabase()
    if client is None:
        return {**out, "ok": False, "error": "Supabase not configured"}

    # book_scope binds the book as part of answering, so this can never
    # be another account's position list.
    rows = await book_scope.positions(str(user_id), where="adoption")
    if rows is None:
        # "Could not check" must never be read as "the broker holds
        # nothing" -- that reading is the bug this module exists to undo.
        return {**out, "ok": False, "error": "broker read failed - no action"}
    if not rows:
        return out

    def _open():
        return (client.table("paper_positions")
                .select("id, ticker, asset_type, side, quantity")
                .eq("user_id", str(user_id)).eq("status", "open").execute())
    try:
        open_rows = (await asyncio.to_thread(_open)).data or []
    except Exception as e:  # noqa: BLE001
        return {**out, "ok": False, "error": f"ledger read failed: {e}"}

    have = {(str(r.get("ticker") or "").upper(),
             str(r.get("side") or "long")) for r in open_rows}

    from app.paper.engine import record_external_position

    for bp in rows:
        try:
            qty = float(bp.get("qty") or 0)
            entry = float(bp.get("avg_entry_price") or 0)
        except (TypeError, ValueError):
            continue
        if abs(qty) < 1e-9 or entry <= 0:
            continue
        at = _asset_type_of(bp)
        pol = policy_for(at)
        ticker = _ledger_ticker(bp, at)
        side = "long" if qty > 0 else "short"
        if not pol.adoptable:
            out["skipped"].append(
                {"ticker": ticker, "why": f"{pol.label} is not adoptable"})
            continue
        if (ticker, side) in have:
            continue

        # What is it worth right now? Both the defaults and anything we
        # inherit are checked against this, so adoption can never hand
        # the monitor a level that is already breached.
        price_now = None
        try:
            _cp = bp.get("current_price")
            price_now = float(_cp) if _cp not in (None, "") else None
        except (TypeError, ValueError):
            price_now = None
        if not price_now or price_now <= 0:
            price_now = await _last_price(ticker, at)

        inh = await _inherit(client, str(user_id), ticker, side) or {}
        stop = inh.get("stop_price")
        target = inh.get("target_price")
        if not stop or not target:
            d_stop, d_target = _default_geometry(
                ticker, at, side, entry, price_now)
            stop = stop or d_stop
            target = target or d_target

        # An INHERITED level can be stale too -- the row it came from was
        # closed, possibly days ago, and the market has moved since. Same
        # rule: adoption puts a position back under management, it does
        # not decide to trade it. If an inherited level is already
        # breached, fall back to the clamped default and say so.
        clamped = False
        if price_now and price_now > 0:
            try:
                _s, _t = float(stop), float(target)
                breached = ((side == "long" and (price_now >= _t or price_now <= _s))
                            or (side != "long" and (price_now <= _t or price_now >= _s)))
                if breached:
                    stop, target = _default_geometry(
                        ticker, at, side, entry, price_now)
                    clamped = True
            except (TypeError, ValueError):
                pass

        strategy = inh.get("strategy") or f"adopted_{at}"

        if dry_run:
            out["adopted"].append({
                "ticker": ticker, "asset_type": at, "side": side,
                "quantity": abs(qty), "entry_price": entry,
                "price_now": price_now,
                "stop_price": stop, "target_price": target,
                "strategy": strategy, "inherited": bool(inh),
                "clamped": clamped, "dry_run": True})
            continue

        try:
            fill = await record_external_position(
                user_id=str(user_id), ticker=ticker, asset_type=at,
                side=side, quantity=abs(qty), entry_price=entry,
                stop_price=float(stop), target_price=float(target),
                strategy=strategy, broker="alpaca", broker_order_id=None,
                source_payload={"adopted": True,
                                "adopted_at": datetime.now(timezone.utc).isoformat(),
                                "broker_asset_class": bp.get("asset_class"),
                                "inherited": bool(inh),
                                "geometry_clamped": clamped,
                                "price_at_adoption": price_now})
        except Exception as e:  # noqa: BLE001
            out["skipped"].append({"ticker": ticker, "why": f"insert failed: {e}"})
            continue
        if not getattr(fill, "ok", False):
            out["skipped"].append(
                {"ticker": ticker,
                 "why": f"insert failed: {getattr(fill, 'error', 'unknown')}"})
            continue

        out["adopted"].append({
            "ticker": ticker, "asset_type": at, "side": side,
            "quantity": abs(qty), "entry_price": entry,
            "price_now": price_now,
            "stop_price": stop, "target_price": target,
            "strategy": strategy, "inherited": bool(inh),
            "clamped": clamped})
        try:
            from app.agents.activity_log import record
            record("position_adopted", ticker,
                   strategy=strategy,
                   reason=(f"broker held {abs(qty):g} @ {entry:g} with no open "
                           f"row - adopted so stops, targets and the profit "
                           f"ladder can manage it again"
                           + (" (geometry inherited from the row that was "
                              "wrongly closed)" if inh and not clamped else
                              " (default geometry - no recent matching row)")
                           + (" [levels clamped around the live price: the "
                              "inherited ones were already breached, and "
                              "adopting must not fire an exit]"
                              if clamped else "")),
                   extra={"user_id": str(user_id), "asset_type": at,
                          "broker": "alpaca"})
        except Exception:  # noqa: BLE001
            pass
    return out


async def adopt_all_books(*, dry_run: bool = False) -> dict:
    """Every book we can resolve and bind. Safe to call from a tick."""
    from app.brokers.accounts import load_accounts
    reports = []
    for a in load_accounts():
        try:
            reports.append(await adopt_for_book(a.account_key, dry_run=dry_run))
        except Exception as e:  # noqa: BLE001
            reports.append({"user_id": a.account_key, "ok": False,
                            "error": str(e)[:200]})
    return {
        "ok": all(r.get("ok", False) for r in reports) if reports else True,
        "books": len(reports),
        "adopted": sum(len(r.get("adopted") or []) for r in reports),
        "skipped": sum(len(r.get("skipped") or []) for r in reports),
        "detail": reports,
        "dry_run": dry_run,
    }
