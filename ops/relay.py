#!/usr/bin/env python3
"""
relay.py -- talk to the Trezo server through the Supabase ops relay.

No SSH, no password, no Mike at a keyboard. Nova writes a job row into
`ops_tasks`; the engine's ops_watchdog drains one job per tick (every
5 minutes) and writes the result back. The reverse channel `ops_log_tail`
carries the server's activity log back here.

Only the six whitelisted kinds exist. This is NOT a shell, and nothing
here can place an order or change risk. See db/migrations/0050_ops_relay.sql.

Usage (run from the sandbox, python3, no third-party deps):

  python3 relay.py check                     # is the relay alive? pending jobs? log freshness
  python3 relay.py health                    # queue report_status and wait for the answer
  python3 relay.py deploy                    # queue git_pull_restart and wait
  python3 relay.py rebuild                   # queue web_rebuild and wait
  python3 relay.py restart TrezoAgents       # restart one service and wait
  python3 relay.py install mem0ai            # pip install a whitelisted package
  python3 relay.py logtail 200               # ask the SERVER for its last N log lines
  python3 relay.py log --minutes 90          # read the log the server already pushed here
  python3 relay.py log --event route_orphan  # filter pushed log by event name
  python3 relay.py jobs                      # recent job history
  python3 relay.py queue <kind> '<json args>' [--wait]

Briefings (skills -> engine context, migration 0056; read by relay_ingest):
  python3 relay.py brief <kind> <payload.json|-> --source <skill> [--slot pre-close]
  python3 relay.py briefs [N]                # recent briefings + what the engine did with them
  kinds: market_context | daily_wrap | health  (schema: agents/app/agents/relay_ingest.py)

Env: read from agents/.env (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY).
Override the path with TREZO_ENV=/path/to/.env
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

KINDS = {
    "restart_service", "pip_install", "git_pull_restart",
    "web_rebuild", "report_status", "tail_log",
}
BRIEF_KINDS = {"market_context", "daily_wrap", "health"}
TICK_SECONDS = 300          # ops_watchdog tick interval
DEFAULT_WAIT = 480          # ~1.5 ticks; a queued job should land well inside this

ENV_CANDIDATES = [
    os.environ.get("TREZO_ENV", ""),
    "/sessions/*/mnt/Trezo/trezo-platform/agents/.env",   # expanded below
    "C:/Trezo/trezo-platform/agents/.env",
]


# ---------------------------------------------------------------- env / http

def _find_env() -> str:
    import glob
    for cand in ENV_CANDIDATES:
        if not cand:
            continue
        for hit in sorted(glob.glob(cand)) or ([cand] if os.path.exists(cand) else []):
            if os.path.exists(hit):
                return hit
    # last resort: walk up from cwd looking for agents/.env
    here = os.path.abspath(os.getcwd())
    for _ in range(6):
        probe = os.path.join(here, "agents", ".env")
        if os.path.exists(probe):
            return probe
        here = os.path.dirname(here)
    raise SystemExit("could not find agents/.env -- set TREZO_ENV=/path/to/.env")


def _load_env() -> tuple[str, str]:
    path = _find_env()
    env: dict[str, str] = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    url = env.get("SUPABASE_URL", "").rstrip("/")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise SystemExit(f"{path} is missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return url, key


_URL, _KEY = "", ""


def _headers(extra: dict | None = None) -> dict:
    h = {
        "apikey": _KEY,
        "Authorization": f"Bearer {_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _req(method: str, path: str, body=None, extra_headers=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_URL + path, data=data,
                                 headers=_headers(extra_headers), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode() or "[]"
            return json.loads(raw) if raw.strip() else []
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        raise SystemExit(f"Supabase {e.code} on {method} {path}\n{detail}")


def get(path: str, timeout=30):
    return _req("GET", path, timeout=timeout)


def post(path: str, body, timeout=30):
    return _req("POST", path, body, {"Prefer": "return=representation"}, timeout=timeout)


# ---------------------------------------------------------------- formatting

def _age(ts: str | None) -> str:
    if not ts:
        return "-"
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    secs = (datetime.now(timezone.utc) - t).total_seconds()
    if secs < 90:
        return f"{int(secs)}s ago"
    if secs < 5400:
        return f"{int(secs / 60)}m ago"
    return f"{secs / 3600:.1f}h ago"


def _short(ts: str | None) -> str:
    return (ts or "")[11:19]


# ---------------------------------------------------------------- operations

def cmd_check() -> int:
    """Is the relay alive? Cheap, read-only, no job queued."""
    jobs = get("/rest/v1/ops_tasks?select=id,kind,status,created_at,finished_at"
               "&order=created_at.desc&limit=10")
    logs = get("/rest/v1/ops_log_tail?select=ts&order=ts.desc&limit=1")

    pending = [j for j in jobs if j["status"] in ("queued", "running")]
    last_done = next((j for j in jobs if j["status"] == "done"), None)

    print("=== RELAY CHECK ===")
    print(f"last log push : {_age(logs[0]['ts']) if logs else 'NEVER'}")
    print(f"last job done : {_age(last_done['finished_at']) if last_done else 'none'}"
          + (f"  ({last_done['kind']})" if last_done else ""))
    print(f"pending jobs  : {len(pending)}")
    for j in pending:
        print(f"   {j['status']:<8} {j['kind']:<18} queued {_age(j['created_at'])}")

    stale = (not logs) or (datetime.now(timezone.utc)
                           - datetime.fromisoformat(logs[0]["ts"].replace("Z", "+00:00"))
                           ).total_seconds() > 3 * TICK_SECONDS
    if stale:
        print("\n!! log push is STALE (>3 ticks). The engine may be down, or the relay")
        print("   drain slipped back inside the once-a-day janitor gate in ops_watchdog.")
        print("   Check that drain_once() runs at the TOP of tick(), unindented.")
        return 1
    print("\nrelay looks healthy.")
    return 0


def queue(kind: str, args: dict | None = None, note: str | None = None) -> str:
    if kind not in KINDS:
        raise SystemExit(f"'{kind}' is not a whitelisted kind. Allowed: {sorted(KINDS)}")
    row = {"kind": kind, "args": args or {}, "requested_by": "nova"}
    if note:
        row["note"] = note
    created = post("/rest/v1/ops_tasks", row)
    job_id = created[0]["id"]
    print(f"queued {kind} -> {job_id}")
    print(f"(engine ticks every {TICK_SECONDS // 60} min; expect a result within ~10 min)")
    return job_id


def wait(job_id: str, seconds: int = DEFAULT_WAIT) -> int:
    deadline = time.time() + seconds
    last = ""
    while time.time() < deadline:
        rows = get(f"/rest/v1/ops_tasks?id=eq.{job_id}"
                   "&select=kind,status,attempts,result,finished_at")
        if not rows:
            print("job vanished")
            return 1
        job = rows[0]
        if job["status"] != last:
            last = job["status"]
            print(f"  [{time.strftime('%H:%M:%S')}] {last}")
        if job["status"] in ("done", "failed", "skipped"):
            print(f"\n=== {job['kind'].upper()} :: {job['status'].upper()} "
                  f"(attempt {job['attempts']}) ===")
            print(job.get("result") or "(no output)")
            return 0 if job["status"] == "done" else 1
        time.sleep(15)
    print(f"\nstill {last or 'queued'} after {seconds}s -- the engine may be stopped.")
    print("Run:  python3 relay.py check")
    return 2


def cmd_log(minutes: int, event: str | None, grep: str | None, limit: int) -> int:
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    q = ("/rest/v1/ops_log_tail?select=ts,host,line"
         f"&ts=gte.{urllib.parse.quote(since)}&order=ts.desc&limit={limit}")
    rows = get(q)
    if event:
        rows = [r for r in rows if str(r["line"].get("event", "")) == event]
    if grep:
        rows = [r for r in rows if grep.lower() in json.dumps(r["line"]).lower()]
    print(f"=== SERVER LOG (last {minutes}m, {len(rows)} rows) ===")
    for r in reversed(rows):
        ln = r["line"]
        bits = [str(ln.get(k)) for k in ("event", "ticker", "agent", "reason", "message")
                if ln.get(k)]
        print(f"  {_short(r['ts'])} " + " | ".join(bits)[:170])
    if not rows:
        print("  (nothing -- if this is empty for hours, run: python3 relay.py check)")
    return 0


def verify_boot(window_min: int = 6, poll_s: int = 30,
                timeout_s: int = 420) -> int:
    """A deploy is done when a NEW process says hello -- not when the
    restart command returns.

    WHY (2026-08-26): three deploys this week reported "done" while the
    old engine kept running. The restart handler runs inside the service
    it kills, and its detached child does not reliably survive; nothing
    downstream checked. The engine ran two-day-old code, every fix in
    that window silently absent, and every deploy log said success.

    This polls ops_log_tail for an `engine_boot` beacon newer than the
    moment we started asking (the bootstrap emits one per process, with
    pid and commit). Beacon found -> prints it, exit 0. No beacon inside
    the timeout -> LOUD failure and exit 3, with the one command that is
    known to land. Failing loudly here is the entire point: a deploy
    that cannot prove a boot must not look like a deploy that did.
    """
    from datetime import datetime, timezone, timedelta
    started = datetime.now(timezone.utc)
    since = (started - timedelta(minutes=window_min)).isoformat()
    print(f"verifying boot (engine_boot beacon, up to {timeout_s}s; the "
          f"log push runs on a ~5 min cadence)...")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            q = ("/rest/v1/ops_log_tail?select=ts,line"
                 f"&ts=gte.{urllib.parse.quote(since)}&order=ts.desc&limit=50")
            for r in get(q):
                ln = r.get("line") or {}
                if str(ln.get("event")) == "engine_boot":
                    print(f"BOOT VERIFIED  {_short(r['ts'])}  "
                          f"{ln.get('reason', '')[:100]}")
                    return 0
        except Exception as e:  # noqa: BLE001
            print(f"  (poll error, retrying: {e})")
        time.sleep(poll_s)
    print("!" * 66)
    print("! BOOT NOT VERIFIED -- the restart very likely did NOT land.")
    print("! The old process is still running whatever code it had.")
    print("! Fix (the one restart that always lands), over RDP:")
    print("!     nssm restart TrezoAgents")
    print("! Then re-run:  python3 ops/relay.py watchboot")
    print("!" * 66)
    return 3


def cmd_jobs(limit: int) -> int:
    rows = get("/rest/v1/ops_tasks?select=id,kind,status,attempts,created_at,finished_at,note"
               f"&order=created_at.desc&limit={limit}")
    print(f"{'when':<12} {'kind':<18} {'status':<8} {'try':<4} note")
    for j in rows:
        print(f"{_age(j['created_at']):<12} {j['kind']:<18} {j['status']:<8} "
              f"{j['attempts']:<4} {(j.get('note') or '')[:44]}")
    return 0


def cmd_brief(kind: str, src_path: str, source: str, slot: str | None) -> int:
    """Post ONE briefing for the engine's relay_ingest agent. Context only:
    the engine files it into agent memory, nothing is executed."""
    if kind not in BRIEF_KINDS:
        raise SystemExit(f"'{kind}' is not a briefing kind. Allowed: {sorted(BRIEF_KINDS)}")
    raw = sys.stdin.read() if src_path == "-" else open(src_path, encoding="utf-8").read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"payload is not valid JSON: {e}")
    if not isinstance(payload, dict):
        raise SystemExit("payload must be a JSON object")
    # Cheap local pre-flight so a typo is caught here, not 5 minutes later.
    required = {
        "market_context": ("as_of", "slot", "regime", "indices", "summary"),
        "daily_wrap": ("as_of", "trade_date", "realized_pnl_usd", "target_pnl_usd",
                        "open_positions", "lanes", "summary"),
        "health": ("as_of", "verdict", "findings", "summary"),
    }[kind]
    missing = [k for k in required if k not in payload]
    if missing:
        raise SystemExit(f"payload missing required field(s): {', '.join(missing)}")
    if slot and kind == "market_context" and payload.get("slot") != slot:
        payload["slot"] = slot
    row = {"kind": kind, "source": source, "payload": payload, "posted_by": "nova",
           "slot": slot or payload.get("slot") or payload.get("trade_date")}
    created = post("/rest/v1/relay_briefings", row)
    bid = created[0]["id"]
    print(f"posted {kind} briefing from {source} -> {bid}")
    print(f"(relay_ingest ticks every {TICK_SECONDS // 60} min; check with: python3 relay.py briefs)")
    return 0


def cmd_briefs(limit: int) -> int:
    rows = get("/rest/v1/relay_briefings?select=id,kind,source,slot,status,result,created_at,ingested_at"
               f"&order=created_at.desc&limit={limit}")
    print(f"{'when':<12} {'kind':<15} {'source':<22} {'slot':<11} {'status':<9} result")
    for r in rows:
        print(f"{_age(r['created_at']):<12} {r['kind']:<15} {(r.get('source') or '')[:21]:<22} "
              f"{(r.get('slot') or '')[:10]:<11} {r['status']:<9} {(r.get('result') or '')[:70]}")
    stuck = [r for r in rows if r["status"] == "new"
             and (datetime.now(timezone.utc)
                  - datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                  ).total_seconds() > 3 * TICK_SECONDS]
    if stuck:
        print(f"\n!! {len(stuck)} briefing(s) unread for >3 ticks. relay_ingest may not be running")
        print("   (old build, or the engine is down). Run: python3 relay.py check")
        return 1
    if not rows:
        print("  (no briefings yet)")
    return 0


# ---------------------------------------------------------------- entrypoint

def main(argv: list[str]) -> int:
    global _URL, _KEY
    _URL, _KEY = _load_env()

    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    do_wait = "--wait" in rest or cmd in {
        "health", "deploy", "rebuild", "restart", "install", "logtail"}
    rest = [a for a in rest if a != "--wait"]

    if cmd == "check":
        return cmd_check()

    if cmd == "jobs":
        return cmd_jobs(int(rest[0]) if rest else 15)

    if cmd == "briefs":
        return cmd_briefs(int(rest[0]) if rest else 15)

    if cmd == "brief":
        if len(rest) < 2:
            raise SystemExit("brief needs: <kind> <payload.json|-> --source <skill> [--slot <slot>]")
        kind, src_path = rest[0], rest[1]
        source, slot = "nova", None
        i = 2
        while i < len(rest):
            if rest[i] == "--source":
                source = rest[i + 1]; i += 2
            elif rest[i] == "--slot":
                slot = rest[i + 1]; i += 2
            else:
                i += 1
        return cmd_brief(kind, src_path, source, slot)

    if cmd == "log":
        minutes, event, grep, limit = 60, None, None, 300
        i = 0
        while i < len(rest):
            if rest[i] == "--minutes":
                minutes = int(rest[i + 1]); i += 2
            elif rest[i] == "--event":
                event = rest[i + 1]; i += 2
            elif rest[i] == "--grep":
                grep = rest[i + 1]; i += 2
            elif rest[i] == "--limit":
                limit = int(rest[i + 1]); i += 2
            else:
                i += 1
        return cmd_log(minutes, event, grep, limit)

    shortcuts = {
        "health":  ("report_status",   {}),
        "deploy":  ("git_pull_restart", {}),
        "rebuild": ("web_rebuild",     {}),
    }
    if cmd in shortcuts:
        kind, args = shortcuts[cmd]
        rc = wait(queue(kind, args, note=cmd)) if do_wait else 0
        if cmd == "deploy" and do_wait and rc == 0:
            rc = verify_boot()
        return rc
    if cmd == "restart":
        if not rest:
            raise SystemExit("restart needs a service: TrezoAgents | TrezoApi | TrezoWeb")
        rc = wait(queue("restart_service", {"service": rest[0]},
                        note=f"restart {rest[0]}"))
        if rest[0] == "TrezoAgents" and rc == 0:
            rc = verify_boot()
        return rc
    if cmd == "install":
        if not rest:
            raise SystemExit("install needs a package name")
        return wait(queue("pip_install", {"package": rest[0]}, note=f"install {rest[0]}"))
    if cmd == "logtail":
        n = int(rest[0]) if rest else 200
        return wait(queue("tail_log", {"lines": n}, note="tail_log"))

    if cmd == "queue":
        if not rest:
            raise SystemExit(f"queue needs a kind: {sorted(KINDS)}")
        args = json.loads(rest[1]) if len(rest) > 1 else {}
        job_id = queue(rest[0], args, note="manual")
        return wait(job_id) if do_wait else 0

    if cmd == "watch":
        return wait(rest[0]) if rest else 1

    if cmd == "watchboot":
        # Standalone boot verification -- run after a manual nssm restart
        # to confirm the new process actually came up.
        return verify_boot()

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
