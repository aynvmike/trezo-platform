#!/usr/bin/env python3
"""Read-only gate for the pinned Supabase stack plus loopback overlay.

Requires Docker Compose >=2.24.4 and a prepared stack/.env. Resolved
configuration contains secrets: capture it only in memory, never print it.
This checks the proposed port configuration, not running services or health.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

EXPECTED_PORTS = {
    ("api-gw", "127.0.0.1", "54321", "8000", "tcp"),
    ("db", "127.0.0.1", "54322", "5432", "tcp"),
}
MIN_COMPOSE = (2, 24, 4)


class VerificationError(Exception):
    """Carries a fixed issue code only, never subprocess/configuration text."""


def config_issues(config: object) -> list[str]:
    if not isinstance(config, dict) or not isinstance(config.get("services"), dict):
        return ["compose_services_missing_or_invalid"]
    services = config["services"]
    issues = []
    if not {"api-gw", "db", "supavisor"}.issubset(services):
        issues.append("required_supabase_services_missing")
    ports = []
    for name, service in services.items():
        if not isinstance(service, dict):
            issues.append("compose_service_invalid")
            continue
        if service.get("network_mode") == "host":
            issues.append("host_networking_not_allowed")
        bindings = service.get("ports", [])
        if bindings is None:
            bindings = []
        if not isinstance(bindings, list):
            issues.append("published_ports_not_normalized")
            continue
        for port in bindings:
            if not isinstance(port, dict):
                issues.append("published_ports_not_normalized")
                continue
            ports.append((name, str(port.get("host_ip", "")),
                          str(port.get("published", "")), str(port.get("target", "")),
                          str(port.get("protocol", "tcp"))))
    if len(ports) != 2 or set(ports) != EXPECTED_PORTS:
        issues.append("only_the_two_expected_loopback_ports_may_be_published")
    for name, service in services.items():
        if not isinstance(service, dict):
            continue
        env = service.get("environment") or {}
        if not isinstance(env, dict):
            issues.append("compose_environment_not_normalized")
            continue
        for key in ("POSTGRES_PORT", "PGPORT"):
            if (key in env or name == "db") and str(env.get(key, "")) != "5432":
                issues.append("postgres_internal_port_must_remain_5432")
    return sorted(set(issues))


def capture(command: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True,
                                text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise VerificationError("docker_compose_unavailable_or_timed_out") from None
    if result.returncode:
        # stderr can include interpolated secrets; never forward it.
        raise VerificationError("docker_compose_command_failed_output_withheld")
    return result.stdout


def verify(stack: Path, override: Path) -> list[str]:
    stack, override = stack.resolve(), override.resolve()
    if not all(p.is_file() for p in (stack / "docker-compose.yml", stack / ".env", override)):
        raise VerificationError("stack_compose_env_or_override_file_missing")
    version = capture(["docker", "compose", "version", "--short"], stack).strip()
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.-]+)?", version)
    if not match or tuple(map(int, match.groups())) < MIN_COMPOSE:
        raise VerificationError("docker_compose_2_24_4_or_later_required")
    raw = capture(["docker", "compose", "--project-directory", str(stack),
                   "--env-file", str(stack / ".env"), "--profile", "*",
                   "-f", str(stack / "docker-compose.yml"), "-f", str(override),
                   "config", "--format", "json"], stack)
    try:
        config = json.loads(raw)
    except (ValueError, TypeError):
        raise VerificationError("resolved_compose_json_invalid_output_withheld") from None
    return config_issues(config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", type=Path, required=True,
                        help="prepared Supabase docker directory containing .env")
    parser.add_argument("--override", type=Path,
                        default=Path(__file__).with_name("supabase-loopback.yml"))
    args = parser.parse_args(argv)
    try:
        issues = verify(args.stack, args.override)
    except VerificationError as exc:
        issues = [str(exc)]
    except Exception:
        # No traceback or configuration output on an unexpected failure.
        issues = ["verification_failed_output_withheld"]
    print(json.dumps({"status": "fail" if issues else "pass", "issues": issues,
                      "services_started": False}))
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
