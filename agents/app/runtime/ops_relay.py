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
import os
import re
import shutil
import subprocess
import sys
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

# A handler that needs THIS process restarted returns this marker instead
# of doing it, so the drain can write the result down FIRST.
#
# Why (2026-08-18): self-kill jobs used to be marked done with a canned
# "restarting agents now" line BEFORE the handler ran, because the
# restart kills us mid-handler and nothing could be written after. The
# cost was total: a pull that failed and a pull that worked produced the
# identical row. The server sat eight commits behind for two deploys
# while every row read done, and the one line that would have explained
# it -- "no tracking information for the current branch" -- was thrown
# away each time. Record, THEN die.
RESTART_SENTINEL = "<<RESTART_TREZOAGENTS>>"


def _restart_detached() -> str:
    """Restart TrezoAgents from OUTSIDE our own process tree.

    Why (2026-08-20): the drain used to run `nssm restart TrezoAgents`
    inline. nssm's stop kills this service's whole process tree
    (AppKillProcessTree is on) -- including that very nssm child, which
    died between the STOP and the START. The row said done, the guards
    were green, and the engine stayed down for 28 minutes until a human
    typed the start by hand. A Task Scheduler one-shot runs under the
    Task Scheduler service, not under us, so it survives our death and
    issues the restart on our grave."""
    # AUDIT 2026-08-27: the original ran as the service account with no
    # /RU and no run level, and minute-granular /ST could land in the
    # already-elapsed minute. Boots kept not happening while every row
    # said done. Now: SYSTEM account, highest run level, scheduled two
    # minutes out so the timestamp is always in the future.
    #
    # 2026-08-27 #2, from the first live test: a FIXED task name plus
    # BOTH /Run and the /ST trigger caused (a) a double restart when
    # both fired (boots 82s apart) and then (b) NOTHING at all — the
    # first run's instance can linger as "running" (nssm restart blocks
    # inside it), and schtasks' default multiple-instance policy
    # IGNORES every later trigger on that task. The 17:41Z deploy
    # scheduled "SUCCESS" twice and the old process kept running.
    # Now: end + delete any lingering legacy task (best-effort), then
    # create a UNIQUELY NAMED one-shot with a single /ST trigger and no
    # immediate /Run — exactly one fire, on a task nothing can block.
    _run(["schtasks", "/End", "/TN", "TrezoRelayRestart"], timeout=30)
    _run(["schtasks", "/Delete", "/TN", "TrezoRelayRestart", "/F"],
         timeout=30)
    _task = "TrezoRelayRestart_" + datetime.now().strftime("%H%M%S")
    out = _run(["schtasks", "/Create", "/F", "/TN", _task,
                "/TR", f"{NSSM} restart TrezoAgents",
                "/SC", "ONCE", "/RU", "SYSTEM", "/RL", "HIGHEST",
                "/ST", (datetime.now() + timedelta(minutes=2)).strftime("%H:%M")],
               timeout=60)
    return f"[task {_task}]\n{out}"


def _run(cmd: list[str], timeout: int = 900, cwd: str | None = None) -> str:
    """Run a command with NO shell. Returns combined output, truncated."""
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=timeout, shell=False, cwd=cwd)
    out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    return f"[exit {p.returncode}]\n{out[-4000:]}"


# ---- handlers (the entire universe of what the relay can do) ----------

def _h_restart_service(args: dict) -> str:
    svc = str(args.get("service") or "")
    if svc not in SERVICES:
        raise ValueError(f"service must be one of {sorted(SERVICES)}")
    if svc == "TrezoAgents":
        # Restarting our own host process from inside it. Hand it back to
        # the drain so the result is durable before we go.
        return RESTART_SENTINEL
    return _run([NSSM, "restart", svc], timeout=300)


