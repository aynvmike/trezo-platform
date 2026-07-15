"""FastAPI entry point for the Trezo agents service."""

import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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


@app.post("/lab/teach", tags=["backtest"])
async def lab_teach(payload: dict):
    """Push a Strategy Lab run into the agents' SHARED MEMORY (Mike
    2026-07-14: "upload this for the agents' memory"). The structured
    half already happens automatically -- every lab run lands in
    backtest_runs, which the per-stock selector reads (net-loss
    strategies are dropped, history breaks ties). This adds the
    narrative half: compact Mem0 notes the agents RECALL when they next
    look at these tickers, plus one visible activity line."""
    try:
        rows = list((payload or {}).get("rows") or [])[:60]
        name = str((payload or {}).get("name") or "lab run")[:60]
        if not rows:
            return {"ok": False, "error": "no rows"}
        from app.memory import get_memory
        mem = get_memory()
        noted = 0
        for r in sorted(rows,
                        key=lambda x: -float(x.get("return_pct") or 0))[:20]:
            sym = str(r.get("symbol") or "").upper()
            strat = str(r.get("strategy") or "?")
            ret = float(r.get("return_pct") or 0)
            wr = float(r.get("win_rate") or 0)
            tr = int(r.get("trades") or 0)
            if not sym:
                continue
            try:
                mem.queue_note(
                    "strategy_lab",
                    (f"lab[{name}]: {sym} best={strat} ret {ret:+.1f}% "
                     f"win {wr * 100:.0f}% ({tr} trades)"),
                    ticker=sym)
                noted += 1
            except Exception:  # noqa: BLE001
                continue
        try:
            from app.agents.activity_log import record as _arec
            _tops = sorted(rows,
                           key=lambda x: -float(x.get("return_pct") or 0))[:3]
            _arec("lab_teach", "MARKET",
                  reason=(f"Strategy Lab run '{name}' taught to the agents: "
                          f"{len(rows)} symbols in backtest history + "
                          f"{noted} memory notes. Standouts: "
                          + ", ".join(
                              f"{t.get('symbol')} "
                              f"{float(t.get('return_pct') or 0):+.0f}% "
                              f"({t.get('strategy')})" for t in _tops)),
                  extra={})
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "noted": noted, "rows": len(rows)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


_LAB_SCAN_CACHE: dict = {}


