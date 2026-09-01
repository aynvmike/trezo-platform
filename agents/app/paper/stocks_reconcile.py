"""Stock-side reconciliation - extracted from main.py so PositionMonitor
can call it on its own schedule (Task #32, 2026-06-03 Mike's ask).

Why this exists: today /stocks/reconcile is a manual button. Options
already auto-reconciles every 30 min; stocks should too. Mike found a
phantom-position drift (Alpaca closed SOFI + INTC, Trezo still showed
them as open) that would have been caught automatically with a
30-minute background reconcile.

Returns the same shape the /stocks/reconcile endpoint used to return.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def _roll_realized(client, user_id, pnl: float) -> None:
    """Fold a reconcile-close P/L into the account realized counters
    (today/week/ytd). P/L stats only -- cash is deliberately untouched so
    the internal cash ledger cannot drift from this path (2026-07-02)."""
    try:
        def _acct():
            return (client.table("paper_accounts")
                    .select("today_realized_pnl_usd, week_realized_pnl_usd, "
                            "ytd_realized_pnl_usd")
                    .eq("user_id", user_id).single().execute())
        row = (await asyncio.to_thread(_acct)).data or {}

        def _upd():
            return (client.table("paper_accounts").update({
                "today_realized_pnl_usd": round(
                    float(row.get("today_realized_pnl_usd") or 0) + pnl, 2),
                "week_realized_pnl_usd": round(
                    float(row.get("week_realized_pnl_usd") or 0) + pnl, 2),
                "ytd_realized_pnl_usd": round(
                    float(row.get("ytd_realized_pnl_usd") or 0) + pnl, 2),
            }).eq("user_id", user_id).execute())
        await asyncio.to_thread(_upd)
    except Exception:  # noqa: BLE001
        pass


async def reconcile_stocks_all_users() -> dict[str, Any]:
    """Reconcile every user's open paper_positions stocks against the
    Alpaca broker truth. Idempotent + safe to call from a tick loop.

    Mirrors the behavior of POST /stocks/reconcile exactly so both
    paths produce the same result.
    """
    from app.brokers.alpaca import (
        alpaca_configured, get_positions, UserToken,
    )
    from app.paper.engine import record_external_position
    from app.integrations.web_tokens import get_user_broker_token
    from app.config import get_settings

    s = get_settings()
    if not (s.supabase_url and s.supabase_service_role_key):
        return {"ok": False, "error": "Supabase not configured."}

    try:
        from supabase import create_client
        client = create_client(
            s.supabase_url, s.supabase_service_role_key
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Supabase client error: {e}"}

    if not alpaca_configured():
        return {"ok": False, "error": "Alpaca env keys not configured."}

    def _users():
        return client.table("paper_accounts").select("user_id").execute()
    user_rows = (await asyncio.to_thread(_users)).data or []

    total_updated = 0
    total_inserted = 0
    total_closed = 0
    per_user: list[dict] = []

    for u in user_rows:
        user_id = u.get("user_id")
        if not user_id:
            continue

        # 2026-08-17: this loop said "every user's positions" but bound
        # NO account -- so with three books live it reconciled book B
        # against whatever book A happened to be holding, and every row
        # B owned that A did not was closed as a phantom. With one
        # account that was invisible; with three it cost both new books
        # their entire open ledger. Bind this book, verify the bind took,
        # and skip rather than guess.
        from app.brokers.accounts import (
            set_account_for_user as _bind_book,
            should_skip_unresolved as _skip_book,
        )
        from app.runtime import book_scope
        if _skip_book(str(user_id)):
            continue
        _bind_book(str(user_id))
        _route_ok, _route_note = book_scope.verify(str(user_id))
        if not _route_ok:
            try:
                from app.brokers.route_guard import record_mismatch
                record_mismatch("-", str(user_id), _route_note,
                                "stocks_reconcile")
            except Exception:  # noqa: BLE001
                pass
            continue
        book_scope.invalidate(str(user_id))

        bt = await get_user_broker_token(user_id, "alpaca")
        token = UserToken(
            access_token=bt.access_token,
            refresh_token=bt.refresh_token,
            expires_at=bt.expires_at,
        ) if bt else None

        # HONEST NOTE (audit 2026-09-01): get_positions() never raises --
        # it collapses a failed read into [] -- so fetch_ok is always True
        # here and cannot tell a 429 from a flat account. The real net is
        # trust_close below, which refuses to phantom-close on an EMPTY
        # list. Behaviour deliberately left as-is in this pass.
        fetch_ok = True
        try:
            alpaca_positions = await get_positions(token=token)
        except Exception:
            alpaca_positions = []
            fetch_ok = False

        alpaca_by_sym: dict[str, dict] = {}
        for p in alpaca_positions:
            # Task #10 (2026-06-11): this reconciler is stocks-only.
            # Without this filter, an Alpaca crypto position ('BTCUSD',
            # asset_class='crypto') gets re-inserted below as a phantom
            # asset_type='stock' row that nothing can ever exit.
            ac = str(p.get("asset_class") or "us_equity").lower()
            if ac != "us_equity":
                continue
            sym = str(p.get("symbol", "")).upper()
            if sym:
                alpaca_by_sym[sym] = p

        # OVERSELL GUARD (Mike 2026-07-22, the DRAM -2 incident): the
        # stock book is LONG-ONLY. A negative stock quantity at the
        # broker means stale exit orders double-sold (a GTC leg filled
        # after a partial had already sold shares). Cover it right away
        # -- closing a short IS the buy -- unless a cover buy is
        # already in flight, and raise a loud line either way.
        for _sym_neg in list(alpaca_by_sym.keys()):
            try:
                _q_neg = float(alpaca_by_sym[_sym_neg].get("qty") or 0)
            except (TypeError, ValueError):
                continue
            if _q_neg >= 0:
                continue
            _st_n = "skipped"
            try:
                from app.brokers.alpaca import _get as _araw
                _oo = await _araw(
                    f"/v2/orders?status=open&symbols={_sym_neg}") or []
                _buy_inflight = any(
                    isinstance(_o, dict) and str(_o.get("side")) == "buy"
                    for _o in _oo)
            except Exception:  # noqa: BLE001
                _buy_inflight = False
            if not _buy_inflight:
                try:
                    from app.agents.position_monitor import (
                        _throttled_liquidate,
                    )
                    _res_n, _st_n = await _throttled_liquidate(
                        _sym_neg, "stock")
                except Exception:  # noqa: BLE001
                    _st_n = "error"
            else:
                _st_n = "cover already in flight"
            try:
                from app.agents.activity_log import record as _arec_n
                _arec_n("oversell_covered", _sym_neg,
                        reason=(f"LONG-ONLY book showed {_q_neg:g} at the "
                                f"broker (stale exits double-sold); "
                                f"buy-to-cover: {_st_n}"),
                        extra={"user_id": str(user_id), "qty": _q_neg})
            except Exception:  # noqa: BLE001
                pass
            # Never reconcile a short as if it were a long row.
            alpaca_by_sym.pop(_sym_neg, None)

        # Trust a "broker doesn't list this symbol" signal as a real
        # close ONLY when the read returned >=1 stock position. An empty
        # list -- which is also what a failed read looks like, see the
        # fetch_ok note above -- must not phantom-close real rows at the
        # open bell (2026-06-15 fix).
        trust_close = fetch_ok and bool(alpaca_by_sym)

        def _trezo_open(uid=user_id):
            return (
                client.table("paper_positions")
                .select(
                    "id, ticker, side, quantity, entry_price, "
                    "stop_price, target_price, strategy"
                )
                .eq("user_id", uid)
                .eq("status", "open")
                .eq("asset_type", "stock")
                .execute()
            )
        trezo_rows = (await asyncio.to_thread(_trezo_open)).data or []

        updated = 0
        closed = 0
        inserted = 0
        notes_list: list[str] = []

        # 1) Close or patch existing Trezo rows.
        for r in trezo_rows:
            sym = str(r["ticker"]).upper()
            ap = alpaca_by_sym.get(sym)
            if ap is None:
                # An empty or errored broker read must never be treated
                # as a close (open-bell phantom-close race, 2026-06-15).
                if not trust_close:
                    continue
                # Trezo has it open; Alpaca does not. Close as manual --
                # and recover the REAL exit fill so realized P/L is true
                # ($0-realized rows corrupted the learning loop and kept
                # the weekly kill-switch blind; fixed 2026-07-02).
                exit_px = None
                try:
                    from app.brokers.alpaca import get_recent_closed_orders
                    _r_side = str(r.get("side") or "long")
                    _close_side = "sell" if _r_side == "long" else "buy"
                    for o in await get_recent_closed_orders(sym, token=token):
                        if (str(o.get("side")) == _close_side
                                and o.get("filled_avg_price")):
                            exit_px = float(o["filled_avg_price"])
                            break
                except Exception:  # noqa: BLE001
                    exit_px = None
                _qty = float(r.get("quantity") or 0)
                _entry = float(r.get("entry_price") or 0)
                realized = 0.0
                if exit_px and _entry > 0 and _qty > 0:
                    realized = round(
                        _qty * (exit_px - _entry)
                        if str(r.get("side") or "long") == "long"
                        else _qty * (_entry - exit_px), 2)

                def _close(rid=r["id"], _px=exit_px, _pnl=realized):
                    return (
                        client.table("paper_positions")
                        .update({
                            # paper_positions has NO notes column; the old
                            # "notes" key here made PostgREST reject the
                            # ENTIRE update, so phantom closes silently
                            # never happened (found 2026-06-11). The
                            # reconcile reason now lives in the summary
                            # message + agent log only.
                            "status": "closed_manual",
                            "exit_price": _px,
                            "realized_pnl_usd": _pnl,
                            "exit_at": _now_iso(),
                        })
                        .eq("id", rid)
                        .execute()
                    )
                try:
                    await asyncio.to_thread(_close)
                    closed += 1
                    notes_list.append(f"{sym} closed (phantom)")
                    # 2026-07-07: ghost rows CAUSE broker rejects (selling
                    # shares the broker no longer has). Once the ghosts are
                    # reconciled the cause is gone -- clear the reject
                    # window so the kill-switch can reopen the day.
                    # KS-4: for THIS book only. A ghost reconciled on one
                    # book must not wipe another book's reject history
                    # (every book is its own book).
                    try:
                        from app.paper.killswitch import reset_broker_rejects
                        reset_broker_rejects(str(user_id))
                        from app.agents.activity_log import record as _arec0
                        _arec0("halt_cleared", sym,
                               reason=("ghost position reconciled - broker-"
                                       "reject counter reset; session can "
                                       "trade again"),
                               extra={"user_id": str(user_id)})
                    except Exception:  # noqa: BLE001
                        pass
                    if realized:
                        await _roll_realized(client, user_id, realized)
                    try:
                        from app.agents.activity_log import record as _arec
                        _arec("reconcile_close", sym,
                              reason=(f"broker no longer holds it - closed "
                                      f"with realized ${realized:+.2f}"
                                      if exit_px else
                                      "broker no longer holds it - closed; "
                                      "no closing fill found so P/L unknown"),
                              extra={"user_id": str(user_id),
                                     "exit_price": exit_px})
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:
                    continue
                continue

            # Both sides have it - check for qty / entry drift.
            try:
                ap_qty = abs(float(ap.get("qty") or 0))
                ap_entry = float(ap.get("avg_entry_price") or 0)
            except Exception:
                continue
            trezo_qty = float(r.get("quantity") or 0)
            trezo_entry = float(r.get("entry_price") or 0)

            if ap_qty <= 0:
                continue

            drift_qty = abs(ap_qty - trezo_qty) > 1e-6
            drift_entry = abs(ap_entry - trezo_entry) > 0.01
            # Slippage rule (2026-07-02, rules doc §1): the entry drift IS
            # the realized fill slippage -- decision price (our row) vs the
            # broker's avg fill. Measure ONCE (the patch below overwrites
            # our copy), log it, feed the session slippage halt.
            if drift_entry and trezo_entry > 0 and ap_entry > 0:
                try:
                    _side_r = str(r.get("side") or "long")
                    _adverse = ((ap_entry - trezo_entry) / trezo_entry
                                if _side_r == "long"
                                else (trezo_entry - ap_entry) / trezo_entry)
                    _bps = _adverse * 10_000.0
                    _n_breach = 0
                    if _bps > 0:
                        from app.paper.killswitch import record_fill_slippage
                        _n_breach = record_fill_slippage(
                            _bps, user_id=str(user_id))
                    from app.agents.activity_log import record as _arec3
                    _arec3("fill_slippage", sym,
                           reason=(f"decision {trezo_entry:g} -> fill "
                                   f"{ap_entry:g} = {_bps:+.0f}bps"),
                           extra={"user_id": str(user_id),
                                  "bps": round(_bps, 1),
                                  "session_breaches": _n_breach})
                except Exception:  # noqa: BLE001
                    pass
            if drift_qty or drift_entry:
                def _patch(rid=r["id"], q=ap_qty, e=ap_entry):
                    return (
                        client.table("paper_positions")
                        .update({"quantity": q, "entry_price": e})
                        .eq("id", rid)
                        .execute()
                    )
                try:
                    await asyncio.to_thread(_patch)
                    updated += 1
                    notes_list.append(
                        f"{sym} patched qty={ap_qty} entry={ap_entry}"
                    )
                except Exception:
                    pass

        # 2) Insert any Alpaca positions Trezo missed.
        trezo_syms = {str(r["ticker"]).upper() for r in trezo_rows}
        for sym, ap in alpaca_by_sym.items():
            if sym in trezo_syms:
                continue
            try:
                ap_qty = float(ap.get("qty") or 0)
                ap_entry = float(ap.get("avg_entry_price") or 0)
            except Exception:
                continue
            if abs(ap_qty) < 1e-6:
                continue
            side = "long" if ap_qty > 0 else "short"
            qty_abs = abs(ap_qty)

            # Inheritance first (2026-06-12: the open-bell phantom-close
            # race closed fresh stms rows, and this re-import path gave
            # them strategy="reconciled" + default stops -- so CSCO/SOFI
            # lost their time stops and rode all day). If THIS ticker has
            # a row closed within the last 24h, inherit its strategy,
            # stop and target: the re-imported position is almost
            # certainly the same trade the books lost.
            inherited = None
            try:
                def _last_closed(uid=user_id, s=sym):
                    return (
                        client.table("paper_positions")
                        .select("strategy, stop_price, target_price, side, entry_at")
                        .eq("user_id", uid).eq("ticker", s)
                        .neq("status", "open")
                        .order("entry_at", desc=True)
                        .limit(5)
                        .execute()
                    )
                prev_rows = (await asyncio.to_thread(_last_closed)).data or []
                if prev_rows:
                    from datetime import datetime, timezone, timedelta
                    now = datetime.now(timezone.utc)

                    def _fresh_same_side(row):
                        ts = str(row.get("entry_at") or "")
                        try:
                            dt = (datetime.fromisoformat(
                                ts.replace("Z", "+00:00")) if ts else None)
                        except Exception:
                            dt = None
                        if not dt or (now - dt) >= timedelta(hours=24):
                            return False
                        return (row.get("side") or side) == side

                    # prev_rows are newest-first (entry_at desc). Take the
                    # strategy from the newest qualifying row with a REAL
                    # name (not blank / "reconciled"), and stop/target from
                    # the newest qualifying row that carries them, so a
                    # prior "reconciled" ghost can't bury the trade's true
                    # strategy (2026-06-15).
                    inh_strategy = None
                    inh_stop = None
                    inh_target = None
                    for row in prev_rows:
                        if not _fresh_same_side(row):
                            continue
                        if inh_strategy is None:
                            cand = str(row.get("strategy") or "").strip()
                            if cand and cand.lower() != "reconciled":
                                inh_strategy = row.get("strategy")
                        if inh_stop is None and row.get("stop_price"):
                            inh_stop = row.get("stop_price")
                        if inh_target is None and row.get("target_price"):
                            inh_target = row.get("target_price")
                    if (inh_strategy is not None or inh_stop is not None
                            or inh_target is not None):
                        inherited = {
                            "strategy": inh_strategy,
                            "stop_price": inh_stop,
                            "target_price": inh_target,
                        }
            except Exception:  # noqa: BLE001
                inherited = None

            # Best-effort stop/target from per-user defaults.
            try:
                from app.runtime.settings import get_bot_settings
                cfg = get_bot_settings(user_id)
                sp = float(cfg.default_stop_pct or 0.05)
                tp = float(cfg.default_target_pct or 0.10)
            except Exception:
                sp, tp = 0.05, 0.10
            if side == "long":
                stop_price = ap_entry * (1 - sp)
                target_price = ap_entry * (1 + tp)
            else:
                stop_price = ap_entry * (1 + sp)
                target_price = ap_entry * (1 - tp)
            strategy_label = "reconciled"
            if inherited:
                strategy_label = inherited.get("strategy") or "reconciled"
                if inherited.get("stop_price"):
                    stop_price = float(inherited["stop_price"])
                if inherited.get("target_price"):
                    target_price = float(inherited["target_price"])

            try:
                await record_external_position(
                    user_id=str(user_id),
                    ticker=sym,
                    asset_type="stock",
                    side=side,
                    quantity=qty_abs,
                    entry_price=ap_entry,
                    stop_price=stop_price,
                    target_price=target_price,
                    strategy=strategy_label,
                    broker="alpaca",
                    broker_order_id=None,
                    source_payload={
                        "auto_reconcile": True,
                        "alpaca_avg_entry": ap_entry,
                    },
                )
                inserted += 1
                notes_list.append(
                    f"{sym} inserted from broker (qty {qty_abs})"
                )
            except Exception:
                continue

        total_updated += updated
        total_inserted += inserted
        total_closed += closed
        per_user.append({
            "user_id": str(user_id),
            "updated": updated,
            "inserted": inserted,
            "closed": closed,
            "notes": notes_list,
        })

    try:
        from app.brokers.accounts import clear_account
        clear_account()
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": True,
        "users_touched": len(per_user),
        "updated": total_updated,
        "inserted": total_inserted,
        "closed": total_closed,
        "details": per_user,
    }


# ---------------------------------------------------------------------------
# Balance + full-integrity reconcile (2026-06-16, Mike's "extend it to
# everything" ask). Broker is the source of truth when connected; these are
# idempotent, never zero the ledger on a failed read, and leave paper-only /
# account-size-sim users (no broker) untouched.
# ---------------------------------------------------------------------------


async def reconcile_account_balances_all_users() -> dict[str, Any]:
    """Sync each book's internal cash ledger (paper_accounts.current_cash_usd)
    to ITS OWN Alpaca account's cash, when a broker is connected. Fixes
    ledger drift (e.g. the dashboard read $39k while the broker held ~$5k).
    Only runs when Alpaca is configured for the book; paper-only/sim accounts
    are left alone so the account-size simulator still works. Never
    overwrites on a failed/empty broker read.

    TE-16 (audit 2026-09-01): this loop ran UNBOUND, so get_account()
    resolved to the primary account for every book and stamped the
    primary's cash onto all three paper_accounts rows hourly (live proof:
    three books identical to the cent). Each book is now bound with
    bind_for_user + check_route before its read; an unresolvable book is
    skipped with a logged reason, never defaulted to the primary."""
    from app.brokers.alpaca import alpaca_configured, get_account, UserToken
    from app.brokers.accounts import bind_for_user
    from app.brokers.route_guard import check_route, record_mismatch
    from app.integrations.web_tokens import get_user_broker_token
    from app.config import get_settings

    s = get_settings()
    if not (s.supabase_url and s.supabase_service_role_key):
        return {"ok": False, "error": "Supabase not configured."}
    try:
        from supabase import create_client
        client = create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Supabase client error: {e}"}

    env_ok = alpaca_configured()
    DRIFT_MIN = 1.0  # ignore sub-dollar noise

    def _users():
        return client.table("paper_accounts").select(
            "user_id, current_cash_usd").execute()
    rows = (await asyncio.to_thread(_users)).data or []

    synced = 0
    skipped: list[dict] = []
    per_user: list[dict] = []
    for u in rows:
        user_id = u.get("user_id")
        if not user_id:
            continue
        bt = await get_user_broker_token(user_id, "alpaca")
        token = UserToken(
            access_token=bt.access_token,
            refresh_token=bt.refresh_token,
            expires_at=bt.expires_at,
        ) if bt else None
        # No broker at all for this user -> leave the modeled/sim ledger be.
        if token is None and not env_ok:
            continue
        # TE-16: the cash read MUST happen under this book's binding, and
        # the write below only ever uses a value read under that binding.
        with bind_for_user(str(user_id)):
            _route_ok, _route_note = check_route(str(user_id))
            if not _route_ok:
                logger.warning(
                    "balance_reconcile.skip user=%s reason=%s",
                    str(user_id)[:8], _route_note)
                record_mismatch("-", str(user_id), _route_note,
                                "balance_reconcile")
                skipped.append({"user_id": str(user_id),
                                "reason": _route_note})
                continue
            try:
                acct = await get_account(token=token)
            except Exception:
                acct = None
        if acct is None:
            # Failed read: never overwrite on a hiccup -- and say so.
            logger.warning(
                "balance_reconcile.skip user=%s reason=broker account read "
                "failed; ledger left untouched", str(user_id)[:8])
            skipped.append({"user_id": str(user_id),
                            "reason": "broker read failed"})
            continue
        broker_cash = round(float(acct.cash or 0.0), 2)
        internal = round(float(u.get("current_cash_usd") or 0.0), 2)
        drift = round(broker_cash - internal, 2)
        if abs(drift) < DRIFT_MIN:
            continue

        def _patch(uid=user_id, cash=broker_cash):
            return (
                client.table("paper_accounts")
                .update({"current_cash_usd": cash, "updated_at": _now_iso()})
                .eq("user_id", uid)
                .execute()
            )
        try:
            await asyncio.to_thread(_patch)
            synced += 1
            per_user.append({
                "user_id": str(user_id), "was": internal,
                "now": broker_cash, "drift": drift,
                "account": getattr(acct, "account_number", ""),
            })
        except Exception:
            continue

    return {"ok": True, "synced": synced, "details": per_user,
            "skipped": skipped}


# detect_option_drift_all_users used to live here. Deleted (audit 2026-09-01,
# TE-17/LT-05): it had zero call sites and counted rows in options_positions,
# a table that holds no open rows -- option legs live in paper_positions
# with asset_type='option'. app/paper/broker_truth.py is the real
# option-drift detector.


async def run_integrity_sweep() -> dict[str, Any]:
    """One self-healing pass aligning Trezo to broker truth across every
    dimension we can: cash ledger + stock positions (active repair) and an
    orphan-option import (the "options" key is import_orphan_options'
    {imported, skipped, details} report -- there is no drift report here;
    broker_truth.py owns that). Idempotent; safe at startup or in a tick
    loop. Each step is independently guarded."""
    report: dict[str, Any] = {"ok": True}
    try:
        report["balances"] = await reconcile_account_balances_all_users()
    except Exception as e:  # noqa: BLE001
        report["balances"] = {"ok": False, "error": str(e)}
    try:
        report["stocks"] = await reconcile_stocks_all_users()
    except Exception as e:  # noqa: BLE001
        report["stocks"] = {"ok": False, "error": str(e)}
    try:
        report["options"] = await import_orphan_options_all_users()
    except Exception as e:  # noqa: BLE001
        report["options"] = {"ok": False, "error": str(e)}
    # Adoption closes the loop the other way round (2026-08-17). The steps
    # above fix rows we HAVE; this one writes rows for positions the
    # broker holds and we have NO row for -- which is the state the
    # pre-binding phantom closes left both new books in, and the state
    # every crashed fill or hand-placed order leaves us in. A position
    # with no row is a position nothing manages; on crypto, with no
    # native bracket, it is a position with no stop.
    try:
        import os as _os
        if _os.getenv("TREZO_ADOPT_ORPHANS", "1") != "0":
            from app.paper.adoption import adopt_all_books
            report["adopted"] = await adopt_all_books(
                dry_run=_os.getenv("TREZO_ADOPT_DRY_RUN", "0") == "1")
    except Exception as e:  # noqa: BLE001
        report["adopted"] = {"ok": False, "error": str(e)}
    return report


def _parse_occ(occ: str):
    """Parse an OCC option symbol (e.g. F260717P00014000) into its parts.
    Returns dict(underlying, expiration 'YYYY-MM-DD', option_type, strike) or
    None if it doesn't match the standard format."""
    import re
    m = re.match(r"^([A-Z]+)(\d{6})([CP])(\d{8})$", str(occ).strip().upper())
    if not m:
        return None
    und, yymmdd, cp, strike = m.groups()
    return {
        "underlying": und,
        "expiration": f"20{yymmdd[0:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}",
        "option_type": "call" if cp == "C" else "put",
        "strike": int(strike) / 1000.0,
    }


