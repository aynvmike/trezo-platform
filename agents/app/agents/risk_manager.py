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
from collections import deque

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

    def __init__(self) -> None:
        # Patched 2026-06-04 stacking fix: set, not deque(maxlen=8).
        # Old deque rotated entries silently so the cap check
        # (len() >= max_open_positions) was effectively dead, AND it
        # allowed the same ticker to appear multiple times. Result: GM
        # got approved 3x in one morning -> 84 shares on $5K equity.
        # Now a set dedupes naturally; Position Monitor calls
        # forget_ticker(t) when a position closes so re-buys ARE
        # allowed after the existing trade exits.
        self._recent_approvals: set[str] = set()
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
                    self._recent_approvals.add(t)
        except Exception:  # noqa: BLE001
            pass

    def forget_ticker(self, ticker: str) -> None:
        """Position Monitor calls this when a position closes, allowing
        a fresh approval on the same ticker. If the ticker was never in
        the set, the discard is a silent no-op."""
        self._recent_approvals.discard(ticker.upper())

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
            cycle_bump = 50
            cycle_reason = f" (earnings in {days_to_earnings}d +50)"
        elif iv_env == "earnings_day" and not cycle_aware_strategy:
            cycle_bump = 150
            cycle_reason = " (earnings TODAY +150)"

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

        # The confidence bar can be raised by the current regime posture,
        # the cycle-aware bump, and (opt-in) the per-strategy outcome nudge.
        effective_min_tcs = min_tcs + scope.tcs_bump + cycle_bump + outcome_delta
        if tcs < effective_min_tcs:
            extra = (
                f" (regime +{scope.tcs_bump}{cycle_reason}{outcome_reason})"
                if scope.tcs_bump or cycle_bump or outcome_delta
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

        if _coin_u not in self._recent_approvals and len(self._recent_approvals) >= max_open:
            # Mike 2026-06-01 capital recycling: the veto stands BUT we
            # attach a rotation hint so the user/UI can see which
            # weakest open position would free up the slot. Pure
            # advisory - we do not auto-close anything here.
            rotation_hint = await _find_rotation_candidate(
                message.payload.get("user_id"), tcs,
            )
            veto = self._veto(
                ticker, tcs,
                f"Open-signal cap reached ({max_open})",
            )
            if rotation_hint:
                veto.payload["rotation_candidate"] = rotation_hint
            return [veto]

        # Daily-drawdown gate - veto if ANY user is over their loss limit.
        drawdown = await _users_in_daily_drawdown()
        if drawdown:
            return [self._veto(
                ticker, tcs,
                f"Daily loss limit hit for {len(drawdown)} user(s) - pausing signals"
            )]

        # Safety kill-switches (Phase 8c) - daily/weekly drawdown, losing
        # streak, broker rejects. Any trip halts every new signal.
        from app.paper.killswitch import check_all as check_killswitches
        ks = await check_killswitches(_supabase())
        if ks.halted:
            return [self._veto(
                ticker, tcs, f"Kill-switch [{ks.scope}] - {ks.reason}")]

        # Market regime + symbol-quality filter (Phase 8d) - stocks only.
        # Crypto trades 24/7 and is not tied to the US equity session.
        # Read the crypto set from COIN_MAP so the ISO 20022-aligned
        # coin expansion (Mike 2026-05-31) is picked up automatically.
        from app.data.candles import COIN_MAP as _COIN_MAP
        if ticker.upper() not in _COIN_MAP:
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
            coin_veto = await coin_loss_halt(_supabase(), ticker)
            if coin_veto:
                return [self._veto(ticker, tcs, coin_veto)]

        self._recent_approvals.add(ticker.upper())
        # Patched 2026-06-05 (Task #47): propagate user_id into the
        # approve payload so persistence + trace panel can attribute
        # per-user instead of falling through to NULL.
        approve_payload: dict = {
            "user_id": message.payload.get("user_id"),
            "ticker": ticker,
            "direction": direction,
            "tcs": tcs,
            "position_pct": self.DEFAULT_PCT_OF_ACCOUNT,
            "strategy": strategy,
            "reason": f"TCS {tcs} clears threshold; {direction} bias [{strategy}]",
            "accumulation": accumulation_add,
        }
        # Adaptive Scope can tighten stops in rougher regimes.
        if stop_pct is not None:
            tightened = round(float(stop_pct) * scope.stop_multiplier, 4)
            approve_payload["stop_pct"] = tightened
            if scope.stop_multiplier < 1.0:
                approve_payload["stop_adjusted"] = True
                approve_payload["reason"] += f"; stop tightened x{scope.stop_multiplier} [{scope.regime}]"
        if target_pct is not None:
            approve_payload["target_pct"] = target_pct

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

        return [
            AgentMessage(
                agent=self.name,
                kind="approve",
                confidence=tcs / 1000.0,
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
                asyncio.create_task(asyncio.to_thread(
                    mem.log_decision,
                    AgentDecision(
                        agent="risk_manager",
                        action="veto",
                        ticker=ticker,
                        reasoning=reason,
                        metadata={
                            "tcs": int(tcs),
                            "strategy": strategy or "unknown",
                            "user_id": user_id or "global",
                        },
                    ),
                ))
        except Exception:
            pass  # memory failure cannot block a veto
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
