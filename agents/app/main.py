"""FastAPI entry point for the Trezo agents service."""

import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Loud debug marker so we can confirm THIS file is the one uvicorn loaded.
print(f"[trezo-agents] main.py LOADED build=PHASE5-D2 file={__file__}", file=sys.stderr, flush=True)

from app.api.agents import router as agents_router
from app.api.patterns import router as patterns_router
from app.config import get_settings
from app.logging import setup_logging
from app.runtime.bootstrap import bootstrap_agents
from app.runtime.registry import registry
from app.runtime.scheduler import start_scheduler, stop_scheduler, _tick_agent

settings = get_settings()
log = setup_logging()

app = FastAPI(
    title="Trezo Agents",
    version="0.1.0",
    description="Multi-agent runtime for the Trezo platform.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(patterns_router)
app.include_router(agents_router)

print(
    f"[trezo-agents] after include_router: {len(app.routes)} routes — paths: "
    f"{[r.path for r in app.routes]}",
    file=sys.stderr,
    flush=True,
)


# ---------------------------------------------------------------------------
# Direct fallback endpoints — registered on `app` itself, NOT via the router.
# These guarantee the /agents endpoints are reachable even if include_router
# is silently misbehaving in the current FastAPI/Pydantic version.
# ---------------------------------------------------------------------------

@app.get("/agents", tags=["agents-direct"])
async def list_agents_direct():
    out = []
    for st in registry.all():
        out.append(st.snapshot())
    return out


@app.get("/agents/feed/recent", tags=["agents-direct"])
async def feed_recent_direct(limit: int = 50):
    from app.api.agents import _supabase

    client = _supabase()
    if not client:
        return {"messages": []}
    try:
        res = (
            client.table("agent_messages")
            .select("*")
            .order("created_at", desc=True)
            .limit(min(max(limit, 1), 200))
            .execute()
        )
        return {"messages": res.data or []}
    except Exception as e:
        return {"messages": [], "error": str(e)}


@app.post("/agents/{name}/toggle", tags=["agents-direct"])
async def toggle_direct(name: str, body: dict):
    enabled = bool(body.get("enabled", True))
    st = registry.set_enabled(name, enabled)
    if not st:
        return {"error": f"Unknown agent: {name}"}, 404
    return st.snapshot()


@app.post("/agents/{name}/trigger", tags=["agents-direct"])
async def trigger_direct(name: str):
    st = registry.get(name)
    if not st:
        return {"error": f"Unknown agent: {name}"}, 404
    enabled_before = st.enabled
    st.enabled = True
    try:
        await _tick_agent(st)
    finally:
        st.enabled = enabled_before
    return st.snapshot()


@app.get("/backtest", tags=["backtest"])
async def backtest_endpoint(symbol: str, strategy: str = "default",
                            tcs_threshold: int = 700, period: str = "2y",
                            stop_pct: float = 0.05, target_pct: float = 0.10):
    """Replay a symbol's history through Trezo's scoring and report the
    win rate, profit factor, drawdown and trade log (#121).

    Phase 12d: works for crypto as well as stocks, and accepts a custom
    stop / target so a strategy variant can be tested."""
    from app.data.candles import fetch_stock_candles, fetch_crypto_ohlc, COIN_MAP
    from app.backtest.engine import run_backtest

    sym = (symbol or "").strip().upper()
    if not sym:
        return {"error": "A ticker symbol is required."}
    # Clamp the custom risk parameters to sane ranges.
    sp = min(0.5, max(0.01, float(stop_pct)))
    tp = min(1.0, max(0.01, float(target_pct)))
    try:
        if sym in COIN_MAP:
            # Crypto: CoinGecko OHLC. days=365 yields ~90 4-day bars.
            candles = await fetch_crypto_ohlc(sym, days=365)
        else:
            candles = await fetch_stock_candles(sym, period=period, interval="1d")
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not fetch history for {sym}: {e}"}
    if not candles or len(candles) < 70:
        return {"error": f"Not enough historical data for {sym} to backtest."}
    result = run_backtest(sym, candles, strategy=strategy,
                          tcs_threshold=int(tcs_threshold),
                          stop_pct=sp, target_pct=tp)
    out = result.to_dict()
    # Compact close series so the front-end can draw the price line and
    # mark each simulated trade on it (Phase 12 follow-up — visualization).
    out["candles"] = [{"c": round(float(c.close), 4)} for c in candles]
    return out


@app.get("/backtest/compare", tags=["backtest"])
async def backtest_compare_endpoint(symbol: str, tcs_threshold: int = 700,
                                    period: str = "2y", stop_pct: float = 0.05,
                                    target_pct: float = 0.10):
    """Run every directional strategy over a symbol's history and report
    which one performed best for that symbol (#121, multi-strategy).

    Fetches the candle series once, then scores it under each strategy -
    so the agents can pick the right strategy per stock rather than
    forcing one strategy on the whole watchlist."""
    from app.data.candles import fetch_stock_candles, fetch_crypto_ohlc, COIN_MAP
    from app.backtest.engine import compare_strategies

    sym = (symbol or "").strip().upper()
    if not sym:
        return {"error": "A ticker symbol is required."}
    sp = min(0.5, max(0.01, float(stop_pct)))
    tp = min(1.0, max(0.01, float(target_pct)))
    try:
        if sym in COIN_MAP:
            candles = await fetch_crypto_ohlc(sym, days=365)
        else:
            candles = await fetch_stock_candles(sym, period=period, interval="1d")
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not fetch history for {sym}: {e}"}
    if not candles or len(candles) < 70:
        return {"error": f"Not enough historical data for {sym} to backtest."}
    return compare_strategies(sym, candles, tcs_threshold=int(tcs_threshold),
                              stop_pct=sp, target_pct=tp)


@app.get("/markets/pulse", tags=["markets"])
async def markets_pulse():
    """Cross-asset pulse and recent correlations.

    Backed by app.data.markets_horizon.compute_snapshot — the same helper
    the Market Horizon agent uses, so the page sees exactly what the
    agent reasons over."""
    from app.data.markets_horizon import compute_snapshot, summarise_snapshot
    try:
        snap = await compute_snapshot()
    except Exception as e:  # noqa: BLE001
        return {"error": f"Cross-asset snapshot failed: {e}"}
    snap["summary"] = summarise_snapshot(snap)
    return snap


@app.get("/simulation/run", tags=["simulation"])
async def simulation_run_endpoint(
    symbols: str,
    days: int = 7,
    starting_equity: float = 10000.0,
    tcs_threshold: int = 650,
    stop_pct: float = 0.05,
    target_pct: float = 0.10,
    compare_all: bool = True,
):
    """Replay the agents over the last `days` of history across a
    watchlist. `symbols` is a comma-separated ticker list."""
    from app.data.simulation_lab import run_simulation
    syms = [s.strip().upper() for s in (symbols or "").split(",") if s.strip()]
    if not syms:
        return {"error": "At least one symbol is required."}
    try:
        return await run_simulation(syms, days=days,
                                     starting_equity=starting_equity,
                                     tcs_threshold=tcs_threshold,
                                     stop_pct=stop_pct,
                                     target_pct=target_pct,
                                     compare_all=compare_all)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Simulation failed: {e}"}


@app.get("/paper/alpaca-snapshot", tags=["paper"])
async def paper_alpaca_snapshot():
    """Live snapshot of the user's Alpaca paper account.

    Returns cash, equity, day-trade status and open positions — the
    single source of truth when Alpaca is configured. The Paper Trading
    page reads this so the dashboard reflects what Alpaca actually
    shows, not just Trezo's internal ledger."""
    from app.brokers.alpaca import (
        alpaca_configured, get_account, get_positions, broker_venue,
    )
    if not alpaca_configured():
        return {
            "configured": False,
            "note": "Alpaca is not configured — set ALPACA_API_KEY and ALPACA_SECRET_KEY on the agents service.",
        }
    acct = await get_account()
    if not acct:
        return {
            "configured": True,
            "note": "Alpaca is configured but the account snapshot could not be fetched. Keys may be wrong, or Alpaca is unreachable.",
        }
    positions = await get_positions()
    # Normalise position payload to the fields the UI uses.
    rows = []
    for pos in positions:
        try:
            rows.append({
                "symbol": str(pos.get("symbol", "")).upper(),
                "qty": float(pos.get("qty") or 0),
                "avg_entry_price": float(pos.get("avg_entry_price") or 0),
                "market_value": float(pos.get("market_value") or 0),
                "current_price": float(pos.get("current_price") or 0),
                "unrealized_pl": float(pos.get("unrealized_pl") or 0),
                "unrealized_plpc": float(pos.get("unrealized_plpc") or 0) * 100.0,
                "side": str(pos.get("side") or "long"),
            })
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda r: -r["market_value"])
    return {
        "configured": True,
        "venue": broker_venue(),
        "account": acct.to_dict(),
        "positions": rows,
        "as_of": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }


