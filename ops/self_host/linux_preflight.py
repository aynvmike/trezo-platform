#!/usr/bin/env python3
"""Read-only capacity check on the proposed Linux database host; no installs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

GIB = 1024 ** 3


def command(args: list[str]) -> str | None:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def probe(path: Path) -> dict:
    issues = []
    linux = platform.system() == "Linux"
    if not linux:
        issues.append("native_linux_required_for_this_preflight")
    memory = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            memory[key] = int(value.strip().split()[0]) * 1024
    except (OSError, ValueError):
        pass
    available = memory.get("MemAvailable", 0)
    if available < 4 * GIB:
        issues.append("less_than_4_gib_available_memory_for_new_stack")
    cpu = os.cpu_count() or 0
    if cpu < 2:
        issues.append("less_than_2_cpu_cores")
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        free = 0
        issues.append("data_directory_unreadable")
    if free < 40 * GIB:
        issues.append("less_than_40_gib_free_for_data_and_recovery")
    endpoint = command(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"])
    explicit = os.environ.get("DOCKER_HOST", "")
    if not endpoint or not endpoint.startswith("unix://") or (explicit and not explicit.startswith("unix://")):
        issues.append("local_unix_docker_engine_not_verified")
    docker_os = command(["docker", "info", "--format", "{{.OSType}}"])
    if docker_os != "linux":
        issues.append("linux_docker_engine_unavailable")
    if command(["docker", "compose", "version", "--short"]) is None:
        issues.append("docker_compose_unavailable")
    if shutil.which("git") is None:
        issues.append("git_unavailable")
    return {
        "status": "CANDIDATE" if not issues else "BLOCKED", "issues": issues,
        "linux": linux, "cpu_cores": cpu,
        "available_memory_gib": round(available / GIB, 1),
        "free_disk_gib": round(free / GIB, 1),
        "scope": "Point-in-time lower bounds only; reserve capacity, monitor load, verify backups and rehearse restore before cutover.",
        "changes_made": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-directory", type=Path, required=True,
                        help="Existing directory on the intended database volume")
    args = parser.parse_args()
    result = probe(args.data_directory)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "CANDIDATE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
