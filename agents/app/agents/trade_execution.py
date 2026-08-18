"""Trade Execution Agent.

Subscribes to `approve` messages from Risk Manager. For each approval:
  - Fetches the current market price
  - Applies the capital-allocation gate (Phase 8a.2): a trade is capped by
    the remaining dollar budget for its market type, and skipped entirely
    if that budget is used up
  - Routes the trade:
      * STOCK + Alpaca configured  -> a bracket order on Alpaca paper
      * crypto, or Alpaca not set  -> Trezo's internal paper engine
  - Emits an `execute` message with the fill details

Phase 8a.2: the per-market-type budgets come from the account posture
(growth / balanced / income) the AI picks from account size. Until the
override UI ships, posture is always the AI default ('auto').
"""

from __future__ import annotations

from app.data.candles import fetch_candles_for
from app.paper.engine import open_position
from app.runtime.trading_mode import get_trading_mode

from .base import Agent, AgentMessage

# Single source of truth for "is this ticker a crypto?" 2026-06-13:
# was a hardcoded 4-symbol set, which misclassified the ISO 20022
# coins (XLM/HBAR/ALGO/IOTA/QNT/XDC/XYO) as STOCKS -> they were routed
# to Alpaca's stock path instead of the modeled crypto engine, so the
# agents could never take a position in them. Derive from COIN_MAP
# (every symbol we have crypto price data for: majors + ISO cluster).
def _all_crypto_symbols() -> set:
    try:
        from app.data.candles import COIN_MAP
        return {s.upper() for s in COIN_MAP.keys()}
    except Exception:  # noqa: BLE001
        return {"XRP", "ETH", "SOL", "BTC"}

CRYPTO_SYMBOLS = _all_crypto_symbols()

# Priority-rotation throttle (2026-07-02): at most N weakest-hold
# rotations per day, process-local; the activity log carries each one.
_ROTATIONS_TODAY: dict = {"day": "", "n": 0}