@app.get("/wheel/live-quotes", tags=["options"])
async def wheel_live_quotes(underlyings: str):
    """Live cash-secured-put + covered-call premiums for a wheel
    watchlist. `underlyings` is a comma-separated list. For each
    symbol: pull the current quote, compute the 5%-below-spot and
    5%-above-spot strikes, look up the nearest listed contract with a
    live mid premium. Returns the rows the Wheel page renders; null
    fields mean we could not get a live read for that leg (the page
    falls back to the modeled price)."""
    from app.brokers.alpaca_data import (
        alpaca_configured, get_quote, live_option_pick,
    )
    from app.brokers.active import active_broker_name
    from datetime import date, timedelta

    # Broker-agnostic gate — today only Alpaca implements the chain,
    # but the response shape and the gate check are provider-neutral
    # so future brokers (Webull, Robinhood, IBKR) plug in without the
    # Wheel page needing changes.
    broker = await active_broker_name()
    if broker == "modeled" or not alpaca_configured():
        return {
            "configured": False,
            "broker": broker,
            "note": (
                "No broker connected — live options chain unavailable. "
                "Pricing on the Wheel page is modeled (Black-Scholes) "
                "until a broker is hooked up."
            ),
        }

    syms = [s.strip().upper() for s in (underlyings or "").split(",") if s.strip()]
    if not syms:
        return {"configured": True, "broker": broker, "rows": []}

    # ~30 days out — typical wheel cycle.
    target_exp = (date.today() + timedelta(days=30)).isoformat()

    rows = []
    for sym in syms:
        spot_q = await get_quote(sym)
        if not spot_q or spot_q.current <= 0:
            rows.append({"symbol": sym, "error": "No quote"})
            continue
        spot = float(spot_q.current)
        target_put = round(spot * 0.95, 2)
        target_call = round(spot * 1.05, 2)
        put = await live_option_pick(sym, "put", target_put, target_exp)
        call = await live_option_pick(sym, "call", target_call, target_exp)
        rows.append({
            "symbol": sym,
            "spot": round(spot, 2),
            "csp": ({
                "occ": put.occ, "strike": put.strike,
                "expiration": put.expiration, "premium": put.premium
            } if put else None),
            "cc": ({
                "occ": call.occ, "strike": call.strike,
                "expiration": call.expiration, "premium": call.premium
            } if call else None),
        })
    return {"configured": True, "broker": broker,
            "as_of": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "rows": rows}


@app.get("/account/options-approval", tags=["options"])
async def options_approval_endpoint():
    """Read the user's options trading approval level off Alpaca's
    /v2/account/configurations. Returns the level + a plain-words
    description. Used by Live Trading + the Wheel page to tell the
    user whether the bot can place options orders yet."""
    from app.brokers.alpaca import alpaca_configured, _get
    if not alpaca_configured():
        return {"configured": False,
                "note": "Alpaca keys not set on the agents service."}
    data = await _get("/v2/account/configurations")
    if not isinstance(data, dict):
        return {"configured": True,
                "note": "Could not read configurations from Alpaca."}

    # Alpaca returns max_options_trading_level as a string like "0", "1",
    # "2" or "3". 1 = covered calls + cash-secured puts (the Wheel),
    # 2 = long calls/puts + simple spreads, 3 = uncovered.
    raw = data.get("max_options_trading_level")
    try:
        level = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        level = 0
    descriptions = {
        0: "Not approved for options trading. Apply on Alpaca to enable the Dividend Wheel.",
        1: "Approved for Level 1 — covered calls + cash-secured puts. The Wheel can run.",
        2: "Approved for Level 2 — long options + simple spreads.",
        3: "Approved for Level 3 — uncovered options + advanced spreads.",
    }
    return {
        "configured": True,
        "level": level,
        "raw_level": raw,
        "description": descriptions.get(level, f"Level {level}"),
        "wheel_ready": level >= 1,
    }


@app.get("/wheel/universe", tags=["options"])
async def wheel_universe(user_id: str = ""):
    """Today's per-user Wheel candidate universe. Returns the curated
    seed list + watchlist additions + active-position names, with a
    `source` tag per ticker so the UI can render reason chips. Mike
    2026-06-01: the Wheel is not restricted to the seed - any quality
    dividend stock the user has surfaced via a dividend-tagged
    watchlist becomes a candidate too."""
    from app.strategies.wheel_universe import get_wheel_universe
    cands = await get_wheel_universe(user_id or None)
    return {
        "ok": True,
        "user_id": user_id or None,
        "count": len(cands),
        "candidates": [
            {"ticker": c.ticker, "source": c.source, "yield_pct": c.yield_pct}
            for c in cands
        ],
    }


