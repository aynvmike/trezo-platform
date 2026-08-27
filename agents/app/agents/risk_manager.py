"""Risk Manager Agent - highest authority.

Subscribes to `signal` messages. For each one, applies position-sizing and
exposure rules and emits either an `approve` or `veto`. Veto wins -
Trade Execution only ever listens for `approve`.

Rules:
  - Veto if direction is "neutral" (no actionable bias)
  - Veto if the signal's strategy is paused by Adaptive Scope
  - Veto if the signal's ticker is flagged by Adaptive Scope
  - Veto if TCS below the user's threshold (raised by the regime posture)
  - Veto if too many open signals already (configurable cap)
  - Veto for everyone today if a user's daily loss limit has been hit
  - Veto for everyone if a safety kill-switch is tripped (Phase 8c)
  - Otherwise approve, forwarding strategy + stop/target geometry, with
    stops tightened by the current Adaptive Scope posture
"""

from __future__ import annotations

import asyncio
import os
from collections import deque

_LAST_KS_LOG = 0.0   # kill-switch veto log throttle (2026-07-07)

from app.config import get_settings
from app.memory import get_memory, AgentDecision
from app.learning.recall_helpers import recall_decision_context
from app.learning.bucket_helpers import (
    is_hopeful, hopeful_allocation_pct, hopeful_cap_for_user,
)

from .base import Agent, AgentMessage


def _supabase():
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(settings.supabase_url, settings.supabase_service_role_key)
    except Exception:
        return None


async def _find_rotation_candidate(
    user_id, incoming_tcs: int,
) -> dict | None:
    """When a signal is vetoed for the open-position cap, ask:
    which open position is the weakest fit, and would the incoming
    signal beat it cleanly? Returns a hint dict the UI can render as
    "Trim AAPL to take SOFI" guidance, or None when no clear swap.

    Pure advisory - this does NOT auto-close anything. Mike's pattern:
    surface the asymmetry, let the user pick the action.
    """
    if not user_id:
        return None
    client = _supabase()
    if not client:
        return None
    try:
        def _sync():
            return (
                client.table("paper_positions")
                .select("id, ticker, side, asset_type, quantity, "
                        "entry_price, stop_price, target_price, entry_at, "
                        "source_payload, peak_unrealized_pnl_usd")
                .eq("user_id", user_id)
                .eq("status", "open")
                .execute()
            )
        res = await asyncio.to_thread(_sync)
        rows = res.data or []
        if not rows:
            return None

        # Score each open position via position_health. Pick the
        # weakest (lowest effective TCS = entry TCS minus decay).
        from app.learning.position_health import compute_position_health
        weakest = None
        weakest_score = None
        for pos in rows:
            try:
                h = await compute_position_health(pos)
            except Exception:  # noqa: BLE001
                h = None
            if h is None or h.entry_tcs is None or h.current_tcs is None:
                continue
            # Effective TCS = current TCS (already decayed). Lower is weaker.
            if weakest_score is None or h.current_tcs < weakest_score:
                weakest = (pos, h)
                weakest_score = h.current_tcs

        if not weakest or weakest_score is None:
            return None

        # Only flag as a rotation when the incoming signal beats the
        # weakest by a clear margin (>= 75 TCS). Otherwise the swap
        # is noise.
        if incoming_tcs - weakest_score < 75:
            return None

        pos, h = weakest
        return {
            "position_id": pos["id"],
            "ticker": pos.get("ticker"),
            "current_tcs": h.current_tcs,
            "entry_tcs": h.entry_tcs,
            "tcs_decay_pct": h.tcs_decay_pct,
            "incoming_tcs": incoming_tcs,
            "gap": incoming_tcs - h.current_tcs,
            "recommendation": h.recommendation,
        }
    except Exception:  # noqa: BLE001
        return None


async def _users_in_daily_drawdown() -> set[str]:
    """Return user_ids whose today's realized loss meets/exceeds their limit."""
    client = _supabase()
    if not client:
        return set()

    def _sync():
        accounts = client.table("paper_accounts").select("user_id, today_realized_pnl_usd").execute()
        profiles = client.table("profiles").select("user_id, daily_loss_limit_usd").execute()
        return accounts.data or [], profiles.data or []

    accounts, profiles = await asyncio.to_thread(_sync)
    limit_by_user: dict[str, float] = {}
    for p in profiles:
        try:
            v = float(p.get("daily_loss_limit_usd") or 0)
            if v > 0:
                limit_by_user[p["user_id"]] = v
        except (TypeError, ValueError):
            pass

    drawdown: set[str] = set()
    for a in accounts:
        uid = a["user_id"]
        limit = limit_by_user.get(uid, 0)
        if limit <= 0:
            continue
        try:
            today = float(a.get("today_realized_pnl_usd") or 0)
        except (TypeError, ValueError):
            continue
        if today <= -limit:
            drawdown.add(uid)
    return drawdown


