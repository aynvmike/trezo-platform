"""The agents' own end-of-day analytics (Mike 2026-07-27).

"Why would it be a task by you and not something the agents would
automatically get done?" -- correct. Nova's scheduled task only runs
when the desktop and Claude are open; the engine runs 24/7. Analysis of
the agents' own trading belongs to the agents.

Runs from ops_watchdog's daily gate. Computes the day the machine
actually had -- realized P&L by lane, profit factor, win/loss, the
decision funnel, book state, capital bottlenecks -- and writes
TREZO_DAILY_DIGEST.md beside the Rulebook, plus a dated JSON history so
trends can be read back later. Nova (or the web UI) then only has to
PRESENT it; the numbers exist whether anyone is watching or not.

Distinct from Mem0 (semantic recall of past setups) and the knowledge
library (the books' craft). This is the ledger talking about itself.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HIST = Path(__file__).with_name("_digest_history.json")


def _doc_path() -> Path:
    return (Path(__file__).resolve().parents[3] / ".."
            ).resolve() / "TREZO_DAILY_DIGEST.md"


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _lane(asset_type: str, strategy: str) -> str:
    a = (asset_type or "").lower()
    s = (strategy or "").lower()
    if a == "crypto" or s.startswith("crypto"):
        return "crypto"
    if a == "forex" or s.startswith("forex"):
        return "forex"
    if a in ("option", "options") or s.startswith(("wheel", "option")):
        return "options"
    return "stocks"


async def build_digest(client, equity: float = 0.0,
                       crypto_usd: float = 0.0) -> dict:
    """Compute + persist today's digest. Returns the summary dict."""
    import asyncio
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=4, minute=0, second=0, microsecond=0)
    if now < day_start:
        day_start -= timedelta(days=1)
    since = day_start.isoformat()
    out: dict = {"date": now.strftime("%Y-%m-%d"), "generated": now.isoformat()}

    def _closed():
        return (client.table("paper_positions")
                .select("ticker, asset_type, strategy, realized_pnl_usd, status")
                .neq("status", "open").gte("exit_at", since)
                .limit(300).execute())

    def _open():
        return (client.table("paper_positions")
                .select("ticker, asset_type, strategy, entry_price, quantity")
                .eq("status", "open").limit(100).execute())

    def _msgs():
        return (client.table("agent_messages")
                .select("kind, payload").gte("created_at", since)
                .limit(4000).execute())

    try:
        closed = (await asyncio.to_thread(_closed)).data or []
        openb = (await asyncio.to_thread(_open)).data or []
        msgs = (await asyncio.to_thread(_msgs)).data or []
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:160]
        return out

    lanes: dict[str, dict] = {}
    wins = losses = 0.0
    wn = ln = 0
    for c in closed:
        p = _f(c.get("realized_pnl_usd"))
        ln_ = _lane(c.get("asset_type"), c.get("strategy"))
        d = lanes.setdefault(ln_, {"n": 0, "w": 0, "net": 0.0,
                                   "won": 0.0, "lost": 0.0})
        d["n"] += 1
        d["net"] += p
        if p >= 0:
            d["w"] += 1
            d["won"] += p
            wins += p
            wn += 1
        else:
            d["lost"] += -p
            losses += -p
            ln += 1
    net = wins - losses
    pf = (wins / losses) if losses > 0 else (99.0 if wins > 0 else 0.0)
    out.update({
        "closed": len(closed), "wins": wn, "losses": ln,
        "gross_won": round(wins, 2), "gross_lost": round(losses, 2),
        "net_realized": round(net, 2), "profit_factor": round(pf, 2),
        "lanes": {k: {kk: (round(vv, 2) if isinstance(vv, float) else vv)
                      for kk, vv in v.items()} for k, v in lanes.items()},
        "open_positions": len(openb),
        "open_mix": dict(Counter(_lane(o.get("asset_type"),
                                       o.get("strategy")) for o in openb)),
        "equity": round(_f(equity), 2),
        "crypto_usd": round(_f(crypto_usd), 2),
    })

    kinds = Counter(m.get("kind") for m in msgs)
    vetoes = [m for m in msgs if m.get("kind") == "veto"]
    vr = Counter(str((m.get("payload") or {}).get("reason") or "")[:55]
                 for m in vetoes)
    out["funnel"] = {k: kinds.get(k, 0) for k in
                     ("signal", "approve", "execute", "veto", "error")}
    out["top_veto"] = vr.most_common(3)

    # Goal context: ~1% of equity is the target Mike manages to.
    eq = _f(equity)
    out["target_1pct"] = round(eq * 0.01, 2) if eq else None
    out["hit_floor_10"] = net >= 10.0
    out["hit_target"] = bool(eq and net >= eq * 0.01)

    # Silent-execution alarm: the pattern that meant a real bug twice.
    out["alarm"] = None
    if out["funnel"]["approve"] >= 10 and out["funnel"]["execute"] == 0:
        out["alarm"] = ("approvals are flowing but NOTHING executed -- "
                        "check the executor and broker path immediately")

    _write_history(out)
    _write_doc(out)
    return out


