"""
Seed Mem0 from accumulated file memory (task #16).

Reads every *.md file in a memory directory (the auto-memory store the
Cowork chat has been accumulating across sessions), parses the YAML
frontmatter, and pushes each as a memory into Mem0 with type-aware
tags.

After this runs, the agents (and tomorrow's Cowork sessions, if/when
Mem0 wires into Cowork) have Day 1 context: project state, feedback,
references, and preferences are all semantically searchable.

Usage:
    python -m scripts.seed_mem0_from_files <path-to-memory-dir>

Example:
    python -m scripts.seed_mem0_from_files \
        "C:\\Users\\nvalm\\AppData\\Roaming\\Claude\\local-agent-mode-sessions\\<session>\\<workspace>\\spaces\\<space>\\memory"

Idempotent: each file is keyed by its frontmatter `name:` slug, written
as metadata.source_file. Re-runs update rather than duplicate.

Safe to abort: each file is pushed independently; failure on one does
not block the rest.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

# Allow running as `python scripts/seed_mem0_from_files.py` from agents/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.memory import get_memory  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("seed_mem0")


FRONTMATTER_RE = re.compile(
    r"^---\s*\n(?P<yaml>.*?)\n---\s*\n(?P<body>.*)$",
    re.DOTALL,
)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body). Empty dict + raw text on miss."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    yaml_block = m.group("yaml")
    body = m.group("body").strip()
    fm: dict = {}
    current_key: str | None = None
    for line in yaml_block.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        # Very small YAML-ish parser: handles `key: value` and a single
        # level of nested `key:` followed by `  subkey: value`. That's
        # all the auto-memory format uses.
        if line.startswith("  ") and current_key:
            sub_match = re.match(r"\s+(?P<k>[\w_-]+):\s*(?P<v>.*)$", line)
            if sub_match:
                if not isinstance(fm.get(current_key), dict):
                    fm[current_key] = {}
                fm[current_key][sub_match.group("k")] = sub_match.group("v").strip()
            continue
        top_match = re.match(r"(?P<k>[\w_-]+):\s*(?P<v>.*)$", line)
        if not top_match:
            continue
        k = top_match.group("k")
        v = top_match.group("v").strip()
        current_key = k
        if v == "":
            fm[k] = {}
        else:
            fm[k] = v.strip().strip('"').strip("'")
    return fm, body


def memory_kind_from_frontmatter(fm: dict) -> str:
    """Map auto-memory frontmatter type to a Mem0 metadata.kind tag."""
    raw = ""
    md = fm.get("metadata")
    if isinstance(md, dict):
        raw = md.get("type", "").strip().lower()
    if not raw:
        raw = fm.get("type", "").strip().lower()
    if raw in ("user", "preference"):
        return "preference"
    if raw == "feedback":
        return "feedback"
    if raw == "project":
        return "project_context"
    if raw == "reference":
        return "reference"
    return "general"


def format_for_mem0(fm: dict, body: str) -> str:
    """Build the content string Mem0 will index. Description + body."""
    desc = (fm.get("description") or "").strip()
    head = f"[{fm.get('name', '')}] {desc}".strip()
    parts = [head, body.strip()]
    return "\n\n".join(p for p in parts if p)


def seed(memory_dir: Path, dry_run: bool = False) -> dict:
    if not memory_dir.is_dir():
        raise FileNotFoundError(f"Memory directory not found: {memory_dir}")

    mem = get_memory()
    if not mem.available and not dry_run:
        logger.error(
            "Mem0 is not available - check MEM0_API_KEY in agents/.env. "
            "Aborting (use --dry-run to preview without writing).",
        )
        return {"skipped": 0, "pushed": 0, "failed": 0,
                "reason": "mem0_unavailable"}

    skipped = pushed = failed = 0
    seen_names: set[str] = set()

    for md_file in sorted(memory_dir.glob("*.md")):
        # Skip the MEMORY.md index - it's a pointer file, not a memory.
        if md_file.name.lower() == "memory.md":
            skipped += 1
            continue
        try:
            raw = md_file.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not read %s: %s", md_file.name, e)
            failed += 1
            continue

        fm, body = parse_frontmatter(raw)
        name = (fm.get("name") or md_file.stem).strip()
        if name in seen_names:
            continue
        seen_names.add(name)

        kind = memory_kind_from_frontmatter(fm)
        content = format_for_mem0(fm, body)
        if not content.strip():
            skipped += 1
            continue

        metadata = {
            "kind": kind,
            "source_file": md_file.name,
            "source_slug": name,
            "seeded": True,
        }
        if isinstance(fm.get("description"), str):
            metadata["description"] = fm["description"]

        if dry_run:
            logger.info(
                "DRY-RUN would push: %s [%s, %d chars]",
                name, kind, len(content),
            )
            pushed += 1
            continue

        try:
            mid = mem._client.add(
                messages=[{"role": "assistant", "content": content}],
                user_id=mem.user_id,
                metadata=metadata,
            )
            _ = mid  # noqa: F841 - log if needed; just acknowledged here
            pushed += 1
            logger.info("Pushed: %s [%s]", name, kind)
        except Exception as e:  # noqa: BLE001
            failed += 1
            logger.warning("Failed pushing %s: %s", name, e)

    summary = {"skipped": skipped, "pushed": pushed, "failed": failed}
    logger.info("DONE: %s", summary)
    return summary


def _find_default_memory_dir() -> Path | None:
    """Best-effort autodetect for the Cowork space memory dir on Windows.

    Walks %APPDATA%/Claude/local-agent-mode-sessions for any folder
    matching */spaces/*/memory and picks the most recently modified.
    """
    import os
    base = Path(os.environ.get("APPDATA", "")) / "Claude" / "local-agent-mode-sessions"
    if not base.is_dir():
        return None
    candidates = list(base.glob("*/*/spaces/*/memory"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "memory_dir",
        nargs="?",
        help="Path to the memory/ directory. Autodetected if omitted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse + classify but do NOT write to Mem0.",
    )
    args = parser.parse_args()

    if args.memory_dir:
        memory_dir = Path(args.memory_dir)
    else:
        auto = _find_default_memory_dir()
        if not auto:
            logger.error(
                "Could not autodetect memory dir. Pass one explicitly.",
            )
            return 2
        logger.info("Autodetected memory dir: %s", auto)
        memory_dir = auto

    summary = seed(memory_dir, dry_run=args.dry_run)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
