#!/usr/bin/env python3
"""Prepare a fresh Linux installation. Never install, enable or start services.

Run as the dedicated service user after an administrator prepares Linux, systemd,
Python >=3.11 (including venv), Node >=20, npm, git and flock. The checkout and
decrypted restore must already exist; database recovery is a separate operation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

try:
    import pwd
except ImportError:  # Allow --help on Windows; real operations reject non-Linux.
    pwd = None

ORIGINS = {
    "https://github.com/aynvmike/trezo-platform",
    "https://github.com/aynvmike/trezo-platform.git",
    "git@github.com:aynvmike/trezo-platform.git",
    "ssh://git@github.com/aynvmike/trezo-platform.git",
}
SERVICES = ("trezo-agents", "trezo-api", "trezo-web")
ENV_FILES = ("agents/.env", "api/.env", "web/.env.local")
# Directory links keep mutable data outside the checkout. Source directories
# cannot be linked wholesale: several app modules derive paths from __file__.
RUNTIME_DIRS = (
    "logs", "state", "agents/local_state", "agents/.cache", "agents/scratch",
    "agents/logs", "api/logs", "agents/.mem0",
    "agents/mem0_cache", "agents/.vectorstore", "agents/.chromadb",
)
RUNTIME_FILES = (
    "agents/app/data/crypto_discovered.json",
    "agents/app/knowledge/_proposals.json",
    "agents/app/knowledge/_digest_history.json",
    "agents/app/knowledge/_research_seen.json",
    "agents/app/memory/.usage_budget.json",
)
LIBRARY = "agents/knowledge/library"


class Refusal(RuntimeError):
    """A fixed, secret-free diagnostic suitable for the console."""


def minimal_env(home: Path) -> dict[str, str]:
    # Never inherit broker keys, proxies containing credentials, NODE_OPTIONS,
    # PYTHONPATH, GIT_*, or npm configuration from an operator's shell.
    return {"PATH": os.defpath, "HOME": str(home), "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8", "CI": "1", "NEXT_TELEMETRY_DISABLED": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1", "GIT_TERMINAL_PROMPT": "0"}


def capture(command: list[str], cwd: Path, home: Path, timeout: int = 60):
    try:
        return subprocess.run(command, cwd=cwd, env=minimal_env(home),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Refusal("Required command failed or timed out; no activation performed.") from None


def git(checkout: Path, *args: str) -> str:
    result = capture(["git", "-c", "core.hooksPath=/dev/null", "-C", str(checkout), *args],
                     checkout, checkout)
    if result.returncode:
        raise Refusal("Git verification failed; no activation performed.")
    return result.stdout.decode("utf-8", "replace").strip()


def safe_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value):
        raise Refusal("Paths must be absolute and contain only letters, numbers, slash, dot, underscore or dash.")
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise Refusal("Installation roots must not contain parent traversal or symlinks.")
    return path


def absent(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise Refusal("A destination already exists. Fresh installation required; nothing is overwritten.")


def private_directory(path: Path) -> None:
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise Refusal("Private state must be outside every Git checkout.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise Refusal("Private state must be owned by the service user with mode0700.")


def check_tree(path: Path) -> None:
    """Restores contain only regular files/directories, never followed links."""
    if path.is_symlink():
        raise Refusal("Restored files must not contain symlinks or special files.")
    for item in [path, *path.rglob("*")]:
        kind = item.lstat().st_mode
        if not (stat.S_ISREG(kind) or stat.S_ISDIR(kind)):
            raise Refusal("Restored files must not contain symlinks or special files.")


def copy_private(source: Path, destination: Path) -> None:
    check_tree(source)
    absent(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if source.is_dir():
        shutil.copytree(source, destination)
        for item in [destination, *destination.rglob("*")]:
            item.chmod(0o700 if item.is_dir() else 0o600)
    else:
        shutil.copyfile(source, destination)
        destination.chmod(0o600)


def library_copy_plan(checkout: Path, restore: Path) -> list[tuple[Path, Path]]:
    """The library mixes versioned material and ignored private additions.

    Preserve the versioned files in place. Never replace the whole directory or
    silently overwrite a newer reviewed version with a restored copy.
    """
    destination = checkout / LIBRARY
    tracked = set(git(checkout, "ls-files", "--", LIBRARY).splitlines())
    if destination.exists():
        check_tree(destination)
        if not destination.is_dir():
            raise Refusal("Knowledge library destination is not a directory.")
        for item in destination.rglob("*"):
            if item.is_file() and item.relative_to(checkout).as_posix() not in tracked:
                raise Refusal("Knowledge library already contains private files; fresh installation required.")
    source = restore / LIBRARY
    if not source.exists():
        return []
    if not source.is_dir():
        raise Refusal("Restored knowledge library must be a directory.")
    plan = []
    for item in source.rglob("*"):
        if item.is_dir():
            continue
        target = destination / item.relative_to(source)
        if target.exists():
            if (target.relative_to(checkout).as_posix() not in tracked or not target.is_file()
                    or item.read_bytes() != target.read_bytes()):
                raise Refusal("Restored knowledge library conflicts with reviewed checkout; no files overwritten.")
        else:
            plan.append((item, target))
    return plan


def verify_checkout(checkout: Path, commit: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise Refusal("Expected commit must be the full lowercase40-character reviewed SHA.")
    if git(checkout, "rev-parse", "--show-toplevel") != str(checkout):
        raise Refusal("Checkout must be the repository root.")
    if git(checkout, "remote", "get-url", "origin") not in ORIGINS:
        raise Refusal("Origin is not the fixed Trezo GitHub repository.")
    if git(checkout, "rev-parse", "HEAD") != commit:
        raise Refusal("Checkout does not match the reviewed commit.")
    if git(checkout, "status", "--porcelain", "--untracked-files=no"):
        raise Refusal("Tracked checkout files are modified; refusing preparation/build.")


def prerequisites(checkout: Path, user: str) -> dict[str, str]:
    if platform.system() != "Linux" or not Path("/run/systemd/system").is_dir():
        raise Refusal("A native Linux host booted with systemd is required.")
    if sys.version_info < (3, 11):
        raise Refusal("Python3.11 or newer is required.")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", user):
        raise Refusal("Invalid service user.")
    try:
        account = pwd.getpwnam(user)
    except KeyError:
        raise Refusal("Administrator must create the dedicated service user first.") from None
    if os.getuid() == 0 or os.getuid() != account.pw_uid:
        raise Refusal("Run preparation/build as the dedicated non-root service user.")
    tools = {}
    for name in ("node", "npm", "git", "systemctl", "flock"):
        found = shutil.which(name, path=os.defpath)
        if not found:
            raise Refusal("Required system tool missing: " + name)
        tools[name] = str(Path(found).resolve())
    node = capture([tools["node"], "--version"], checkout, checkout)
    if node.returncode or not re.match(rb"v(?:2[0-9]|[3-9][0-9])\.", node.stdout):
        raise Refusal("Node20 or newer is required from the system PATH.")
    for service in SERVICES:
        result = capture([tools["systemctl"], "show", service + ".service",
                          "--property=LoadState", "--value"], checkout, checkout)
        if result.stdout.strip() != b"not-found":
            raise Refusal("An existing service or an unreadable systemd state blocks fresh installation.")
    tools["python"] = str(Path(sys.executable).resolve())
    return tools


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    path.chmod(0o600)


def validate_restore(restore: Path) -> dict:
    if restore.name != "host":
        raise Refusal("Restore root must be the host directory inside verified migration staging.")
    spec = importlib.util.spec_from_file_location("trezo_portable_backup", Path(__file__).with_name("backup.py"))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.validate_staging(restore.parent)
    except Exception:
        raise Refusal("Migration staging validation failed. Verify manifest, file hashes, completeness and private permissions.") from None


def render_units(checkout: Path, private: Path, user: str, tools: dict[str, str]) -> dict[str, str]:
    values = {"CHECKOUT": str(checkout), "PRIVATE": str(private), "USER": user,
              "NODE": tools["node"], "FLOCK": tools["flock"]}
    rendered = {}
    for service in SERVICES:
        body = (Path(__file__).parent / "templates" / (service + ".service.in")).read_text()
        for key, value in values.items():
            body = body.replace("@" + key + "@", value)
        if re.search(r"@[A-Z]+@", body):
            raise Refusal("Unresolved service template placeholder.")
        rendered[service + ".service"] = body
    return rendered


def prepare(checkout: Path, private: Path, restore: Path, commit: str,
            user: str, tools: dict[str, str]) -> dict:
    if private == checkout or checkout in private.parents or private in checkout.parents:
        raise Refusal("Private state and checkout must be separate directories.")
    manifest = validate_restore(restore)
    private_directory(private)
    for destination in (private / "install", private / "runtime", private / "units"):
        absent(destination)
    for relative in (*ENV_FILES, *RUNTIME_DIRS, *RUNTIME_FILES):
        absent(checkout / relative)
        # Fail if a future revision stops ignoring private/runtime data.
        ignored = relative + "/" if relative in RUNTIME_DIRS else relative
        if capture(["git", "-C", str(checkout), "check-ignore", "--quiet", ignored],
                   checkout, checkout).returncode:
            raise Refusal("A private/runtime destination is not protected by gitignore.")
    check_tree(restore)
    for relative in ENV_FILES:
        source = restore / relative
        if not source.is_file() or not source.stat().st_size:
            raise Refusal("The restored host is missing one of the three required environment files.")
    for relative in RUNTIME_DIRS:
        if (restore / relative).exists() and not (restore / relative).is_dir():
            raise Refusal("A restored runtime directory has the wrong type.")
    for relative in RUNTIME_FILES:
        if (restore / relative).exists() and not (restore / relative).is_file():
            raise Refusal("A restored runtime file has the wrong type.")
    library_plan = library_copy_plan(checkout, restore)
    # Directory patterns ending in slash do not ignore a symlink to that
    # directory. Add explicit local-only excludes without editing tracked code.
    exclude = Path(git(checkout, "rev-parse", "--git-path", "info/exclude"))
    if not exclude.is_absolute():
        exclude = checkout / exclude
    if exclude.is_symlink() or not exclude.parent.is_dir():
        raise Refusal("Local git exclude destination is unsafe.")
    units = render_units(checkout, private, user, tools)
    # All validation above precedes changes. A partial copy is left private and
    # visibly incomplete; retries never overwrite it or activate an engine.
    for directory in ("install", "runtime", "units", "runtime/home"):
        (private / directory).mkdir(parents=True, mode=0o700)
    with exclude.open("a", encoding="utf-8") as stream:
        stream.write("\n# Portable private runtime symlinks\n")
        stream.writelines("/" + path + "\n" for path in RUNTIME_DIRS)
    for relative in ENV_FILES:
        target = private / "runtime" / relative
        copy_private(restore / relative, target)
        (checkout / relative).symlink_to(target)
    for relative in RUNTIME_DIRS:
        target = private / "runtime" / relative
        source = restore / relative
        if source.exists():
            if not source.is_dir():
                raise Refusal("A restored runtime directory has the wrong type.")
            copy_private(source, target)
        else:
            target.mkdir(parents=True, mode=0o700)
        (checkout / relative).parent.mkdir(parents=True, exist_ok=True)
        (checkout / relative).symlink_to(target, target_is_directory=True)
    copied_files = []
    for relative in RUNTIME_FILES:
        if (restore / relative).exists():
            if not (restore / relative).is_file():
                raise Refusal("A restored runtime file has the wrong type.")
            copy_private(restore / relative, checkout / relative)
            copied_files.append(relative)
    for source, target in library_plan:
        copy_private(source, target)
    for filename, body in units.items():
        destination = private / "units" / filename
        destination.write_text(body, encoding="utf-8")
        destination.chmod(0o600)
    receipt = {"schema": 1, "status": "PREPARED_NOT_BUILT_NOT_ACTIVE", "commit": commit,
               "checkout": str(checkout), "private_root": str(private), "service_user": user,
               "tools": tools, "repo_local_runtime_files": copied_files,
               "repo_local_runtime_directories": [LIBRARY],
               "source_git_commit": manifest.get("source_git_commit"),
               "source_completeness": manifest.get("completeness"),
               "created_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    write_json(private / "install" / "prepared.json", receipt)
    return receipt


def run_step(name: str, command: list[str], cwd: Path, private: Path,
             timeout: int = 1800, extra_env: dict | None = None) -> None:
    """Record only outcome/timing: tool output can contain secrets, so discard it."""
    start = time.monotonic()
    env = minimal_env(private / "runtime" / "home")
    env.update(extra_env or {})
    try:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        code = result.returncode
    except (OSError, subprocess.TimeoutExpired):
        code = -1
    with (private / "install" / "build.log").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"step": name, "exit_code": code,
                                 "seconds": round(time.monotonic() - start, 1)}) + "\n")
    if code:
        raise Refusal("Build step failed: " + name + ". No service activated; inspect private build.log outcome.")


def build(checkout: Path, private: Path, commit: str, user: str, tools: dict[str, str]) -> dict:
    private_directory(private)
    try:
        receipt = json.loads((private / "install" / "prepared.json").read_text())
    except (OSError, ValueError):
        raise Refusal("Preparation receipt missing or invalid.") from None
    if any(receipt.get(k) != v for k, v in {"commit": commit, "checkout": str(checkout),
            "private_root": str(private), "service_user": user, "tools": tools}.items()):
        raise Refusal("Preparation receipt does not match this build.")
    for path in (checkout / "agents/.venv", checkout / "node_modules", checkout / "web/.next",
                 checkout / "api/dist", private / "install/build.log", private / "install/built.json"):
        absent(path)
    for relative in ENV_FILES:
        if not (checkout / relative).is_symlink() or (checkout / relative).resolve() != private / "runtime" / relative:
            raise Refusal("Environment link changed since preparation.")
    log = private / "install/build.log"
    log.touch(mode=0o600)
    venv = checkout / "agents/.venv"
    run_step("create_python_venv", [tools["python"], "-m", "venv", str(venv)], checkout, private)
    python = str(venv / "bin/python")
    run_step("python_dependencies", [python, "-m", "pip", "install", "-r", "agents/requirements.txt"], checkout, private)
    run_step("npm_ci_root", [tools["npm"], "ci", "--include=dev"], checkout, private)
    run_step("build_api", [tools["npm"], "run", "build:api"], checkout, private)
    run_step("build_web", [tools["npm"], "run", "build:web"], checkout, private,
             extra_env={"NODE_ENV": "production"})
    # Detached guard checkout contains no restored .env or local database files.
    stage = private / "install/guard-checkout"
    absent(stage)
    run_step("stage_guards", [tools["git"], "-c", "core.hooksPath=/dev/null", "-C", str(checkout),
                             "worktree", "add", "--detach", str(stage), commit], checkout, private)
    run_step("agent_guard_suites", [python, "-m", "tests.run_all"], stage / "agents", private)
    verify_checkout(checkout, commit)
    result = {"schema": 1, "status": "BUILT_NOT_ACTIVE", "commit": commit,
              "checkout": str(checkout), "private_root": str(private), "service_user": user,
              "services_started": False, "database_restored": False,
              "created_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    write_json(private / "install/built.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "build"))
    parser.add_argument("--checkout", default="/srv/trezo/app")
    parser.add_argument("--private-root", default="/srv/trezo/private")
    parser.add_argument("--restore-root", default="/srv/trezo/private/restore/host")
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--service-user", default="trezo")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        checkout, private, restore = map(safe_path, (args.checkout, args.private_root, args.restore_root))
        verify_checkout(checkout, args.expected_commit)
        tools = prerequisites(checkout, args.service_user)
        if args.operation == "prepare":
            result = prepare(checkout, private, restore, args.expected_commit, args.service_user, tools)
        else:
            result = build(checkout, private, args.expected_commit, args.service_user, tools)
        print(json.dumps({"status": result["status"], "commit": result["commit"], "services_started": False}))
        return 0
    except Refusal as error:
        print("REFUSED: " + str(error), file=sys.stderr)
    except Exception:
        # Paths, command errors and config content are deliberately not echoed.
        print("INCOMPLETE: local preparation/build failed; no service activated.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
