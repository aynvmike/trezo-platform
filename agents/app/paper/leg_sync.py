"""Re-arm Alpaca exit legs after an engine-side risk adjustment.

Mike 2026-07-14 (the RBLX morning): the reevaluator tightened stops and
lowered targets in the BOOKS, but for broker-held stocks the stale legs
kept sitting at Alpaca -- the far-away $59.81 sell never moved while the
price reversed away from it. Every engine-side adjustment to a broker
position must now CANCEL the old legs and re-arm an OCO at the new
prices, using the same verified cancel-first dance as the profit-step.
Long stocks only (v1); crypto has no broker legs (monitor owns those
exits internally).

BOOK-BOUND (TE-12 / BI-07, audit 2026-09-01). Every broker call in here
runs under bind_for_user(<the row's book>) with the route guard checked
first. Until then the pre-holiday review and the open-bell gap check
called this at tick start, BEFORE the monitor's per-row binding, so a
25k/75k row's resync cancelled the PRIMARY's legs for that symbol and
re-armed them at the other book's prices. The binding now happens INSIDE
this function, so no caller can reach the broker unbound; an
unresolvable book is skipped with a logged reason, never defaulted to
the primary. The broker-truth quantity read is STRICT: a failed read
means "do nothing, retry next pass", never "no shares".
"""

from __future__ import annotations

import asyncio


def _note(event: str, sym: str, reason: str, user_id: str) -> None:
    """One activity-log line. Never raises."""
    try:
        from app.agents.activity_log import record as _rec
        _rec(event, sym, reason=reason, extra={"user_id": str(user_id or "")})
    except Exception:  # noqa: BLE001
        pass


async def resync_alpaca_legs(row: dict, new_stop=None, new_target=None,
                             why: str = "", *,
                             user_id: str | None = None) -> tuple[bool, str]:
    """Cancel open orders for the row's symbol and re-arm an OCO at the
    row's CURRENT stop/target (or the overrides) -- on the row's OWN
    book. Never raises; returns (ok, note).

    `user_id` names the book and callers pass it explicitly (TE-12). It
    falls back to row["user_id"] only so an old-shape call can never
    pick up whichever account happens to be bound; a row that names no
    book is refused outright.

    Fail-CLOSED on the route and on the broker read: an unknown book, a
    binding the route guard rejects, or an answerless positions read
    means no order is touched. Fail-OPEN on the dance itself: once the
    read is good and a cancel or re-arm fails, the caller's DB state
    still stands and the next monitor pass / manual action can retry."""
    try:
        sym = str(row.get("ticker") or "").upper()
        if (str(row.get("broker") or "") != "alpaca"
                or str(row.get("asset_type") or "stock") != "stock"):
            return False, "not an alpaca stock row"
        if str(row.get("side") or "long").lower() != "long":
            return False, "long-only v1"
        qty = float(row.get("quantity") or 0)
        stop_p = float(new_stop if new_stop is not None
                       else (row.get("stop_price") or 0))
        tgt_p = float(new_target if new_target is not None
                      else (row.get("target_price") or 0))
        if not (sym and qty > 0 and stop_p > 0 and tgt_p > stop_p):
            return False, "bad inputs"
        # TE-12 / BI-07: bind THIS row's book and verify the route before
        # any broker call. The callers in the pre-break review and the
        # gap check run before the monitor's per-row binding, so without
        # this the primary's legs were the ones cancelled and re-armed.
        uid = str(user_id if user_id is not None
                  else (row.get("user_id") or ""))
        if not uid:
            _note("legs_resync_skipped", sym,
                  "row names no book -- refusing rather than acting on "
                  "whichever account is bound", uid)
            return False, "no book on row -- refused"
        from app.brokers.accounts import bind_for_user
        from app.brokers.route_guard import check_route, record_mismatch
        with bind_for_user(uid):
            rok, rnote = check_route(uid)
            if not rok:
                record_mismatch(sym, uid, rnote, "leg_sync")
                return False, f"route refused: {rnote}"
            return await _resync_bound(sym, qty, stop_p, tgt_p, why, uid)
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:120]


