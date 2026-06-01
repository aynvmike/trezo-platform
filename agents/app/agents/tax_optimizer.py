"""Tax Optimizer Agent.

Phase 7: a real agent, not a heartbeat. Every 30 minutes it reads each
user's YTD realized P&L from `paper_accounts` and emits a tax-position
summary with an estimated setaside. Also reacts to `execute` messages
with a per-trade note.

Phase 9.5c: extended into a tax-strategy nudge. Alongside the setaside
note it now surfaces two opportunities, in plain language:
  - employer match left on the table (the highest-return move there is);
  - money moved into a child's tax-advantaged KINDRIP account.

Detailed bracket math (federal + state, short/long term, wash sales,
quarterly estimates) and the full strategy guide live in the web app
(`lib/tax.ts`, `lib/tax-strategy.ts`) and render on /dashboard/tax. This
agent provides the running nudges so the user is never surprised.

NOTE: estimates only — not tax advice. OBBB (P.L. 119-21) left
capital-gains rates unchanged; crypto is taxed as property.
"""

from __future__ import annotations

import asyncio

from app.config import get_settings

from .base import Agent, AgentMessage


# A conservative blended setaside rate. Most Trezo paper trades close
# same-day, so gains are short-term (ordinary income). 22% is a sensible
# "set aside roughly this much" default until the user's real bracket is
# applied on the /dashboard/tax page.
DEFAULT_SETASIDE_RATE = 0.22


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:
        return None


def _match_left_on_table(salary, contribution_pct, match_rate_pct,
                         match_cap_pct):
    """Employer match captured vs. left unclaimed (the "free money" math).

    Mirrors employerMatchValue() in the web app's lib/tax-strategy.ts.
    Returns (employer_match, left_on_table) in dollars.
    """
    s = max(0.0, float(salary or 0))
    contrib = max(0.0, min(float(contribution_pct or 0), 100.0))
    rate = max(0.0, float(match_rate_pct or 0)) / 100.0
    cap = max(0.0, min(float(match_cap_pct or 0), 100.0))
    matched_pct = min(contrib, cap)
    employer_match = s * (matched_pct / 100.0) * rate
    full_match = s * (cap / 100.0) * rate
    return employer_match, max(0.0, full_match - employer_match)


class TaxOptimizerAgent(Agent):
    name = "tax_optimizer"
    tick_interval_seconds = 1800  # every 30 minutes

    async def tick(self) -> list[AgentMessage]:
        client = _supabase()
        if not client:
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "Supabase not configured."})]

        def _accounts():
            return (
                client.table("paper_accounts")
                .select("user_id, ytd_realized_pnl_usd, today_realized_pnl_usd")
                .execute()
            )

        res = await asyncio.to_thread(_accounts)
        rows = res.data or []

        # Profiles — for the employer-match nudge. Optional: if the Phase
        # 9.5 columns are not migrated yet, this simply returns nothing.
        profiles: dict[str, dict] = {}

        def _profiles():
            return (
                client.table("profiles")
                .select("user_id, annual_income_usd, "
                        "retirement_contribution_pct, employer_match_pct, "
                        "employer_match_cap_pct")
                .execute()
            )

        try:
            pres = await asyncio.to_thread(_profiles)
            for p in (pres.data or []):
                profiles[p["user_id"]] = p
        except Exception:
            profiles = {}

        # KINDRIP children — for the tax-advantaged child-account note.
        contributed: dict[str, float] = {}

        def _children():
            return (
                client.table("kindrip_children")
                .select("user_id, total_contributed_usd")
                .execute()
            )

        try:
            cres = await asyncio.to_thread(_children)
            for c in (cres.data or []):
                uid = c["user_id"]
                contributed[uid] = contributed.get(uid, 0.0) + float(
                    c.get("total_contributed_usd") or 0)
        except Exception:
            contributed = {}

        out: list[AgentMessage] = []
        for r in rows:
            uid = r["user_id"]
            ytd = float(r.get("ytd_realized_pnl_usd") or 0)
            today = float(r.get("today_realized_pnl_usd") or 0)
            # Only positive gains create a tax liability.
            taxable = max(0.0, ytd)
            setaside = taxable * DEFAULT_SETASIDE_RATE
            out.append(AgentMessage(
                agent=self.name,
                kind="info",
                payload={
                    "user_id": uid,
                    "event": "tax_position",
                    "ytd_realized_pnl": round(ytd, 2),
                    "today_realized_pnl": round(today, 2),
                    "estimated_setaside": round(setaside, 2),
                    "setaside_rate": DEFAULT_SETASIDE_RATE,
                    "note": (
                        f"Set aside ~${setaside:,.0f} for taxes on ${taxable:,.0f} "
                        f"of YTD gains. See the Tax page for the full bracket estimate."
                    ),
                },
            ))

            # Employer-match nudge — the highest-return move available.
            prof = profiles.get(uid)
            if prof:
                match, left = _match_left_on_table(
                    prof.get("annual_income_usd"),
                    prof.get("retirement_contribution_pct"),
                    prof.get("employer_match_pct"),
                    prof.get("employer_match_cap_pct"),
                )
                if left >= 1.0:
                    out.append(AgentMessage(
                        agent=self.name,
                        kind="info",
                        payload={
                            "user_id": uid,
                            "event": "employer_match_gap",
                            "employer_match": round(match, 2),
                            "left_on_table": round(left, 2),
                            "note": (
                                f"You are leaving about ${left:,.0f} of employer "
                                f"match unclaimed this year — free money no trade "
                                f"can reliably beat. The Tax page shows the math."
                            ),
                        },
                    ))

            # Tax-advantaged child-account note.
            kid_total = contributed.get(uid, 0.0)
            if kid_total > 0:
                out.append(AgentMessage(
                    agent=self.name,
                    kind="info",
                    payload={
                        "user_id": uid,
                        "event": "child_accounts",
                        "total_contributed": round(kid_total, 2),
                        "note": (
                            f"${kid_total:,.0f} sits in tax-advantaged child "
                            f"accounts — its growth is sheltered, unlike taxable "
                            f"trading gains. KINDRIP keeps the running total."
                        ),
                    },
                ))

        if not out:
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "No paper accounts to summarize yet."})]
        return out

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        if message.kind != "execute":
            return []
        ticker = message.payload.get("ticker", "?")
        return [
            AgentMessage(
                agent=self.name,
                kind="info",
                payload={
                    "ticker": ticker,
                    "note": "Trade logged for the tax ledger. Realized gain (if any) "
                            "is computed when the position closes.",
                },
            )
        ]
