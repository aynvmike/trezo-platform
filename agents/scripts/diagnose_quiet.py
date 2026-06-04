"""Comprehensive 'why is the bot silent' diagnostic.

Run: `python -m scripts.diagnose_quiet` from agents venv.

Walks through every common reason Trezo stops trading and prints a
single readable report. No speculation - all signals come from
agent_messages, bot_settings, paper_positions, paper_accounts, and the
runtime Adaptive Scope.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _supabase():
    from app.config import get_settings
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception as e:
        print(f"[FATAL] Could not connect to Supabase: {e}")
        return None


def hr():
    print("-" * 72)


def head(s: str):
    print()
    print("=" * 72)
    print(f"  {s}")
    print("=" * 72)


async def check_agent_registry():
    head("1b. Agent registry (which agents are loaded?)")
    import urllib.request, json as _json
    try:
        with urllib.request.urlopen(
            "http://localhost:8001/agents", timeout=5
        ) as r:
            data = _json.loads(r.read().decode())
            if isinstance(data, dict) and "agents" in data:
                agents = data["agents"]
            elif isinstance(data, list):
                agents = data
            else:
                agents = []
            enabled = [a for a in agents if a.get("enabled", True)]
            disabled = [a for a in agents if not a.get("enabled", True)]
            print(f"  registered: {len(agents)} agents")
            print(f"  enabled:    {len(enabled)}")
            if disabled:
                print(f"  ⚠ DISABLED: {[a.get('name') for a in disabled]}")
            for a in agents[:25]:
                tick = a.get("tick_interval_seconds")
                last = a.get("last_tick_at") or a.get("last_run_at") or "—"
                count = a.get("message_count") or a.get("messages") or 0
                en = a.get("enabled", True)
                tag = "" if en else " ⚠ DISABLED"
                print(f"    {str(a.get('name', '?')):24s} "
                      f"tick={tick}s msgs={count} last={str(last)[:19]}{tag}")
    except Exception as e:
        print(f"  ✗ could not pull /agents: {e}")


async def check_agents_service():
    head("1. Agents service alive?")
    import urllib.request
    try:
        with urllib.request.urlopen(
            "http://localhost:8001/health", timeout=3
        ) as r:
            body = r.read().decode()
            print(f"  ✓ Agents service responding: {body[:120]}")
            return True
    except Exception as e:
        print(f"  ✗ Agents service NOT responding on port 8001: {e}")
        print("    -> RUN: start-agents.bat")
        return False


async def check_bot_settings(client):
    head("2. Bot settings (auto-trade, TCS threshold)")
    try:
        def _q():
            return (
                client.table("bot_settings")
                .select("user_id, auto_trade_enabled, tcs_threshold, "
                        "max_open_positions, autonomy_mode, updated_at, "
                        "pattern_enabled, stms_enabled, extended_enabled, "
                        "crypto_enabled")
                .order("updated_at", desc=True)
                .limit(5)
                .execute()
            )
        res = await asyncio.to_thread(_q)
        rows = res.data or []
        if not rows:
            print("  ⚠ No bot_settings row. Save once on /dashboard/settings/bot.")
            return
        for r in rows:
            on = r.get("auto_trade_enabled")
            tcs = r.get("tcs_threshold")
            print(f"  user {str(r.get('user_id'))[:8]} ... auto_trade={on}, "
                  f"tcs_threshold={tcs}, autonomy={r.get('autonomy_mode')}, "
                  f"max_open={r.get('max_open_positions')}")
            pe = r.get("pattern_enabled")
            se = r.get("stms_enabled")
            ee = r.get("extended_enabled")
            ce = r.get("crypto_enabled")
            print(f"    strategies: pattern={pe} stms={se} extended={ee} crypto={ce}")
            if on is False:
                print("    ⚠ auto_trade is OFF - bot only signals, no executes")
            if isinstance(tcs, (int, float)) and tcs > 800:
                print(f"    ⚠ TCS threshold {tcs} is HIGH - few setups will clear it")
            disabled = [k for k, v in {
                "pattern": pe, "stms": se, "extended": ee, "crypto": ce,
            }.items() if v is False]
            if disabled:
                print(f"    ⚠ Strategies OFF: {disabled} - those scanners are silent.")
            if pe is False and se is False and ee is False and ce is False:
                print("    ⚠⚠ ALL stock+crypto scanners disabled. THIS IS THE SILENCE.")
    except Exception as e:
        print(f"  ✗ Could not read bot_settings: {e}")


async def check_recent_messages(client):
    head("3. Recent agent activity (24h)")
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    try:
        def _q():
            return (
                client.table("agent_messages")
                .select("kind, agent_name, payload, created_at")
                .gte("created_at", since)
                .order("created_at", desc=True)
                .limit(2000)
                .execute()
            )
        res = await asyncio.to_thread(_q)
        rows = res.data or []
        print(f"  total messages in last 24h: {len(rows)}")
        if not rows:
            print("    ⚠ ZERO messages in 24h. Agents service likely not running OR scanners disabled.")
            return

        kinds: dict[str, int] = {}
        agents_active: dict[str, int] = {}
        for r in rows:
            k = r.get("kind", "?")
            kinds[k] = kinds.get(k, 0) + 1
            a = r.get("agent_name", "?")
            agents_active[a] = agents_active.get(a, 0) + 1

        print("  by kind:", ", ".join(
            f"{k}={n}" for k, n in sorted(kinds.items(), key=lambda x: -x[1])
        ))
        print("  top agents:", ", ".join(
            f"{a}={n}" for a, n in sorted(
                agents_active.items(), key=lambda x: -x[1]
            )[:8]
        ))

        signals = kinds.get("signal", 0)
        approves = kinds.get("approve", 0)
        vetoes = kinds.get("veto", 0)
        executes = kinds.get("execute", 0)

        if signals == 0:
            print("    ⚠ NO signals in 24h - scanners aren't finding setups OR are disabled.")
        else:
            print(f"    signals={signals}, approved={approves}, "
                  f"vetoed={vetoes}, executed={executes}")
            if approves > 0 and executes == 0:
                print("    ⚠ Signals approved but NOTHING executed - Trade Execution may be stuck.")
            if signals > 0 and approves == 0 and vetoes > 0:
                print(f"    ⚠ EVERY signal vetoed ({vetoes}). See top veto reasons below.")
    except Exception as e:
        print(f"  ✗ Could not read agent_messages: {e}")


async def check_agent_last_ticks(client):
    head("3b. Last activity PER AGENT (when did each scanner last emit?)")
    try:
        def _q():
            return (
                client.table("agent_messages")
                .select("agent_name, created_at")
                .order("created_at", desc=True)
                .limit(500)
                .execute()
            )
        res = await asyncio.to_thread(_q)
        rows = res.data or []
        if not rows:
            print("  agent_messages table is EMPTY. Persistence subscriber may be down.")
            return
        latest: dict[str, str] = {}
        for r in rows:
            a = r.get("agent_name", "?")
            ts = r.get("created_at", "")
            if a not in latest:
                latest[a] = ts
        now = datetime.now(timezone.utc)
        scanners = ["pattern_detection", "stms_scanner", "orb_scanner",
                    "extended_scanner", "crypto_scanner", "options_scanner",
                    "risk_manager", "trade_execution", "position_monitor"]
        for a in scanners:
            ts = latest.get(a)
            if not ts:
                print(f"  ⚠ {a:24s} NEVER posted to agent_messages")
                continue
            try:
                tdt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                age_h = (now - tdt).total_seconds() / 3600.0
                tag = "" if age_h < 2 else (f" ⚠ {age_h:.0f}h ago - STALE"
                                            if age_h < 24 else
                                            f" ⚠⚠ {age_h/24:.1f}d ago - DEAD")
                print(f"  {a:24s} last={ts[:19]}{tag}")
            except Exception:
                print(f"  {a:24s} last={ts}")
    except Exception as e:
        print(f"  ✗ Could not check per-agent ticks: {e}")


async def check_veto_reasons(client):
    head("4. Recent veto reasons (last 50)")
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        def _q():
            return (
                client.table("agent_messages")
                .select("payload, created_at")
                .eq("kind", "veto")
                .gte("created_at", since)
                .order("created_at", desc=True)
                .limit(50)
                .execute()
            )
        res = await asyncio.to_thread(_q)
        rows = res.data or []
        if not rows:
            print("  no vetoes in 7d (means signals either approved or none fired)")
            return
        reasons: dict[str, int] = {}
        for r in rows:
            p = r.get("payload") or {}
            reason = (p.get("reason") or "unknown")
            # bucket by leading 50 chars for grouping
            key = reason[:60]
            reasons[key] = reasons.get(key, 0) + 1
        for reason, n in sorted(reasons.items(), key=lambda x: -x[1])[:10]:
            print(f"  [{n:3d}x] {reason}")
    except Exception as e:
        print(f"  ✗ Could not read vetoes: {e}")


async def check_adaptive_scope(client):
    head("5. Adaptive Scope (regime / paused / flagged)")
    try:
        # Pull the latest scope status row if persisted
        from app.runtime.scope import get_scope
        scope = get_scope()
        print(f"  regime: {getattr(scope, 'regime', '?')}")
        print(f"  paused_strategies: {sorted(getattr(scope, 'paused_strategies', set()))}")
        print(f"  flagged_tickers: {sorted(getattr(scope, 'flagged_tickers', set()))[:10]}")
        print(f"  stop_multiplier: {getattr(scope, 'stop_multiplier', None)}")
        if getattr(scope, "regime", "") == "risk_off":
            print("    ⚠ Adaptive Scope is RISK_OFF - position sizes shrunk + stops tightened")
        if getattr(scope, "paused_strategies", set()):
            print("    ⚠ Strategies are paused. Risk Manager will veto signals from them.")
    except Exception as e:
        print(f"  ✗ scope unavailable: {e}")


async def check_open_positions(client):
    head("6. Open positions + last close")
    try:
        def _q_open():
            return (
                client.table("paper_positions")
                .select("id, ticker, status, entry_at")
                .eq("status", "open")
                .order("entry_at", desc=True)
                .execute()
            )
        res = await asyncio.to_thread(_q_open)
        rows = res.data or []
        print(f"  open paper positions: {len(rows)}")
        if rows:
            for r in rows[:5]:
                print(f"    {r.get('ticker')} opened {r.get('entry_at', '?')[:16]}")

        def _q_recent_close():
            return (
                client.table("paper_positions")
                .select("ticker, exit_at, exit_price, realized_pnl_usd, status")
                .neq("status", "open")
                .order("exit_at", desc=True)
                .limit(5)
                .execute()
            )
        res2 = await asyncio.to_thread(_q_recent_close)
        closes = res2.data or []
        print(f"  recent closes:")
        if not closes:
            print("    (none in DB)")
        for c in closes:
            ts = c.get("exit_at", "?")
            pnl = c.get("realized_pnl_usd")
            print(f"    {c.get('ticker')} {ts[:16] if isinstance(ts, str) else ts} "
                  f"pnl=${pnl} status={c.get('status')}")
    except Exception as e:
        print(f"  ✗ could not check positions: {e}")


async def check_account(client):
    head("7. Account state (kill switch / daily loss limit)")
    try:
        def _q():
            return (
                client.table("paper_accounts")
                .select("user_id, current_cash_usd, today_realized_pnl_usd, "
                        "consecutive_losses, trading_halted, updated_at")
                .order("updated_at", desc=True)
                .limit(5)
                .execute()
            )
        res = await asyncio.to_thread(_q)
        rows = res.data or []
        for r in rows:
            uid = str(r.get("user_id"))[:8]
            halted = r.get("trading_halted")
            cl = r.get("consecutive_losses")
            tp = r.get("today_realized_pnl_usd")
            cash = r.get("current_cash_usd")
            print(f"  user {uid}... cash=${cash} today_pnl=${tp} "
                  f"consec_losses={cl} halted={halted}")
            if halted:
                print("    ⚠ TRADING HALTED on this account - kill switch tripped.")
            if isinstance(cl, int) and cl >= 3:
                print(f"    ⚠ consecutive losses at {cl} - kill switch may trip soon.")
    except Exception as e:
        print(f"  ✗ could not check accounts: {e}")


async def check_alpaca_connectivity():
    head("8. Alpaca connectivity (env keys)")
    try:
        from app.brokers.alpaca import alpaca_configured
        cfg = alpaca_configured()
        print(f"  alpaca env-keys configured: {cfg}")
        if not cfg:
            print("    ⚠ Alpaca env keys missing - executor can't place real orders.")
    except Exception as e:
        print(f"  ✗ alpaca check failed: {e}")


async def main():
    print()
    print("#" * 72)
    print(f"# Trezo Trading-Silence Diagnostic")
    print(f"# {datetime.now().isoformat(timespec='seconds')}")
    print("#" * 72)

    alive = await check_agents_service()
    if alive:
        await check_agent_registry()

    client = _supabase()
    if not client:
        print("\n[FATAL] Supabase unreachable. Most checks below will be skipped.")
        return 1

    await check_bot_settings(client)
    await check_recent_messages(client)
    await check_agent_last_ticks(client)
    await check_veto_reasons(client)
    if alive:
        await check_adaptive_scope(client)
    await check_open_positions(client)
    await check_account(client)
    await check_alpaca_connectivity()

    print()
    print("#" * 72)
    print("# DONE - read the ⚠ lines above. They name the likely cause(s).")
    print("#" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
