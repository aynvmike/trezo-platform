"""Offline DB restore guards; never invoke a real database or broker."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("trezo_portable_database_test", HERE / "database.py")
db = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(db)


def inventory():
    books = {slot: f"00000000-0000-4000-8000-{i:012d}"
             for i, slot in enumerate(("primary", "acct2", "acct3"), 1)}
    return {"format": 1, "captured_at": "2026-10-04T00:00:00Z", "writers_stopped": True,
            "expected_books": books, "server_version_num": "170006",
            "tables": {name: {"rows": 3, "fingerprint": "a" * 32} for name in db.verify.REQUIRED},
            "books": [{"account_key": key, "owner_id": books["primary"], "is_paper": True,
                       "is_active": True, "broker": "alpaca", "owner_count": 1,
                       "settings_count": 1, "account_count": 1} for key in books.values()]}


def empty_target(**overrides):
    meta = dict(kind="meta", server_addr="172.18.0.2", superuser=True,
                other_clients=0, server_version_num="170006")
    meta.update(overrides)
    tables = [dict(kind="table", name=name, rows=0) for name in (
        "auth.users", "auth.identities", "auth.sessions", "storage.buckets", "storage.objects")]
    return "\n".join(json.dumps(row) for row in [meta, *tables])


def capture(value):
    rows = [{"kind": "meta", "server_version_num": value["server_version_num"]}]
    rows += [{"kind": "book", **row} for row in value["books"]]
    rows += [{"kind": "table", "name": name, **row} for name, row in value["tables"].items()]
    return "\n".join(json.dumps(row) for row in rows)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/tmp" if Path("/tmp").is_dir() else None)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir(mode=0o700)
        self.folder = self.bundle / "database"
        self.folder.mkdir(mode=0o700)
        (self.folder / "storage").mkdir(mode=0o700)
        self.files = {name: self.write(self.folder / name, "-- trusted official dump fixture\n")
                      for name in ("roles.sql", "schema.sql", "data.sql")}
        self.source = inventory()
        self.write(self.folder / "source-inventory.private.json", json.dumps(self.source))
        self.books = self.write(self.root / "books.json", json.dumps(self.source["expected_books"]))
        self.service_file = self.write(self.root / "pg_service.conf", "[trezo-target]\nhost=127.0.0.1\nuser=postgres\ndbname=postgres\npassword=NOT_A_REAL_PASSWORD\n")
        self.command, self.env = db.connection("trezo-target", self.service_file, 54322)
        self.output = self.root / "target-inventory.private.json"

    def write(self, path, text):
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
        return path

    def run_restore(self, **flags):
        return db.restore_database(self.command, self.env, self.files, self.source,
                                   self.source["expected_books"], self.output,
                                   confirm_empty_target=flags.get("confirm", True),
                                   writers_stopped=flags.get("stopped", True))

    def test_connection_forces_local_host_and_port_without_secret_arguments(self):
        args = " ".join(self.command)
        self.assertIn("host=127.0.0.1 hostaddr=127.0.0.1 port=54322", args)
        self.assertNotIn("NOT_A_REAL_PASSWORD", args)
        self.assertIn("-w", self.command)
        self.assertIn("-X", self.command)
        self.assertIn("ON_ERROR_STOP=1", self.command)
        with patch.dict(os.environ, {"PGPASSWORD": "secret", "PGOPTIONS": "malicious"}):
            _, env = db.connection("trezo-target", self.service_file, 54322)
        self.assertNotIn("PGPASSWORD", env)
        self.assertNotIn("PGOPTIONS", env)

    def test_remote_profile_and_service_injection_are_refused(self):
        for host in ("cloud.supabase.co", "100.115.119.32", "/var/run/postgresql", "127.0.0.1,cloud"):
            self.write(self.service_file, f"[trezo-target]\nhost={host}\nuser=postgres\ndbname=postgres\npassword=secret\n")
            with self.subTest(host=host), self.assertRaises(db.DatabaseError):
                db.connection("trezo-target", self.service_file, 54322)
        with self.assertRaises(db.DatabaseError):
            db.connection("target host=remote", self.service_file, 54322)

    def test_preflight_is_read_only_and_accepts_docker_bridge(self):
        with patch.object(db, "run_psql", return_value=empty_target()) as run:
            result = db.preflight(self.command, self.env)
        self.assertEqual(result["status"], "EMPTY_TARGET")
        self.assertFalse(result["activation_authorized"])
        self.assertIn("READ ONLY", run.call_args.kwargs["sql"])

    def test_preflight_refuses_writers_non_superuser_and_global_server_address(self):
        for override in ({"other_clients": 1}, {"other_clients": True}, {"superuser": False},
                         {"server_addr": "8.8.8.8"}, {"server_addr": None}):
            with self.subTest(override=override), patch.object(db, "run_psql", return_value=empty_target(**override)), self.assertRaises(db.DatabaseError):
                db.preflight(self.command, self.env)

    def test_preflight_refuses_populated_auth_or_public_and_malformed_or_missing_rows(self):
        for raw in ("", "not json", '{"kind":"meta"}',
                    empty_target().replace('"rows": 0', '"rows": 1', 1),
                    empty_target() + '\n{"kind":"table","name":"public.paper_accounts","rows":1}',
                    empty_target().replace('"rows": 0', '"rows": null', 1),
                    "\n".join(empty_target().splitlines()[:-1])):
            with self.subTest(raw=raw[:30]), patch.object(db, "run_psql", return_value=raw), self.assertRaises(db.DatabaseError):
                db.preflight(self.command, self.env)

    def test_restore_requires_both_attestations_before_psql(self):
        for flags in ({"confirm": False}, {"stopped": False}):
            with patch.object(db, "run_psql") as run, self.assertRaises(db.DatabaseError):
                self.run_restore(**flags)
            run.assert_not_called()

    def test_restore_preserves_official_transaction_order_and_compares_private_inventory(self):
        with patch.object(db, "run_psql", side_effect=[empty_target(), "", capture(self.source)]) as run:
            result = self.run_restore()
        args = run.call_args_list[1].args[0]
        self.assertIn("--single-transaction", args)
        ordered = [str(self.files["roles.sql"]), str(self.files["schema.sql"]),
                   "SET LOCAL session_replication_role = replica", str(self.files["data.sql"])]
        self.assertEqual(sorted(args.index(item) for item in ordered), [args.index(item) for item in ordered])
        self.assertIn(db.RESTORE_GUARD, args)
        self.assertNotIn("DROP TABLE", db.RESTORE_GUARD)
        self.assertEqual(result["status"], "DATABASE_ROWS_MATCH")
        self.assertFalse(result["activation_authorized"])
        self.assertFalse(result["storage_restored"])
        self.assertTrue(self.output.is_file())
        if os.name == "posix":
            self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_import_failure_does_not_capture_or_write_inventory(self):
        with patch.object(db, "run_psql", side_effect=[empty_target(), db.DatabaseError("psql failed")]) as run, self.assertRaises(db.DatabaseError):
            self.run_restore()
        self.assertEqual(run.call_count, 2)
        self.assertFalse(self.output.exists())

    def test_failed_verification_after_import_is_explicitly_not_a_retry_instruction(self):
        with patch.object(db, "run_psql", side_effect=[empty_target(), "", db.DatabaseError("psql failed")]), self.assertRaises(db.DatabaseError) as raised:
            self.run_restore()
        self.assertIn("import completed", str(raised.exception))
        self.assertIn("do not activate or rerun", str(raised.exception))

    def test_changed_target_rows_block_activation_even_after_successful_sql(self):
        changed = copy.deepcopy(self.source)
        changed["tables"]["public.bot_settings"]["fingerprint"] = "b" * 32
        with patch.object(db, "run_psql", side_effect=[empty_target(), "", capture(changed)]):
            result = self.run_restore()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["activation_authorized"])

    def test_psql_errors_are_sanitized_and_restore_stdout_is_discarded(self):
        for failure in (subprocess.CompletedProcess([], 1, "secret-output", "SECRET_PASSWORD"),
                        subprocess.TimeoutExpired("SECRET_PASSWORD", 1)):
            options = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
            with patch.object(db.subprocess, "run", **options) as run, self.assertRaises(db.DatabaseError) as raised:
                db.run_psql(self.command, self.env, restore=True)
            self.assertNotIn("SECRET", str(raised.exception))
            self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)

    def test_source_requires_complete_matching_three_book_inventory_and_storage(self):
        with patch.object(db, "validate_bundle"):
            source, expected, files = db.source_inputs(self.bundle, self.books)
            self.assertEqual(source["expected_books"], expected)
            self.assertEqual(files["roles.sql"], self.files["roles.sql"].resolve())
            for invalid in ({}, {**self.source, "writers_stopped": False}):
                self.write(self.folder / "source-inventory.private.json", json.dumps(invalid))
                with self.assertRaises(db.DatabaseError):
                    db.source_inputs(self.bundle, self.books)
            self.write(self.folder / "source-inventory.private.json", json.dumps(self.source))
            (self.folder / "storage").rmdir()
            with self.assertRaises(db.DatabaseError):
                db.source_inputs(self.bundle, self.books)

    def test_actual_backup_manifest_contract_and_tamper_refusal(self):
        spec = importlib.util.spec_from_file_location("portable_backup_fixture", HERE / "backup.py")
        backup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backup)
        for relative in ("host", "host/agents", "host/api", "host/web"):
            (self.bundle / relative).mkdir(mode=0o700)
        for relative in ("host/agents/.env", "host/api/.env", "host/web/.env.local"):
            self.write(self.bundle / relative, "FIXTURE=true\n")
        self.write(self.folder / "books.json", json.dumps(self.source["expected_books"]))
        files = {path.relative_to(self.bundle).as_posix(): {
            "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in self.bundle.rglob("*") if path.is_file()}
        directories = sorted(path.relative_to(self.bundle).as_posix()
                             for path in self.bundle.rglob("*") if path.is_dir())
        manifest = {"version": 1, "created_at": "2026-10-04T00:00:00+00:00",
                    "source_git_commit": "a" * 40, "writers_stopped": True,
                    "files": files, "directories": directories,
                    "host_configuration_review": [],
                    "missing_optional_host_files": backup.missing_optional(files, directories),
                    "completeness": backup.completeness(files, directories, True, [])}
        self.write(self.bundle / "manifest.json", json.dumps(manifest))
        source, expected, files = db.source_inputs(self.bundle, self.books)
        self.assertEqual(expected, self.source["expected_books"])
        self.write(self.files["data.sql"], "tampered\n")
        with self.assertRaises(db.DatabaseError):
            db.source_inputs(self.bundle, self.books)

    def test_empty_dump_and_partial_archive_are_rejected_before_database_work(self):
        with self.assertRaises(db.DatabaseError):
            db.source_inputs(self.bundle, self.books)  # no complete portable manifest
        self.write(self.files["data.sql"], "")
        with patch.object(db, "validate_bundle"), self.assertRaises(db.DatabaseError):
            db.source_inputs(self.bundle, self.books)

    def test_dump_cannot_reconnect_or_execute_psql_commands_and_copy_must_finish(self):
        for text in ("\\connect cloud\n", "\\! command\n", "\\i other.sql\n",
                     "COPY public.test (value) FROM stdin;\nunfinished\n"):
            self.write(self.files["data.sql"], text)
            with self.assertRaises(db.DatabaseError):
                db.validate_dump_controls(self.files["data.sql"])
        self.write(self.files["data.sql"], "\\restrict ABC123\nCOPY public.test (value) FROM stdin;\n\\connect is opaque data\n\\.\n\\unrestrict ABC123\n")
        db.validate_dump_controls(self.files["data.sql"])

    def test_private_outputs_never_overwrite_existing_inventory(self):
        self.write(self.output, "preserve")
        with patch.object(db, "run_psql") as run, self.assertRaises(db.DatabaseError):
            self.run_restore()
        run.assert_not_called()
        self.assertEqual(self.output.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
