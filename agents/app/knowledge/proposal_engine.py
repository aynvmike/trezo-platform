"""Turns the agents' own logged behaviour into written proposals.

Runs once a day from ops_watchdog. Reads the last 24-48h of decisions
and outcomes, looks for patterns that a human would want to know about,
and files them through app.knowledge.proposals -- which writes
TREZO_AGENT_PROPOSALS.md for Mike.

Every detector must produce EVIDENCE (counts, dollars, records). A
detector that cannot say "here is the number" does not get to speak.
Nothing here edits a rule; the agents argue, Mike decides.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.knowledge.proposals import propose, render_doc


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


async def run_detectors(client) -> dict:
    """One daily pass. Returns a summary dict; never raises."""
    out = {"filed": [], "doc": None}
    if client is None:
        return out
    import asyncio
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    def _msgs():
        return (client.table("agent_messages")
                .select("kind, agent_name, payload, created_at")
                .gte("created_at", since).limit(4000).execute())
    try:
        rows = (await asyncio.to_thread(_msgs)).data or []
    except Exception:  # noqa: BLE001
        return out

    vetoes = [r for r in rows if r.get("kind") == "veto"]
    approves = [r for r in rows if r.get("kind") == "approve"]
    execs = [r for r in rows if r.get("kind") == "execute"]
    errors = [r for r in rows if r.get("kind") == "error"]

    # --- 1. A single veto reason dominating the day ------------------
    if len(vetoes) >= 40:
        reasons = Counter()
        for v in vetoes:
            r = str((v.get("payload") or {}).get("reason") or "")[:60]
            reasons[r] += 1
        top, n = reasons.most_common(1)[0]
        share = n / float(len(vetoes))
        if share >= 0.45 and top:
            key = "veto_dominant:" + top[:40].lower().replace(" ", "_")
            propose(
                key,
                area="Gates / capacity",
                title=f"One refusal is doing {share:.0%} of the vetoing: “{top.strip()}”",
                observation=(
                    f"Of {len(vetoes)} refusals in the last 24h, {n} were the "
                    f"same reason. When one gate accounts for nearly half of "
                    f"every 'no', it is shaping the book more than the "
                    f"strategies are."),
                evidence=(f"{n}/{len(vetoes)} vetoes ({share:.0%}) in 24h; "
                          f"{len(approves)} approvals and {len(execs)} "
                          f"executions in the same window."),
                impact=("Signals that pass every quality test are being "
                        "turned away by a capacity or configuration limit, "
                        "not by their own merit."),
                suggestion=(
                    "Review whether this limit is still the right size for "
                    "the account. If it is a position/slot cap, raising it "
                    "one notch converts refused signals into shots on goal; "
                    "if it is a data or config gate, fixing the source "
                    "removes the refusals entirely."),
                agent="ops_watchdog",
            )
            out["filed"].append(key)

    # --- 2. Repeated broker rejects of the same shape ----------------
    if errors:
        shapes = Counter()
        for e in errors:
            msg = str((e.get("payload") or {}).get("error") or "")
            if "rejected" in msg.lower() or "HTTP 4" in msg:
                shapes[msg[:70]] += 1
        if shapes:
            top, n = shapes.most_common(1)[0]
            if n >= 3:
                key = "broker_reject:" + top[:40].lower().replace(" ", "_")
                propose(
                    key,
                    area="Execution / broker",
                    title=f"The broker keeps refusing the same order shape ({n}× in 24h)",
                    observation=(
                        f"“{top.strip()}” was rejected {n} times in 24 hours. "
                        f"Repeated rejects of one shape are a construction "
                        f"bug, not market conditions."),
                    evidence=f"{n} identical-shape rejects in 24h out of {len(errors)} errors.",
                    impact=("Rejects count toward the kill-switch, so a "
                            "recurring malformed order can pause every "
                            "lane -- including the 24/7 ones."),
                    suggestion=("Validate this order shape locally before "
                                "submission so a malformed order never "
                                "reaches the broker or the halt counter."),
                    agent="trade_execution",
                )
                out["filed"].append(key)

    # --- 3. Strategy records worth acting on -------------------------
    def _closed():
        return (client.table("paper_positions")
                .select("strategy, realized_pnl_usd, exit_at")
                .neq("status", "open")
                .gte("exit_at", (datetime.now(timezone.utc)
                                 - timedelta(days=21)).isoformat())
                .limit(500).execute())
    try:
        closed = (await asyncio.to_thread(_closed)).data or []
    except Exception:  # noqa: BLE001
        closed = []
    by = {}
    for c in closed:
        s = str(c.get("strategy") or "unknown")
        p = _f(c.get("realized_pnl_usd"))
        d = by.setdefault(s, {"n": 0, "w": 0, "win": 0.0, "loss": 0.0,
                              "pnls": []})
        d["n"] += 1
        d["pnls"].append(p)
        if p >= 0:
            d["w"] += 1
            d["win"] += p
        else:
            d["loss"] += -p
    for s, d in by.items():
        if d["n"] < 8:
            continue                     # the platform's 8-trade minimum
        pf = (d["win"] / d["loss"]) if d["loss"] > 0 else 99.0
        wr = d["w"] / d["n"]

        # SIGNIFICANCE GATE (de Prado, ch.14-15; added 2026-08-05).
        # A profit factor computed on a couple of dozen trades is mostly
        # noise. Before claiming a lane is weak or strong, ask whether the
        # sample can support the claim at all, and what win rate the lane's
        # OWN realised geometry actually demands. Both are appended to the
        # evidence; neither blocks the proposal, because a proposal that
        # says "this might be noise" is more useful than one suppressed.
        _sig_line = ""
        try:
            from app.runtime.significance import (
                bootstrap_mean_test, implied_precision,
            )
            _bt = bootstrap_mean_test(d["pnls"], iterations=4000)
            _wins = [x for x in d["pnls"] if x > 0]
            _loss = [x for x in d["pnls"] if x <= 0]
            _need = None
            if len(_wins) >= 2 and len(_loss) >= 2:
                _aw = sum(_wins) / len(_wins)
                _al = sum(_loss) / len(_loss)
                _sc = (abs(_aw) + abs(_al)) / 2.0
                if _sc > 0:
                    _need = implied_precision(_al / _sc, _aw / _sc,
                                              d["n"] / 21 * 365, 0.0)
            if _bt is not None:
                if _bt.get("conclusive"):
                    _sig_line = (
                        f" SIGNIFICANCE: with {d['n']} trades the 95% interval "
                        f"for average P&L per trade is "
                        f"${_bt['ci95_low']:+.2f} to ${_bt['ci95_high']:+.2f}, "
                        f"which does NOT straddle zero -- this result is "
                        f"distinguishable from luck.")
                else:
                    _sig_line = (
                        f" SIGNIFICANCE: with only {d['n']} trades the 95% "
                        f"interval for average P&L per trade runs "
                        f"${_bt['ci95_low']:+.2f} to ${_bt['ci95_high']:+.2f}, "
                        f"which STRADDLES ZERO. This sample cannot yet tell "
                        f"profit from noise, so treat the figure above as a "
                        f"signal to keep watching rather than as a finding.")
            if _need is not None:
                _sig_line += (
                    f" GEOMETRY: its realised win/loss sizes demand a "
                    f"{_need:.0%} win rate just to break even; it is running "
                    f"at {wr:.0%}.")
        except Exception:  # noqa: BLE001
            _sig_line = ""
        if pf < 0.8:
            key = f"strategy_weak:{s}"
            propose(
                key,
                area="Strategy weighting",
                title=f"{s} is not paying for itself (PF {pf:.2f} over {d['n']} trades)",
                observation=(
                    f"{s} closed {d['n']} trades in 21 days: {d['w']} wins, "
                    f"${d['win']:.2f} gross won against ${d['loss']:.2f} "
                    f"gross lost."),
                evidence=(f"PF {pf:.2f}, win rate {wr:.0%}, net "
                          f"${d['win'] - d['loss']:+.2f} over {d['n']} "
                          f"closed trades.{_sig_line}"),
                impact="Capital committed here is earning less than it loses.",
                suggestion=(
                    f"Either raise {s}'s confidence bar so only its best "
                    f"setups trade, or shrink its allocation until the "
                    f"record recovers. The outcome loop can do this itself "
                    f"once its sample threshold is met -- this proposal is "
                    f"the human-visible version of that same evidence."),
                agent="learning_loop",
            )
            out["filed"].append(key)
        elif pf >= 2.0 and d["n"] >= 10:
            key = f"strategy_strong:{s}"
            propose(
                key,
                area="Strategy weighting",
                title=f"{s} is earning its keep (PF {pf:.2f} over {d['n']} trades)",
                observation=(
                    f"{s} closed {d['n']} trades in 21 days with {d['w']} "
                    f"wins and a profit factor of {pf:.2f}."),
                evidence=(f"PF {pf:.2f}, win rate {wr:.0%}, net "
                          f"${d['win'] - d['loss']:+.2f} over {d['n']} "
                          f"closed trades.{_sig_line}"),
                impact="This lane is currently the most reliable source of daily income.",
                suggestion=(
                    f"Consider giving {s} a larger share of the daily "
                    f"capital, or letting it take more concurrent shots, "
                    f"while the record holds. Re-check after every 10 "
                    f"further closes -- a good record is a lease, not a deed."),
                agent="learning_loop",
            )
            out["filed"].append(key)

    # --- 4. Signals dying just under the confidence bar --------------
    near = Counter()
    for v in vetoes:
        p = v.get("payload") or {}
        r = str(p.get("reason") or "")
        if "below threshold" in r:
            try:
                got = int(str(r).split("TCS ")[1].split(" ")[0])
                need = int(str(r).split("threshold ")[1].split(" ")[0])
                if 0 < need - got <= 3:
                    near[str(p.get("strategy") or "?")] += 1
            except Exception:  # noqa: BLE001
                pass
    if near:
        s, n = near.most_common(1)[0]
        if n >= 10:
            key = f"near_miss:{s}"
            propose(
                key,
                area="Confidence floor",
                title=f"{n} {s} setups missed the bar by 3 points or less",
                observation=(
                    f"In 24 hours, {n} {s} signals scored within 3 points of "
                    f"the floor and were refused. That is a crowd at the "
                    f"door, not a trickle."),
                evidence=f"{n} near-miss refusals in 24h for {s}.",
                impact=("These may be the cheapest available additional "
                        "trades -- or the exact trades that should stay "
                        "refused. Only a shadow test can tell."),
                suggestion=(
                    "Do NOT lower the floor on a hunch. Run these near-"
                    "misses in shadow: record what they WOULD have returned "
                    "for two weeks, then move the floor only if the shadow "
                    "ledger is profitable. Evidence first, dial second."),
                agent="risk_manager",
            )
            out["filed"].append(key)

    out["doc"] = render_doc()
    return out
