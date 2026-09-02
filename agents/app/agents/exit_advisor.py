"""Exit Advisor Agent — Phase 13d.

The 19th agent. Ticks every 5 minutes, 24/7, on every book -- there is
no session gate in tick() (the old "during the US equity session" here
was stale by 2026-09-02; crypto rows are watched overnight and at
weekends like any other). For each open paper_position, fetches the
latest price, updates the
running peak unrealized P&L on the row, and watches for the
held-too-long pattern in real time:

  - If unrealized P&L was previously positive AND has given back
    >=30% of the peak gain, raise a 'peak_giveback' alert.
  - If a position has been open >=5 days AND is still positive but
    flat-lining, raise a 'time_in_trade' alert (capital is parked).
  - If the position is approaching its stop within 1%, raise
    'stop_approaching'.

By default the advisor only alerts. It writes rows into
`exit_advisor_alerts` so the dashboard shows them inline and so the
user has an audit trail of the bot's reasoning. BUT when the book's
Bot Tuning `auto_exit_advisor` is ON (Task #92), a peak_giveback alert
ACTS: urgent -> close the position (broker-aware; Alpaca rows are
liquidated at the broker first), warn -> trim half on internal paper
rows. That close runs under bind_for_user(row.user_id) with the route
verified (TE-18) so it lands on the row's own broker account, never
the primary; a row whose book cannot be resolved is left as an alert.

Alerts are deduplicated: we don't re-raise the same alert_kind for
the same position while an unacknowledged one exists. Once Mike
dismisses an alert (acknowledged_at set), the agent is free to raise
a fresh one if the condition continues to deteriorate.

Why this exists: Mike's stated weakness is holding too long. The
post-mortem analyzer surfaces the pattern AFTER the fact; this
catches it WHILE the trade is still open, when he can still act.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings
from app.data.candles import fetch_candles_for

from .base import Agent, AgentMessage


# Pattern thresholds — kept tunable inline so we can move them into
# bot_settings later if Mike wants per-user control.
PEAK_GIVEBACK_PCT = 0.30      # default 30% giveback (used as the fallback)
TIME_IN_TRADE_DAYS = 5        # alert when >=5 days in a flat winner
STOP_APPROACH_PCT = 0.01      # alert when within 1% of stop


# ---------------------------------------------------------------------------
# Mike 2026-06-03 ask: scale the giveback tolerance to the absolute peak
# gain. Small wins (up <=15%) need TIGHTER protection because one bad
# move flips them losing. Big wins (up >30%) can absorb more drawback
# without panicking the user out of a great trade.
#
# Returns (warn_threshold, urgent_threshold) in fraction units.
# ---------------------------------------------------------------------------
def _giveback_thresholds_for_peak(peak_pct: float) -> tuple[float, float]:
    """Tier giveback alerts by absolute peak gain.

      peak gain  | warn  | urgent
      ---------- | ----- | ------
      <=5%       | 0.15  | 0.30
      <=15%      | 0.20  | 0.40     <- Mike's 10% case lives here
      <=30%      | 0.30  | 0.50     <- old default range
      >30%       | 0.40  | 0.60     <- big winners get room
    """
    p = abs(float(peak_pct or 0.0))
    if p <= 0.05:
        return (0.15, 0.30)
    if p <= 0.15:
        return (0.20, 0.40)
    if p <= 0.30:
        return (0.30, 0.50)
    return (0.40, 0.60)


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unrealized_pnl(side: str, qty: float, entry: float, price: float) -> float:
    if side == "short":
        return qty * (entry - price)
    return qty * (price - entry)


def _days_open(opened_at: Optional[str]) -> float:
    if not opened_at:
        return 0.0
    try:
        t = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - t).total_seconds() / 86400.0)
    except Exception:  # noqa: BLE001
        return 0.0


class ExitAdvisorAgent(Agent):
    name = "exit_advisor"
    tick_interval_seconds = 300  # every 5 minutes

    async def tick(self) -> list[AgentMessage]:
        client = _supabase()
        if not client:
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"note": "Supabase not configured."},
            )]

        # Fetch all open positions. Cheap-ish - we expect <100 rows
        # per user; if this grows, paginate by user_id.
        def _sync_get_open():
            return (
                client.table("paper_positions")
                .select("id, user_id, ticker, side, asset_type, "
                        "quantity, entry_price, stop_price, target_price, "
                        "peak_unrealized_pnl_usd, peak_price, peak_at, "
                        "entry_at, strategy")
                .eq("status", "open")
                .execute()
            )

        res = await asyncio.to_thread(_sync_get_open)
        positions = res.data or []
        if not positions:
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"note": "No open positions to watch.", "checked": 0},
            )]

        out: list[AgentMessage] = []
        alerts_raised = 0

        for pos in positions:
            try:
                ticker = (pos.get("ticker") or "").upper()
                side = (pos.get("side") or "long").lower()
                qty = float(pos.get("quantity") or 0)
                entry = float(pos.get("entry_price") or 0)
                if not ticker or qty <= 0 or entry <= 0:
                    continue

                # HODL exemption (2026-06-13): a long-horizon HODL is
                # "hold and do not sell" by design. The peak-giveback
                # rule (and its auto-close when auto_exit_advisor is ON)
                # must NEVER fire on a HODL -- only its catastrophe stop
                # or a manual close exits one. Skip entirely.
                if "hodl" in (pos.get("strategy") or "").lower():
                    continue

                # Latest price from the standard candle path.
                candles = await fetch_candles_for(
                    ticker, pos.get("asset_type") or "stock",
                )
                if not candles:
                    continue
                price = float(candles[-1].close)
                if price <= 0:
                    continue

                pnl = _unrealized_pnl(side, qty, entry, price)
                peak = float(pos.get("peak_unrealized_pnl_usd") or 0)
                peak_price = float(pos.get("peak_price") or 0)

                # Update high-water mark when we have a new peak. We
                # only track positive peaks - the held-too-long pattern
                # is about giving back winners.
                if pnl > peak:
                    def _sync_update_peak(
                        pid=pos["id"], new_peak=pnl, new_price=price,
                    ):
                        return (
                            client.table("paper_positions")
                            .update({
                                "peak_unrealized_pnl_usd": round(new_peak, 4),
                                "peak_price": round(new_price, 4),
                                "peak_at": _now_iso(),
                            })
                            .eq("id", pid)
                            .execute()
                        )
                    await asyncio.to_thread(_sync_update_peak)
                    peak = pnl
                    peak_price = price

                alerts_for_position = await self._diagnose_and_alert(
                    client, pos, peak, peak_price, pnl, price,
                )
                alerts_raised += alerts_for_position
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(
                    agent=self.name, kind="error",
                    payload={"ticker": pos.get("ticker"),
                             "error": str(e)[:200]},
                ))

        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={
                "event": "exit_advisor_tick",
                "checked": len(positions),
                "alerts_raised": alerts_raised,
            },
        ))
        return out

    async def _diagnose_and_alert(
        self, client, pos: dict, peak: float, peak_price: float,
        pnl: float, price: float,
    ) -> int:
        """Run the rule set against a single open position. Returns
        the number of NEW alerts raised."""
        raised = 0
        user_id = pos.get("user_id")
        pid = pos["id"]
        ticker = (pos.get("ticker") or "").upper()
        side = (pos.get("side") or "long").lower()
        stop = float(pos.get("stop_price") or 0)
        opened_at = pos.get("entry_at")

        # Derive entry cost (quantity * entry_price) so we can
        # scale the giveback tiers per Mike's 2026-06-03 ask.
        try:
            entry_value = abs(float(pos.get("entry_price") or 0)
                              * float(pos.get("quantity") or 0))
        except Exception:  # noqa: BLE001
            entry_value = 0.0

        # --- Rule 1: peak giveback (the main held-too-long signal).
        # Active only when we ever had a positive peak AND current pnl
        # is positive too (no point alerting on a stop-bound trade).
        if peak > 0 and pnl > 0:
            from app.runtime.capabilities import peak_giveback_pct
            giveback = peak_giveback_pct(peak, pnl)
            # Use entry cost to derive peak gain percentage so the
            # tier picker can scale appropriately.
            peak_pct = (peak / entry_value) if entry_value > 0 else 0.0
            warn_th, urgent_th = _giveback_thresholds_for_peak(peak_pct)
            if giveback >= warn_th:
                if not await self._has_open_alert(client, pid, "peak_giveback"):
                    severity = "urgent" if giveback >= urgent_th else "warn"
                    tier_label = (
                        "small-win (tight)" if peak_pct <= 0.15
                        else "medium-win" if peak_pct <= 0.30
                        else "big-win (room)"
                    )
                    msg = (
                        f"{ticker} hit peak unrealized P&L of "
                        f"${peak:.0f} ({peak_pct*100:.1f}% of cost) and "
                        f"has given back {giveback*100:.0f}% of that "
                        f"gain. Tier: {tier_label}. The setup may be "
                        f"exhausted - consider trimming or trailing the "
                        f"stop to lock in what's left."
                    )
                    await self._raise_alert(
                        client, user_id=user_id, position_id=pid,
                        ticker=ticker, kind="peak_giveback",
                        severity=severity, message=msg,
                        current_price=price, peak_price=peak_price,
                        giveback_pct=round(giveback, 4),
                        unrealized_pnl_usd=round(pnl, 2),
                    )
                    raised += 1

                    # Task #92 (Mike 2026-06-10): bot rule should take effect.
                    # When auto_exit_advisor is ON in Bot Tuning, ACT on the
                    # rule instead of just alerting. Urgent -> close fully,
                    # warn -> trim 50%. Best-effort: any failure leaves
                    # the alert in place so Mike can still act manually.
                    try:
                        from app.runtime.settings import get_bot_settings as _gbs_ea
                        _bs = _gbs_ea(user_id)
                        if getattr(_bs, "auto_exit_advisor", False):
                            from app.paper.engine import (
                                close_position_broker_aware,
                                trim_position,
                            )
                            # TE-18: close_position_broker_aware ->
                            # liquidate_position submits to the CURRENTLY
                            # BOUND account, and nothing here bound one --
                            # so an urgent auto-close on a 25k/75k row hit
                            # the primary. Bind the row's book and verify
                            # the route first; an unresolvable book is
                            # skipped with a logged reason (the alert
                            # stays so Mike can act), never defaulted.
                            from app.brokers.accounts import bind_for_user as _bind_acct
                            from app.brokers.route_guard import check_route as _check_route
                            from app.brokers.route_guard import record_mismatch as _rec_mm
                            with _bind_acct(user_id):
                                _ok, _note = _check_route(user_id)
                                if not _ok:
                                    _rec_mm(ticker, user_id, _note,
                                            "exit_advisor.auto_close")
                                elif severity == "urgent":
                                    # Gap 2 fix (2026-06-11): broker-aware close.
                                    # For broker=alpaca rows, liquidate at Alpaca
                                    # FIRST (cancels brackets + sells), then update
                                    # Trezo. For internal paper, plain close.
                                    await close_position_broker_aware(
                                        user_id, pid, price,
                                        reason=f"auto_exit_advisor: peak_giveback {int(giveback*100)}% "
                                               f"(tier {tier_label}, urgent)",
                                    )
                                else:
                                    # warn -> trim half. Sells half the shares,
                                    # leaves the runner so winners can keep running.
                                    # Gap 2 follow-up (Task #7b, deferred): trim
                                    # on broker=alpaca rows is complex (cancel
                                    # bracket, sell half, re-submit bracket sized
                                    # to remainder). Until shipped, broker=alpaca
                                    # trim alerts stay alert-only so Mike can act
                                    # manually. Internal paper trims work as
                                    # before.
                                    _row_broker = ""
                                    try:
                                        _row_res = await asyncio.to_thread(
                                            lambda: client.table("paper_positions")
                                            .select("broker")
                                            .eq("id", pid)
                                            .maybe_single()
                                            .execute()
                                        )
                                        _row_broker = ((_row_res.data or {}).get("broker") or "").lower().strip()
                                    except Exception:
                                        _row_broker = ""
                                    if _row_broker == "alpaca":
                                        # Don't trim Alpaca rows yet - alert stays
                                        # in place, no silent-half-close bug.
                                        pass
                                    else:
                                        await trim_position(
                                            user_id, pid, fraction=0.5, price=price,
                                            reason=f"auto_exit_advisor: peak_giveback {int(giveback*100)}% "
                                                   f"(tier {tier_label}, half-trim)",
                                        )
                    except Exception:  # noqa: BLE001
                        pass  # leave the alert so Mike can act manually

        # --- Rule 2: stop approaching. Quiet warning, not urgent.
        if stop > 0:
            if side == "long":
                dist = (price - stop) / price
            else:
                dist = (stop - price) / price
            if 0 < dist <= STOP_APPROACH_PCT:
                if not await self._has_open_alert(client, pid, "stop_approaching"):
                    msg = (
                        f"{ticker} is within {dist*100:.1f}% of your "
                        f"stop at ${stop:.2f}. The position may close "
                        "automatically soon; this is just a heads-up."
                    )
                    await self._raise_alert(
                        client, user_id=user_id, position_id=pid,
                        ticker=ticker, kind="stop_approaching",
                        severity="info", message=msg,
                        current_price=price, peak_price=peak_price or None,
                        giveback_pct=None,
                        unrealized_pnl_usd=round(pnl, 2),
                    )
                    raised += 1

        # --- Rule 3: time in trade (capital is parked).
        days = _days_open(opened_at)
        if days >= TIME_IN_TRADE_DAYS and 0 < pnl <= peak * 0.30:
            if not await self._has_open_alert(client, pid, "time_in_trade"):
                msg = (
                    f"{ticker} has been open {days:.0f} days and is "
                    f"sitting at {pnl/max(peak, 1)*100:.0f}% of its "
                    "peak. The capital may earn more in a fresher "
                    "setup; consider taking the modest win and "
                    "rotating."
                )
                await self._raise_alert(
                    client, user_id=user_id, position_id=pid,
                    ticker=ticker, kind="time_in_trade",
                    severity="info", message=msg,
                    current_price=price, peak_price=peak_price or None,
                    giveback_pct=None,
                    unrealized_pnl_usd=round(pnl, 2),
                )
                raised += 1

        # --- Rule 4: decayed thesis (Mike 2026-06-01). The richest
        # signal: TCS dropped + peak gave back + price went flat. The
        # original setup is exhausted; capital can earn more elsewhere.
        try:
            from app.learning.position_health import (
                compute_position_health, render_alert_message,
            )
            health = await compute_position_health(pos)
            if health and health.recommendation in ("rotate", "trim_partial"):
                if not await self._has_open_alert(client, pid, "decayed_thesis"):
                    severity = "warn" if health.recommendation == "rotate" else "info"
                    await self._raise_alert(
                        client, user_id=user_id, position_id=pid,
                        ticker=ticker, kind="decayed_thesis",
                        severity=severity,
                        message=render_alert_message(health),
                        current_price=price,
                        peak_price=peak_price or None,
                        giveback_pct=health.peak_giveback_pct,
                        unrealized_pnl_usd=round(pnl, 2),
                    )
                    raised += 1
        except Exception:  # noqa: BLE001
            pass

        return raised

    async def _has_open_alert(self, client, position_id: str,
                              kind: str) -> bool:
        """True when we already have an un-acknowledged alert of this
        kind on this position. Stops the advisor from spamming."""
        def _sync():
            return (
                client.table("exit_advisor_alerts")
                .select("id")
                .eq("position_id", position_id)
                .eq("alert_kind", kind)
                .is_("acknowledged_at", "null")
                .limit(1)
                .execute()
            )
        try:
            res = await asyncio.to_thread(_sync)
            return bool(res.data)
        except Exception:  # noqa: BLE001
            # Fail OPEN - better to skip a duplicate alert than crash.
            return True

    async def _raise_alert(
        self, client, *, user_id: str, position_id: str, ticker: str,
        kind: str, severity: str, message: str,
        current_price: float, peak_price: Optional[float],
        giveback_pct: Optional[float],
        unrealized_pnl_usd: float,
    ) -> None:
        row = {
            "user_id": user_id,
            "position_id": position_id,
            "ticker": ticker,
            "alert_kind": kind,
            "severity": severity,
            "message": message,
            "current_price": round(current_price, 4),
            "peak_price": round(peak_price, 4) if peak_price else None,
            "giveback_pct": giveback_pct,
            "unrealized_pnl_usd": unrealized_pnl_usd,
            "raised_at": _now_iso(),
        }

        def _sync():
            return client.table("exit_advisor_alerts").insert(row).execute()
        try:
            await asyncio.to_thread(_sync)
        except Exception:  # noqa: BLE001
            pass
