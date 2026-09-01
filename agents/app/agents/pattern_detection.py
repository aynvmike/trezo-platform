"""Pattern Detection Agent.

Scans each user's default watchlist for trade signals. Ticks every 60s.

Per-stock strategy selection (#121 follow-up): no single strategy suits
every stock, so for each ticker the agent scores it under every eligible
directional strategy and emits the signal under the best strategy *for
that stock* - favouring strategies proven on it in past backtests. Every
signal carries the full comparison, so the choice is auditable.

Per-user (Phase 5b / #119): it scans each user's own default watchlist
and tags every signal with that user's id, so the approve -> execute
chain runs per user. With no users or no watchlist data it falls back
to a shared founder watchlist, emitting unscoped signals as before.

Strategy-change surfacing (#124 follow-up): when the per-stock pick
flips from one strategy to another between ticks, the agent records
the switch on the next scan summary so the dashboard's Scanner Pulse
can show "AMD: pattern -> orb" inline rather than burying it in the
activity feed.

Switching friction (2026-05-29): the flip is gated on the new pick's
TCS beating the previous pick's TCS by a configurable advantage. See
`required_switch_advantage` in `app/runtime/settings.py` for the four
modes (off / fixed / adaptive / tiered). Suppressed flips emit a
`strategy_held` info message so Mike can see the friction working.
"""

from __future__ import annotations

import asyncio
import time

from .base import Agent, AgentMessage
from app.config import get_settings
from app.data.candles import fetch_candles_for, COIN_MAP
from app.patterns.scoring import MarketContext
from app.patterns.confluence import confluence_bonus
from app.strategies.selector import select_strategy, eligible_strategies
from app.strategies.stms import is_trading_window as _stms_window
from app.strategies.orb import orb_window as _orb_window
from app.strategies.extended import swing_window as _swing_window
from app.data.market_universe import expanded_scan_pool


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def _urgency_for(tcs) -> str:
    """Task #91 urgency bands on the 0-100 TCS scale.

    EQ-9: these were 700/500 -- unreachable since the 2026-07-08 move to
    0-100, so every pattern signal was tagged "low" and Risk Manager gave
    all of them the slowest staleness deadline."""
    t = int(tcs or 0)
    if t >= 70:
        return "urgent"
    if t >= 50:
        return "mixed"
    return "low"


