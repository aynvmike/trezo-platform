"""Seed strategy knowledge into Mem0 so ALL agents can recall it.

2026-06-12 (Mike): "are the strategies tied to the mem0 so all the
agents can see them?" -- they weren't. The coded strategies live in
app/strategies/* (agents run them directly) and the 15 StrategyCards
feed Adaptive Scope, but none of that knowledge -- nor the uploaded
external research (TREZO_PROJECT/06_external_research/INSIGHTS.md) --
was queryable through the shared Mem0 brain.

This script pushes, as kind='strategy_knowledge' memories:
  1. every StrategyCard in app/strategies/library.py (always in sync
     with code -- the cards ARE the source);
  2. each "## " section of INSIGHTS.md (the distilled external algos).

Idempotent: each memory carries a deterministic `knowledge_key`; the
script searches Mem0 first and skips keys that already exist.

Usage [PowerShell, agents venv]:
  python -m scripts.seed_strategy_knowledge --dry-run   # preview
  python -m scripts.seed_strategy_knowledge             # commit
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

AGENTS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENTS_ROOT))


def _existing_keys(mem) -> set[str]:
    keys: set[str] = set()
    try:
        hits = mem.recall_similar(query="strategy knowledge card", limit=100,
                                  kind="strategy_knowledge")
        for h in hits or []:
            k = ((h or {}).get("metadata") or {}).get("knowledge_key")
            if k:
                keys.add(str(k))
    except Exception:  # noqa: BLE001
        pass
    return keys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--insights", default=None,
                    help="Path to INSIGHTS.md (default: autodetect)")
    args = ap.parse_args()

    from app.memory import get_memory
    from app.memory.mem0_client import AgentDecision
    mem = get_memory()
    if not mem.available and not args.dry_run:
        print("Mem0 unavailable - aborting.")
        return 1

    existing = _existing_keys(mem) if not args.dry_run else set()
    planned: list[tuple[str, str, dict]] = []  # (key, content, meta)

    # 1) StrategyCards from the library
    from app.strategies.library import all_strategies
    for card in all_strategies():
        d = card.__dict__ if hasattr(card, "__dict__") else {}
        sid = getattr(card, "strategy_id", None) or d.get("strategy_id") or getattr(card, "name", "unknown")
        key = f"librarycard:{sid}"
        name = getattr(card, "name", sid)
        thesis = getattr(card, "thesis", "")
        family = getattr(card, "family", "")
        regimes = getattr(card, "best_regimes", getattr(card, "regimes", ""))
        layer = getattr(card, "layer", "")
        content = (
            f"Strategy card '{name}' (id={sid}, family={family}, "
            f"layer={layer}, best regimes={regimes}). Thesis: {thesis}"
        )
        planned.append((key, content, {
            "kind": "strategy_knowledge", "knowledge_key": key,
            "strategy": str(sid), "source": "library.py",
        }))

    # 2) INSIGHTS.md sections (external research)
    insights = Path(args.insights) if args.insights else None
    if insights is None:
        for cand in (
            AGENTS_ROOT.parents[1] / "TREZO_PROJECT" / "06_external_research" / "INSIGHTS.md",
            AGENTS_ROOT.parents[0] / "TREZO_PROJECT" / "06_external_research" / "INSIGHTS.md",
        ):
            if cand.is_file():
                insights = cand
                break
    if insights and insights.is_file():
        text = insights.read_text(encoding="utf-8")
        section_title, lines = None, []
        sections: list[tuple[str, str]] = []
        for line in text.splitlines():
            if line.startswith("## "):
                if section_title and lines:
                    sections.append((section_title, "\n".join(lines).strip()))
                section_title, lines = line[3:].strip(), []
            elif section_title:
                lines.append(line)
        if section_title and lines:
            sections.append((section_title, "\n".join(lines).strip()))
        for title, body in sections:
            if not body:
                continue
            key = "insights:" + "".join(c.lower() if c.isalnum() else "-" for c in title)[:60]
            content = f"External strategy research -- {title}: {body[:1500]}"
            planned.append((key, content, {
                "kind": "strategy_knowledge", "knowledge_key": key,
                "source": "INSIGHTS.md",
            }))
    else:
        print("WARNING: INSIGHTS.md not found - seeding library cards only.")

    added = skipped = 0
    for key, content, meta in planned:
        if key in existing:
            skipped += 1
            continue
        if args.dry_run:
            print(f"[dry-run] would add {key}: {content[:90]}...")
            added += 1
            continue
        rid = mem.log_decision(AgentDecision(
            agent="knowledge_seeder", action="seed", ticker="N/A",
            reasoning=content, metadata=meta,
        ))
        if rid:
            added += 1
            print(f"added {key}")
        else:
            print(f"FAILED {key} (budget/pause?)")
    print(f"\ndone: {added} added, {skipped} already present, "
          f"{len(planned)} total planned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
