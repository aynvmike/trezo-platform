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

CRYPTO_SYMBOLS = {"XRP", "ETH", "SOL", "BTC"}


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

        return await self._execute_for_user(user_id, ticker, side, message.payload)

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
        for uid in users:
            try:
                msgs = await self._execute_for_user(uid, ticker, side, source_payload)
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

        if asset_type == "stock" and alpaca_configured():
            return await self._execute_alpaca(
                user_id, ticker, side, market_price,
                stop_pct, target_pct, strategy, source_payload,
            )

        return await self._execute_internal(
            user_id, ticker, asset_type, side, market_price,
            stop_pct, target_pct, strategy, source_payload,
        )

    async def _allocation_gate(self, user_id, equity, strategy, asset_type):
        from app.paper.allocation import (
            build_allocation, deployed_capital, market_type_for,
        )
        from app.runtime.settings import get_bot_settings
        cfg = get_bot_settings()
        mt = market_type_for(strategy, asset_type)
        alloc = build_allocation(
            equity,
            posture_setting=cfg.account_posture,
            overrides=cfg.allocation_overrides,
        )
        budget = float(alloc.budgets.get(mt, 0.0))
        deployed = float((await deployed_capital(user_id)).get(mt, 0.0))
        remaining = max(0.0, budget - deployed)
        return mt, budget, deployed, remaining, alloc.posture

    def _budget_skip(self, user_id, ticker, mt, budget, deployed, posture):
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
            return self._budget_skip(user_id, ticker, mt, budget, deployed, posture)

        kwargs: dict = {
            "user_id": user_id,
            "ticker": ticker,
            "asset_type": asset_type,
            "side": side,
            "market_price": market_price,
            "strategy": strategy,
            "source_payload": source_payload,
            "risk_pct": get_bot_settings().risk_per_trade_pct,
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
            return self._budget_skip(user_id, ticker, mt, budget, deployed, posture)

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
            risk_pct = get_bot_settings().risk_per_trade_pct
        plan = plan_position(
            equity=acct.equity,
            entry_price=market_price,
            stop_price=stop_price,
            target_price=target_price,
            risk_pct=float(risk_pct),
            asset_type="stock",
            buying_power=min(acct.buying_power, remaining),
        )
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

        tif = "gtc" if strategy == "extended" else "day"
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
            return _err(f"Alpaca rejected the order: {err}")

        order_id = order.get("id")
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
            return self._budget_skip(user_id, ticker, mt, budget, deployed, posture)

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
            risk_pct = get_bot_settings().risk_per_trade_pct
        plan = plan_position(
            equity=acct.equity,
            entry_price=market_price,
            stop_price=stop_price,
            target_price=target_price,
            risk_pct=float(risk_pct),
            asset_type="crypto",
            buying_power=min(acct.buying_power, remaining),
        )
        if not plan.ok:
            return _err(plan.reject_reason or "Sizing rejected the trade")

        order, err = await submit_crypto_order(
            symbol=ticker,
            side=order_side,
            qty=plan.quantity,
            token=token,
        )
        if err or not order:
            from app.paper.killswitch import record_broker_reject
            record_broker_reject()
            return _err(f"Alpaca rejected the crypto order: {err}")

        order_id = order.get("id")
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