def _h_pip_install(args: dict) -> str:
    pkg = str(args.get("package") or "").strip()
    if not PKG_OK.match(pkg):
        raise ValueError("package name failed validation")
    base = pkg.split("==")[0].lower()
    if base not in PKG_ALLOW:
        raise ValueError(f"'{base}' not in the allowlist")
    return _run([str(VENV_PIP), "install", pkg], timeout=600)


VENV_PY = REPO / "agents" / ".venv" / "Scripts" / "python.exe"


def _tell(message: str, key: str = "deploy_blocked") -> None:
    """Say it out loud. A deploy that fails quietly is how the server
    ended up eight commits behind with every row marked done."""
    try:
        # AUDIT 2026-08-27: this used to call the ASYNC notify() from a
        # worker thread without awaiting it -- a coroutine was built,
        # never run, and the except below ate the RuntimeWarning. Every
        # "deploy aborted/blocked" alert since 08-20 was silent.
        # notify_sync exists precisely for non-async contexts.
        from app.runtime.alerts import notify_sync
        # key= as a KEYWORD (re-audit: it was bound positionally to
        # title, defeating the dedupe the module exists for, and the
        # alert title read literally "deploy_blocked").
        notify_sync("Trezo deploy", message, severity="urgent", key=key)
    except Exception:  # noqa: BLE001
        pass


def _head() -> str:
    p = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                       capture_output=True, text=True, timeout=60, shell=False)
    return (p.stdout or "").strip()


def _h_git_pull_restart(args: dict) -> str:
    """Pull, PROVE the new code passes its guards, then restart.

    Added 2026-08-18. Before this, deploy was pull-then-restart on
    faith: if the pulled commit was broken the engine restarted onto it
    and stopped managing three books, which is exactly the fifteen-hour
    outage on 8/17 with an extra step. The guard suites run in a bare
    checkout by design -- no .env, no keys, no network -- so there is no
    excuse for a deploy not to run them.

    On failure the checkout is rolled back to the commit that was there
    before and NO restart happens, so the running engine keeps serving
    the code it is already on. The server checkout is deploy-only, which
    is what makes reset --hard safe here; pull --ff-only already assumes
    it. Skip with args {"skip_tests": true} when you need to ship a fix
    to the tests themselves."""
    before = _head()
    # `git pull --ff-only` with no arguments needs branch tracking, and
    # on 2026-08-18 the server had none: every deploy since the GitHub
    # repo was created exited with "no tracking information for the
    # current branch", pulled nothing, and restarted anyway. The box sat
    # eight commits behind while the rows all said done. Name the remote
    # and branch explicitly so the deploy never depends on a piece of
    # server-side config nobody set and nobody can see from here.
    out = _run(["git", "-C", str(REPO), "pull", "--ff-only", "origin", "main"],
               timeout=300)
    after = _head()

    # A pull that did nothing must not look like a pull that worked.
    if "[exit 0]" not in out:
        out += "\nNOT restarted - the pull FAILED, so there is nothing new to run"
        _tell(f"Deploy aborted: git pull failed on the server, still on "
              f"{before[:8]}. Nothing was restarted.")
        return out
    if before and after and before == after:
        out += f"\nNothing to deploy - already on {before[:8]}; NOT restarted"
        return out

    if not args.get("skip_tests"):
        py = str(VENV_PY) if VENV_PY.exists() else "python"
        try:
            # cwd matters: `-m tests.run_all` resolves relative to it,
            # and the service's own working directory is not agents/.
            tests = _run([py, "-m", "tests.run_all"], timeout=600,
                         cwd=str(REPO / "agents"))
        except Exception as e:  # noqa: BLE001
            tests = f"[guards could not run] {e}"
        out += "\n--- guards ---\n" + tests
        if "all green across" not in tests:
            if before and after and before != after:
                out += "\n" + _run(
                    ["git", "-C", str(REPO), "reset", "--hard", before],
                    timeout=120)
                out += f"\nROLLED BACK to {before[:8]} - guards failed"
            else:
                out += "\nNOT restarted - guards failed"
            _tell(f"Deploy blocked: guards failed on {after[:8]}. "
                  f"Rolled back to {before[:8]}; engine still running the "
                  f"old code and was NOT restarted.")
            return out

    return out + "\n" + RESTART_SENTINEL


