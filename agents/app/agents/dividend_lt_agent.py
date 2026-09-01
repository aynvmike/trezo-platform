"""Dividends (Long-Term) lane agent — the ladder that ticks.

Closes the gap left on 2026-08-22: the lane's math, screen and rules all
existed, but nothing ran them. The Wheel used the screen; the LADDER —
the 70% of the lane — did not exist as a running thing.

WHAT IT DOES EACH TICK (30 min)
  1. Reads each book's lane inputs (§1) from bot_settings, falling back
     to spec defaults.
  2. Sizes the lane (§2) — ladder/wheel/buffer split, name count, CSP
     blocks, book unlocks U1-U4.
  3. Screens market-wide candidates (§4) through dividend_screen, applies
     the sector cap, and ranks what is left.
  4. Emits ladder BUY signals for names the book does not yet hold, up to
     `ladder_names`, sized under the per-name concentration cap.
  5. Logs graduation transitions (FRACTIONAL -> LOT_READY) as lane events,
     because compounding unlocking option income name-by-name is the
     mechanism the spec cares most about observing.

WHAT IT DELIBERATELY DOES NOT DO
  - It never places an order. Signals go on the bus; Risk Manager judges
    them and Trade Execution routes them, exactly like every other lane.
    A lane that executed its own orders would bypass every gate the
    platform has.
  - It never writes a covered call. That is the Wheel's job, and lane
    rule #4 (GROWTH names never wear calls) is enforced in
    dividend_lt.can_write_covered_call where the Wheel reads it.
  - It does not chase `target_return`. The slider explains; it never
    actuates (§5). Nothing in this agent reads it as an instruction.

MODE: ladder entries only fire in ACCUMULATE and PARTIAL. In INCOME mode
the lane is drawing down, not building, so new ladder buys would work
against the owner's stated intent.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from app.config import get_settings
from app.strategies.dividend_lt import (
    FRACTIONAL, LOT_READY, LaneGuardrailError, LaneInputs, name_state,
    per_name_cap_pct, size_lane,
)
from app.strategies.dividend_screen import screen_many, sector_capped

from .base import Agent, AgentMessage

# Spec §7: 90 days proves plumbing and forecast accuracy. Until the lane
# has a measured record, entries stay small and the tick is unhurried.
TICK_SECONDS = 1800
MAX_NEW_ENTRIES_PER_TICK = 2      # a ladder is built slowly, on purpose


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def _lane_inputs_for(row: dict, equity: float) -> Optional[LaneInputs]:
    """Build §1 inputs from a book's bot_settings row.

    `allocation_overrides` already carries the owner's pocket split, so
    the lane reads the SAME numbers the rest of the platform sizes
    against rather than inventing a parallel truth. Falls back to spec
    defaults (70/25/5) when a book has no overrides.
    """
    pockets = row.get("allocation_overrides") or {}
    income = float(pockets.get("income", 0) or 0)
    stocks = float(pockets.get("stocks", 0) or 0)
    options = float(pockets.get("options", 0) or 0)

    # The lane's capital is the income pocket when one is funded; a book
    # with no income pocket is not running this lane at all.
    capital = income if income > 0 else 0.0
    if capital < 500:
        return None

    total = income + stocks + options
    if total > 0 and options > 0:
        w_wheel = min(0.40, max(0.0, options / total))
    else:
        w_wheel = 0.25
    w_buffer = 0.05
    w_ladder = max(0.50, min(0.90, 1.0 - w_wheel - w_buffer))

    try:
        _ppct = 0.0
        try:
            _ppct = float(row.get("dividend_lane_partial_pct") or 0.0)
        except (TypeError, ValueError):
            _ppct = 0.0
        return LaneInputs(
            capital=capital,
            w_ladder=w_ladder, w_wheel=w_wheel, w_buffer=w_buffer,
            wheel_delta=0.25,
            mode=str(row.get("dividend_lane_mode") or "ACCUMULATE").upper(),
            partial_pct=_ppct,
        )
    except LaneGuardrailError:
        # A book configured outside the guardrails does not get a
        # silently-corrected lane — it gets no lane, and says so.
        return None


class DividendLTAgent(Agent):
    name = "dividend_lt"
    tick_interval_seconds = TICK_SECONDS
    # 2026-08-28: today's bus-visible cancellations showed this agent
    # blowing the default scheduler ceiling on a live market day
    # (cancelled 1x at 900s) — every cancelled tick discarded its signals. Honest
    # ceiling; max_instances=1 + coalesce prevent overlap.
    tick_timeout_seconds = 1800

    # ticker -> last observed state, per book. Used to notice graduations.
    _last_states: dict = {}

    async def tick(self) -> list[AgentMessage]:
        out: list[AgentMessage] = []
        client = _supabase()
        if client is None:
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "Supabase not configured"})]

        def _books():
            # AUDIT 2026-08-27: dividend_lane_mode was read off this row
            # but never SELECTed (and, until migration 0058, never
            # existed) — so the lane was permanently ACCUMULATE and the
            # §6 INCOME branch could not execute. The wildcard-free
            # select now names both lane columns. Until 0058 is applied
            # PostgREST rejects unknown columns, so fall back to the old
            # shape rather than killing the whole lane.
            try:
                return (client.table("bot_settings")
                        .select("user_id, allocation_overrides, "
                                "auto_trade_enabled, dividend_lane_mode, "
                                "dividend_lane_partial_pct")
                        .execute())
            except Exception:  # noqa: BLE001 — column not migrated yet
                return (client.table("bot_settings")
                        .select("user_id, allocation_overrides, "
                                "auto_trade_enabled")
                        .execute())
        try:
            rows = (await asyncio.to_thread(_books)).data or []
        except Exception as e:  # noqa: BLE001
            return [AgentMessage(agent=self.name, kind="error",
                                 payload={"error": str(e)[:200]})]

        for row in rows:
            uid = str(row.get("user_id") or "")
            if not uid:
                continue
            msgs = await self._tick_book(client, uid, row)
            out.extend(msgs)
        return out

    async def _tick_book(self, client, uid: str, row: dict
                         ) -> list[AgentMessage]:
        out: list[AgentMessage] = []

        inp = _lane_inputs_for(row, 0.0)
        if inp is None:
            return out           # this book does not run the lane

        sizing = size_lane(inp)

        # --- open positions for this book (states + what we already hold)
        def _positions():
            return (client.table("paper_positions")
                    .select("ticker, quantity, asset_type, strategy")
                    .eq("user_id", uid).eq("status", "open").execute())
        try:
            positions = (await asyncio.to_thread(_positions)).data or []
        except Exception:  # noqa: BLE001
            positions = []

        # `held` is EVERY open holding in the book, whatever strategy
        # opened it: the fresh filter below must not propose a name the
        # book already owns under another lane. `ladder` is only what
        # THIS lane opened -- that is what counts against ladder_names.
        held = {}
        ladder = {}
        for p in positions:
            t = str(p.get("ticker") or "").upper()
            if not t:
                continue
            qty = float(p.get("quantity") or 0)
            held[t] = held.get(t, 0.0) + qty
            # TE-07 (audit 2026-09-01): this used to count ALL open
            # positions as ladder names, so a book with a few ordinary
            # stock positions read as a full ladder and the lane never
            # added a single name. Only strategy='dividend_lt' is ladder.
            if str(p.get("strategy") or "") == "dividend_lt":
                ladder[t] = ladder.get(t, 0.0) + qty

        ladder_held = [t for t in ladder if ladder[t] > 0]
        room = max(0, sizing.ladder_names - len(ladder_held))

        # --- graduation watch (§3). This fires regardless of whether the
        # lane has room to add: a name crossing 100 shares is the event
        # the spec most wants surfaced, because it is compounding
        # unlocking option income by itself. Watched on LADDER names only
        # (TE-07): an ordinary stock position crossing 100 shares is not a
        # lane graduation, and screening every holding each tick was a
        # lookup per position for an event that could not apply to it.
        from app.strategies.dividend_screen import screen as _screen
        for ticker, qty in ladder.items():
            key = f"{uid}:{ticker}"
            try:
                verdict = await _screen(ticker)
            except Exception:  # noqa: BLE001
                continue
            state = name_state(qty, verdict.tier)
            prior = self._last_states.get(key)
            self._last_states[key] = state
            if prior == FRACTIONAL and state == LOT_READY:
                out.append(AgentMessage(
                    agent=self.name, kind="info", confidence=1.0,
                    payload={
                        "user_id": uid, "ticker": ticker,
                        "event": "lane_graduation",
                        "note": (f"{ticker} reached {qty:.0f} shares — "
                                 f"FRACTIONAL to LOT_READY. Covered calls "
                                 f"now eligible on this name."),
                    }))

        if inp.mode == "INCOME":
            return out           # drawing down, not building
        if room <= 0:
            return out

        # --- candidates: market-wide, screened, sector-capped
        try:
            from app.data.market_universe import market_wide_candidates
            pool = await market_wide_candidates(limit=80)
        except Exception:  # noqa: BLE001
            pool = []
        if not pool:
            return out

        fresh = [s for s in pool if s.upper() not in held]
        try:
            verdicts = await screen_many(fresh)
        except Exception as e:  # noqa: BLE001
            out.append(AgentMessage(agent=self.name, kind="error",
                                    payload={"error": str(e)[:200]}))
            return out

        eligible = [v for v in verdicts.values() if v.ladder_eligible]
        # Rank: quality first (payout headroom, streak), yield second. The
        # lane is not reaching for yield — that is the trap the whole spec
        # is written against.
        eligible.sort(key=lambda v: (
            -(v.raise_streak_years or 0),
            (v.payout_ratio if v.payout_ratio is not None else 1.0),
            -(v.yield_pct or 0.0),
        ))
        chosen = sector_capped(eligible)[:min(room, MAX_NEW_ENTRIES_PER_TICK)]

        cap_pct = per_name_cap_pct(sizing)
        per_name_dollars = sizing.ladder_capital * cap_pct

        for v in chosen:
            out.append(AgentMessage(
                agent=self.name, kind="signal", confidence=0.60,
                payload={
                    "user_id": uid,
                    "ticker": v.ticker,
                    # TE-07 (audit 2026-09-01): the platform vocabulary is
                    # bullish/bearish. Trade Execution maps ONLY 'bullish'
                    # to a long; the 'long' this used to emit would have
                    # been routed as a SHORT of a dividend grower.
                    "direction": "bullish",
                    "strategy": "dividend_lt",
                    "asset_type": "stock",
                    # The ladder has no stop: a dividend grower is held
                    # through drawdowns, and the exits are the spec's
                    # (dividend cut, payout breach, recycling ratio), not
                    # a price stop. Signalled explicitly so Risk Manager
                    # does not infer a missing one.
                    # TE-06 / NEQ-05 (audit 2026-09-01): deliberately NO
                    # `tcs` on this signal. Risk Manager only forwards
                    # signals that carry a tcs (TE-06), so the lane stays
                    # dark -- but the `no_price_stop` contract is not yet
                    # honoured downstream (NEQ-05): adding a tcs today
                    # would put the default 5% price stop on every ladder
                    # name. Turn the lane on only after NEQ-05 is fixed;
                    # that is Mike's call, not this agent's.
                    "no_price_stop": True,
                    "max_notional": round(per_name_dollars, 2),
                    "dividend_lt": {
                        "tier": v.tier,
                        "yield_pct": v.yield_pct,
                        "payout_ratio": v.payout_ratio,
                        "raise_streak_years": v.raise_streak_years,
                        "sector": v.sector,
                        "rationale": v.explain(),
                        "per_name_cap_pct": cap_pct,
                        "ladder_names_target": sizing.ladder_names,
                        "unlocks": sizing.unlocks,
                    },
                }))

        if chosen:
            out.append(AgentMessage(
                agent=self.name, kind="info", confidence=1.0,
                payload={
                    "user_id": uid, "ticker": "LANE",
                    "event": "dividend_lt_scan",
                    "note": (f"screened {len(verdicts)} names, "
                             f"{len(eligible)} eligible, proposing "
                             f"{len(chosen)}; ladder {len(ladder_held)}/"
                             f"{sizing.ladder_names} names, "
                             f"cap {cap_pct*100:.0f}%/name"),
                }))
        return out