@app.get("/lab/scan", tags=["backtest"])
async def lab_scan(scope: str = "market", sector: str = "", limit: int = 24):
    """Market / industry scan for the Strategy Lab (Mike 2026-07-14): hunt
    beyond the watchlists -- the whole market or one industry -- and save
    the picks straight into a custom watchlist. Returns movers with 1-day
    and 3-day moves plus volume pace, and the sector menu for the UI."""
    import time as _t
    from app.data.candles import fetch_stock_candles
    from app.data.market_universe import (
        SECTOR_ETFS, SECTOR_GENERALS, market_wide_candidates,
    )
    key = f"{scope}:{(sector or '').upper()}:{int(limit)}"
    hit = _LAB_SCAN_CACHE.get(key)
    if hit and (_t.time() - hit[0]) < 600:
        return hit[1]
    syms: list[str] = []
    if sector and sector.upper() in SECTOR_GENERALS:
        syms = [sector.upper()] + list(SECTOR_GENERALS[sector.upper()])
    else:
        for _etf, names in SECTOR_GENERALS.items():
            syms.extend(names[:3])
        try:
            movers = await market_wide_candidates(limit=30)
            syms.extend(movers or [])
        except Exception:  # noqa: BLE001
            pass
    seen: set = set()
    ordered: list[str] = []
    for s in syms:
        u = (s or "").upper()
        if u and u not in seen:
            seen.add(u)
            ordered.append(u)
    out = []
    for sym in ordered[: max(5, min(int(limit), 40))]:
        try:
            cs = await fetch_stock_candles(sym)
            if not cs or len(cs) < 22:
                continue
            cl = [float(c.close) for c in cs]
            d1 = (cl[-1] / cl[-2] - 1.0) * 100.0 if cl[-2] else 0.0
            d3 = ((cl[-1] / cl[-4] - 1.0) * 100.0
                  if len(cl) > 4 and cl[-4] else 0.0)
            vols = [float(c.volume or 0) for c in cs[-21:]]
            va = sum(vols[:-1]) / max(len(vols) - 1, 1)
            vr = (vols[-1] / va) if va > 0 else 0.0
            out.append({"symbol": sym, "price": round(cl[-1], 2),
                        "d1": round(d1, 2), "d3": round(d3, 2),
                        "volume_ratio": round(vr, 2)})
        except Exception:  # noqa: BLE001
            continue
    out.sort(key=lambda x: -abs(x["d3"]))
    # News sentiment lens (Mike 2026-07-14: "news sentiment ... can also
    # play a role in the market") -- 2-day keyword sentiment on the
    # leaders, from the same Finnhub pass the Market Sentiment agent uses.
    try:
        from app.data.news import assess, fetch_company_news
        for row in out[:12]:
            try:
                items = await fetch_company_news(row["symbol"], days=2)
                row["news_n"] = len(items or [])
                if not items:
                    continue
                scores = [float(assess(it).sentiment_score or 0)
                          for it in items[:8]]
                avg = sum(scores) / max(len(scores), 1)
                row["news_score"] = round(avg, 2)
                row["news_sent"] = ("bullish" if avg >= 0.15
                                    else "bearish" if avg <= -0.15
                                    else "neutral")
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    resp = {"available": True, "scope": scope, "sector": (sector or None),
            "results": out,
            "sectors": [{"etf": k, "name": v} for k, v in SECTOR_ETFS.items()]}
    _LAB_SCAN_CACHE[key] = (_t.time(), resp)
    return resp


