"""Agent-driven crypto universe expander (Mike 2026-07-23).

"I look at crypto as stocks, just more liquid." The stock side already
scans the whole market through the movers/most-actives screener; this
module is the crypto twin. The agents DISCOVER coins from the venue
itself (Kraken's public listings), QUALIFY them by CONDITIONS -- never
lists -- ENROLL them into the scan universe, and SHARE the knowledge:
an activity line per change, a running note in the Quantconnect
drop-box (swept into the knowledge library daily), and a persistent
state file so enrollments survive restarts.

Conditions, not lists:
  * USD-quoted SPOT pair live on Kraken (venue truth -> real volume)
  * 24h notional >= TREZO_CRYPTO_DISCOVER_MIN_VOL_USD (default $5M)
  * 24h range >= 0.5% of price -- stablecoins exclude THEMSELVES by
    behavior; no hardcoded stablecoin list
  * not already in the universe; not resting on the no-data list
  * fiat bases (EUR, GBP, ...) routed away -- they are the forex
    lane's asset class, not a crypto ban

Caps: TREZO_CRYPTO_DISCOVER_MAX_ADDS per pass (default 3) and
TREZO_CRYPTO_DISCOVER_MAX_TOTAL discovered coins (default 15).
Removal is condition-driven too: a discovered coin whose 24h notional
falls under HALF the floor retires with a logged reason -- never
banned, it can re-qualify on any later pass.

Everything downstream still applies: TCS floor, fee-aware edge gate,
pockets, per-coin stops. Discovery only decides what gets LOOKED AT.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

_STATE_FILE = Path(__file__).with_name("crypto_discovered.json")
_last_run: float = 0.0
_state_cache: dict | None = None

# Fiat bases belong to the forex lane -- asset-class routing, not a ban.
_FIAT_BASES = {"EUR", "GBP", "USD", "CHF", "CAD", "JPY", "AUD", "NZD"}
_BASE_ALIAS = {"XBT": "BTC", "XDG": "DOGE"}


def _envf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def load_state() -> dict:
    global _state_cache
    if _state_cache is not None:
        return _state_cache
    try:
        _state_cache = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        _state_cache = {}
    return _state_cache


def _save_state(st: dict) -> None:
    global _state_cache
    _state_cache = st
    try:
        tmp = _STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=2), encoding="utf-8")
        tmp.replace(_STATE_FILE)
    except Exception:  # noqa: BLE001
        pass


def discovered_symbols() -> list[str]:
    return list(load_state().keys())


def hydrate() -> None:
    """Re-register Kraken pairs + coin params for every discovered coin.
    Cheap and idempotent -- called after discovery and on the scanner's
    first pass after a restart so in-memory registries repopulate."""
    try:
        from app.brokers.crypto_exchange import register_pair
        from app.strategies.crypto import ensure_coin_params
        for sym, meta in load_state().items():
            register_pair(sym, str(meta.get("pair") or (sym + "USD")))
            ensure_coin_params(sym, str(meta.get("tier") or "c"))
    except Exception:  # noqa: BLE001
        pass


def _norm_base(b: str) -> str:
    b = (b or "").upper()
    if len(b) == 4 and b[0] in ("X", "Z"):
        b = b[1:]
    return _BASE_ALIAS.get(b, b)


def _activity(event: str, sym: str, reason: str, extra: dict | None = None) -> None:
    try:
        from app.agents.activity_log import record
        record(event, sym, reason=reason, extra=extra or {})
    except Exception:  # noqa: BLE001
        pass


def _knowledge_note(line: str) -> None:
    """Append one line to the drop-box discovery note -- the daily library
    sweep turns it into shared agent knowledge."""
    try:
        base = (Path(__file__).resolve().parents[3] / ".." / "Quantconnect").resolve()
        f = base / "CRYPTO_UNIVERSE_DISCOVERY.md"
        if not f.exists():
            f.write_text(
                "# Crypto Universe Discovery Log (agent-maintained)\n\n"
                "The crypto expander enrolls/retires coins by CONDITIONS "
                "(USD spot on Kraken, 24h notional >= floor, real range; "
                "retire under half-floor). Mike's frame: crypto = stocks, "
                "just more liquid. Every change is logged here for the "
                "knowledge library.\n\n",
                encoding="utf-8")
        with f.open("a", encoding="utf-8") as fh:
            fh.write(line.rstrip() + "\n")
    except Exception:  # noqa: BLE001
        pass


async def run_discovery(force: bool = False) -> dict:
    """One expander pass. Throttled internally (TREZO_CRYPTO_DISCOVER_EVERY_H,
    default 6h). Returns a small summary dict for the scanner's feed note."""
    global _last_run
    every_h = _envf("TREZO_CRYPTO_DISCOVER_EVERY_H", 6.0)
    if not force and (time.time() - _last_run) < every_h * 3600.0:
        return {"skipped": True}
    _last_run = time.time()
    out: dict = {"added": [], "removed": [], "candidates": 0}
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get("https://api.kraken.com/0/public/AssetPairs")
            data = r.json()
        pairs: dict[str, str] = {}
        for _k, v in (data.get("result") or {}).items():
            alt = str(v.get("altname") or "")
            ws = str(v.get("wsname") or "")
            if not alt.endswith("USD") or "." in alt:
                continue
            base = _norm_base(ws.split("/")[0] if "/" in ws else alt[:-3])
            if not base or not base.isalnum() or len(base) > 6:
                continue
            if base in _FIAT_BASES:
                continue
            pairs[base] = alt

        # Broker-only (Mike 2026-07-28): never enrol a coin Alpaca
        # cannot execute -- discovery should widen the REAL universe,
        # not the modeled one. Alpaca lists 36 USD pairs vs the 20 the
        # scanner watches, so this is a bigger pool, not a smaller one.
        try:
            from app.config import get_settings as _gs_d
            if bool(getattr(_gs_d(), "trezo_broker_only", False)):
                from app.brokers.alpaca import tradable_crypto_symbols
                _ok = tradable_crypto_symbols()
                if _ok:
                    pairs = {b: p for b, p in pairs.items() if b in _ok}
        except Exception:  # noqa: BLE001
            pass

        from app.strategies.crypto import CRYPTO_WATCHLIST
        st = dict(load_state())
        have = set(CRYPTO_WATCHLIST) | set(st)
        cand = {b: p for b, p in pairs.items() if b not in have}
        out["candidates"] = len(cand)

        # Rest-listed coins wait their TTL out before re-qualifying.
        try:
            from app.data.candles import _NO_DATA
            cand = {b: p for b, p in cand.items()
                    if _NO_DATA.get("C:" + b, 0) < time.time()}
        except Exception:  # noqa: BLE001
            pass

        want = list(cand.values()) + [str(m.get("pair")) for m in st.values() if m.get("pair")]
        stats: dict[str, dict] = {}
        for i in range(0, len(want), 40):
            chunk = ",".join(want[i:i + 40])
            try:
                async with httpx.AsyncClient(timeout=15.0) as c:
                    r = await c.get("https://api.kraken.com/0/public/Ticker",
                                    params={"pair": chunk})
                for pk, pv in (r.json().get("result") or {}).items():
                    try:
                        vwap = float(pv["p"][1])
                        vol = float(pv["v"][1])
                        hi = float(pv["h"][1])
                        lo = float(pv["l"][1])
                        s_ = {"usd": vwap * vol,
                              "range": ((hi - lo) / vwap) if vwap > 0 else 0.0}
                        stats[pk] = s_
                        stats[_norm_base(pk[:-3]) + "USD"] = s_
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                continue
            await asyncio.sleep(0.35)   # polite to the public API

        floor = _envf("TREZO_CRYPTO_DISCOVER_MIN_VOL_USD", 5_000_000.0)

        # Condition-driven retirement: volume collapsed under half-floor.
        for sym in list(st):
            s_ = stats.get(str(st[sym].get("pair") or ""))
            if s_ and s_["usd"] < floor / 2.0:
                st.pop(sym, None)
                out["removed"].append(sym)
                _activity("crypto_universe_retire", sym,
                          reason=(f"24h notional ~${s_['usd']:,.0f} fell under "
                                  f"half the ${floor:,.0f} floor -- retired "
                                  f"(re-qualifies any time it recovers)"))
                _knowledge_note(
                    f"- {datetime.now(timezone.utc).date()}: {sym} RETIRED -- "
                    f"24h notional ~${s_['usd']/1e6:.1f}M under half-floor. "
                    f"Not a ban; re-qualifies on recovery.")

        qual: list[tuple[float, str, str]] = []
        for b, p in cand.items():
            s_ = stats.get(p) or stats.get(b + "USD")
            if not s_:
                continue
            if s_["usd"] >= floor and s_["range"] >= 0.005:
                qual.append((s_["usd"], b, p))
        qual.sort(reverse=True)

        max_adds = int(_envf("TREZO_CRYPTO_DISCOVER_MAX_ADDS", 3))
        max_total = int(_envf("TREZO_CRYPTO_DISCOVER_MAX_TOTAL", 15))
        room = max(0, max_total - len(st))
        for usd, b, p in qual[:max(0, min(max_adds, room))]:
            tier = "b" if usd >= 50_000_000 else "c"
            st[b] = {"pair": p, "tier": tier,
                     "added": datetime.now(timezone.utc).isoformat(),
                     "vol_usd": round(usd)}
            out["added"].append(b)
            _activity("crypto_universe_add", b,
                      reason=(f"enrolled by conditions: USD spot at Kraken "
                              f"({p}), 24h notional ~${usd:,.0f} >= "
                              f"${floor:,.0f} floor, real range; tier {tier}"),
                      extra={"pair": p, "tier": tier, "vol_usd": round(usd)})
            _knowledge_note(
                f"- {datetime.now(timezone.utc).date()}: {b} ENROLLED -- 24h "
                f"~${usd/1e6:.1f}M at Kraken ({p}), tier {tier}. Conditions: "
                f"USD spot, notional >= ${floor/1e6:.0f}M, range >= 0.5%.")

        _save_state(st)
        hydrate()
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:140]
    return out
