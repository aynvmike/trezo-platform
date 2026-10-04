"""Offline migration bundle guards; no network, credentials or live services.

python -m unittest discover -s ops/portable -p test_backup.py
age is mocked for orchestration tests; these do not claim cryptographic testing.
"""
from __future__ import annotations

import copy
import ast
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("portable_backup", Path(__file__).with_name("backup.py"))
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp" if Path("/tmp").is_dir() else None)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir(mode=0o700)
        (self.repo / ".git").mkdir()
        (self.repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        self.work = self.root / "private"
        self.work.mkdir(mode=0o700)
        self.commit = patch.object(backup, "source_commit", return_value="a" * 40)
        self.commit.start()
        self.addCleanup(self.commit.stop)
        for path in ("agents/.env", "api/.env", "web/.env.local"):
            file = self.repo / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("SYNTHETIC_KEY=not-a-real-key\n")

    def archive(self, database=None, state=None):
        directory = Path(tempfile.mkdtemp(dir=self.work))
        return backup.make_archive(self.repo, database, directory, True, state)

    def database(self):
        folder = self.work / "database-input"
        folder.mkdir()
        for name in ("roles.sql", "schema.sql", "data.sql", "source-inventory.private.json", "books.json"):
            (folder / name).write_text("{}\n" if name.endswith("json") else "-- synthetic SQL\n")
        (folder / "storage").mkdir()
        (folder / "storage" / "synthetic-object.txt").write_text("storage bytes")
        return folder

    def rewrite(self, source, changes=None, extras=None, manifest_change=None):
        destination = self.work / ("modified-" + str(len(list(self.work.glob("modified-*")))) + ".tar")
        with tarfile.open(source, "r:") as src, tarfile.open(destination, "w") as dst:
            for item in src:
                raw = src.extractfile(item).read() if item.isfile() else None
                if changes and item.name in changes:
                    raw = changes[item.name]
                    if raw is None:
                        continue
                if item.name == "manifest.json" and manifest_change:
                    value = json.loads(raw)
                    manifest_change(value)
                    raw = json.dumps(value).encode()
                info = copy.copy(item)
                if raw is not None:
                    info.size = len(raw)
                dst.addfile(info, io.BytesIO(raw) if raw is not None else None)
            for name, kind, payload in extras or []:
                info = tarfile.TarInfo(name)
                info.type = kind
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    info.linkname = "../../outside"
                elif kind == tarfile.REGTYPE:
                    info.size = len(payload)
                dst.addfile(info, io.BytesIO(payload) if kind == tarfile.REGTYPE else None)
        return destination

    def test_host_only_cannot_claim_database_recovery(self):
        archive, manifest = self.archive()
        self.assertEqual(backup.validate_archive(archive), manifest)
        self.assertEqual(manifest["completeness"]["status"], "HOST_ONLY")
        self.assertFalse(manifest["completeness"]["restore_tested"])
        self.assertFalse(manifest["completeness"]["cutover_authorized"])
        self.assertIn("database/roles.sql", manifest["completeness"]["missing_database_material"])

    def test_database_material_is_unverified_and_missing_sql_is_incomplete(self):
        folder = self.database()
        _, value = self.archive(folder)
        self.assertEqual(value["completeness"]["status"], "RECOVERY_MATERIAL_PRESENT_UNVERIFIED")
        (folder / "data.sql").unlink()
        _, value = self.archive(folder)
        self.assertEqual(value["completeness"]["status"], "INCOMPLETE")
        self.assertIn("database/data.sql", value["completeness"]["missing_database_material"])

    def test_empty_required_env_is_incomplete(self):
        (self.repo / "agents/.env").write_bytes(b"")
        _, manifest = self.archive()
        self.assertEqual(manifest["completeness"]["status"], "INCOMPLETE")

    def test_writer_attestation_required(self):
        with self.assertRaises(backup.BundleError):
            backup.make_archive(self.repo, None, self.work, False)

    def test_collects_logs_and_runtime_but_never_dependencies(self):
        for name in ("logs/activity-20261004.jsonl", "agents/logs/engine.log",
                     "agents/.cache/prices.json", "agents/knowledge/library/_index.json"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic-data")
        forbidden = self.repo / "node_modules/should-not-copy.txt"
        forbidden.parent.mkdir()
        forbidden.write_text("not copied")
        _, manifest = self.archive()
        self.assertIn("host/logs/activity-20261004.jsonl", manifest["files"])
        self.assertIn("host/agents/.cache/prices.json", manifest["files"])
        self.assertFalse(any("node_modules" in name for name in manifest["files"]))

    def test_sqlite_backup_includes_committed_wal_and_not_sidecars(self):
        path = self.repo / "agents/local_state/research.sqlite3"
        path.parent.mkdir()
        db = sqlite3.connect(path)
        self.addCleanup(db.close)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE examples (value TEXT)")
        db.execute("INSERT INTO examples VALUES ('committed in WAL')")
        db.commit()
        self.assertTrue(Path(str(path) + "-wal").exists())
        archive, manifest = self.archive()
        self.assertFalse(any(name.endswith(("-wal", "-shm")) for name in manifest["files"]))
        destination = self.work / "sqlite-restored"
        backup.restore_archive(archive, destination)
        with sqlite3.connect(destination / "host/agents/local_state/research.sqlite3") as restored:
            self.assertEqual(restored.execute("SELECT value FROM examples").fetchall(), [("committed in WAL",)])

    def test_custom_state_path_is_flagged_by_name_without_exposing_value(self):
        marker = r"D:\PRIVATE\custom.sqlite3"
        (self.repo / "agents/.env").write_text("TREZO_RESEARCH_DB_PATH=" + marker + "\n")
        _, manifest = self.archive(self.database())
        self.assertEqual(manifest["host_configuration_review"], ["TREZO_RESEARCH_DB_PATH"])
        self.assertEqual(manifest["completeness"]["status"], "INCOMPLETE")
        self.assertNotIn(marker, json.dumps(manifest))

    def test_linux_private_state_root_avoids_following_checkout_symlinks(self):
        state = self.work / "runtime"
        state.mkdir(mode=0o700)
        for relative in ("agents/.env", "api/.env", "web/.env.local"):
            target = state / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("SYNTHETIC_MIGRATED=1\n")
            original = self.repo / relative
            original.unlink()
            try:
                original.symlink_to(target)
            except OSError:
                self.skipTest("Symlinks unavailable to this test user")
        with self.assertRaises(backup.BundleError):
            self.archive()
        archive, manifest = self.archive(state=state)
        self.assertEqual(manifest["completeness"]["status"], "HOST_ONLY")
        self.assertEqual(backup.validate_archive(archive), manifest)

    def test_private_runtime_export_reads_current_atomic_json_from_checkout(self):
        state = self.work / "runtime"
        state.mkdir(mode=0o700)
        for relative in ("agents/.env", "api/.env", "web/.env.local"):
            target = state / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.repo / relative, target)
        relative = "agents/app/data/crypto_discovered.json"
        current = self.repo / relative
        current.parent.mkdir(parents=True)
        current.write_text('{"generation":"current"}')
        stale = state / relative
        stale.parent.mkdir(parents=True)
        stale.write_text('{"generation":"stale"}')
        library = self.repo / "agents/knowledge/library/book.txt"
        library.parent.mkdir(parents=True)
        library.write_text("current library")
        stale_library = state / "agents/knowledge/library/book.txt"
        stale_library.parent.mkdir(parents=True)
        stale_library.write_text("stale library")
        archive, _ = self.archive(state=state)
        with tarfile.open(archive) as tar:
            self.assertEqual(tar.extractfile("host/" + relative).read(), current.read_bytes())
            self.assertEqual(tar.extractfile("host/agents/knowledge/library/book.txt").read(), library.read_bytes())

    def test_installed_private_layout_roundtrips_every_runtime_directory(self):
        # Read the installer contract without importing its operational code.
        # A newly added install path must not silently disappear from backups.
        tree = ast.parse(Path(__file__).with_name("install.py").read_text(encoding="utf-8"))
        assignments = {target.id: node.value for node in tree.body if isinstance(node, ast.Assign)
                       for target in node.targets if isinstance(target, ast.Name)}
        installer_directories = ast.literal_eval(assignments["RUNTIME_DIRS"])
        library = ast.literal_eval(assignments["LIBRARY"])
        self.assertEqual(set(backup.HOST_DIRECTORIES), set(installer_directories) | {library})
        state = self.work / "complete-runtime"
        state.mkdir(mode=0o700)
        for relative in ("agents/.env", "api/.env", "web/.env.local"):
            target = state / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.repo / relative, target)
        for relative in installer_directories:
            directory = state / relative
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "private-state.txt").write_text("state from " + relative)
        # Exercise suffix and header detection in two persistent cache stores.
        stores = ("agents/.chromadb/chroma.sqlite3", "agents/.mem0/history.db")
        for relative in stores:
            connection = sqlite3.connect(state / relative)
            self.addCleanup(connection.close)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("CREATE TABLE examples (source TEXT)")
            connection.execute("INSERT INTO examples VALUES (?)", (relative,))
            connection.commit()
        (self.repo / library).mkdir(parents=True)
        (self.repo / library / "book.txt").write_text("private library")
        archive, manifest = self.archive(state=state)
        destination = self.work / "all-runtime-restored"
        backup.restore_archive(archive, destination)
        backup.validate_staging(destination)
        for relative in installer_directories:
            self.assertEqual((destination / "host" / relative / "private-state.txt").read_text(),
                             "state from " + relative)
        for relative in stores:
            with sqlite3.connect(destination / "host" / relative) as connection:
                self.assertEqual(connection.execute("SELECT source FROM examples").fetchall(), [(relative,)])
        self.assertFalse(any(name.endswith(("-wal", "-shm")) for name in manifest["files"]))

    def test_source_link_is_rejected(self):
        source = self.repo / "agents/.env"
        source.unlink()
        try:
            source.symlink_to(self.repo / "api/.env")
        except OSError:
            self.skipTest("Symlinks unavailable to this test user")
        with self.assertRaises(backup.BundleError):
            self.archive()

    def test_database_export_symlink_is_rejected(self):
        folder = self.database()
        try:
            (folder / "escape").symlink_to(self.repo, target_is_directory=True)
        except OSError:
            self.skipTest("Symlinks unavailable to this test user")
        with self.assertRaises(backup.BundleError):
            self.archive(folder)

    def test_traversal_links_duplicate_and_extra_entries_are_rejected(self):
        archive, _ = self.archive()
        cases = [("../outside", tarfile.REGTYPE, b"x"),
                 ("/absolute", tarfile.REGTYPE, b"x"),
                 ("host/agents/../../escape", tarfile.REGTYPE, b"x"),
                 ("host\\escape", tarfile.REGTYPE, b"x"),
                 ("database/link", tarfile.SYMTYPE, b""),
                 ("database/hardlink", tarfile.LNKTYPE, b""),
                 ("host/agents/.env", tarfile.REGTYPE, b"duplicate"),
                 ("host/agents/EXTRA", tarfile.REGTYPE, b"extra")]
        for entry in cases:
            with self.subTest(entry=entry[0]):
                modified = self.rewrite(archive, extras=[entry])
                with self.assertRaises(backup.BundleError):
                    backup.validate_archive(modified)

    def test_tampered_bytes_missing_file_and_manifest_claim_rejected(self):
        archive, _ = self.archive()
        for raw in (b"tampered-content", None):
            modified = self.rewrite(archive, changes={"host/agents/.env": raw})
            with self.assertRaises(backup.BundleError):
                backup.validate_archive(modified)
        modified = self.rewrite(archive, manifest_change=lambda m: m["completeness"].update(restore_tested=True))
        with self.assertRaises(backup.BundleError):
            backup.validate_archive(modified)

    def test_restore_new_only_private_and_validates_staging(self):
        archive, manifest = self.archive(self.database())
        dest = self.work / "restore"
        result = backup.restore_archive(archive, dest)
        self.assertTrue(result["staging_only"])
        self.assertFalse(result["live_database_modified"])
        self.assertEqual(backup.validate_staging(dest), manifest)
        if os.name == "posix":
            self.assertEqual(dest.stat().st_mode & 0o777, 0o700)
            self.assertEqual((dest / "host/agents/.env").stat().st_mode & 0o777, 0o600)
        with self.assertRaises(backup.BundleError):
            backup.restore_archive(archive, dest)
        (dest / "host/agents/.env").write_text("changed")
        with self.assertRaises(backup.BundleError):
            backup.validate_staging(dest)

    def test_restore_validates_before_creating_destination(self):
        archive, _ = self.archive()
        modified = self.rewrite(archive, changes={"host/api/.env": b"changed"})
        dest = self.work / "never-created"
        with self.assertRaises(backup.BundleError):
            backup.restore_archive(modified, dest)
        self.assertFalse(dest.exists())

    def test_private_outputs_in_checkout_or_worktree_refused(self):
        with self.assertRaises(backup.BundleError):
            backup.private_directory(self.repo)
        worktree = self.work / "worktree"
        worktree.mkdir(mode=0o700)
        (worktree / ".git").write_text("gitdir: /synthetic/location\n")
        with self.assertRaises(backup.BundleError):
            backup.private_directory(worktree)

    def test_age_failure_cleans_partial_ciphertext_and_plaintext(self):
        output = self.work / "failed.age"

        def fail_age(arguments, fh):
            fh.write(b"partial")
            raise backup.BundleError("synthetic age failure")

        with patch.object(backup, "age_command", side_effect=fail_age):
            with self.assertRaises(backup.BundleError):
                backup.export_bundle(self.repo, output, self.work, None, None, True, True)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.work.iterdir()), [])

    def test_mock_age_roundtrip_and_no_overwrite(self):
        output = self.work / "roundtrip.age"

        def fake_age(arguments, fh):
            # Orchestration-only mock. This deliberately does NOT encrypt.
            with Path(arguments[-1]).open("rb") as src:
                shutil.copyfileobj(src, fh)

        with patch.object(backup, "age_command", side_effect=fake_age) as age:
            result = backup.export_bundle(self.repo, output, self.work, None, "age1" + "q" * 58, False, True)
            self.assertEqual(result["status"], "HOST_ONLY")
            self.assertEqual(age.call_args.args[0][:2], ["-r", "age1" + "q" * 58])
            self.assertFalse(any(p.name.startswith("trezo-private-") for p in self.work.iterdir()))
            with backup.decrypted(output, self.work, None) as (archive, manifest):
                self.assertEqual(manifest["completeness"]["status"], "HOST_ONLY")
                backup.restore_archive(archive, self.work / "roundtrip-stage")
            with self.assertRaises(backup.BundleError):
                backup.export_bundle(self.repo, output, self.work, None, None, True, True)

    def test_age_passphrase_is_interactive_not_argument_or_environment(self):
        with patch.object(backup.shutil, "which", return_value="/synthetic/age"), \
             patch.object(backup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            backup.age_command(["-p", "private-payload.tar"], io.BytesIO())
        self.assertEqual(run.call_args.args[0], ["age", "-p", "private-payload.tar"])
        self.assertNotIn("env", run.call_args.kwargs)
        self.assertNotIn("input", run.call_args.kwargs)

    def test_duplicate_manifest_keys_rejected(self):
        archive, _ = self.archive()
        with tarfile.open(archive) as tar:
            raw = tar.extractfile("manifest.json").read()
        raw = raw.replace(b'"version": 1', b'"version": 1, "version": 1')
        modified = self.rewrite(archive, changes={"manifest.json": raw})
        with self.assertRaises(backup.BundleError):
            backup.validate_archive(modified)

    @unittest.skipUnless(shutil.which("age") and shutil.which("age-keygen"), "age CLI not installed")
    def test_real_age_roundtrip_and_ciphertext_tamper_failure(self):
        identity = self.work / "identity.txt"
        generated = subprocess.run(["age-keygen", "-o", str(identity)], capture_output=True, check=False)
        self.assertEqual(generated.returncode, 0, "age-keygen failed")
        public = subprocess.run(["age-keygen", "-y", str(identity)], capture_output=True, text=True, check=False)
        self.assertEqual(public.returncode, 0, "public recipient extraction failed")
        database = self.repo / "agents/local_state/research.sqlite3"
        database.parent.mkdir()
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE sample (value INTEGER)")
            db.execute("INSERT INTO sample VALUES (42)")
        output = self.work / "real-encrypted.age"
        receipt = backup.export_bundle(self.repo, output, self.work, None, public.stdout.strip(), False, True)
        self.assertEqual(receipt["status"], "HOST_ONLY")
        encrypted = output.read_bytes()
        self.assertTrue(encrypted.startswith(b"age-encryption.org/v1"))
        self.assertNotIn(b"not-a-real-key", encrypted)
        with backup.decrypted(output, self.work, identity) as (archive, _manifest):
            destination = self.work / "real-restore"
            backup.restore_archive(archive, destination)
        self.assertEqual((destination / "host/agents/.env").read_bytes(), (self.repo / "agents/.env").read_bytes())
        with sqlite3.connect(destination / "host/agents/local_state/research.sqlite3") as db:
            self.assertEqual(db.execute("SELECT value FROM sample").fetchall(), [(42,)])
        changed = bytearray(encrypted)
        changed[-20] ^= 1
        tampered = self.work / "tampered.age"
        tampered.write_bytes(changed)
        with self.assertRaises(backup.BundleError):
            with backup.decrypted(tampered, self.work, identity):
                self.fail("Tampered ciphertext must not decrypt successfully")
        self.assertFalse(any(p.name.startswith("trezo-private-") for p in self.work.iterdir()))


if __name__ == "__main__":
    unittest.main()