class TradeExecutionAgent(Agent):
    name = "trade_execution"
    tick_interval_seconds = 0  # event-driven

    async def tick(self) -> list[AgentMessage]:
        return []

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        if message.kind != "approve":
            return []

        ticker = message.payload.get("ticker", "?")
        direction = message.payload.get("direction", "neutral")
        side = "long" if direction == "bullish" else "short"
        user_id = message.payload.get("user_id")

        # Auto-trade toggle (Mike 2026-06-01). When the user has flipped
        # auto_trade_enabled OFF, every signal still scored + approved
        # + recorded - but no open_position fires. The post-mortem loop
        # gets a "would_have_traded" event so learning continues even
        # in observe-only mode.
        try:
            from app.runtime.settings import get_bot_settings
            cfg = get_bot_settings(user_id)
            if not cfg.auto_trade_enabled:
                return [AgentMessage(
                    agent=self.name, kind="info", confidence=1.0,
                    payload={
                        "user_id": user_id,
                        "event": "would_have_traded",
                        "ticker": ticker,
                        "side": side,
                        "tcs": message.payload.get("tcs"),
                        "strategy": message.payload.get("strategy"),
                        "note": (
                            f"Auto-trade OFF: {ticker} {side} would have "
                            "been placed. Flip Auto-trade ON in Bot "
                            "Tuning to let the bot act."
                        ),
                    },
                )]
        except Exception:  # noqa: BLE001
            # Fail OPEN: if the settings lookup errors, default to the
            # historical behavior (trades go through). Better to trade
            # by mistake than silently freeze the bot on a transient
            # Supabase blip.
            pass

        if not user_id:
            return await self._execute_for_all_users(ticker, side, message.payload)

        # Bind THIS book's broker credentials before placing its order.
        # trade_execution already fans out across paper_accounts rows, but
        # nothing bound the account -- so every book's orders would have
        # gone to the primary Alpaca account (2026-08-09).
        from app.brokers.accounts import bind_for_user as _bind_acct
        from app.brokers.route_guard import check_route, record_mismatch
        with _bind_acct(user_id):
            _ok, _note = check_route(user_id)
            if not _ok:
                # Refuse rather than mis-route: 7 orders landed on the
                # wrong broker account on 8/10-11 with no error anywhere.
                record_mismatch(ticker, user_id, _note, "execute.single")
                return [AgentMessage(
                    agent=self.name, kind="error", confidence=1.0,
                    payload={"user_id": user_id, "ticker": ticker,
                             "error": f"route check failed: {_note}"})]
            return await self._execute_for_user(user_id, ticker, side,
                                                message.payload)

    async def _execute_for_all_users(
        self,
        ticker: str,
        side: str,
        source_payload: dict,
    ) -> list[AgentMessage]:
        """Approve message did not carry a user_id (Risk Manager does not
        currently propagate it through approve/veto payloads). Fan the
        approval out to every active paper account so per-user execution,
        budgets, and cost-basis all stay correct.

        Aggregates messages from every per-user call. If no paper_accounts
        exist (fresh install) we emit a single info row so the trace panel
        records what happened instead of silently dropping the approve.
        """
        import asyncio
        from app.runtime.persistence import _client

        client = _client()
        if client is None:
            return [AgentMessage(
                agent=self.name, kind="info", confidence=1.0,
                payload={
                    "ticker": ticker,
                    "side": side,
                    "note": "Skipped: Supabase client unavailable, cannot enumerate paper accounts",
                },
            )]

        def _fetch():
            return client.table("paper_accounts").select("user_id").execute()

        try:
            accts = await asyncio.to_thread(_fetch)
        except Exception as e:  # noqa: BLE001
            return [AgentMessage(
                agent=self.name, kind="error", confidence=1.0,
                payload={
                    "ticker": ticker,
                    "side": side,
                    "error": f"paper_accounts lookup failed: {e}",
                },
            )]

        users = [a.get("user_id") for a in (accts.data or []) if a.get("user_id")]
        if not users:
            return [AgentMessage(
                agent=self.name, kind="info", confidence=1.0,
                payload={
                    "ticker": ticker,
                    "side": side,
                    "note": "Skipped: no paper accounts exist yet",
                },
            )]

        out: list[AgentMessage] = []
        from app.brokers.accounts import bind_for_user as _bind_acct
        from app.brokers.route_guard import check_route as _check_route
        from app.brokers.route_guard import record_mismatch as _rec_mm
        for uid in users:
            try:
                # Each book's order must go to ITS OWN broker account.
                # This loop already existed -- Trezo has always fanned out
                # across paper_accounts -- but with one global credential
                # every book's orders landed on the primary (2026-08-09).
                with _bind_acct(uid):
                    _ok, _note = _check_route(uid)
                    if not _ok:
                        _rec_mm(ticker, uid, _note, "execute.fanout")
                        continue
                    msgs = await self._execute_for_user(uid, ticker, side,
                                                        source_payload)
                out.extend(msgs or [])
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(
                    agent=self.name, kind="error", confidence=1.0,
                    payload={
                        "user_id": uid,
                        "ticker": ticker,
                        "side": side,
                        "error": f"execute failed for user: {e}",
                    },
                ))
        return out

    async def _execute_for_user(
        self,
        user_id: str,
        ticker: str,
        side: str,
        source_payload: dict,
    ) -> list[AgentMessage]:
        # Forex (2026-07-02): the signal declares its own asset_type;
        # ticker-derived detection stays the fallback for stock/crypto.
        _declared = str(source_payload.get("asset_type") or "").lower()
        if _declared == "forex":
            asset_type = "forex"
        else:
            asset_type = "crypto" if ticker.upper() in CRYPTO_SYMBOLS else "stock"
        # Strategy label - prefer the field the source agent set explicitly,
        # then fall back to the richer per-pick selection metadata, then the
        # dominant detected pattern, then a generic "system" tag (never the
        # opaque "default" placeholder that the UI used to surface).
        strategy = (
            source_payload.get("strategy")
            or (source_payload.get("strategy_selection") or {}).get("chosen")
            or source_payload.get("dominant_pattern")
            or source_payload.get("source_agent")
            or "system"
        )

        candles = await fetch_candles_for(ticker, asset_type)
        if not candles:
            return [AgentMessage(
                agent=self.name, kind="error",
                payload={"user_id": user_id, "ticker": ticker, "error": "No price data"},
            )]
        market_price = float(candles[-1].close)

        stop_pct = source_payload.get("stop_pct")
        target_pct = source_payload.get("target_pct")

        from app.brokers.alpaca import alpaca_configured
        from app.brokers.alpaca import alpaca_crypto_supports
        from app.config import get_settings as _gs_for_routing
        _routing_cfg = _gs_for_routing()

        # Phase F (2026-06-04): Alpaca crypto routing. Feature-flagged
        # OFF by default - flip on with ALPACA_CRYPTO_ENABLED=true in
        # agents/.env. Symbol must also be in the allowlist; anything
        # not supported by Alpaca crypto falls through to the modeled
        # paper engine identical to today's behavior. To remove this
        # branch entirely, delete the whole if block (the rest of the
        # routing keeps working unchanged).
        if (
            asset_type == "crypto"
            and getattr(_routing_cfg, "alpaca_crypto_enabled", False)
            and alpaca_configured()
            and alpaca_crypto_supports(ticker)
        ):
            return await self._execute_alpaca_crypto(
                user_id, ticker, side, market_price,
                stop_pct, target_pct, strategy, source_payload,
            )

        # Crypto Part 2 (2026-06-13): real exchange connector (Coinbase/
        # Kraken) for the ISO coins Alpaca cannot trade. SCAFFOLD + OFF:
        # is_configured() is False until keys are added, so this never
        # fires today and crypto stays on the modeled engine. Part 3 fills
        # in crypto_exchange.submit_order and routes the full ISO list to a
        # live venue. Long-only.
        if asset_type == "crypto":
            try:
                from app.brokers.crypto_exchange import (
                    is_configured as _cx_ready,
                    exchange_supports as _cx_supports,
                )
                if _cx_ready() and _cx_supports(ticker):
                    return await self._execute_crypto_exchange(
                        user_id, ticker, side, market_price,
                        stop_pct, target_pct, strategy, source_payload,
                    )
            except Exception:  # noqa: BLE001
                pass  # connector error -> fall through to the modeled engine

        if asset_type == "stock" and alpaca_configured():
            return await self._execute_alpaca(
                user_id, ticker, side, market_price,
                stop_pct, target_pct, strategy, source_payload,
            )

        return await self._execute_internal(
            user_id, ticker, asset_type, side, market_price,
            stop_pct, target_pct, strategy, source_payload,
        )

    async def _execute_crypto_exchange(
        self, user_id, ticker, side, market_price,
        stop_pct, target_pct, strategy, source_payload,
    ) -> list[AgentMessage]:
        # Scaffold path (crypto Part 2). The connector's submit_order
        # raises NotImplementedError today; we catch it and fall back to
        # the modeled engine so flipping the flag early can never strand a
        # signal. Part 3 replaces this body with real fill handling.
        try:
            from app.brokers import crypto_exchange as _cx
            await _cx.submit_order(
                user_id=user_id, ticker=ticker, side=side,
                price=market_price, stop_pct=stop_pct, target_pct=target_pct,
            )
        except NotImplementedError:
            return await self._execute_internal(
                user_id, ticker, "crypto", side, market_price,
                stop_pct, target_pct, strategy, source_payload,
            )
        except Exception as e:  # noqa: BLE001
            return [AgentMessage(
                agent=self.name, kind="error",
                payload={"user_id": user_id, "ticker": ticker,
                         "error": f"crypto_exchange submit failed: {e}"},
            )]
        return await self._execute_internal(
            user_id, ticker, "crypto", side, market_price,
            stop_pct, target_pct, strategy, source_payload,
        )

    async def _allocation_gate(self, user_id, equity, strategy, asset_type):
        from app.paper.allocation import (
            build_allocation, deployed_capital, market_type_for,
            effective_equity,
        )
        # Pockets size from BROKER-truth equity (2026-07-02) -- the internal
        # ledger had drifted below the broker and was shrinking every pocket.
        try:
            _true_eq = await effective_equity(user_id)
            if _true_eq > 0:
                equity = _true_eq
        except Exception:  # noqa: BLE001
            pass
        from app.runtime.settings import get_bot_settings
        # Per book. Posture and allocation overrides are exactly the kind
        # of setting that must not leak between accounts (2026-08-18).
        cfg = get_bot_settings(user_id)
        mt = market_type_for(strategy, asset_type)
        alloc = build_allocation(
            equity,
            posture_setting=cfg.account_posture,
            overrides=cfg.allocation_overrides,
        )
        budget = float(alloc.budgets.get(mt, 0.0))
        # Small-account soft pockets (Mike 2026-07-02): hard pockets work
        # at size, but at low equity they SQUEEZE -- a 10% pocket of a
        # $5k account cannot fund one option, and swing holds starve the
        # fast lanes. Below TREZO_HARD_POCKET_MIN_EQUITY the pockets act
        # as soft WEIGHTS: each lane stretches by TREZO_SMALL_ACCT_POCKET_
        # STRETCH (capped at 60% of equity per lane). At size, pockets
        # harden back to exact fractions automatically.
        try:
            import os as _os2
            _min_eq = float(_os2.getenv("TREZO_HARD_POCKET_MIN_EQUITY", "25000"))
            if equity and float(equity) < _min_eq:
                _stretch = float(_os2.getenv(
                    "TREZO_SMALL_ACCT_POCKET_STRETCH", "1.75"))
                budget = min(budget * max(1.0, _stretch),
                             float(equity) * 0.60)
        except Exception:  # noqa: BLE001
            pass
        # Intraday overflow (2026-07-02): multi-day swing holds were
        # filling the stocks pocket and STARVING every intraday idea
        # (found live: TSLL/BITO/TZA approvals skipped all morning).
        # Self-liquidating strategies (scalp/orb/stms exit by 3:45) may
        # run the pocket over by a bounded fraction -- they give the
        # capital back the same session.
        try:
            import os as _os
            _s = (strategy or "").lower()
            # 2026-07-14 (Mike): crypto and forex round-trip the same day
            # too -- their capital should be as flexible as the stock
            # intraday lanes, not pinched by held-position conservatism.
            if (_s.startswith(("scalp", "orb", "stms"))
                    or str(mt) in ("crypto", "forex")):
                _ov = float(_os.getenv("TREZO_INTRADAY_OVERFLOW_PCT", "0.25"))
                # SURGE days (Mike 2026-07-14): when the generals run on
                # heavy volume, the fast lanes stretch +50% -- catch the
                # wave, sell by the rules, recycle the capital.
                try:
                    from app.data.market_universe import surge_day
                    if surge_day():
                        _ov = max(_ov, float(_os.getenv(
                            "TREZO_SURGE_OVERFLOW_PCT", "0.50")))
                        import datetime as _dtm
                        _tdy = _dtm.date.today().isoformat()
                        if getattr(surge_day, "_logged", "") != _tdy:
                            surge_day._logged = _tdy  # type: ignore[attr-defined]
                            from app.agents.activity_log import record as _arec
                            _arec("pocket_surge", "MARKET",
                                  reason=("hot-volume day: fast-lane pockets "
                                          "stretched +50% (surge overflow) -- "
                                          "catch the wave, sell by the rules, "
                                          "recycle"),
                                  extra={})
                except Exception:  # noqa: BLE001
                    pass
                budget = budget * (1.0 + max(0.0, _ov))
        except Exception:  # noqa: BLE001
            pass
        deployed = float((await deployed_capital(user_id)).get(mt, 0.0))
        remaining = max(0.0, budget - deployed)
        return mt, budget, deployed, remaining, alloc.posture

    async def _budget_skip(self, user_id, ticker, mt, budget, deployed,
                           posture):
        # Priority rotation (Mike 2026-07-02: "the bots should weigh out
        # the decision to actually take certain trades over others").
        # When live demand keeps hitting a FULL pocket, the lane's weakest
        # stale hold (36h+ old, entry conviction under 550) is asked to
        # leave through the normal close_requested flow -- capital
        # recycles to fresher, higher-priority demand in the SAME lane.
        # Income lanes are never rotated for fast lanes; max N/day.
        try:
            import os as _os3
            if (_os3.getenv("TREZO_PRIORITY_ROTATION", "1") != "0"
                    and mt in ("stocks", "crypto", "forex")):
                from datetime import date as _date
                from datetime import datetime, timezone
                global _ROTATIONS_TODAY
                _today = _date.today().isoformat()
                if _ROTATIONS_TODAY.get("day") != _today:
                    _ROTATIONS_TODAY = {"day": _today, "n": 0}
                _max_rot = int(float(_os3.getenv(
                    "TREZO_PRIORITY_ROTATION_MAX_PER_DAY", "2")))
                if _ROTATIONS_TODAY["n"] < _max_rot:
                    from app.runtime.settings import _supabase
                    client = _supabase()
                    if client is not None:
                        import asyncio as _aio

                        def _q():
                            return (client.table("paper_positions")
                                    .select("id, ticker, entry_at, "
                                            "source_payload, strategy")
                                    .eq("user_id", user_id)
                                    .eq("status", "open")
                                    .eq("close_requested", False)
                                    .execute())
                        rows = (await _aio.to_thread(_q)).data or []
                        from app.paper.allocation import market_type_for
                        now = datetime.now(timezone.utc)
                        cands = []
                        for r in rows:
                            if market_type_for(r.get("strategy"), None) != mt:
                                continue
                            if str(r.get("ticker") or "").upper() == str(ticker).upper():
                                continue
                            try:
                                ea = datetime.fromisoformat(
                                    str(r.get("entry_at")).replace("Z", "+00:00"))
                                held_h = (now - ea).total_seconds() / 3600.0
                            except Exception:  # noqa: BLE001
                                continue
                            _tcs0 = int(((r.get("source_payload") or {})
                                         .get("tcs")) or 0)
                            if held_h >= 36 and _tcs0 < 55:
                                cands.append((held_h, _tcs0, r))
                        if cands:
                            cands.sort(key=lambda x: (x[1], -x[0]))
                            _held_h, _tcs0, victim = cands[0]

                            def _flag(rid=victim["id"]):
                                return (client.table("paper_positions")
                                        .update({"close_requested": True})
                                        .eq("id", rid).execute())
                            await _aio.to_thread(_flag)
                            _ROTATIONS_TODAY["n"] += 1
                            try:
                                from app.agents.activity_log import record as _arec
                                _arec("priority_rotation",
                                      str(victim.get("ticker")),
                                      reason=(f"{mt} pocket full while demand "
                                              f"queues ({ticker}) - weakest hold "
                                              f"(entry TCS {_tcs0}, held "
                                              f"{_held_h:.0f}h) asked to leave; "
                                              f"capital recycles to stronger "
                                              f"signals"),
                                      extra={"user_id": str(user_id),
                                             "displaced_by": str(ticker)})
                            except Exception:  # noqa: BLE001
                                pass
        except Exception:  # noqa: BLE001
            pass
        # Visibility pack (2026-07-01): pocket-full skips are the #1 silent
        # trade-dropper -- make every one visible with the pocket numbers.
        try:
            from app.agents.activity_log import record as _arec
            _arec("pocket_skip", ticker,
                  reason=f"{mt} pocket full under the {posture} posture "
                         f"(${deployed:,.0f} of ${budget:,.0f} deployed) - trade skipped",
                  extra={"user_id": str(user_id), "market_type": mt,
                         "budget_usd": round(budget, 2),
                         "deployed_usd": round(deployed, 2)})
        except Exception:  # noqa: BLE001
            pass
        return [AgentMessage(
            agent=self.name, kind="info",
            payload={
                "user_id": user_id, "ticker": ticker,
                "note": f"{mt} budget used up under the {posture} posture - trade skipped",
                "market_type": mt,
                "budget_usd": round(budget, 2),
                "deployed_usd": round(deployed, 2),
            },
        )]

    async def _execute_internal(
        self, user_id, ticker, asset_type, side, market_price,
        stop_pct, target_pct, strategy, source_payload,
    ) -> list[AgentMessage]:
        from app.runtime.settings import get_bot_settings
        from app.paper.engine import get_account

        account = await get_account(user_id)
        equity = 0.0
        if account:
            try:
                equity = (float(account.get("current_cash_usd") or 0)
                          + float(account.get("vault_balance_usd") or 0))
            except (TypeError, ValueError):
                equity = 0.0

        mt, budget, deployed, remaining, posture = await self._allocation_gate(
            user_id, equity, strategy, asset_type)
        if remaining <= 0:
            if not (source_payload or {}).get("coverage_trade"):
                return await self._budget_skip(user_id, ticker, mt, budget, deployed, posture)

        kwargs: dict = {
            "user_id": user_id,
            "ticker": ticker,
            "asset_type": asset_type,
            "side": side,
            "market_price": market_price,
            "strategy": strategy,
            "source_payload": source_payload,
            "risk_pct": get_bot_settings(user_id).risk_per_trade_pct,
            "max_notional": remaining,
        }
        if isinstance(stop_pct, (int, float)) and stop_pct > 0:
            kwargs["stop_pct"] = float(stop_pct)
        if isinstance(target_pct, (int, float)) and target_pct > 0:
            kwargs["target_pct"] = float(target_pct)

        fill = await open_position(**kwargs)
        if not fill.ok:
            return [AgentMessage(
                agent=self.name, kind="error",
                payload={"user_id": user_id, "ticker": ticker, "error": fill.error},
            )]
        return [AgentMessage(
            agent=self.name, kind="execute", confidence=1.0,
            payload={
                "user_id": user_id,
                "ticker": ticker,
                "side": side,
                "fill_price": fill.fill_price,
                "position_id": fill.position_id,
                "strategy": strategy,
                "market_type": mt,
                "broker": "paper",
                "paper": True,
                "trading_mode": get_trading_mode(),
            },
        )]

    async def _execute_alpaca(
        self, user_id, ticker, side, market_price,
        stop_pct, target_pct, strategy, source_payload,
    ) -> list[AgentMessage]:
        from app.brokers.alpaca import (
            get_account, get_clock, submit_bracket_order, broker_venue,
            UserToken,
        )
        from app.paper.sizing import plan_position
        from app.paper.engine import record_external_position
        from app.runtime.settings import get_bot_settings
        from app.integrations.web_tokens import get_user_broker_token

        def _err(msg: str) -> list[AgentMessage]:
            # Visibility (2026-07-06): execution-stage rejections were
            # INVISIBLE in the activity feed -- approvals showed, then
            # silence (the R:R-floor incident). Every _err now logs.
            try:
                from app.agents.activity_log import record as _arec
                _arec("execute_error", ticker, strategy=strategy,
                      reason=str(msg)[:180],
                      extra={"user_id": str(user_id)})
            except Exception:  # noqa: BLE001
                pass
            return [AgentMessage(
                agent=self.name, kind="error",
                payload={"user_id": user_id, "ticker": ticker,
                         "broker": "alpaca", "error": msg},
            )]

        bt = await get_user_broker_token(user_id, "alpaca")
        token = UserToken(
            access_token=bt.access_token,
            refresh_token=bt.refresh_token,
            expires_at=bt.expires_at,
        ) if bt else None
        routed = "user-oauth" if token else "env-keys"

        clock = await get_clock(token=token)
        if not clock or not clock.get("is_open"):
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"user_id": user_id, "ticker": ticker,
                         "note": "Market closed - Alpaca stock order not placed",
                         "routed_via": routed},
            )]

        acct = await get_account(token=token)
        if not acct:
            return _err("Could not read the Alpaca account")
        if acct.trading_blocked:
            return _err("Alpaca account has trading blocked")

        mt, budget, deployed, remaining, posture = await self._allocation_gate(
            user_id, acct.equity, strategy, "stock")
        if remaining <= 0:
            if not (source_payload or {}).get("coverage_trade"):
                return await self._budget_skip(user_id, ticker, mt, budget, deployed, posture)

        sp = float(stop_pct) if isinstance(stop_pct, (int, float)) and stop_pct > 0 else 0.05
        tp = float(target_pct) if isinstance(target_pct, (int, float)) and target_pct > 0 else 0.10
        if side == "long":
            stop_price = market_price * (1 - sp)
            target_price = market_price * (1 + tp)
            order_side = "buy"
        else:
            stop_price = market_price * (1 + sp)
            target_price = market_price * (1 - tp)
            order_side = "sell"

        risk_pct = source_payload.get("risk_pct_override")
        if risk_pct is None:
            # Per book (2026-08-18). A bare get_bot_settings() here meant
            # every book could be SIZED from one book's risk_per_trade_pct
            # -- the 75k's appetite applied to the 25k, or the reverse.
            # Sizing is the last place a setting should leak.
            risk_pct = get_bot_settings(user_id).risk_per_trade_pct
        plan = plan_position(
            equity=acct.equity,
            entry_price=market_price,
            stop_price=stop_price,
            target_price=target_price,
            risk_pct=float(risk_pct),
            asset_type="stock",
            buying_power=min(acct.buying_power, remaining),
        )
        # Coverage trades stay SMALL (Mike 2026-07-02): one labeled test
        # position per strategy, capped near TREZO_COVERAGE_TRADE_USD.
        if plan.ok and (source_payload or {}).get("coverage_trade"):
            try:
                import dataclasses as _dc
                import os as _osc
                _cov = float(_osc.getenv("TREZO_COVERAGE_TRADE_USD", "150"))
                _maxq = max(1.0, float(int(_cov / max(market_price, 0.01))))
                if plan.quantity > _maxq:
                    plan = _dc.replace(plan, quantity=_maxq,
                                       notional_usd=round(_maxq * market_price, 2))
            except Exception:  # noqa: BLE001
                pass
        # Probation half-size (Mike 2026-07-14): the regime playbook keeps
        # breakout LIVE in rough weather but at reduced size. Risk Manager
        # sets size_scale on the approval; we honor it here.
        if plan.ok:
            try:
                _ss = float((source_payload or {}).get("size_scale") or 0)
                if 0.0 < _ss < 1.0:
                    import dataclasses as _dcs
                    _q2 = plan.quantity * _ss
                    if str(asset_type or "stock") not in ("crypto", "forex"):
                        _q2 = max(1.0, float(int(_q2)))
                    plan = _dcs.replace(
                        plan, quantity=_q2,
                        notional_usd=round(_q2 * market_price, 2))
            except Exception:  # noqa: BLE001
                pass
        force_min = int(source_payload.get("force_min_qty") or 0)
        if not plan.ok and force_min >= 1 and acct.buying_power >= market_price:
            from app.paper.sizing import SizingPlan as _SP, account_tier as _at
            stop_distance = abs(market_price - stop_price)
            plan = _SP(
                ok=True,
                quantity=float(force_min),
                notional_usd=round(force_min * market_price, 2),
                risk_usd=round(force_min * stop_distance, 2),
                risk_pct=round(force_min * stop_distance / acct.equity, 4) if acct.equity > 0 else 0,
                stop_distance=round(stop_distance, 4),
                reward_risk=round(abs(target_price - market_price) / max(stop_distance, 1e-6), 2),
                account_equity=acct.equity,
                account_tier=_at(acct.equity),
            )
        if not plan.ok:
            return _err(plan.reject_reason or "Sizing rejected the trade")

        # Fixed 2026-06-12 (the AAPL incident): bracket exit legs with
        # tif="day" DIE at the 4 PM close while the position lives on --
        # so any multi-day trade went naked overnight (AAPL "default"
        # strategy targets +10%, a multi-day journey, but its stop/target
        # expired same-day). Only true intraday strategies (STMS/ORB,
        # which also have hard time stops) keep day legs; everything
        # else gets GTC legs that survive until filled or cancelled.
        _s = (strategy or "").lower()
        tif = "day" if (_s.startswith("stms") or _s.startswith("orb")) else "gtc"
        # Broker sanity clamps (2026-07-07, from the morning's rejects):
        # (1) Alpaca 422: take_profit must sit >= base+0.01 and the stop
        #     <= base-0.01 -- tight ATR targets can round INTO the base.
        # (2) Alpaca 403: risk-based sizing with tight stops can explode
        #     notional past buying power -- cap at max_position_pct of
        #     equity AND 90% of current BP. Three of these rejects tripped
        #     the session kill-switch and killed the whole day.
        try:
            # DIRECTION-AWARE clamp (fixed 2026-08-11). The 7/7 version
            # assumed every trade was a LONG: it forced take-profit above
            # market and stop below market. Applied to a SHORT, that takes
            # correct levels and INVERTS them -- TP dragged above the stop
            # -- so every short bracket died on the local orientation
            # guard ("short take-profit must sit BELOW stop"). IREN,
            # 2026-08-11 13:31, and the 6 rejects of 8/5 are this bug.
            _tick = max(0.01, round(float(market_price) * 0.001, 2))
            if order_side == "sell":
                # Short: profit BELOW market, stop ABOVE market.
                if target_price is not None:
                    target_price = min(float(target_price),
                                       round(float(market_price) - _tick, 2))
                if stop_price is not None:
                    stop_price = max(float(stop_price),
                                     round(float(market_price) + _tick, 2))
            else:
                if target_price is not None:
                    target_price = max(float(target_price),
                                       round(float(market_price) + _tick, 2))
                if stop_price is not None:
                    stop_price = min(float(stop_price),
                                     round(float(market_price) - _tick, 2))
        except Exception:  # noqa: BLE001
            pass
        try:
            import dataclasses as _dc
            from app.config import get_settings as _gcfg
            try:
                from app.paper.allocation import position_pct_for_equity
                _mp_pct = position_pct_for_equity(float(acct.equity or 0))
            except Exception:  # noqa: BLE001
                _mp_pct = float(getattr(_gcfg(), "max_position_pct", 0.25) or 0.25)
            _cap_usd = min(_mp_pct * float(acct.equity or 0),
                           0.90 * float(acct.buying_power or 0))
            if _cap_usd > 0 and plan.ok:
                _maxq2 = max(1.0, float(int(_cap_usd / max(market_price, 0.01))))
                if plan.quantity > _maxq2:
                    plan = _dc.replace(plan, quantity=_maxq2,
                                       notional_usd=round(_maxq2 * market_price, 2))
        except Exception:  # noqa: BLE001
            pass
        order, err = await submit_bracket_order(
            symbol=ticker,
            qty=plan.quantity,
            side=order_side,
            take_profit_price=target_price,
            stop_loss_price=stop_price,
            time_in_force=tif,
            token=token,
        )
        if err or not order:
            from app.paper.killswitch import record_broker_reject
            record_broker_reject()
            try:
                from app.agents.activity_log import record as _arec
                _arec("broker_reject", ticker, strategy=strategy,
                      reason=str(err)[:200],
                      extra={"user_id": str(user_id), "asset_type": "stock"})
            except Exception:  # noqa: BLE001
                pass
            return _err(f"Alpaca rejected the order: {err}")

        order_id = order.get("id")
        try:
            from app.agents.activity_log import record as _arec
            _arec("submitted", ticker, strategy=strategy,
                  reason=f"{side} {plan.quantity} @ ~{market_price} "
                         f"(stop {stop_price}, target {target_price})",
                  extra={"user_id": str(user_id), "asset_type": "stock"})
        except Exception:  # noqa: BLE001
            pass
        rec = await record_external_position(
            user_id=user_id,
            ticker=ticker,
            asset_type="stock",
            side=side,
            quantity=plan.quantity,
            entry_price=market_price,
            stop_price=stop_price,
            target_price=target_price,
            strategy=strategy,
            broker="alpaca",
            broker_order_id=order_id,
            source_payload={**source_payload, "broker": "alpaca",
                    "broker_order_id": order_id},
        )
        return [
            AgentMessage(
                agent=self.name, kind="execute", confidence=1.0,
                payload={
                    "user_id": user_id,
                    "ticker": ticker,
                    "side": side,
                    "broker": "alpaca",
                    "broker_order_id": order_id,
                    "strategy": strategy,
                    "note": f"Submitted {ticker} {side} via Alpaca, order_id={order_id}",
                },
            )
        ]


    async def _execute_alpaca_crypto(
        self, user_id, ticker, side, market_price,
        stop_pct, target_pct, strategy, source_payload,
    ) -> list[AgentMessage]:
        """Phase F: route crypto signals to Alpaca paper crypto.

        Crypto at Alpaca does NOT support bracket orders, so stops and
        targets are tracked client-side by Position Monitor via the
        stop_price / target_price columns on paper_positions - identical
        to how the internal modeled engine already handles them.

        Market clock is NOT checked because crypto trades 24/7. The
        order uses GTC time-in-force (the only crypto-valid TIF).
        """
        from app.brokers.alpaca import (
            get_account, submit_crypto_order, broker_venue, UserToken,
        )
        from app.paper.sizing import plan_position
        from app.paper.engine import record_external_position
        from app.runtime.settings import get_bot_settings
        from app.integrations.web_tokens import get_user_broker_token

        def _err(msg: str) -> list[AgentMessage]:
            # Visibility (2026-07-06): execution-stage rejections were
            # INVISIBLE in the activity feed -- approvals showed, then
            # silence (the R:R-floor incident). Every _err now logs.
            try:
                from app.agents.activity_log import record as _arec
                _arec("execute_error", ticker, strategy=strategy,
                      reason=str(msg)[:180],
                      extra={"user_id": str(user_id)})
            except Exception:  # noqa: BLE001
                pass
            return [AgentMessage(
                agent=self.name, kind="error",
                payload={"user_id": user_id, "ticker": ticker,
                         "broker": "alpaca", "asset_type": "crypto",
                         "error": msg},
            )]

        bt = await get_user_broker_token(user_id, "alpaca")
        token = UserToken(
            access_token=bt.access_token,
            refresh_token=bt.refresh_token,
            expires_at=bt.expires_at,
        ) if bt else None
        routed = "user-oauth" if token else "env-keys"

        acct = await get_account(token=token)
        if not acct:
            return _err("Could not read the Alpaca account")
        if acct.trading_blocked:
            return _err("Alpaca account has trading blocked")

        mt, budget, deployed, remaining, posture = await self._allocation_gate(
            user_id, acct.equity, strategy, "crypto")
        if remaining <= 0:
            if not (source_payload or {}).get("coverage_trade"):
                return await self._budget_skip(user_id, ticker, mt, budget, deployed, posture)

        sp = float(stop_pct) if isinstance(stop_pct, (int, float)) and stop_pct > 0 else 0.05
        tp = float(target_pct) if isinstance(target_pct, (int, float)) and target_pct > 0 else 0.10
        if side == "long":
            stop_price = market_price * (1 - sp)
            target_price = market_price * (1 + tp)
            order_side = "buy"
        else:
            stop_price = market_price * (1 + sp)
            target_price = market_price * (1 - tp)
            order_side = "sell"

        risk_pct = source_payload.get("risk_pct_override")
        if risk_pct is None:
            # Per book (2026-08-18). A bare get_bot_settings() here meant
            # every book could be SIZED from one book's risk_per_trade_pct
            # -- the 75k's appetite applied to the 25k, or the reverse.
            # Sizing is the last place a setting should leak.
            risk_pct = get_bot_settings(user_id).risk_per_trade_pct
        # Crypto spends NON-MARGINABLE USD at Alpaca (2026-07-23: six
        # approvals died as HTTP 403 "insufficient balance for USD,
        # available: 0" while options collateral pledged every dollar,
        # and the rejects tripped the session kill-switch). Check the
        # right bucket BEFORE the broker does: when the USD wallet is
        # collateral-locked, skip cleanly -- one visible line, no 403
        # storm, no kill-switch trips.
        # Shots on goal (Mike 2026-07-27: "crypto trades are producing a
        # way to make income in the dailies"). The 15%-of-equity
        # concentration cap let ONE coin swallow ~$730 -- two positions
        # emptied the wallet and the 24/7 lane went quiet until an exit.
        # Slice the crypto pocket into TREZO_CRYPTO_MAX_CONCURRENT
        # (default 5) equal shots instead: same capital at risk, several
        # independent chances at a daily win, and a stop on one coin no
        # longer benches the whole lane. Scales with the pocket, so it
        # grows automatically as the account grows.
        try:
            import os as _os_cx
            _cx_n = max(1, int(float(
                _os_cx.getenv("TREZO_CRYPTO_MAX_CONCURRENT", "5"))))
        except (TypeError, ValueError):
            _cx_n = 5
        _cx_slice = max(25.0, float(budget) / _cx_n) if budget else 1e12
        _crypto_usd = float(getattr(
            acct, "non_marginable_buying_power", 0.0) or 0.0)
        # FEE HEADROOM (Mike 2026-08-03: repeated 403s at "requested:
        # 65.66, available: 64.35"). Sizing spent the wallet to the last
        # cent, but Alpaca needs room for fees and price drift between
        # the quote and the fill, so orders missed by ~2% and were
        # rejected -- and each reject counted toward the kill-switch.
        # Keep a small buffer back; a slightly smaller order fills,
        # a perfectly-sized one does not.
        try:
            import os as _os_hr
            _hair = float(_os_hr.getenv("TREZO_CRYPTO_USD_HAIRCUT", "0.96"))
        except (TypeError, ValueError):
            _hair = 0.96
        _crypto_usd = _crypto_usd * max(0.5, min(1.0, _hair))
        if _crypto_usd < 25.0:
            try:
                from app.agents.activity_log import record as _arec
                _arec("crypto_skip_no_usd", ticker, strategy=strategy,
                      reason=(f"crypto entry skipped: USD wallet "
                              f"collateral-locked at the broker "
                              f"(available ${_crypto_usd:,.2f}); frees as "
                              f"option collateral releases"),
                      extra={"user_id": str(user_id)})
            except Exception:  # noqa: BLE001
                pass
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"user_id": user_id, "ticker": ticker,
                         "event": "crypto_skip_no_usd",
                         "note": (f"{ticker}: crypto entry skipped -- USD "
                                  f"wallet collateral-locked "
                                  f"(${_crypto_usd:,.2f} available)")},
            )]
        plan = plan_position(
            equity=acct.equity,
            entry_price=market_price,
            stop_price=stop_price,
            target_price=target_price,
            risk_pct=float(risk_pct),
            asset_type="crypto",
            buying_power=min(_crypto_usd, remaining, _cx_slice),
        )
        if plan.ok and (source_payload or {}).get("coverage_trade"):
            try:
                import dataclasses as _dc
                import os as _osc
                _cov = float(_osc.getenv("TREZO_COVERAGE_TRADE_USD", "150"))
                _maxq = _cov / max(market_price, 1e-9)
                if plan.quantity > _maxq:
                    plan = _dc.replace(plan, quantity=_maxq,
                                       notional_usd=round(_maxq * market_price, 2))
            except Exception:  # noqa: BLE001
                pass
        if not plan.ok:
            return _err(plan.reject_reason or "Sizing rejected the trade")

        # ALPACA CRYPTO MINIMUM (2026-08-09). Alpaca rejects any crypto order
        # whose cost basis is under $10 -- "cost basis must be >= minimal
        # amount of order 10". On 8/9 that produced 12 rejects, and THREE
        # rejects inside an hour trip the session kill-switch, so a sizing
        # problem cascaded into an hour-long trading pause. Skipping the
        # order cleanly costs one trade; sending it costs the hour.
        import os as _os_min      # module has NO top-level `import os`
        _min_notional = float(_os_min.getenv("TREZO_CRYPTO_MIN_ORDER_USD", "10"))
        _notional = float(plan.quantity) * float(market_price)
        if _notional < _min_notional:
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"user_id": user_id, "ticker": ticker,
                         "event": "crypto_skip_below_min",
                         "note": (f"{ticker}: order would be ${_notional:,.2f}, "
                                  f"below Alpaca's ${_min_notional:,.0f} crypto "
                                  f"minimum -- skipped before the broker could "
                                  f"reject it and trip the kill-switch")},
            )]

        order, err = await submit_crypto_order(
            symbol=ticker,
            side=order_side,
            qty=plan.quantity,
            token=token,
        )
        if err or not order:
            from app.paper.killswitch import record_broker_reject
            record_broker_reject()
            try:
                from app.agents.activity_log import record as _arec
                _arec("broker_reject", ticker, strategy=strategy,
                      reason=str(err)[:200],
                      extra={"user_id": str(user_id), "asset_type": "crypto"})
            except Exception:  # noqa: BLE001
                pass
            return _err(f"Alpaca rejected the crypto order: {err}")

        order_id = order.get("id")
        try:
            from app.agents.activity_log import record as _arec
            _arec("submitted", ticker, strategy=strategy,
                  reason=f"{side} {plan.quantity} crypto @ ~{market_price}",
                  extra={"user_id": str(user_id), "asset_type": "crypto"})
        except Exception:  # noqa: BLE001
            pass
        await record_external_position(
            user_id=user_id,
            ticker=ticker,
            asset_type="crypto",
            side=side,
            quantity=plan.quantity,
            entry_price=market_price,
            stop_price=stop_price,
            target_price=target_price,
            strategy=strategy,
            broker="alpaca",
            broker_order_id=order_id,
            source_payload={
                **source_payload, "broker": "alpaca",
                "broker_order_id": order_id,
                "alpaca_crypto": True,
            },
        )
        return [
            AgentMessage(
                agent=self.name, kind="execute", confidence=1.0,
                payload={
                    "user_id": user_id,
                    "ticker": ticker,
                    "side": side,
                    "asset_type": "crypto",
                    "broker": "alpaca",
                    "broker_order_id": order_id,
                    "strategy": strategy,
                    "quantity": plan.quantity,
                    "entry_price": market_price,
                    "stop_price": stop_price,
                    "target_price": target_price,
                    "routed_via": routed,
                    "note": (
                        f"Submitted {ticker} {side} crypto via Alpaca, "
                        f"order_id={order_id}"
                    ),
                },
            )
        ]