class PatternDetectionAgent(Agent):
    name = "pattern_detection"
    tick_interval_seconds = 180  # Throttled 2026-06-05 (was 60) to cut API load
    # 2026-08-28: today's bus-visible cancellations showed this agent
    # blowing the default scheduler ceiling on a live market day
    # (cancelled 7x at 360s) — every cancelled tick discarded its signals. Honest
    # ceiling; max_instances=1 + coalesce prevent overlap.
    tick_timeout_seconds = 900

    # TCS at/above this triggers a signal.
    signal_threshold: int = 70   # 0-100 scale

    # Fallback watchlist - used only when there are no users / no
    # per-user watchlist data to scan.
    watchlist: list[str] = [
        "AMD", "INTC", "CZR", "WMT", "AMSC",
        "XRP", "ETH", "SOL"
    ]

    # Per-ticker backtest history is a slow-moving quality gate, so it is
    # refreshed only every 15 minutes rather than every tick.
    _BT_TTL = 900.0

    def __init__(self) -> None:
        self._bt_history: dict[str, dict[str, float]] = {}
        self._bt_at: float = 0.0
        # Per-(user, ticker) memory of the last chosen strategy AND
        # its TCS at the time of selection. Used to (a) surface
        # strategy-change events on the next tick, and (b) enforce
        # switching friction so a tiny TCS bump doesn't flip the
        # pick. See `required_switch_advantage` in
        # `app/runtime/settings.py` for the four modes.
        # Keyed by f"{user_id or 'global'}:{SYM}". Value: (strategy, tcs).
        self._prev_strategy: dict[str, tuple[str, int]] = {}
        # Patched 2026-06-10 (same class as WMT stacking): seed
        # _prev_strategy from today's emitted signals so restart
        # doesn't blow away strategy-switching friction state.
        self._seeded_prev_strategy: bool = False

    async def _scan_targets(self) -> list[tuple]:
        """[(user_id, [tickers])] to scan - each user's default watchlist.
        Falls back to [(None, fallback_watchlist)] when there is no
        per-user data, so the agent always has something to scan."""
        client = _supabase()
        if not client:
            return [(None, self.watchlist)]
        try:
            def _accts():
                return client.table("paper_accounts").select("user_id").execute()
            accts = await asyncio.to_thread(_accts)
            user_ids = [a["user_id"] for a in (accts.data or []) if a.get("user_id")]
            if not user_ids:
                return [(None, self.watchlist)]

            targets: list[tuple] = []
            for uid in user_ids:
                def _wl(u=uid):
                    return (client.table("watchlists").select("id")
                            .eq("user_id", u).eq("is_default", True)
                            .limit(1).execute())
                wl = await asyncio.to_thread(_wl)
                wl_rows = wl.data or []
                if not wl_rows:
                    continue

                def _items(w=wl_rows[0]["id"]):
                    return (client.table("watchlist_items").select("ticker")
                            .eq("watchlist_id", w).execute())
                items = await asyncio.to_thread(_items)
                tickers = [it["ticker"] for it in (items.data or [])
                           if it.get("ticker")]
                if tickers:
                    targets.append((uid, tickers))
            if targets:
                return targets
            # No book has narrowed itself to a watchlist. The platform
            # default is THE MARKET (Mike 2026-08-20: "the agents should
            # work with the market and not just a watchlist"), not a
            # hardcoded symbol list. Walk the same pool the Extended
            # scanner uses - watchlist seeds lead, liquid market movers
            # fill - and emit unpinned signals every book may judge.
            try:
                from app.data.market_universe import expanded_scan_pool
                pool, _info = await expanded_scan_pool(
                    list(self.watchlist), limit=60)
                if pool:
                    return [(None, list(pool))]
            except Exception:  # noqa: BLE001
                pass
            return [(None, self.watchlist)]
        except Exception:  # noqa: BLE001
            return [(None, self.watchlist)]

    async def _backtest_history(self) -> dict[str, dict[str, float]]:
        """{SYMBOL: {strategy: avg_return_pct}} from the backtest_runs log.

        This is the quality gate for strategy selection - it favours
        strategies proven on a stock and drops ones that lost on it.
        Cached for 15 minutes; it changes only when the user runs a
        backtest, so it does not need to be re-read every tick."""
        now = time.time()
        if self._bt_history and (now - self._bt_at) < self._BT_TTL:
            return self._bt_history
        client = _supabase()
        if not client:
            self._bt_at = now
            return self._bt_history
        try:
            def _q():
                return (client.table("backtest_runs")
                        .select("symbol, strategy, total_return_pct, trades")
                        .order("created_at", desc=True).limit(600).execute())
            res = await asyncio.to_thread(_q)
            rows = res.data or []
        except Exception:  # noqa: BLE001
            self._bt_at = now
            return self._bt_history

        agg: dict[str, dict[str, list]] = {}
        for r in rows:
            if (r.get("trades") or 0) <= 0:
                continue
            sym = str(r.get("symbol") or "").upper()
            if not sym:
                continue
            strat = str(r.get("strategy") or "default")
            agg.setdefault(sym, {}).setdefault(strat, []).append(
                float(r.get("total_return_pct") or 0.0))
        self._bt_history = {
            sym: {st: sum(v) / len(v) for st, v in smap.items() if v}
            for sym, smap in agg.items()
        }
        self._bt_at = now
        return self._bt_history

    async def _maybe_seed_prev_strategy(self) -> None:
        if self._seeded_prev_strategy:
            return
        self._seeded_prev_strategy = True
        try:
            from app.runtime.restart_state import seed_today_ticker_strategy_map
            mp = await seed_today_ticker_strategy_map("pattern_detection")
            # Reconstruct (strategy, tcs=0) tuples - TCS isn't tracked
            # in this map and 0 is a safe default for friction comparison.
            for ticker, strategy in mp.items():
                self._prev_strategy[ticker] = (strategy, 0)
        except Exception:
            pass

    async def tick(self) -> list[AgentMessage]:
        await self._maybe_seed_prev_strategy()
        from app.runtime.settings import (
            get_bot_settings, required_switch_advantage,
        )

        out: list[AgentMessage] = []
        candle_cache: dict[str, list] = {}

        in_stms = bool(_stms_window())
        in_orb = bool(_orb_window()[0])
        in_swing = bool(_swing_window())

        history = await self._backtest_history()

        scan_summary: dict[str, dict] = {}

        for user_id, tickers in await self._scan_targets():
            cfg = get_bot_settings(user_id)
            if not cfg.pattern_enabled:
                continue

            # Outcome-weighted selection (2026-06-16): this user's learned
            # per-strategy edge, fetched once per tick (cached 10 min). The
            # selector drops strategies the live record says to avoid and
            # tiebreaks toward proven edge. {} = no opinion (thin data).
            try:
                from app.learning.strategy_weighting import get_live_strategy_edge
                outcome_edge = await get_live_strategy_edge(user_id)
            except Exception:  # noqa: BLE001
                outcome_edge = {}

            threshold = int(cfg.tcs_threshold or self.signal_threshold)

            pool, breakdown = await expanded_scan_pool(tickers, limit=70)

            ukey = str(user_id or "global")
            summary = scan_summary.setdefault(ukey, {
                "user_id": user_id,
                "tickers_scanned": 0,
                "signals_emitted": 0,
                "max_tcs": 0,
                "max_tcs_ticker": None,
                "max_tcs_direction": "neutral",
                "threshold": threshold,
                "bullish_count": 0,
                "from_watchlist": breakdown["watchlist"],
                "from_market_wide": breakdown["market_wide"],
                "strategy_changes": [],
                "strategy_change_count": 0,
                "strategy_holds": 0,
            })

            for symbol in pool:
                try:
                    sym = symbol.upper()
                    if sym not in candle_cache:
                        candle_cache[sym] = await fetch_candles_for(symbol, "stock")
                    candles = candle_cache[sym]
                    if not candles:
                        continue
                    summary["tickers_scanned"] += 1

                    conf = confluence_bonus({
                        "recent_15": candles[-15:] if len(candles) >= 15 else candles,
                        "recent_30": candles[-30:] if len(candles) >= 30 else candles,
                        "full":      candles,
                    })
                    ctx = MarketContext(
                        confluence_bonus=float(conf["bonus"]),
                        pattern_weights=cfg.pattern_weights,
                    )

                    asset_type = "crypto" if sym in COIN_MAP else "stock"
                    # Pull cycle position here so we can feed it into
                    # eligible_strategies() - cycle-aware strategies
                    # (iv_crush_short, dividend_capture_long) ONLY
                    # appear in the pool when the symbol's cycle
                    # position matches. Cheap: 24h cached.
                    try:
                        from app.data.cycles import get_cycle_position
                        cpos_for_pool = await get_cycle_position(sym)
                        iv_env = cpos_for_pool.iv_environment
                        days_e = cpos_for_pool.days_until_earnings
                        days_d = cpos_for_pool.days_until_exdiv
                    except Exception:  # noqa: BLE001
                        iv_env = "normal"
                        days_e = None
                        days_d = None

                    pool_strats = eligible_strategies(
                        asset_type,
                        in_stms_window=in_stms,
                        in_orb_window=in_orb,
                        in_swing_window=in_swing,
                        iv_environment=iv_env,
                        days_until_earnings=days_e,
                        days_until_exdiv=days_d,
                    )

                    # Expert override: per-stock strategy pin overrides
                    # the entire eligible pool. When set, we force
                    # exactly that one strategy through select_strategy
                    # so the user's pin wins regardless of TCS / scoring.
                    try:
                        from app.runtime.overrides import get_strategy_override
                        pinned = await get_strategy_override(user_id, sym)
                        if pinned:
                            pool_strats = [pinned]
                    except Exception:  # noqa: BLE001
                        pass
                    pick = select_strategy(
                        candles, ctx=ctx,
                        history=history.get(sym, {}),
                        strategies=pool_strats,
                        outcome_edge=outcome_edge,
                    )

                    # Strategy-change detection + switching friction.
                    # See `required_switch_advantage` for the four modes.
                    prev_key = f"{ukey}:{sym}"
                    prev_pair = self._prev_strategy.get(prev_key)
                    new_tcs = int(pick.tcs)

                    if prev_pair is None:
                        # First time we see this ticker - just record.
                        self._prev_strategy[prev_key] = (pick.strategy, new_tcs)
                    else:
                        prev_strategy, prev_tcs = prev_pair
                        if prev_strategy == pick.strategy:
                            # Same strategy - refresh the TCS baseline.
                            self._prev_strategy[prev_key] = (prev_strategy, new_tcs)
                        else:
                            # Different strategy - gate on the required advantage.
                            adv = required_switch_advantage(
                                cfg.switching_mode,
                                cfg.switching_advantage_pct,
                                cfg.tcs_threshold,
                                new_tcs,
                            )
                            min_to_flip = float(prev_tcs) * (1.0 + adv)
                            if new_tcs > min_to_flip:
                                # Flip allowed - record and emit.
                                self._prev_strategy[prev_key] = (pick.strategy, new_tcs)
                                summary["strategy_change_count"] += 1
                                if len(summary["strategy_changes"]) < 8:
                                    summary["strategy_changes"].append({
                                        "ticker": sym,
                                        "from": prev_strategy,
                                        "to": pick.strategy,
                                        "tcs": new_tcs,
                                        "direction": pick.direction,
                                    })
                                ev = {
                                    "ticker": sym,
                                    "from": prev_strategy,
                                    "to": pick.strategy,
                                    "tcs": new_tcs,
                                    "direction": pick.direction,
                                    "reason": pick.reason,
                                }
                                if user_id:
                                    ev["user_id"] = user_id
                                out.append(AgentMessage(
                                    agent=self.name, kind="strategy_change",
                                    confidence=pick.tcs / 100.0, payload=ev,
                                ))
                            else:
                                # Suppressed - keep prev pick, emit a 'held' info
                                # message so Mike can see the friction working.
                                summary["strategy_holds"] += 1
                                held_ev = {
                                    "ticker": sym,
                                    "held": prev_strategy,
                                    "challenger": pick.strategy,
                                    "prev_tcs": int(prev_tcs),
                                    "challenger_tcs": new_tcs,
                                    "required_advantage_pct": round(adv * 100, 1),
                                    "mode": cfg.switching_mode,
                                }
                                if user_id:
                                    held_ev["user_id"] = user_id
                                out.append(AgentMessage(
                                    agent=self.name, kind="strategy_held",
                                    confidence=prev_tcs / 100.0, payload=held_ev,
                                ))

                    if pick.tcs > summary["max_tcs"]:
                        summary["max_tcs"] = int(pick.tcs)
                        summary["max_tcs_ticker"] = sym
                        summary["max_tcs_direction"] = pick.direction
                    if pick.direction == "bullish":
                        summary["bullish_count"] += 1

                    if pick.tcs >= threshold:
                        summary["signals_emitted"] += 1
                        # Cycle context (Phase 13a). Pull the symbol's
                        # cycle position - it's cached 24h so this is
                        # essentially free. Downstream agents (Risk
                        # Manager, Strategy Engine) can act on the
                        # cycle data without re-fetching.
                        try:
                            from app.data.cycles import get_cycle_position
                            cpos = await get_cycle_position(sym)
                            cycle_ctx = {
                                "next_earnings_days": cpos.days_until_earnings,
                                "next_exdiv_days": cpos.days_until_exdiv,
                                "iv_environment": cpos.iv_environment,
                                "earnings_time": cpos.earnings_time,
                            }
                        except Exception:  # noqa: BLE001
                            cycle_ctx = {
                                "next_earnings_days": None,
                                "next_exdiv_days": None,
                                "iv_environment": "normal",
                                "earnings_time": None,
                            }

                        payload = {
                            "ticker": symbol,
                            "tcs": pick.tcs,
                            "score": pick.score,
                            "direction": pick.direction,
                            "strategy": pick.strategy,
                            "dominant_pattern": pick.dominant_pattern,
                            "detected_patterns": pick.detected_patterns,
                            "breakdown": pick.breakdown,
                            "strategy_selection": {
                                "chosen": pick.strategy,
                                "reason": pick.reason,
                                "considered": pick.considered,
                            },
                            "cycle": cycle_ctx,
                        }
                        if user_id:
                            payload["user_id"] = user_id
                        # Task #91 (2026-06-05): tag urgency for tiered
                        # staleness in Risk Manager. Mike: TCS alone is
                        # misleading; agents should learn what's actually
                        # time-sensitive. Initial rule: high TCS = urgent,
                        # mid-band = mixed, else low. Pattern.is_fresh
                        # would refine this once we plumb a freshness
                        # signal through (TODO).
                        payload["urgency"] = _urgency_for(pick.tcs)
                        out.append(AgentMessage(
                            agent=self.name, kind="signal",
                            confidence=pick.tcs / 100.0, payload=payload,
                        ))
                except Exception as e:  # noqa: BLE001
                    out.append(AgentMessage(
                        agent=self.name, kind="error",
                        payload={"ticker": symbol, "error": str(e)},
                    ))

        # End-of-tick scan summary - one per user - so the user can see
        # exactly what the scanner did and why nothing fired.
        for ukey, summary in scan_summary.items():
            wl_n = int(summary.get("from_watchlist") or 0)
            mw_n = int(summary.get("from_market_wide") or 0)
            pool_desc = f"{summary['tickers_scanned']} tickers"
            if wl_n or mw_n:
                pool_desc += f" ({wl_n} watchlist + {mw_n} market-wide)"
            note_bits = [
                f"Scanned {pool_desc} at TCS threshold {summary['threshold']}.",
            ]
            if summary["signals_emitted"] > 0:
                note_bits.append(
                    f"{summary['signals_emitted']} signal(s) fired.")
            else:
                if summary["max_tcs_ticker"]:
                    note_bits.append(
                        f"Strongest read: {summary['max_tcs_ticker']} at TCS "
                        f"{summary['max_tcs']} ({summary['max_tcs_direction']}) - "
                        f"below threshold, nothing fired.")
                else:
                    note_bits.append("No tickers produced a scoring read this tick.")
            sc_count = int(summary.get("strategy_change_count") or 0)
            sh_count = int(summary.get("strategy_holds") or 0)
            if sc_count:
                note_bits.append(
                    f"Strategy Engine flipped pick on {sc_count} ticker(s) this tick.")
            if sh_count:
                note_bits.append(
                    f"Friction held {sh_count} challenger(s) (insufficient TCS advantage).")
            payload = {
                "note": " ".join(note_bits),
                "tickers_scanned": summary["tickers_scanned"],
                "signals": summary["signals_emitted"],
                "max_tcs": summary["max_tcs"],
                "max_tcs_ticker": summary["max_tcs_ticker"],
                "max_tcs_direction": summary["max_tcs_direction"],
                "threshold": summary["threshold"],
                "bullish_count": summary["bullish_count"],
                "from_watchlist": wl_n,
                "from_market_wide": mw_n,
                "strategy_changes": summary["strategy_changes"],
                "strategy_change_count": sc_count,
                "strategy_holds": sh_count,
            }
            if summary["user_id"]:
                payload["user_id"] = summary["user_id"]
            out.append(AgentMessage(
                agent=self.name, kind="info", payload=payload))

        # Task #60 (2026-06-05): emit a single scanner_pulse summary.
        # Replaces N signal rows in agent_messages with 1 summary row -
        # trace panel reads this for the "X SIGNAL" counter without
        # paying for per-signal storage.
        try:
            _signals = [m for m in out if getattr(m, "kind", None) == "signal"]
            if _signals:
                _tcss = []
                for s in _signals:
                    t = (s.payload or {}).get("tcs")
                    if isinstance(t, (int, float)):
                        _tcss.append(int(t))
                _top_tcs = max(_tcss) if _tcss else 0
                _by_strategy = {}
                for s in _signals:
                    st = (s.payload or {}).get("strategy") or "default"
                    _by_strategy[st] = _by_strategy.get(st, 0) + 1
                out.append(AgentMessage(
                    agent=self.name,
                    kind="scanner_pulse",
                    confidence=1.0,
                    payload={
                        # EQ-10/NEQ-02: `symbols` never existed in this
                        # scope, so the pulse always reported 0 scanned.
                        "scanned": sum(int(s.get("tickers_scanned") or 0)
                                       for s in scan_summary.values()),
                        "fired": len(_signals),
                        "top_tcs": _top_tcs,
                        "by_strategy": _by_strategy,
                    },
                ))
        except Exception:
            pass

        return out