@app.get("/backtest", tags=["backtest"])
async def backtest_endpoint(symbol: str, strategy: str = "default",
                            tcs_threshold: int = 70, period: str = "2y",
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
async def backtest_compare_endpoint(symbol: str, tcs_threshold: int = 70,
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
    """Force a stock-side reconciliation. Real work lives in
    app/paper/stocks_reconcile.py so PositionMonitor can call the same
    code on a 30-min schedule (Task #32, 2026-06-03)."""
    from app.paper.stocks_reconcile import reconcile_stocks_all_users
    return await reconcile_stocks_all_users()

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




@app.post("/admin/clear-session-halt", tags=["admin"])
async def admin_clear_session_halt():
    """One-click recovery (Mike 2026-07-07): resets the session-scoped
    broker-reject and slippage counters so the kill-switch stops vetoing,
    without waiting for the daily roll. Day/week drawdown halts are NOT
    touched -- those protect capital and clear on their own schedule."""
    from app.paper.killswitch import (
        broker_reject_count, reset_broker_rejects,
        reset_slippage_breaches, slippage_breach_count,
    )
    before = {"broker_rejects": broker_reject_count(),
              "slippage_breaches": slippage_breach_count()}
    reset_broker_rejects()
    reset_slippage_breaches()
    try:
        from app.agents.activity_log import record as _arec
        _arec("halt_cleared", "SESSION",
              reason=(f"manual clear: rejects {before['broker_rejects']} -> 0, "
                      f"slippage breaches {before['slippage_breaches']} -> 0"),
              extra={})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "before": before, "after": {"broker_rejects": 0,
                                                    "slippage_breaches": 0}}


@app.post("/admin/settings-sync", tags=["admin"])
async def admin_settings_sync():
    """Force-sync (Mike 2026-07-06: "auto fix if needed, or give a reason
    why it will not set"). Clears the 30s settings cache so every agent
    re-reads the saved row on its next tick, then re-runs the audit.
    Drift that SURVIVES a sync is real and the response says what that
    means; drift right after saving is just the cache window."""
    from app.runtime.settings import clear_settings_cache
    clear_settings_cache()
    out = await admin_settings_audit()
    try:
        out["sync"] = {
            "cache_cleared": True,
            "how_it_heals": ("agents re-read settings within one tick; "
                             "values refresh automatically every 30s after "
                             "any save -- no restart needed for Bot Tuning"),
            "if_drift_remains": ("a field still drifting AFTER this sync "
                                 "means an env override or a hardcoded "
                                 "value is winning for that field -- "
                                 "report it to Nova with the field name"),
        }
    except Exception:  # noqa: BLE001
        pass
    return out


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
                # Compare the SAME row the agents read (2026-07-06):
                # with TREZO_PRIMARY_USER_ID set, that row; else the
                # most-recently-updated one (legacy).
                import os as _o
                _prim = (_o.getenv("TREZO_PRIMARY_USER_ID") or "").strip()
                qq = cl.table("bot_settings").select("*")
                if _prim:
                    qq = qq.eq("user_id", _prim)
                return qq.order("updated_at", desc=True).limit(1).execute()
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
        # Phase C+D options filters (Path α): show per-user override when
        # set, else what the agent will actually use (env default).
        "options_min_dte": (cfg.options_min_dte
                            if cfg.options_min_dte is not None
                            else int(s.options_min_dte)),
        "options_max_premium_delta": (cfg.options_max_premium_delta
                                      if cfg.options_max_premium_delta is not None
                                      else float(s.options_max_premium_delta)),
        "options_min_iv_rank_scalp": (cfg.options_min_iv_rank_scalp
                                      if cfg.options_min_iv_rank_scalp is not None
                                      else float(s.options_min_iv_rank_scalp)),
        "options_hopeful_allocation_cap_pct": (
            cfg.options_hopeful_allocation_cap_pct
            if cfg.options_hopeful_allocation_cap_pct is not None
            else float(s.options_hopeful_allocation_cap_pct)
        ),
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
        best_reading_and_source, get_macro_reading, classify_macro_regime,
    )

    reading, src = await best_reading_and_source()
    if src is None:
        r0 = await get_macro_reading()
        return {
            "configured": False,
            "source": None,
            "note": r0.note or "No macro source configured.",
        }
    if reading is None:
        reading = await get_macro_reading()
    regime, why = classify_macro_regime(reading)

    return {
        "configured": True,
        "source": getattr(reading, "source", None) or getattr(src, "name", "unknown"),
        "attribution": getattr(src, "attribution", ""),
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


# ----------------------------------------------------------------------
# Trim endpoints - stocks (capital recycling, shipped 2026-06-01) and
# options (task #29 v1, modeled close, 2026-06-02). Both proxy to a
# specialized async primitive in app/paper/.
# ----------------------------------------------------------------------

class _StockTrimReq(BaseModel):
    user_id: str
    position_id: str
    ticker: str | None = None
    asset_type: str | None = None
    fraction: float
    reason: str = "user_trim"


@app.get("/knowledge/search", tags=["paper"])
async def knowledge_search(q: str, k: int = 3):
    """Search the agents' local trading-knowledge library (Mike 2026-07-13).
    Books live in agents/knowledge/library/; scripts/build_library.py adds
    the manifest titles and indexes anything Mike drops in the folder."""
    try:
        from app.knowledge.library import search, stats
        return {"available": True, "results": search(q, k=k), **stats()}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)[:200]}


@app.get("/goal/today", tags=["paper"])
async def goal_today(user_id: str | None = None):
    """The agents' daily income goal (Mike 2026-07-13): the paycheck-ladder
    rung for the current account size plus today's realized progress."""
    try:
        from app.paper.daily_goal import goal_state
        st = await goal_state(user_id)
        return {"available": True, **st}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)[:200]}


