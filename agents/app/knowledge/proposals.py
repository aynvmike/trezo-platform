"""Agent rule-change proposals (Mike 2026-07-27).

"Can we make it a way that the agents can have a way to show the changes
that they believe should happen, in a document such as rules and formulas."

The agents already SEE more of their own behaviour than any human can
read: every veto reason, every broker reject, every closed outcome. This
module lets them turn that evidence into a written PROPOSAL -- never a
silent self-edit. Nothing here changes a rule. It writes a document Mike
reads, exactly like the Rulebook, and he decides.

Design rules (they mirror the platform's own laws):
  * EVIDENCE OR SILENCE. A proposal must carry counts, dollars, or an
    outcome record. No hunches.
  * ONE VOICE PER ISSUE. Re-observing the same thing updates the
    existing proposal's evidence and count -- it never spams new rows.
  * SELF-RETIRING. A proposal that stops being observed for
    TREZO_PROPOSAL_STALE_DAYS (default 14) drops off the active list.
  * MIKE DECIDES. Status starts at 'open' and only a human moves it.

Output: TREZO_AGENT_PROPOSALS.md beside the Rulebook in C:\\Trezo, plus
a JSON store the agents read back so evidence accumulates across
restarts.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

_STORE = Path(__file__).with_name("_proposals.json")


def _doc_path() -> Path:
    """C:\\Trezo\\TREZO_AGENT_PROPOSALS.md (next to the Rulebook)."""
    return (Path(__file__).resolve().parents[3] / ".."
            ).resolve() / "TREZO_AGENT_PROPOSALS.md"


def _load() -> dict:
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(d: dict) -> None:
    try:
        tmp = _STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
        tmp.replace(_STORE)
    except Exception:  # noqa: BLE001
        pass


def propose(key: str, *, area: str, title: str, observation: str,
            suggestion: str, evidence: str, agent: str = "system",
            impact: str = "") -> None:
    """File (or re-observe) one proposal. `key` is the stable identity --
    same key = same issue, so evidence accumulates instead of duplicating."""
    now = datetime.now(timezone.utc).isoformat()
    d = _load()
    row = d.get(key) or {"first_seen": now, "times_observed": 0,
                         "status": "open"}
    row.update({
        "area": area, "title": title, "observation": observation,
        "suggestion": suggestion, "evidence": evidence, "impact": impact,
        "agent": agent, "last_seen": now,
        "times_observed": int(row.get("times_observed", 0)) + 1,
    })
    d[key] = row
    _save(d)


def resolve(key: str, note: str = "") -> None:
    """Mark a proposal handled (called after a rule actually ships)."""
    d = _load()
    if key in d:
        d[key]["status"] = "shipped"
        d[key]["resolved_note"] = note
        d[key]["resolved_at"] = datetime.now(timezone.utc).isoformat()
        _save(d)


def _stale_days() -> float:
    try:
        return float(os.getenv("TREZO_PROPOSAL_STALE_DAYS", "14"))
    except (TypeError, ValueError):
        return 14.0


def render_doc() -> str:
    """Write the human-facing proposals document. Returns its path."""
    d = _load()
    now = datetime.now(timezone.utc)
    active, shipped, stale = [], [], []
    for key, r in d.items():
        try:
            last = datetime.fromisoformat(str(r.get("last_seen")))
            age = (now - last).days
        except Exception:  # noqa: BLE001
            age = 0
        if r.get("status") == "shipped":
            shipped.append((key, r))
        elif age > _stale_days():
            stale.append((key, r, age))
        else:
            active.append((key, r))
    # Most-observed first: repetition IS the strength of the evidence.
    active.sort(key=lambda kr: -int(kr[1].get("times_observed", 0)))

    L = []
    L.append("# Trezo — What the Agents Would Change\n")
    L.append("_Written by the agents from their own logged evidence. "
             "Nothing here is self-applied: these are proposals for Mike, "
             "the same way the Rulebook is a record of decisions already "
             "made._\n")
    L.append(f"_Last updated {now.strftime('%Y-%m-%d %H:%M UTC')} · "
             f"{len(active)} open · {len(shipped)} shipped_\n")
    L.append("---\n")
    if not active:
        L.append("## No open proposals\n\nThe agents have not observed "
                 "anything with enough evidence to argue about. Quiet is "
                 "a valid verdict.\n")
    for key, r in active:
        L.append(f"## {r.get('title')}\n")
        L.append(f"**Area:** {r.get('area')}  ·  **Raised by:** "
                 f"{r.get('agent')}  ·  **Observed "
                 f"{r.get('times_observed')}×** since "
                 f"{str(r.get('first_seen'))[:10]}\n")
        L.append(f"**What the agents keep seeing:** {r.get('observation')}\n")
        L.append(f"**Evidence:** {r.get('evidence')}\n")
        if r.get("impact"):
            L.append(f"**Why it matters:** {r.get('impact')}\n")
        L.append(f"**Proposed change:** {r.get('suggestion')}\n")
        L.append(f"`proposal key: {key}`\n")
        L.append("---\n")
    if shipped:
        L.append("## Shipped\n")
        for key, r in shipped:
            L.append(f"- **{r.get('title')}** — "
                     f"{r.get('resolved_note') or 'implemented'} "
                     f"({str(r.get('resolved_at'))[:10]})\n")
    if stale:
        L.append("\n## Retired (no longer observed)\n")
        for key, r, age in stale:
            L.append(f"- {r.get('title')} — last seen {age} days ago\n")
    text = "\n".join(L)
    try:
        _doc_path().write_text(text, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return str(_doc_path())


def open_proposals() -> list[dict]:
    """Active proposals, richest evidence first (for the API / UI)."""
    d = _load()
    rows = [dict(r, key=k) for k, r in d.items()
            if r.get("status") != "shipped"]
    rows.sort(key=lambda r: -int(r.get("times_observed", 0)))
    return rows
