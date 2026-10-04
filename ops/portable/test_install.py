"""Offline tests. No package installation, host service calls or network access."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("portable_install", Path(__file__).with_name("install.py"))
install = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(install)


@unittest.skipUnless(os.name == "posix" and shutil.which("git"), "Requires POSIX file permissions, symlinks and local git")
class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="trezo-portable-test-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "app"
        self.repo.mkdir()
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.restore = self.private / "restore" / "host"
        self.restore.mkdir(parents=True)
        source_repo = Path(__file__).resolve().parents[2]
        shutil.copyfile(source_repo / ".gitignore", self.repo / ".gitignore")
        for relative in install.ENV_FILES:
            destination = self.restore / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("TEST_SECRET=never_print_this_value\n")
            (self.repo / relative).parent.mkdir(parents=True, exist_ok=True)
        for relative in install.RUNTIME_FILES:
            (self.repo / relative).parent.mkdir(parents=True, exist_ok=True)
        self.tracked_library = self.repo / install.LIBRARY / "research--options-strategy-formulas.txt"
        self.tracked_library.parent.mkdir(parents=True)
        self.tracked_library.write_text("reviewed versioned library material")
        self.local_git("init", "--quiet")
        self.local_git("config", "user.name", "Offline Test")
        self.local_git("config", "user.email", "offline@example.invalid")
        self.local_git("add", ".gitignore")
        self.local_git("add", "--force", self.tracked_library.relative_to(self.repo).as_posix())
        self.local_git("commit", "--quiet", "-m", "fixture")
        self.local_git("remote", "add", "origin", "https://github.com/aynvmike/trezo-platform.git")
        self.commit = self.local_git("rev-parse", "HEAD")
        self.validation = patch.object(install, "validate_restore", return_value={"source_git_commit": self.commit})
        self.validate_mock = self.validation.start()
        self.tools = {"node": "/usr/bin/node", "npm": "/usr/bin/npm",
                      "git": "/usr/bin/git", "flock": "/usr/bin/flock",
                      "systemctl": "/usr/bin/systemctl", "python": "/usr/bin/python3"}

    def tearDown(self):
        self.validation.stop()
        self.temp.cleanup()

    def local_git(self, *args):
        result = subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=install.minimal_env(self.root))
        return result.stdout.decode().strip()

    def prepare(self):
        return install.prepare(self.repo, self.private, self.restore, self.commit, "trezo", self.tools)

    def test_prepare_copies_private_state_and_never_installs_units(self):
        cache = self.restore / "agents/local_state"
        cache.mkdir(parents=True)
        (cache / "journal.sqlite3").write_bytes(b"offline fixture")
        result = self.prepare()
        self.validate_mock.assert_called_once_with(self.restore)
        self.assertEqual(result["status"], "PREPARED_NOT_BUILT_NOT_ACTIVE")
        self.assertEqual((self.repo / "agents/.env").resolve(), self.private / "runtime/agents/.env")
        self.assertEqual((self.repo / "agents/.env").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.repo / "agents/local_state/journal.sqlite3").read_bytes(), b"offline fixture")
        self.assertEqual(self.local_git("status", "--porcelain"), "")
        units = list((self.private / "units").glob("*.service"))
        self.assertEqual(len(units), 3)
        self.assertTrue(all("never_print_this_value" not in p.read_text() for p in units))

    def test_existing_destination_is_not_overwritten(self):
        env = self.repo / "agents/.env"
        env.write_text("existing")
        with self.assertRaises(install.Refusal):
            self.prepare()
        self.assertEqual(env.read_text(), "existing")
        self.assertFalse((self.private / "runtime").exists())

    def test_manifest_rejection_precedes_copy(self):
        self.validate_mock.side_effect = install.Refusal("Migration staging validation failed.")
        with self.assertRaises(install.Refusal):
            self.prepare()
        self.assertFalse((self.private / "runtime").exists())

    def test_restore_links_and_special_files_refused(self):
        malicious = self.restore / "linked"
        malicious.symlink_to(self.root)
        with self.assertRaises(install.Refusal):
            self.prepare()
        self.assertFalse((self.private / "runtime").exists())

    def test_reprepare_refused_without_overwriting(self):
        self.prepare()
        before = (self.private / "install/prepared.json").read_bytes()
        with self.assertRaises(install.Refusal):
            self.prepare()
        self.assertEqual((self.private / "install/prepared.json").read_bytes(), before)

    def test_library_keeps_tracked_material_and_copies_private_additions(self):
        source = self.restore / install.LIBRARY
        source.mkdir(parents=True)
        (source / self.tracked_library.name).write_bytes(self.tracked_library.read_bytes())
        (source / "private-book.txt").write_text("private book")
        self.prepare()
        self.assertFalse(self.tracked_library.parent.is_symlink())
        self.assertEqual(self.tracked_library.read_text(), "reviewed versioned library material")
        added = self.tracked_library.parent / "private-book.txt"
        self.assertEqual(added.read_text(), "private book")
        self.assertEqual(added.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.local_git("status", "--porcelain"), "")

    def test_library_conflict_refused_before_private_runtime_created(self):
        source = self.restore / install.LIBRARY
        source.mkdir(parents=True)
        (source / self.tracked_library.name).write_text("old conflicting source material")
        with self.assertRaises(install.Refusal):
            self.prepare()
        self.assertFalse((self.private / "runtime").exists())
        self.assertEqual(self.tracked_library.read_text(), "reviewed versioned library material")

    def test_checkout_requires_exact_commit_origin_and_cleanliness(self):
        install.verify_checkout(self.repo, self.commit)
        with self.assertRaises(install.Refusal):
            install.verify_checkout(self.repo, "f" * 40)
        self.local_git("remote", "set-url", "origin", "https://example.invalid/untrusted.git")
        with self.assertRaises(install.Refusal):
            install.verify_checkout(self.repo, self.commit)
        self.local_git("remote", "set-url", "origin", "https://github.com/aynvmike/trezo-platform.git")
        (self.repo / ".gitignore").write_text("changed")
        with self.assertRaises(install.Refusal):
            install.verify_checkout(self.repo, self.commit)

    def test_units_pin_loopback_and_single_locked_engine(self):
        units = install.render_units(self.repo, self.private, "trezo", self.tools)
        agents = units["trezo-agents.service"]
        self.assertIn("--nonblock --no-fork", agents)
        self.assertIn("--host 127.0.0.1 --port 8001 --workers 1", agents)
        self.assertNotIn("--reload", agents)
        self.assertIn("Environment=TREZO_REPO_DIR=" + str(self.repo), agents)
        self.assertIn("Environment=API_BIND_HOST=127.0.0.1", units["trezo-api.service"])
        self.assertIn("--hostname 127.0.0.1 --port 3000", units["trezo-web.service"])
        self.assertTrue(all("User=trezo" in u and "UMask=0077" in u for u in units.values()))

    def test_existing_systemd_service_refuses_preparation(self):
        responses = [subprocess.CompletedProcess([], 0, b"v20.19.0\n"),
                     subprocess.CompletedProcess([], 0, b"loaded\n")]
        with patch.object(install.platform, "system", return_value="Linux"), \
                patch.object(install.Path, "is_dir", return_value=True), \
                patch.object(install.pwd, "getpwnam", return_value=types.SimpleNamespace(pw_uid=123)), \
                patch.object(install.os, "getuid", return_value=123), \
                patch.object(install.shutil, "which", side_effect=lambda name, **kw: "/usr/bin/" + name), \
                patch.object(install, "capture", side_effect=responses) as commands:
            with self.assertRaises(install.Refusal):
                install.prerequisites(self.repo, "trezo")
        self.assertEqual(commands.call_count, 2)
        self.assertIn("show", commands.call_args.args[0])

    def test_build_failure_leaves_no_success_receipt(self):
        self.prepare()
        calls = []

        def step(name, *args, **kwargs):
            calls.append(name)
            if name == "build_web":
                raise install.Refusal("Build step failed: build_web")

        with patch.object(install, "run_step", side_effect=step):
            with self.assertRaises(install.Refusal):
                install.build(self.repo, self.private, self.commit, "trezo", self.tools)
        self.assertFalse((self.private / "install/built.json").exists())
        self.assertEqual(calls, ["create_python_venv", "python_dependencies", "npm_ci_root", "build_api", "build_web"])

    def test_build_runs_root_workspaces_and_isolated_guard_checkout(self):
        self.prepare()
        calls = []

        def step(name, command, cwd, *args, **kwargs):
            calls.append((name, command, cwd))

        with patch.object(install, "run_step", side_effect=step):
            result = install.build(self.repo, self.private, self.commit, "trezo", self.tools)
        self.assertEqual(result["status"], "BUILT_NOT_ACTIVE")
        self.assertFalse(result["services_started"])
        by_name = {name: (command, cwd) for name, command, cwd in calls}
        self.assertEqual(by_name["npm_ci_root"][1], self.repo)
        self.assertEqual(by_name["build_web"][1], self.repo)
        self.assertEqual(by_name["agent_guard_suites"][1], self.private / "install/guard-checkout/agents")
        self.assertTrue(all("systemctl" not in command for _, command, _ in calls))

    def test_tool_output_and_shell_secrets_not_logged(self):
        self.prepare()
        with patch.dict(os.environ, {"ALPACA_SECRET_KEY": "never_print_this_value", "NODE_OPTIONS": "bad"}):
            env = install.minimal_env(self.root)
            self.assertNotIn("ALPACA_SECRET_KEY", env)
            self.assertNotIn("NODE_OPTIONS", env)
            with patch.object(install.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)) as mock:
                with self.assertRaises(install.Refusal):
                    install.run_step("test_failure", ["unused"], self.repo, self.private)
                self.assertEqual(mock.call_args.kwargs["stdout"], subprocess.DEVNULL)
                self.assertEqual(mock.call_args.kwargs["stderr"], subprocess.DEVNULL)
        text = (self.private / "install/build.log").read_text()
        self.assertNotIn("never_print_this_value", text)
        self.assertEqual(json.loads(text)["exit_code"], 1)

    def test_paths_refuse_symlinks_and_systemd_metacharacters(self):
        alias = self.root / "alias"
        alias.symlink_to(self.repo)
        for value in (str(alias), "/srv/trezo/%n", "/srv/trezo/../other", "relative"):
            with self.assertRaises(install.Refusal):
                install.safe_path(value)


if __name__ == "__main__":
    unittest.main()