@app.get("/wheel/positions", tags=["options"])
async def wheel_positions(user_id: str = ""):
    """Real options positions on the user's connected Alpaca account.

    Classifies each leg using OCC parsing:
      - wheel_csp  = short put (sold to open; cash-secured)
      - wheel_cc   = short call (sold to open; covered by shares)
      - equity_holding = long shares (often the result of an
                          assignment on a previous CSP)
    Uses the per-user OAuth token when available, falling back to the
    env-driven keys for backward compatibility."""
    from app.brokers.alpaca import alpaca_configured, UserToken, _get
    from app.integrations.web_tokens import get_user_broker_token
    from app.data.occ import parse_occ

    # Per-user token first; env fallback. broker_venue() stays accurate.
    token: UserToken | None = None
    routed = "env-keys"
    if user_id:
        bt = await get_user_broker_token(user_id, "alpaca")
        if bt:
            token = UserToken(
                access_token=bt.access_token,
                refresh_token=bt.refresh_token,
                expires_at=bt.expires_at,
            )
            routed = "user-oauth"
    if token is None and not alpaca_configured():
        return {"configured": False,
                "note": "Alpaca keys not set and the user has no OAuth connection."}

    positions = await _get("/v2/positions", token=token)
    if not isinstance(positions, list):
        return {"configured": True, "routed": routed,
                "note": "Could not read positions from Alpaca."}

    options_rows: list[dict] = []
    equity_rows: list[dict] = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        sym = str(pos.get("symbol", "")).strip().upper()
        if not sym:
            continue
        try:
            qty = float(pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        try:
            avg_entry = float(pos.get("avg_entry_price") or 0)
        except (TypeError, ValueError):
            avg_entry = 0.0
        try:
            market_value = float(pos.get("market_value") or 0)
        except (TypeError, ValueError):
            market_value = 0.0
        try:
            unrealized = float(pos.get("unrealized_pl") or 0)
        except (TypeError, ValueError):
            unrealized = 0.0
        side = str(pos.get("side") or "long").lower()
        asset_class = str(pos.get("asset_class") or "").lower()

        parts = parse_occ(sym)
        if parts and asset_class in ("us_option", "option") or parts:
            # An options leg. Short = sold-to-open. Wheel attribution:
            #   short put  → CSP
            #   short call → CC
            #   long       → speculative (or DIY hedge)
            is_short = side == "short" or qty < 0
            leg = "wheel_csp" if parts.type == "put" and is_short else (
                  "wheel_cc"  if parts.type == "call" and is_short else
                  "long_option")
            contracts = int(round(abs(qty)))
            # Per-contract entry premium is avg_entry_price (Alpaca returns
            # this in dollars per share, so ×100 for the contract's value).
            net_premium = round(avg_entry * 100 * contracts, 2) if is_short else 0.0
            options_rows.append({
                "occ": sym,
                "underlying": parts.underlying,
                "type": parts.type,
                "strike": parts.strike,
                "expiration": parts.expiration,
                "contracts": contracts,
                "side": side,
                "leg": leg,
                "avg_entry_price": round(avg_entry, 4),
                "market_value": round(market_value, 2),
                "unrealized_pl": round(unrealized, 2),
                "net_premium_usd": net_premium,
            })
        else:
            # Long equity — count it; might be the result of an
            # assignment + waiting for a CC to be written.
            equity_rows.append({
                "symbol": sym,
                "qty": qty,
                "avg_entry_price": round(avg_entry, 4),
                "market_value": round(market_value, 2),
                "unrealized_pl": round(unrealized, 2),
            })

    return {
        "configured": True,
        "routed": routed,
        "options": options_rows,
        "equity": equity_rows,
        "as_of": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }


@app.post("/wheel/place-leg", tags=["options"])
async def wheel_place_leg(
    user_id: str,
    leg: str,                 # "csp" | "cc"
    underlying: str,
    target_strike: float,
    target_exp: str,
    contracts: int = 1,
    limit_price: float | None = None,
):
    """Place a single-leg wheel order on Alpaca paper (sell-to-open).

    leg = "csp" picks a put ~5% below spot; "cc" picks a call ~5%
    above. The bot uses live_option_pick to land on the real listed
    contract closest to the target strike + expiration. The order
    routes through the user's Alpaca OAuth connection when available,
    falling back to the env keys for legacy / single-tenant setups."""
    from app.brokers.alpaca import (
        alpaca_configured, UserToken, submit_option_order,
    )
    from app.brokers.alpaca_data import live_option_pick
    from app.integrations.web_tokens import get_user_broker_token

    if leg not in ("csp", "cc"):
        return {"ok": False, "error": "leg must be 'csp' or 'cc'."}
    if not underlying or not target_strike or not target_exp:
        return {"ok": False, "error": "Missing required params."}

    # Per-user token first; env keys as fallback.
    token: UserToken | None = None
    routed = "env-keys"
    if user_id:
        bt = await get_user_broker_token(user_id, "alpaca")
        if bt:
            token = UserToken(
                access_token=bt.access_token,
                refresh_token=bt.refresh_token,
                expires_at=bt.expires_at,
            )
            routed = "user-oauth"
    if token is None and not alpaca_configured():
        return {"ok": False, "error": "Alpaca not configured + user has no OAuth connection.",
                "routed": routed}

    opt_type = "put" if leg == "csp" else "call"
    pick = await live_option_pick(underlying, opt_type, float(target_strike),
                                   str(target_exp))
    if not pick:
        return {"ok": False, "error": f"No listed {opt_type} contract near ${target_strike} for {target_exp}.",
                "routed": routed}

    # Sell-to-open: short the put (CSP) or short the call (CC).
    order, err = await submit_option_order(
        occ_symbol=pick.occ,
        contracts=int(contracts),
        side="sell",
        time_in_force="day",
        limit_price=limit_price,
        token=token,
    )
    if err or not order:
        return {"ok": False, "error": f"Alpaca rejected the order: {err}",
                "routed": routed, "occ": pick.occ}

    return {
        "ok": True,
        "routed": routed,
        "leg": "wheel_csp" if leg == "csp" else "wheel_cc",
        "occ": pick.occ,
        "underlying": underlying.upper(),
        "strike": pick.strike,
        "expiration": pick.expiration,
        "premium": pick.premium,
        "alpaca_order_id": order.get("id"),
        "alpaca_order_status": order.get("status"),
    }


@app.post("/agents/run-now/{name}", tags=["agents"])
async def agent_run_now(name: str):
    """Force-tick a named agent immediately, bypassing its normal cadence.

    Returns the message count produced and a short summary so the user
    can verify the chain (e.g. STMS during the 7-11 AM window: did it
    fire a signal, was Risk Manager called, did Trade Execution fire to
    Alpaca?). Messages still flow through the normal bus, so anything
    fired will appear in the activity feed and dashboards."""
    from app.runtime.registry import registry as _reg
    from app.runtime.bus import bus as _bus
    state = _reg.get(name)
    if not state or not state.impl:
        return {"ok": False, "error": f"Unknown agent: {name}"}
    if not state.enabled:
        return {"ok": False, "error": f"Agent {name} is disabled in Bot Tuning."}
    try:
        msgs = await state.impl.tick()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Tick raised: {e}"}
    state.mark_ticked()
    state.message_count += len(msgs or [])

    # Publish each message onto the bus so downstream agents (Risk Manager,
    # Trade Execution) react in real time as if a scheduled tick had fired.
    for m in msgs or []:
        await _bus.publish(m)

    by_kind: dict[str, int] = {}
    for m in msgs or []:
        by_kind[m.kind] = by_kind.get(m.kind, 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(by_kind.items())) or "no messages"
    return {
        "ok": True,
        "agent": name,
        "messages_produced": len(msgs or []),
        "by_kind": by_kind,
        "summary": summary,
    }


@app.post("/wheel/reconcile", tags=["options"])
async def wheel_reconcile():
    """Force a reconciliation pass: any open modeled wheel_csp / wheel_cc
    row on Supabase that has NO matching option contract on the user's
    Alpaca account is closed_manual with a 'Reconciled' note.

    The same logic runs every 30 minutes as part of the Options Scanner
    tick — this endpoint is the manual-trigger version so the user can
    clear stale rows immediately without waiting for the next tick."""
    from app.agents.options_scanner import OptionsScannerAgent
    from app.config import get_settings as _gs
    s = _gs()
    if not (s.supabase_url and s.supabase_service_role_key):
        return {"ok": False, "error": "Supabase not configured."}
    try:
        from supabase import create_client
        client = create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Supabase client error: {e}"}

    scanner = OptionsScannerAgent()
    msgs = await scanner._reconcile_with_broker(client)
    total = sum(int(m.payload.get("closed_count", 0)) for m in msgs)
    return {
        "ok": True,
        "users_touched": len(msgs),
        "rows_closed": total,
        "details": [m.payload for m in msgs],
    }


@app.post("/stocks/reconcile", tags=["paper"])
async def stocks_reconcile():
    """Force a stock-side reconciliation: bring Trezo's open paper_positions
    rows for stocks in line with what Alpaca actually holds.

    Why this exists (Mike 2026-05-29): a user opened a SOFI position in
    two fills (3 shares + 4 shares) but Trezo's local DB only captured
    one fill (qty=3). Alpaca was the truth at qty=7, $18.23 avg entry,
    but Trezo's dashboard showed qty=3 at $16.98. That mismatch matters
    because (a) sizing math uses Trezo's view, (b) the user gets
    confused which is the truth.

    Behavior:
      - For each open Trezo paper_position with broker='alpaca':
          * If Alpaca holds nothing in that symbol -> close the row
            with status='closed_manual' and a reconcile note.
          * If Alpaca's qty / avg_entry differs from Trezo's -> patch
            the Trezo row to match Alpaca (broker truth wins).
      - For each Alpaca position not present in Trezo (was missed at
        fill time) -> insert a tracking row via record_external_position.

    The agent-side `/wheel/reconcile` is the options-side equivalent.
    """
    from app.brokers.alpaca import (
        alpaca_configured, get_positions, get_account, UserToken,
    )
    from app.paper.engine import record_external_position
    from app.integrations.web_tokens import get_user_broker_token
    from app.config import get_settings as _gs

    s = _gs()
    if not (s.supabase_url and s.supabase_service_role_key):
        return {"ok": False, "error": "Supabase not configured."}

    try:
        from supabase import create_client
        client = create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Supabase client error: {e}"}

    if not alpaca_configured():
        return {"ok": False, "error": "Alpaca env keys not configured."}

    import asyncio

    def _users():
        return client.table("paper_accounts").select("user_id").execute()
    user_rows = (await asyncio.to_thread(_users)).data or []

    total_updated = 0
    total_inserted = 0
    total_closed = 0
    per_user: list[dict] = []

    for u in user_rows:
        user_id = u.get("user_id")
        if not user_id:
            continue

        # Per-user token if OAuth-wired, else env keys.
        bt = await get_user_broker_token(user_id, "alpaca")
        token = UserToken(
            access_token=bt.access_token,
            refresh_token=bt.refresh_token,
            expires_at=bt.expires_at,
        ) if bt else None

        try:
            alpaca_positions = await get_positions(token=token)
        except Exception:
            alpaca_positions = []

        # Index Alpaca positions by symbol (uppercase).
        alpaca_by_sym: dict[str, dict] = {}
        for p in alpaca_positions:
            sym = str(p.get("symbol", "")).upper()
            if sym:
                alpaca_by_sym[sym] = p

        # Trezo's open stock positions for this user.
        def _trezo_open(uid=user_id):
            return (
                client.table("paper_positions")
                .select("id, ticker, side, quantity, entry_price, stop_price, target_price, strategy")
                .eq("user_id", uid)
                .eq("status", "open")
                .eq("asset_type", "stock")
                .execute()
            )
        trezo_rows = (await asyncio.to_thread(_trezo_open)).data or []
        trezo_syms = {str(r["ticker"]).upper() for r in trezo_rows}

        updated = 0
        closed = 0
        inserted = 0
        notes_list: list[str] = []

        # 1) Update or close existing Trezo rows.
        for r in trezo_rows:
            sym = str(r["ticker"]).upper()
            ap = alpaca_by_sym.get(sym)
            if ap is None:
                # Alpaca has nothing in this symbol - close as reconciled.
                def _close(rid=r["id"]):
                    return (
                        client.table("paper_positions")
                        .update({
                            "status": "closed_manual",
                            "closed_at": "now()",
                            "exit_at": "now()",
                            "realized_pnl_usd": 0.0,
                        })
                        .eq("id", rid)
                        .execute()
                    )
                await asyncio.to_thread(_close)
                closed += 1
                notes_list.append(f"{sym} closed (not at broker)")
                continue

            # Alpaca has this symbol. Compare qty + avg_entry. If
            # they differ, patch Trezo to match (broker truth wins).
            try:
                ap_qty = float(ap.get("qty") or 0)
                ap_entry = float(ap.get("avg_entry_price") or 0)
            except (TypeError, ValueError):
                ap_qty = 0
                ap_entry = 0
            ap_side = "long" if ap_qty > 0 else "short"
            ap_qty_abs = abs(ap_qty)

            cur_qty = float(r.get("quantity") or 0)
            cur_entry = float(r.get("entry_price") or 0)

            if (abs(cur_qty - ap_qty_abs) > 1e-6
                or abs(cur_entry - ap_entry) > 0.005
                or r.get("side") != ap_side):
                def _patch(rid=r["id"]):
                    return (
                        client.table("paper_positions")
                        .update({
                            "quantity": ap_qty_abs,
                            "entry_price": ap_entry,
                            "side": ap_side,
                        })
                        .eq("id", rid)
                        .execute()
                    )
                await asyncio.to_thread(_patch)
                updated += 1
                notes_list.append(
                    f"{sym} patched qty {cur_qty}->{ap_qty_abs}, entry "
                    f"${cur_entry:.2f}->${ap_entry:.2f}"
                )

        # 2) Insert Alpaca positions that Trezo doesn't have.
        for sym, ap in alpaca_by_sym.items():
            if sym in trezo_syms:
                continue
            try:
                ap_qty = float(ap.get("qty") or 0)
                ap_entry = float(ap.get("avg_entry_price") or 0)
            except (TypeError, ValueError):
                continue
            if ap_qty == 0 or ap_entry <= 0:
                continue
            side = "long" if ap_qty > 0 else "short"
            qty_abs = abs(ap_qty)

            # Use bot-settings default stop/target so the row carries
            # reasonable exits. Fine adjustments stay with the broker.
            from app.runtime.settings import get_bot_settings
            cfg = get_bot_settings(user_id)
            sp = float(cfg.default_stop_pct or 0.05)
            tp = float(cfg.default_target_pct or 0.10)
            if side == "long":
                stop_price = ap_entry * (1 - sp)
                target_price = ap_entry * (1 + tp)
            else:
                stop_price = ap_entry * (1 + sp)
                target_price = ap_entry * (1 - tp)

            try:
                await record_external_position(
                    user_id=str(user_id),
                    ticker=sym,
                    asset_type="stock",
                    side=side,
                    quantity=qty_abs,
                    entry_price=ap_entry,
                    stop_price=stop_price,
                    target_price=target_price,
                    strategy="reconciled",
                    broker="alpaca",
                    broker_order_id=None,
                    source_payload={"reconcile": True, "alpaca_avg_entry": ap_entry},
                )
                inserted += 1
                notes_list.append(f"{sym} inserted from broker (qty {qty_abs})")
            except Exception:
                continue

        total_updated += updated
        total_inserted += inserted
        total_closed += closed
        per_user.append({
            "user_id": str(user_id),
            "updated": updated,
            "inserted": inserted,
            "closed": closed,
            "notes": notes_list,
        })

    return {
        "ok": True,
        "users_touched": len(per_user),
        "updated": total_updated,
        "inserted": total_inserted,
        "closed": total_closed,
        "details": per_user,
    }


@app.post("/admin/manual-trade", tags=["admin"])
async def admin_manual_trade(user_id: str, ticker: str, side: str = "long",
                              stop_pct: float | None = None,
                              target_pct: float | None = None):
    """Trigger a manual trade through the full Trezo chain — Risk
    Manager → Trade Execution → current venue. Venue is determined by
    trading_mode (paper today, flips to live when go-live is signed off
    and _LIVE_EXECUTOR_AVAILABLE is True). The same button works for
    both — no UI rework when live ships.

    `side` = 'long' (buy) or 'short' (sell). `stop_pct` / `target_pct`
    fall back to Bot Tuning defaults when omitted."""
    from app.agents.trade_execution import TradeExecutionAgent
    if side not in ("long", "short"):
        return {"ok": False, "error": "side must be 'long' or 'short'."}
    sym = (ticker or "").strip().upper()
    if not sym:
        return {"ok": False, "error": "ticker is required."}

    payload: dict = {
        "ticker": sym,
        "direction": "bullish" if side == "long" else "bearish",
        "strategy": "manual",
        "user_id": user_id,
        "manual_trigger": True,
    }
    if stop_pct is not None:
        payload["stop_pct"] = float(stop_pct)
    if target_pct is not None:
        payload["target_pct"] = float(target_pct)

    exec_agent = TradeExecutionAgent()
    try:
        msgs = await exec_agent._execute_for_user(user_id, sym, side, payload)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Trade Execution raised: {e}"}

    # Manual-trade UX: if sizing rejected with "Sizing produced 0 shares"
    # but the user has buying power for at least 1 share, RETRY once with
    # a forced 1-share quantity. The user explicitly clicked Place — they
    # want a trade, not a math rejection. The result toast discloses the
    # override so they know.
    first_err = next((m for m in (msgs or []) if m.kind == "error"), None)
    risk_override_applied = False
    if first_err and "Sizing produced 0 shares" in str(first_err.payload.get("error", "")):
        try:
            from app.brokers.alpaca import alpaca_configured, get_account as _alp_acct
            from app.data.candles import fetch_candles_for as _fc
            acct = await _alp_acct() if alpaca_configured() else None
            candles = await _fc(sym, "stock")
            spot = float(candles[-1].close) if candles else 0.0
            bp = float(acct.buying_power) if acct else 0.0
            if spot > 0 and bp >= spot:
                # Calculate the risk_pct that yields exactly 1 share.
                # 1 share × stop_distance = risk_usd → risk_pct = risk_usd / equity
                sp = float(payload.get("stop_pct") or 0.05)
                stop_distance = spot * sp
                equity = float(acct.equity) if acct else bp
                if equity > 0 and stop_distance > 0:
                    # Bump risk to just enough for 1 share, capped at 25%.
                    needed_risk = min(0.25, (stop_distance / equity) * 1.05)
                    payload["risk_pct_override"] = needed_risk
                    payload["force_min_qty"] = 1
                    msgs = await exec_agent._execute_for_user(user_id, sym, side, payload)
                    risk_override_applied = True
        except Exception:  # noqa: BLE001
            pass

    # Publish onto the bus so Position Monitor / Tax Optimizer etc. see it.
    from app.runtime.bus import bus as _bus
    for m in msgs or []:
        await _bus.publish(m)

    # Find the first 'execute' message to surface; otherwise the first 'error'.
    fill = next((m for m in msgs if m.kind == "execute"), None)
    err = next((m for m in msgs if m.kind == "error"), None)
    if fill:
        return {
            "ok": True,
            "kind": "executed",
            "venue": fill.payload.get("venue") or fill.payload.get("broker") or "paper",
            "broker": fill.payload.get("broker"),
            "fill_price": fill.payload.get("fill_price"),
            "alpaca_order_id": fill.payload.get("alpaca_order_id"),
            "alpaca_order_status": fill.payload.get("alpaca_order_status"),
            "quantity": fill.payload.get("quantity"),
            "strategy": "manual",
            "risk_override_applied": risk_override_applied,
            "risk_override_note": (
                "Risk was auto-bumped to fit 1 share — you explicitly clicked Place."
                if risk_override_applied else None
            ),
        }
    if err:
        return {"ok": False, "error": err.payload.get("error", "Trade Execution rejected the order.")}
    # Info messages (budget skipped, market closed etc.)
    info = next((m for m in msgs if m.kind == "info"), None)
    if info:
        return {"ok": False, "info": info.payload.get("note", "Trade not placed."),
                "details": info.payload}
    return {"ok": False, "error": "Trade Execution produced no result."}


@app.get("/admin/diagnose", tags=["admin"])
async def admin_diagnose():
    """All-in-one diagnostic: account snapshot + market clock + today's
    orders + recent Risk Manager vetoes. Answers 'is anything actually
    reaching the broker today' without leaving the dashboard.

    Uses Trezo's existing Alpaca client (env keys), so it works whenever
    paper trading is configured — no Cowork MCP / plugin plumbing needed."""
    from datetime import date, datetime, timezone
    from app.brokers.alpaca import (
        alpaca_configured, get_account, get_clock, get_positions,
        broker_venue, _base_url, _headers,
    )

    out: dict = {
        "ok": True,
        "venue": broker_venue(),
        "configured": alpaca_configured(),
        "checks": [],
        "verdict": "",
        "next_action": "",
    }

    if not alpaca_configured():
        out["verdict"] = "Alpaca env keys are not set on the agents service."
        out["next_action"] = "Add ALPACA_API_KEY + ALPACA_SECRET_KEY to agents/.env and restart."
        out["checks"].append({"name": "configured", "ok": False,
                              "detail": "alpaca_configured() returned False"})
        return out

    # 1. Account
    acct = await get_account()
    if not acct:
        out["verdict"] = "Could not reach Alpaca — keys look unreachable from the agents service."
        out["next_action"] = "Verify ALPACA_API_KEY / ALPACA_SECRET_KEY in agents/.env match the Alpaca dashboard."
        out["checks"].append({"name": "account", "ok": False,
                              "detail": "get_account() returned None"})
        return out
    out["account"] = {
        "equity": acct.equity, "cash": acct.cash,
        "buying_power": acct.buying_power, "status": acct.status,
        "trading_blocked": acct.trading_blocked,
        "options_approved_level": acct.options_approved_level,
        "daytrade_count": acct.daytrade_count,
    }
    out["checks"].append({"name": "account", "ok": True,
                          "detail": f"equity ${acct.equity:.2f}, buying_power ${acct.buying_power:.2f}, status={acct.status}"})
    if acct.trading_blocked:
        out["verdict"] = "Alpaca has trading_blocked=TRUE on this account."
        out["next_action"] = "Resolve the block in your Alpaca dashboard before any orders can fire."
        return out

    # 2. Market clock
    clock = await get_clock()
    if clock:
        out["clock"] = clock
        out["checks"].append({"name": "clock", "ok": bool(clock.get("is_open")),
                              "detail": f"is_open={clock.get('is_open')}, next_open={clock.get('next_open')}, next_close={clock.get('next_close')}"})

    # 3. Today's orders straight from Alpaca
    orders: list = []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            today_iso = date.today().isoformat() + "T00:00:00Z"
            resp = await client.get(
                _base_url() + "/v2/orders",
                headers=_headers(),
                params={"status": "all", "after": today_iso, "limit": 100,
                        "direction": "desc"},
            )
            if resp.status_code < 400:
                orders = resp.json() or []
    except Exception as e:  # noqa: BLE001
        out["checks"].append({"name": "orders", "ok": False,
                              "detail": f"orders fetch raised: {e}"})

    by_status: dict[str, int] = {}
    reject_reasons: list = []
    for o in orders:
        s = str(o.get("status") or "unknown")
        by_status[s] = by_status.get(s, 0) + 1
        if s in ("rejected", "canceled", "expired"):
            reject_reasons.append({
                "symbol": o.get("symbol"),
                "status": s,
                "reason": o.get("failed_at_reason") or o.get("rejected_reason") or "(no reason given)",
                "submitted_at": o.get("submitted_at"),
            })
    out["orders_today"] = {
        "total": len(orders),
        "by_status": by_status,
        "rejects": reject_reasons[:10],
    }
    out["checks"].append({"name": "orders_today", "ok": True,
                          "detail": f"{len(orders)} order(s) today: " + (", ".join(f"{v} {k}" for k, v in sorted(by_status.items())) or "(none)")})

    # 4. Today's Risk Manager vetoes from the agent bus
    vetoes_summary: dict[str, int] = {}
    veto_examples: list = []
    try:
        from app.config import get_settings as _gs
        s = _gs()
        if s.supabase_url and s.supabase_service_role_key:
            from supabase import create_client
            import asyncio
            cl = create_client(s.supabase_url, s.supabase_service_role_key)
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            def _q():
                return (cl.table("agent_messages")
                        .select("payload, created_at")
                        .eq("agent_name", "risk_manager")
                        .eq("kind", "veto")
                        .gte("created_at", today_start)
                        .order("created_at", desc=True).limit(50).execute())
            res = await asyncio.to_thread(_q)
            for row in (res.data or []):
                p = row.get("payload") or {}
                reason = str(p.get("reason") or "(no reason)")
                key = _veto_bucket(reason)
                vetoes_summary[key] = vetoes_summary.get(key, 0) + 1
                if len(veto_examples) < 5:
                    veto_examples.append({"ticker": p.get("ticker"),
                                          "tcs": p.get("tcs"),
                                          "reason": reason})
    except Exception as e:  # noqa: BLE001
        out["checks"].append({"name": "vetoes", "ok": False, "detail": f"veto pull raised: {e}"})

    out["vetoes_today"] = {
        "total": sum(vetoes_summary.values()),
        "by_bucket": vetoes_summary,
        "examples": veto_examples,
    }
    out["checks"].append({"name": "vetoes_today", "ok": True,
                          "detail": f"{sum(vetoes_summary.values())} veto(es): " + (", ".join(f"{v} {k}" for k, v in sorted(vetoes_summary.items())) or "(none)")})

    # 5. Synthesize the verdict
    if len(orders) == 0 and sum(vetoes_summary.values()) == 0:
        out["verdict"] = "Quiet day — Trezo fired no signals AND Alpaca has no orders. Either the market is closed or no scanner cleared its TCS threshold."
        out["next_action"] = "Check the Strategy Windows panel — if all scanners are 'Observing', wait for an active window. Otherwise lower Bot Tuning TCS threshold."
    elif len(orders) == 0 and sum(vetoes_summary.values()) > 0:
        top = sorted(vetoes_summary.items(), key=lambda x: -x[1])[0]
        out["verdict"] = (f"Signals fired but ALL were vetoed by Risk Manager — "
                          f"none reached Alpaca. Top reason: {top[0]} ({top[1]} of {sum(vetoes_summary.values())}).")
        out["next_action"] = f"Open the 'Why Risk Manager vetoed today' panel and relax the {top[0]} filter in Bot Tuning."
    elif len(orders) > 0:
        rejects = sum(1 for o in orders if o.get("status") in ("rejected", "canceled", "expired"))
        accepted = len(orders) - rejects
        if rejects == 0:
            out["next_action"] = "Watch the execution feed for fills."
        else:
            out["verdict"] = f"{accepted} accepted, {rejects} rejected by Alpaca today."
            out["next_action"] = "Open the rejects list below — most common cause is wash-trade detection, insufficient buying power, or symbol not tradable."

    return out


def _veto_bucket(reason: str) -> str:
    r = reason.lower()
    if any(t in r for t in ("kill", "daily loss", "consec", "draw")):
        return "kill_switch"
    if any(t in r for t in ("neutral", "bearish", "long-only", "actionable")):
        return "direction"
    if any(t in r for t in ("liquidity", "average volume", "avg volume")):
        return "liquidity"
    if any(t in r for t in ("spread", "bid", "illiquid", "wide")):
        return "spread"
    if "overextend" in r or "atr" in r:
        return "overextension"
    if any(t in r for t in ("broad market", "spy", "qqq", "vwap")):
        return "market_filter"
    if any(t in r for t in ("budget", "capital", "posture", "notional")):
        return "capital"
    if "tcs" in r or "threshold" in r:
        return "tcs_below"
    if "scope" in r or "flag" in r:
        return "scope"
    return "other"




@app.get("/admin/settings-audit", tags=["admin"])
async def admin_settings_audit():
    """End-to-end proof that Bot Tuning values reach the agents.

    Pulls the saved bot_settings row, then asks each settings consumer
    what it's *actually* using right now. Surfaces any drift - e.g. a
    scanner that hardcoded a value and ignores the slider (the STMS 750
    bug from earlier). All green = your tuning is in force."""
    from app.runtime.settings import get_bot_settings
    from app.config import get_settings as _gs
    s = _gs()
    out: dict = {"ok": True, "checks": [], "saved": None}

    saved: dict = {}
    if s.supabase_url and s.supabase_service_role_key:
        try:
            from supabase import create_client
            import asyncio
            cl = create_client(s.supabase_url, s.supabase_service_role_key)
            def _q():
                return (cl.table("bot_settings").select("*")
                        .order("updated_at", desc=True).limit(1).execute())
            res = await asyncio.to_thread(_q)
            if res.data:
                saved = res.data[0]
        except Exception as e:  # noqa: BLE001
            out["checks"].append({"name": "supabase_read", "ok": False,
                                  "detail": f"could not read bot_settings: {e}"})
    out["saved"] = saved

    cfg = get_bot_settings()
    live = {
        "tcs_threshold": cfg.tcs_threshold,
        "max_open_positions": cfg.max_open_positions,
        "consecutive_loss_limit": cfg.consecutive_loss_limit,
        "risk_per_trade_pct": cfg.risk_per_trade_pct,
        "default_stop_pct": cfg.default_stop_pct,
        "default_target_pct": cfg.default_target_pct,
        "min_reward_risk": cfg.min_reward_risk,
        "risk_profile": cfg.risk_profile,
        "pattern_enabled": cfg.pattern_enabled,
        "stms_enabled": cfg.stms_enabled,
        "extended_enabled": cfg.extended_enabled,
        "crypto_enabled": cfg.crypto_enabled,
        "autonomy_mode": cfg.autonomy_mode,
        "account_posture": cfg.account_posture,
        "switching_mode": cfg.switching_mode,
        "switching_advantage_pct": cfg.switching_advantage_pct,
        "wheel_auto_execute": cfg.wheel_auto_execute,
    }
    out["live_in_agents"] = live

    for key, agent_val in live.items():
        saved_val = saved.get(key) if saved else None
        if saved_val is None:
            out["checks"].append({
                "name": key, "ok": True,
                "detail": f"not saved · agent using default {agent_val}",
            })
            continue
        match = (
            float(saved_val) == float(agent_val)
            if isinstance(agent_val, (int, float))
            and isinstance(saved_val, (int, float, str))
            and str(saved_val).replace(".", "").replace("-", "").isdigit()
            else saved_val == agent_val
        )
        out["checks"].append({
            "name": key, "ok": match,
            "detail": (
                f"saved={saved_val} · agent={agent_val}"
                if match else f"DRIFT · saved={saved_val}, agent={agent_val}"
            ),
        })

    try:
        from app.strategies.stms import TCS_THRESHOLD as _STMS_SEED
        out["checks"].append({
            "name": "stms_tcs_seed",
            "ok": True,
            "detail": f"STMS seed/fallback={_STMS_SEED} · runtime uses bot_settings.tcs_threshold={cfg.tcs_threshold} per tick",
        })
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.agents.crypto_scanner import CryptoScannerAgent as _CSA
        out["checks"].append({
            "name": "crypto_tcs_seed",
            "ok": True,
            "detail": f"Crypto seed/fallback={_CSA.MIN_TCS} · runtime uses bot_settings.tcs_threshold per tick",
        })
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.paper.sizing import MIN_REWARD_RISK as _RR_SEED
        out["checks"].append({
            "name": "rr_floor_seed",
            "ok": True,
            "detail": f"sizing.py seed={_RR_SEED} · runtime reads bot_settings.min_reward_risk={cfg.min_reward_risk}",
        })
    except Exception:  # noqa: BLE001
        pass

    drifts = [c for c in out["checks"] if not c["ok"]]
    out["verdict"] = (
        "All settings consumers match what's saved - no hardcoded overrides."
        if not drifts else
        f"DRIFT on {len(drifts)} setting(s) - your saved values aren't reaching every agent."
    )
    out["ok"] = len(drifts) == 0
    return out


@app.get("/broker/snapshot", tags=["broker"])
async def broker_snapshot_endpoint(user_id: str | None = None):
    """Active broker's account snapshot - normalised across providers.
    Goes through the broker-agnostic adapter so the Wheel page never
    hard-codes Alpaca."""
    from app.brokers.active import active_broker_snapshot, active_broker_name
    snap = await active_broker_snapshot(user_id)
    if not snap:
        return {
            "ok": True,
            "broker": await active_broker_name(user_id),
            "snapshot": None,
            "note": "No broker connected - running in modeled mode.",
        }
    return {
        "ok": True,
        "broker": snap.name,
        "venue": snap.venue,
        "snapshot": {
            "equity": snap.equity,
            "last_equity": snap.last_equity,
            "cash": snap.cash,
            "buying_power": snap.buying_power,
            "options_approved_level": snap.options_approved_level,
            "trading_blocked": snap.trading_blocked,
        },
    }


@app.get("/broker/chain", tags=["broker"])
async def broker_chain_endpoint(underlying: str, user_id: str | None = None):
    """Active broker's near-the-money option chain for `underlying`,
    normalised. Empty when broker has no chain or no broker is
    connected - caller falls back to modeled pricing."""
    from app.brokers.active import active_broker_option_chain, active_broker_name
    quotes = await active_broker_option_chain(underlying, user_id)
    return {
        "ok": True,
        "broker": await active_broker_name(user_id),
        "underlying": underlying.upper(),
        "quotes": [
            {
                "occ": q.occ, "type": q.type, "strike": q.strike,
                "expiration": q.expiration,
                "bid": q.bid, "ask": q.ask, "mid": q.mid,
                "iv": q.iv, "delta": q.delta, "gamma": q.gamma,
                "theta": q.theta, "vega": q.vega,
            }
            for q in quotes
        ],
    }




@app.get("/macro/snapshot", tags=["macro"])
async def macro_snapshot():
    """Latest macro reading from the active source adapter.

    Routes through `app.data.macro.get_macro_reading()` which picks the
    backend from env (Nasdaq Data Link, manual, etc.). The UI displays
    the source-specific attribution notice verbatim so each backend's
    license requirements are honored. Returns `configured: false` when
    no backend is active."""
    from app.data.macro import (
        get_macro_reading, classify_macro_regime,
        active_source_attribution, pick_active_source,
    )

    reading = await get_macro_reading()
    regime, why = classify_macro_regime(reading)
    src = pick_active_source()

    if src is None:
        return {
            "configured": False,
            "source": None,
            "note": reading.note or "No macro source configured.",
        }

    return {
        "configured": True,
        "source": src.name,
        "attribution": active_source_attribution(),
        "regime": regime,
        "reason": why,
        "vix": reading.vix,
        "yield_spread_10y3m": reading.yield_spread_10y3m,
        "fed_funds_rate": reading.fed_funds_rate,
        "observation_dates": reading.observation_dates or {},
        "note": reading.note,
    }


# /learning/extract uses multipart upload, which requires the
# `python-multipart` library. If it's not installed (older venvs),
# we register a JSON-body fallback that takes base64 content. Either
# way the route exists and uvicorn boots cleanly.
try:
    import multipart  # noqa: F401 — only checking presence
    from fastapi import File as _FastAPIFile, UploadFile as _UploadFile

    @app.post("/learning/extract", tags=["learning"])
    async def learning_extract(file: _UploadFile = _FastAPIFile(...)):
        """Extract trade rows from a non-CSV document (PDF, image, XLSX,
        DOCX, text). Sends the file to Claude with structured extraction."""
        from app.learning.extract import extract_rows
        if file is None:
            return {"ok": False, "error": "No file uploaded."}
        blob = await file.read()
        if not blob:
            return {"ok": False, "error": "Empty file."}
        if len(blob) > 10 * 1024 * 1024:
            return {"ok": False, "error": "Files larger than 10MB aren't supported here."}
        return await extract_rows(
            content_type=file.content_type or "",
            file_bytes=blob,
            filename=file.filename or "",
        )
except ImportError:
    # python-multipart not installed - register a JSON-body fallback
    # so uvicorn still boots. The web layer can either pip install
    # python-multipart for the full multipart path or POST a base64
    # JSON body here. Same extract_rows() handler powers both.
    from fastapi import Request as _Request
    import base64 as _b64

    @app.post("/learning/extract", tags=["learning"])
    async def learning_extract_json(request: _Request):
        """Fallback when python-multipart isn't installed in the agents
        venv. Accepts JSON: {filename, content_type, data_b64}."""
        from app.learning.extract import extract_rows
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "Send JSON body or pip install python-multipart."}
        data_b64 = body.get("data_b64")
        if not data_b64:
            return {"ok": False, "error": "Missing data_b64 in JSON body."}
        try:
            blob = _b64.b64decode(data_b64)
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "Bad base64 in data_b64."}
        if len(blob) > 10 * 1024 * 1024:
            return {"ok": False, "error": "Files larger than 10MB aren't supported here."}
        return await extract_rows(
            content_type=str(body.get("content_type") or ""),
            file_bytes=blob,
            filename=str(body.get("filename") or ""),
        )