def _write_history(row: dict) -> None:
    try:
        hist = json.loads(_HIST.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        hist = []
    hist = [h for h in hist if h.get("date") != row.get("date")][-120:]
    hist.append(row)
    try:
        tmp = _HIST.with_suffix(".tmp")
        tmp.write_text(json.dumps(hist, indent=1), encoding="utf-8")
        tmp.replace(_HIST)
    except Exception:  # noqa: BLE001
        pass


def history(days: int = 14) -> list[dict]:
    try:
        return json.loads(_HIST.read_text(encoding="utf-8"))[-days:]
    except Exception:  # noqa: BLE001
        return []


def _write_doc(d: dict) -> None:
    L = [f"# Trezo — Daily Digest · {d.get('date')}\n",
         "_Written by the agents from their own ledger, every day, "
         "whether or not anyone is watching._\n"]
    net = d.get("net_realized", 0.0)
    tgt = d.get("target_1pct")
    verdict = ("GREEN" if net > 0 else "RED" if net < 0 else "FLAT")
    L.append(f"**{verdict} day: ${net:+,.2f} realized** on "
             f"{d.get('closed', 0)} closed trades "
             f"({d.get('wins', 0)}W / {d.get('losses', 0)}L, "
             f"profit factor {d.get('profit_factor')}).")
    if tgt:
        L.append(f"Target was ~${tgt:,.2f} (1% of ${d.get('equity'):,.2f} "
                 f"equity); the $10/day floor was "
                 f"{'CLEARED' if d.get('hit_floor_10') else 'missed'}.\n")
    L.append("\n## Which lane earned it\n")
    for lane, v in sorted(d.get("lanes", {}).items(),
                          key=lambda kv: -kv[1]["net"]):
        L.append(f"- **{lane}** — {v['n']} closed, {v['w']} green, "
                 f"net ${v['net']:+,.2f} (won ${v['won']:,.2f} / "
                 f"lost ${v['lost']:,.2f})")
    if not d.get("lanes"):
        L.append("- nothing closed today")
    L.append(f"\n## The book\n\n{d.get('open_positions')} open — "
             f"{d.get('open_mix')}. Crypto-spendable USD: "
             f"${d.get('crypto_usd'):,.2f}"
             + (" (exhausted — the 24/7 lane cannot open new positions "
                "until collateral or a position frees)"
                if _f(d.get("crypto_usd")) < 25 else "") + "\n")
    f = d.get("funnel", {})
    L.append(f"\n## The machine\n\nsignals {f.get('signal')} · approvals "
             f"{f.get('approve')} · executions {f.get('execute')} · "
             f"vetoes {f.get('veto')} · errors {f.get('error')}\n")
    for r, n in d.get("top_veto", []):
        L.append(f"- {n}× — {r}")
    if d.get("alarm"):
        L.append(f"\n> **ALARM:** {d['alarm']}\n")
    try:
        _doc_path().write_text("\n".join(L) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
