"""Shared agent capability library.

A single, importable registry of the platform's risk / exit / profit
protections so EVERY agent and strategy is aware of what is available --
even capabilities its own strategy does not use. Part of the agents'
shared knowledge: ``seed_shared_capabilities()`` writes the registry into
shared agent memory at startup, and ``trailing_profit_stop()`` is the one
shared profit-lock math every position type can call.

Mike 2026-06-23: "make every strategy and agent aware of what is available
... a library that is available ... shared knowledge and continuous
building of memory and data for the agents to get better."
"""
from __future__ import annotations

import asyncio


def trailing_profit_stop(
    entry: float, price: float, side: str,
    min_gain: float = 0.03, giveback: float = 0.30,
) -> float | None:
    """Shared trailing profit-lock. Returns a proposed stop that locks in
    (1 - giveback) of the open gain once the position is >= min_gain in
    profit, for LONG or SHORT. The proposed stop always sits between entry
    and the current price, so it can only protect a winner -- never forces a
    loss, never triggers an instant exit. The caller ratchets (long: raise
    only; short: lower only) and persists. None when not enough profit yet
    or on bad input."""
    try:
        entry = float(entry)
        price = float(price)
    except (TypeError, ValueError):
        return None
    if entry <= 0 or price <= 0:
        return None
    s = str(side or "").lower()
    if s == "long":
        gain = price - entry
        if gain <= entry * min_gain:
            return None
        new_stop = round(entry + gain * (1.0 - giveback), 4)
        return new_stop if new_stop > entry else None
    if s == "short":
        gain = entry - price
        if gain <= entry * min_gain:
            return None
        new_stop = round(entry - gain * (1.0 - giveback), 4)
        return new_stop if new_stop < entry else None
    return None


def trailing_stop_from_price(
    price: float, side: str, giveback: float,
    entry: float | None = None, trigger_gain: float | None = None,
) -> float | None:
    """Price-anchored trailing stop (shared; used by the crypto HODL trail):
    place the stop ``giveback`` below the live price for a long (above for a
    short) so the position keeps running while protecting a fixed % off the
    peak price. Optionally gated by ``trigger_gain`` -- only trail once the
    position is at least that far in profit vs ``entry``. Caller ratchets +
    persists. Returns the proposed stop or None (bad input / before trigger)."""
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    s = str(side or "").lower()
    if trigger_gain is not None and entry:
        try:
            e = float(entry)
        except (TypeError, ValueError):
            e = 0.0
        if e > 0:
            if s == "long" and price < e * (1.0 + trigger_gain):
                return None
            if s == "short" and price > e * (1.0 - trigger_gain):
                return None
    if s == "long":
        return round(price * (1.0 - giveback), 8)
    if s == "short":
        return round(price * (1.0 + giveback), 8)
    return None


def ladder_stop(entry, price: float, ladder, side: str = "long") -> float | None:
    """Tiered step-ladder profit lock (shared; used by crypto SWING / DCA /
    Extended). ``ladder`` = ((gain_trigger, locked_floor), ...) as fractions
    of entry. As the gain climbs through the rungs, lock the stop at the
    highest rung reached: entry*(1+floor) for a long, entry*(1-floor) for a
    short. Caller ratchets + persists. Returns the proposed stop or None
    (below rung one / bad input)."""
    try:
        entry = float(entry)
        price = float(price)
    except (TypeError, ValueError):
        return None
    if entry <= 0 or price <= 0:
        return None
    s = str(side or "").lower()
    gain = (price - entry) / entry if s == "long" else (entry - price) / entry
    locked = None
    # EXACT-BOUNDARY EPSILON (2026-08-19). `gain >= trigger` on raw floats
    # misses the rung when the peak lands ON it: entry 100.0, price 100.8
    # gives 0.007999999999999996, which is not >= 0.008, so the +0.8% rung
    # does not arm. Same for +1.8% at 101.8. With the old +5%/+8%/+10% rungs
    # nobody noticed. With sub-1% rungs this is the difference between a
    # ladder that works and a ladder that looks deployed and locks nothing.
    # 1e-9 is ~1000x the double-rounding error at these magnitudes and far
    # below any price move that could matter.
    _EPS = 1e-9
    for trigger, floor in ladder:
        if gain >= float(trigger) - _EPS:
            locked = floor
    if locked is None:
        return None
    if s == "long":
        return round(entry * (1.0 + locked), 8)
    if s == "short":
        return round(entry * (1.0 - locked), 8)
    return None