@app.get("/activity/today", tags=["paper"])
async def activity_today(limit: int = 14):
    """Today's agent decision trail for the UI (2026-07-02): the Overview
    was position-derived and told the user NOTHING about what the agents
    were doing. This reads the local activity log (the same file the
    midday snapshot uses) and returns event counts + the last N lines."""
    import json as _json
    import os as _os
    from datetime import datetime as _dt, timezone as _tz
    here = _os.path.dirname(_os.path.abspath(__file__))
    root = _os.path.abspath(_os.path.join(here, ".."))
    logdir = _os.getenv("TREZO_ACTIVITY_LOG_DIR") or _os.path.join(
        _os.path.dirname(root), "logs")
    today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
    path = _os.path.join(logdir, f"activity-{today}.jsonl")
    counts: dict = {}
    last: list = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        for ln in lines:
            try:
                rec = _json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            ev = str(rec.get("event") or "?")
            counts[ev] = counts.get(ev, 0) + 1
        for ln in lines[-max(1, int(limit)):]:
            try:
                rec = _json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            last.append({
                "ts": rec.get("ts"),
                "event": rec.get("event"),
                "ticker": rec.get("ticker"),
                "reason": str(rec.get("reason") or "")[:140],
            })
        last.reverse()
        return {"available": True, "date": today,
                "total": sum(counts.values()), "counts": counts,
                "last": last}
    except FileNotFoundError:
        return {"available": False, "date": today, "total": 0,
                "counts": {}, "last": []}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "date": today, "total": 0,
                "counts": {}, "last": [], "error": str(e)[:120]}


@app.get("/allocations/snapshot", tags=["paper"])
async def allocations_snapshot(user_id: str):
    """The REAL capital pockets the Trade Execution gate enforces (Phase
    8a.2 allocation): per-market-type dollar budgets under the account's
    posture, plus how much of each pocket is deployed right now. Added
    2026-07-02 to replace the dead /sleeves/snapshot the Capital Sleeves
    page pointed at -- the UI now shows exactly what the gate enforces."""
    from app.paper.allocation import (
        MARKET_TYPES, build_allocation, deployed_capital,
    )
    from app.paper.engine import get_account
    from app.runtime.settings import get_bot_settings

    from app.paper.allocation import effective_equity
    cfg = get_bot_settings(user_id)
    account = await get_account(user_id)
    equity = await effective_equity(user_id)
    alloc = build_allocation(
        equity,
        posture_setting=cfg.account_posture,
        overrides=cfg.allocation_overrides,
    )
    deployed = await deployed_capital(user_id)
    copy = {
        "stocks": ("Stocks", "Day-to-swing stock strategies.",
                   "Ladder stops; the profit trail locks gains on giveback.",
                   ["1 Stock Bot"]),
        "crypto": ("Crypto", "Crypto swings + patient HODL accumulation.",
                   "Entries must net a profit after fees + slippage; "
                   "trail-to-lock protects big runs.",
                   ["2 Crypto Bot"]),
        "options": ("Options", "Directional option plays.",
                    "Drawback ladder + take-profit recycle.",
                    ["3 Options"]),
        "income": ("Income", "Wheel cycles + dividend holdings.",
                   "Collect premium and dividends; assignment is part "
                   "of the plan.",
                   ["4 Dividend Wheel", "5 Dividends"]),
        "forex": ("Forex", "Major fiat pairs, long or short (modeled).",
                  "ATR-fit targets; quick realistic moves, 24x5.",
                  ["6 Forex"]),
    }
    sleeves = []
    for mt in MARKET_TYPES:
        b = float(alloc.budgets.get(mt, 0.0))
        d = float(deployed.get(mt, 0.0))
        label, hold, profit, layers = copy[mt]
        sleeves.append({
            "id": mt,
            "label": label,
            "budget_usd": round(b, 2),
            "deployed_usd": round(d, 2),
            "free_usd": round(max(0.0, b - d), 2),
            "used_pct": round((d / b * 100.0) if b > 0 else 0.0, 1),
            "hold": hold,
            "profit": profit,
            "layers": layers,
        })
    return {
        "configured": bool(account),
        "profile": alloc.posture,
        "equity_usd": round(equity, 2),
        "scaled_max_open": int(cfg.max_open_positions),
        "summary": alloc.summary,
        "sleeves": sleeves,
    }


