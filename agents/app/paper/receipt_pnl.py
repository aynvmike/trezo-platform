"""Read-only broker evidence -> FIFO scorecards. Never alters trades or balances.

Nightly windows end at 21:30 New York time and start at the previous 21:30,
so crypto has no unreported overnight gap. Session/day-trade labels use the
New York calendar independently. Unknown basis, spread and reconciliation
components remain explicit; a modeled fee is never described as posted.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import date, datetime, time, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
OPTION = re.compile(r"^[A-Z]+\d{6}[CP]\d{8}$")


def stamp(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp without timezone")
    return result


def num(value):
    if isinstance(value, bool):
        raise ValueError("invalid number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("invalid number")
    return result


def symbol(value):
    return str(value or "").upper().replace("/", "")


def crypto_fill(row):
    from app.data.candles import COIN_MAP
    sym = symbol(row.get("symbol"))
    return (row.get("asset_class") == "crypto" or "/" in str(row.get("symbol"))
            or (sym.endswith("USD") and sym[:-3] in COIN_MAP))


def window(day):
    day = date.fromisoformat(str(day))
    return (datetime.combine(day-timedelta(days=1), time(21, 30), ET),
            datetime.combine(day, time(21, 30), ET))


def unknown(reason):
    return {"status": "unknown", "reason": reason, "lanes": {}, "totals": None,
            "unexplained_usd": None, "reconciliation_status": "unknown"}


def order_lanes(rows):
    """Attribute ONLY explicit entry order IDs, never a symbol's latest strategy."""
    candidates = defaultdict(set)
    for row in rows:
        payload = row.get("source_payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {}
        oid = row.get("broker_order_id") or payload.get("broker_order_id")
        if oid and row.get("strategy"):
            candidates[str(oid)].add(str(row["strategy"]))
    return {oid: next(iter(lanes)) if len(lanes) == 1 else "unattributed"
            for oid, lanes in candidates.items()}


def metrics(trades):
    values = [t["net_pnl_usd"] for t in trades]
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    return {"trades": len(trades), "day_trades": sum(t["day_trade"] for t in trades),
            "win_rate": len(wins)/len(values) if values else None,
            "average_win": sum(wins)/len(wins) if wins else None,
            "average_loss": sum(losses)/len(losses) if losses else None,
            "profit_factor": sum(wins)/abs(sum(losses)) if losses else None,
            "expectancy": sum(values)/len(values) if values else None,
            "friction_share_of_equity": None,
            "gross_pnl_usd": sum(t["gross_pnl_usd"] for t in trades),
            "fees_usd": sum(t["fees_usd"] for t in trades),
            "net_pnl_usd": sum(values)}


def build_report(fills, fees, *, start, end, lanes=None, opening=None,
                 equity=None, equity_delta=None, mtm_delta=None, cash_flow=None):
    """Pure FIFO. `opening` is explicit inventory at the receipt window start.

    Unknown initial inventory cannot be assumed flat. A caller with a proven
    flat starting account supplies {}. Partial receipts stay chronological;
    realized pieces aggregate by entry/exit order pair, avoiding inflated counts.
    """
    if fills is None or fees is None or opening is None:
        return unknown("receipts_fees_or_opening_inventory_unavailable")
    try:
        events, seen, issues, settlement = [], {}, [], set()
        for row in fills:
            kind = row.get("activity_type", "FILL")
            if kind != "FILL":
                settlement.add(symbol(row.get("symbol")))
                continue
            aid = str(row["id"])
            if aid in seen:
                if seen[aid] != row:
                    raise ValueError("conflicting duplicate fill")
                continue
            seen[aid] = row
            at = stamp(row["transaction_time"])
            qty, price = num(row["qty"]), num(row["price"])
            sym, side, oid = symbol(row["symbol"]), row["side"], str(row["order_id"])
            if not sym or not oid or qty <= 0 or price <= 0 or side not in ("buy", "sell"):
                raise ValueError("invalid fill")
            events.append({"at": at, "qty": qty, "price": price, "symbol": sym,
                           "sign": 1 if side == "buy" else -1, "order": oid,
                           "crypto": crypto_fill(row),
                           "multiplier": 100 if OPTION.match(sym) else 1, "id": aid})
        events.sort(key=lambda x: (x["at"], x["id"]))
        order_qty = defaultdict(float)
        for e in events:
            order_qty[e["order"]] += e["qty"]
        posted, fee_seen, unallocated = defaultdict(float), set(), 0.0
        for row in fees:
            aid = str(row["id"])
            if aid in fee_seen:
                continue
            fee_seen.add(aid)
            amount = -num(row["net_amount"])
            if row.get("order_id") in order_qty:
                posted[str(row["order_id"])] += amount
            elif start.date().isoformat() <= str(row.get("date", ""))[:10] <= end.date().isoformat():
                unallocated += amount
        lots, matches = defaultdict(deque), {}
        for sym, signed in opening.items():
            signed = num(signed)
            if signed:
                lots[symbol(sym)].append({"qty": abs(signed), "sign": 1 if signed > 0 else -1,
                    "price": None, "order": None, "at": None, "fee": 0, "fee_source": "unknown"})
        unknown_basis = 0
        for e in events:
            if e["at"] >= end:
                break
            qty, oid = e["qty"], e["order"]
            if oid in posted:
                fee, fee_source = posted[oid]/order_qty[oid], "posted"
            elif e["crypto"]:
                fee, fee_source = e["price"]*0.0026, "model"
            else:
                fee, fee_source = 0.0, "no_posted_fee"
            queue = lots[e["symbol"]]
            while qty > 1e-10 and queue and queue[0]["sign"] != e["sign"]:
                lot = queue[0]
                take = min(qty, lot["qty"])
                if start <= e["at"] < end:
                    if lot["price"] is None or e["symbol"] in settlement:
                        unknown_basis += 1
                    else:
                        key = (e["symbol"], lot["order"], oid)
                        item = matches.setdefault(key, {"symbol": e["symbol"],
                            "entry_order": lot["order"], "exit_order": oid,
                            "lane": (lanes or {}).get(lot["order"], "unattributed"),
                            "quantity": 0.0, "gross_pnl_usd": 0.0, "fees_usd": 0.0,
                            "day_trade": True, "fee_sources": set()})
                        item["quantity"] += take
                        item["gross_pnl_usd"] += (e["price"]-lot["price"])*lot["sign"]*take*e["multiplier"]
                        item["fees_usd"] += take*(lot["fee"]+fee)
                        item["day_trade"] &= lot["at"].astimezone(ET).date() == e["at"].astimezone(ET).date()
                        item["fee_sources"].update((lot["fee_source"], fee_source))
                lot["qty"] -= take
                qty -= take
                if lot["qty"] <= 1e-10:
                    queue.popleft()
            if qty > 1e-10:
                queue.append({**e, "qty": qty, "fee": fee, "fee_source": fee_source})
        trades = list(matches.values())
        by_lane = defaultdict(list)
        for t in trades:
            t["net_pnl_usd"] = t["gross_pnl_usd"]-t["fees_usd"]
            t["fee_sources"] = sorted(t["fee_sources"])
            t["fee_source"] = t["fee_sources"][0] if len(t["fee_sources"]) == 1 else "mixed"
            by_lane[t["lane"]].append(t)
        if unknown_basis:
            issues.append("unresolved_opening_basis_or_option_settlement")
        if settlement:
            issues.append("option_settlement_requires_separate_receipt_interpretation")
        if unallocated:
            issues.append("posted_fees_without_order_attribution")
        totals = metrics(trades)
        # No bid/ask observations exist in the FILL endpoint. Measured spread
        # cannot be reconstructed honestly from execution prices alone.
        reconciliation = (equity_delta is not None and mtm_delta is not None
                          and cash_flow is not None and not issues)
        unexplained = (equity_delta-mtm_delta-cash_flow-totals["net_pnl_usd"]
                       if reconciliation else None)
        return {"status": "partial" if issues else "complete", "issues": issues,
                "window_start": start.isoformat(), "window_end": end.isoformat(),
                "lanes": {lane: metrics(ts) for lane, ts in by_lane.items()}, "totals": totals,
                "round_trips": trades, "unknown_basis_matches": unknown_basis,
                "totals_scope": "known_fifo_matches_only",
                "leftover_lots": {s: sum(l["qty"]*l["sign"] for l in q) for s, q in lots.items() if q},
                "unallocated_posted_fees_usd": unallocated,
                "measured_spread_usd": None, "friction_share_of_equity": None,
                "fee_share_of_equity": totals["fees_usd"]/equity if equity and equity > 0 else None,
                "equity_delta_usd": equity_delta, "mtm_delta_usd": mtm_delta, "cash_flow_usd": cash_flow,
                "equity_delta_minus_known_net_usd": equity_delta-totals["net_pnl_usd"] if equity_delta is not None else None,
                "unexplained_usd": unexplained,
                "reconciliation_status": "measured" if reconciliation else "unknown",
                "reconciliation_note": "Requires aligned equity, open-position marks and cash movements; fee timing/model differences remain in residual."}
    except (KeyError, TypeError, ValueError, OverflowError):
        return unknown("malformed_or_conflicting_broker_evidence")


async def _ledger_lanes(client, uid):
    rows = []
    for offset in range(0, 20000, 500):
        page = (await asyncio.to_thread(lambda: client.table("paper_positions")
                .select("id,broker_order_id,strategy,source_payload").eq("user_id", uid)
                .order("id").range(offset, offset+499).execute())).data
        if not isinstance(page, list):
            raise ValueError("ledger attribution unavailable")
        rows.extend(page)
        if len(page) < 500:
            return order_lanes(rows)
    raise ValueError("ledger attribution truncated")


async def collect_book(account, day, *, client, now=None):
    from app.brokers.accounts import bind_for_user
    from app.brokers.route_guard import check_route
    from app.brokers import alpaca
    start, end = window(day)
    now = now or datetime.now(timezone.utc)
    if end > now:
        return unknown("report_window_not_complete")
    uid = str(account.user_id)
    with bind_for_user(uid) as bound:
        if (bound is None or bound.user_id != uid or not check_route(uid)[0]
                or alpaca.broker_venue() != "paper"
                or alpaca._headers() != bound.headers()):
            return unknown("book_route_unverified")
        # Read sufficiently far back for FIFO, while deriving unknown opening
        # inventory from current broker quantity minus ALL fetched net fills.
        days = max(1, min(365, int(os.getenv("TREZO_RECEIPT_LOOKBACK_DAYS", "30"))))
        since = (start-timedelta(days=days)).isoformat()
        fills = await alpaca.get_fill_activities_strict(since, max_pages=20)
        fees = await alpaca.get_fill_activities_strict(since, max_pages=20, activity_types="FEE")
        positions = await alpaca.get_positions_strict()
        acct = await alpaca.get_account()
        history = await alpaca._get("/v2/account/portfolio/history?period=1M&timeframe=1D")
        flows = await alpaca.get_fill_activities_strict(start.isoformat(), max_pages=20,
                    activity_types="CSD,CSW,DIV,INT,JNL,ACATC,ACATS")
        if fills is None or fees is None or positions is None or acct is None:
            return unknown("broker_read_failed_or_pagination_incomplete")
        try:
            current = {symbol(p["symbol"]): num(p["qty"]) for p in positions}
            if len(current) != len(positions):
                raise ValueError("duplicate inventory symbols")
            opening = defaultdict(float, current)
            seen = set()
            for f in fills:
                if f.get("activity_type", "FILL") == "FILL" and f["id"] not in seen:
                    seen.add(f["id"])
                    opening[symbol(f["symbol"])] -= num(f["qty"])*(1 if f["side"] == "buy" else -1)
            lanes = await _ledger_lanes(client, uid)
            equity_delta = mtm_delta = cash_flow = None
            mark = sum(num(p["unrealized_pl"]) for p in positions)
            aligned = abs((now-end).total_seconds()) <= 300
            previous = (await asyncio.to_thread(lambda: client.table("book_daily_pnl")
                        .select("report").eq("user_id", uid)
                        .eq("day", (date.fromisoformat(str(day))-timedelta(days=1)).isoformat())
                        .limit(1).execute())).data
            prior = previous[0]["report"] if previous else {}
            if aligned and prior.get("closing_marks_aligned"):
                if abs((stamp(prior["observed_at"])-start).total_seconds()) <= 300:
                    equity_delta = num(acct.equity)-num(prior["equity_observed_usd"])
                    mtm_delta = mark-num(prior["unrealized_observed_usd"])
            if flows is not None:
                cash_flow = 0.0
                for flow in flows:
                    # Date-only nontrade entries cannot be placed on a 21:30
                    # boundary. Preserve unknown rather than allocating them.
                    try:
                        at = stamp(flow["transaction_time"])
                        if start <= at < end:
                            cash_flow += num(flow["net_amount"])
                    except (KeyError, ValueError, TypeError):
                        cash_flow = None
                        break
            result = build_report(fills, fees, start=start, end=end, lanes=lanes,
                                  opening=opening, equity=acct.equity, equity_delta=equity_delta,
                                  mtm_delta=mtm_delta, cash_flow=cash_flow)
            # Daily broker history does not establish aligned 21:30 marks.
            # Preserve its observations without pretending the residual is zero.
            result.update({"book": account.account_id, "user_id": uid, "day": str(day),
                           "equity_observed_usd": acct.equity, "observed_at": now.isoformat(),
                           "unrealized_observed_usd": mark, "closing_marks_aligned": aligned,
                           "daytrade_count": acct.daytrade_count,
                           "portfolio_history": {key: history.get(key) for key in
                               ("timestamp", "equity", "profit_loss", "profit_loss_pct", "base_value")}
                               if isinstance(history, dict) else None,
                           "receipt_window_after": since})
            if not isinstance(history, dict):
                result["status"] = "partial"
                result.setdefault("issues", []).append("portfolio_history_unavailable")
            else:
                try:
                    points = [(num(t), num(e)) for t, e in zip(history["timestamp"], history["equity"])]
                    if len(points) >= 2:
                        result["portfolio_history_comparison"] = {
                            "from_timestamp": points[-2][0], "to_timestamp": points[-1][0],
                            "equity_delta_usd": points[-1][1]-points[-2][1],
                            "less_known_net_usd": points[-1][1]-points[-2][1]-(result.get("totals") or {}).get("net_pnl_usd", 0),
                            "aligned_with_receipt_window": False}
                except (KeyError, TypeError, ValueError):
                    result.setdefault("issues", []).append("portfolio_history_malformed")
                    result["status"] = "partial"
            return result
        except Exception:
            return unknown("broker_inventory_or_attribution_unverified")


def markdown(report, book, day):
    lines = [f"# {book} — {day}", "", f"Status: {report['status']}",
             "", "FIFO realized order-pair matches; fees labeled below. This is not a profitability guarantee.",
             "", "| Lane | Trades | Day trades | Gross USD | Fees USD | Net USD |",
             "|---|---:|---:|---:|---:|---:|"]
    for lane, m in report.get("lanes", {}).items():
        lines.append(f"| {lane.replace('|', '/')} | {m['trades']} | {m['day_trades']} | {m['gross_pnl_usd']:.4f} | {m['fees_usd']:.4f} | {m['net_pnl_usd']:.4f} |")
    lines += ["", "Measured spread: unknown (FILL receipts have no bid/ask).",
              "Unexplained difference: " + str(report.get("unexplained_usd") if report.get("unexplained_usd") is not None else "unknown; aligned marks/cash flows unavailable"),
              "", "Full scorecard and evidence metadata:", "", "```json", json.dumps(report, indent=2, allow_nan=False), "```", ""]
    return "\n".join(lines)


async def run_nightly(day=None, *, report_dir=None, now=None):
    from app.brokers.accounts import load_accounts
    from app.runtime.settings import _supabase
    from app.agents.base import AgentMessage
    now = now or datetime.now(timezone.utc)
    day = date.fromisoformat(str(day or now.astimezone(ET).date())).isoformat()
    folder = Path(report_dir or os.getenv("TREZO_PNL_REPORT_DIR", r"C:\Trezo\reports"))
    client = _supabase()
    messages = []
    for account in load_accounts():
        uid = str(account.user_id)
        try:
            report = await collect_book(account, day, client=client, now=now) if client else unknown("database_unavailable")
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"pnl-{account.account_id}-{day}.md"
            path.write_text(markdown(report, account.account_id, day), encoding="utf-8")
            totals = report.get("totals") or {}
            metric_names = ("trades", "day_trades", "win_rate", "average_win", "average_loss",
                            "profit_factor", "expectancy", "gross_pnl_usd", "fees_usd",
                            "net_pnl_usd", "friction_share_of_equity")
            row = {"user_id": uid, "day": day, "status": report["status"],
                   "lanes": report.get("lanes", {}), "report": report,
                   "unexplained_usd": report.get("unexplained_usd"),
                   "generated_at": now.isoformat(), **{k: totals.get(k) for k in metric_names}}
            if client is None:
                raise ValueError("database unavailable")
            saved = await asyncio.to_thread(lambda: client.table("book_daily_pnl").upsert(row, on_conflict="user_id,day").execute())
            if not getattr(saved, "data", None):
                raise ValueError("scorecard write unconfirmed")
            status = report["status"]
        except Exception:
            status = "unknown"
        messages.append(AgentMessage(agent="market_desk", kind="info", payload={
            "event": "receipt_pnl", "user_id": uid, "day": day, "status": status}))
    return messages


async def _publish_nightly():
    from app.runtime.bus import bus
    for message in await run_nightly():
        await bus.publish(message)


def schedule_receipt_pnl(scheduler):
    scheduler.add_job(_publish_nightly, trigger="cron", hour=21, minute=30,
                      timezone="America/New_York", id="receipt_pnl:nightly",
                      replace_existing=True, coalesce=True, max_instances=1,
                      misfire_grace_time=300)


_MORNING_SEEN = set()


async def morning_scorecards(now=None):
    from app.runtime.settings import _supabase
    from app.brokers.accounts import load_accounts
    from app.agents.base import AgentMessage
    now = now or datetime.now(timezone.utc)
    day = (now.astimezone(ET).date()-timedelta(days=1)).isoformat()
    _MORNING_SEEN.intersection_update(k for k in list(_MORNING_SEEN) if k[1] == day)
    messages = []
    client = _supabase()
    if client is None:
        return messages
    for book in load_accounts():
        key = (str(book.user_id), day)
        if key in _MORNING_SEEN:
            continue
        try:
            rows = (await asyncio.to_thread(lambda: client.table("book_daily_pnl")
                    .select("status,lanes,net_pnl_usd,unexplained_usd")
                    .eq("user_id", key[0]).eq("day", day).limit(1).execute())).data
            if rows:
                messages.append(AgentMessage(agent="market_desk", kind="info", payload={
                    "event": "receipt_pnl_scorecard", "user_id": key[0], "day": day, **rows[0]}))
                _MORNING_SEEN.add(key)
        except Exception:
            pass
    return messages
