"""Exit Advisor - Options edition. Phase B of the options agent upgrade.

The 20th agent (when registered). Ticks every 5 minutes during the
US equity session. Encodes Mike's actual options trading psychology
so the bot trades "more human" - meaning the way he trades, not
abstract optimal math.

Source of rules: project memory project_options_trading_rules.md
and TREZO_PROJECT/OPTIONS_AGENT_UPGRADE.md.

Rules:

  1. Contract-count drives the profit target:
       * 1-10 contracts (low):  target 30-50% gain.
       * >10 contracts (high):  target ~15% (emotion takes over at
         scale, per Mike's own model).

  2. Capital recovery first on low-contract positions: at 50%+ gain,
     suggest trimming to recover cost basis (house-money pattern).

  3. Drawback ladder from peak unrealized:
       * >=39% drawback:  defensive_trim (warn) - early-warning.
       * >=30% drawback with position still in profit:
         save_profit_before_negative (warn).
       * >=25% drawback:  drawdown_tolerance_hit (URGENT) - Mike's
         stated ceiling.

  4. Catalyst-aware urgency (Rule 8 in project memory): when cycle
     awareness flags earnings_day OR adaptive scope is risk_off,
     bump the alert severity up by one notch. A held position into
     a catalyst day is higher-risk than the same position on a
     quiet day.

NEVER closes positions. Writes plain-English alerts to
exit_advisor_alerts so the UI surfaces them and Mike acts.

Mark-to-market strategy (Phase B v1):
  * For modeled positions (paper-only users, no broker):
      The current value is approximated as the credit received minus
      a simple intrinsic-value penalty if the underlying has moved
      against the position. This is a coarse proxy; full Greek-aware
      MTM lands in Phase C.
  * For live Alpaca positions:
      The Alpaca options snapshot would be queried via the existing
      get_alpaca_options_positions helper. v1 falls back to modeled
      MTM when the broker snapshot isn't available within the tick.

Activation: not yet registered in bootstrap. To turn on, add to
the bootstrap.AGENT_CLASSES list (or equivalent). Until then this
file imports cleanly but the agent does not tick.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings
from app.data.candles import fetch_candles_for

from .base import Agent, AgentMessage


# Mike's psychology, encoded as constants.
LOW_CONTRACT_THRESHOLD = 10                  # <=10 = "low" tier
LOW_TIER_PROFIT_TARGET = 0.30                # 30% gain triggers profit-tier alert on low contracts
LOW_TIER_CAPITAL_RECOVERY = 0.50             # at 50% gain, suggest cost-basis recovery
HIGH_TIER_PROFIT_TARGET = 0.15               # 15% emotion cap on high contracts

DRAWBACK_DEFENSIVE_TRIM = 0.39               # first warning at 39% drawback from peak
DRAWBACK_SAVE_PROFIT = 0.30                  # second warning at 30%
DRAWBACK_TOLERANCE_CEILING = 0.25            # urgent at 25% (Mike's stated ceiling)
DRAWBACK_TOLERANCE_HOPEFUL = 0.20            # urgent at 20% for hopeful bucket (Mike's rule 5)


# Use the shared bucket classifier so Risk Manager + Options Scanner
# + this advisor can never disagree.
from app.learning.bucket_helpers import (
    strategy_bucket as _strategy_bucket,
    hopeful_allocation_pct,
    hopeful_cap_for_user,
)

# How often this advisor ticks. Same cadence as stock exit advisor.
TICK_SECONDS = 300


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


class ExitAdvisorOptionsAgent(Agent):
    """Real-time options-position health watcher.

    Holds an in-memory `_peaks` dict mapping position_id -> peak
    unrealized P&L USD seen so far. Persisted peak tracking
    (similar to paper_positions.peak_unrealized_pnl_usd added in
    migration 0035) is on the queue as a follow-up - the in-memory
    version is fine for Phase B because the alerts table itself is
    persistent and the worst case of an agent restart is one missed
    alert cycle.
    """

    name = "exit_advisor_options"
    tick_interval_seconds = TICK_SECONDS

    def __init__(self) -> None:
        # position_id -> peak unrealized P&L USD seen since open
        self._peaks: dict[str, float] = {}

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        # Event-driven hooks could be added here later (e.g. broker
        # fill events). Today the advisor is tick-only.
        return []

    async def tick(self) -> list[AgentMessage]:
        client = _supabase()
        if not client:
            return []

        # Pull every open option position. RLS isn't relevant here -
        # the agent uses the service-role client.
        def _sync():
            return (
                client.table("options_positions")
                .select("id, user_id, underlying, strategy, option_type, "
                        "strike, expiration, contracts, net_premium_usd, "
                        "opened_at, status")
                .eq("status", "open")
                .execute()
            )
        try:
            res = await asyncio.to_thread(_sync)
        except Exception as e:  # noqa: BLE001
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"note": f"options exit advisor query failed: {str(e)[:120]}"},
            )]

        rows = res.data or []
        out: list[AgentMessage] = []

        for r in rows:
            try:
                pid = str(r["id"])
                user_id = str(r["user_id"])
                ticker = str(r.get("underlying") or "?")
                contracts = int(r.get("contracts") or 1)
                premium = float(r.get("net_premium_usd") or 0.0)
                strike = float(r.get("strike") or 0.0)
                opt_type = str(r.get("option_type") or "put")
                strategy = str(r.get("strategy") or "wheel_csp")
                if premium == 0:
                    continue

                # Cost basis = abs(net premium). For a sold CSP this is
                # the credit, which is also the maximum profit when the
                # put expires worthless. For a bought long_call this is
                # the debit paid.
                cost_basis = abs(premium)

                # Mark to market. Modeled v1: use spot vs strike as a
                # proxy for the option's intrinsic-value component plus
                # the original credit. This is coarse and will be
                # replaced with Greek-aware MTM in Phase C.
                candles = await fetch_candles_for(ticker, "stock")
                if not candles:
                    continue
                spot = float(candles[-1].close)
                current_value = self._mark_to_market(
                    strategy=strategy, opt_type=opt_type, premium=premium,
                    strike=strike, spot=spot, contracts=contracts,
                )
                # Unrealized P&L = current value relative to credit/debit
                if premium > 0:  # credit position (sold) - we want premium to decay
                    # gain when current_value < premium (option worth less to buy back)
                    unrealized = (premium - current_value)
                else:           # debit position (bought) - we want intrinsic to rise
                    unrealized = (current_value - cost_basis)

                # Track running peak per position.
                prev_peak = self._peaks.get(pid, 0.0)
                peak = max(prev_peak, unrealized)
                self._peaks[pid] = peak

                gain_pct = unrealized / cost_basis if cost_basis > 0 else 0.0
                peak_pct = peak / cost_basis if cost_basis > 0 else 0.0
                drawback_pct = ((peak - unrealized) / peak) if peak > 0 else 0.0

                # Decide which alert (if any) to raise. Run rules in
                # priority order; first match wins per position per tick.
                bucket = _strategy_bucket(strategy)
                alert = self._evaluate_rules(
                    contracts=contracts, gain_pct=gain_pct,
                    peak_pct=peak_pct, drawback_pct=drawback_pct,
                    bucket=bucket,
                )
                if alert is None:
                    continue

                kind, severity, message = alert
                # Catalyst-aware bump: severity goes up one notch when
                # ctx is hot. Read cycle position best-effort.
                severity = await self._catalyst_bump(ticker, severity)

                await self._raise_alert(
                    client, user_id=user_id, position_id=pid,
                    ticker=ticker, kind=kind, severity=severity,
                    message=message, current_value=current_value,
                    peak_value=peak + cost_basis if peak > 0 else None,
                    drawback_pct=round(drawback_pct, 4),
                    unrealized_pnl_usd=round(unrealized, 2),
                )
                out.append(AgentMessage(
                    agent=self.name, kind="info",
                    payload={
                        "event": "options_exit_alert",
                        "position_id": pid, "ticker": ticker,
                        "kind": kind, "severity": severity,
                        "contracts": contracts, "gain_pct": round(gain_pct, 4),
                        "drawback_pct": round(drawback_pct, 4),
                    },
                ))
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(
                    agent=self.name, kind="info",
                    payload={"note": f"options exit advisor row error: {str(e)[:120]}"},
                ))

        # Path beta: per-user hopeful-bucket near-cap warning. Once per
        # tick per user we touched, check if hopeful allocation is at
        # >=75% of the user's cap, and if so raise an info alert. The
        # dedupe in _raise_alert keeps this from spamming.
        seen_users = {str(r["user_id"]) for r in rows if r.get("user_id")}
        for uid in seen_users:
            try:
                cap = hopeful_cap_for_user(uid)
                if cap <= 0:
                    continue
                pct = await hopeful_allocation_pct(client, uid)
                if pct >= 0.75 * cap and pct < cap:
                    await self._raise_alert(
                        client, user_id=uid,
                        position_id="hopeful_bucket_alert",
                        ticker="HOPEFUL",
                        kind="hopeful_near_cap",
                        severity="info",
                        message=(
                            f"Hopeful-bucket allocation at "
                            f"{pct*100:.1f}% of options capital - approaching "
                            f"your {cap*100:.0f}% cap. New hopeful trades will "
                            f"be blocked when the cap is hit."
                        ),
                        current_value=None,
                        peak_value=None,
                        drawback_pct=None,
                        unrealized_pnl_usd=None,
                    )
            except Exception:  # noqa: BLE001
                pass

        return out

    # ------------------------------------------------------------------
    # Mark-to-market (v1: coarse proxy; Phase C upgrades to Greeks)
    # ------------------------------------------------------------------

    @staticmethod
    def _mark_to_market(*, strategy: str, opt_type: str, premium: float,
                        strike: float, spot: float, contracts: int) -> float:
        """Approximate current value (per share, scaled to contracts)
        for an open option position.

        For sold puts (CSP):
          ITM proxy = max(0, strike - spot) * 100 * contracts
          That is what we'd have to pay to close. Less is better
          for the seller.
        For sold calls (CC):
          ITM proxy = max(0, spot - strike) * 100 * contracts
        For bought calls (long_call) or bought puts:
          ITM proxy is the intrinsic; that's our worth.

        This ignores time-value / theta entirely. Phase C reads real
        Greeks from the broker chain instead.
        """
        c = max(1, int(contracts))
        if strategy in ("wheel_csp", "cash_secured_put") or (
            strategy.startswith("bull_put") and premium > 0
        ):
            return max(0.0, strike - spot) * 100.0 * c
        if strategy == "wheel_cc":
            return max(0.0, spot - strike) * 100.0 * c
        if strategy == "long_call":
            return max(0.0, spot - strike) * 100.0 * c
        # Default coarse proxy: treat as credit position with intrinsic.
        return max(0.0, strike - spot) * 100.0 * c

    # ------------------------------------------------------------------
    # Rule evaluation - Mike's psychology, distilled
    # ------------------------------------------------------------------

    @staticmethod
    def _evaluate_rules(*, contracts: int, gain_pct: float,
                        peak_pct: float, drawback_pct: float,
                        bucket: str = "wheel",
                        ) -> Optional[tuple[str, str, str]]:
        """Return (alert_kind, severity, message) or None when no alert.

        Priority order:
          1. Drawback ceiling hit (URGENT) - Mike's stated wall. Ceiling
             is 25% for wheel/income, 20% for hopeful (Mike's rule 5).
          2. Save-profit-before-negative (warn).
          3. Defensive trim (warn).
          4. Capital recovery on low-contract winner (info).
          5. Profit target hit per contract-count tier (info).
        """
        ceiling = (DRAWBACK_TOLERANCE_HOPEFUL if bucket == "hopeful"
                   else DRAWBACK_TOLERANCE_CEILING)
        # ---- Drawback ladder (most urgent first) ----------------------
        if peak_pct > 0 and drawback_pct >= ceiling:
            return (
                "drawdown_tolerance_hit", "urgent",
                f"Drawdown from peak hit {drawback_pct*100:.0f}% - your "
                f"{bucket}-bucket ceiling is {ceiling*100:.0f}%. Consider "
                f"closing to protect remaining gain.",
            )
        if (peak_pct > 0 and gain_pct > 0
                and drawback_pct >= DRAWBACK_SAVE_PROFIT):
            return (
                "save_profit_before_negative", "warn",
                f"Peak gave back {drawback_pct*100:.0f}% but you're still in "
                f"profit ({gain_pct*100:.0f}%). Consider closing before this "
                f"becomes a drawdown.",
            )
        if peak_pct > 0 and drawback_pct >= DRAWBACK_DEFENSIVE_TRIM:
            return (
                "defensive_trim", "warn",
                f"Drawback from peak is {drawback_pct*100:.0f}%. Defensive trim "
                f"recommended before the 30% step.",
            )

        # ---- Profit / capital-recovery (low vs high contract count) ----
        if contracts <= LOW_CONTRACT_THRESHOLD:
            if gain_pct >= LOW_TIER_CAPITAL_RECOVERY:
                return (
                    "trim_for_capital_recovery", "info",
                    f"Up {gain_pct*100:.0f}% on {contracts} contract(s). "
                    f"Consider trimming to recover cost basis - the rest "
                    f"rides as house money.",
                )
            if gain_pct >= LOW_TIER_PROFIT_TARGET:
                return (
                    "profit_target_low_tier", "info",
                    f"Up {gain_pct*100:.0f}% on {contracts} contract(s). "
                    f"In your 30-50% target window for small positions.",
                )
        else:  # high tier
            if gain_pct >= HIGH_TIER_PROFIT_TARGET:
                return (
                    "emotion_cap_take_gain", "info",
                    f"Up {gain_pct*100:.0f}% on {contracts} contracts. Your "
                    f"high-contract emotion cap is 15% - consider taking it.",
                )

        return None

    # ------------------------------------------------------------------
    # Catalyst-aware severity bump (Rule 8)
    # ------------------------------------------------------------------

    async def _catalyst_bump(self, ticker: str, severity: str) -> str:
        """Bump severity up one notch when the ticker is in a hot
        cycle window (earnings_day) or when adaptive scope is risk_off.
        Best-effort: any failure returns the original severity."""
        try:
            from app.data.cycles import get_cycle_position
            cyc = await get_cycle_position(ticker)
            if cyc and getattr(cyc, "iv_environment", "") == "earnings_day":
                return self._bump(severity)
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.runtime.scope import get_scope
            scope = get_scope()
            if getattr(scope, "regime", "neutral") == "risk_off":
                return self._bump(severity)
        except Exception:  # noqa: BLE001
            pass
        return severity

    @staticmethod
    def _bump(sev: str) -> str:
        return {"info": "warn", "warn": "urgent", "urgent": "urgent"}.get(sev, sev)

    # ------------------------------------------------------------------
    # Alert writer
    # ------------------------------------------------------------------

    async def _raise_alert(self, client, *, user_id: str, position_id: str,
                           ticker: str, kind: str, severity: str,
                           message: str, current_value: Optional[float],
                           peak_value: Optional[float],
                           drawback_pct: Optional[float],
                           unrealized_pnl_usd: Optional[float]) -> None:
        """Write a row to exit_advisor_alerts. Deduplicated: if there's
        already an unacknowledged alert of the same kind for this
        position_id, skip. The advisor isn't allowed to nag - one alert
        per kind per position until Mike acknowledges."""
        def _sync_dedupe():
            return (
                client.table("exit_advisor_alerts")
                .select("id")
                .eq("position_id", position_id)
                .eq("alert_kind", kind)
                .is_("acknowledged_at", None)
                .limit(1)
                .execute()
            )
        try:
            existing = await asyncio.to_thread(_sync_dedupe)
            if (existing.data or []):
                return
        except Exception:  # noqa: BLE001
            # If dedupe lookup fails, we'd rather over-raise than miss.
            pass

        row = {
            "user_id": user_id,
            "position_id": position_id,
            "ticker": ticker,
            "alert_kind": kind,
            "severity": severity,
            "message": message,
            "current_price": current_value,
            "peak_price": peak_value,
            "giveback_pct": drawback_pct,
            "unrealized_pnl_usd": unrealized_pnl_usd,
            "raised_at": datetime.now(timezone.utc).isoformat(),
        }

        def _sync_insert():
            return client.table("exit_advisor_alerts").insert(row).execute()
        try:
            await asyncio.to_thread(_sync_insert)
        except Exception:  # noqa: BLE001
            pass  # never block on alert-write failure