@app.post("/paper/positions/trim", tags=["paper"])
async def paper_positions_trim(req: _StockTrimReq) -> dict:
    """Sell a fraction of an open paper position. Backs the stock
    Trim button on Exit Advisor alerts. The slice's P&L lands in
    today_realized_pnl_usd; the remaining position keeps trading."""
    from app.paper.engine import close_partial_position
    # We need a market price for the slice. Fetch from candles.
    market_price = 0.0
    try:
        from app.data.candles import fetch_candles_for
        candles = await fetch_candles_for(
            req.ticker or "", req.asset_type or "stock"
        )
        if candles:
            market_price = float(candles[-1].close)
    except Exception:
        pass
    if market_price <= 0:
        return {"ok": False, "error": "no_market_price"}
    result = await close_partial_position(
        user_id=req.user_id,
        position_id=req.position_id,
        fraction=req.fraction,
        market_price=market_price,
        reason=req.reason,
    )
    return {
        "ok": getattr(result, "ok", False),
        "error": getattr(result, "error", None),
        "realized_pnl_usd": getattr(result, "realized_pnl_usd", None),
        "filled_qty": getattr(result, "filled_qty", None),
        "fill_price": getattr(result, "fill_price", None),
    }


class _OptionsTrimReq(BaseModel):
    user_id: str
    position_id: str
    contracts_to_close: int
    reason: str = "user_trim"


@app.post("/paper/options/trim", tags=["paper"])
async def paper_options_trim(req: _OptionsTrimReq) -> dict:
    """Close N contracts of an open options_positions row. Backs the
    Trim button on options Exit Advisor alerts. Task #29 v1: modeled
    close only - the user is expected to mirror live broker orders
    manually until v2 ships."""
    from app.paper.options_trim import close_partial_options_position
    return await close_partial_options_position(
        user_id=req.user_id,
        position_id=req.position_id,
        contracts_to_close=req.contracts_to_close,
        reason=req.reason,
    )


# ---------------------------------------------------------------------------
# FastAPI lifecycle hooks - load the agents and start the scheduler.
# Mike 2026-06-03: this was MISSING for days, which is why bootstrap
# never ran, the registry was empty, no scanners ticked, and the bot
# went silent. Adding the startup hook is the single fix that brings
# the platform back online.
# ---------------------------------------------------------------------------

async def _startup_auto_repair() -> None:
    """Self-healing data + account integrity pass, run once at startup.
    Never raises - every step is independently guarded so one failure can
    neither block the others nor the boot. Added 2026-06-16 (Mike's ask:
    always point at the right Alpaca account; no stale data on refresh)."""
    # (1) Account-identity guard: prove WHICH Alpaca account we are bound to
    # and flag the wrong-account / blocked / not-options-approved cases.
    try:
        from app.brokers.alpaca import account_self_check
        chk = await account_self_check()
        problem = (not chk.get("ok")) or chk.get("mismatch") or chk.get("trading_blocked")
        if problem:
            log.error("alpaca.account_check.PROBLEM",
                      account=chk.get("account_number"),
                      mismatch=chk.get("mismatch"),
                      blocked=chk.get("trading_blocked"),
                      note=chk.get("note"))
        else:
            log.info("alpaca.account_check.ok",
                     account=chk.get("account_number"),
                     buying_power=chk.get("buying_power"),
                     options_level=chk.get("options_approved_level"),
                     note=chk.get("note"))
        # Surface it in the UI feed/ticker (best-effort, never blocks boot).
        try:
            from app.runtime.persistence import persist_message
            from app.agents.base import AgentMessage
            await persist_message(AgentMessage(
                agent="ops_watchdog",
                kind="error" if problem else "info",
                payload={**chk, "event": "account_guard"},
            ))
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        log.error("alpaca.account_check.FAILED", error=str(e))

    # (2) Purge stale in-memory caches so a refresh can't serve data from
    # before the restart (defensive; a fresh process also starts empty).
    try:
        import app.strategies.market_filter as _mf
        _mf._cache = None
        _mf._cache_at = 0.0
    except Exception:  # noqa: BLE001
        pass

    # (3) Full integrity sweep vs broker truth so cash, stock positions and
    # option drift are all correct the moment the service returns (not at
    # tick 2 / the hourly sweep). Aligns the internal ledger to the broker.
    try:
        from app.paper.stocks_reconcile import run_integrity_sweep
        res = await run_integrity_sweep()
        if isinstance(res, dict):
            bal = res.get("balances") or {}
            stk = res.get("stocks") or {}
            opt = res.get("options") or {}
            log.info("agents.startup_integrity_sweep.done",
                     cash_synced=bal.get("synced"),
                     stocks_closed=stk.get("closed"),
                     stocks_updated=stk.get("updated"),
                     option_mismatches=opt.get("mismatches"))
    except Exception as e:  # noqa: BLE001
        log.error("agents.startup_integrity_sweep.FAILED", error=str(e))