def _npm_exe() -> str:
    """The npm executable this host can actually spawn WITHOUT a shell.

    2026-09-02: the first web_rebuild queued after the audit fixes died on
    the server with `[WinError 2] The system cannot find the file
    specified` -- subprocess.run(["npm", ...], shell=False) cannot resolve
    the npm shim on Windows (it is npm.cmd; CLAUDE.md gotcha #1). Resolve
    the real file first, prefer the .cmd on Windows, and fall back to the
    bare name only where a shell-less spawn can find it (POSIX)."""
    for name in (("npm.cmd", "npm") if sys.platform.startswith("win") else ("npm",)):
        found = shutil.which(name)
        if found:
            return found
    return "npm.cmd" if sys.platform.startswith("win") else "npm"


def _web_service_is_dev_mode() -> bool:
    """True when the TrezoWeb service is launched with `next dev` / `npm run
    dev`. Read from nssm's own AppParameters so the answer is the truth on
    THIS host, not an assumption. Unreadable -> False (build path, as
    before). Overridable with TREZO_WEB_MODE=dev|prod."""
    forced = str(os.environ.get("TREZO_WEB_MODE", "")).strip().lower()
    if forced in ("dev", "prod"):
        return forced == "dev"
    try:
        out = _run([NSSM, "get", "TrezoWeb", "AppParameters"], timeout=30)
        body = out.split("\n", 1)[1] if "\n" in out else out
        return " dev" in f" {body.strip().lower()} " or "run dev" in body.lower()
    except Exception:  # noqa: BLE001
        return False


def _h_web_rebuild(args: dict) -> str:
    """AUDIT 2026-08-27: this used to restart TrezoWeb unconditionally
    after the build -- a failed `npm run build` restarted the site onto
    whatever half-state .next held, with the row marked done. The engine
    tier had a guard for exactly this; the web tier never got one. Now:
    no restart unless the build output says it compiled, and the refusal
    is stated in the row AND alerted."""
    web = REPO / "web"
    if _web_service_is_dev_mode():
        # 2026-09-02: a production build against a running `next dev`
        # corrupts the dev server's .next and fails ("Cannot find module
        # for page" while collecting page data) -- and the site serves
        # raw HTML until the dev server restarts. For a dev-mode service
        # the rebuild IS the restart: it recompiles from the source the
        # deploy just pulled.
        out = ("[exit 0]\nTrezoWeb runs in dev mode (next dev): skipped "
               "`next build` (it would race the dev server's .next); "
               "restarting so it recompiles from the pulled source.")
        out += "\n" + _run([NSSM, "restart", "TrezoWeb"], timeout=300)
        return out
    out = _run([_npm_exe(), "--prefix", str(web), "run", "build"], timeout=1800)
    ok = "[exit 0]" in out  # exit code only (2026-08-28): _run keeps the
        # LAST 4000 chars and Next prints "Compiled successfully" BEFORE an
        # ~8KB route table, so the string match refused every good build
    if not ok:
        out += "\nNOT restarted - build did not succeed"
        _tell(f"Web rebuild FAILED; TrezoWeb was NOT restarted and is "
              f"still serving the previous build. Tail: {out[-400:]}",
              key="web_rebuild_failed")
        return out
    out += "\n" + _run([NSSM, "restart", "TrezoWeb"], timeout=300)
    return out


