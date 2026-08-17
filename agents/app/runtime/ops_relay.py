"""Ops relay -- the engine executes operator jobs queued in Supabase.

WHY (Mike, 2026-08-13): after the VM migration Nova lost hands on the
box. SSH from the PC is flaky and requires Mike awake at a keyboard.
Supabase is the one place both sides already hold keys, so it becomes a
mailbox: Nova queues a job, the engine runs it on its next watchdog tick
and writes the result back. Also carries the REVERSE direction -- the
server's activity log is posted back so Nova can read it from anywhere.

SAFETY -- read before extending:
  * WHITELIST ONLY. Every job is a named handler below. There is no
    "run this string" path and there must never be one: this table lives
    beside broker credentials.
  * pip_install validates the package name against a strict pattern and
    a small allowlist. No URLs, no local paths, no version pins with
    shell characters.
  * NOTHING here may place an order, change risk/posture/settings, or
    start a second engine. Operations only.
  * One job per tick, oldest first, max 3 attempts -- a poisonous job
    cannot spin the engine.
  * Everything is logged: activity log + the row's own result field.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

NSSM = r"C:\ProgramData\chocolatey\bin\nssm.exe"
REPO = Path(r"C:\Trezo\trezo-platform")
VENV_PIP = REPO / "agents" / ".venv" / "Scripts" / "pip.exe"
SERVICES = {"TrezoAgents", "TrezoApi", "TrezoWeb"}
PKG_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,48}(==[0-9][0-9A-Za-z.]{0,15})?$")
PKG_ALLOW = {"mem0ai", "supabase", "httpx", "yfinance", "structlog",
             "pandas", "numpy", "scipy", "python-dotenv", "pydantic",
             "pydantic-settings", "fastapi", "uvicorn", "apscheduler"}
MAX_ATTEMPTS = 3
_TICK_BUSY = False


def _run(cmd: list[str], timeout: int = 900) -> str:
    """Run a command with NO shell. Returns combined output, truncated."""
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=timeout, shell=False)
    out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    return f"[exit {p.returncode}]\n{out[-4000:]}"


# ---- handlers (the entire universe of what the relay can do) ----------

def _h_restart_service(args: dict) -> str:
    svc = str(args.get("service") or "")
    if svc not in SERVICES:
        raise ValueError(f"service must be one of {sorted(SERVICES)}")
    if svc == "TrezoAgents":
        # Restarting our own host process from inside it: fire and let
        # NSSM bring us back; the row is marked done BEFORE we die.
        return _run([NSSM, "restart", svc], timeout=120)
    return _run([NSSM, "restart", svc], timeout=300)


def _h_pip_install(args: dict) -> str:
    pkg = str(args.get("package") or "").strip()
    if not PKG_OK.match(pkg):
        raise ValueError("package name failed validation")
    base = pkg.split("==")[0].lower()
    if base not in PKG_ALLOW:
        raise ValueError(f"'{base}' not in the allowlist")
    return _run([str(VENV_PIP), "install", pkg], timeout=600)


def _h_git_pull_restart(args: dict) -> str:
    out = _run(["git", "-C", str(REPO), "pull", "--ff-only"], timeout=300)
    out += "\n" + _run([NSSM, "restart", "TrezoAgents"], timeout=120)
    return out


def _h_web_rebuild(args: dict) -> str:
    web = REPO / "web"
    out = _run(["npm", "--prefix", str(web), "run", "build"], timeout=1800)
    out += "\n" + _run([NSSM, "restart", "TrezoWeb"], timeout=300)
    return out


def _h_report_status(args: dict) -> str:
    lines = []
    for svc in sorted(SERVICES):
        lines.append(f"{svc}: {_run([NSSM, 'status', svc], timeout=60)}")
    try:
        import urllib.request as _u
        with _u.urlopen("http://127.0.0.1:8001/health", timeout=10) as r:
            lines.append("health: " + r.read(400).decode("utf-8", "ignore"))
    except Exception as e:  # noqa: BLE001
        lines.append(f"health: UNREACHABLE ({e})")
    try:
        from app.brokers.accounts import load_accounts, validation_report
        lines.append("accounts: "
                     + ", ".join(a.account_id for a in load_accounts())
                     + " | problems: " + str(validation_report() or "none"))
    except Exception as e:  # noqa: BLE001
        lines.append(f"accounts: error {e}")
    try:
        import importlib
        importlib.import_module("app.knowledge.market_brief")
        lines.append("market_brief module: importable")
    except Exception as e:  # noqa: BLE001
        lines.append(f"market_brief module: MISSING ({e})")
    try:
        import mem0  # noqa: F401
        lines.append("mem0 SDK: installed")
    except Exception:  # noqa: BLE001
        lines.append("mem0 SDK: NOT installed")
    return "\n".join(lines)


def _h_tail_log(args: dict) -> str:
    n = max(1, min(int(args.get("lines") or 100), 500))
    d = REPO / "logs"
    files = sorted(d.glob("activity-*.jsonl"))
    if not files:
        return "no activity logs found"
    tail = files[-1].read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
    return f"{files[-1].name} last {len(tail)} lines:\n" + "\n".join(tail)[-6000:]


HANDLERS = {
    "restart_service": _h_restart_service,
    "pip_install": _h_pip_install,
    "git_pull_restart": _h_git_pull_restart,
    "web_rebuild": _h_web_rebuild,
    "report_status": _h_report_status,
    "tail_log": _h_tail_log,
}


# ---- the drain, called from ops_watchdog every tick ------------------

async def drain_once(client) -> dict | None:
    """Claim and run ONE queued job. Returns a summary or None."""
    global _TICK_BUSY
    if _TICK_BUSY or client is None:
        return None
    _TICK_BUSY = True
    try:
        def _q():
            return (client.table("ops_tasks").select("*")
                    .eq("status", "queued").order("created_at")
                    .limit(1).execute())
        rows = (await asyncio.to_thread(_q)).data or []
        if not rows:
            return None
        job = rows[0]
        jid, kind = job["id"], str(job.get("kind"))
        args = job.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:  # noqa: BLE001
                args = {}
        attempts = int(job.get("attempts") or 0) + 1

        def _claim():
            return (client.table("ops_tasks").update({
                "status": "running", "attempts": attempts,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", jid).execute())
        await asyncio.to_thread(_claim)

        try:
            fn = HANDLERS.get(kind)
            if fn is None:
                raise ValueError(f"unknown kind '{kind}'")
            # Restarting ourselves kills this process: record success first.
            self_kill = (kind == "restart_service"
                         and str(args.get("service")) == "TrezoAgents") \
                        or kind == "git_pull_restart"
            if self_kill:
                def _pre():
                    return (client.table("ops_tasks").update({
                        "status": "done",
                        "result": "restarting agents now (result recorded "
                                  "before the process exits)",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", jid).execute())
                await asyncio.to_thread(_pre)
            out = await asyncio.to_thread(fn, args)
            if not self_kill:
                def _done():
                    return (client.table("ops_tasks").update({
                        "status": "done", "result": out[:8000],
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", jid).execute())
                await asyncio.to_thread(_done)
            try:
                from app.agents.activity_log import record
                record("ops_relay", kind.upper(),
                       reason=f"executed {kind} -> {out[:180]}")
            except Exception:  # noqa: BLE001
                pass
            return {"kind": kind, "status": "done"}
        except Exception as e:  # noqa: BLE001
            final = "failed" if attempts >= MAX_ATTEMPTS else "queued"
            def _fail():
                return (client.table("ops_tasks").update({
                    "status": final, "result": f"ERROR: {e}"[:4000],
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", jid).execute())
            await asyncio.to_thread(_fail)
            try:
                from app.agents.activity_log import record
                record("ops_relay", kind.upper(),
                       reason=f"{kind} FAILED ({attempts}/{MAX_ATTEMPTS}): {e}"[:280])
            except Exception:  # noqa: BLE001
                pass
            return {"kind": kind, "status": final, "error": str(e)}
    except Exception:  # noqa: BLE001
        return None
    finally:
        _TICK_BUSY = False


_LAST_PUSH = None


async def push_log_tail(client, minutes: int = 10, cap: int = 120) -> int:
    """Engine -> Nova: post recent activity-log lines to Supabase so the
    SERVER's log is readable from anywhere (the visibility the migration
    took away). Only lines newer than the last push, capped per run."""
    global _LAST_PUSH
    if client is None:
        return 0
    try:
        d = REPO / "logs"
        files = sorted(d.glob("activity-*.jsonl"))
        if not files:
            return 0
        cutoff = _LAST_PUSH or (datetime.now(timezone.utc)
                                - timedelta(minutes=minutes))
        newest = cutoff
        batch = []
        for raw in files[-1].read_text(encoding="utf-8",
                                       errors="ignore").splitlines()[-1200:]:
            try:
                row = json.loads(raw)
                ts = datetime.fromisoformat(str(row.get("ts")).replace("Z", "+00:00"))
            except Exception:  # noqa: BLE001
                continue
            if ts <= cutoff:
                continue
            newest = max(newest, ts)
            batch.append({"ts": ts.isoformat(), "host": "trezo-server",
                          "line": row})
        if not batch:
            return 0
        batch = batch[-cap:]
        def _ins():
            return client.table("ops_log_tail").insert(batch).execute()
        await asyncio.to_thread(_ins)
        _LAST_PUSH = newest
        return len(batch)
    except Exception:  # noqa: BLE001
        return 0