def peak_giveback_pct(peak: float, current: float) -> float:
    """Drawback from a position's best unrealized P&L (shared; used by both
    Exit Advisors): (peak - current) / peak, or 0.0 when there is no positive
    peak yet. Pure -- no side effects, no clamping (matches the advisors'
    existing semantics where a giveback can exceed 100%)."""
    try:
        peak = float(peak)
        current = float(current)
    except (TypeError, ValueError):
        return 0.0
    if peak <= 0:
        return 0.0
    return (peak - current) / peak


# The shared toolbox every agent should be aware of. Add new protections
# here so the whole system + the seeded shared memory stay in sync.
CAPABILITIES: list[dict] = [
    {"id": "profit_trail_stock", "name": "Stock profit trail-to-lock",
     "summary": "Once a stock is >=3% in profit, ratchet the stop toward price to lock ~70% of the gain and sell on a giveback (long and short).",
     "applies_to": "stocks"},
    {"id": "crypto_hodl_trail", "name": "Crypto HODL trail-to-lock",
     "summary": "After ~+40% a HODL coin trails its stop ~20% below price; no target, keeps holding while protecting the run.",
     "applies_to": "crypto HODL"},
    {"id": "crypto_step_ladders", "name": "Crypto step-ladder profit locks",
     "summary": "SWING / DCA / Extended ratchet the stop up through ROC tiers, locking gains in stages while the trade still rides to target.",
     "applies_to": "crypto swing/dca/extended"},
    {"id": "bracket_stop_target", "name": "Stop + target bracket",
     "summary": "Every entry carries a protective stop and a profit target managed as a one-cancels-other pair.",
     "applies_to": "all"},
    {"id": "time_exits", "name": "Time-based exits",
     "summary": "Intraday force-exit near the close, max-hold + stagnation checks, and multi-day swing windows close trades that overstay.",
     "applies_to": "all"},
    {"id": "daily_profit_lock", "name": "Daily profit lock",
     "summary": "When today's realized P&L reaches the target, that amount auto-locks into the vault.",
     "applies_to": "account"},
    {"id": "daily_loss_limit", "name": "Daily loss limit",
     "summary": "When today's realized loss hits the limit, Risk Manager vetoes all new signals for the rest of the day.",
     "applies_to": "account"},
    {"id": "exit_advisor_giveback", "name": "Exit Advisor peak-giveback alert",
     "summary": "Tracks each position's peak unrealized P&L and alerts when a winner gives back >=30% of its peak gain (advisory).",
     "applies_to": "all positions"},
    {"id": "options_drawback_ladder", "name": "Options take-profit + drawback ladder",
     "summary": "Contract-count drives the target (1-10 -> 30-50%, >10 -> 15%) with a 39/30/25% drawback ladder; catalyst-aware urgency.",
     "applies_to": "options"},
    {"id": "tiered_staleness", "name": "Signal staleness auto-clear",
     "summary": "Risk Manager auto-vetoes a signal older than its confidence/urgency deadline (60-300s) so stale setups never fire.",
     "applies_to": "all signals"},
    {"id": "integrity_audit", "name": "Position integrity audit",
     "summary": "Reconciles Trezo's open positions against real Alpaca holdings and flags/quarantines phantom rows.",
     "applies_to": "all positions"},
    {"id": "outcome_learning", "name": "Outcome-weighted strategy learning",
     "summary": "Closed-trade outcomes feed strategy weighting so the bot favors what works per asset and avoids what doesn't over time.",
     "applies_to": "strategy selection"},
]


def capabilities_text() -> str:
    """One line per capability -- for prompts / logs / agent context."""
    protections = "\n".join("- " + c["name"] + ": " + c["summary"] for c in CAPABILITIES)
    trading = "\n".join("- " + c["label"] + ": " + c["reason"] for c in capability_catalog())
    return protections + "\nTrading capabilities (availability is per book):\n" + trading