def _h_report_status(args: dict) -> str:
    lines = []
    # 2026-08-28: queue report_status with {"send_test": true} to prove
    # the alert channel end to end — send_test() had zero callers while
    # its docstring claimed the relay used it.
    if args.get("send_test"):
        try:
            import asyncio as _aio_rs
            from app.runtime import alerts as _al
            _res = _aio_rs.run(_al.send_test())
            lines.append(f"send_test: {_res}")
        except Exception as _e:  # noqa: BLE001
            lines.append(f"send_test: FAILED {str(_e)[:160]}")
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
    # 2026-08-27: the scheduler's per-agent truth (last tick, message
    # count, last_error) lives only in this process and the localhost
    # dashboard — the day options_scanner went silent, nothing remote
    # could read WHY. Now the relay can. Runs in the SAME process as
    # the scheduler, so this is the live registry, not a copy.
    try:
        from app.runtime.registry import registry as _reg
        import datetime as _dt_rs
        for _st in _reg.all():
            _lt = getattr(_st, "last_tick_at", None)
            if isinstance(_lt, _dt_rs.datetime):
                _lt = _lt.isoformat()[:19]
            _err = str(getattr(_st, "last_error", None) or "")[:160]
            lines.append(
                f"agent {_st.name}: enabled={getattr(_st, 'enabled', '?')} "
                f"ticks={getattr(_st, 'tick_count', '?')} "
                f"msgs={getattr(_st, 'message_count', '?')} "
                f"last_tick={_lt} err={_err or '-'}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"agent states: error {str(e)[:160]}")
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

# Jobs whose handler can outlive the ops_watchdog tick (its ceiling is
# 600s). 2026-09-02: the first web_rebuild after the audit fixes took longer
# than that on the server; asyncio.wait_for cancelled the tick, the npm
# thread kept building, and nothing was left to mark the row done or
# restart TrezoWeb -- the row sat in "running" forever. These kinds now run
# to completion in their OWN asyncio task (tasks are not cancelled when the
# tick is), which writes the durable result and does the restart itself.
DETACHED_KINDS = {"web_rebuild"}
STALE_RUNNING_MIN = 45   # a "running" row older than this was stranded


def _parse_iso(ts) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


async def sweep_stranded(client) -> int:
    """Mark long-abandoned "running" rows failed so the queue tells the
    truth (and `relay.py check` stops showing a phantom pending job).
    Returns the number of rows swept. Never raises."""
    if client is None:
        return 0
    try:
        def _q():
            return (client.table("ops_tasks").select("id,kind,started_at")
                    .eq("status", "running").limit(20).execute())
        rows = (await asyncio.to_thread(_q)).data or []
        now = datetime.now(timezone.utc)
        n = 0
        for r in rows:
            st = _parse_iso(r.get("started_at"))
            if st is None or (now - st) < timedelta(minutes=STALE_RUNNING_MIN):
                continue
            jid = r["id"]
            def _mark(_jid=jid):
                return (client.table("ops_tasks").update({
                    "status": "failed",
                    "result": ("STRANDED: still 'running' after "
                               f"{STALE_RUNNING_MIN} min -- the tick that "
                               "owned it was cancelled before it could "
                               "record a result. Re-queue if still wanted."),
                    "finished_at": now.isoformat(),
                }).eq("id", _jid).execute())
            await asyncio.to_thread(_mark)
            n += 1
        return n
    except Exception:  # noqa: BLE001
        return 0


async def _complete_detached(client, jid: str, kind: str, args: dict,
                             attempts: int, fn) -> None:
    """Run a DETACHED_KINDS handler to completion and write its result --
    in its own task, so the watchdog tick's ceiling cannot orphan it."""
    global _TICK_BUSY
    try:
        try:
            out = await asyncio.to_thread(fn, args)
            def _done():
                return (client.table("ops_tasks").update({
                    "status": "done", "result": out[:8000],
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", jid).execute())
            await asyncio.to_thread(_done)
            try:
                from app.agents.activity_log import record
                record("ops_relay", kind.upper(),
                       reason=f"executed {kind} -> {out[-180:]}")
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            final = "failed" if attempts >= MAX_ATTEMPTS else "queued"
            def _fail():
                return (client.table("ops_tasks").update({
                    "status": final, "result": f"ERROR: {e}"[:4000],
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", jid).execute())
            try:
                await asyncio.to_thread(_fail)
            except Exception:  # noqa: BLE001
                pass
            try:
                from app.agents.activity_log import record
                record("ops_relay", kind.upper(),
                       reason=f"{kind} FAILED ({attempts}/{MAX_ATTEMPTS}): {e}"[:280])
            except Exception:  # noqa: BLE001
                pass
    finally:
        _TICK_BUSY = False


_DETACHED_TASKS: set = set()


async def drain_once(client) -> dict | None:
    """Claim and run ONE queued job. Returns a summary or None."""
    global _TICK_BUSY
    if _TICK_BUSY or client is None:
        return None
    _TICK_BUSY = True
    handed_off = False
    try:
        await sweep_stranded(client)
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

        if kind in DETACHED_KINDS and kind in HANDLERS:
            # Hand the long job to its own task and give the tick back.
            # _TICK_BUSY stays True until that task finishes, so the drain
            # still runs one job at a time.
            handed_off = True
            t = asyncio.create_task(_complete_detached(
                client, jid, kind, args, attempts, HANDLERS[kind]))
            _DETACHED_TASKS.add(t)
            t.add_done_callback(_DETACHED_TASKS.discard)
            try:
                from app.agents.activity_log import record
                record("ops_relay", kind.upper(),
                       reason=f"{kind} started in a detached task (result lands when it finishes)")
            except Exception:  # noqa: BLE001
                pass
            return {"kind": kind, "status": "started"}

        try:
            fn = HANDLERS.get(kind)
            if fn is None:
                raise ValueError(f"unknown kind '{kind}'")
            out = await asyncio.to_thread(fn, args)
            wants_restart = RESTART_SENTINEL in out
            out = out.replace(RESTART_SENTINEL, "").strip()

            # ALWAYS write the real result, self-kill or not. This is the
            # whole fix: the row now says what actually happened, so a
            # failed pull can never again read exactly like a good one.
            def _done():
                return (client.table("ops_tasks").update({
                    "status": "done",
                    "result": (out + ("\n[restarting TrezoAgents now]"
                                      if wants_restart else ""))[:8000],
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", jid).execute())
            await asyncio.to_thread(_done)
            try:
                from app.agents.activity_log import record
                record("ops_relay", kind.upper(),
                       reason=f"executed {kind} -> {out[:180]}")
            except Exception:  # noqa: BLE001
                pass
            if wants_restart:
                # Everything above is durable now. Safe to be killed --
                # but the restart itself must NOT be: hand it to Task
                # Scheduler so it survives this process's death.
                #
                # AUDIT 2026-08-27: the return value used to be assigned
                # to nothing, so an "Access is denied" from Task
                # Scheduler existed nowhere. Now it is logged, and a
                # non-SUCCESS output raises an urgent alert -- the boot
                # beacon proves a restart happened; this proves the
                # scheduling of one was even accepted.
                _rd_out = ""
                try:
                    _rd_out = await asyncio.to_thread(_restart_detached)
                except Exception as _rd_e:  # noqa: BLE001
                    _rd_out = f"EXCEPTION: {_rd_e}"
                try:
                    from app.agents.activity_log import record as _rrec
                    _rrec("restart_scheduled", "SYSTEM",
                          reason=f"schtasks -> {_rd_out[:200]}")
                except Exception:  # noqa: BLE001
                    pass
                if "SUCCESS" not in _rd_out.upper():
                    _tell(f"restart scheduling FAILED -- engine will "
                          f"keep running old code until a manual nssm "
                          f"restart: {_rd_out[:300]}",
                          key="restart_not_scheduled")
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
        if not handed_off:
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