async def import_orphan_options_all_users() -> dict[str, Any]:
    """Repair: import option positions that exist at the broker but are NOT
    tracked in Trezo (orphans - e.g. a Wheel CSP that fired but whose tracking
    insert failed). Mirrors the Wheel's own insert shape. Deduped on
    (underlying, type, strike, expiration) against open options_positions
    AND against the book's open paper_positions option rows (matched by OCC
    ticker or the same 4-tuple), so it never double-imports, and never runs
    on a failed broker read. Short put -> wheel_csp, short call -> wheel_cc,
    long -> reconciled_option. Added 2026-06-16.

    TE-17 + LT-05 (audit 2026-09-01): this ran UNBOUND, so every book was
    handed the PRIMARY's contracts, and it deduped only against
    options_positions -- while real option legs live in paper_positions
    (asset_type='option'). Result: 232 churn rows and phantom collateral on
    acct3. Now: bind per book (skip unresolved, logged), read with the
    strict variant (None -> skip the book), dedupe against the real ledger.
    """
    from app.brokers.alpaca import (
        alpaca_configured, get_option_positions_strict, UserToken,
    )
    from app.brokers.accounts import bind_for_user
    from app.brokers.route_guard import check_route, record_mismatch
    from app.integrations.web_tokens import get_user_broker_token
    from app.config import get_settings

    s = get_settings()
    if not (s.supabase_url and s.supabase_service_role_key):
        return {"ok": False, "error": "Supabase not configured."}
    try:
        from supabase import create_client
        client = create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Supabase client error: {e}"}

    env_ok = alpaca_configured()

    def _users():
        return client.table("paper_accounts").select("user_id").execute()
    rows = (await asyncio.to_thread(_users)).data or []

    imported = 0
    skipped = 0
    details: list[dict] = []
    for u in rows:
        user_id = u.get("user_id")
        if not user_id:
            continue
        bt = await get_user_broker_token(user_id, "alpaca")
        token = UserToken(
            access_token=bt.access_token, refresh_token=bt.refresh_token,
            expires_at=bt.expires_at,
        ) if bt else None
        if token is None and not env_ok:
            continue
        # TE-17: read THIS book's contracts under ITS binding. The strict
        # read returns None on any failed read -> skip the book, say so.
        with bind_for_user(str(user_id)):
            _route_ok, _route_note = check_route(str(user_id))
            if not _route_ok:
                logger.warning(
                    "orphan_options.skip user=%s reason=%s",
                    str(user_id)[:8], _route_note)
                record_mismatch("-", str(user_id), _route_note,
                                "orphan_options")
                details.append({"user_id": str(user_id),
                                "skipped": _route_note})
                continue
            try:
                broker_opts = await get_option_positions_strict(token=token)
            except Exception:
                broker_opts = None
        if broker_opts is None:
            logger.warning(
                "orphan_options.skip user=%s reason=broker option read "
                "failed; nothing imported", str(user_id)[:8])
            details.append({"user_id": str(user_id),
                            "skipped": "broker read failed"})
            continue  # failed read: never import on a hiccup

        def _trezo_open(uid=user_id):
            return (
                client.table("options_positions")
                .select("underlying, option_type, strike, expiration")
                .eq("user_id", uid).eq("status", "open").execute()
            )

        # LT-05: the REAL option ledger. Legs the engine trades live in
        # paper_positions with asset_type='option' and ticker = OCC code.
        def _ledger_open(uid=user_id):
            return (
                client.table("paper_positions")
                .select("ticker")
                .eq("user_id", uid).eq("status", "open")
                .eq("asset_type", "option").execute()
            )
        try:
            trezo_rows = (await asyncio.to_thread(_trezo_open)).data or []
            ledger_rows = (await asyncio.to_thread(_ledger_open)).data or []
        except Exception:
            # Cannot see what this book already tracks -> importing would
            # be a guess. Skip the book.
            details.append({"user_id": str(user_id),
                            "skipped": "ledger read failed"})
            continue

        def _key(und, typ, strike, exp):
            return (str(und).upper(), str(typ).lower(),
                    round(float(strike or 0), 2), str(exp))
        have = {
            _key(r.get("underlying"), r.get("option_type"),
                 r.get("strike"), r.get("expiration"))
            for r in trezo_rows
        }
        have_occ: set[str] = set()
        for r in ledger_rows:
            _t = str(r.get("ticker") or "").upper().strip()
            if not _t:
                continue
            have_occ.add(_t)
            _p = _parse_occ(_t)
            if _p:
                have.add(_key(_p["underlying"], _p["option_type"],
                              _p["strike"], _p["expiration"]))

        for op in broker_opts:
            occ = str(op.get("symbol") or "")
            parsed = _parse_occ(occ)
            if not parsed:
                skipped += 1
                continue
            try:
                qty = float(op.get("qty") or 0)
            except (TypeError, ValueError):
                continue
            if abs(qty) < 1e-9:
                continue
            k = _key(parsed["underlying"], parsed["option_type"],
                     parsed["strike"], parsed["expiration"])
            if k in have or occ.upper().strip() in have_occ:
                continue  # already tracked (options_positions or ledger)
            is_short = qty < 0
            contracts = int(abs(qty)) or 1
            try:
                prem = float(op.get("avg_entry_price") or 0)
            except (TypeError, ValueError):
                prem = 0.0
            if is_short and parsed["option_type"] == "put":
                strat = "wheel_csp"
            elif is_short and parsed["option_type"] == "call":
                strat = "wheel_cc"
            else:
                strat = "reconciled_option"
            row = {
                "user_id": user_id,
                "underlying": parsed["underlying"],
                "strategy": strat,
                "direction": "income" if is_short else "long",
                "option_type": parsed["option_type"],
                "strike": parsed["strike"],
                "expiration": parsed["expiration"],
                "contracts": contracts,
                "net_premium_usd": round(prem * 100.0 * contracts, 2),
                "legs": [{
                    "action": "sell" if is_short else "buy",
                    "type": parsed["option_type"],
                    "strike": parsed["strike"], "premium": prem,
                }],
                "notes": (f"Imported from broker by integrity sweep (orphan) "
                          f"· occ={occ}"),
            }

            def _ins(r=row):
                return client.table("options_positions").insert(r).execute()
            try:
                await asyncio.to_thread(_ins)
                imported += 1
                have.add(k)
                details.append({
                    "user_id": str(user_id), "occ": occ,
                    "underlying": parsed["underlying"], "strategy": strat,
                    "contracts": contracts, "strike": parsed["strike"],
                })
            except Exception as e:  # noqa: BLE001
                skipped += 1
                details.append({"occ": occ, "error": str(e)[:120]})

    return {"ok": True, "imported": imported, "skipped": skipped,
            "details": details}
