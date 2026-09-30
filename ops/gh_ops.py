"""GitHub-driven ops channel for Trezo -- runs INSIDE a GitHub Actions job.

Why (2026-09-30): the laptop that holds the keys was away for weeks and the
server takes orders only through the Supabase relay. With the Supabase keys
held as GitHub Actions secrets, a request committed to the ops branch is
executed here and its (redacted) result is committed back, so an operator
with only git access can see the engine and drive the relay.

Request file: ops/requests/current.json
  {"id": "2026-09-30-1", "actions": [
     {"do": "check"},
     {"do": "diag", "since": "2026-09-21"},
     {"do": "relay", "kind": "report_status", "args": {"diagnostics": true}, "wait_s": 600},
     {"do": "relay", "kind": "tail_log", "args": {"lines": 300}, "wait_s": 600},
     {"do": "log", "minutes": 120, "event": "engine_boot"},
     {"do": "sql", "file": "supabase/migrations/20260910143905_independent_book_capabilities.sql"},
     {"do": "enable_books", "owner_id": "<uuid>", "apply": false},
     {"do": "deploy"},
     {"do": "sleep", "seconds": 60}
  ]}

The action set is CLOSED on purpose (like the relay's job kinds): no shell,
no arbitrary python. Result: ops/results/<id>.md, with every secret value
scrubbed. A request whose result file already exists is not run again.

Secrets (Actions secrets -> env): SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
SUPABASE_ACCESS_TOKEN (optional; only 'sql' needs it).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "ops" / "requests" / "current.json"
RESULTS = ROOT / "ops" / "results"
KNOWN_URL = "https://cvtxbyjtytoxlpkifbcs.supabase.co"
RELAY_KINDS = {"git_pull_restart", "pip_install", "report_status", "restart_service", "tail_log", "web_rebuild"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()[:19] + "Z"


class Runner:
    def __init__(self):
        self.url = (os.environ.get("SUPABASE_URL") or KNOWN_URL).rstrip("/")
        self.key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self.pat = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
        self.secrets = [s for s in (self.key, self.pat) if s]
        self.out: list[str] = []
        self.env_path = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "trezo-relay.env"
        self.env_path.write_text("SUPABASE_URL=%s\nSUPABASE_SERVICE_ROLE_KEY=%s\n" % (self.url, self.key), encoding="utf-8")
        try:
            os.chmod(self.env_path, 0o600)
        except Exception:  # noqa: BLE001
            pass
        self.child_env = dict(os.environ, TREZO_ENV=str(self.env_path), PYTHONIOENCODING="utf-8")

    # ---- output -------------------------------------------------------
    def scrub(self, text: str) -> str:
        for s in self.secrets:
            if s:
                text = text.replace(s, "***")
        text = re.sub(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "***jwt***", text)
        text = re.sub(r"sbp_[A-Za-z0-9]{20,}", "***sbp***", text)
        return text

    def say(self, text: str = ""):
        text = self.scrub(str(text))
        print(text, flush=True)
        self.out.append(text)

    def section(self, title: str):
        self.say("\n## %s  (%s)" % (title, now_iso()))

    # ---- primitives ---------------------------------------------------
    def run(self, args: list[str], timeout: int = 900) -> tuple[int, str]:
        try:
            p = subprocess.run(args, cwd=str(ROOT), env=self.child_env, capture_output=True,
                               text=True, timeout=timeout, encoding="utf-8", errors="replace")
            return p.returncode, (p.stdout + ("\n" + p.stderr if p.stderr.strip() else ""))
        except subprocess.TimeoutExpired as e:
            return 124, "TIMEOUT after %ss\n%s" % (timeout, (e.stdout or "")[-3000:] if isinstance(e.stdout, str) else "")

    def relay(self, *args: str, timeout: int = 900) -> tuple[int, str]:
        return self.run([sys.executable, "ops/relay.py", *args], timeout=timeout)

    def rest(self, method: str, path: str, body=None, headers=None, timeout=60):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key, "Content-Type": "application/json"}
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode() or "[]"
                return r.status, (json.loads(raw) if raw.strip() else [])
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")[:600]
        except Exception as e:  # noqa: BLE001
            return 0, "%s: %s" % (type(e).__name__, str(e)[:200])

    # ---- actions ------------------------------------------------------
    def do_check(self, a):
        rc, out = self.relay("check", timeout=120)
        self.say(out.strip())
        self.say("(exit %d)" % rc)

    def do_diag(self, a):
        since = str(a.get("since") or "")
        args = [sys.executable, "ops/diag.py", "--section", str(a.get("section") or "engine")]
        if since:
            args += ["--since", since]
        rc, out = self.run(args, timeout=600)
        self.say(out.strip())
        self.say("(exit %d)" % rc)

    def do_relay(self, a):
        kind = str(a.get("kind") or "")
        if kind not in RELAY_KINDS:
            self.say("refused: kind %r is not one of %s" % (kind, sorted(RELAY_KINDS)))
            return
        if kind == "git_pull_restart":
            self.say("refused: use {\"do\": \"deploy\"} for git_pull_restart (it verifies the boot)")
            return
        args = json.dumps(a.get("args") or {})
        wait_s = int(a.get("wait_s") or 720)
        rc, out = self.relay("queue", kind, args, "--wait", timeout=wait_s + 60)
        self.say(out.strip())
        self.say("(exit %d)" % rc)

    def do_deploy(self, a):
        self.say("deploy = queue git_pull_restart, wait for the job, then wait for a NEW engine_boot beacon")
        rc, out = self.relay("deploy", timeout=1500)
        self.say(out.strip())
        self.say("(exit %d -- 0 means a fresh process said hello)" % rc)

    def do_log(self, a):
        args = ["log", "--minutes", str(int(a.get("minutes") or 120)), "--limit", str(int(a.get("limit") or 300))]
        if a.get("event"):
            args += ["--event", str(a["event"])]
        if a.get("grep"):
            args += ["--grep", str(a["grep"])]
        rc, out = self.relay(*args, timeout=120)
        self.say(out.strip())

    def do_sql(self, a):
        if not self.pat:
            self.say("skipped: SUPABASE_ACCESS_TOKEN secret is not set (needed to run SQL)")
            return
        ref = self.url.split("//", 1)[-1].split(".", 1)[0]
        if a.get("file"):
            path = (ROOT / str(a["file"])).resolve()
            if ROOT not in path.parents or not path.exists():
                self.say("refused: %s is not a file inside the repo" % a.get("file"))
                return
            query = path.read_text(encoding="utf-8")
            self.say("sql file: %s (%d chars)" % (a["file"], len(query)))
        else:
            query = str(a.get("query") or "")
            self.say("sql query: %s" % query[:300].replace("\n", " "))
        if not query.strip():
            self.say("refused: empty sql")
            return
        req = urllib.request.Request("https://api.supabase.com/v1/projects/%s/database/query" % ref,
                                     data=json.dumps({"query": query}).encode(),
                                     headers={"Authorization": "Bearer " + self.pat, "Content-Type": "application/json"},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read().decode(errors="replace")
                self.say("HTTP %d: %s" % (r.status, body[:3000]))
        except urllib.error.HTTPError as e:
            self.say("HTTP %d: %s" % (e.code, e.read().decode(errors="replace")[:1500]))
        except Exception as e:  # noqa: BLE001
            self.say("error: %s: %s" % (type(e).__name__, str(e)[:200]))

    def do_enable_books(self, a):
        args = [sys.executable, "ops/enable_books.py", "--owner-id", str(a.get("owner_id") or ""), "--db-only"]
        if a.get("apply"):
            args.append("--apply")
        rc, out = self.run(args, timeout=300)
        self.say(out.strip())
        self.say("(exit %d)" % rc)

    def do_sleep(self, a):
        s = min(600, max(0, int(a.get("seconds") or 30)))
        self.say("sleeping %ds" % s)
        time.sleep(s)

    def do_query(self, a):
        """Read-only PostgREST GET, e.g. {"do":"query","path":"/rest/v1/bot_settings?select=*"}."""
        path = str(a.get("path") or "")
        if not path.startswith("/rest/v1/"):
            self.say("refused: path must start with /rest/v1/")
            return
        code, body = self.rest("GET", path + ("&" if "?" in path else "?") + "limit=%d" % int(a.get("limit") or 200))
        text = json.dumps(body, indent=1, default=str) if not isinstance(body, str) else body
        self.say("GET %s -> HTTP %s\n%s" % (path, code, text[:12000]))

    ACTIONS = {"check": do_check, "diag": do_diag, "relay": do_relay, "deploy": do_deploy, "log": do_log,
               "sql": do_sql, "enable_books": do_enable_books, "sleep": do_sleep, "query": do_query}


def main() -> int:
    if not REQ.exists():
        print("no request file at %s" % REQ)
        return 0
    req = json.loads(REQ.read_text(encoding="utf-8"))
    rid = re.sub(r"[^A-Za-z0-9._-]", "_", str(req.get("id") or "request"))
    RESULTS.mkdir(parents=True, exist_ok=True)
    result_path = RESULTS / ("%s.md" % rid)
    if result_path.exists() and not req.get("rerun"):
        print("request %s already has a result; nothing to do" % rid)
        return 0
    r = Runner()
    r.say("# ops result %s" % rid)
    r.say("started %s on %s" % (now_iso(), os.environ.get("GITHUB_SHA", "?")[:10]))
    if not r.key:
        r.say("FATAL: SUPABASE_SERVICE_ROLE_KEY secret is not set")
    else:
        for i, a in enumerate(req.get("actions") or []):
            do = str(a.get("do") or "")
            r.section("%d. %s %s" % (i + 1, do, json.dumps({k: v for k, v in a.items() if k != "do"})))
            fn = Runner.ACTIONS.get(do)
            if fn is None:
                r.say("refused: unknown action %r (allowed: %s)" % (do, sorted(Runner.ACTIONS)))
                continue
            try:
                fn(r, a)
            except Exception as e:  # noqa: BLE001
                r.say("action error: %s: %s" % (type(e).__name__, r.scrub(str(e))[:400]))
    r.say("\nfinished %s" % now_iso())
    result_path.write_text("\n".join(r.out) + "\n", encoding="utf-8")
    print("wrote %s (%d chars)" % (result_path, sum(len(x) + 1 for x in r.out)))
    try:
        r.env_path.unlink()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
