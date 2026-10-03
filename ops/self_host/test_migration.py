"""Offline guard tests. Run: python -m unittest discover -s ops/self_host -p 'test_*.py'."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("trezo_verify_migration", HERE / "verify_migration.py")
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def fixture() -> dict:
    expected = {"primary": "00000000-0000-4000-8000-000000000001",
                "acct2": "00000000-0000-4000-8000-000000000002",
                "acct3": "00000000-0000-4000-8000-000000000003"}
    return {
        "format": 1, "captured_at": "2026-10-03T00:00:00Z", "writers_stopped": True,
        "expected_books": expected, "server_version_num": "170006",
        "tables": {name: {"rows": 3, "fingerprint": "a" * 32} for name in verify.REQUIRED},
        "books": [{"account_key": key, "owner_id": expected["primary"],
                   "is_paper": True, "is_active": True, "broker": "alpaca",
                   "owner_count": 1, "settings_count": 1, "account_count": 1}
                  for key in expected.values()],
    }


class MigrationTests(unittest.TestCase):
    def test_matching_rows_never_authorize_cutover(self):
        source = fixture()
        target = copy.deepcopy(source)
        target["captured_at"] = "2026-10-03T00:02:00Z"
        target["books"].reverse()
        result = verify.compare(source, target)
        self.assertEqual(result["status"], "MATCH")
        self.assertFalse(result["cutover_authorized"])

    def test_same_count_changed_budget_is_blocked(self):
        source, target = fixture(), fixture()
        target["tables"]["public.bot_settings"]["fingerprint"] = "b" * 32
        result = verify.compare(source, target)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["changed_tables"], ["public.bot_settings"])

    def test_book_slot_swap_is_blocked(self):
        source, target = fixture(), fixture()
        target["expected_books"]["primary"], target["expected_books"]["acct2"] = (
            target["expected_books"]["acct2"], target["expected_books"]["primary"])
        self.assertIn("book_slot_mapping_changed", verify.compare(source, target)["issues"])

    def test_owner_change_is_blocked(self):
        source, target = fixture(), fixture()
        target["books"][1]["owner_id"] = target["expected_books"]["acct2"]
        self.assertIn("book_ownership_or_account_state_changed", verify.compare(source, target)["issues"])

    def test_missing_table_rejected(self):
        value = fixture()
        del value["tables"]["auth.users"]
        with self.assertRaises(verify.CheckError):
            verify.validate(value)

    def test_extra_table_detected(self):
        source, target = fixture(), fixture()
        target["tables"]["public.unknown"] = {"rows": 0, "fingerprint": "a" * 32}
        self.assertEqual(verify.compare(source, target)["status"], "BLOCKED")

    def test_empty_book_or_live_book_rejected(self):
        for field, value in (("account_count", 0), ("settings_count", 0),
                             ("owner_count", 0), ("is_paper", False), ("is_active", False)):
            sample = fixture()
            sample["books"][0][field] = value
            with self.subTest(field=field), self.assertRaises(verify.CheckError):
                verify.validate(sample)

    def test_unfrozen_snapshot_not_enough(self):
        value = fixture()
        value["writers_stopped"] = False
        self.assertEqual(verify.compare(value, fixture())["status"], "BLOCKED")

    def test_psql_failure_and_empty_success_never_become_inventory(self):
        for code, output in ((1, ""), (0, ""), (0, '{"kind":"meta","server_version_num":"170006"}')):
            result = subprocess.CompletedProcess([], code, output, "SECRET_PASSWORD")
            with patch.object(verify.subprocess, "run", return_value=result), self.assertRaises(verify.CheckError) as exc:
                verify.capture("trezo-source", fixture()["expected_books"], False)
            self.assertNotIn("SECRET_PASSWORD", str(exc.exception))

    def test_capture_uses_read_only_sql_and_secret_free_arguments(self):
        value = fixture()
        lines = [{"kind": "meta", "server_version_num": value["server_version_num"]}]
        lines.extend({"kind": "book", **row} for row in value["books"])
        lines.extend({"kind": "table", "name": name, **row} for name, row in value["tables"].items())
        stdout = "\n".join(json.dumps(row) for row in lines)
        with patch.object(verify.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout, "")) as run:
            captured = verify.capture("trezo-source", value["expected_books"], True)
        self.assertEqual(verify.compare(value, captured)["status"], "MATCH")
        self.assertIn("READ ONLY", run.call_args.kwargs["input"])
        self.assertIn("service=trezo-source", run.call_args.args[0])
        with self.assertRaises(verify.CheckError):
            verify.capture("trezo-source password=secret", value["expected_books"], False)

    def test_duplicate_book_ids_rejected_and_output_not_overwritten(self):
        # CI may set TMPDIR beneath its checkout; private output intentionally
        # refuses a repository ancestor, so create a genuinely separate fixture.
        with tempfile.TemporaryDirectory(dir="/tmp" if Path("/tmp").is_dir() else None) as directory:
            folder = Path(directory)
            path = folder / "books.json"
            path.write_text(json.dumps(dict.fromkeys(verify.SLOTS, fixture()["expected_books"]["primary"])))
            with self.assertRaises(verify.CheckError):
                verify.books_from_file(path)
            output = folder / "manifest.json"
            verify.write_private(output, fixture())
            with self.assertRaises(verify.CheckError):
                verify.write_private(output, {})
            (folder / ".git").mkdir()
            (folder / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            with self.assertRaises(verify.CheckError):
                verify.write_private(folder / "another.json", fixture())

    def test_duplicate_table_does_not_hide_truncated_capture(self):
        row = {"kind": "table", "name": "public.bot_settings", "rows": 1, "fingerprint": "a" * 32}
        with self.assertRaises(verify.CheckError):
            verify.parse_capture(json.dumps(row) + "\n" + json.dumps(row), fixture()["expected_books"], True)


if __name__ == "__main__":
    unittest.main()
