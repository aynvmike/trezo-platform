#!/usr/bin/env python3
"""Read-only restore inventory; stdlib + psql. No cutover or broker operations.

Connection credentials belong in libpq service/pass files, never CLI arguments.
The comparison proves selected row consistency, not backup completeness, RLS
correctness, broker agreement, or permission to start the engine.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

FORMAT = 1
SLOTS = {"primary", "acct2", "acct3"}
REQUIRED = {
    "public.trading_accounts", "public.bot_settings", "public.paper_accounts",
    "public.paper_positions", "public.schema_migrations", "auth.users",
    "auth.identities", "storage.buckets", "storage.objects",
}


class CheckError(Exception):
    """Only deliberately sanitized messages cross the CLI boundary."""


def books_from_file(path: Path) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != SLOTS:
            raise ValueError
        result = {slot: str(uuid.UUID(book)) for slot, book in value.items()}
        if len(set(result.values())) != 3:
            raise ValueError
        return result
    except (OSError, ValueError, TypeError, AttributeError):
        raise CheckError("Books file must map primary, acct2 and acct3 to three distinct UUIDs.") from None


def validate(manifest: dict) -> None:
    try:
        if manifest["format"] != FORMAT:
            raise ValueError
        expected = manifest["expected_books"]
        if set(expected) != SLOTS or len(set(expected.values())) != 3:
            raise ValueError
        if any(str(uuid.UUID(v)) != v for v in expected.values()):
            raise ValueError
        tables = manifest["tables"]
        if not REQUIRED.issubset(tables):
            raise ValueError
        for table in tables.values():
            if (type(table["rows"]) is not int or table["rows"] < 0
                    or not re.fullmatch(r"[a-f0-9]{32}", table["fingerprint"])):
                raise ValueError
        books = manifest["books"]
        if not isinstance(books, list):
            raise ValueError
        keyed = {b["account_key"]: b for b in books}
        if len(keyed) != len(books):
            raise ValueError
        # Additional inactive historical books are preserved, never deleted.
        active = {b["account_key"] for b in books if b["is_active"] is True}
        if active != set(expected.values()):
            raise ValueError
        for key in expected.values():
            book = keyed[key]
            if (book["is_paper"] is not True or book["broker"] != "alpaca"
                    or book["owner_count"] != 1 or book["settings_count"] != 1
                    or book["account_count"] != 1):
                raise ValueError
        if type(manifest["writers_stopped"]) is not bool:
            raise ValueError
        if int(manifest["server_version_num"]) < 120000:
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise CheckError("Inventory incomplete or book identity/account/settings validation failed.") from None


def parse_capture(text: str, expected: dict, writers_stopped: bool) -> dict:
    manifest = {
        "format": FORMAT, "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "writers_stopped": writers_stopped, "expected_books": expected,
        "books": [], "tables": {},
    }
    try:
        for line in text.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            kind = row.pop("kind")
            if kind == "meta" and "server_version_num" not in manifest:
                manifest["server_version_num"] = row["server_version_num"]
            elif kind == "book":
                manifest["books"].append(row)
            elif kind == "table":
                name = row.pop("name")
                if name in manifest["tables"]:
                    raise ValueError
                manifest["tables"][name] = row
            else:
                raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise CheckError("psql returned an invalid or incomplete inventory.") from None
    validate(manifest)
    return manifest


def capture(service: str, expected: dict, writers_stopped: bool) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", service):
        raise CheckError("Use a libpq service name containing only letters, numbers, underscores or hyphens.")
    sql = Path(__file__).with_name("capture.sql").read_text(encoding="utf-8")
    try:
        result = subprocess.run(
            ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-w", "service=" + service],
            input=sql, capture_output=True, text=True, timeout=600, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise CheckError("psql unavailable or timed out; no inventory was written.") from None
    if result.returncode:
        # Raw connection errors can contain credentials; never echo stderr.
        raise CheckError("psql failed; no inventory was written. Diagnose using a private database console.")
    return parse_capture(result.stdout, expected, writers_stopped)


def write_private(path: Path, value: dict) -> None:
    resolved = path.resolve()
    if any(is_git_checkout(parent) for parent in resolved.parents):
        raise CheckError("Write private inventories outside the Git checkout.")
    try:
        fd = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2, sort_keys=True, allow_nan=False)
            fh.write("\n")
    except (OSError, ValueError):
        raise CheckError("Could not create inventory; output must be a new file in an existing private directory.") from None


def is_git_checkout(directory: Path) -> bool:
    marker = directory / ".git"
    if marker.is_dir():
        return (marker / "HEAD").is_file()
    try:
        return marker.is_file() and marker.read_text(encoding="utf-8").startswith("gitdir:")
    except (OSError, UnicodeError):
        return True  # Unreadable metadata is not permission to place private files there.


def read_manifest(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CheckError("Cannot read inventory JSON.") from None
    validate(result)
    return result


def compare(source: dict, target: dict) -> dict:
    validate(source)
    validate(target)
    issues = []
    if not source["writers_stopped"] or not target["writers_stopped"]:
        issues.append("writers_not_confirmed_stopped")
    if source["expected_books"] != target["expected_books"]:
        issues.append("book_slot_mapping_changed")
    source_books = sorted(source["books"], key=lambda b: b["account_key"])
    target_books = sorted(target["books"], key=lambda b: b["account_key"])
    if source_books != target_books:
        issues.append("book_ownership_or_account_state_changed")
    left, right = source["tables"], target["tables"]
    missing = sorted(set(left) - set(right))
    extra = sorted(set(right) - set(left))
    changed = sorted(name for name in set(left) & set(right) if left[name] != right[name])
    if missing or extra or changed:
        issues.append("table_inventory_differs")
    return {
        "status": "MATCH" if not issues else "BLOCKED", "issues": issues,
        "missing_tables": missing, "extra_tables": extra, "changed_tables": changed,
        "source_postgres_major": int(source["server_version_num"]) // 10000,
        "target_postgres_major": int(target["server_version_num"]) // 10000,
        "scope": "Row consistency only; storage files, schema/RLS, broker reconciliation and restore rehearsal remain required.",
        "cutover_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    take = subs.add_parser("capture", help="Read inventory using psql and a libpq service profile")
    take.add_argument("--service", required=True)
    take.add_argument("--books", type=Path, required=True)
    take.add_argument("--out", type=Path, required=True)
    take.add_argument("--writers-stopped", action="store_true",
                      help="Attest ALL writers stopped; does not stop them for you")
    check = subs.add_parser("compare", help="Compare two private inventories offline")
    check.add_argument("source", type=Path)
    check.add_argument("target", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            value = capture(args.service, books_from_file(args.books), args.writers_stopped)
            write_private(args.out, value)
            print("Inventory written. No database or broker changes were made.")
            return 0
        result = compare(read_manifest(args.source), read_manifest(args.target))
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "MATCH" else 2
    except CheckError as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
