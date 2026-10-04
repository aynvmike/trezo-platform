import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("verify_compose", Path(__file__).with_name("verify_compose.py"))
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def good_config():
    return {"services": {
        "api-gw": {"ports": [{"host_ip": "127.0.0.1", "published": "54321",
                              "target": 8000, "protocol": "tcp"}]},
        "db": {"ports": [{"host_ip": "127.0.0.1", "published": "54322",
                          "target": 5432, "protocol": "tcp"}],
               "environment": {"POSTGRES_PORT": "5432", "PGPORT": "5432",
                               "POSTGRES_PASSWORD": "test-secret-never-printed"}},
        "supavisor": {"environment": {"POSTGRES_PORT": "5432"}},
    }}


class PortTests(unittest.TestCase):
    def test_exact_loopback_bindings_pass(self):
        self.assertEqual(verify.config_issues(good_config()), [])

    def test_public_or_unspecified_interface_is_rejected(self):
        for host in ("0.0.0.0", "::", "", "192.168.1.4", "::1"):
            config = good_config()
            config["services"]["api-gw"]["ports"][0]["host_ip"] = host
            self.assertTrue(verify.config_issues(config), host)

    def test_additive_merge_or_pooler_publishing_is_rejected(self):
        for service in ("api-gw", "supavisor", "another-service"):
            config = good_config()
            config["services"].setdefault(service, {}).setdefault("ports", []).append(
                {"target": 8000, "published": "8000", "protocol": "tcp"})
            self.assertTrue(verify.config_issues(config), service)

    def test_extra_loopback_port_or_duplicate_is_rejected(self):
        config = good_config()
        config["services"]["db"]["ports"].append(copy.deepcopy(config["services"]["db"]["ports"][0]))
        self.assertTrue(verify.config_issues(config))

    def test_wrong_port_protocol_and_missing_published_port_are_rejected(self):
        for key, value in (("target", 54322), ("published", "6543"), ("protocol", "udp")):
            config = good_config()
            config["services"]["db"]["ports"][0][key] = value
            self.assertTrue(verify.config_issues(config), key)
        config = good_config()
        del config["services"]["api-gw"]["ports"]
        self.assertTrue(verify.config_issues(config))

    def test_host_network_cannot_bypass_the_port_gate(self):
        config = good_config()
        config["services"]["extra"] = {"network_mode": "host"}
        self.assertIn("host_networking_not_allowed", verify.config_issues(config))

    def test_internal_postgres_port_must_not_be_changed_to_host_port(self):
        for name in ("db", "supavisor"):
            config = good_config()
            config["services"][name]["environment"]["POSTGRES_PORT"] = "54322"
            self.assertIn("postgres_internal_port_must_remain_5432", verify.config_issues(config))

    def test_invalid_or_short_form_data_cannot_pass(self):
        for config in (None, [], {}, {"services": {}}, {"services": {"db": None}}):
            self.assertTrue(verify.config_issues(config))
        config = good_config()
        config["services"]["db"]["ports"] = ["127.0.0.1:54322:5432"]
        self.assertIn("published_ports_not_normalized", verify.config_issues(config))


class CommandTests(unittest.TestCase):
    def run_cli(self, side_effect):
        with tempfile.TemporaryDirectory() as folder:
            stack = Path(folder)
            for name in ("docker-compose.yml", ".env", "override.yml"):
                (stack / name).write_text("fixture", encoding="utf-8")
            output = io.StringIO()
            with patch.object(verify.subprocess, "run", side_effect=side_effect) as run, \
                    contextlib.redirect_stdout(output):
                code = verify.main(["--stack", str(stack), "--override", str(stack / "override.yml")])
            return code, output.getvalue(), run.call_args_list

    def test_only_version_and_config_are_run_and_secrets_stay_in_memory(self):
        responses = [subprocess.CompletedProcess([], 0, "2.24.4\n", ""),
                     subprocess.CompletedProcess([], 0, json.dumps(good_config()), "")]
        code, output, calls = self.run_cli(responses)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["status"], "pass")
        self.assertNotIn("test-secret-never-printed", output)
        self.assertEqual(calls[0].args[0], ["docker", "compose", "version", "--short"])
        self.assertEqual(calls[1].args[0][-3:], ["config", "--format", "json"])
        self.assertIn("--env-file", calls[1].args[0])
        self.assertIn("--profile", calls[1].args[0])
        self.assertTrue(all(c.kwargs["capture_output"] for c in calls))

    def test_older_compose_is_rejected_before_config(self):
        code, _, calls = self.run_cli([subprocess.CompletedProcess([], 0, "2.24.3", "")])
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)

    def test_command_failures_and_invalid_json_never_echo_secret_output(self):
        secret = "test-secret-never-printed"
        cases = [
            [subprocess.CompletedProcess([], 1, secret, secret)],
            [subprocess.CompletedProcess([], 0, "2.24.4", ""),
             subprocess.CompletedProcess([], 0, secret, "")],
            subprocess.TimeoutExpired([secret], 60, output=secret, stderr=secret),
        ]
        for responses in cases:
            code, output, _ = self.run_cli(responses)
            self.assertEqual(code, 1)
            self.assertNotIn(secret, output)
            self.assertFalse(json.loads(output)["services_started"])


if __name__ == "__main__":
    unittest.main()
