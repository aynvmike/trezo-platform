"""Options Scanner Agent — the Dividend Wheel income engine + options ideas.

Ticks every 30 minutes. Three jobs:

  1. SETTLE — close any modeled option position whose expiration has passed.
     For a cash-secured put: if spot >= strike the put expires worthless and
     the full credit is kept; if spot < strike it's "assigned" and the loss
     is credit - (strike - spot) * 100 * contracts.

  2. RECONCILE — when a user has a live Alpaca connection, compare each
     open options_positions row against the user's actual broker option
     positions. Any row that has no matching contract at the broker is
     closed_manual with a "Reconciled — not present at broker" note. This
     keeps the modeled book honest: Alpaca is the truth, the planner is
     not allowed to drift.

  3. WHEEL — for each quality name in the Wheel watchlist with no open
     position, either:
       a) emit a SUGGESTION (when the user has Alpaca connected) so they
          can place a real CSP via the Place CSP button, or
       b) open a modeled cash-secured put (paper-only users with no live
          broker — the original Phase-6 behaviour).

It also emits `info` messages with Long Call / Bull Call Spread / CSP
*ideas* for the watchlist — surfaced as suggestions, not auto-executed,
because directional options carry more risk.
"""

from __future__ import annotations

import asyncio
from datetime import date

from app.config import get_settings
from app.data.candles import fetch_candles_for
from app.strategies.wheel import (
    WHEEL_WATCHLIST, evaluate_csp, evaluate_cc, refine_csp_live,
)
from app.strategies.options_strategies import (
    build_long_call,
    build_bull_call_spread,
    build_cash_secured_put,
    build_bull_put_spread,
    build_iron_condor,
)

from .base import Agent, AgentMessage


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:
        return None


