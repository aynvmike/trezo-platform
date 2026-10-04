#!/usr/bin/env python3
"""Private, encrypted Trezo migration bundles; Python stdlib plus the age CLI.

Export requires all source writers stopped. Only the explicit host file/directory
allowlists and an optional operator-supplied database export directory are copied.
No services, brokers, live database or application configuration are modified.
Restore creates a NEW private staging directory, never a live checkout.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

VERSION = 1
HOST_FILES = (
    "agents/.env", "api/.env", "web/.env.local",
    "agents/app/knowledge/_proposals.json",
    "agents/app/knowledge/_digest_history.json",
    "agents/app/knowledge/_research_seen.json",
    "agents/app/data/crypto_discovered.json",
    "agents/app/memory/.usage_budget.json",
)
RUNTIME_JSON_FILES = frozenset(HOST_FILES[3:])
# Keep the private runtime directory contract aligned with install.RUNTIME_DIRS.
# The knowledge library is the one explicitly supported checkout-local tree.
HOST_DIRECTORIES = (
    "logs", "state", "agents/local_state", "agents/.cache", "agents/scratch",
    "agents/logs", "api/logs", "agents/.mem0", "agents/mem0_cache",
    "agents/.vectorstore", "agents/.chromadb", "agents/knowledge/library",
)
REPO_DIRECTORIES = frozenset({"agents/knowledge/library"})
REVIEW_KEYS = {"TREZO_RESEARCH_DB_PATH", "TREZO_REPO_DIR", "TREZO_WEB_BASE_URL",
               "WEB_INTERNAL_BASE_URL", "NEXT_PUBLIC_BASE_URL"}
CUSTOM_STATE_KEYS = {"TREZO_RESEARCH_DB_PATH"}
REQUIRED_HOST = {"host/agents/.env", "host/api/.env", "host/web/.env.local"}
REQUIRED_DB = {"database/roles.sql", "database/schema.sql", "database/data.sql",
               "database/source-inventory.private.json", "database/books.json"}
MAX_MEMBERS = 100000
MAX_MANIFEST = 16 * 1024 * 1024
MAX_BYTES = 100 * 1024 ** 3
CHUNK = 1024 * 1024


class BundleError(Exception):
    """Messages intentionally contain no source data or credentials."""


def is_link(path: Path) -> bool:
    st = path.lstat()
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def no_links(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        if part.exists() or part.is_symlink():
            if is_link(part):
                raise BundleError("Symlinks and Windows reparse points are not accepted.")
    return path


def outside_git(path: Path) -> None:
    # Include linked worktrees and bare repositories. An empty folder named
    # .git alone is not a checkout (some execution environments seed one).
    for parent in (path, *path.parents):
        marker = parent / ".git"
        if (marker.is_file() or (marker / "HEAD").is_file()
                or ((parent / "HEAD").is_file() and (parent / "objects").is_dir())):
            raise BundleError("Private bundles and staging must be outside every Git checkout.")


def private_directory(path: Path) -> Path:
    path = no_links(path)
    outside_git(path)
    if not path.is_dir():
        raise BundleError("The private working directory must already exist.")
    if os.name == "posix":
        st = path.stat()
        if st.st_mode & 0o077 or st.st_uid != os.getuid():
            raise BundleError("Private directory must be owned by this user with mode 0700.")
    return path


def safe_name(name: str) -> str:
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or any(ord(c) < 32 for c in name)):
        raise BundleError("Unsafe archive path.")
    parts = name.split("/")
    if any(not p or p in (".", "..") or p.endswith((".", " ")) for p in parts):
        raise BundleError("Unsafe archive path.")
    for part in parts:
        stem = part.split(".")[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}:
            raise BundleError("Archive path is not portable to Windows.")
    if PurePosixPath(name).is_absolute():
        raise BundleError("Unsafe archive path.")
    return name


def new_file(path: Path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")


def digest_file(path: Path) -> tuple[int, str]:
    digest, length = hashlib.sha256(), 0
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            length += len(chunk)
            digest.update(chunk)
    return length, digest.hexdigest()


def copy_regular(source: Path, target: Path) -> None:
    no_links(source)
    if not stat.S_ISREG(source.lstat().st_mode):
        raise BundleError("Only regular source files are accepted.")
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as src, new_file(target) as dst:
        before = os.fstat(src.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise BundleError("Source file changed type during export.")
        shutil.copyfileobj(src, dst, CHUNK)
        after = os.fstat(src.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise BundleError("Source changed during export; stop every writer and retry.")


def snapshot_sqlite(source: Path, target: Path) -> None:
    no_links(source)
    for suffix in ("-wal", "-shm", "-journal"):
        sibling = Path(str(source) + suffix)
        if sibling.exists() or sibling.is_symlink():
            no_links(sibling)
    if not stat.S_ISREG(source.lstat().st_mode):
        raise BundleError("SQLite source must be a regular file.")
    # Never copy the main SQLite file without committed WAL contents.
    with new_file(target):
        pass
    deadline = time.monotonic() + 90

    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise BundleError("SQLite snapshot timed out; confirm writers are stopped.")

    try:
        with contextlib.closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)) as src:
            with contextlib.closing(sqlite3.connect(target)) as dst:
                src.backup(dst, pages=256, progress=progress, sleep=0.05)
                if dst.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise BundleError("SQLite snapshot failed its integrity check.")
    except sqlite3.Error:
        raise BundleError("SQLite snapshot failed; no successful bundle was produced.") from None


def sqlite_source(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as fh:
        header = fh.read(16)
    return header == b"SQLite format 3\x00" or path.suffix in (".sqlite3", ".sqlite")


def collect_tree(source: Path, target: Path, sqlite_snapshots: bool = False) -> None:
    no_links(source)
    if not source.is_dir():
        raise BundleError("Database export input must be a directory.")
    target.mkdir(mode=0o700)
    seen = set()
    sqlite_files = set()
    if sqlite_snapshots:
        for entry in source.iterdir():
            no_links(entry)
            if sqlite_source(entry):
                sqlite_files.add(entry.name)
    for entry in sorted(source.iterdir()):
        safe_name(entry.name)
        if entry.name.casefold() in seen:
            raise BundleError("Source names collide on a case-insensitive filesystem.")
        seen.add(entry.name.casefold())
        no_links(entry)
        if sqlite_snapshots and any(entry.name == base + suffix for base in sqlite_files
                                    for suffix in ("-wal", "-shm", "-journal")):
            continue  # The SQLite backup API includes committed WAL content.
        if entry.name in {".git", ".venv", "venv", "node_modules"}:
            raise BundleError("Unexpected dependency or Git tree inside allowlisted runtime data.")
        if entry.is_dir():
            collect_tree(entry, target / entry.name, sqlite_snapshots)
        elif entry.name in sqlite_files:
            snapshot_sqlite(entry, target / entry.name)
        else:
            copy_regular(entry, target / entry.name)


def completeness(files: dict, directories: list[str], database_supplied: bool,
                 custom_state_keys: list[str] | None = None) -> dict:
    missing_host = sorted(name for name in REQUIRED_HOST if not files.get(name, {}).get("size"))
    missing_db = sorted(name for name in REQUIRED_DB if not files.get(name, {}).get("size"))
    if "database/storage" not in directories:
        missing_db.append("database/storage/")
    status = ("INCOMPLETE" if missing_host else "HOST_ONLY")
    if database_supplied:
        status = "INCOMPLETE" if missing_host or missing_db else "RECOVERY_MATERIAL_PRESENT_UNVERIFIED"
    if custom_state_keys:
        status = "INCOMPLETE"
    return {"status": status, "database_supplied": database_supplied,
            "missing_required_host": missing_host, "missing_database_material": missing_db,
            "custom_state_exports_unverified": custom_state_keys or [],
            "restore_tested": False, "cutover_authorized": False}


def configured_review_keys(stage: Path) -> list[str]:
    found = set()
    for relative in ("host/agents/.env", "host/api/.env", "host/web/.env.local"):
        path = stage / relative
        if not path.is_file():
            continue
        # Only key names escape this function, never configured values.
        with path.open(encoding="utf-8-sig", errors="replace") as fh:
            found.update(review_key_lines(fh))
    return sorted(found)


def review_key_lines(lines) -> set[str]:
    found = set()
    for line in lines:
        match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)", line)
        if match and match[1] in REVIEW_KEYS and match[2].strip().strip("\"'"):
            found.add(match[1])
    return found


def missing_optional(files: dict, directories: list[str]) -> list[str]:
    missing = ["host/" + p for p in HOST_FILES
               if "host/" + p not in files and "host/" + p not in REQUIRED_HOST]
    missing.extend("host/" + p + "/" for p in HOST_DIRECTORIES if "host/" + p not in directories)
    return sorted(missing)


def source_commit(repo: Path) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise BundleError("Cannot identify source Git commit.") from None
    if proc.returncode or not re.fullmatch(r"[0-9a-f]{40}", proc.stdout.strip()):
        raise BundleError("Source must be a Git checkout with a valid commit.")
    return proc.stdout.strip()


def make_archive(repo: Path, database: Path | None, temporary: Path, writers_stopped: bool,
                 host_state_root: Path | None = None) -> tuple[Path, dict]:
    if not writers_stopped:
        raise BundleError("Export requires --writers-stopped after stopping ALL source writers.")
    repo = no_links(repo)
    commit = source_commit(repo)
    state_source = private_directory(host_state_root) if host_state_root is not None else repo
    stage = temporary / "content"
    stage.mkdir(mode=0o700)
    for relative in HOST_FILES:
        # These modules atomically replace JSON beside their Python code. The
        # Linux installer therefore keeps five exact JSONs in the checkout;
        # it routes env files and runtime directory trees to private storage.
        source = (repo if relative in RUNTIME_JSON_FILES else state_source) / relative
        no_links(source)
        if not source.exists():
            continue
        target = stage / "host" / relative
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if source.suffix == ".sqlite3":
            snapshot_sqlite(source, target)
        else:
            copy_regular(source, target)
    for relative in HOST_DIRECTORIES:
        # This library includes tracked content; the installer preserves its
        # directory in the checkout and copies private additions there.
        source = (repo if relative in REPO_DIRECTORIES else state_source) / relative
        no_links(source)
        if source.exists():
            target = stage / "host" / relative
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            collect_tree(source, target, sqlite_snapshots=True)
    if database is not None:
        collect_tree(no_links(database), stage / "database")
    files, directories, folded = {}, [], set()
    for path in sorted(stage.rglob("*")):
        name = safe_name(path.relative_to(stage).as_posix())
        if name.casefold() in folded:
            raise BundleError("Bundle names collide on a case-insensitive filesystem.")
        folded.add(name.casefold())
        if path.is_dir():
            directories.append(name)
        else:
            size, checksum = digest_file(path)
            files[name] = {"size": size, "sha256": checksum}
    review = configured_review_keys(stage)
    manifest = {"version": VERSION, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "source_git_commit": commit, "writers_stopped": True,
                "files": files, "directories": directories,
                "missing_optional_host_files": missing_optional(files, directories),
                "host_configuration_review": review,
                "completeness": completeness(files, directories, database is not None,
                                             sorted(CUSTOM_STATE_KEYS.intersection(review)))}
    raw = json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_MANIFEST or len(files) + len(directories) >= MAX_MEMBERS:
        raise BundleError("Bundle exceeds supported inventory limits.")
    with new_file(stage / "manifest.json") as fh:
        fh.write(raw)
    archive = temporary / "payload.tar"
    with new_file(archive) as handle, tarfile.open(fileobj=handle, mode="w") as tar:
        for path in sorted(stage.rglob("*")):
            name = path.relative_to(stage).as_posix()
            info = tar.gettarinfo(str(path), arcname=name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o700 if path.is_dir() else 0o600
            if path.is_dir():
                tar.addfile(info)
            else:
                with path.open("rb") as fh:
                    tar.addfile(info, fh)
    validate_archive(archive)
    return archive, manifest


def json_unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise BundleError("Duplicate JSON manifest key.")
        out[key] = value
    return out


def validate_archive(archive: Path) -> dict:
    try:
        with tarfile.open(archive, "r:") as tar:
            members = {}
            folded = set()
            total = 0
            for member in tar:
                name = safe_name(member.name)
                if name.casefold() in folded or not (member.isfile() or member.isdir()):
                    raise BundleError("Duplicate, linked or unsupported archive entry.")
                if name != "manifest.json" and name.split("/")[0] not in ("host", "database"):
                    raise BundleError("Unexpected archive root.")
                folded.add(name.casefold())
                members[name] = member
                total += member.size
                if len(members) > MAX_MEMBERS or total > MAX_BYTES or member.size < 0:
                    raise BundleError("Archive exceeds supported size limits.")
            entry = members.get("manifest.json")
            if entry is None or not entry.isfile() or entry.size > MAX_MANIFEST:
                raise BundleError("Missing or oversized manifest.")
            manifest = json.loads(tar.extractfile(entry).read(), object_pairs_hook=json_unique)
            validate_manifest(manifest)
            files = manifest["files"]
            directories = set(manifest["directories"])
            if set(members) != set(files) | directories | {"manifest.json"}:
                raise BundleError("Extra or missing archive entries.")
            for name in directories:
                if not members[name].isdir() or members[name].size:
                    raise BundleError("Directory metadata mismatch.")
            for name, record in files.items():
                member = members[name]
                if not member.isfile() or member.size != record["size"]:
                    raise BundleError("File size or type differs from the manifest.")
                digest = hashlib.sha256()
                with tar.extractfile(member) as fh:
                    while chunk := fh.read(CHUNK):
                        digest.update(chunk)
                if digest.hexdigest() != record["sha256"]:
                    raise BundleError("File checksum differs from the manifest.")
            review = set()
            for name in REQUIRED_HOST.intersection(files):
                with io.TextIOWrapper(tar.extractfile(name), encoding="utf-8-sig", errors="replace") as fh:
                    review.update(review_key_lines(fh))
            if sorted(review) != manifest["host_configuration_review"]:
                raise BundleError("Host configuration review does not match encrypted files.")
            return manifest
    except BundleError:
        raise
    except (OSError, tarfile.TarError, ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise BundleError("Invalid or incomplete bundle; nothing was restored.") from None


def validate_manifest(manifest: dict) -> None:
    required = {"version", "created_at", "source_git_commit", "writers_stopped", "files",
                "directories", "missing_optional_host_files", "host_configuration_review", "completeness"}
    if (not isinstance(manifest, dict) or set(manifest) != required
            or type(manifest["version"]) is not int or manifest["version"] != VERSION
            or manifest["writers_stopped"] is not True
            or not re.fullmatch(r"[a-f0-9]{40}", manifest["source_git_commit"])):
        raise BundleError("Invalid manifest version, source commit or writer attestation.")
    dt.datetime.fromisoformat(manifest["created_at"])
    files, directories = manifest["files"], manifest["directories"]
    if not isinstance(files, dict) or not isinstance(directories, list):
        raise BundleError("Invalid manifest inventory.")
    if len(set(directories)) != len(directories) or set(files) & set(directories):
        raise BundleError("Duplicate manifest paths.")
    for name in (*files, *directories):
        safe_name(name)
        if name.split("/")[0] not in ("host", "database"):
            raise BundleError("Manifest path outside allowed roots.")
        for parent in PurePosixPath(name).parents:
            if str(parent) != "." and str(parent) not in directories:
                raise BundleError("Manifest omits a parent directory.")
    for name, record in files.items():
        if (not isinstance(record, dict) or set(record) != {"size", "sha256"}
                or type(record["size"]) is not int or record["size"] < 0
                or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"])):
            raise BundleError("Invalid manifest checksum record.")
        if name in ("host", "database"):
            raise BundleError("Archive roots must be directories.")
        if (name.startswith("host/") and name[5:] not in HOST_FILES
                and not any(name.startswith("host/" + root + "/") for root in HOST_DIRECTORIES)):
            raise BundleError("Host file is not on the explicit allowlist.")
    allowed_host_parents = {"host"}
    for name in (*HOST_FILES, *HOST_DIRECTORIES):
        allowed_host_parents.update(str(p) for p in PurePosixPath("host/" + name).parents if str(p) != ".")
    allowed_host_parents.update("host/" + name for name in HOST_DIRECTORIES)
    for name in directories:
        if (name.startswith("host/") and name not in allowed_host_parents
                and not any(name.startswith("host/" + root + "/") for root in HOST_DIRECTORIES)):
            raise BundleError("Host directory is not on the explicit allowlist.")
    supplied = "database" in directories
    review = manifest["host_configuration_review"]
    if not isinstance(review, list) or review != sorted(set(review)) or not set(review).issubset(REVIEW_KEYS):
        raise BundleError("Invalid host configuration review inventory.")
    if manifest["completeness"] != completeness(files, directories, supplied,
                                                sorted(CUSTOM_STATE_KEYS.intersection(review))):
        raise BundleError("Manifest completeness claim does not match its files.")
    expected_missing = missing_optional(files, directories)
    if manifest["missing_optional_host_files"] != expected_missing:
        raise BundleError("Manifest optional-file inventory does not match.")


def validate_staging(directory: Path) -> dict:
    """Validate exact private staged contents before an installer consumes them.

    This proves consistency with the stored manifest, not the sender's identity
    or database semantic correctness. The caller must still rehearse restoration.
    """
    directory = private_directory(directory)
    try:
        path = no_links(directory / "manifest.json")
        if not path.is_file() or path.stat().st_size > MAX_MANIFEST:
            raise BundleError("Missing or oversized staging manifest.")
        manifest = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=json_unique)
        validate_manifest(manifest)
        actual_files, actual_directories, folded = {}, [], set()
        total = 0
        for path in directory.rglob("*"):
            no_links(path)
            name = safe_name(path.relative_to(directory).as_posix())
            if name.casefold() in folded:
                raise BundleError("Case-insensitive staging path collision.")
            folded.add(name.casefold())
            if len(folded) > MAX_MEMBERS:
                raise BundleError("Staging exceeds supported inventory size.")
            if path.is_dir():
                actual_directories.append(name)
            elif name != "manifest.json":
                if not stat.S_ISREG(path.stat().st_mode):
                    raise BundleError("Unsupported staging file type.")
                size, checksum = digest_file(path)
                total += size
                if total > MAX_BYTES:
                    raise BundleError("Staging exceeds supported byte limit.")
                actual_files[name] = {"size": size, "sha256": checksum}
        if (actual_files != manifest["files"]
                or sorted(actual_directories) != sorted(manifest["directories"])):
            raise BundleError("Staging has changed, extra or missing files/directories.")
        if configured_review_keys(directory) != manifest["host_configuration_review"]:
            raise BundleError("Staging configuration review is inconsistent.")
        return manifest
    except BundleError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise BundleError("Invalid staging manifest or inventory.") from None


def age_command(arguments: list[str], destination) -> None:
    if shutil.which("age") is None:
        raise BundleError("Install the reviewed age CLI before creating or opening bundles.")
    # age reads passphrases interactively from its terminal. Never accept or set
    # a passphrase in command arguments, environment, Python memory or a log.
    try:
        result = subprocess.run(["age", *arguments], stdout=destination, check=False)
    except OSError:
        raise BundleError("Could not run age; no successful output was produced.") from None
    if result.returncode:
        raise BundleError("age failed or authentication was cancelled; no successful output was produced.")


def export_bundle(repo: Path, output: Path, work: Path, database: Path | None,
                  recipient: str | None, passphrase: bool, writers_stopped: bool,
                  host_state_root: Path | None = None) -> dict:
    work = private_directory(work)
    output = no_links(output)
    private_directory(output.parent)
    outside_git(output)
    if output.exists():
        raise BundleError("Output already exists; overwriting is forbidden.")
    if bool(recipient) == bool(passphrase):
        raise BundleError("Choose one age recipient or interactive passphrase encryption.")
    if recipient and not re.fullmatch(r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}", recipient):
        raise BundleError("Recipient must be an age1 public recipient key.")
    with tempfile.TemporaryDirectory(prefix="trezo-private-", dir=work) as name:
        archive, manifest = make_archive(repo, database, Path(name), writers_stopped, host_state_root)
        created = False
        try:
            with new_file(output) as target:
                created = True
                args = ["-p"] if passphrase else ["-r", recipient]
                age_command([*args, str(archive)], target)
                target.flush()
                os.fsync(target.fileno())
            if output.stat().st_size == 0:
                raise BundleError("age produced an empty output.")
        except BaseException:
            if created:
                output.unlink(missing_ok=True)
            raise
    size, checksum = digest_file(output)
    return {"status": manifest["completeness"]["status"], "files": len(manifest["files"]),
            "encrypted_bytes": size, "encrypted_sha256": checksum,
            "source_git_commit": manifest["source_git_commit"], "restore_tested": False}


@contextlib.contextmanager
def decrypted(bundle: Path, work: Path, identity: Path | None):
    work = private_directory(work)
    bundle = no_links(bundle)
    if not bundle.is_file():
        raise BundleError("Encrypted input must be a regular file.")
    if identity is not None:
        identity = no_links(identity)
        if not identity.is_file():
            raise BundleError("Identity must be a private age identity file.")
    with tempfile.TemporaryDirectory(prefix="trezo-private-", dir=work) as name:
        archive = Path(name) / "decrypted.tar"
        with new_file(archive) as fh:
            args = ["-d"]
            if identity is not None:
                args.extend(["-i", str(identity)])
            age_command([*args, str(bundle)], fh)
        yield archive, validate_archive(archive)


def restore_archive(archive: Path, destination: Path) -> dict:
    # Validation precedes creating the destination. Never use tar.extractall.
    manifest = validate_archive(archive)
    destination = no_links(destination)
    private_directory(destination.parent)
    outside_git(destination)
    if destination.exists():
        raise BundleError("Restore requires a NEW destination directory; overwrite is forbidden.")
    required = sum(r["size"] for r in manifest["files"].values()) + MAX_MANIFEST
    if shutil.disk_usage(destination.parent).free < required:
        raise BundleError("Insufficient space for staging restore.")
    destination.mkdir(mode=0o700)
    try:
        with tarfile.open(archive, "r:") as tar:
            for name in sorted(manifest["directories"], key=lambda n: (n.count("/"), n)):
                (destination / name).mkdir(mode=0o700)
            for name in ("manifest.json", *manifest["files"]):
                with tar.extractfile(name) as source, new_file(destination / name) as target:
                    shutil.copyfileobj(source, target, CHUNK)
        return {"status": manifest["completeness"]["status"], "files": len(manifest["files"]),
                "staging_only": True, "live_database_modified": False, "services_started": False}
    except BaseException:
        shutil.rmtree(destination)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="On POSIX create a private directory with mode 0700. On Windows restrict its ACL to yourself.\n"
               "The archive contains secrets. Never put it or decrypted files in Git. age -p prompts in a terminal.\n"
               "HOST_ONLY and INCOMPLETE bundles are not full database backups; present material is still unverified.")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="Encrypt explicitly allowlisted host files and optional database export")
    exp.add_argument("--repo", type=Path, required=True)
    exp.add_argument("--host-state-root", type=Path,
                     help="Explicit private env/runtime directory on an installed Linux host, same hostrelative layout. Five app JSONs and agents/knowledge/library still come from --repo. Default: all state directly from --repo, without following links.")
    exp.add_argument("--out", type=Path, required=True, help="NEW encrypted output, outside Git")
    exp.add_argument("--work-directory", type=Path, required=True, help="Existing private directory outside Git for temporary plaintext")
    exp.add_argument("--database-export-dir", type=Path, help="Whole directory; material-present requires roles.sql/schema.sql/data.sql, storage/, books.json, source-inventory.private.json")
    exp.add_argument("--writers-stopped", action="store_true", required=True, help="Attest all source writers are stopped; does not stop them")
    mode = exp.add_mutually_exclusive_group(required=True)
    mode.add_argument("--recipient", help="age1 public recipient key")
    mode.add_argument("--passphrase", action="store_true", help="Interactive age passphrase prompt, never passed through this script")
    for action in ("inspect", "restore"):
        cmd = sub.add_parser(action, help="Decrypt and verify" if action == "inspect" else "Decrypt, verify and stage in a NEW private directory")
        cmd.add_argument("bundle", type=Path)
        cmd.add_argument("--work-directory", type=Path, required=True)
        cmd.add_argument("--identity", type=Path, help="age private identity file; omit for passphrase bundles")
        if action == "restore":
            cmd.add_argument("--dest", type=Path, required=True, help="NEW private staging directory outside Git")
    args = parser.parse_args(argv)
    if os.name == "nt":
        print("Windows: restrict working, output and staging directory ACLs to yourself; this tool cannot verify ACLs.", file=sys.stderr)
    try:
        if args.command == "export":
            result = export_bundle(args.repo, args.out, args.work_directory, args.database_export_dir,
                                   args.recipient, args.passphrase, args.writers_stopped, args.host_state_root)
        else:
            with decrypted(args.bundle, args.work_directory, args.identity) as (archive, manifest):
                if args.command == "restore":
                    result = restore_archive(archive, args.dest)
                else:
                    result = {"version": manifest["version"], "source_git_commit": manifest["source_git_commit"],
                              "files": len(manifest["files"]), "completeness": manifest["completeness"],
                              "host_configuration_review": manifest["host_configuration_review"],
                              "checksums_verified": True}
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except BundleError as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError, tarfile.TarError):
        print("BLOCKED: private file or archive operation failed; no successful result was produced.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