async def _resync_bound(sym: str, qty: float, stop_p: float, tgt_p: float,
                        why: str, uid: str) -> tuple[bool, str]:
    """The cancel-first dance. Runs ONLY under the row's book binding
    (resync_alpaca_legs is the sole caller and binds before calling)."""
    from app.brokers.alpaca import (
        alpaca_configured, cancel_open_orders_for, get_open_orders_for,
        get_positions_strict, submit_oco_sell,
    )
    if not alpaca_configured():
        return False, "alpaca not configured for this book"
    # BROKER-TRUTH qty (2026-07-15, the PYPL 4-share incident): a TP
    # leg can PARTIALLY FILL in the same breath the resync cancels it
    # -- the row's quantity is then stale and an OCO for the old size
    # gets refused, leaving the remainder naked. Protect what the
    # broker actually holds.
    #
    # TE-12 / house rule 3: the read is STRICT. None means the read
    # FAILED (429/timeout/5xx), which is not "no shares" -- cancelling
    # legs on an answerless read strips protection from shares we
    # cannot see. Take no action and retry next pass.
    try:
        _live = await get_positions_strict(token=None)
    except Exception as e:  # noqa: BLE001
        # REVIEW TE-12 (2026-09-01): return here. Falling through to the
        # `_live is None` branch below logged a SECOND legs_resync_deferred
        # line for the same failed read, doubling the deferral count the
        # ops audit reads from the activity log.
        _note("legs_resync_deferred", sym,
              f"broker positions read raised ({str(e)[:60]}) -- legs "
              f"left as they are; retry next pass", uid)
        return False, "broker read failed -- retry next pass"
    if _live is None:
        _note("legs_resync_deferred", sym,
              "broker positions read failed -- legs left as they are; "
              "retry next pass", uid)
        return False, "broker read failed -- retry next pass"
    _bq = 0.0
    for _p in _live:
        if str(_p.get("symbol", "")).upper() == sym:
            _bq = abs(float(_p.get("qty") or 0))
            break
    if _bq <= 0:
        return False, "no shares at the broker (closed mid-dance)"
    qty = min(qty, _bq)
    _n, err = await cancel_open_orders_for(sym)
    if err:
        return False, f"cancel failed: {err}"
    for _ in range(6):
        left = await get_open_orders_for(sym)
        if not left:
            break
        await asyncio.sleep(0.7)
    o, oerr = await submit_oco_sell(sym, qty, limit_price=round(tgt_p, 2),
                                    stop_price=round(stop_p, 2))
    if oerr or not o:
        # PROTECTION FIRST (2026-07-15): when the OCO is refused, a
        # plain stop still guards the shares -- never leave them
        # naked because the fancier order was rejected.
        try:
            from app.brokers.alpaca import submit_stop_sell
            o2, e2 = await submit_stop_sell(sym, qty, stop_p)
            if o2 and not e2:
                _note("legs_resynced", sym,
                      (f"OCO refused ({str(oerr)[:60]}) -- "
                       f"protection-first STOP placed at "
                       f"{stop_p:.2f} for {qty:g} shares"), uid)
                return True, "stop-only"
            _note("legs_naked_alert", sym,
                  (f"exit legs could NOT be re-armed (OCO: "
                   f"{str(oerr)[:60]}; stop: {str(e2)[:60]}) -- "
                   f"POSITION MAY BE UNPROTECTED"), uid)
        except Exception:  # noqa: BLE001
            pass
        return False, f"OCO re-arm failed: {oerr}"
    _note("legs_resynced", sym,
          (f"broker exit legs re-armed: target {tgt_p:.2f}, "
           f"stop {stop_p:.2f}" + (f" -- {why}" if why else "")), uid)
    return True, "ok"
