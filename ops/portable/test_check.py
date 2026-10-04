import copy
import datetime as dt
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("portable_check", Path(__file__).with_name("check.py"))
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.books = {slot: str(i) for i, slot in enumerate(check.SLOTS)}
        self.database = "https://database.example.test"
        self.web = "https://trezo.example.test"
        self.envs = {role: {"SUPABASE_SERVICE_ROLE_KEY": "test-private-key"}
                     for role in ("agents", "api", "web")}
        self.envs["agents"].update({"SUPABASE_URL": self.database,
            "TREZO_ACCOUNTS_ENABLED": "primary,acct2,acct3", "ALPACA_CRYPTO_ENABLED": "true"})
        for slot, (suffix, identity) in check.SLOTS.items():
            self.envs["agents"].update({identity: self.books[slot],
                "ALPACA_API_KEY" + suffix: "test-key-" + slot,
                "ALPACA_SECRET_KEY" + suffix: "test-secret-" + slot})
        for role in ("api", "web"):
            self.envs[role].update({"NEXT_PUBLIC_SUPABASE_URL": self.database,
                                    "NEXT_PUBLIC_SUPABASE_ANON_KEY": "test-public-key"})
        self.envs["web"]["NEXT_PUBLIC_BASE_URL"] = self.web

    def issues(self):
        return check.config_issues(self.envs, self.books, self.database, self.web)

    def test_matching_paper_book_configuration(self):
        self.assertEqual(self.issues(), [])

    def test_mixed_cloud_and_restored_database_is_blocked(self):
        self.envs["web"]["NEXT_PUBLIC_SUPABASE_URL"] = "https://old-project.supabase.co"
        self.assertIn("all_three_components_must_use_the_reviewed_database_url", self.issues())

    def test_live_endpoint_and_cross_book_key_are_blocked(self):
        self.envs["agents"]["ALPACA_BASE_URL_2"] = "https://api.alpaca.markets"
        self.envs["agents"]["ALPACA_API_KEY_3"] = self.envs["agents"]["ALPACA_API_KEY"]
        self.assertIn("acct2_broker_endpoint_is_not_alpaca_paper", self.issues())
        self.assertIn("broker_key_reused_across_books", self.issues())

    def test_identity_change_and_missing_slot_are_blocked(self):
        self.envs["agents"]["TREZO_ACCOUNT_USER_ID_3"] = "another-book"
        self.envs["agents"]["TREZO_ACCOUNTS_ENABLED"] = "primary"
        self.assertIn("acct3_book_identity_changed_or_missing", self.issues())
        self.assertIn("exactly_three_independent_book_slots_required", self.issues())

    def test_privileged_browser_key_is_rejected_without_echoing_value(self):
        for role in ("api", "web"):
            self.envs[role]["NEXT_PUBLIC_SUPABASE_ANON_KEY"] = "test-private-key"
        issues = self.issues()
        self.assertIn("public_anon_keys_missing_mismatched_or_privileged", issues)
        self.assertNotIn("test-private-key", str(issues))

    def test_windows_paths_and_old_web_callback_are_blocked(self):
        self.envs["agents"]["TREZO_RESEARCH_DB_PATH"] = r"D:\Trezo\research.sqlite3"
        self.envs["agents"]["TREZO_WEB_BASE_URL"] = "http://100.115.119.32:3000"
        self.assertTrue(any("windows_path" in x for x in self.issues()))
        self.assertTrue(any("unexpected_internal_endpoint" in x for x in self.issues()))

    def test_no_http_credentials_or_remote_plaintext(self):
        for endpoint in ("http://database.example.test", "https://user:password@db.example.test", "https://db.example.test?key=test"):
            self.assertFalse(check.private_endpoint(endpoint))
        self.assertTrue(check.private_endpoint("http://127.0.0.1:54321"))


class BootTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "Linux proc socket ownership fixture")
    def test_old_listener_cannot_validate_a_new_engine_boot(self):
        with tempfile.TemporaryDirectory() as folder:
            proc = Path(folder)
            (proc / "42/fd").mkdir(parents=True)
            (proc / "net").mkdir()
            (proc / "42/fd/7").symlink_to("socket:[12345]")
            (proc / "net/tcp6").write_text("header\n")
            (proc / "net/tcp").write_text("header\n0: 0100007F:1F41 00000000:0000 0A 0 0 0 0 0 99999\n")
            self.assertFalse(check.owns_listener(42, proc))
            (proc / "net/tcp").write_text("header\n0: 0100007F:1F41 00000000:0000 0A 0 0 0 0 0 12345\n")
            self.assertTrue(check.owns_listener(42, proc))
            (proc / "net/tcp").write_text("header\n0: 00000000:1F41 00000000:0000 0A 0 0 0 0 0 12345\n")
            self.assertFalse(check.owns_listener(42, proc))

    def test_old_or_wrong_process_beacon_does_not_prove_deployment(self):
        now = dt.datetime.now(dt.timezone.utc)
        sha = "a" * 40
        row = {"event": "engine_boot", "reason": "engine process started: pid=42 commit=aaaaaaa agents=30",
               "ts": (now - dt.timedelta(seconds=2)).isoformat()}
        self.assertTrue(check.boot_matches(row, 42, sha, now - dt.timedelta(seconds=5)))
        self.assertFalse(check.boot_matches(row, 41, sha, now - dt.timedelta(seconds=5)))
        self.assertFalse(check.boot_matches(row, 42, "b" * 40, now - dt.timedelta(seconds=5)))
        self.assertFalse(check.boot_matches(row, 42, sha, now))
        broken = copy.deepcopy(row)
        broken["reason"] = "engine process started: pid=42 commit=unknown agents=30"
        self.assertFalse(check.boot_matches(broken, 42, sha, now - dt.timedelta(seconds=5)))


if __name__ == "__main__":
    unittest.main()
