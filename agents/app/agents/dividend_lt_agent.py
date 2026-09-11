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

ENTRY CONFIDENCE (2026-09-10). Each book's dividend_lt_enabled flag controls
its own ladder. Quality-screened candidates receive a measured bullish
pattern score when TREZO_DIVIDEND_LT_TCS is unset/0. The former global
score override (e.g. TREZO_DIVIDEND_LT_TCS=75) is retained for compatibility
and labelled as configured, never presented as measured evidence. Risk
Manager applies the book's unchanged tcs_threshold and other gates. Missing
market data or a non-bullish setup produces a visible skip, never a score
copied from the entry threshold. The no-price-stop execution and monitoring
contract remains required on every signal, together with book_scoped and
the independently sized max_notional.
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


def _lane_tcs() -> int:
    """Legacy configured score, or 0 to require measured candidate scoring."""
    try:
        v = getattr(get_settings(), "trezo_dividend_lt_tcs", 0)
        return max(0, min(100, int(float(v or 0))))
    except Exception:  # noqa: BLE001
        return 0


def _lane_inputs_for(row: dict, equity: float) -> Optional[LaneInputs]:
    """Build §1 inputs from a book's bot_settings row.

    `allocation_overrides` already carries the owner's pocket split, so
    the lane reads the SAME numbers the rest of the platform sizes
    against rather than inventing a parallel truth. Falls back to spec
    defaults (70/25/5) when a book has no overrides.
    """
    from app.paper.allocation import build_allocation
    pockets = build_allocation(
        equity, posture_setting=str(row.get("account_posture") or "auto"),
        overrides=row.get("allocation_overrides"),
    ).budgets
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


async def _measured_entry_score(ticker: str, cfg):
    """Use the existing chart scorer after the independent dividend screen."""
    from app.data.candles import fetch_candles_for
    from app.patterns.confluence import confluence_bonus
    from app.patterns.scoring import MarketContext, calculate_score
    candles = await fetch_candles_for(ticker, "stock")
    if not candles or len(candles) < 15:
        return None
    conf = confluence_bonus({"recent_15": candles[-15:],
                             "recent_30": candles[-30:], "full": candles})
    return calculate_score(candles, MarketContext(
        confluence_bonus=float(conf["bonus"]),
        pattern_weights=getattr(cfg, "pattern_weights", None),
    ), strategy="dividend_lt")


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

        def blocked(reason, note, ticker="LANE"):
            return AgentMessage(agent=self.name, kind="info", payload={
                "event": "dividend_lt_blocked", "user_id": uid,
                "ticker": ticker, "reason": reason, "note": note,
            })

        from app.runtime.settings import get_bot_settings, is_fallback_settings
        from app.paper.allocation import effective_equity
        try:
            cfg = get_bot_settings(uid)
            if not uid or is_fallback_settings(cfg):
                return [blocked("settings_unverified",
                    "Cannot verify this book's dividend settings; no ladder entries proposed.")]
            if not getattr(cfg, "dividend_lt_enabled", True):
                return [blocked("disabled_for_book", "Dividend ladder disabled for this book.")]
            equity = await effective_equity(uid)
            lane_row = dict(row)
            lane_row.setdefault("account_posture", cfg.account_posture)
            lane_row.setdefault("allocation_overrides", cfg.allocation_overrides)
            inp = _lane_inputs_for(lane_row, equity)
        except Exception as exc:  # noqa: BLE001
            return [blocked("allocation_unavailable", f"Could not resolve this book's lane budget: {exc}")]
        if inp is None:
            return [blocked("income_budget_or_lane_inputs",
                "Income pocket is below $500 or the lane inputs violate its guardrails.")]

        sizing = size_lane(inp)

        # --- open positions for this book (states + what we already hold)
        def _positions():
            return (client.table("paper_positions")
                    .select("ticker, quantity, asset_type, strategy")
                    .eq("user_id", uid).eq("status", "open").execute())
        try:
            result = await asyncio.to_thread(_positions)
            if getattr(result, "error", None) or not isinstance(result.data, list):
                raise RuntimeError("Open-position read did not return a verified list")
            positions = result.data
        except Exception as exc:  # noqa: BLE001
            return [blocked("position_read_failed",
                f"Cannot verify this book's holdings; no ladder entries proposed: {exc}")]

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
            return out + [blocked("income_draw_mode", "INCOME mode draws cash rather than adding ladder names.")]
        if room <= 0:
            return out + [blocked("ladder_full", "This book has reached its configured ladder name count.")]

        # --- candidates: market-wide, screened, sector-capped
        try:
            from app.data.market_universe import market_wide_candidates
            pool = await market_wide_candidates(limit=80)
        except Exception:  # noqa: BLE001
            pool = []
        if not pool:
            return out + [blocked("market_candidates_unavailable", "No market-wide candidates available this tick.")]

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
        _tcs = _lane_tcs()

        for v in chosen:
            score = None
            tcs = _tcs
            if tcs <= 0:
                try:
                    score = await _measured_entry_score(v.ticker, cfg)
                except Exception as exc:  # noqa: BLE001
                    out.append(blocked("scoring_unavailable", str(exc)[:180], v.ticker))
                    continue
                if score is None:
                    out.append(blocked("scoring_unavailable", "Insufficient candles for measured entry confidence.", v.ticker))
                    continue
                if score.direction != "bullish":
                    out.append(blocked("no_bullish_setup",
                        f"Dividend quality screen passed, but chart direction is {score.direction}; no ladder buy proposed.", v.ticker))
                    continue
                tcs = int(score.tcs)
            _payload = {
                "user_id": uid,
                "ticker": v.ticker,
                # TE-07 (audit 2026-09-01): the platform vocabulary is
                # bullish/bearish. Trade Execution maps ONLY 'bullish'
                # to a long; the 'long' this used to emit would have
                # been routed as a SHORT of a dividend grower.
                "direction": "bullish",
                "strategy": "dividend_lt",
                "asset_type": "stock",
                "tcs": tcs,
                "tcs_source": "measured_pattern_score" if score is not None else "legacy_configured_score",
                "breakdown": dict(score.breakdown) if score is not None else {},
                # The ladder has no stop: a dividend grower is held
                # through drawdowns, and the exits are the spec's
                # (dividend cut, payout breach, recycling ratio), not
                # a price stop. Signalled explicitly so Risk Manager
                # does not infer a missing one, the executor plants
                # none, and the monitor manages none (NEQ-05). On
                # EVERY signal, switch or no switch.
                "no_price_stop": True,
                # Pin the ladder entry to THIS book. Without book_scoped the
                # executor treats user_id as provenance and fans the approval
                # out to every book at this book's per-name cap (Wave 3 review).
                "book_scoped": True,
                "max_notional": round(per_name_dollars, 2),
                "dividend_lt": {
                    "quality_screen_passed": True,
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
                }
            out.append(AgentMessage(
                agent=self.name, kind="signal", confidence=tcs / 100.0,
                payload=_payload))

        if chosen:
            out.append(AgentMessage(
                agent=self.name, kind="info", confidence=1.0,
                payload={
                    "user_id": uid, "ticker": "LANE",
                    "event": "dividend_lt_scan",
                    "note": (f"screened {len(verdicts)} names, "
                             f"{len(eligible)} eligible, proposing "
                             f"{sum(m.kind == 'signal' for m in out)}; ladder {len(ladder_held)}/"
                             f"{sizing.ladder_names} names, "
                             f"cap {cap_pct*100:.0f}%/name"),
                }))
        return out
