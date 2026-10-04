#!/usr/bin/env python3
"""Restore a verified official Supabase dump into an unused local target only.

Database import is not activation. Storage bytes, credentials, schema/RLS checks,
broker reconciliation and one-engine cutover remain separate operator steps.
Procedure: https://supabase.com/docs/guides/self-hosting/restore-from-platform
"""
from __future__ import annotations

import argparse
import configparser
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("portable_verify_migration", HERE.parent / "self_host" / "verify_migration.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class DatabaseError(Exception):
    """Sanitized operator message; never wrap raw SQL or connection errors."""


# A freshly initialized Auth service records its own schema migrations. That
# infrastructure metadata is the sole nonempty Auth-table exception; user data,
# sessions, identities and public application data must all be absent.
TABLE_FILTER = """c.relkind IN ('r','p') AND (
 n.nspname = 'public' OR
 (n.nspname = 'auth' AND c.relname <> 'schema_migrations') OR
 (n.nspname = 'storage' AND c.relname IN ('buckets','objects')))"""
META_SQL = """SELECT json_build_object('kind','meta',
 'server_addr',inet_server_addr()::text,
 'superuser',(SELECT rolsuper FROM pg_roles WHERE rolname=current_user),
 'other_clients',(SELECT count(*) FROM pg_stat_activity
    WHERE pid <> pg_backend_pid() AND backend_type='client backend'),
 'server_version_num',current_setting('server_version_num'));
"""
PREFLIGHT_SQL = """BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='120s';
""" + META_SQL + """
SELECT format('SELECT json_build_object(''kind'',''table'',''name'',%L,''rows'',count(*)) FROM %I.%I;',
 n.nspname||'.'||c.relname,n.nspname,c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE """ + TABLE_FILTER + """ ORDER BY n.nspname,c.relname
\\gexec
COMMIT;
"""
# Run again inside the SAME transaction as the import, after preflight and
# before the first dump file. This is a guard, not a means of stopping writers.
RESTORE_GUARD = """SET LOCAL statement_timeout='120s';
DO $trezo_guard$
DECLARE relation record; occupied bigint;
BEGIN
 IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname=current_user) THEN
  RAISE EXCEPTION 'target privileges unavailable';
 END IF;
 IF EXISTS (SELECT 1 FROM pg_stat_activity WHERE pid <> pg_backend_pid()
            AND backend_type='client backend') THEN
  RAISE EXCEPTION 'other client connections exist';
 END IF;
 PERFORM pg_advisory_xact_lock(728396104);
 FOR relation IN SELECT n.nspname,c.relname FROM pg_class c
 JOIN pg_namespace n ON n.oid=c.relnamespace WHERE """ + TABLE_FILTER + """ LOOP
  EXECUTE format('SELECT count(*) FROM %I.%I',relation.nspname,relation.relname) INTO occupied;
  IF occupied <> 0 THEN RAISE EXCEPTION 'target contains data'; END IF;
 END LOOP;
END
$trezo_guard$;
SET LOCAL statement_timeout=0;
"""


def private_path(path: Path, *, directory: bool = False) -> Path:
    try:
        if path.is_symlink():
            raise ValueError
        resolved = path.resolve(strict=True)
        if (directory and not resolved.is_dir()) or (not directory and not resolved.is_file()):
            raise ValueError
        if any(verify.is_git_checkout(parent) for parent in (resolved, *resolved.parents)):
            raise ValueError
        if os.name == "posix" and stat.S_IMODE(resolved.stat().st_mode) & 0o077:
            raise ValueError
        return resolved
    except (OSError, ValueError):
        raise DatabaseError("Inputs must be private regular files/directories outside Git (0700 directories, 0600 files).") from None


def connection(service: str, service_file: Path, port: int, passfile: Path | None = None) -> tuple[list[str], dict]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", service) or not 1024 <= port <= 65535:
        raise DatabaseError("Use a simple libpq service name and a local unprivileged port.")
    service_file = private_path(service_file)
    cfg = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        cfg.read_string(service_file.read_text(encoding="utf-8"))
        if cfg.defaults() or service not in cfg:
            raise ValueError
        profile = dict(cfg[service])
        # Prevent nested/alternate service resolution and socket/multi-host paths.
        allowed = {"host", "hostaddr", "port", "dbname", "user", "password", "passfile",
                   "sslmode", "sslrootcert", "sslcert", "sslkey", "application_name", "connect_timeout"}
        if set(profile) - allowed or not profile.get("dbname") or not profile.get("user"):
            raise ValueError
        if any(profile.get(key, "127.0.0.1") not in {"127.0.0.1", "::1", "localhost"}
               for key in ("host", "hostaddr")):
            raise ValueError
    except (OSError, ValueError, configparser.Error):
        raise DatabaseError("Service must describe one local database with explicit user/dbname; remote or unsupported profile refused.") from None
    selected_passfile = passfile or (Path(profile["passfile"]) if profile.get("passfile") else None)
    if selected_passfile:
        selected_passfile = private_path(selected_passfile)
    elif not profile.get("password"):
        raise DatabaseError("Configure a private passfile or password in the private service profile; no interactive password entry.")
    # Never inherit an ambient PGPASSWORD/PGOPTIONS/PGSERVICE override.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PG")}
    env.update(PGSERVICEFILE=str(service_file), PGCONNECT_TIMEOUT="10")
    if selected_passfile:
        env["PGPASSFILE"] = str(selected_passfile)
    # Explicit parameters override the service and force the local published DB
    # port. Docker NAT can legitimately report a private bridge server address.
    conninfo = f"service={service} host=127.0.0.1 hostaddr=127.0.0.1 port={port} application_name=trezo-portable-restore"
    return ["psql", "-X", "-w", "-qAt", "-v", "ON_ERROR_STOP=1", "--dbname", conninfo], env


def run_psql(command: list[str], env: dict, *, sql: str | None = None, restore: bool = False) -> str:
    try:
        result = subprocess.run(command, input=sql, text=True, env=env,
                                stdout=subprocess.DEVNULL if restore else subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=3600 if restore else 600, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise DatabaseError("psql unavailable or timed out; stop here and diagnose in a private database console.") from None
    if result.returncode:
        raise DatabaseError("psql failed; restore/verification is blocked. Raw database diagnostics were suppressed.")
    return result.stdout or ""


def preflight(command: list[str], env: dict) -> dict:
    raw = run_psql(command, env, sql=PREFLIGHT_SQL)
    try:
        meta, tables = None, {}
        for line in raw.splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item["kind"] == "meta" and meta is None:
                meta = item
            elif item["kind"] == "table" and item["name"] not in tables:
                if type(item["rows"]) is not int or item["rows"] < 0:
                    raise ValueError
                tables[item["name"]] = item["rows"]
            else:
                raise ValueError
        if not meta or meta["superuser"] is not True or type(meta["other_clients"]) is not int or meta["other_clients"] != 0:
            raise ValueError
        address = ipaddress.ip_address(meta["server_addr"])
        docker_or_loopback = (address.is_loopback or any(address in net for net in (
            ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"))))
        if not docker_or_loopback or int(meta["server_version_num"]) < 120000:
            raise ValueError
        if not {"auth.users", "auth.identities", "storage.buckets", "storage.objects"}.issubset(tables) or any(tables.values()):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise DatabaseError("Target is not verified empty/local/isolated Supabase, or preflight output was incomplete. Stop other clients; never delete data to pass.") from None
    return {"status": "EMPTY_TARGET", "tables_checked": len(tables),
            "postgres_major": int(meta["server_version_num"]) // 10000,
            "activation_authorized": False}


def validate_bundle(bundle: Path) -> dict:
    # The portable backup verifier validates all manifest hashes and refuses
    # partial archives. Import lazily so --help remains usable independently.
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("portable_backup", HERE / "backup.py")
        backup = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = backup
        spec.loader.exec_module(backup)
        manifest = backup.validate_staging(bundle)
        if manifest["completeness"]["status"] != "RECOVERY_MATERIAL_PRESENT_UNVERIFIED":
            raise ValueError
        return manifest
    except Exception:
        raise DatabaseError("Portable backup integrity verification failed; use the complete verified bundle, never an agent archive.") from None


def validate_dump_controls(path: Path) -> None:
    """Reject psql reconnect/include/shell controls in official plain exports.

    COPY data is opaque, not psql input. This is a format guard, not a SQL
    sandbox: import only the operator's trusted, unmodified Supabase CLI dump.
    """
    copying = False
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                text = line.strip()
                if copying:
                    if text == r"\.":
                        copying = False
                    continue
                if re.match(r"COPY\s.+\sFROM stdin;\s*$", text, re.I):
                    copying = True
                elif text.startswith("\\") and not re.fullmatch(r"\\(?:unrestrict|restrict) [A-Za-z0-9]+", text):
                    raise ValueError
        if copying:
            raise ValueError
    except (OSError, UnicodeError, ValueError):
        raise DatabaseError("Dump has unsupported psql controls or truncated COPY data; use unmodified official CLI exports.") from None


def source_inputs(bundle: Path, books_file: Path) -> tuple[dict, dict, dict[str, Path]]:
    bundle = private_path(bundle, directory=True)
    validate_bundle(bundle)
    folder = private_path(bundle / "database", directory=True)
    files = {name: private_path(folder / name) for name in ("roles.sql", "schema.sql", "data.sql", "source-inventory.private.json")}
    private_path(folder / "storage", directory=True)
    if any(files[name].stat().st_size == 0 for name in ("roles.sql", "schema.sql", "data.sql")):
        raise DatabaseError("Required official Supabase role/schema/data dump is empty.")
    for name in ("roles.sql", "schema.sql", "data.sql"):
        validate_dump_controls(files[name])
    try:
        expected = verify.books_from_file(private_path(books_file))
        source = verify.read_manifest(files["source-inventory.private.json"])
        if source["expected_books"] != expected or source["writers_stopped"] is not True:
            raise DatabaseError("Source inventory must match all three book slots and attest a frozen source.")
    except verify.CheckError:
        raise DatabaseError("Source inventory or three-book UUID file is invalid/incomplete.") from None
    return source, expected, files


def restore_database(command: list[str], env: dict, files: dict[str, Path], source: dict,
                     expected: dict, output: Path, *, confirm_empty_target: bool, writers_stopped: bool) -> dict:
    if not confirm_empty_target or not writers_stopped:
        raise DatabaseError("Restore requires --confirm-empty-target and --writers-stopped. These attestations do not stop services for you.")
    parent = private_path(output.parent, directory=True)
    output = parent / output.name
    if output.exists() or output.is_symlink():
        raise DatabaseError("Target inventory output must be a new private file.")
    preflight(command, env)
    # This is the supported Supabase order. No application migrations, table
    # drops, schema cleanup, or compatibility edits are generated by this tool.
    args = [*command, "--single-transaction", "--command", RESTORE_GUARD,
            "--file", str(files["roles.sql"]), "--file", str(files["schema.sql"]),
            "--command", "SET LOCAL session_replication_role = replica",
            "--file", str(files["data.sql"])]
    run_psql(args, env, restore=True)
    try:
        sql = (HERE.parent / "self_host" / "capture.sql").read_text(encoding="utf-8")
        target = verify.parse_capture(run_psql(command, env, sql=sql), expected, True)
        verify.write_private(output, target)
        comparison = verify.compare(source, target)
    except (OSError, verify.CheckError, DatabaseError):
        raise DatabaseError("Database import completed but inventory verification failed. Keep all writers stopped; do not activate or rerun restore.") from None
    return {"status": "DATABASE_ROWS_MATCH" if comparison["status"] == "MATCH" else "BLOCKED",
            "row_comparison": comparison, "storage_restored": False, "activation_authorized": False,
            "next": "Transfer Storage bytes using the supported S3 API procedure; verify schema/RLS/auth, private networking and broker state before a separate cutover."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "restore"))
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--books", required=True, type=Path)
    parser.add_argument("--service", required=True)
    parser.add_argument("--service-file", required=True, type=Path)
    parser.add_argument("--passfile", type=Path)
    parser.add_argument("--port", type=int, default=54322)
    parser.add_argument("--target-inventory", type=Path)
    parser.add_argument("--confirm-empty-target", action="store_true")
    parser.add_argument("--writers-stopped", action="store_true")
    args = parser.parse_args(argv)
    try:
        source, expected, files = source_inputs(args.bundle, args.books)
        command, env = connection(args.service, args.service_file, args.port, args.passfile)
        if args.action == "preflight":
            result = preflight(command, env)
        else:
            if not args.target_inventory:
                raise DatabaseError("Restore requires a new private --target-inventory path.")
            result = restore_database(command, env, files, source, expected, args.target_inventory,
                confirm_empty_target=args.confirm_empty_target, writers_stopped=args.writers_stopped)
        print(json.dumps(result, indent=2))
        return 2 if result["status"] == "BLOCKED" else 0
    except DatabaseError as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    except Exception:
        print("BLOCKED: Input or database operation failed; raw diagnostics suppressed. No activation is authorized.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