def capability_catalog() -> list[dict]:
    """Known execution adapters, separate from ideas and broker permission.

    This pure catalog is safe for market-report ingestion; only the async
    per-book read below may assert that a configured lane is available.
    """
    specs = [
        ("stock_long", "Stock longs", True, ["bullish"], "pattern_enabled", 0,
         "Pattern, opening-range and momentum entries; each book's signal and risk gates apply."),
        ("stock_short", "Stock shorts", True, ["bearish"], "pattern_enabled", 0,
         "Requires this account's shorting permission and a borrowable symbol at order time."),
        ("stms", "Small-cap momentum", True, ["bullish"], "stms_enabled", 0,
         "Implemented long momentum setups; market window and liquidity gates apply."),
        ("orb", "Opening-range breakouts", True, ["bullish", "bearish"], "stms_enabled", 0,
         "Both directions are implemented; one qualifying breakout per symbol during the configured opening window."),
        ("extended", "Multi-day stock swings", True, ["bullish"], "extended_enabled", 0,
         "Implemented long continuation setups; overnight holding follows this lane's existing rules."),
        ("crypto_long", "Spot crypto", True, ["bullish"], "crypto_enabled", 0,
         "Long-only spot execution; cash, fees and coin limits apply per book."),
        ("crypto_short", "Crypto shorts", False, ["bearish"], None, 0,
         "Unavailable: no crypto borrowing or derivatives execution adapter is implemented."),
        ("wheel_csp", "Cash-secured puts", True, ["bullish", "neutral"], "wheel_auto_execute", 1,
         "Requires own options permission, verified cash collateral and a qualifying contract."),
        ("wheel_cc", "Covered calls", True, ["neutral"], "wheel_auto_execute", 1,
         "Requires own options permission and unpledged 100-share lots; duplicate calls are refused."),
        ("day_options", "Intraday calls and puts", True, ["bullish", "bearish"], "day_options_enabled", 2,
         "Purchased contracts; direction of the contract is distinct from underlying exposure."),
        ("spreads", "Defined-risk option spreads", True, ["bullish", "bearish"], "spreads_enabled", 3,
         "Bull-put and bear-call credit spreads and iron condors; requires own spread permission, buying power and tradable paired contracts."),
        ("bull_call_spread", "Bull-call debit spreads", False, ["bullish"], None, 3,
         "Research only: an idea builder exists, but no autonomous selection branch is connected."),
        ("butterfly", "Option butterflies", False, ["neutral"], None, 3,
         "Research only: an idea builder exists, but no autonomous selection branch is connected."),
        ("long_options", "Directional calls and puts", True, ["bullish", "bearish"], "long_options_enabled", 2,
         "Purchased calls or puts, selected from both market leaders and laggards."),
        ("dividend_lt", "Long-term dividends", True, ["bullish"], "dividend_lt_enabled", 0,
         "Quality-screened stock or fund entries; own score, income budget and screen-managed exits apply."),
        ("forex", "Foreign exchange", False, ["bullish", "bearish"], None, 0,
         "Unavailable: market-data research exists but no FX execution venue is connected."),
        ("reevaluation", "Broker stock reevaluation", False, ["bullish", "bearish"], "reevaluation_enabled", 0,
         "Unavailable: stock leg resynchronization rejects shorts and does not safely roll back failed broker changes. Existing protective exits remain active."),
        ("crypto_reevaluation", "Crypto thesis reevaluation", True, ["bullish"], "crypto_reevaluation_enabled", 0,
         "Rechecks this book's losing coins around the clock; existing exemptions and exit limits apply."),
        ("research", "New strategy research", False, ["bullish", "bearish"], None, 0,
         "Research only: stored opportunities can generate tests; unvalidated rules cannot place orders."),
    ]
    rows = [{"id": i, "label": label, "implemented": implemented,
             "directions": directions, "flag": flag, "options_level": level,
             "reason": reason} for i, label, implemented, directions, flag, level, reason in specs]
    from app.strategies.library import LIBRARY
    rows.extend({"id": "library:" + c.id, "label": c.name, "implemented": False,
                 "directions": [], "flag": None, "options_level": 0,
                 "reason": "Research reference: no execution-module mapping. Retained for future implementation."}
                for c in LIBRARY if not c.maps_to)
    return rows