async def _user_halted(client, user_id: str) -> bool:
    """True when the user's paper_account is currently in trading_halted
    state (kill-switch tripped, consecutive-loss limit hit, etc.).
    Wheel auto-execute must never fire into a halted account."""
    import asyncio

    def _sync():
        return (
            client.table("paper_accounts")
            .select("trading_halted")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    try:
        res = await asyncio.to_thread(_sync)
        rows = res.data or []
        if not rows:
            return False
        return bool(rows[0].get("trading_halted"))
    except Exception:  # noqa: BLE001
        # Fail SAFE: when the check itself errors, treat the account
        # as halted so we don't auto-fire on incomplete information.
        return True


async def _user_has_alpaca(user_id: str) -> bool:
    """True when an Alpaca path is configured for this user — either
    per-user OAuth token OR env-key fallback. Used to decide between
    modeled-insert (no broker at all) and suggestion-only (broker
    exists, so the user should place legs via the Place button).

    The env-key check is important: if env keys are set, the modeled
    book and broker are in the same world, so auto-inserting modeled
    phantoms makes the planner drift from reality every tick."""
    try:
        from app.integrations.web_tokens import get_user_broker_token
        bt = await get_user_broker_token(user_id, "alpaca")
        if bt and bt.access_token:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.brokers.alpaca import alpaca_configured
        return alpaca_configured()
    except Exception:  # noqa: BLE001
        return False


def _occ_match(occ: str, underlying: str, opt_type: str, strike: float,
               expiration: str) -> bool:
    """Best-effort match between an OCC symbol and a modeled row.
    OCC format: <root><yymmdd><C|P><strike*1000 zero-padded 8 digits>.
    Examples: AAPL250620C00150000, WMT260626P00115000.
    """
    if not occ or not underlying or not expiration:
        return False
    root = "".join(c for c in occ if c.isalpha()).rstrip("CP")
    # The trailing "CP" is part of the format separator — be lenient: pull
    # the leading alpha run as the root candidate.
    leading_alpha = ""
    for c in occ:
        if c.isalpha():
            leading_alpha += c
        else:
            break
    if leading_alpha.upper() != underlying.upper():
        return False
    # Expiration: YY-MM-DD pieces should appear right after the root.
    yy, mm, dd = expiration[2:4], expiration[5:7], expiration[8:10]
    if f"{yy}{mm}{dd}" not in occ:
        return False
    # Strike: 8-digit chunk = strike * 1000.
    try:
        strike_chunk = f"{int(round(float(strike) * 1000)):08d}"
    except (TypeError, ValueError):
        return False
    if strike_chunk not in occ:
        return False
    # Option type: C for call (wheel_cc), P for put (wheel_csp).
    expected = "C" if opt_type == "call" else "P"
    return expected in occ


class OptionsScannerAgent(Agent):
    name = "options_scanner"
    tick_interval_seconds = 1800  # every 30 minutes

    async def tick(self) -> list[AgentMessage]:
        client = _supabase()
        if not client:
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "Supabase not configured."})]

        out: list[AgentMessage] = []

        # --- 1. SETTLE expired positions -----------------------------------
        settled = await self._settle_expired(client)
        out.extend(settled)

        # --- 2. RECONCILE modeled book vs broker (per user) ---------------
        reconciled = await self._reconcile_with_broker(client)
        out.extend(reconciled)

        # --- 3. WHEEL: open CSPs where missing -----------------------------
        opened = await self._run_wheel(client)
        out.extend(opened)

        # --- 4. Options-strategy IDEAS (suggestions only) ------------------
        ideas = await self._options_ideas()
        out.extend(ideas)

        if not out:
            out.append(AgentMessage(agent=self.name, kind="info",
                                    payload={"note": "Options scan complete — no actions."}))
        return out

    # ----------------------------------------------------------------------

    async def _settle_expired(self, client) -> list[AgentMessage]:
        today = date.today().isoformat()

        def _sync_get():
            return (
                client.table("options_positions")
                .select("id, user_id, underlying, strategy, option_type, strike, contracts, net_premium_usd, expiration")
                .eq("status", "open")
                .lte("expiration", today)
                .execute()
            )

        res = await asyncio.to_thread(_sync_get)
        rows = res.data or []
        out: list[AgentMessage] = []

        for r in rows:
            candles = await fetch_candles_for(r["underlying"], "stock")
            spot = float(candles[-1].close) if candles else 0.0
            strike = float(r.get("strike") or 0)
            contracts = int(r.get("contracts") or 1)
            credit = float(r.get("net_premium_usd") or 0)

            # Cash-secured put settlement
            if r["strategy"] in ("wheel_csp", "cash_secured_put") and strike > 0 and spot > 0:
                if spot >= strike:
                    status, realized = "closed_expired", credit          # kept full credit
                else:
                    assignment_loss = (strike - spot) * 100 * contracts
                    status, realized = "closed_assigned", credit - assignment_loss
            elif r["strategy"] == "wheel_cc" and strike > 0 and spot > 0:
                # Covered call: above the strike the shares are called away
                # (premium kept); below it the call expires worthless and the
                # shares are retained for the next covered call.
                if spot >= strike:
                    status, realized = "closed_called_away", credit
                else:
                    status, realized = "closed_expired", credit
            else:
                # Other strategies: settle at the modeled credit/debit for now
                status, realized = "closed_expired", credit

            def _sync_close(rid=r["id"], st=status, pnl=realized):
                return (
                    client.table("options_positions")
                    .update({
                        "status": st,
                        "realized_pnl_usd": round(pnl, 2),
                        "closed_at": "now()",
                    })
                    .eq("id", rid)
                    .execute()
                )

            await asyncio.to_thread(_sync_close)
            out.append(AgentMessage(
                agent=self.name, kind="close",
                payload={
                    "user_id": r["user_id"],
                    "underlying": r["underlying"],
                    "strategy": r["strategy"],
                    "status": status,
                    "realized_pnl_usd": round(realized, 2),
                },
            ))
        return out

    async def _reconcile_with_broker(self, client) -> list[AgentMessage]:
        """For every user with a live Alpaca connection: any open modeled
        row that has no matching contract at the broker is closed_manual."""
        from app.brokers.alpaca import (
            UserToken, get_option_positions, alpaca_configured,
        )
        from app.integrations.web_tokens import get_user_broker_token

        out: list[AgentMessage] = []

        # Open rows grouped per user.
        def _sync_open():
            return (
                client.table("options_positions")
                .select("id, user_id, underlying, strategy, option_type, "
                        "strike, expiration, contracts, notes")
                .eq("status", "open")
                .in_("strategy", ["wheel_csp", "wheel_cc"])
                .execute()
            )
        rows = (await asyncio.to_thread(_sync_open)).data or []
        if not rows:
            return out

        by_user: dict[str, list[dict]] = {}
        for r in rows:
            by_user.setdefault(str(r["user_id"]), []).append(r)

        for user_id, user_rows in by_user.items():
            # Skip users with no live Alpaca connection (and no env-key
            # broker either — those stay in pure modeled mode).
            token = None
            bt = await get_user_broker_token(user_id, "alpaca")
            if bt and bt.access_token:
                token = UserToken(
                    access_token=bt.access_token,
                    refresh_token=bt.refresh_token,
                    expires_at=bt.expires_at,
                )
            if token is None and not alpaca_configured():
                continue

            try:
                broker_options = await get_option_positions(token=token)
            except Exception:  # noqa: BLE001
                broker_options = []
            broker_occ = [str(p.get("symbol", "")) for p in broker_options]

            closed_count = 0
            for r in user_rows:
                # If the row was placed via the new place-leg flow it has
                # 'Placed via Alpaca' in its notes — leave those alone for
                # the broker to manage. Anything else is a modeled phantom.
                notes = str(r.get("notes") or "")
                if "Placed via Alpaca" in notes:
                    # Verify it still exists at broker; if it doesn't, that
                    # means the broker closed/expired it — also close locally.
                    matched = any(_occ_match(
                        occ, r["underlying"], r["option_type"],
                        float(r["strike"]), str(r["expiration"]))
                        for occ in broker_occ)
                    if matched:
                        continue
                # No match at the broker -> close it as Reconciled.
                def _sync_close(rid=r["id"]):
                    return (
                        client.table("options_positions")
                        .update({
                            "status": "closed_manual",
                            "realized_pnl_usd": 0.0,
                            "closed_at": "now()",
                            "notes": (notes + " · Reconciled — not present at broker.").strip(" ·"),
                        })
                        .eq("id", rid)
                        .execute()
                    )
                await asyncio.to_thread(_sync_close)
                closed_count += 1

            if closed_count:
                out.append(AgentMessage(
                    agent=self.name, kind="info",
                    payload={
                        "user_id": user_id,
                        "event": "reconcile",
                        "note": (f"Reconciled {closed_count} modeled Wheel "
                                 f"leg(s) against Alpaca — none matched at "
                                 f"the broker, so they were closed."),
                        "closed_count": closed_count,
                    },
                ))
        return out

    async def _wheel_auto_fire(
        self,
        user_id: str,
        underlying: str,
        leg,
        strategy: str,
        priced: str,
    ):
        """Fire a Wheel CSP / CC order on Alpaca, mirroring the same
        primitives /wheel/place-leg uses for the manual button.

        Returns an AgentMessage on SUCCESS (the order was accepted and a
        tracking row inserted) or None on FAILURE (caller falls back to
        the suggestion path so nothing is silently dropped).

        Safety gates handled INSIDE this method:
          - Alpaca options approval level >= 1 (covered).
          - live_option_pick finds a real listed contract.
          - submit_option_order returns ok.

        Outside gates (caller checks first):
          - wheel_auto_execute setting is on.
          - User's paper_account is not halted.
        """
        from app.brokers.alpaca import (
            UserToken, submit_option_order, get_account,
        )
        from app.brokers.alpaca_data import live_option_pick
        from app.integrations.web_tokens import get_user_broker_token
        from app.paper.engine import record_external_position
        import asyncio

        # Resolve token: per-user OAuth first, env-key fallback.
        token: "UserToken | None" = None
        routed = "env-keys"
        bt = await get_user_broker_token(user_id, "alpaca")
        if bt and bt.access_token:
            token = UserToken(
                access_token=bt.access_token,
                refresh_token=bt.refresh_token,
                expires_at=bt.expires_at,
            )
            routed = "user-oauth"

        # Options-approval gate. Mike has Level 3 paper; Level 1 is the
        # minimum the Wheel needs (covered CSP + CC).
        acct = await get_account(token=token)
        approval = int(getattr(acct, "options_approved_level", 0) or 0)
        if approval < 1:
            return AgentMessage(
                agent=self.name, kind="info",
                payload={
                    "user_id": user_id,
                    "event": "wheel_auto_blocked",
                    "underlying": underlying,
                    "strategy": strategy,
                    "reason": (
                        f"Alpaca options approval level {approval} - "
                        f"need >= 1 to fire CSP / CC. Apply on Alpaca "
                        f"(Account - Configure - Options trading)."
                    ),
                    "routed_via": routed,
                },
            )

        # Find the actual listed contract closest to our target.
        opt_type = "put" if strategy == "wheel_csp" else "call"
        pick = await live_option_pick(
            underlying, opt_type, float(leg.strike), str(leg.expiration),
        )
        if not pick:
            return AgentMessage(
                agent=self.name, kind="info",
                payload={
                    "user_id": user_id,
                    "event": "wheel_auto_blocked",
                    "underlying": underlying,
                    "strategy": strategy,
                    "reason": (
                        f"No listed {opt_type} contract near "
                        f"${leg.strike:.2f} for {leg.expiration}."
                    ),
                    "routed_via": routed,
                },
            )

        # SELL-TO-OPEN the put (CSP) or call (CC). Same call shape the
        # manual button uses - day time-in-force, no limit price (market).
        order, err = await submit_option_order(
            occ_symbol=pick.occ,
            contracts=int(leg.contracts or 1),
            side="sell",
            time_in_force="day",
            limit_price=None,
            token=token,
        )
        if err or not order:
            return AgentMessage(
                agent=self.name, kind="error",
                payload={
                    "user_id": user_id,
                    "event": "wheel_auto_blocked",
                    "underlying": underlying,
                    "strategy": strategy,
                    "reason": f"Alpaca rejected the order: {err}",
                    "occ": pick.occ,
                    "routed_via": routed,
                },
            )

        # Record the tracking row - same shape as the manual flow.
        order_id = order.get("id")
        note = (
            f"Auto-placed {priced} "
            f"{'covered call' if strategy == 'wheel_cc' else 'cash-secured put'} "
            f"on {underlying} at ${pick.strike:.2f}, expiring "
            f"{pick.expiration}. Routed via {routed}."
        )

        def _sync_insert():
            return (
                client.table("options_positions").insert({
                    "user_id": user_id,
                    "underlying": underlying.upper(),
                    "strategy": strategy,
                    "direction": "income",
                    "option_type": opt_type,
                    "strike": pick.strike,
                    "expiration": pick.expiration,
                    "contracts": int(leg.contracts or 1),
                    "net_premium_usd": float(pick.premium or leg.credit_usd or 0) * 100 * int(leg.contracts or 1),
                    "modeled_iv": getattr(leg, "modeled_iv", None),
                    "legs": [{
                        "action": "sell",
                        "type": opt_type,
                        "strike": pick.strike,
                        "premium": pick.premium,
                    }],
                    "notes": note + " · Placed via Alpaca · auto-fired",
                    "broker_order_id": order_id,
                    "source_payload": {
                        "auto_fired": True,
                        "routed_via": routed,
                        "occ": pick.occ,
                    },
                }).execute()
            )

        try:
            await asyncio.to_thread(_sync_insert)
        except Exception:  # noqa: BLE001
            # The order DID fire on Alpaca but we couldn't track it -
            # surface that loudly so Mike can manually reconcile.
            return AgentMessage(
                agent=self.name, kind="error",
                payload={
                    "user_id": user_id,
                    "event": "wheel_auto_tracking_failed",
                    "underlying": underlying,
                    "strategy": strategy,
                    "occ": pick.occ,
                    "alpaca_order_id": order_id,
                    "reason": (
                        "Auto-placed at Alpaca but failed to insert "
                        "Trezo tracking row. Reconcile via the Wheel "
                        "page reconcile button."
                    ),
                    "routed_via": routed,
                },
            )

        return AgentMessage(
            agent=self.name, kind="execute", confidence=1.0,
            payload={
                "user_id": user_id,
                "event": "wheel_auto_placed",
                "underlying": underlying,
                "strategy": strategy,
                "occ": pick.occ,
                "strike": pick.strike,
                "expiration": pick.expiration,
                "contracts": int(leg.contracts or 1),
                "premium_per_share": pick.premium,
                "credit_usd": float(pick.premium or 0) * 100 * int(leg.contracts or 1),
                "alpaca_order_id": order_id,
                "alpaca_order_status": order.get("status"),
                "routed_via": routed,
                "note": note,
            },
        )

    async def _run_wheel(self, client) -> list[AgentMessage]:
        # Every user with a paper account participates in the Wheel.
        def _sync_users():
            return client.table("paper_accounts").select("user_id").execute()

        users = [u["user_id"] for u in ((await asyncio.to_thread(_sync_users)).data or [])]
        if not users:
            return []

        out: list[AgentMessage] = []
        # Mike 2026-06-01: switched from a single static WHEEL_WATCHLIST
        # loop to a per-user dynamic universe. Each user's wheel can
        # consider any quality dividend stock they've surfaced via
        # watchlists, plus any name they already hold an open option
        # position on, on top of the curated seed list. See
        # app/strategies/wheel_universe.py for the composition rules.
        from app.strategies.wheel_universe import get_wheel_universe
        # Flip the loop nesting so we fetch the universe once per user.
        for user_id in users:
            try:
                universe = await get_wheel_universe(user_id)
            except Exception:  # noqa: BLE001
                # Universe fetch is best-effort - fall back to seed.
                universe = [
                    type("_C", (), {"ticker": s, "source": "seed",
                                    "yield_pct": 0.0})()
                    for s in WHEEL_WATCHLIST
                ]
            for cand in universe:
                underlying = cand.ticker
                candles = await fetch_candles_for(underlying, "stock")
                if not candles:
                    continue

                # Skip if this user already has an open position on this name.
                def _sync_existing(uid=user_id, sym=underlying):
                    return (
                        client.table("options_positions").select("id")
                        .eq("user_id", uid).eq("underlying", sym)
                        .eq("status", "open").execute()
                    )
                if (await asyncio.to_thread(_sync_existing)).data:
                    continue

                # The user's most recent settled position on this name -
                # if the last cash-secured put was assigned, the user now
                # holds the shares and the Wheel turns to a covered call.
                def _sync_last(uid=user_id, sym=underlying):
                    return (
                        client.table("options_positions")
                        .select("status, strike, contracts")
                        .eq("user_id", uid).eq("underlying", sym)
                        .neq("status", "open")
                        .order("closed_at", desc=True).limit(1).execute()
                    )
                last_rows = (await asyncio.to_thread(_sync_last)).data or []
                last = last_rows[0] if last_rows else None

                # Phase 13b — cycle awareness in the Wheel. Pull the
                # ex-div + earnings position once per name; passed into
                # evaluate_cc so the strike picker can dodge dividend
                # call-aways.
                cycle_days_to_exdiv = None
                try:
                    from app.data.cycles import get_cycle_position
                    cyc = await get_cycle_position(underlying)
                    cycle_days_to_exdiv = cyc.next_exdiv_days
                except Exception:  # noqa: BLE001
                    cycle_days_to_exdiv = None

                if last and last.get("status") == "closed_assigned":
                    # Covered-call-after-assignment: sell a call above the
                    # assigned cost basis (the prior put's strike).
                    leg = evaluate_cc(
                        underlying, candles,
                        float(last.get("strike") or 0),
                        days_until_exdiv=cycle_days_to_exdiv,
                    )
                    strategy = "wheel_cc"
                else:
                    leg = evaluate_csp(underlying, candles)
                    if leg:
                        leg = await refine_csp_live(leg)
                    strategy = "wheel_csp"
                if not leg:
                    continue

                priced = "Live-quoted" if getattr(leg, "live", False) else "Modeled"

                # Has this user connected Alpaca? When YES, behavior splits
                # on the wheel_auto_execute bot setting:
                #   - OFF (default): emit a suggestion; user clicks the
                #     Place CSP / CC button on the Wheel page to fire.
                #   - ON: bot fires the order itself through the same
                #     /wheel/place-leg primitives. Kill-switches +
                #     consecutive-loss limit honored. Failures fall
                #     back to a suggestion so nothing is silently dropped.
                if await _user_has_alpaca(user_id):
                    from app.runtime.settings import get_bot_settings
                    cfg = get_bot_settings(user_id)

                    # Check kill-switch state first - never auto-fire
                    # into a halted account.
                    halted = await _user_halted(client, user_id)

                    if cfg.wheel_auto_execute and not halted:
                        # AUTO-FIRE PATH
                        autofire = await self._wheel_auto_fire(
                            user_id=user_id,
                            underlying=leg.underlying,
                            leg=leg,
                            strategy=strategy,
                            priced=priced,
                        )
                        if autofire is not None:
                            out.append(autofire)
                            continue
                        # Auto-fire failed; fall through to suggestion so
                        # Mike sees what was tried + why it didn't work.

                    # SUGGESTION PATH (default, or auto-fire fell back).
                    suggestion_note = (
                        f"Suggestion: {priced} "
                        f"{'covered call' if strategy == 'wheel_cc' else 'cash-secured put'} "
                        f"on {leg.underlying} at ${leg.strike:.2f}, "
                        f"~${leg.credit_usd:.0f} credit. "
                    )
                    if cfg.wheel_auto_execute and halted:
                        suggestion_note += (
                            "Auto-execute is ON but the account is "
                            "halted (kill-switch). Nothing auto-fired."
                        )
                    else:
                        suggestion_note += (
                            "Use the Place button on the Wheel page "
                            "if you want to fire it."
                        )
                    out.append(AgentMessage(
                        agent=self.name, kind="info",
                        payload={
                            "user_id": user_id,
                            "event": "wheel_suggestion",
                            "underlying": leg.underlying,
                            "strategy": strategy,
                            "credit_usd": leg.credit_usd,
                            "strike": leg.strike,
                            "expiration": leg.expiration,
                            "modeled": not getattr(leg, "live", False),
                            "note": suggestion_note,
                        },
                    ))
                    continue

                # Paper-only users (no Alpaca) keep the original auto-insert
                # behaviour so the planner is not empty.
                if strategy == "wheel_cc":
                    note = (f"{priced} covered call above the assigned cost "
                            f"basis. Collect ${leg.credit_usd:.0f} credit.")
                else:
                    note = (f"{priced} cash-secured put. Collect "
                            f"${leg.credit_usd:.0f} credit; "
                            f"${leg.cash_secured_usd:.0f} cash secured.")

                def _sync_insert(uid=user_id, lg=leg, st=strategy, nt=note):
                    return (
                        client.table("options_positions").insert({
                            "user_id": uid,
                            "underlying": lg.underlying,
                            "strategy": st,
                            "direction": "income",
                            "option_type": lg.option_type,
                            "strike": lg.strike,
                            "expiration": lg.expiration,
                            "contracts": lg.contracts,
                            "net_premium_usd": lg.credit_usd,
                            "modeled_iv": lg.modeled_iv,
                            "legs": [{"action": "sell", "type": lg.option_type,
                                      "strike": lg.strike,
                                      "premium": lg.premium_per_share}],
                            "notes": nt,
                        }).execute()
                    )

                await asyncio.to_thread(_sync_insert)
                out.append(AgentMessage(
                    agent=self.name, kind="execute",
                    payload={
                        "user_id": user_id,
                        "underlying": leg.underlying,
                        "strategy": strategy,
                        "credit_usd": leg.credit_usd,
                        "strike": leg.strike,
                        "modeled": not getattr(leg, "live", False),
                    },
                ))
        return out

    async def _options_ideas(self) -> list[AgentMessage]:
        """Surface — but don't auto-execute — directional options plays."""
        out: list[AgentMessage] = []
        for underlying in WHEEL_WATCHLIST[:3]:  # keep the heartbeat light
            candles = await fetch_candles_for(underlying, "stock")
            if not candles:
                continue
            for builder in (build_long_call, build_bull_call_spread,
                            build_cash_secured_put, build_bull_put_spread,
                            build_iron_condor):
                play = builder(underlying, candles)
                if not play:
                    continue
                    continue
                out.append(AgentMessage(
                    agent=self.name, kind="info",
                    payload={
                        "event": "options_idea",
                        "underlying": play.underlying,
                        "strategy": play.strategy,
                        "direction": play.direction,
                        "expiration": play.expiration,
                        "contracts": play.contracts,
                        "net_premium_usd": play.net_premium_usd,
                        "max_loss_usd": play.max_loss_usd,
                        "max_gain_usd": play.max_gain_usd,
                        "modeled_iv": play.modeled_iv,
                        "net_delta": play.net_delta,
                        "net_gamma": play.net_gamma,
                        "net_theta": play.net_theta,
                        "net_vega": play.net_vega,
                        "legs": play.legs,
                        "notes": play.notes,
                    },
                ))
        return out
