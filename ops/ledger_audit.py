#!/usr/bin/env python3
"""Read-only, stdlib crypto audit. Python 3.10+. No orders or database writes.

python ops/ledger_audit.py --since 2026-07-24
python ops/ledger_audit.py --input broker_export.json
python ops/ledger_audit.py --selftest

Input schema: {"books": [{"label": "primary", "fills": [...],
"positions": [...], "activities": [...], "history_complete": true}]}
Fills use Alpaca's activity schema, including id and order_id. Offline crypto
fills must have asset_class=crypto or slash-form USD pairs. Supply ALL fills,
not just those after --since. This date filters completed entry-order lots.
Fee-in-kind, missing basis, transfers, failed reads and position mismatches
block statistical verdicts. Their resolution is never guessed.

PASS is an exploratory paper-evidence screen, not proof of live profitability.
Minimum 50 fully closed entry orders and 10 closing UTC dates; resample whole
closing dates to reduce within-day dependence. Not multiple-testing adjusted.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ALPACA = "https://paper-api.alpaca.markets"
DATA = "https://data.alpaca.markets"
BOOKS = [("primary", ""), ("book2_25k", "_2"), ("book3_75k", "_3")]
ZERO = Decimal(0)
EPS = Decimal("0.000000001")


class AuditError(Exception):
    """Only sanitized, fixed diagnostic strings belong in this exception."""


def number(value):
    try:
        n = Decimal(str(value))
        if n.is_finite():
            return n
    except (InvalidOperation, ValueError, TypeError):
        pass
    raise AuditError("Missing or non-finite numeric data")


def stamp(value):
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if t.tzinfo is None:
            raise ValueError
        return t.astimezone(dt.timezone.utc)
    except (ValueError, TypeError):
        raise AuditError("Missing or invalid timezone-aware timestamp") from None


def date_arg(value):
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD") from None


def load_env(path=None):
    explicit = path or os.environ.get("TREZO_ENV")
    candidates = [Path(explicit)] if explicit else [
        Path(__file__).resolve().parents[1] / "agents" / ".env",
        Path.cwd() / "agents" / ".env", Path.cwd() / ".env",
        Path(r"C:\Trezo\trezo-platform\agents\.env")]
    env = {}
    found = next((p for p in candidates if p.is_file()), None)
    if explicit and not found:
        raise AuditError("Explicit env file not found")
    if found:
        for line in found.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if value[:1] in ("'", '"'):
                quote = value[0]
                end = value.find(quote, 1)
                if end < 0:
                    raise AuditError("Unterminated quoted env value")
                value = value[1:end]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
            env[key.strip()] = value
    env.update(os.environ)  # hosted secrets work without any file
    return env


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # never forward authentication to another host


def request(url, headers):
    opener = urllib.request.build_opener(NoRedirect)
    for attempt in range(3):
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=25) as r:
                return json.loads(r.read().decode()), dict(r.headers)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1 + attempt)
                continue
            raise AuditError("HTTP %d" % exc.code) from None
        except (OSError, ValueError):
            raise AuditError("Network, TLS or invalid JSON response") from None
    raise AuditError("Retry limit reached")


def activities(headers, max_pages=2000):
    rows, token, seen = [], None, set()
    for _ in range(max_pages):
        query = {"direction": "asc", "page_size": 100}
        if token:
            query["page_token"] = token
        page, _ = request(ALPACA + "/v2/account/activities?" + urllib.parse.urlencode(query), headers)
        if not isinstance(page, list):
            raise AuditError("Activities response is not a list")
        if not page:
            return rows
        for row in page:
            identity = row.get("id")
            if not identity or identity in seen:
                raise AuditError("Missing or repeated activity id; pagination incomplete")
            seen.add(identity)
        rows.extend(page)
        token = page[-1]["id"]
        # Continue to an empty page; do not assume server page size.
    raise AuditError("Activity page limit reached; report would be truncated")


def canonical(symbol):
    return str(symbol or "").upper().replace("/", "").replace(" ", "")


def fifo(fills, crypto_symbols):
    """FIFO matched realizations, counted once per fully closed entry order.

    Shorts are rejected: Alpaca spot crypto does not support them. Separate
    orders retain separate lots; partial fills of one entry order count once.
    """
    lots = collections.defaultdict(collections.deque)
    orders, issues, seen = {}, [], set()
    matched = []
    for f in sorted(fills, key=lambda x: (stamp(x["transaction_time"]), str(x.get("id", "")))):
        sym = canonical(f.get("symbol"))
        if sym not in crypto_symbols:
            continue
        if not sym.endswith("USD"):
            issues.append("Non-USD crypto pair is unsupported")
            continue
        identity, oid = f.get("id"), f.get("order_id")
        if not identity or not oid:
            raise AuditError("Fill id and order_id are required")
        if identity in seen:
            raise AuditError("Duplicate fill id")
        seen.add(identity)
        qty, px = number(f.get("qty")), number(f.get("price"))
        if qty <= 0 or px <= 0 or f.get("side") not in ("buy", "sell"):
            raise AuditError("Invalid fill quantity, price or side")
        if f["side"] == "buy":
            key = (sym, oid)
            rec = orders.setdefault(key, {"symbol": sym, "order_id": oid,
                "opened_at": f["transaction_time"], "closed_at": None,
                "qty": ZERO, "closed_qty": ZERO, "pnl": ZERO,
                "entry_notional": ZERO, "exit_notional": ZERO})
            rec["qty"] += qty
            lots[sym].append({"qty": qty, "px": px, "order": key})
            continue
        left = qty
        while left > EPS and lots[sym]:
            lot = lots[sym][0]
            take = min(left, lot["qty"])
            rec = orders[lot["order"]]
            gross = take * (px - lot["px"])
            rec["pnl"] += gross
            rec["entry_notional"] += take * lot["px"]
            rec["exit_notional"] += take * px
            rec["closed_qty"] += take
            rec["closed_at"] = f["transaction_time"]
            matched.append({"symbol": sym, "closed_at": f["transaction_time"],
                "pnl": gross, "entry_notional": take * lot["px"], "exit_notional": take * px})
            lot["qty"] -= take
            left -= take
            if lot["qty"] <= EPS:
                lots[sym].popleft()
        if left > EPS:
            issues.append("Unmatched crypto sale: missing basis or inventory event")
    completed = [r for r in orders.values() if r["qty"] - r["closed_qty"] <= EPS]
    completed.sort(key=lambda r: stamp(r["closed_at"]))
    inventory = {s: sum((v["qty"] for v in q), ZERO) for s, q in lots.items()}
    return completed, matched, inventory, sorted(set(issues))


def drawdown(values, baseline=None):
    peak = baseline
    dollar, percent = 0.0, 0.0
    for value in values:
        v = float(value)
        peak = v if peak is None else max(peak, v)
        dollar = min(dollar, v - peak)
        if peak > 0:
            percent = min(percent, (v - peak) / peak * 100)
    return {"usd": round(dollar, 2), "pct": round(percent, 4) if baseline is None else None}


def stats(trades, fee_bps=25, slip_bps=5, complete=True):
    rate = (number(fee_bps) + number(slip_bps)) / 10000
    xs = [float(t["pnl"] - rate * (t["entry_notional"] + t["exit_notional"])) for t in trades]
    days = collections.defaultdict(list)
    for t, pnl in zip(trades, xs):
        days[stamp(t["closed_at"]).date().isoformat()].append(pnl)
    blocks = [(sum(v), len(v)) for v in days.values()]
    ci = None
    if len(blocks) >= 2:
        rng, means = random.Random(7), []
        for _ in range(3000):
            picked = rng.choices(blocks, k=len(blocks))
            means.append(sum(v[0] for v in picked) / sum(v[1] for v in picked))
        means.sort()
        ci = [means[75], means[2924]]
    verdict = "INCOMPLETE" if not complete else "INSUFFICIENT"
    if complete and len(xs) >= 50 and len(days) >= 10:
        verdict = "PASS" if ci and ci[0] > 0 else "FAIL"
    wins, losses = sum(x for x in xs if x > 0), -sum(x for x in xs if x < 0)
    curve, acc = [0.0], 0.0
    for x in xs:
        acc += x
        curve.append(acc)
    return {"n_completed_entry_orders": len(xs), "closing_days": len(days),
        "gross_usd": round(sum(float(t["pnl"]) for t in trades), 2),
        "modeled_net_usd": round(sum(xs), 2), "expectancy_usd": round(sum(xs)/len(xs), 4) if xs else None,
        "win_rate_pct": round(sum(x > 0 for x in xs)/len(xs)*100, 2) if xs else None,
        "profit_factor": round(wins/losses, 4) if losses else None,
        "no_losses": bool(xs) and losses == 0,
        "ci95_day_cluster": [round(x, 6) for x in ci] if ci else None,
        "closed_order_drawdown": drawdown(curve, baseline=0), "verdict": verdict}


def audit_book(book, since, fee_bps=25, slip_bps=5):
    fills = book.get("fills", [])
    symbols = {canonical(s) for s in book.get("crypto_symbols", [])}
    symbols.update(canonical(f.get("symbol")) for f in fills if
        f.get("asset_class") == "crypto" or "/USD" in str(f.get("symbol", "")))
    trades, matched, inventory, issues = fifo(fills, symbols)
    if not book.get("history_complete"):
        issues.append("Complete account-lifetime activity coverage is not confirmed")
    if "positions" not in book or not isinstance(book["positions"], list):
        issues.append("Broker position snapshot unavailable")
    else:
        current = {canonical(p.get("symbol")): number(p["qty"]) for p in book["positions"]
                   if p.get("asset_class") == "crypto" or canonical(p.get("symbol")) in symbols}
        for sym in set(inventory) | set(current):
            if abs(inventory.get(sym, ZERO) - current.get(sym, ZERO)) > EPS:
                issues.append("Fill inventory differs from broker: " + sym)
    for a in book.get("activities", []):
        typ = a.get("activity_type")
        if typ == "CFEE" and number(a.get("qty", 0)) != 0:
            issues.append("Crypto fees paid in coins require receipt-level basis reconciliation")
        if typ in ("ACATS", "JNLS", "FOPT", "SSP", "REORG") and canonical(a.get("symbol")) in symbols:
            issues.append("Crypto inventory adjustment requires reconciliation")
    cutoff = stamp(since + "T00:00:00Z")
    selected = [t for t in trades if stamp(t["closed_at"]) >= cutoff]
    realized = [t for t in matched if stamp(t["closed_at"]) >= cutoff]
    rate = (number(fee_bps) + number(slip_bps)) / 10000
    summary = stats(selected, fee_bps, slip_bps, complete=not issues)
    return {"label": book.get("label", "unknown"), "source": "Alpaca paper fills; modeled costs",
        "account_snapshot_all_assets": book.get("account_snapshot_all_assets"),
        "issues": sorted(set(issues)), "fills": len(fills), "summary": summary,
        "matched_realizations_since": {"gross_usd": round(sum(float(t["pnl"]) for t in realized), 2),
            "modeled_net_usd": round(sum(float(t["pnl"] - rate*(t["entry_notional"]+t["exit_notional"])) for t in realized), 2)},
        "open_fill_inventory": {s: str(q) for s, q in inventory.items() if q},
        "by_symbol": {s: stats([t for t in selected if t["symbol"] == s], fee_bps, slip_bps, not issues)
                      for s in sorted({t["symbol"] for t in selected})},
        "note": "FAIL means the positive-edge screen was not met; it does not necessarily mean losses. "
                "Partial entry-order realizations appear in matched totals but not the sample. "
                "Closed-order drawdown is not portfolio drawdown. Coin fees and inventory gaps block verdicts."}


def ledger_summary(rows):
    """Ledger values may already include fees. Never subtract them twice.

    This is a direction-only view, separate from broker samples and verdicts.
    """
    groups = {}
    seen = set()
    for row in rows:
        if row.get("asset_type") != "crypto" or not str(row.get("status", "")).startswith("closed"):
            continue
        if not row.get("id") or row["id"] in seen:
            raise AuditError("Missing or duplicated ledger row id")
        seen.add(row["id"])
        book = str(row.get("user_id") or "unattributed")
        strategy = str(row.get("strategy") or "unknown")
        key = (book, strategy)
        g = groups.setdefault(key, {"book": book, "strategy": strategy,
             "rows": 0, "missing_pnl": 0, "reported_realized_usd": ZERO, "reported_fees_usd": ZERO})
        g["rows"] += 1
        if row.get("realized_pnl_usd") is None:
            g["missing_pnl"] += 1
        else:
            g["reported_realized_usd"] += number(row["realized_pnl_usd"])
        g["reported_fees_usd"] += number(row.get("fees_usd") or 0)
    return [{**g, "reported_realized_usd": float(g["reported_realized_usd"]),
             "reported_fees_usd": float(g["reported_fees_usd"])} for g in groups.values()]


def fetch_ledger(env, since):
    url = env.get("SUPABASE_URL", "").rstrip("/")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return {"status": "UNAVAILABLE", "reason": "Supabase URL/service key absent"}
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise AuditError("Invalid Supabase HTTPS origin")
    headers = {"apikey": key, "Authorization": "Bearer " + key,
               "Prefer": "count=exact", "Range-Unit": "items"}
    params = {"asset_type": "eq.crypto", "status": "like.closed*", "exit_at": "gte." + since + "T00:00:00Z",
              "select": "id,user_id,strategy,asset_type,status,realized_pnl_usd,fees_usd,exit_at",
              "order": "exit_at.asc,id.asc"}
    rows = []
    for _ in range(1000):
        h = {**headers, "Range": "%d-%d" % (len(rows), len(rows)+999)}
        page, meta = request(url + "/rest/v1/paper_positions?" + urllib.parse.urlencode(params), h)
        if not isinstance(page, list):
            raise AuditError("Invalid ledger response")
        content_range = next((v for k,v in meta.items() if k.lower() == "content-range"), "")
        try:
            total = int(content_range.split("/")[-1])
        except ValueError:
            raise AuditError("Ledger pagination total unavailable") from None
        rows.extend(page)
        if len(rows) >= total:
            return {"status": "DIRECTION_ONLY", "by_book_strategy": ledger_summary(rows),
                    "note": "Not reconciled to broker fills. Row counts include partial closes. No edge verdict."}
        if not page:
            raise AuditError("Ledger ended before reported total")
    raise AuditError("Ledger page cap reached")


def fetch_book(env, label, suffix):
    key, secret = env.get("ALPACA_API_KEY" + suffix), env.get("ALPACA_SECRET_KEY" + suffix)
    if not key or not secret:
        raise AuditError("Both Alpaca paper key and secret are required for this book")
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    account, _ = request(ALPACA + "/v2/account", headers)
    if not isinstance(account, dict) or not account.get("id"):
        raise AuditError("Invalid broker account response")
    assets, _ = request(ALPACA + "/v2/assets?asset_class=crypto", headers)
    if not isinstance(assets, list):
        raise AuditError("Crypto asset registry unavailable")
    all_rows = activities(headers)
    positions, _ = request(ALPACA + "/v2/positions", headers)
    if not isinstance(positions, list):
        raise AuditError("Broker positions unavailable")
    return {"label": label, "account_identity": account["id"],
        "account_snapshot_all_assets": {k: account.get(k) for k in
            ("equity", "cash", "last_equity", "non_marginable_buying_power", "trading_blocked")},
        "crypto_symbols": [a["symbol"] for a in assets],
        "fills": [r for r in all_rows if r.get("activity_type") == "FILL"],
        "activities": [r for r in all_rows if r.get("activity_type") != "FILL"],
        "positions": positions, "history_complete": True}


def collect(env, since, fee_bps=25, slip_bps=5):
    out, ids = [], set()
    for label, suffix in BOOKS:
        try:
            book = fetch_book(env, label, suffix)
            if book["account_identity"] in ids:
                raise AuditError("Duplicate broker account mapping")
            ids.add(book["account_identity"])
            out.append(audit_book(book, since, fee_bps, slip_bps))
        except (AuditError, KeyError, TypeError, ValueError) as exc:
            message = str(exc) if isinstance(exc, AuditError) else "Invalid broker data schema"
            out.append({"label": label, "error": message, "summary": {"verdict": "INCOMPLETE"}})
    return out


def print_report(out):
    print("TREZO CRYPTO AUDIT — since", out["since"])
    print("Paper executions with modeled fees/slippage; exploratory evidence, not live profit proof.")
    for book in out["books"]:
        s = book["summary"]
        print("%s: %s | closed entry orders=%s | modeled net=$%s | CI=%s" % (
            book["label"], s["verdict"], s.get("n_completed_entry_orders", "?"),
            s.get("modeled_net_usd", "?"), s.get("ci95_day_cluster")))
        for issue in book.get("issues", []) + ([book["error"]] if book.get("error") else []):
            print("  INCOMPLETE:", issue)


def selftest():
    import importlib.util
    testfile = Path(__file__).resolve().parents[1] / "agents/tests/test_ledger_audit.py"
    if not testfile.is_file():
        # Standalone download still has a meaningful arithmetic smoke test.
        assert drawdown([-10, -20], baseline=0)["usd"] == -20
        assert stats([])["verdict"] == "INSUFFICIENT"
        print("Standalone smoke tests passed; full regression tests ship in the repository.")
        return 0
    spec = importlib.util.spec_from_file_location("audit_selftests", testfile)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in sorted(vars(mod)):
        if name.startswith("test_"):
            getattr(mod, name)()
    print("Crypto audit regression tests passed.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", type=date_arg, default="2026-05-01")
    ap.add_argument("--env")
    ap.add_argument("--input", help="Offline JSON with account-lifetime fills and current positions")
    ap.add_argument("--out", default="ledger_audit.json")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--ledger", action="store_true", help="Also read crypto ledger by book and strategy")
    ap.add_argument("--fee-bps", type=float, default=25, help="ASSUMED per-side fee, not verified actual fees")
    ap.add_argument("--slippage-bps", type=float, default=5, help="Additional per-side stress on recorded fills")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if number(a.fee_bps) < 0 or number(a.slippage_bps) < 0:
        ap.error("Costs must be nonnegative")
    if a.input:
        raw = json.loads(Path(a.input).read_text(encoding="utf-8-sig"))
        books = [audit_book(b, a.since, a.fee_bps, a.slippage_bps) for b in raw["books"]]
    else:
        books = collect(load_env(a.env), a.since, a.fee_bps, a.slippage_bps)
    out = {"schema_version": 2, "since": a.since, "run_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "cost_assumptions": {"fee_bps_per_side": a.fee_bps, "additional_slippage_bps_per_side": a.slippage_bps},
        "books": books}
    if a.ledger:
        try:
            out["ledger"] = fetch_ledger(load_env(a.env), a.since)
        except AuditError as exc:
            out["ledger"] = {"status": "INCOMPLETE", "reason": str(exc)}
    Path(a.out).write_text(json.dumps(out, indent=2, allow_nan=False), encoding="utf-8")
    print_report(out)
    print("JSON:", Path(a.out).resolve())
    return 2 if not books or any(b["summary"]["verdict"] == "INCOMPLETE" for b in books) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AuditError, OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc) if isinstance(exc, AuditError) else "Audit failed: input/file schema or I/O error", file=sys.stderr)
        sys.exit(2)