def _book_capability_rows(cfg, account, *, settings_verified: bool) -> list[dict]:
    """Pure status evaluation. Enabled means eligible, never an order/fill."""
    rows = []
    for item in capability_catalog():
        row = {k: item[k] for k in ("id", "label", "directions", "reason")}
        row["status"] = "unavailable"
        if item["implemented"]:
            if not settings_verified:
                row.update(status="unverified", reason="This book's settings could not be verified.")
            elif not getattr(cfg, "auto_trade_enabled", False) or not getattr(cfg, item["flag"], False):
                row.update(status="disabled", reason="Disabled by this book's own settings.")
            elif account is None:
                row.update(status="unverified", reason="Broker permissions could not be read for this book.")
            elif account.trading_blocked or str(account.status).upper() != "ACTIVE":
                row.update(status="unavailable", reason="This broker account currently blocks trading.")
            elif item["options_level"] and min(account.options_approved_level, account.options_trading_level) < item["options_level"]:
                row.update(status="unavailable", reason=f"This book needs options trading level {item['options_level']}.")
            elif item["id"] == "stock_short" and getattr(account, "shorting_enabled", None) is not True:
                known = getattr(account, "shorting_enabled", None)
                row.update(status="unverified" if known is None else "unavailable",
                           reason="Shorting permission is unverified." if known is None else "This broker account does not permit stock shorts.")
            else:
                row["status"] = "enabled"
                if item["id"] == "orb" and getattr(account, "shorting_enabled", None) is not True:
                    row["directions"] = ["bullish"]
                    row["reason"] += (" Bearish entries are unavailable: shorting is disabled for this book."
                                      if getattr(account, "shorting_enabled", None) is False else
                                      " Bearish entries remain unverified until this book's shorting permission is confirmed.")
        rows.append(row)
    return rows


async def capabilities_for_book(book_id: str) -> dict:
    """Read only one bound paper account; never substitute a default book."""
    from app.brokers.accounts import account_for_user, bind_for_user, PAPER_BASE_URL
    from app.runtime.settings import get_bot_settings, is_fallback_settings
    from app.brokers import alpaca
    account = account_for_user(book_id)
    cfg = get_bot_settings(book_id)
    snapshot = None
    if account is not None and account.base_url.rstrip("/") == PAPER_BASE_URL:
        try:
            with bind_for_user(book_id):
                snapshot = await asyncio.wait_for(alpaca.get_account(), timeout=12)
        except Exception:
            snapshot = None
    return {"book_id": book_id, "label": account.label if account else book_id,
            "capabilities": _book_capability_rows(cfg, snapshot,
                settings_verified=not is_fallback_settings(cfg)),
            "note": "Availability is checked independently. Every entry still checks this book's risk, collateral, capacity and current symbol eligibility."}


async def seed_shared_capabilities() -> int:
    """Write the capability registry into shared agent memory so every agent
    is aware of the toolbox. Idempotent (upsert by topic) and fail-open --
    any error returns 0 and never blocks startup. Returns rows inserted."""
    try:
        from app.config import get_settings
        s = get_settings()
        if not (s.supabase_url and s.supabase_service_role_key):
            return 0
        from supabase import create_client
        from datetime import datetime, timezone
        client = create_client(s.supabase_url, s.supabase_service_role_key)
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        trading_caps = [{"id": c["id"], "name": c["label"],
                         "summary": c["reason"], "applies_to": "per-book trading eligibility"}
                        for c in capability_catalog()]
        for cap in CAPABILITIES + trading_caps:
            topic = "capability:" + cap["id"]
            content = cap["name"] + " - " + cap["summary"] + " (applies to: " + cap["applies_to"] + ")"

            def _find(_t=topic):
                return (client.table("agent_memory").select("id")
                        .eq("scope", "shared").eq("topic", _t).limit(1).execute())
            try:
                rows = (await asyncio.to_thread(_find)).data or []
            except Exception:
                continue
            if rows:
                rid = rows[0].get("id")

                def _upd(_id=rid, _c=content):
                    return (client.table("agent_memory")
                            .update({"content": _c, "updated_at": now})
                            .eq("id", _id).execute())
                try:
                    await asyncio.to_thread(_upd)
                except Exception:
                    pass
            else:
                def _ins(_t=topic, _c=content):
                    return (client.table("agent_memory").insert({
                        "agent": "system", "scope": "shared", "topic": _t,
                        "category": "capability", "content": _c,
                        "weight": 5.0, "created_at": now, "updated_at": now,
                    }).execute())
                try:
                    await asyncio.to_thread(_ins)
                    inserted += 1
                except Exception:
                    continue
        return inserted
    except Exception:
        return 0