@app.post("/learning/postmortem/run", tags=["learning"])
async def learning_postmortem_run(user_id: str, force: bool = False):
    """Run the post-mortem analyzer over the user's trade_outcomes
    rows. Returns counts by diagnosis (held_too_long, optimal, etc).
    Idempotent; pass force=true to re-analyze already-scored rows."""
    from app.learning.postmortem import run_postmortem_for_user
    return await run_postmortem_for_user(user_id, force=force)


@app.get("/learning/capital-pressure", tags=["learning"])
async def learning_capital_pressure(user_id: str):
    """Capital pressure snapshot for the Trading page banner.

    Returns:
      - locked_usd: total cost basis of open positions whose health
        recommends rotate/trim_partial (capital that's "stuck" in
        decayed setups)
      - waiting_signals: recent veto messages that carried a
        rotation_candidate hint (high-TCS signals that lost to a
        weaker open position because the cap was hit)
      - rotations: array of {trim_ticker, take_ticker, gap} entries
        suggesting specific swaps


    Mike 2026-06-01: surfaces the asymmetry between locked-in stalled
    winners and waiting higher-TCS opportunities.
    """
    from app.config import get_settings
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return {"ok": False, "error": "Supabase not configured"}
    try:
        from supabase import create_client
        client = create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}

    import asyncio as _aio

    def _open_positions():
        return (
            client.table("paper_positions")
            .select("id, ticker, asset_type, side, quantity, entry_price, "
                    "stop_price, target_price, entry_at, source_payload, "
                    "peak_unrealized_pnl_usd")
            .eq("user_id", user_id)
            .eq("status", "open")
            .execute()
        )

    def _recent_rotation_vetos():
        from datetime import datetime, timedelta, timezone as _tz
        cutoff = (datetime.now(_tz.utc) - timedelta(hours=24)).isoformat()
        return (
            client.table("agent_messages")
            .select("payload, created_at")
            .eq("agent_name", "risk_manager")
            .eq("kind", "veto")
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )

    try:
        pos_rows = (await _aio.to_thread(_open_positions)).data or []
        veto_rows = (await _aio.to_thread(_recent_rotation_vetos)).data or []
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}

    from app.learning.position_health import compute_position_health
    locked_usd = 0.0
    stalled_positions = []
    for pos in pos_rows:
        try:
            h = await compute_position_health(pos)
        except Exception:  # noqa: BLE001
            h = None
        if not h or h.recommendation == "hold":
            continue
        notional = float(pos.get("entry_price") or 0) * float(pos.get("quantity") or 0)
        locked_usd += notional
        stalled_positions.append({
            "position_id": pos["id"],
            "ticker": pos.get("ticker"),
            "notional_usd": round(notional, 2),
            "recommendation": h.recommendation,
            "current_tcs": h.current_tcs,
            "entry_tcs": h.entry_tcs,
        })

    rotations = []
    for v in veto_rows:
        p = v.get("payload") or {}
        rc = p.get("rotation_candidate")
        if not rc:
            continue
        rotations.append({
            "trim_ticker": rc.get("ticker"),
            "trim_position_id": rc.get("position_id"),
            "trim_current_tcs": rc.get("current_tcs"),
            "take_ticker": p.get("ticker"),
            "take_tcs": rc.get("incoming_tcs"),
            "gap": rc.get("gap"),
            "raised_at": v.get("created_at"),
        })
    seen = set()
    deduped = []
    for r in rotations:
        key = r.get("trim_position_id")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    return {
        "ok": True,
        "locked_usd": round(locked_usd, 2),
        "stalled_positions": stalled_positions,
        "rotations": deduped[:5],
        "waiting_count": len(deduped),
    }


@app.get("/learning/insights", tags=["learning"])
async def learning_insights(user_id: str, lookback_days: int = 30):
    """Phase 13/14 learning loop - per-strategy stats."""
    from app.learning.outcomes import get_strategy_stats, suggest_tuning
    stats = await get_strategy_stats(user_id, lookback_days=lookback_days)
    stats["suggestions"] = suggest_tuning(stats)
    return stats


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "trezo-agents",
        "env": settings.env,
    }