class RiskManagerAgent(Agent):
    name = "risk_manager"
    tick_interval_seconds = 0  # event-driven; never auto-ticks

    # Note: TCS minimum used to live here as a class default. It now
    # comes from `bot_settings.tcs_threshold` (per-user) via
    # `get_bot_settings(user_id).tcs_threshold` so the user's Bot Tuning
    # slider drives the gate. The dead constant is gone on purpose.
    MAX_OPEN_SIGNALS = 3
    DEFAULT_PCT_OF_ACCOUNT = 0.02
    # Cached broker snapshot for the margin-territory gate (60s TTL).
    _margin_snap: dict = {"ts": 0.0, "cash": None, "equity": None}

    def __init__(self) -> None:
        # Patched 2026-06-04 stacking fix: set, not deque(maxlen=8).
        # Old deque rotated entries silently so the cap check
        # (len() >= max_open_positions) was effectively dead, AND it
        # allowed the same ticker to appear multiple times. Result: GM
        # got approved 3x in one morning -> 84 shares on $5K equity.
        # Now a set dedupes naturally; Position Monitor calls
        # forget_ticker(t) when a position closes so re-buys ARE
        # allowed after the existing trade exits.
        # 2026-07-15 (Mike's quiet afternoon): set -> dict of
        # ticker -> approved-at epoch (0.0 = seeded from an open
        # position). Slots SELF-HEAL: _prune_approvals frees any entry
        # whose ticker has no open row and whose approval is stale --
        # leaked slots (silent execute deaths, close paths that never
        # message us) can no longer suffocate the desk at the cap.
        self._recent_approvals: dict[str, float] = {}
        self._last_prune: float = 0.0
        # Patched 2026-06-10 (Mike's WMT 52-share incident): seed
        # open positions into the dedup set on first message so a
        # restart-while-positions-open doesn't re-stack.
        self._seeded_open_positions: bool = False

    async def _seed_open_positions(self) -> None:
        """Load currently-open position tickers into _recent_approvals
        so dedup survives agent restarts. Best-effort - any failure
        leaves the set empty and we fall back to the runtime behavior
        (concentration cap still gates oversizing). Idempotent: only
        runs the seed query once per process lifetime."""
        if self._seeded_open_positions:
            return
        self._seeded_open_positions = True
        try:
            from app.runtime.persistence import _client
            client = _client()
            if client is None:
                return
            import asyncio
            def _fetch():
                return client.table("paper_positions").select(
                    "ticker"
                ).eq("status", "open").execute()
            res = await asyncio.to_thread(_fetch)
            for row in (res.data or []):
                t = (row.get("ticker") or "").strip().upper()
                if t:
                    self._recent_approvals[t] = 0.0
        except Exception:  # noqa: BLE001
            pass

    async def _prune_approvals(self) -> None:
        """SELF-HEALING for the open-signal cap (Mike 2026-07-15: the
        afternoon went quiet at ~50% deployed -- every veto said
        'Open-signal cap reached (10)' while leaked slots sat on
        tickers with no position behind them, AAL among them). A slot
        may be held only while (a) the ticker still has an OPEN
        position row, or (b) the approval is younger than
        TREZO_APPROVAL_TTL_H (2h) and may still be executing.
        Everything else is a leak and gets freed. Runs at most every
        10 minutes; never raises."""
        import os as _pr_os
        import time as _pr_t
        now = _pr_t.time()
        if now - self._last_prune < 600.0:
            return
        self._last_prune = now
        try:
            from app.runtime.persistence import _client
            client = _client()
            if client is None:
                return
            import asyncio as _pr_aio

            def _fetch():
                return (client.table("paper_positions")
                        .select("ticker").eq("status", "open").execute())
            res = await _pr_aio.to_thread(_fetch)
            open_tk = {(r.get("ticker") or "").strip().upper()
                       for r in (res.data or [])}
            ttl = float(_pr_os.getenv("TREZO_APPROVAL_TTL_H", "2")) * 3600.0
            before = len(self._recent_approvals)
            self._recent_approvals = {
                t: ts for t, ts in self._recent_approvals.items()
                if t in open_tk or (ts > 0 and (now - ts) < ttl)
            }
            freed = before - len(self._recent_approvals)
            if freed > 0:
                try:
                    from app.agents.activity_log import record as _rec
                    _rec("approval_slots_freed", "SYSTEM",
                         reason=(f"{freed} leaked approval slot(s) freed "
                                 f"-- no open position and no in-flight "
                                 f"execution behind them (the open-signal "
                                 f"cap self-heals)"),
                         extra={})
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass

    def forget_ticker(self, ticker: str) -> None:
        """Position Monitor calls this when a position closes, allowing
        a fresh approval on the same ticker. If the ticker was never in
        the set, the discard is a silent no-op."""
        self._recent_approvals.pop(ticker.upper(), None)

    async def _account_equity(self, user_id) -> float:
        """Best-effort account equity (cash + vault) for per-coin cap
        math. Returns 0.0 on any miss (the cap then disengages and the
        normal single-row dedup still protects the book)."""
        try:
            from app.paper.engine import get_account
            acct = await get_account(user_id)
            if not acct:
                return 0.0
            return (float(acct.get("current_cash_usd") or 0)
                    + float(acct.get("vault_balance_usd") or 0))
        except Exception:  # noqa: BLE001
            return 0.0

    async def _crypto_coin_state(self, user_id, coin: str) -> dict:
        """Summed open exposure + hours since the most recent add for a
        single coin, across every open row and pair-symbol variant
        (BTC / BTCUSD / BTC/USD). Powers the per-coin HODL cap and the
        accumulation cooldown. Best-effort: any failure returns an empty
        state so the caller falls back to plain single-row dedup."""
        empty = {"exposure_usd": 0.0, "rows": 0, "hours_since_last": 1e9}
        try:
            from datetime import datetime, timezone
            from app.runtime.persistence import _client
            client = _client()
            if client is None:
                return empty
            try:
                from app.brokers.alpaca import crypto_symbol_variants
                variants = sorted(crypto_symbol_variants(coin))
            except Exception:  # noqa: BLE001
                variants = [coin.upper()]
            def _fetch():
                q = (client.table("paper_positions")
                     .select("quantity, entry_price, entry_at")
                     .eq("status", "open").in_("ticker", variants))
                if user_id:
                    q = q.eq("user_id", user_id)
                return q.execute()
            res = await asyncio.to_thread(_fetch)
            rows = res.data or []
            exposure = 0.0
            latest = None
            for row in rows:
                try:
                    exposure += (float(row.get("quantity") or 0)
                                 * float(row.get("entry_price") or 0))
                except (TypeError, ValueError):
                    pass
                ts = row.get("entry_at")
                if ts:
                    try:
                        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if latest is None or dt > latest:
                            latest = dt
                    except Exception:  # noqa: BLE001
                        pass
            hours_since = 1e9
            if latest is not None:
                now = datetime.now(timezone.utc)
                hours_since = (now - latest).total_seconds() / 3600.0
            return {"exposure_usd": exposure, "rows": len(rows),
                    "hours_since_last": hours_since}
        except Exception:  # noqa: BLE001
            return empty

    async def tick(self) -> list[AgentMessage]:
        return []

    # Tiered staleness deadlines by TCS (Task #89, 2026-06-05).
    # Mike's design: urgent signals get fast processing, low-priority
    # signals can wait, and anything older than its tier gets vetoed
    # with timeout. Prevents queue buildup when APIs lag.
    STALE_TIMEOUTS = (
        (700, 60),    # TCS >= 700 -> 60-second deadline (urgent)
        (500, 180),   # TCS 500-699 -> 180-second deadline (MIXED priority - Mike 2026-06-05: TCS in this band is misleading on urgency, will be refined by agent-tagged urgency over time)
        (0,   300),   # TCS <  500 -> 300-second deadline (low priority)
    )

    # Agent-tagged urgency override mapping. Mike 2026-06-05: TCS alone
    # is misleading for urgency. Agents (eventually informed by Mem0
    # outcomes) tag signals with payload["urgency"] - we honor that
    # tag over the score-based tier. This is the seam for the
    # "agent-recommended priority" upgrade Mike asked for.
    URGENCY_TAGS = {
        "urgent": 60,
        "mixed":  180,
        "medium": 180,  # alias for mixed
        "low":    300,
    }

    @classmethod
    def _stale_deadline_for(cls, tcs: int, urgency_tag: str | None = None) -> int:
        # 1. If the emitting agent tagged urgency directly, use that.
        if urgency_tag:
            t = str(urgency_tag).strip().lower()
            if t in cls.URGENCY_TAGS:
                return cls.URGENCY_TAGS[t]
        # 2. Otherwise fall back to TCS-band tier.
        for floor, secs in cls.STALE_TIMEOUTS:
            if tcs >= floor:
                return secs
        return 300

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        # Patched 2026-06-10 (Mike's WMT 52-share incident): seed open
        # positions into the dedup set on first message so a restart
        # while positions are already open doesn't re-stack the ticker
        # via fresh signals.
        await self._seed_open_positions()
        await self._prune_approvals()

        # Approve-without-fill release (2026-06-11). Found live: SOFI was
        # approved at 9:16/9:29 ET pre-open, Trade Execution skipped it
        # ("Market closed"), but the ticker stayed in _recent_approvals --
        # so every fresh SOFI signal for the REST OF THE DAY was vetoed
        # as "already approved" with no position behind it. Any
        # trade_execution info/error about a ticker that is NOT a fill
        # means the approve died (market closed, budget skip, sizing
        # reject, broker reject); free the ticker so the next signal can
        # be considered on its own merits. Safe because fills emit
        # kind="execute" only, and trade_execution has no info/error
        # emission after a successful submit (verified 2026-06-11) --
        # so info/error + ticker always means "no position was opened".
        if message.agent == "trade_execution" and message.kind in ("info", "error"):
            _p = message.payload if isinstance(message.payload, dict) else {}
            _tk = str(_p.get("ticker") or "").upper().strip()
            if _tk:
                self.forget_ticker(_tk)
            return []

        # Tiered staleness veto (Task #89, 2026-06-05). Mike: signals
        # waiting past their priority deadline get auto-cleared so they
        # don't sit in a hung queue forever. Cheap check, runs BEFORE
        # all expensive Supabase / Mem0 work so stale signals also
        # relieve load.
        if message.kind == "signal":
            import time
            ts_val = message.payload.get("emitted_at_epoch") or message.payload.get("ts")
            if ts_val is not None:
                try:
                    age = time.time() - float(ts_val)
                    tcs_for_age = int(message.payload.get("tcs", 0))
                    urgency_tag = message.payload.get("urgency")
                    deadline = self._stale_deadline_for(tcs_for_age, urgency_tag)
                    if age > deadline:
                        return [self._veto(
                            message.payload.get("ticker", "?"),
                            tcs_for_age,
                            f"Stale signal: {int(age)}s old, tier deadline {deadline}s "
                            f"(TCS {tcs_for_age}) - auto-cleared by timeout",
                            strategy=message.payload.get("strategy"),
                            user_id=message.payload.get("user_id"),
                        )]
                except (TypeError, ValueError):
                    pass  # bad timestamp - don't block, just process normally

        # Listen for close messages to forget the ticker so a fresh
        # approval is allowed (Patched 2026-06-04 stacking fix - paired
        # with the dedup veto above). Position Monitor emits kind="close"
        # whenever a position exits via stop/target/manual/alpaca.
        if message.kind == "close":
            tk = (message.payload or {}).get("ticker")
            if tk:
                self.forget_ticker(str(tk))
            return []

        if message.kind != "signal":
            return []

        tcs = int(message.payload.get("tcs", 0))
        direction = message.payload.get("direction", "neutral")
        ticker = message.payload.get("ticker", "?")
        strategy = message.payload.get("strategy", "default")
        stop_pct = message.payload.get("stop_pct")
        target_pct = message.payload.get("target_pct")

        # User-tunable thresholds from the Bot Tuning settings page.
        from app.runtime.settings import get_bot_settings
        # Per-user settings when the signal is user-scoped (#119);
        # the global row otherwise.
        cfg = get_bot_settings(message.payload.get("user_id"))
        min_tcs = cfg.tcs_threshold
        # Strategy-coverage test mode (Mike 2026-07-02): drop the floor to
        # TREZO_COVERAGE_TCS (400) so EVERY strategy can find one live,
        # labeled trade instead of waiting on perfect tape.
        _coverage_on = os.getenv("TREZO_COVERAGE_MODE", "0") != "0"
        if _coverage_on:
            try:
                min_tcs = min(int(min_tcs),
                              int(float(os.getenv("TREZO_COVERAGE_TCS", "40"))))
            except (TypeError, ValueError):
                min_tcs = min(int(min_tcs), 40)
        # Crypto floor (Mike 2026-07-23): crypto_* strategies run at
        # trezo_crypto_tcs_floor (Settings/.env, default 35) when that
        # is below the slider -- otherwise 35-49 signals the scanner
        # now emits would die here at 50. Fee gate, regime bumps, and
        # pockets still apply on top.
        try:
            if str(strategy or "").lower().startswith("crypto"):
                from app.config import get_settings as _gs_cf
                min_tcs = min(int(min_tcs), int(getattr(
                    _gs_cf(), "trezo_crypto_tcs_floor", 35)))
        except Exception:  # noqa: BLE001
            pass
        max_open = cfg.max_open_positions

        # Adaptive Scope - the news/regime self-tuner (Phase 7.5). The Risk
        # Manager is the single enforcement point: every signal flows
        # through here, so consulting scope here covers every strategy.
        from app.runtime.scope import get_scope
        scope = get_scope()

        if direction == "neutral":
            return [self._veto(ticker, tcs, "Neutral direction - no actionable bias")]

        # Paused strategy - a base name in the paused set pauses its
        # variants too (e.g. 'crypto' pauses crypto_scalp/swing/dca).
        if (strategy in scope.paused_strategies
                or strategy.split("_")[0] in scope.paused_strategies):
            return [self._veto(
                ticker, tcs,
                f"Strategy '{strategy}' paused by Adaptive Scope [{scope.regime}]")]

        # Breakout PROBATION (Mike 2026-07-14: "I would like for it to be
        # active -- it helps with the opening of the market"). Probation
        # families are never blocked: they pay a +10 confidence bar and
        # trade HALF size while the regime lasts. Awareness without blackout.
        probation_bump = 0
        probation_note = ""
        try:
            from app.strategies.adaptive import TREZO_STRATEGY_FAMILY as _famm
            from app.strategies.library import playbook_for as _pbf
            _play = _pbf(str(getattr(scope, "regime", "") or ""))
            _prob = set(getattr(_play, "probation", ()) or ()) if _play else set()
            if _prob:
                _fam = (_famm.get(strategy)
                        or _famm.get(strategy.split("_")[0]))
                if _fam in _prob:
                    probation_bump = 10
                    probation_note = f", {_fam} probation +10 half-size"
        except Exception:  # noqa: BLE001
            probation_bump = 0

        # Flagged ticker - a recent material event on this name.
        if ticker in scope.flagged_tickers:
            return [self._veto(
                ticker, tcs,
                f"{ticker} flagged by Adaptive Scope - recent material event")]

        # Expert override: per-stock disable list. When the user has
        # turned off a ticker (e.g. "skip NVDA until earnings"),
        # Risk Manager vetoes every signal on it with the user's
        # reason in the note.
        try:
            from app.runtime.overrides import get_disabled_reason
            disabled_reason = await get_disabled_reason(
                message.payload.get("user_id"), ticker,
            )
            if disabled_reason:
                return [self._veto(
                    ticker, tcs,
                    f"{ticker} disabled in Expert overrides: {disabled_reason}")]
        except Exception:  # noqa: BLE001
            pass

        # Cycle-aware bump (Phase 13a). Mike's "think like a human" push:
        # directional plays close to earnings are riskier - IV is rich
        # so options trades pay better, but stock trades face a binary
        # event. Bump the TCS floor by +50 when within 3 days of
        # earnings to filter all but the strongest signals. Strategies
        # that EXPLICITLY want the earnings window (iv_crush_short)
        # bypass this bump.
        cycle = message.payload.get("cycle") or {}
        cycle_bump = 0
        cycle_reason = ""
        days_to_earnings = cycle.get("next_earnings_days")
        iv_env = cycle.get("iv_environment", "normal")
        cycle_aware_strategy = strategy in (
            "iv_crush_short", "dividend_capture_long",
        )
        if (
            isinstance(days_to_earnings, int)
            and 0 < days_to_earnings <= 3
            and not cycle_aware_strategy
        ):
            cycle_bump = 5
            cycle_reason = f" (earnings in {days_to_earnings}d +50)"
        elif iv_env == "earnings_day" and not cycle_aware_strategy:
            cycle_bump = 15
            cycle_reason = " (earnings TODAY +150)"

        # Market-report bump (2026-08-25, Mike: reports processed "for
        # each agent"). When the Market Desk holds a FRESH report calling
        # the tape risk_off, every EQUITY and OPTIONS entry needs +5 more
        # conviction. Same additive family as the earnings bump above.
        # Tighten-only by construction: risk_on and mixed add nothing --
        # the report can raise the bar, never lower it. Crypto and forex
        # are deliberately exempt: a 24/7 book gated by a 9:30-4:00
        # equity read would be borrowing context across market hours,
        # and crypto already carries its own floor (35).
        report_bump = 0
        report_reason = ""
        try:
            if not str(strategy or "").startswith(("crypto", "forex")):
                from app.agents.market_desk import current_market_view
                _mv = current_market_view()
                if _mv is not None and _mv.regime == "risk_off":
                    report_bump = 5
                    report_reason = (f" (market report [{_mv.slot}] "
                                     f"risk_off +5)")
        except Exception:  # noqa: BLE001
            pass

        # Experience-driven floor nudge (2026-06-16, OPT-IN, default OFF).
        # When enabled, the user's realized record moves the bar per strategy:
        # a proven winner ("favor") trades a bit more freely, a proven loser
        # ("avoid") needs higher conviction. Bounded + data-gated (>=8 closed
        # trades) so it never changes behavior until turned on with real data.
        outcome_delta = 0
        outcome_reason = ""
        try:
            from app.config import get_settings as _get_cfg
            if _get_cfg().outcome_gate_tuning_enabled:
                from app.learning.strategy_weighting import (
                    get_live_strategy_edge, floor_delta_for,
                )
                _edge = await get_live_strategy_edge(message.payload.get("user_id"))
                outcome_delta = floor_delta_for(_edge, strategy)
                if outcome_delta:
                    sign = "+" if outcome_delta > 0 else ""
                    outcome_reason = f" (record {sign}{outcome_delta})"
        except Exception:  # noqa: BLE001
            outcome_delta = 0

        # Daily-goal discipline (Mike 2026-07-13): once today's paycheck
        # is banked, new entries get PICKIER (+5 TCS) -- protect the day.
        # The goal never loosens anything; being behind changes nothing here.
        goal_bump = 0
        goal_reason = ""
        try:
            from app.paper.daily_goal import goal_state, mark_goal_hit_once
            _gs = await goal_state(message.payload.get("user_id"))
            if _gs.get("hit"):
                goal_bump = 5
                goal_reason = ", goal-banked +5"
                if mark_goal_hit_once(message.payload.get("user_id")):
                    try:
                        from app.agents.activity_log import record as _grec
                        _grec("daily_goal_hit", "ACCOUNT",
                              reason=(f"daily goal ${_gs['goal']:.0f} "
                                      f"({_gs['label']}) reached -- realized "
                                      f"${_gs['realized']:.2f}; new entries "
                                      "get pickier (+5 TCS) for the rest of "
                                      "the day"),
                              extra={"window": "day"})
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            goal_bump = 0

        # Margin-territory gate (Mike 2026-07-17): agents may dip into
        # margin buying power -- but leverage multiplies BOTH directions,
        # so it must be earned. When broker cash thins below
        # TREZO_MARGIN_CASH_FRACTION of equity (default 15% -- roughly
        # one position's notional), the next stock entry is margin
        # territory and the bar rises +TREZO_MARGIN_TCS_BUMP (default 8)
        # on top of every other bump. Crypto/forex exempt (no margin at
        # the venue; the engine keeps them cash-only). Snapshot cached
        # 60s; fail-open with no bump -- the engine's deployment ceiling
        # (TREZO_MAX_DEPLOY_X x equity) still caps exposure.
        leverage_bump = 0
        leverage_note = ""
        try:
            from app.data.candles import COIN_MAP as _CM_LEV
            _lev_exempt = (
                ticker.upper() in _CM_LEV
                or str(message.payload.get("asset_type") or "").lower()
                in ("forex", "crypto")
            )
        except Exception:  # noqa: BLE001
            _lev_exempt = False
        if not _lev_exempt:
            try:
                import time as _lvt
                _snap = type(self)._margin_snap
                if _lvt.time() - float(_snap.get("ts") or 0) > 60:
                    from app.brokers.alpaca import (
                        get_account, alpaca_configured,
                    )
                    if alpaca_configured():
                        _acct = await get_account()
                        if _acct:
                            _snap["cash"] = float(_acct.get("cash") or 0)
                            _snap["equity"] = float(_acct.get("equity") or 0)
                            _snap["ts"] = _lvt.time()
                _lc, _le = _snap.get("cash"), _snap.get("equity")
                if _lc is not None and _le and _le > 0:
                    try:
                        _lfrac = float(os.getenv(
                            "TREZO_MARGIN_CASH_FRACTION", "0.15"))
                    except (TypeError, ValueError):
                        _lfrac = 0.15
                    if _lc < _le * _lfrac:
                        try:
                            leverage_bump = int(float(os.getenv(
                                "TREZO_MARGIN_TCS_BUMP", "8")))
                        except (TypeError, ValueError):
                            leverage_bump = 8
                        leverage_note = (
                            f", margin territory +{leverage_bump} "
                            f"(cash ${_lc:,.0f} < {_lfrac:.0%} of "
                            f"${_le:,.0f} equity)")
            except Exception:  # noqa: BLE001
                leverage_bump = 0

        # BROKER-ONLY consistency gate (Mike 2026-07-28: "I would like
        # to have more of a consistency... the platform would not
        # recognize the trades and leave it out of the data"). Alpaca
        # has no forex venue, so forex rows can only ever be modeled.
        # Under broker-only they pause -- unless trezo_forex_modeled_ok
        # says Mike wants the lane anyway, clearly labelled.
        try:
            if str(message.payload.get("asset_type") or "").lower() == "forex":
                from app.config import get_settings as _gs_bo
                _cfg_bo = _gs_bo()
                if (bool(getattr(_cfg_bo, "trezo_broker_only", False))
                        and not bool(getattr(_cfg_bo,
                                             "trezo_forex_modeled_ok", False))):
                    return [self._veto(
                        ticker, tcs,
                        "Broker-only mode: Alpaca has no forex venue, so a "
                        "forex position could only ever be modeled - it "
                        "would never appear on the broker screen. Set "
                        "TREZO_FOREX_MODELED_OK=true to trade it anyway.")]
        except Exception:  # noqa: BLE001
            pass

        # CROWDING / correlation (Mike 2026-07-27: "deeper understanding
        # of the network and finance as a whole"). Counting positions is
        # not measuring risk: on 7/27 the book held 14 positions but 9
        # were crypto -- one risk factor, ~6.8 independent bets, and they
        # fell together. Adding to an already-crowded basket now costs
        # extra confidence (+3 at 4 open, +6 at 6, +9 at 8+), bounded
        # like every other bump. Never a ban: a crowded lane that is
        # earning can still trade -- it just has to be better.
        # PER-BOOK crowding (Mike 2026-08-21: "the open positions was
        # supposed to be for each pocket available in the book, not the
        # total"). The old query pooled every book's open rows into one
        # read, so the 25k was penalized for what the 75k held -- the
        # veto lines said "17 positions" when no single book held 17.
        # A veto here kills the signal for ALL books, so the honest
        # per-book judgement is the MINIMUM bump across active books:
        # if any book still has room in this basket, the signal stays
        # alive and the per-book gates downstream decide who takes it.
        crowding_bump_v = 0
        crowding_note = ""
        try:
            from app.data.portfolio_risk import (
                basket_of, concentration_read, crowding_bump,
            )
            _pr_cl = _supabase()
            if _pr_cl is not None:
                import asyncio as _aio_pr

                def _q_book():
                    return (_pr_cl.table("paper_positions")
                            .select("user_id, ticker, asset_type, strategy")
                            .eq("status", "open").limit(120).execute())
                _bk = (await _aio_pr.to_thread(_q_book)).data or []
                _by_book: dict[str, list] = {}
                for _row in _bk:
                    _u = str(_row.get("user_id") or "")
                    if _u:
                        _by_book.setdefault(_u, []).append(_row)
                _bask = basket_of(
                    ticker, str(message.payload.get("asset_type") or ""),
                    strategy)
                if _by_book:
                    _best: tuple[int, str] | None = None
                    for _rows in _by_book.values():
                        _bv, _bn = crowding_bump(
                            _bask, concentration_read(_rows))
                        if _best is None or _bv < _best[0]:
                            _best = (_bv, _bn)
                        if _best[0] == 0:
                            break  # some book has room - no bump
                    crowding_bump_v, crowding_note = _best
        except Exception:  # noqa: BLE001
            crowding_bump_v = 0

        # The confidence bar can be raised by the current regime posture,
        # the cycle-aware bump, the per-strategy outcome nudge, the
        # banked-paycheck bump, the margin-territory bump, and crowding.
        effective_min_tcs = (min_tcs + scope.tcs_bump + cycle_bump
                             + outcome_delta + goal_bump + probation_bump
                             + leverage_bump + crowding_bump_v + report_bump
                             + recovery_bump)
        if tcs < effective_min_tcs:
            extra = (
                f" (regime +{scope.tcs_bump}{cycle_reason}{outcome_reason}{goal_reason}{probation_note}{leverage_note}{crowding_note}{report_reason}{recovery_reason})"
                if (scope.tcs_bump or cycle_bump or outcome_delta
                        or goal_bump or probation_bump or leverage_bump
                        or crowding_bump_v or report_bump or recovery_bump)
                else ""
            )
            return [self._veto(
                ticker, tcs,
                f"TCS {tcs} below threshold {effective_min_tcs}{extra}")]

        # --- Crypto accumulation + per-coin cap (Mike 2026-06-13, Part 2) ---
        # Crypto HODL/DCA may SCALE IN on dips across days, unlike one-shot
        # stock/swing trades. Three guards keep it disciplined: a per-coin
        # exposure cap (summed across rows), a cooldown so adds land across
        # days (not every tick), and the normal max-open cap for brand-new
        # coins (below). Each add is its own small row, so the catastrophe
        # stop applies per add and the cap sums them.
        from app.data.candles import COIN_MAP as _COIN_MAP_ACC
        from app.strategies.crypto import is_accumulation_strategy
        _coin_u = ticker.upper()
        _is_crypto = _coin_u in _COIN_MAP_ACC
        # Forex (2026-07-02): fiat pairs skip the US-equity session and
        # stock-liquidity gates; costs are tiny (5bps slip each way) and
        # the scanner's ATR targets clear them. Pocket + sizing still gate.
        _is_forex = (str(message.payload.get("asset_type") or "").lower()
                     == "forex")
        _accumulate_mode = is_accumulation_strategy(strategy)
        accumulation_add = False
        if _is_crypto:
            # Fee-aware net-edge gate (Mike 2026-06-15): a crypto entry must
            # be able to net a profit after round-trip fees + slippage + a
            # 0.01% cushion. NEVER gate on the coin's price/cost -- only on net
            # profitability. Fails OPEN (allows) on any error.
            try:
                from app.strategies.crypto import (
                    COIN_PARAMS as _CP, clears_fee_edge as _cfe,
                    net_edge_pct as _nep,
                )
                from app.paper.engine import (
                    CRYPTO_COMMISSION_BPS as _FEE, SLIPPAGE_BPS as _SLIP,
                )
                _p = _CP.get(_coin_u)
                _tgt = float(_p["target_pct"]) if _p and _p.get("target_pct") else None
                if _tgt is not None and not _cfe(_tgt, _FEE, _SLIP):
                    _net = _nep(_tgt, _FEE, _SLIP)
                    return [self._veto(
                        ticker, tcs,
                        f"Net-edge filter: {_coin_u} target {_tgt * 100:.2f}% "
                        f"nets {_net * 100:+.2f}% after fees + slippage - "
                        f"below the +0.01% floor",
                        strategy=strategy,
                        user_id=message.payload.get("user_id"),
                    )]
            except Exception:
                pass
            _equity = await self._account_equity(message.payload.get("user_id"))
            _coin_state = await self._crypto_coin_state(
                message.payload.get("user_id"), _coin_u)
            _cap_pct = float(getattr(cfg, "hodl_per_coin_cap_pct", 0.10) or 0.10)
            _cap_usd = _equity * _cap_pct if _equity > 0 else 0.0
            # Hard per-coin ceiling: never approve more of a coin once its
            # summed open exposure has reached the cap. Guards first buys
            # and accumulation adds alike.
            if _cap_usd > 0 and _coin_state["exposure_usd"] >= _cap_usd:
                return [self._veto(
                    ticker, tcs,
                    f"Per-coin cap reached for {ticker}: "
                    f"${_coin_state['exposure_usd']:.0f} open is at/above "
                    f"{_cap_pct * 100:.0f}% of equity (${_cap_usd:.0f}). "
                    f"HODL holds; no more accumulation until it trims or "
                    f"equity grows.",
                    strategy=strategy,
                    user_id=message.payload.get("user_id"),
                )]

        # Patched 2026-06-04: same-ticker stacking veto. If this ticker
        # already has a recent approval (and Position Monitor hasn't told
        # us the position closed yet), veto rather than re-buy -- EXCEPT
        # crypto HODL/DCA, which may add once the cooldown clears.
        if _coin_u in self._recent_approvals:
            if _is_crypto and _accumulate_mode:
                _cool = float(getattr(cfg, "crypto_accumulate_cooldown_hours", 18.0) or 18.0)
                _hrs = _coin_state["hours_since_last"]
                if _hrs < _cool:
                    return [self._veto(
                        ticker, tcs,
                        f"{ticker} {strategy} accumulation on cooldown: last "
                        f"add {_hrs:.1f}h ago, need {_cool:.0f}h between adds. "
                        f"Holding the existing position.",
                        strategy=strategy,
                        user_id=message.payload.get("user_id"),
                    )]
                accumulation_add = True
            else:
                return [self._veto(
                    ticker, tcs,
                    f"Already approved {ticker} in this session - skip to "
                    f"avoid stacking. The open position must close (or be "
                    f"trimmed) before a fresh approval is allowed.",
                    strategy=strategy,
                    user_id=message.payload.get("user_id"),
                )]

        # Book-first (Mike 2026-08-20): "make the agents look at the
        # books as a default and not the account. no matter what."
        # This counter spans EVERY book - it seeds from paper_positions
        # with no user filter - so with three books holding ~10
        # positions each it sat permanently at 14/14 and vetoed the
        # whole platform's entries: 516 "Open-signal cap reached (14)"
        # vetoes on 08-20 alone, while no single book was near ITS cap.
        # A platform-wide count judged against one book's setting is a
        # category error. The cap now lives at the fan-out, where each
        # book is counted by name (trade_execution._book_open_tickers)
        # against its own max_open_positions. Here the crossing is only
        # NOTED - with the rotation hint kept, since "which weakest
        # position frees a slot" is still useful on the dashboard.
        if _coin_u not in self._recent_approvals and len(self._recent_approvals) >= max_open:
            try:
                rotation_hint = await _find_rotation_candidate(
                    message.payload.get("user_id"), tcs,
                )
                note = AgentMessage(
                    agent=self.name, kind="info", confidence=0.3,
                    payload={
                        "ticker": ticker,
                        "event": "platform_signal_pressure",
                        "note": (f"{len(self._recent_approvals)} tickers "
                                 f"approved-and-open across all books - "
                                 f"per-book caps decide at the fan-out"),
                        **({"rotation_candidate": rotation_hint}
                           if rotation_hint else {}),
                    })
                # advisory only - the signal continues to the gates below
                _pressure_note = [note]
            except Exception:  # noqa: BLE001
                _pressure_note = []
        else:
            _pressure_note = []

        # PER-BOOK kill-switches + weekly RECOVERY (Mike 2026-08-27:
        # "the agents are not treating each book as their own book").
        # The old shape here was two platform-wide vetoes — ANY user in
        # daily drawdown paused all signals, and check_all's single
        # verdict let one book's tripped weekly limit freeze all three
        # (2026-08-27: primary at -8.0% vetoed 1,162 signals while the
        # 25k/-1.6% and 75k/-2.7% books were healthy). Now: a signal is
        # vetoed only when NO book can take it. Hard halts (daily /
        # streak / session) block their book; a weekly trip puts its
        # book in RECOVERY (speculative lanes suspended, half size,
        # tighter stops — enforced per book at the execution fan-out).
        # When every eligible book is recovering, the conviction bar
        # rises by RECOVERY_TCS_BUMP here as well.
        recovery_bump = 0
        recovery_reason = ""
        try:
            from app.paper.killswitch import (
                RECOVERY_TCS_BUMP, check_states, recovery_policy)
            _states = await check_states(_supabase())
        except Exception:  # noqa: BLE001
            _states = {}
        if _states:
            _daily_over = set()
            try:
                _daily_over = await _users_in_daily_drawdown()
            except Exception:  # noqa: BLE001
                pass
            _blocked_notes: list[str] = []
            _n_recovering = 0
            _n_open = 0
            for _uid_b, _st in _states.items():
                if _st.halted and _st.mode != "recovery":
                    _blocked_notes.append(f"[{_st.scope}] {_st.reason}")
                    continue
                if _uid_b in _daily_over:
                    _blocked_notes.append("daily $ loss limit (user setting)")
                    continue
                if _st.mode == "recovery":
                    if recovery_policy(strategy) == "suspend":
                        _blocked_notes.append(
                            f"recovery suspends {strategy or 'this lane'}")
                        continue
                    _n_recovering += 1
                    continue
                _n_open += 1
            if _n_open == 0 and _n_recovering == 0:
                _why = "; ".join(sorted(set(_blocked_notes))[:3]) or "all books halted"
                return [self._veto(
                    ticker, tcs, f"Kill-switch [all books] - {_why}")]
            if _n_open == 0 and _n_recovering > 0:
                recovery_bump = int(RECOVERY_TCS_BUMP)
                recovery_reason = (f", weekly recovery +{recovery_bump} "
                                   f"({_n_recovering} book(s) working back)")

        # Market regime + symbol-quality filter (Phase 8d) - stocks only.
        # Crypto trades 24/7 and is not tied to the US equity session.
        # Read the crypto set from COIN_MAP so the ISO 20022-aligned
        # coin expansion (Mike 2026-05-31) is picked up automatically.
        from app.data.candles import COIN_MAP as _COIN_MAP
        if ticker.upper() not in _COIN_MAP and not _is_forex:
            from app.strategies.market_filter import (
                get_market_bias, direction_blocked, liquidity_check,
                overextension_check, spread_quality_check,
            )
            from app.data.candles import fetch_candles_for
            side = "long" if direction == "bullish" else "short"
            blocked = direction_blocked(await get_market_bias(), side)
            if blocked:
                return [self._veto(ticker, tcs, blocked)]
            stock_candles = await fetch_candles_for(ticker, "stock")
            liq = liquidity_check(stock_candles, strategy=strategy)
            if liq:
                # Strategy reattribution (Mike 2026-06-12, mem0 72c35e29:
                # YMAT TCS 670 died on the $5 DEFAULT floor because its
                # strategy tag was 'unknown' -- but STMS's $1 lane fits a
                # $1.23 small-cap momentum name perfectly). When a high-
                # TCS signal fails ITS floor, name the lanes that WOULD
                # take it, carry them in the veto payload, and preserve
                # the case in Mem0 (kind=decision, action=
                # veto_reattribution_candidate -- deliberately NOT
                # filtered as routine noise) so pattern recognition can
                # learn which mislabeled setups keep recurring. The veto
                # itself stands: per Mike's capital-safety directive,
                # out-of-parameter trades prove themselves in the lab
                # first, not with live capital.
                fits = []
                try:
                    from app.strategies.market_filter import profiles_accepting
                    fits = [s for s in profiles_accepting(stock_candles)
                            if s != (strategy or "").lower()]
                except Exception:  # noqa: BLE001
                    fits = []
                if fits and tcs >= 600:
                    try:
                        mem = get_memory()
                        if mem.available:
                            asyncio.create_task(asyncio.to_thread(
                                mem.log_decision,
                                AgentDecision(
                                    agent="risk_manager",
                                    action="veto_reattribution_candidate",
                                    ticker=ticker,
                                    reasoning=(
                                        f"{liq} -- but profiles "
                                        f"{fits} would accept this "
                                        f"symbol. High TCS ({tcs}) with a "
                                        f"'{strategy}' label suggests the "
                                        f"signal belongs in another lane; "
                                        f"candidate for relabeling or a "
                                        f"new strategy definition."
                                    ),
                                    metadata={
                                        "tcs": int(tcs),
                                        "strategy": strategy or "unknown",
                                        "reattribution_candidates": fits,
                                        "price": float(stock_candles[-1].close) if stock_candles else None,
                                        "user_id": message.payload.get("user_id") or "global",
                                    },
                                ),
                            ))
                    except Exception:  # noqa: BLE001
                        pass
                v = self._veto(ticker, tcs, liq, strategy=strategy,
                               user_id=message.payload.get("user_id"))
                if fits:
                    v.payload["reattribution_candidates"] = fits
                return [v]
            ext = overextension_check(stock_candles)
            if ext:
                return [self._veto(ticker, tcs, ext)]
            spread = await spread_quality_check(ticker)
            if spread:
                return [self._veto(ticker, tcs, spread)]
        else:
            # Per-coin daily loss limit (QW6) - crypto only. Benches a
            # single coin without halting the rest of the book.
            from app.paper.killswitch import coin_loss_halt
            coin_veto = await coin_loss_halt(
                _supabase(), ticker, message.payload.get("user_id"))
            if coin_veto:
                return [self._veto(ticker, tcs, coin_veto)]

        import time as _apt
        self._recent_approvals[ticker.upper()] = _apt.time()
        # Patched 2026-06-05 (Task #47): propagate user_id into the
        # approve payload so persistence + trace panel can attribute
        # per-user instead of falling through to NULL.
        approve_payload: dict = {
            "user_id": message.payload.get("user_id"),
            "asset_type": message.payload.get("asset_type"),
            "ticker": ticker,
            "direction": direction,
            "tcs": tcs,
            "position_pct": self.DEFAULT_PCT_OF_ACCOUNT,
            "strategy": strategy,
            "reason": f"TCS {tcs} clears threshold; {direction} bias [{strategy}]",
            "accumulation": accumulation_add,
        }
        if crowding_bump_v:
            approve_payload["crowding_bump"] = crowding_bump_v
            approve_payload["reason"] += (
                f"; cleared a +{crowding_bump_v} crowding bar")
        if leverage_bump:
            # Ledger-separable: leveraged entries carry the tag so the
            # outcome loop can judge leverage on its own record.
            approve_payload["leveraged"] = True
            approve_payload["reason"] += (
                f"; margin territory, bar was +{leverage_bump}")
        if probation_bump:
            approve_payload["size_scale"] = 0.5
            approve_payload["reason"] += (
                f"; probation: bar +10, HALF size [{scope.regime}]")
        # Adaptive Scope can tighten stops in rougher regimes.
        if stop_pct is not None:
            tightened = round(float(stop_pct) * scope.stop_multiplier, 4)
            approve_payload["stop_pct"] = tightened
            if scope.stop_multiplier < 1.0:
                approve_payload["stop_adjusted"] = True
                approve_payload["reason"] += f"; stop tightened x{scope.stop_multiplier} [{scope.regime}]"
        if target_pct is not None:
            approve_payload["target_pct"] = target_pct

        # Market-cap tier formulas (2026-07-02): the LAST formula step.
        # Megas trade tight + quick (scalp-friendly); micros get room and
        # the risk math sizes them smaller via the wider stop. Fail-open.
        if not _is_crypto:
            try:
                from app.strategies.cap_tiers import (
                    tier_for, adjust_stop_target,
                )
                _tier = await tier_for(ticker)
                # Scalp lane (2026-07-02): reserved for liquid mega/large
                # names; everything else is vetoed before it takes a slot.
                if str(strategy or "").lower() == "scalp":
                    from app.strategies.cap_tiers import scalp_ok as _scalp_ok
                    if not _scalp_ok(_tier):
                        return [self._veto(
                            ticker, tcs,
                            f"Scalp gate: {_tier or 'unknown'}-cap name - "
                            f"scalps are reserved for liquid mega/large caps",
                            strategy=strategy,
                            user_id=message.payload.get("user_id"),
                        )]
                _s0 = approve_payload.get("stop_pct")
                _t0 = approve_payload.get("target_pct")
                # Pattern/default signals carry no stop/target -- they used
                # to pick up RAW bot defaults later at execution and skip
                # the formula layer entirely. Fill them here so EVERY trade
                # gets tier + realism scaling (2026-07-02).
                if _s0 is None:
                    _s0 = float(getattr(cfg, "default_stop_pct", 0.05) or 0.05)
                if _t0 is None:
                    _t0 = float(getattr(cfg, "default_target_pct", 0.10) or 0.10)
                _s1, _t1 = adjust_stop_target(_tier, _s0, _t0)
                if _s1 is not None:
                    approve_payload["stop_pct"] = _s1
                if _t1 is not None:
                    approve_payload["target_pct"] = _t1
                approve_payload["cap_tier"] = _tier
                # Realistic-move target (Mike 2026-07-02): on an idle tape
                # a big defined target is "waiting money" -- the position
                # barcodes between green and red and never fills. Cap the
                # target at what the name ACTUALLY moves (1.5x its 14-day
                # ATR%), floored above round-trip costs, so quick real
                # profits get banked instead of waited on. Tunables:
                # TREZO_TARGET_ATR_MULT / TREZO_TARGET_MIN_PCT.
                try:
                    from app.strategies.market_filter import atr as _atr_fn
                    if stock_candles and len(stock_candles) >= 15:
                        _last_close = float(stock_candles[-1].close)
                        _atr_abs = float(_atr_fn(stock_candles) or 0.0)
                        _atr_pct = (_atr_abs / _last_close) if _last_close > 0 else 0.0
                        # Scalp geometry (2026-07-02): the scalp lane IS
                        # the ATR -- stop 0.8x, target 1.0x the daily range.
                        if _atr_pct > 0 and str(strategy or "").lower() == "scalp":
                            approve_payload["stop_pct"] = round(
                                max(0.004, 0.8 * _atr_pct), 4)
                            approve_payload["target_pct"] = round(
                                max(0.006, 1.0 * _atr_pct), 4)
                        _t_cur = approve_payload.get("target_pct")
                        if _atr_pct > 0 and _t_cur is not None:
                            _mult = float(os.getenv("TREZO_TARGET_ATR_MULT", "1.5"))
                            _floor = float(os.getenv("TREZO_TARGET_MIN_PCT", "0.006"))
                            _cap = max(_floor, round(_mult * _atr_pct, 4))
                            # Learned-target calibration (Mike 2026-07-08):
                            # if the lane's trades have only been REACHING
                            # ~2% lately, stop asking for 10% -- cap the
                            # target at the recent median achieved move and
                            # test the strategy at the number it earns.
                            _lrn_n = 0
                            try:
                                from app.learning.target_calibration import (
                                    achieved_move_pct,
                                )
                                _lrn, _lrn_n = await achieved_move_pct(
                                    str(strategy or ""), "stock",
                                    message.payload.get("user_id"))
                                if _lrn:
                                    _lmult = float(os.getenv(
                                        "TREZO_LEARNED_TARGET_MULT", "1.0"))
                                    _cap = max(_floor,
                                               min(_cap,
                                                   round(_lrn * _lmult, 4)))
                            except Exception:  # noqa: BLE001
                                _lrn = None
                            if float(_t_cur) > _cap:
                                approve_payload["target_pct"] = _cap
                                approve_payload["target_realism"] = True
                                approve_payload["reason"] += (
                                    f"; realistic target {_cap * 100:.1f}%"
                                    f" (ATR {_atr_pct * 100:.1f}%"
                                    + (f", learned from {_lrn_n} recent trades"
                                       if _lrn_n else "") + ")")
                                # R:R consistency (2026-07-06): a realistic
                                # target NEEDS a proportionate stop, or the
                                # sizing floor (min_reward_risk) rejects the
                                # trade -- found live: EVERY approval since
                                # 7/2 died at "Reward:risk 0.9 below 1.5".
                                # Tight target -> tight stop is Mike's
                                # geometry anyway; floor at 0.5x ATR so
                                # daily noise cannot wick it out.
                                try:
                                    _rr = float(getattr(cfg, "min_reward_risk", 1.5) or 1.5)
                                    _s_cur = approve_payload.get("stop_pct")
                                    _s_need = round(_cap / max(_rr, 0.1), 4)
                                    if _s_cur is None or float(_s_cur) > _s_need:
                                        _s_new = max(_s_need,
                                                     round(0.5 * _atr_pct, 4),
                                                     0.004)
                                        approve_payload["stop_pct"] = _s_new
                                        approve_payload["reason"] += (
                                            f"; stop {_s_new * 100:.1f}% keeps "
                                            f"R:R >= {_rr:g}")
                                except Exception:  # noqa: BLE001
                                    pass
                                try:
                                    from app.agents.activity_log import record as _arec
                                    _arec("realistic_target", ticker,
                                          strategy=strategy,
                                          reason=(f"idle-tape realism: target "
                                                  f"{float(_t_cur) * 100:.1f}% -> "
                                                  f"{_cap * 100:.1f}% "
                                                  f"({_mult}x ATR {_atr_pct * 100:.2f}%)"),
                                          extra={"user_id": message.payload.get("user_id")
                                                 or "global", "cap_tier": _tier})
                                except Exception:  # noqa: BLE001
                                    pass
                except Exception:  # noqa: BLE001
                    pass
                if _tier != "unknown" and (_s1 != _s0 or _t1 != _t0):
                    approve_payload["reason"] += f"; {_tier}-cap formulas"
                    try:
                        from app.agents.activity_log import record as _arec
                        _arec("cap_tier_adjust", ticker, strategy=strategy,
                              reason=(f"{_tier}-cap: stop {_s0} -> {_s1}, "
                                      f"target {_t0} -> {_t1}"),
                              extra={"user_id": message.payload.get("user_id")
                                     or "global"})
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass

        # Global R:R harmonizer (2026-07-08): whichever layer compressed
        # the target -- tier multiplier, ATR realism, learned calibration --
        # the stop must follow, or sizing's reward:risk floor silently
        # rejects the trade (the 7/6 lesson, now enforced on EVERY path).
        if not _is_crypto:
            try:
                _sf = approve_payload.get("stop_pct")
                _tf = approve_payload.get("target_pct")
                if _sf and _tf and float(_sf) > 0:
                    _rrf = float(getattr(cfg, "min_reward_risk", 1.5) or 1.5)
                    if float(_tf) / float(_sf) < _rrf:
                        _new_s = max(round(float(_tf) / max(_rrf, 0.1), 4),
                                     0.004)
                        if _new_s < float(_sf):
                            approve_payload["stop_pct"] = _new_s
                            approve_payload["reason"] += (
                                f"; stop {_new_s * 100:.1f}% keeps "
                                f"R:R >= {_rrf:g}")
            except Exception:  # noqa: BLE001
                pass

        # Path beta: hopeful-bucket cap enforcement. If this signal is
        # a hopeful-bucket strategy and the user is already at or above
        # their cap, veto - we don't want to push their hopeful
        # allocation past the limit. Best-effort: any failure passes
        # through (we'd rather approve than freeze).
        if is_hopeful(strategy):
            try:
                client = _supabase()
                user_id_str = message.payload.get("user_id")
                if client and user_id_str:
                    cap = hopeful_cap_for_user(user_id_str)
                    current = await hopeful_allocation_pct(client, user_id_str)
                    if cap > 0 and current >= cap:
                        return [self._veto(
                            ticker, tcs,
                            f"Hopeful bucket cap hit "
                            f"({current*100:.1f}% >= {cap*100:.1f}%) - "
                            f"skip until existing hopeful positions close.",
                            strategy=strategy, user_id=user_id_str,
                        )]
            except Exception:  # noqa: BLE001
                pass

        # Phase E: surface a tiny summary of similar past
        # situations so downstream (UI, TradeExecution) can render
        # "11 similar setups; 7 won, 4 lost" context. Best-effort.
        # Patched 2026-06-04 for async Mem0 calls - the sync version
        # of this call was blocking the event loop when Mem0 was slow.
        # Now runs on a worker thread; we await it so we keep the
        # return value but other handlers can run during the wait.
        try:
            recall = await asyncio.to_thread(
                lambda: recall_decision_context(
                    ticker=ticker, strategy=strategy,
                    extra_query=f"tcs {tcs} {direction}",
                ),
            )
            if recall.get("available"):
                approve_payload["learning_context"] = recall
        except Exception:  # noqa: BLE001
            pass

        # Log the approval to Mem0. Patched 2026-06-04 for async safety:
        # the Mem0 SDK's .add() is sync; calling it from on_message blocked
        # the FastAPI event loop when Mem0 was slow, killing the whole bot.
        # Now fire-and-forget on a worker thread. We lose the immediate
        # memory_id linkage (Task #47 will rework that tomorrow), but the
        # log record still lands and the bot keeps trading.
        try:
            mem = get_memory()
            if mem.available:
                # Task #47 fix (2026-06-12): Mem0 v3 adds are async (no
                # memory id in the response), so generate OUR OWN
                # correlation key BEFORE the fire-and-forget write and
                # carry it through approve_payload -> source_payload ->
                # TradeOutcome.related_decisions. The decision and its
                # outcome share the key in metadata; recall correlates
                # on it without needing Mem0's internal ids.
                import uuid as _uuid
                _decision_key = _uuid.uuid4().hex
                approve_payload["risk_manager_memory_id"] = _decision_key
                asyncio.create_task(asyncio.to_thread(
                    mem.log_decision,
                    AgentDecision(
                        agent="risk_manager",
                        action="approve",
                        ticker=ticker,
                        reasoning=approve_payload["reason"],
                        metadata={
                            "decision_key": _decision_key,
                            "tcs": int(tcs),
                            "strategy": strategy,
                            "direction": direction,
                            "user_id": message.payload.get("user_id") or "global",
                            "stop_pct": approve_payload.get("stop_pct"),
                            "target_pct": approve_payload.get("target_pct"),
                        },
                    ),
                ))
        except Exception:
            pass

        # Coverage tag (Mike 2026-07-02): in coverage mode, a strategy's
        # FIRST-EVER trade is marked so the pocket gate lets a small
        # labeled test position through -- one per strategy.
        if _coverage_on:
            try:
                client_cov = _supabase()
                if client_cov is not None:
                    import asyncio as _aio

                    def _qcov():
                        return (client_cov.table("paper_positions")
                                .select("id")
                                .eq("user_id", message.payload.get("user_id"))
                                .eq("strategy", strategy)
                                .limit(1).execute())
                    _had = (await _aio.to_thread(_qcov)).data or []
                    if not _had:
                        approve_payload["coverage_trade"] = True
                        approve_payload["reason"] += (
                            f"; coverage: first live {strategy} trade")
                        try:
                            from app.agents.activity_log import record as _arec
                            _arec("coverage_trade", ticker, tcs=int(tcs),
                                  strategy=strategy,
                                  reason=(f"first live {strategy} trade -- "
                                          f"small labeled test position"),
                                  extra={"user_id": message.payload.get("user_id")
                                         or "global"})
                        except Exception:  # noqa: BLE001
                            pass
            except Exception:  # noqa: BLE001
                pass

        # Trade thesis (Mike 2026-07-02): every approval carries its own
        # breakdown -- WHY it was taken, WHAT the exit watches, and the
        # plan BOTH ways. Persists on the position row (source_payload)
        # and prints one activity-log line.
        try:
            _sp_pct = float(approve_payload.get("stop_pct") or 0) * 100
            _tp_pct = float(approve_payload.get("target_pct") or 0) * 100
            _tier_t = approve_payload.get("cap_tier") or "untiered"
            _pat_t = (message.payload.get("dominant_pattern")
                      or (message.payload.get("crypto_signal") or {}).get("reason")
                      or "")
            _sname = str(strategy or "signal")
            _fast_t = _sname.startswith(("scalp", "orb", "stms"))
            approve_payload["thesis"] = {
                "why": (f"{_sname} fired {direction} at TCS {tcs}"
                        + (f" on {_pat_t}" if _pat_t else "")
                        + f"; {_tier_t}-cap formulas sized the geometry"),
                "exit_watch": (
                    f"target +{_tp_pct:.1f}%, stop -{_sp_pct:.1f}%"
                    + ("; intraday rules: 90-min max hold, 3:45 ET force-exit, "
                       "75-min stagnation exit" if _fast_t
                       else "; hourly re-score guards the thesis")),
                "if_with_us": ("profit-step ladder banks 50% of what's left at "
                               "60/80/100% of the run; the trail locks the rest; "
                               "never round-trip a green trade"),
                "if_against_us": (f"hard stop -{_sp_pct:.1f}% caps the loss; "
                                  "hourly TCS re-score rotates out early if the "
                                  "setup collapses; daily kill-switch caps the "
                                  "book at -3%"),
            }
            # Playbook grounding (Mike 2026-07-13): one cited line from
            # the local knowledge library so the trade carries the craft
            # from Mike's books, not just the math. Local search, no cost.
            try:
                from app.knowledge.library import search as _ksearch
                _khits = _ksearch(
                    f"{_sname} {direction} {_pat_t} entry exit risk stop",
                    k=1)
                if _khits:
                    _kh = _khits[0]
                    approve_payload["thesis"]["playbook_note"] = (
                        f"{_kh['source']} (p.{_kh['page']}): "
                        + _kh["text"][:180])
            except Exception:  # noqa: BLE001
                pass
            try:
                from app.agents.activity_log import record as _arec
                _arec("thesis", ticker, tcs=int(tcs), strategy=strategy,
                      reason=(approve_payload["thesis"]["why"] + " | exit: "
                              + approve_payload["thesis"]["exit_watch"])[:220],
                      extra={"user_id": message.payload.get("user_id")
                             or "global"})
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass

        # Visibility pack (2026-07-01): approvals in the activity log too.
        try:
            from app.agents.activity_log import record as _arec
            _arec("approve", str(approve_payload.get("ticker") or "?"),
                  tcs=int(tcs), strategy=approve_payload.get("strategy"),
                  reason="cleared all gates",
                  extra={"user_id": approve_payload.get("user_id") or "global",
                         "direction": approve_payload.get("direction")})
        except Exception:  # noqa: BLE001
            pass
        return _pressure_note + [
            AgentMessage(
                agent=self.name,
                kind="approve",
                confidence=tcs / 100.0,
                payload=approve_payload,
            )
        ]

    def _veto(self, ticker: str, tcs: int, reason: str,
              strategy: str | None = None,
              user_id: str | None = None) -> AgentMessage:
        # Log the veto to Mem0 so future-self can query "did I veto this
        # kind of setup before, and was I right?". Best-effort: failure
        # in the memory layer must NEVER break the trading decision.
        #
        # 2026-06-11 quota guard: routine filter vetoes (neutral bias,
        # liquidity, staleness, dedup, wide spread) fired ~120x/day and
        # burned the ENTIRE 10k/month Mem0 ADD quota on noise -- writes
        # 429'd from mid-June. Only decision-quality vetoes are worth
        # remembering; the routine ones carry no learning signal.
        _ROUTINE_VETO_MARKERS = (
            "Neutral direction",
            "Liquidity filter",
            "Stale signal",
            "Already approved",
            "bid/ask spread",
        )
        _is_routine = any(k in reason for k in _ROUTINE_VETO_MARKERS)
        try:
            mem = get_memory()
            if mem.available and not _is_routine:
                # Patched 2026-06-04: fire-and-forget on worker thread.
                # Sync Mem0 calls block the event loop when Mem0 is slow.
                # Batch digest (2026-07-02): vetoes ride the token-lean
                # digest buffer -- one combined Mem0 add per window instead
                # of one API call per veto. Full reason is in the local
                # activity log already.
                asyncio.create_task(asyncio.to_thread(
                    mem.queue_note, "risk_manager",
                    f"v tcs{int(tcs)} {strategy or '?'}: {reason[:90]}",
                    ticker,
                ))
        except Exception:
            pass  # memory failure cannot block a veto
        # Visibility pack (2026-07-01): EVERY veto lands in the local
        # activity log, including the routine ones Mem0 skips. File-append
        # only; never raises, never blocks the decision.
        # 2026-07-07: kill-switch vetoes THROTTLED to one log line per 10
        # minutes -- a session halt vetoes every signal all day (4,091
        # identical lines drowned the feed). The VETO still applies.
        try:
            _log_it = True
            if reason.startswith("Kill-switch"):
                import time as _t
                global _LAST_KS_LOG
                if (_t.time() - _LAST_KS_LOG) < 600.0:
                    _log_it = False
                else:
                    _LAST_KS_LOG = _t.time()
            if _log_it:
                from app.agents.activity_log import record as _arec
                _arec("veto", ticker, tcs=int(tcs), strategy=strategy,
                      reason=reason, extra={"user_id": user_id or "global"})
        except Exception:  # noqa: BLE001
            pass
        # Patched 2026-06-05 (Task #47): include user_id so vetoes are
        # per-user attributable in the audit trail.
        return AgentMessage(
            agent=self.name,
            kind="veto",
            confidence=1.0,
            payload={
                "ticker": ticker,
                "tcs": tcs,
                "reason": reason,
                "user_id": user_id,
                "strategy": strategy or "unknown",
            },
        )
