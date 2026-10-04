#!/usr/bin/env python3
"""Read-only migration configuration and optional Linux process verification.

Run with agents/.venv/bin/python (python-dotenv is already a Trezo dependency).
Never imports the trading app, starts services, reads broker balances, or sends
orders. A passing result is NOT proof of database recovery or trading readiness.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

SLOTS = {"primary": ("", "TREZO_PRIMARY_USER_ID"),
         "acct2": ("_2", "TREZO_ACCOUNT_USER_ID_2"),
         "acct3": ("_3", "TREZO_ACCOUNT_USER_ID_3")}
PAPER = "https://paper-api.alpaca.markets"
LOCAL_AGENTS = {"http://127.0.0.1:8001", "http://localhost:8001"}
LOCAL_WEB = {"http://127.0.0.1:3000", "http://localhost:3000"}


def url(value: str) -> str:
    return value.strip().rstrip("/")


def private_endpoint(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return bool(parsed.hostname and not parsed.username and not parsed.password
                    and not parsed.query and not parsed.fragment
                    and parsed.path in ("", "/") and
                    (parsed.scheme == "https" or
                     (parsed.scheme == "http" and parsed.hostname in
                      {"127.0.0.1", "localhost", "::1"})))
    except ValueError:
        return False


def config_issues(envs: dict, books: dict, database_url: str, web_url: str) -> list[str]:
    problems = []
    database_url, web_url = url(database_url), url(web_url)
    if not private_endpoint(database_url) or not private_endpoint(web_url):
        problems.append("expected_urls_require_https_or_local_loopback")
    agents, api, web = (envs[k] for k in ("agents", "api", "web"))
    actual_urls = [agents.get("SUPABASE_URL", ""),
                   api.get("NEXT_PUBLIC_SUPABASE_URL") or api.get("SUPABASE_URL", ""),
                   web.get("NEXT_PUBLIC_SUPABASE_URL", "")]
    if any(url(v) != database_url for v in actual_urls):
        problems.append("all_three_components_must_use_the_reviewed_database_url")
    roles = [e.get("SUPABASE_SERVICE_ROLE_KEY", "") for e in (agents, api, web)]
    if not all(roles) or len(set(roles)) != 1:
        problems.append("server_service_keys_missing_or_mismatched")
    anons = [api.get("NEXT_PUBLIC_SUPABASE_ANON_KEY") or api.get("SUPABASE_ANON_KEY", ""),
             web.get("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")]
    if not all(anons) or len(set(anons)) != 1 or anons[0] in roles:
        problems.append("public_anon_keys_missing_mismatched_or_privileged")
    if agents.get("TRADING_MODE", "paper").lower() != "paper":
        problems.append("paper_trading_mode_required")
    enabled = [s.strip() for s in agents.get("TREZO_ACCOUNTS_ENABLED", "").split(",")]
    if len(enabled) != 3 or set(enabled) != set(SLOTS):
        problems.append("exactly_three_independent_book_slots_required")
    if set(books) != set(SLOTS) or len(set(books.values())) != 3:
        problems.append("invalid_expected_book_mapping")
    keys = []
    for slot, (suffix, identity) in SLOTS.items():
        if not agents.get(identity) or agents.get(identity) != books.get(slot):
            problems.append(slot + "_book_identity_changed_or_missing")
        key, secret = agents.get("ALPACA_API_KEY" + suffix), agents.get("ALPACA_SECRET_KEY" + suffix)
        if not key or not secret:
            problems.append(slot + "_broker_credentials_missing")
        keys.append(key)
        broker = url(agents.get("ALPACA_BASE_URL" + suffix) or PAPER)
        if broker.removesuffix("/v2") != PAPER:
            problems.append(slot + "_broker_endpoint_is_not_alpaca_paper")
    if len(set(keys)) != 3:
        problems.append("broker_key_reused_across_books")
    if agents.get("ALPACA_CRYPTO_ENABLED", "false").lower() not in {"true", "1"}:
        problems.append("alpaca_crypto_route_not_enabled")
    for role, env in envs.items():
        for name, value in env.items():
            if name.endswith(("_PATH", "_DIR")) and re.match(r"^(?:[A-Za-z]:[\\/]|\\\\)", value):
                problems.append(role + "_windows_path_requires_relocation:" + name)
        for name in ("API_BASE_URL", "AGENTS_BASE_URL", "WEB_INTERNAL_BASE_URL", "TREZO_WEB_BASE_URL"):
            if not env.get(name):
                continue
            allowed = (LOCAL_AGENTS if name == "AGENTS_BASE_URL" else
                       {"http://127.0.0.1:8000", "http://localhost:8000"} if name == "API_BASE_URL" else
                       LOCAL_WEB | {web_url})
            if url(env[name]) not in allowed:
                problems.append(role + "_old_or_unexpected_internal_endpoint:" + name)
    if url(web.get("NEXT_PUBLIC_BASE_URL", "")) != web_url:
        problems.append("web_public_url_requires_relocation")
    if api.get("API_BIND_HOST", "127.0.0.1") != "127.0.0.1":
        problems.append("api_must_bind_loopback")
    return sorted(set(problems))


def run(args: list[str], cwd: Path | None = None) -> str:
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=15, check=False)
    if p.returncode:
        raise ValueError("command_failed")
    return p.stdout.strip()


def timestamp(value: str) -> dt.datetime:
    stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timezone_required")
    return stamp


def boot_matches(row: dict, pid: int, sha: str, after: dt.datetime) -> bool:
    try:
        match = re.fullmatch(r"engine process started: pid=(\d+) commit=([a-f0-9]{7,40}) agents=(\d+)",
                             row.get("reason", ""))
        at = timestamp(row["ts"])
        return bool(row.get("event") == "engine_boot" and match and int(match[1]) == pid
                    and sha.startswith(match[2]) and int(match[3]) >= 30
                    and after <= at <= dt.datetime.now(dt.timezone.utc))
    except (ValueError, TypeError, KeyError):
        return False


def owns_listener(pid: int, proc: Path = Path("/proc")) -> bool:
    """The verified engine, rather than an older listener, must own port8001."""
    try:
        owned = set()
        for fd in (proc / str(pid) / "fd").iterdir():
            try:
                target = fd.readlink().as_posix()
            except FileNotFoundError:
                continue
            match = re.fullmatch(r"socket:\[(\d+)\]", target)
            if match:
                owned.add(match[1])
        listeners = []
        for table in ("tcp", "tcp6"):
            for line in (proc / "net" / table).read_text().splitlines()[1:]:
                fields = line.split()
                if len(fields) < 10 or fields[3] != "0A":
                    continue
                address, port = fields[1].split(":")
                if int(port, 16) == 8001:
                    listeners.append((address, fields[9]))
        return len(listeners) == 1 and listeners[0][0] == "0100007F" and listeners[0][1] in owned
    except (OSError, ValueError):
        return False


def runtime_issues(repo: Path, sha: str, after: dt.datetime) -> list[str]:
    problems = []
    if not sys.platform.startswith("linux"):
        return ["runtime_verification_requires_linux"]
    try:
        if run(["git", "rev-parse", "HEAD"], repo) != sha:
            problems.append("checkout_commit_mismatch")
        if run(["git", "status", "--porcelain", "--untracked-files=no"], repo):
            problems.append("tracked_checkout_modified")
        pid = int(run(["systemctl", "show", "trezo-agents.service", "--property=MainPID", "--value"]))
        if pid <= 0:
            raise ValueError("not_running")
        process = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        executable = str(repo / "agents/.venv/bin/python").encode()
        if process[:4] != [executable, b"-m", b"uvicorn", b"app.main:app"]:
            problems.append("unexpected_engine_process")
        for name, value in ((b"--workers", b"1"), (b"--port", b"8001"), (b"--host", b"127.0.0.1")):
            if name not in process or process[process.index(name) + 1:process.index(name) + 2] != [value]:
                problems.append("single_loopback_engine_arguments_unverified")
        if b"--reload" in process:
            problems.append("engine_reload_must_be_disabled")
        if not owns_listener(pid):
            problems.append("port8001_listener_not_owned_by_verified_engine")
        engine_pids = []
        for entry in Path("/proc").glob("[0-9]*"):
            try:
                argv = (entry / "cmdline").read_bytes().split(b"\0")
                if (b"uvicorn" in argv or (argv and argv[0].rsplit(b"/", 1)[-1] == b"uvicorn")) and b"app.main:app" in argv:
                    engine_pids.append(int(entry.name))
            except (OSError, ValueError):
                continue
        if engine_pids != [pid]:
            problems.append("additional_or_unverified_local_engine_process")
        if Path(f"/proc/{pid}/cwd").resolve() != (repo / "agents").resolve():
            problems.append("engine_working_directory_mismatch")
        boot_ok = False
        for log in sorted((repo / "logs").glob("activity-*.jsonl"))[-2:]:
            with log.open("rb") as stream:
                size = stream.seek(0, 2)
                stream.seek(max(0, size - 2 * 1024 * 1024))
                for line in stream:
                    try:
                        boot_ok |= boot_matches(json.loads(line), pid, sha, after)
                    except (ValueError, TypeError):
                        continue
        if not boot_ok:
            problems.append("fresh_boot_for_current_process_and_commit_not_found")
    except (OSError, ValueError, subprocess.SubprocessError):
        problems.append("engine_process_or_checkout_unverified")
    opener = build_opener(ProxyHandler({}))
    for port, name in ((8000, "trezo-api"), (8001, "trezo-agents")):
        try:
            with opener.open(f"http://127.0.0.1:{port}/health", timeout=5) as response:
                value = json.loads(response.read(65536))
            if value.get("status") != "ok" or value.get("service") != name:
                raise ValueError("health_failed")
        except Exception:
            problems.append(name + "_health_unverified")
    return sorted(set(problems))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--books", type=Path, required=True)
    parser.add_argument("--supabase-url", required=True)
    parser.add_argument("--web-url", required=True)
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--expected-commit")
    parser.add_argument("--started-after")
    args = parser.parse_args()
    try:
        from dotenv import dotenv_values
        envs = {}
        for role, path in (("agents", "agents/.env"), ("api", "api/.env"), ("web", "web/.env.local")):
            if not (args.repo / path).is_file():
                raise ValueError("missing_env")
            envs[role] = {k.upper(): (v or "") for k, v in
                          dotenv_values(args.repo / path, interpolate=False).items()}
        books = json.loads(args.books.read_text(encoding="utf-8"))
        issues = config_issues(envs, books, args.supabase_url, args.web_url)
        if args.runtime:
            if not re.fullmatch(r"[0-9a-f]{40}", args.expected_commit or "") or not args.started_after:
                raise ValueError("missing_runtime_evidence")
            issues += runtime_issues(args.repo.resolve(), args.expected_commit, timestamp(args.started_after))
        print(json.dumps({"status": "BLOCKED" if issues else "CHECKS_PASSED", "issues": issues,
                          "runtime_checked": args.runtime, "changes_made": False,
                          "scope": "Configuration/process checks only. Database/Storage restore, per-book crypto-only settings, broker reconciliation, login and trading readiness still require verification."}, indent=2))
        return 2 if issues else 0
    except (ImportError, OSError, ValueError, TypeError, AttributeError):
        print('BLOCKED: unreadable or invalid inputs; use the agents venv and private restored configuration.', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