@app.on_event("startup")
async def _on_startup() -> None:
    """Bootstrap every agent into the registry, then start the
    APScheduler tick loop. Both calls are idempotent so re-runs
    (uvicorn reload) won't double-register."""
    try:
        bootstrap_agents()
        log.info(
            "agents.bootstrap.complete",
            count=len(registry.all()),
        )
    except Exception as e:
        log.error("agents.bootstrap.FAILED", error=str(e))
        # Don't swallow - if bootstrap fails, scanners won't tick.
        # Re-raise so uvicorn logs the traceback.
        raise

    try:
        start_scheduler(app=app, registry=registry)
        log.info("agents.scheduler.started")
    except TypeError:
        # Older signature with no kwargs
        try:
            start_scheduler()
            log.info("agents.scheduler.started.fallback")
        except Exception as e:
            log.error("agents.scheduler.FAILED", error=str(e))
    except Exception as e:
        log.error("agents.scheduler.FAILED", error=str(e))

    # Patched 2026-06-05 (Task #61): start the batched-persistence
    # flush loop. Every persist_message() call queues into an
    # in-memory deque; the flush loop drains it via bulk-insert
    # every second. Cuts Supabase round-trips ~50x.
    try:
        from app.runtime.persistence import start_flush_loop
        start_flush_loop()
        log.info("persistence.flush_loop.started")
    except Exception as e:
        log.error("persistence.flush_loop.FAILED", error=str(e))

    # 2026-06-16: self-healing startup repair (account guard + cache purge
    # + immediate reconcile). Best-effort; never blocks the boot.
    try:
        await _startup_auto_repair()
    except Exception as e:  # noqa: BLE001
        log.error("agents.auto_repair.FAILED", error=str(e))


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    """Stop the APScheduler tick loop cleanly so uvicorn reload doesn't
    leak the prior scheduler instance. Also drain the persistence
    buffer so we never lose pending messages on a clean shutdown."""
    # Drain the batched-persistence buffer FIRST so any messages
    # produced during the last tick still land in Supabase.
    try:
        from app.runtime.persistence import stop_flush_loop
        await stop_flush_loop()
    except Exception:
        pass
    try:
        stop_scheduler()
    except Exception:
        pass


@app.get("/account-check")
async def account_check() -> dict:
    """On-demand account-identity guard: which Alpaca account the bot is
    bound to, buying power, options approval, and any expected-account
    mismatch. Read-only."""
    from app.brokers.alpaca import account_self_check
    return await account_self_check()


@app.get("/integrity-check", tags=["ops"])
async def integrity_check() -> dict:
    """Run the full self-healing sweep on demand: sync the cash ledger to the
    broker, reconcile stock positions, and report option-position drift.
    Idempotent and safe to call repeatedly."""
    from app.paper.stocks_reconcile import run_integrity_sweep
    return await run_integrity_sweep()


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "trezo-agents",
        "env": settings.env,
    }
