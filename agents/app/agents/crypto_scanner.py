"""Crypto Scanner Agent.

Runs 24/7 (crypto never closes). Ticks every 60 seconds. For XRP/ETH/SOL:
  - Fetches recent OHLC candles (CoinGecko)
  - Runs SCALP/SWING/DCA mode detection
  - If a mode triggers, computes a Trade Confidence Score and emits a
    `signal` carrying the mode + mode-specific stop_pct/target_pct

The signal flows through Risk Manager → Trade Execution → paper engine
exactly like STMS, but tagged `strategy="crypto_<mode>"`.
"""

from __future__ import annotations

from app.data.candles import fetch_candles_for
from app.patterns.scoring import calculate_score, MarketContext
from app.strategies.crypto import CRYPTO_WATCHLIST, detect_mode, indicators

from .base import Agent, AgentMessage


class CryptoScannerAgent(Agent):
    name = "crypto_scanner"
    tick_interval_seconds = 180  # Throttled 2026-06-05 (was 60) to cut API load

    # Crypto signals can be acted on with a slightly lower TCS bar than
    # stocks — the per-coin stops are tighter. Still gated by Risk Manager.
    MIN_TCS = 65   # 0-100 scale

    _last_hb: float = 0.0

    async def tick(self) -> list[AgentMessage]:
        from app.runtime.settings import (
            lane_enabled_any, min_tcs_floor_across_books,
        )
        # Honor the Bot Tuning TCS slider. Crypto stays slightly under
        # the stock floor (per-coin stops are tighter) so if the user
        # sets a stock floor of 50, crypto effectively runs at 50 too.
        # BI-03: a bare get_bot_settings() is the PRIMARY book's opinion;
        # this scanner feeds every book. Emit at the LOWEST enabled
        # book's floor and run while ANY book has the lane on -- the
        # fan-out prunes per book (book_gate.min_tcs_for).
        tcs_floor = int(min_tcs_floor_across_books() or self.MIN_TCS)
        # Crypto floor via Settings (Mike 2026-07-23: "lower it to 35
        # and see what the agents do" -- his frame: crypto = stocks,
        # just more liquid; tighter per-coin stops justify the lower
        # bar). NOTE the earlier os.getenv coverage read never saw
        # agents/.env (this app loads .env through pydantic Settings
        # ONLY), which is why scan details kept showing floor 50.
        # The Risk Manager applies the same floor for crypto_*; the
        # fee-aware edge gate still judges every entry.
        try:
            from app.config import get_settings as _gs_cf
            tcs_floor = min(tcs_floor, int(getattr(
                _gs_cf(), "trezo_crypto_tcs_floor", 35)))
        except Exception:  # noqa: BLE001
            pass
        if not lane_enabled_any("crypto_enabled"):
            # Patched 2026-06-05: surface clearly so Mike can spot it
            # in the trace panel. If Bot Tuning has crypto_enabled=False
            # on EVERY book (default for new users), this is why no
            # crypto signals ever fire even though the scanner is alive.
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={
                    "note": "Crypto strategy DISABLED in Bot Tuning. Toggle 'crypto_enabled' ON in /dashboard/settings/bot to enable XRP/ETH/SOL scanning.",
                    "fix": "Bot Tuning settings -> Strategies -> Crypto: ON",
                },
            )]

        out: list[AgentMessage] = []

        # Agent-driven universe expander (Mike 2026-07-23: "crypto =
        # stocks, just more liquid"). Throttled inside (default 6h);
        # the first tick after a restart also re-hydrates pair/param
        # registries for previously discovered coins. Discovery only
        # decides what gets LOOKED AT -- every gate still applies.
        _disc: dict = {}
        try:
            from app.data.crypto_discovery import run_discovery
            _disc = await run_discovery()
        except Exception:  # noqa: BLE001
            _disc = {}
        if _disc.get("added") or _disc.get("removed"):
            out.append(AgentMessage(
                agent=self.name, kind="info",
                payload={
                    "event": "crypto_universe_update",
                    "added": _disc.get("added") or [],
                    "removed": _disc.get("removed") or [],
                    "note": (
                        "Crypto universe updated by the expander: "
                        f"+[{','.join(_disc.get('added') or []) or 'none'}] "
                        f"-[{','.join(_disc.get('removed') or []) or 'none'}] "
                        "(conditions: USD spot at Kraken, 24h notional >= "
                        "floor, real range; retire under half-floor)"),
                }))

        scanned = 0
        triggered = 0
        detail: list[dict] = []  # per-coin why-it-did/didn't-fire (observability)

        try:
            import asyncio as _aio_u
            from app.strategies.crypto import get_crypto_universe
            _universe = await _aio_u.to_thread(get_crypto_universe)
        except Exception:  # noqa: BLE001
            _universe = list(CRYPTO_WATCHLIST)
        for coin in _universe:
            try:
                candles = await fetch_candles_for(coin, "crypto")
                if not candles:
                    detail.append({"ticker": coin, "result": "no_data"})
                    continue
                scanned += 1

                ind = indicators(candles)
                sig = detect_mode(coin, candles)
                if not sig:
                    detail.append({"ticker": coin, "result": "no_setup", **ind})
                    continue

                score = calculate_score(candles, MarketContext(), strategy=f"crypto_{sig.mode}")
                if score.tcs < tcs_floor:
                    detail.append({"ticker": coin, "result": "low_tcs",
                                   "mode": sig.mode, "tcs": score.tcs,
                                   "tcs_floor": tcs_floor, **ind})
                    continue

                triggered += 1
                detail.append({"ticker": coin, "result": "FIRED",
                               "mode": sig.mode, "tcs": score.tcs, **ind})
                out.append(AgentMessage(
                    agent=self.name,
                    kind="signal",
                    confidence=score.tcs / 100.0,
                    payload={
                        "ticker": coin,
                        "tcs": score.tcs,
                        "direction": sig.direction,
                        "strategy": f"crypto_{sig.mode}",
                        "mode": sig.mode,
                        "stop_pct": sig.stop_pct,
                        "target_pct": sig.target_pct,
                        "crypto_signal": {
                            "rsi": round(sig.rsi, 1),
                            "bb_width_pct": round(sig.bb_width_pct, 2),
                            "volume_ratio": round(sig.volume_ratio, 2),
                            "reason": sig.reason,
                        },
                    },
                ))
            except Exception as e:  # noqa: BLE001
                detail.append({"ticker": coin, "result": "error", "error": str(e)[:120]})
                out.append(AgentMessage(
                    agent=self.name, kind="error",
                    payload={"ticker": coin, "error": str(e)},
                ))

        # Hourly visibility heartbeat (2026-07-02): the crypto story in one
        # activity-log line -- crypto scans were previously invisible there.
        try:
            import time as _t
            if (_t.time() - CryptoScannerAgent._last_hb) >= 3600.0:
                CryptoScannerAgent._last_hb = _t.time()
                from app.agents.activity_log import record as _arec
                _summary = ", ".join(
                    f"{d.get('ticker')}:{d.get('result')}" for d in detail[:6])
                _arec("crypto_scan", "CRYPTO",
                      reason=f"{scanned} scanned, {triggered} fired -- {_summary}",
                      extra={"triggered": triggered})
        except Exception:  # noqa: BLE001
            pass

        # REAL COST OBSERVATION (Harris, phase 4, 2026-08-05). Trezo's cost
        # model charges a FLAT 5bps of slippage to every asset and had no
        # crypto quote function at all, so the actual spread was never
        # measured -- while the scalp lane's exit is set by exactly that
        # modelled number. This samples the live spread on the coins that
        # fired and records what a round trip really costs. Observation
        # only: it changes no decision, it just ends the guessing.
        try:
            from app.brokers.alpaca_data import get_crypto_quote
            from app.runtime.trading_costs import (
                half_spread_pct, round_trip_cost, adverse_selection_note,
            )
            from app.paper.engine import CRYPTO_COMMISSION_BPS as _FEE
            from app.agents.activity_log import record as _crec
            _fired = [d.get("ticker") for d in detail
                      if str(d.get("result") or "").upper() == "FIRED"][:4]
            for _c in _fired:
                _q = await get_crypto_quote(str(_c))
                if _q is None:
                    continue
                _hs = half_spread_pct(_q.bid, _q.ask)
                if _hs is None:
                    continue
                _cost = round_trip_cost(_FEE, half_spread=_hs)
                _crec("real_cost", str(_c), strategy="crypto",
                      reason=(f"round trip {_cost['total_pct']:.3f}% "
                              f"(fee {_cost['fee_pct']:.3f}% + spread "
                              f"{_cost['spread_pct']:.3f}%), dominated by "
                              f"{_cost['dominant']}; modelled cost is 0.620% "
                              f"flat -- {adverse_selection_note(_hs, _FEE)}")[:300],
                      extra={"bid": _q.bid, "ask": _q.ask,
                             "half_spread_pct": round(_hs * 100, 4),
                             "real_round_trip_pct": _cost["total_pct"],
                             "modelled_round_trip_pct": 0.620,
                             "dominant_cost": _cost["dominant"],
                             "observe_only": True})
        except Exception:  # noqa: BLE001
            pass
        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={
                "note": "Crypto scan complete",
                "coins_scanned": scanned,
                "modes_triggered": triggered,
                "detail": detail,
            },
        ))
        # Task #60 (2026-06-05): scanner_pulse summary emission.
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
                # EQ-10/NEQ-02: `symbols` was never defined here, so the
                # pulse always reported the signal count as "scanned".
                _scanned = scanned
                out.append(AgentMessage(
                    agent=self.name,
                    kind="scanner_pulse",
                    confidence=1.0,
                    payload={
                        "scanned": _scanned,
                        "fired": len(_signals),
                        "top_tcs": _top_tcs,
                        "by_strategy": _by_strategy,
                    },
                ))
        except Exception:
            pass

        return out
