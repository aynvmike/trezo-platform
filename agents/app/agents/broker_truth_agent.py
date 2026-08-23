"""Broker Truth agent — keeps the option ledger honest against Alpaca.

Mike 2026-08-23: "make sure that the alpaca and live is always accurate."

A dedicated agent rather than another job bolted onto Position Monitor or
Book Health. Two reasons. Load: those two already run every 60s and every
300s doing their own work, and option reconciliation means an extra broker
round-trip per book. Blame: when the ledger and the broker disagree, the
question "which component was supposed to notice?" should have exactly one
answer.

Cadence is 15 minutes, not 60 seconds. Option drift is a slow, structural
disagreement — an expiry that settled, an order that never landed. Polling
it every minute would spend three broker calls a minute to catch something
that changes a few times a week.

It CLOSES only the unambiguous case (expired, settled out of the money,
nothing to move) and FLAGS everything else loudly. See
app/paper/broker_truth.py for why that asymmetry is deliberate.
"""

from __future__ import annotations

from app.paper.broker_truth import reconcile_options_all_books

from .base import Agent, AgentMessage


class BrokerTruthAgent(Agent):
    name = "broker_truth"
    tick_interval_seconds = 900   # 15 min

    async def tick(self) -> list[AgentMessage]:
        try:
            result = await reconcile_options_all_books()
        except Exception as e:  # noqa: BLE001
            return [AgentMessage(agent=self.name, kind="error",
                                 payload={"ticker": "BROKER_TRUTH",
                                          "error": str(e)[:200]})]

        if not result.get("ok"):
            return [AgentMessage(agent=self.name, kind="error",
                                 payload={"ticker": "BROKER_TRUTH",
                                          "error": result.get("error")})]

        out: list[AgentMessage] = []

        for rep in result.get("reports", []):
            uid = rep.get("user_id")

            for c in rep.get("closed", []):
                out.append(AgentMessage(
                    agent=self.name, kind="info", confidence=1.0,
                    payload={
                        "user_id": uid, "ticker": c["symbol"],
                        "event": "expired_option_reconciled",
                        "note": (f"{c['symbol']} expired worthless and the "
                                 f"broker had already dropped it — ledger "
                                 f"closed, realized ${c['realized']:.2f}. "
                                 f"Its collateral is released."),
                    }))

            for f in rep.get("flagged", []):
                # Flags are ALERTS, not info: every one of them is a case
                # the reconciler deliberately refused to guess at.
                out.append(AgentMessage(
                    agent=self.name, kind="alert", confidence=1.0,
                    payload={
                        "user_id": uid, "ticker": f["symbol"],
                        "event": "option_ledger_drift",
                        "note": f"{f['symbol']}: {f['why']}",
                    }))

            for o in rep.get("orphans", []):
                out.append(AgentMessage(
                    agent=self.name, kind="alert", confidence=1.0,
                    payload={
                        "user_id": uid, "ticker": o["symbol"],
                        "event": "untracked_broker_option",
                        "note": f"{o['symbol']}: {o['why']}",
                    }))

        # Only speak when there is something to say. A reconciler that
        # posts "all clear" every 15 minutes trains everyone to skim past
        # the one time it says otherwise.
        if not out:
            return []

        out.append(AgentMessage(
            agent=self.name, kind="info", confidence=1.0,
            payload={
                "ticker": "BROKER_TRUTH",
                "event": "broker_truth_sweep",
                "note": (f"{result['books']} books: "
                         f"{result['closed']} expired closed, "
                         f"{result['flagged']} flagged, "
                         f"{result['orphans']} untracked at broker"),
            }))
        return out
