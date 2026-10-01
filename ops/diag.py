"""Trezo live diagnostic: is the engine up, can the agents reach what they need,
and what did the three books actually do (from broker receipts, not the ledger).

Read-only. Never prints a key (values from the .env are redacted from output).
Stdlib only, so it runs with any Python 3.9+ on the server or in a sandbox.

  python ops/diag.py                       # needs $TREZO_ENV (or finds agents/.env)
  python ops/diag.py --server              # also asks the engine on localhost:8001
                                           # and reads logs/activity-*.jsonl
  python ops/diag.py --server --out C:\\Trezo\\reports\\diag.txt --discord
                                           # write the full report; post the
                                           # compact verdict to the alert webhook

Sections: ENGINE (Supabase evidence), BROKER (each book at Alpaca), RECEIPT
P&L (FIFO round trips from FILL activities), PROVIDERS (every key the agents
use, probed with that key), SERVER (localhost endpoints, nssm, activity log).
The VERDICT block at the top is what to paste back to Nova.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001  (tzdata missing on a bare Windows python)
    ET = timezone(timedelta(hours=-4))

NOW = datetime.now(timezone.utc)

BOOKS = [
    ("primary", "cf1b0460-039d-40ac-adc8-7ca3ef17c5bb", "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_BASE_URL"),
    ("25k", "6ce61054-7ffd-41b5-80c3-1cd0220c79eb", "ALPACA_API_KEY_2", "ALPACA_SECRET_KEY_2", "ALPACA_BASE_URL_2"),
    ("75k", "49acafdd-1c86-4740-a1b1-f94aa7abce08", "ALPACA_API_KEY_3", "ALPACA_SECRET_KEY_3", "ALPACA_BASE_URL_3"),
]
NAMES = {b[1]: b[0] for b in BOOKS}
CAP_COLS = ("day_options_enabled", "spreads_enabled", "long_options_enabled",
            "dividend_lt_enabled", "reevaluation_enabled", "crypto_reevaluation_enabled",
            "goal_lock_enabled")

OUT = io.StringIO()
VERDICT: list[str] = []
SECRETS: list[str] = []


def say(*parts):
    line = " ".join(str(p) for p in parts)
    for s in SECRETS:
        if s and s in line:
            line = line.replace(s, "***")
    print(line)
    OUT.write(line + "\n")


def verdict(line):
    VERDICT.append(line)


# ------------------------------------------------------------------ helpers
def find_env() -> str:
    cands = [os.environ.get("TREZO_ENV", "")]
    here = os.path.dirname(os.path.abspath(__file__))
    cands.append(os.path.join(here, "..", "agents", ".env"))
    cands.append(r"C:\Trezo\trezo-platform\agents\.env")
    for c in cands:
        if c and os.path.exists(c):
            return c
    raise SystemExit("could not find agents/.env -- set TREZO_ENV=/path/to/.env")


def load_env(path: str) -> dict:
    env = {}
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")  # last duplicate wins
    for k, v in env.items():
        if v and len(v) >= 12 and ("KEY" in k or "SECRET" in k or "TOKEN" in k or "WEBHOOK" in k or "PASSWORD" in k):
            SECRETS.append(v)
    return env


def http(url, headers=None, method="GET", data=None, timeout=25):
    hdrs = {"User-Agent": "TrezoDiag/1.0 (+https://github.com/aynvmike/trezo-platform)"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, headers=hdrs, method=method, data=data)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            try:
                return r.status, json.loads(body.decode() or "null"), round(time.time() - t0, 2)
            except ValueError:
                return r.status, body.decode(errors="replace")[:300], round(time.time() - t0, 2)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode(errors="replace")[:300]
        except Exception:  # noqa: BLE001
            body = ""
        return e.code, body, round(time.time() - t0, 2)
    except Exception as e:  # noqa: BLE001
        return 0, "%s: %s" % (type(e).__name__, str(e)[:200]), round(time.time() - t0, 2)


def parse_ts(ts):
    t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def age(ts) -> str:
    if not ts:
        return "never"
    try:
        s = (NOW - parse_ts(ts)).total_seconds()
        if s < 3600:
            return "%dm ago" % round(s / 60)
        if s < 86400 * 2:
            return "%.1fh ago" % (s / 3600)
        return "%.1fd ago" % (s / 86400)
    except Exception:  # noqa: BLE001
        return "?(%s)" % ts


def fnum(v, nd=2):
    try:
        return ("%%+.%df" % nd) % float(v)
    except Exception:  # noqa: BLE001
        return str(v)


# ----------------------------------------------------------------- Supabase
class SB:
    def __init__(self, env):
        self.url = env.get("SUPABASE_URL", "").rstrip("/")
        key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self.h = {"apikey": key, "Authorization": "Bearer " + key, "Accept": "application/json"}
        self.ok = bool(self.url and key)

    def get(self, table, query, limit=None):
        q = query + ("&limit=%d" % limit if limit else "")
        return http("%s/rest/v1/%s?%s" % (self.url, table, q), self.h)


def section_engine(sb: SB, since_iso: str):
    say("\n## ENGINE (Supabase evidence)")
    code, rows, dt = sb.get("ops_log_tail", "select=ts,host,line&line->>event=eq.engine_boot&order=ts.desc", 8)
    if code != 200 or not isinstance(rows, list):
        say("  engine_boot beacons: HTTP %s %s" % (code, str(rows)[:160]))
        verdict("beacon: UNREADABLE (HTTP %s)" % code)
    else:
        say("  engine_boot beacons (newest first):")
        for r in rows:
            line = r.get("line") or {}
            commit = line.get("commit") or line.get("sha") or line.get("git") or "?"
            rest = {k: v for k, v in line.items() if k not in ("event", "commit", "sha", "git", "ts")}
            say("    %sZ %9s host=%s commit=%s %s" % (r["ts"][:19], age(r["ts"]), r.get("host"), commit, str(rest)[:160]))
        if rows:
            line = rows[0].get("line") or {}
            verdict("last engine boot: %s (%s) commit=%s" % (rows[0]["ts"][:16] + "Z", age(rows[0]["ts"]),
                    line.get("commit") or line.get("sha") or line.get("git") or "?"))
    code, rows, dt = sb.get("ops_log_tail", "select=ts,line&order=ts.desc", 12)
    if code == 200 and isinstance(rows, list) and rows:
        say("  ops_log_tail newest line: %sZ (%s) event=%s" % (rows[0]["ts"][:19], age(rows[0]["ts"]), (rows[0].get("line") or {}).get("event")))
        say("    recent events: " + ", ".join(str((r.get("line") or {}).get("event")) for r in rows))
        verdict("engine log push: %s" % age(rows[0]["ts"]))
    code, rows, dt = sb.get("paper_accounts", "select=user_id,updated_at,current_cash_usd,trading_halted,today_realized_pnl_usd,last_reset_date,consecutive_losses&order=updated_at.desc", 10)
    if code != 200 or not isinstance(rows, list):
        say("  paper_accounts: HTTP %s %s" % (code, str(rows)[:200]))
        verdict("heartbeat: UNREADABLE")
    else:
        say("  paper_accounts heartbeat:")
        hb = []
        for r in rows:
            n = NAMES.get(r["user_id"], r["user_id"][:8])
            say("    %8s updated %9s cash=%s halted=%s today_realized=%s reset=%s consec_losses=%s" % (
                n, age(r["updated_at"]), r.get("current_cash_usd"), r.get("trading_halted"),
                r.get("today_realized_pnl_usd"), r.get("last_reset_date"), r.get("consecutive_losses")))
            hb.append("%s %s%s" % (n, age(r["updated_at"]), " HALTED" if r.get("trading_halted") else ""))
        verdict("heartbeat: " + "; ".join(hb))
    code, rows, dt = sb.get("agent_messages", "select=created_at,agent_name,kind&order=created_at.desc", 2000)
    if code == 200 and isinstance(rows, list) and rows:
        say("  agent_messages newest: %sZ (%s) from %s" % (rows[0]["created_at"][:19], age(rows[0]["created_at"]), rows[0].get("agent_name")))
        last, kinds = {}, defaultdict(int)
        for r in rows:
            a = r.get("agent_name") or "?"
            last.setdefault(a, r["created_at"])
            kinds[(a, r.get("kind"))] += 1
        say("  per-agent newest message (sample of %d msgs back to %sZ):" % (len(rows), rows[-1]["created_at"][:19]))
        for a, ts in sorted(last.items(), key=lambda kv: kv[1], reverse=True):
            ks = ", ".join("%s=%d" % (k, n) for (aa, k), n in sorted(kinds.items()) if aa == a)
            say("    %-26s %9s  %s" % (a, age(ts), ks))
        errs = sum(n for (a, k), n in kinds.items() if k == "error")
        verdict("bus: newest msg %s; %d agents seen in last %d msgs; error msgs=%d" % (age(rows[0]["created_at"]), len(last), len(rows), errs))
    else:
        say("  agent_messages: HTTP %s %s" % (code, str(rows)[:120]))
    code, rows, dt = sb.get("ops_health_alerts", "select=alert_kind,target_name,severity,message,raised_at&order=raised_at.desc", 60)
    if code == 200 and isinstance(rows, list):
        cutoff = NOW - timedelta(days=7)
        recent = [r for r in rows if parse_ts(r["raised_at"]) >= cutoff]
        say("  ops_health_alerts last 7d: %d (of newest 60)" % len(recent))
        for r in recent[:20]:
            say("    %sZ %5s %-18s %-18s %s" % (r["raised_at"][:16], r["severity"], r["alert_kind"], str(r.get("target_name"))[:18], str(r.get("message"))[:120]))
        kinds = defaultdict(int)
        for r in recent:
            kinds[r["alert_kind"]] += 1
        verdict("health alerts 7d: %d %s" % (len(recent), dict(kinds) if kinds else ""))
    else:
        say("  ops_health_alerts: HTTP %s %s" % (code, str(rows)[:120]))
    code, rows, dt = sb.get("bot_settings", "select=*", 10)
    if code == 200 and isinstance(rows, list):
        cols = set()
        for r in rows:
            cols.update(r.keys())
        present = [c for c in CAP_COLS if c in cols]
        say("  bot_settings rows=%d capability columns present: %s" % (len(rows), present))
        flags = [c for c in sorted(cols) if c.endswith("_enabled")]
        vb = []
        for r in rows:
            uid = str(r.get("user_id"))
            n = NAMES.get(uid, uid[:8])
            on = [f.replace("_enabled", "") for f in flags if r.get(f) is True]
            off = [f.replace("_enabled", "") for f in flags if r.get(f) is False]
            say("    %8s tcs=%s max_open=%s rr=%s autonomy=%s auto_trade=%s" % (n, r.get("tcs_threshold"), r.get("max_open_positions"), r.get("min_reward_risk"), r.get("autonomy_mode"), r.get("auto_trade_enabled")))
            say("             ON : %s" % on)
            say("             OFF: %s" % off)
            vb.append("%s off=%s" % (n, off))
        verdict("PR#3 migration applied: %s (cap cols %d/6); PR#4: %s" % (
            "YES" if "day_options_enabled" in cols else "NO", len([c for c in CAP_COLS[:6] if c in cols]),
            "YES" if "goal_lock_enabled" in cols else "NO"))
        verdict("lanes " + " | ".join(vb))
    else:
        say("  bot_settings: HTTP %s %s" % (code, str(rows)[:160]))
    code, rows, dt = sb.get("ops_tasks", "select=id,kind,status,created_at,finished_at,args,result&order=created_at.desc", 8)
    if code == 200 and isinstance(rows, list):
        say("  ops_tasks newest:")
        for r in rows:
            res = str(r.get("result") or "")
            flag = " ROLLED BACK" if "ROLLED BACK" in res else (" NOT restarted" if "NOT restarted" in res else "")
            say("    %sZ %-18s %-9s %s%s" % (r["created_at"][:16], r["kind"], r["status"], str(r.get("args"))[:70], flag))
        if rows:
            verdict("relay: last job %s %s %s (%s)" % (rows[0]["kind"], rows[0]["status"], age(rows[0]["created_at"]),
                    ("ROLLED BACK" if "ROLLED BACK" in str(rows[0].get("result")) else "ok")))
    else:
        say("  ops_tasks: HTTP %s %s" % (code, str(rows)[:120]))
    code, rows, dt = sb.get("paper_positions", "select=user_id,ticker,asset_type,strategy,side,quantity,entry_price,entry_at,status&status=eq.open&order=entry_at.desc", 200)
    if code == 200 and isinstance(rows, list):
        by = defaultdict(list)
        for r in rows:
            by[NAMES.get(str(r["user_id"]), str(r["user_id"])[:8])].append(r)
        say("  open paper_positions: %d" % len(rows))
        for b, rs in by.items():
            say("    %s: %s" % (b, ", ".join("%s(%s/%s, %s)" % (r["ticker"], str(r["asset_type"])[:1], str(r.get("strategy"))[:12], age(r["entry_at"])) for r in rs)))
        verdict("open ledger rows: " + ", ".join("%s=%d" % (b, len(rs)) for b, rs in by.items()) if by else "open ledger rows: none")
    else:
        say("  paper_positions open: HTTP %s %s" % (code, str(rows)[:120]))
    code, rows, dt = sb.get("paper_positions", "select=user_id,ticker,asset_type,strategy,side,quantity,entry_price,exit_price,entry_at,exit_at,status,realized_pnl_usd,fees_usd,source_payload&status=like.closed*&exit_at=gte.%s&order=exit_at.desc" % since_iso, 2000)
    if code == 200 and isinstance(rows, list):
        say("  ledger closes since %s: %d" % (since_iso[:10], len(rows)))
        agg = defaultdict(lambda: [0, 0.0, 0.0, 0, 0])
        src = defaultdict(int)
        byday = defaultdict(lambda: defaultdict(float))
        for r in rows:
            b = NAMES.get(str(r["user_id"]), str(r["user_id"])[:8])
            pnl = float(r.get("realized_pnl_usd") or 0)
            a = agg[(b, r["asset_type"])]
            a[0] += 1
            a[1] += pnl
            a[2] += float(r.get("fees_usd") or 0)
            a[3] += pnl > 0
            a[4] += pnl < 0
            sp = r.get("source_payload") or {}
            if isinstance(sp, str):
                try:
                    sp = json.loads(sp)
                except ValueError:
                    sp = {}
            src[(b, sp.get("exit_price_source") or r["status"])] += 1
            byday[parse_ts(r["exit_at"]).astimezone(ET).date().isoformat()][b] += pnl
        vb = []
        for (b, at), a in sorted(agg.items()):
            say("    %8s %-7s n=%-4d wins=%-3d losses=%-3d realized=%s fees=%.2f" % (b, at, a[0], a[3], a[4], fnum(a[1]), a[2]))
            vb.append("%s/%s n=%d %s" % (b, at[:1], a[0], fnum(a[1])))
        say("    exit provenance: " + ", ".join("%s/%s=%d" % (b, s, n) for (b, s), n in sorted(src.items())))
        say("    ledger realized by ET day:")
        for d in sorted(byday):
            say("      %s: %s" % (d, "  ".join("%s=%s" % (b, fnum(v)) for b, v in sorted(byday[d].items()))))
        verdict("ledger closes since %s: %s" % (since_iso[5:10], "; ".join(vb) if vb else "NONE"))
    else:
        say("  paper_positions closed: HTTP %s %s" % (code, str(rows)[:160]))


# ------------------------------------------------------------------- Alpaca
def alp_headers(env, k, s):
    return {"APCA-API-KEY-ID": env.get(k, ""), "APCA-API-SECRET-KEY": env.get(s, ""), "Accept": "application/json"}


def alp_get(base, h, path):
    code, body, dt = http(base.rstrip("/") + path, h)
    return code, body


def paged_activities(base, h, atype, after):
    out, token = [], None
    for _ in range(40):
        q = "/v2/account/activities/%s?after=%s&direction=asc&page_size=100%s" % (
            atype, urllib.parse.quote(after), ("&page_token=" + token) if token else "")
        code, body = alp_get(base, h, q)
        if code != 200 or not isinstance(body, list):
            return out, "HTTP %s %s" % (code, str(body)[:120])
        out.extend(body)
        if len(body) < 100:
            break
        token = body[-1].get("id")
    return out, None


def section_broker(env, since_iso):
    say("\n## BROKER (Alpaca, per book)")
    h0 = alp_headers(env, "ALPACA_API_KEY", "ALPACA_SECRET_KEY")
    code, clock = alp_get("https://paper-api.alpaca.markets", h0, "/v2/clock")
    if code == 200 and isinstance(clock, dict):
        say("  clock: open=%s next_open=%s next_close=%s" % (clock.get("is_open"), clock.get("next_open"), clock.get("next_close")))
    else:
        say("  clock: HTTP %s %s" % (code, str(clock)[:120]))
    results = {}
    for name, uid, k, s, b in BOOKS:
        base = env.get(b) or "https://paper-api.alpaca.markets"
        if not env.get(k):
            say("  %s: no key in .env (%s)" % (name, k))
            verdict("%s: NO KEY" % name)
            continue
        h = alp_headers(env, k, s)
        code, acct = alp_get(base, h, "/v2/account")
        if code != 200 or not isinstance(acct, dict):
            say("  %s: /v2/account HTTP %s %s" % (name, code, str(acct)[:160]))
            verdict("%s: broker UNREACHABLE (HTTP %s)" % (name, code))
            continue
        eq, last = float(acct.get("equity") or 0), float(acct.get("last_equity") or 0)
        say("  %8s acct ...%s status=%s equity=%.2f last_eq=%.2f day=%s cash=%.2f bp=%.0f daytrades=%s PDT=%s blocked=%s/%s crypto=%s options_lvl=%s" % (
            name, str(acct.get("account_number"))[-4:], acct.get("status"), eq, last, fnum(eq - last), float(acct.get("cash") or 0),
            float(acct.get("buying_power") or 0), acct.get("daytrade_count"), acct.get("pattern_day_trader"), acct.get("trading_blocked"),
            acct.get("account_blocked"), acct.get("crypto_status"), acct.get("options_trading_level")))
        vline = "%s eq=%.0f day=%s dt=%s pdt=%s" % (name, eq, fnum(eq - last, 0), acct.get("daytrade_count"), acct.get("pattern_day_trader"))
        if acct.get("trading_blocked") or acct.get("account_blocked"):
            vline += " BLOCKED"
        code, pos = alp_get(base, h, "/v2/positions")
        if code == 200 and isinstance(pos, list):
            say("           positions (%d): %s" % (len(pos), ", ".join("%s %s@%.4g upl=%s" % (p["symbol"], p["qty"], float(p["avg_entry_price"]), fnum(p["unrealized_pl"])) for p in pos[:20])))
            vline += " pos=%d upl=%s" % (len(pos), fnum(sum(float(p["unrealized_pl"]) for p in pos)))
        else:
            say("           positions HTTP %s %s" % (code, str(pos)[:100]))
        code, oo = alp_get(base, h, "/v2/orders?status=open&limit=50")
        if code == 200 and isinstance(oo, list):
            say("           open orders (%d): %s" % (len(oo), ", ".join("%s %s %s %s %s" % (o["symbol"], o["side"], o["type"], o.get("qty") or o.get("notional"), o["status"]) for o in oo[:12])))
        code, orders = alp_get(base, h, "/v2/orders?status=all&after=%s&limit=500&direction=asc" % since_iso)
        if code == 200 and isinstance(orders, list):
            st = defaultdict(int)
            for o in orders:
                st[o["status"]] += 1
            say("           orders since %s: %d  %s" % (since_iso[:10], len(orders), ", ".join("%s=%d" % kv for kv in sorted(st.items()))))
            if orders:
                o = orders[-1]
                say("           newest order: %sZ %s %s %s (%s)" % (o["submitted_at"][:19], o["symbol"], o["side"], o["status"], age(o["submitted_at"])))
                vline += " orders=%d(filled=%d) newest=%s" % (len(orders), st.get("filled", 0), age(o["submitted_at"]))
            else:
                vline += " orders=0"
        code, hist = alp_get(base, h, "/v2/account/portfolio/history?period=1M&timeframe=1D")
        if code == 200 and isinstance(hist, dict) and hist.get("timestamp"):
            pts = list(zip(hist["timestamp"], hist["equity"]))[-10:]
            say("           equity by day: " + "  ".join("%s=%.0f" % (datetime.fromtimestamp(t, tz=ET).date().isoformat()[5:], e) for t, e in pts))
            if len(pts) >= 6:
                vline += " eq5d=%s" % fnum(pts[-1][1] - pts[-6][1], 0)
        verdict(vline)
        results[name] = (base, h, acct)
    return results


def fifo_pnl(fills, fees, start, end):
    posted = defaultdict(float)
    for f in fees or []:
        if f.get("order_id"):
            posted[str(f["order_id"])] += -float(f.get("net_amount") or 0)
    ev = []
    for f in fills:
        if f.get("activity_type", "FILL") != "FILL":
            continue
        ev.append((parse_ts(f["transaction_time"]), str(f["id"]), f))
    ev.sort(key=lambda x: (x[0], x[1]))
    oq = defaultdict(float)
    for _, _, f in ev:
        oq[str(f["order_id"])] += float(f["qty"])
    lots, trips = defaultdict(deque), []
    for at, _, f in ev:
        sym = str(f["symbol"]).replace("/", "")
        qty, price = float(f["qty"]), float(f["price"])
        sign = 1 if f["side"] == "buy" else -1
        oid = str(f["order_id"])
        is_opt = len(sym) > 12 and any(c.isdigit() for c in sym)
        is_crypto = (not is_opt) and sym.endswith("USD") and len(sym) <= 8
        fee_each = posted[oid] / oq[oid] if oid in posted else (price * 0.0026 if is_crypto else 0.0)
        fee_src = "posted" if oid in posted else ("model" if is_crypto else "none")
        mult = 100 if is_opt else 1
        q = lots[sym]
        while qty > 1e-10 and q and q[0]["sign"] != sign:
            lot = q[0]
            take = min(qty, lot["qty"])
            if start <= at < end:
                gross = (price - lot["price"]) * lot["sign"] * take * mult
                fee = take * (lot["fee"] + fee_each)
                trips.append({"symbol": sym, "at": at, "entry_at": lot["at"], "gross": gross, "fee": fee, "net": gross - fee,
                              "crypto": is_crypto, "option": is_opt,
                              "day_trade": lot["at"].astimezone(ET).date() == at.astimezone(ET).date(),
                              "fee_src": fee_src, "hold_min": (at - lot["at"]).total_seconds() / 60})
            lot["qty"] -= take
            qty -= take
            if lot["qty"] <= 1e-10:
                q.popleft()
        if qty > 1e-10:
            q.append({"qty": qty, "price": price, "sign": sign, "at": at, "fee": fee_each})
    leftover = {s: sum(l["qty"] * l["sign"] for l in q) for s, q in lots.items() if q}
    return trips, leftover


def section_pnl(env, books, since_iso):
    say("\n## RECEIPT P&L (broker FILL activities, round trips closed since %s)" % since_iso[:10])
    start = parse_ts(since_iso)
    lookback = (start - timedelta(days=21)).isoformat()
    for name, (base, h, acct) in books.items():
        fills, err = paged_activities(base, h, "FILL", lookback)
        if err:
            say("  %s: fills %s" % (name, err))
            verdict("%s receipts: UNREADABLE" % name)
            continue
        fees, ferr = paged_activities(base, h, "FEE", lookback)
        trips, leftover = fifo_pnl(fills, fees if not ferr else [], start, NOW)
        n = len(trips)
        wins = [t for t in trips if t["net"] > 0]
        loss = [t for t in trips if t["net"] < 0]
        gross = sum(t["gross"] for t in trips)
        fee = sum(t["fee"] for t in trips)
        net = gross - fee
        eq = float(acct.get("equity") or 0)
        say("  %8s: fills=%d fee_rows=%s round_trips=%d wins=%d losses=%d gross=%s fees=%.2f net=%s (%s%% of equity)" % (
            name, len(fills), (len(fees) if not ferr else ferr), n, len(wins), len(loss), fnum(gross), fee, fnum(net), fnum(net / eq * 100 if eq else 0)))
        vline = "%s receipts since %s: %d trips %dW/%dL net=%s fees=%.0f" % (name, since_iso[5:10], n, len(wins), len(loss), fnum(net, 0), fee)
        if n:
            dt = [t for t in trips if t["day_trade"]]
            cr = [t for t in trips if t["crypto"]]
            op = [t for t in trips if t["option"]]
            st = [t for t in trips if not t["crypto"] and not t["option"]]
            say("           day-trades=%d net=%s | crypto n=%d net=%s fees=%.2f | options n=%d net=%s | stock n=%d net=%s" % (
                len(dt), fnum(sum(t["net"] for t in dt)), len(cr), fnum(sum(t["net"] for t in cr)), sum(t["fee"] for t in cr),
                len(op), fnum(sum(t["net"] for t in op)), len(st), fnum(sum(t["net"] for t in st))))
            say("           avg win=%s avg loss=%s median hold=%.0fm fee sources=%s" % (
                fnum(sum(t["net"] for t in wins) / len(wins)) if wins else "n/a", fnum(sum(t["net"] for t in loss) / len(loss)) if loss else "n/a",
                sorted(t["hold_min"] for t in trips)[n // 2], {s: sum(1 for t in trips if t["fee_src"] == s) for s in ("posted", "model", "none")}))
            byday = defaultdict(float)
            for t in trips:
                byday[t["at"].astimezone(ET).date().isoformat()] += t["net"]
            say("           net by ET day: " + "  ".join("%s=%s" % (d[5:], fnum(v)) for d, v in sorted(byday.items())))
            bysym = defaultdict(lambda: [0, 0.0])
            for t in trips:
                bysym[t["symbol"]][0] += 1
                bysym[t["symbol"]][1] += t["net"]
            worst = sorted(bysym.items(), key=lambda kv: kv[1][1])[:6]
            best = sorted(bysym.items(), key=lambda kv: -kv[1][1])[:4]
            say("           worst: " + ", ".join("%s n=%d %s" % (s, a[0], fnum(a[1])) for s, a in worst))
            say("           best : " + ", ".join("%s n=%d %s" % (s, a[0], fnum(a[1])) for s, a in best))
            vline += " | crypto %d/%s opt %d/%s stock %d/%s | daytrades %d" % (
                len(cr), fnum(sum(t["net"] for t in cr), 0), len(op), fnum(sum(t["net"] for t in op), 0), len(st), fnum(sum(t["net"] for t in st), 0), len(dt))
        if leftover:
            say("           still-open lots (FIFO): %s" % {k: round(v, 6) for k, v in leftover.items()})
        verdict(vline)


# ---------------------------------------------------------------- providers
def section_providers(env):
    say("\n## PROVIDERS (reachability with the engine's own keys)")
    dh = alp_headers(env, "ALPACA_API_KEY", "ALPACA_SECRET_KEY")
    checks = [
        ("alpaca data: SPY latest trade", "https://data.alpaca.markets/v2/stocks/SPY/trades/latest?feed=iex", dh,
         lambda b: "t=%s (%s)" % (b["trade"]["t"], age(b["trade"]["t"]))),
        ("alpaca data: SPY latest bar", "https://data.alpaca.markets/v2/stocks/SPY/bars/latest?feed=iex", dh,
         lambda b: "t=%s (%s) c=%s" % (b["bar"]["t"], age(b["bar"]["t"]), b["bar"]["c"])),
        ("alpaca data: crypto quotes", "https://data.alpaca.markets/v1beta3/crypto/us/latest/quotes?symbols=BTC/USD,ETH/USD,SOL/USD", dh,
         lambda b: ", ".join("%s bid=%s ask=%s %s" % (k, v["bp"], v["ap"], age(v["t"])) for k, v in b["quotes"].items())),
        ("alpaca data: options snapshots SPY", "https://data.alpaca.markets/v1beta1/options/snapshots/SPY?limit=2&feed=indicative", dh,
         lambda b: "%d contracts" % len(b.get("snapshots", {}))),
        ("alpaca data: news", "https://data.alpaca.markets/v1beta1/news?limit=1", dh,
         lambda b: ("newest %s (%s)" % (b["news"][0]["created_at"], age(b["news"][0]["created_at"]))) if b.get("news") else "empty"),
    ]
    if env.get("FINNHUB_API_KEY"):
        checks.append(("finnhub quote SPY", "https://finnhub.io/api/v1/quote?symbol=SPY&token=" + env["FINNHUB_API_KEY"], {},
                       lambda b: "c=%s t=%s" % (b.get("c"), age(datetime.fromtimestamp(b["t"], tz=timezone.utc).isoformat()) if b.get("t") else "?")))
    if env.get("TWELVE_DATA_API_KEY"):
        checks.append(("twelvedata quote SPY", "https://api.twelvedata.com/quote?symbol=SPY&apikey=" + env["TWELVE_DATA_API_KEY"], {},
                       lambda b: "close=%s status=%s %s" % (b.get("close"), b.get("status", "ok"), str(b.get("message", ""))[:80])))
    if env.get("ALPHA_VANTAGE_API_KEY"):
        checks.append(("alphavantage quote SPY", "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=SPY&apikey=" + env["ALPHA_VANTAGE_API_KEY"], {},
                       lambda b: str({k: str(v)[:60] for k, v in b.items()})[:160]))
    if env.get("NASDAQ_DATA_LINK_API_KEY"):
        checks.append(("nasdaq data link", "https://data.nasdaq.com/api/v3/datasets/FRED/GDP.json?rows=1&api_key=" + env["NASDAQ_DATA_LINK_API_KEY"], {},
                       lambda b: "ok" if b.get("dataset") else str(b)[:100]))
    if env.get("MASSIVE_API_KEY"):
        checks.append(("polygon/massive prev SPY", "https://api.polygon.io/v2/aggs/ticker/SPY/prev?apiKey=" + env["MASSIVE_API_KEY"], {},
                       lambda b: "status=%s n=%s" % (b.get("status"), b.get("resultsCount"))))
    if env.get("ANTHROPIC_API_KEY"):
        checks.append(("anthropic api (models list)", "https://api.anthropic.com/v1/models?limit=1",
                       {"x-api-key": env["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                       lambda b: ("ok, first=%s" % b["data"][0]["id"]) if b.get("data") else str(b)[:100]))
    if env.get("MEM0_API_KEY"):
        checks.append(("mem0", "https://api.mem0.ai/v1/memories/?user_id=trezo&page_size=1", {"Authorization": "Token " + env["MEM0_API_KEY"]}, lambda b: "ok"))
    if env.get("TREZO_ALERT_WEBHOOK"):
        checks.append(("discord webhook (GET metadata, no post)", env["TREZO_ALERT_WEBHOOK"], {},
                       lambda b: "name=%s channel=%s" % (b.get("name"), b.get("channel_id"))))
    checks.append(("kraken public ticker", "https://api.kraken.com/0/public/Ticker?pair=XBTUSD", {},
                   lambda b: "err=%s last=%s" % (b.get("error"), list(b["result"].values())[0]["c"][0] if b.get("result") else "?")))
    checks.append(("coingecko ping", "https://api.coingecko.com/api/v3/ping", {}, lambda b: str(b)[:60]))
    bad = []
    for label, url, h, fmt in checks:
        code, body, dt = http(url, h)
        try:
            detail = fmt(body) if code == 200 and body is not None else str(body)[:160]
        except Exception as e:  # noqa: BLE001
            detail = "(parse) %s: %s" % (type(e).__name__, str(body)[:120])
        say("  %s HTTP %-3s %5ss  %-40s %s" % ("OK " if code == 200 else "BAD", code, dt, label, detail))
        if code != 200 and label.split(" (")[0] not in bad:
            bad.append(label.split(" (")[0])
    say("  keys present: " + ", ".join(k for k in ("ANTHROPIC_API_KEY", "FINNHUB_API_KEY", "TWELVE_DATA_API_KEY", "ALPHA_VANTAGE_API_KEY",
        "NASDAQ_DATA_LINK_API_KEY", "MASSIVE_API_KEY", "MEM0_API_KEY", "TREZO_ALERT_WEBHOOK", "KRAKEN_API_KEY", "TREZO_DROPBOX_TOKEN",
        "UPSTASH_REDIS_REST_URL") if env.get(k)))
    say("  toggles: " + ", ".join("%s=%s" % (k, env.get(k)) for k in ("TREZO_BROKER_ONLY", "ALPACA_CRYPTO_ENABLED", "TREZO_RESEARCH_ENABLED",
        "TREZO_REEVAL_ENABLED", "TREZO_CRYPTO_REEVAL", "TREZO_PRIMARY_USER_ID", "TREZO_SETTINGS_SINGLE_ROW", "TREZO_DAILY_GOAL", "TRADING_MODE",
        "ENV") if env.get(k) is not None))
    verdict("providers: %d checked, BAD=%s" % (len(checks), bad if bad else "none"))


# ------------------------------------------------------------------- server
def run_cmd(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return "%s: %s" % (type(e).__name__, str(e)[:120])


def section_server(env, repo_dir):
    say("\n## SERVER (localhost:8001, services, activity log)")
    nssm = r"C:\ProgramData\chocolatey\bin\nssm.exe"
    if os.path.exists(nssm):
        svcs = {s: run_cmd([nssm, "status", s], 30) for s in ("TrezoAgents", "TrezoApi", "TrezoWeb")}
        say("  services: " + ", ".join("%s=%s" % kv for kv in svcs.items()))
        verdict("services: " + ", ".join("%s=%s" % kv for kv in svcs.items()))
    git_head = run_cmd(["git", "-C", repo_dir, "log", "-1", "--format=%h %cd %s", "--date=short"], 30)
    say("  server checkout: %s" % git_head[:120])
    verdict("server checkout: %s" % git_head[:60])
    for path, fmt in (
        ("/health", lambda b: str(b)[:100]),
        ("/agents", None),
        ("/account-check", lambda b: str(b)[:300]),
        ("/admin/diagnose", lambda b: "verdict=%s next=%s checks=%s" % (b.get("verdict"), b.get("next_action"), [(c.get("name"), c.get("ok")) for c in b.get("checks", [])])),
        ("/activity/today", lambda b: str(b)[:400]),
        ("/allocations/snapshot", lambda b: str(b)[:300]),
    ):
        code, body, dt = http("http://localhost:8001" + path, timeout=30)
        if path == "/agents" and code == 200:
            agents = body.get("agents") if isinstance(body, dict) else body
            agents = agents if isinstance(agents, list) else []
            say("  /agents: %d registered" % len(agents))
            stale, disabled = [], []
            for a in agents:
                last = a.get("last_tick_at") or a.get("last_run_at") or a.get("last_tick")
                en = a.get("enabled", True)
                say("    %-26s enabled=%s tick=%ss msgs=%s last=%s (%s) errors=%s" % (
                    a.get("name"), en, a.get("tick_interval_seconds"), a.get("message_count") or a.get("messages"), str(last)[:19], age(last) if last else "never", a.get("error_count") or a.get("errors")))
                if not en:
                    disabled.append(a.get("name"))
                try:
                    if last and (NOW - parse_ts(last)).total_seconds() > max(900, 3 * float(a.get("tick_interval_seconds") or 300)):
                        stale.append(a.get("name"))
                except Exception:  # noqa: BLE001
                    pass
            verdict("agents registry: %d, disabled=%s, stale=%s" % (len(agents), disabled or "none", stale or "none"))
            continue
        if code == 200 and fmt:
            try:
                say("  %s: %s" % (path, fmt(body)))
            except Exception as e:  # noqa: BLE001
                say("  %s: (parse) %s %s" % (path, type(e).__name__, str(body)[:200]))
            if path == "/admin/diagnose" and isinstance(body, dict):
                verdict("engine self-diagnose: %s" % str(body.get("verdict"))[:120])
        else:
            say("  %s: HTTP %s %s" % (path, code, str(body)[:160]))
            if path == "/health":
                verdict("localhost:8001/health: HTTP %s (engine process not answering)" % code)
    # activity log: counts per day and today's detail
    logdir = env.get("TREZO_ACTIVITY_LOG_DIR") or os.path.join(repo_dir, "logs")
    say("  activity log dir: %s" % logdir)
    days = [(NOW - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7, -1, -1)]
    total_today = defaultdict(int)
    reasons = defaultdict(int)
    for d in days:
        p = os.path.join(logdir, "activity-%s.jsonl" % d)
        if not os.path.exists(p):
            say("    %s: (no file)" % d)
            continue
        counts = defaultdict(int)
        n = 0
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                n += 1
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                ev = str(rec.get("event"))
                counts[ev] += 1
                if d == days[-1]:
                    total_today[ev] += 1
                    if ev in ("veto", "broker_reject", "pdt_reject", "reentry_refused", "pdt_guard", "goal_lock_refused",
                              "book_at_capacity", "pocket_at_capacity", "book_already_holds", "price_unavailable", "execute_error"):
                        reasons[(ev, str(rec.get("reason"))[:70])] += 1
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:14]
        say("    %s: %d lines  %s" % (d, n, ", ".join("%s=%d" % kv for kv in top)))
    if reasons:
        say("    today's refusal/veto reasons (top 12):")
        for (ev, r), c in sorted(reasons.items(), key=lambda kv: -kv[1])[:12]:
            say("      %3d  %-16s %s" % (c, ev, r))
    keyev = {k: total_today.get(k, 0) for k in ("approve", "approved", "fill", "filled", "veto", "broker_reject", "execute_error", "price_unavailable") if total_today.get(k)}
    verdict("activity today: %s" % (keyev if keyev else dict(list(total_today.items())[:6]) if total_today else "no lines"))


# ------------------------------------------------------------------ discord
def post_discord(env, text):
    hook = env.get("TREZO_ALERT_WEBHOOK")
    if not hook:
        say("  (no TREZO_ALERT_WEBHOOK; skipping discord post)")
        return
    chunks, cur = [], ""
    for line in text.splitlines():
        if len(cur) + len(line) + 1 > 1850:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur:
        chunks.append(cur)
    for i, c in enumerate(chunks):
        payload = json.dumps({"content": "```\n%s```" % c, "username": "Nova diag"}).encode()
        code, body, dt = http(hook, {"Content-Type": "application/json"}, method="POST", data=payload)
        say("  discord chunk %d/%d: HTTP %s" % (i + 1, len(chunks), code))
        time.sleep(0.7)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=(NOW - timedelta(days=7)).strftime("%Y-%m-%d"))
    ap.add_argument("--section", default="all", help="all|engine|broker|pnl|providers")
    ap.add_argument("--server", action="store_true", help="also query localhost:8001, nssm and the activity log")
    ap.add_argument("--repo", default=r"C:\Trezo\trezo-platform")
    ap.add_argument("--out", default="", help="write the full report here")
    ap.add_argument("--discord", action="store_true", help="post the VERDICT block to TREZO_ALERT_WEBHOOK")
    a = ap.parse_args()
    env = load_env(find_env())
    since_iso = a.since + "T00:00:00Z"
    say("# Trezo diagnostic  now=%sZ (%s)  since=%s  env keys=%d" % (NOW.isoformat()[:19], NOW.astimezone(ET).strftime("%a %H:%M ET"), a.since, len(env)))
    sb = SB(env)
    if a.section in ("all", "engine"):
        if sb.ok:
            section_engine(sb, since_iso)
        else:
            say("no Supabase creds in env")
            verdict("supabase: NO CREDS")
    books = {}
    if a.section in ("all", "broker", "pnl"):
        books = section_broker(env, since_iso)
    if a.section in ("all", "pnl"):
        section_pnl(env, books, since_iso)
    if a.section in ("all", "providers"):
        section_providers(env)
    if a.server:
        section_server(env, a.repo)
    head = "VERDICT %sZ (%s)\n" % (NOW.isoformat()[:16], NOW.astimezone(ET).strftime("%a %H:%M ET")) + "\n".join("- " + v for v in VERDICT)
    for s in SECRETS:
        head = head.replace(s, "***")
    print("\n" + "=" * 70 + "\n" + head + "\n" + "=" * 70)
    full = head + "\n\n" + OUT.getvalue()
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(full)
        print("full report written: %s (%d chars)" % (a.out, len(full)))
    if a.discord:
        post_discord(env, head)


if __name__ == "__main__":
    main()
