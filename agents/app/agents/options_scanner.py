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
from app.memory import get_memory, AgentDecision
from app.learning.recall_helpers import recall_decision_context
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

import time

# Wheel auto-fire cooldown (2026-06-16). When the broker rejects (or Trezo
# blocks) an auto CSP/CC, record a per-(user, underlying, strategy) cooldown
# so the SAME failing order is not re-submitted every 30-minute tick. That
# retry loop is what flooded the ticker with ERROR "wheel auto blocked"
# messages. The name is retried once the window elapses. In-memory only
# (clears on restart, so a restart re-tests the broker exactly once).
_WHEEL_BLOCK_COOLDOWN_S = 4 * 3600.0  # 4h: a couple retries a day, no spam
_wheel_block_until: dict[tuple[str, str, str], float] = {}


def _wheel_in_cooldown(user_id: str, underlying: str, strategy: str) -> bool:
    key = (str(user_id), str(underlying).upper(), str(strategy))
    until = _wheel_block_until.get(key)
    return until is not None and time.time() < until


def _wheel_set_cooldown(user_id: str, underlying: str, strategy: str) -> None:
    key = (str(user_id), str(underlying).upper(), str(strategy))
    _wheel_block_until[key] = time.time() + _WHEEL_BLOCK_COOLDOWN_S


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
    _last_rescore: float = 0.0
    _harvested: set = set()      # option-row ids already sent a harvest order
    _long_fired: set = set()     # 'L:SYM:date' one-shot guard for long entries
    name = "options_scanner"
    tick_interval_seconds = 1800  # every 30 minutes

    @staticmethod
    def leg_delta_of(net_delta: float | None, contracts: int | None) -> float | None:
        """Translate a POSITION-level, share-equivalent net delta into the
        per-leg delta fraction Mike's settings speak in (2026-06-12).
        Example: net_delta 24.18 with 1 contract -> 0.2418. Values already
        in fraction form (|d| <= 1.5) pass through unchanged. Returns None
        when the input can't be interpreted."""
        if net_delta is None:
            return None
        try:
            d = float(net_delta)
        except (TypeError, ValueError):
            return None
        if abs(d) > 1.5:
            d = d / (100.0 * max(int(contracts or 1), 1))
        if abs(d) > 1.5:
            return None
        return round(d, 4)

    def _greek_filter(self, *, expiration: str,
                      net_delta: float | None = None,
                      is_premium_sell: bool = False,
                      modeled_iv: float | None = None,
                      is_scalp_play: bool = False,
                      user_id: str | None = None,
                      contracts: int = 1,
                      n_legs: int = 1,
                      ) -> tuple[bool, str]:
        """Return (passes, reason). False reason is non-empty when the
        play was filtered out so the caller can log + surface why.

        Rules read from settings (Bot Tuning controls these):
          1. options_min_dte: any play within N DTE is skipped unless
             explicitly tagged as a scalp setup.
          2. options_max_premium_delta: premium-sell setups whose
             |net_delta| exceeds this are skipped (they are too
             stock-proxy-like for the Wheel income model).
          3. options_min_iv_rank_scalp: scalp setups require elevated
             IV (modeled_iv is the proxy when we lack a true rank).

        Per Mike's options-trading rules (project memory).
        """
        s = get_settings()
        # Phase C UI follow-up: when a user_id is provided, prefer their
        # per-user bot_settings override; fall through to env defaults.
        user_min_dte: int | None = None
        user_max_delta: float | None = None
        user_min_iv: float | None = None
        if user_id:
            try:
                from app.runtime.settings import get_bot_settings
                bs = get_bot_settings(user_id)
                user_min_dte = bs.options_min_dte
                user_max_delta = bs.options_max_premium_delta
                user_min_iv = bs.options_min_iv_rank_scalp
            except Exception:
                pass
        eff_min_dte = int(user_min_dte if user_min_dte is not None else s.options_min_dte)
        eff_max_delta = float(user_max_delta if user_max_delta is not None else s.options_max_premium_delta)
        eff_min_iv = float(user_min_iv if user_min_iv is not None else s.options_min_iv_rank_scalp)
        try:
            from datetime import date as _date
            exp = _date.fromisoformat(expiration[:10])
            today = _date.today()
            dte = (exp - today).days
        except Exception:
            dte = 999

        if dte < eff_min_dte and not is_scalp_play:
            return False, (
                f"DTE {dte} below min {eff_min_dte} - theta burn "
                f"risk too high without explicit scalp framing."
            )

        if is_premium_sell and net_delta is not None:
            # ---- Delta semantics fix (Mike, 2026-06-12) --------------
            # Two bugs lived here:
            # 1) UNITS: OptionPlay.net_delta is POSITION-level and
            #    share-equivalent (per-share delta x 100 x contracts).
            #    Comparing it against the 0.45 PER-LEG cap rejected
            #    essentially every premium sell (e.g. STAG bull put
            #    spread: "net delta 14.13 > 0.45" -- mem0 afa5668c).
            #    Normalize back to a per-leg fraction first.
            # 2) SEMANTICS: options_max_premium_delta is Mike's cap on
            #    the LEG delta for normal-cycle premium sells -- NOT a
            #    flat cap for every timeframe. LEAPs legitimately carry
            #    high delta (stock replacement) and same-day contracts
            #    swing delta too fast for it to gate risk; the cap must
            #    follow the timeframe. Ladder (Mike's bands: 0.05 floor,
            #    0.30 / 0.45 / 0.75 / 1.00):
            #      <=1 DTE    -> no delta cap (IV gate governs scalps)
            #      <=45 DTE   -> user's options_max_premium_delta (0.45)
            #      <=180 DTE  -> 0.75
            #      >180 LEAPs -> 1.00 (effectively uncapped)
            d = abs(float(net_delta))
            if d > 1.5:
                # Share-equivalent units -> per-leg fraction.
                d = d / (100.0 * max(int(contracts or 1), 1))
            if d > 1.5:
                # Still impossible as a per-share delta: bad upstream
                # data. Don't trade on numbers we can't interpret.
                return False, (
                    f"delta {net_delta} uninterpretable even after "
                    f"unit normalization - skipping on bad data."
                )
            # Structure awareness (Mike 2026-06-12, mem0 7c991cc1: an
            # iron condor on O was vetoed for its delta -- but a condor
            # is delta-neutral BY DESIGN; near-zero net delta is the
            # goal, not a defect). For multi-leg defined-risk spreads
            # the net delta measures the position's directional TILT:
            # small is good, so the 0.05 floor must not apply, and the
            # band cap only guards against a spread so lopsided it has
            # become a directional bet in disguise. The floor only
            # makes sense for SINGLE-leg shorts (CSP / covered call),
            # where a 0.03-delta strike truly is lottery-dust premium.
            is_spread = int(n_legs or 1) >= 2
            if dte <= 1:
                pass  # same-day: gamma rules; IV gate below governs
            else:
                if dte <= 45:
                    band_cap, band = eff_max_delta, f"<=45 DTE (user cap {eff_max_delta})"
                elif dte <= 180:
                    band_cap, band = max(0.75, eff_max_delta), "<=180 DTE (0.75)"
                else:
                    band_cap, band = 1.0, "LEAP >180 DTE (1.00)"
                if d > band_cap:
                    kind_txt = ("net directional tilt" if is_spread
                                else "per-leg |delta|")
                    return False, (
                        f"{kind_txt} {d:.2f} exceeds the {band} "
                        f"band cap for premium-sell."
                    )
                if d < 0.05 and not is_spread:
                    return False, (
                        f"per-leg |delta| {d:.2f} below the 0.05 floor - "
                        f"premium too thin to be worth fees on a "
                        f"single-leg short."
                    )

        if is_scalp_play and modeled_iv is not None:
            iv_pct = float(modeled_iv) * 100.0
            if iv_pct < eff_min_iv:
                return False, (
                    f"IV {iv_pct:.0f}% below scalp minimum "
                    f"{eff_min_iv}% - premium not "
                    f"juicy enough for short-DTE play."
                )

        return True, ""

    def _log_to_mem0(self, *, action: str, ticker: str, reasoning: str,
                     metadata: dict | None = None) -> str | None:
        """Persist an options-side decision to Mem0. Returns memory_id on
        success or None on any failure. NEVER raises - options trading
        cannot break because the memory layer hiccuped.
        """
        try:
            mem = get_memory()
            if not mem.available:
                return None
            return mem.log_decision(AgentDecision(
                agent="options_scanner",
                action=action,
                ticker=ticker,
                reasoning=reasoning,
                metadata=metadata or {},
            ))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Phase D: hopeful-holds bucket classification + 3% cap enforcement.
    # Wheel = wheel_csp / wheel_cc. Income = income-style premium plays
    # (CSPs, spreads). Hopeful = directional long calls / debit spreads
    # outside the Wheel - Mike's "3% of the time" bucket.
    # ------------------------------------------------------------------

    @staticmethod
    def _strategy_bucket(strategy: str) -> str:
        """Map a strategy name to its bucket. Used to enforce Mike's
        3% allocation cap on hopeful holds."""
        s = (strategy or "").lower()
        if s in ("wheel_csp", "wheel_cc"):
            return "wheel"
        if s in ("cash_secured_put", "bull_put_spread", "iron_condor",
                 "bear_call_spread"):
            return "income"
        if s in ("long_call", "long_put", "bull_call_spread"):
            return "hopeful"
        return "income"  # safe default

    async def _hopeful_allocation_pct(self, client, user_id: str) -> float:
        """Return the current open hopeful allocation as a fraction of
        total options capital. 0.0 when no open positions or query
        fails - fail OPEN so a quiet DB doesn't lock the user out."""
        def _sync():
            return (
                client.table("options_positions")
                .select("strategy, contracts, strike, net_premium_usd")
                .eq("user_id", user_id)
                .eq("status", "open")
                .execute()
            )
        try:
            res = await asyncio.to_thread(_sync)
            rows = res.data or []
        except Exception:
            return 0.0

        total_capital = 0.0
        hopeful_capital = 0.0
        for r in rows:
            strat = str(r.get("strategy") or "")
            bucket = self._strategy_bucket(strat)
            contracts = int(r.get("contracts") or 1)
            strike = float(r.get("strike") or 0.0)
            premium = float(r.get("net_premium_usd") or 0.0)
            # Capital at risk per row:
            #   wheel CSP -> strike * 100 * contracts (cash-secured)
            #   wheel CC  -> 0 (no cash at risk; underlying held separately)
            #   long debit play -> abs(premium) (debit paid)
            if bucket == "wheel" and "csp" in strat:
                cap = strike * 100.0 * contracts
            elif premium < 0:  # debit position
                cap = abs(premium)
            else:
                cap = strike * 100.0 * contracts * 0.1  # rough proxy for credit risk
            total_capital += cap
            if bucket == "hopeful":
                hopeful_capital += cap

        if total_capital <= 0:
            return 0.0
        return hopeful_capital / total_capital

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

        # --- 5. DIRECTIONAL: long calls/puts on the leading generals -------
        longs = await self._run_directional(client)
        out.extend(longs)

        if not out:
            out.append(AgentMessage(agent=self.name, kind="info",
                                    payload={"note": "Options scan complete — no actions."}))
        return out

    # ----------------------------------------------------------------------

    async def _run_directional(self, client) -> list[AgentMessage]:
        """LONG calls/puts on the strongest sector GENERALS (Mike 2026-07-14:
        "trade all level 3 option contracts, not just cash-secured puts").

        Defined-risk premium buying, deliberately tight:
          - candidates: SECTOR_BIAS generals moving >= 2.5% over 3 days
          - 1 contract, ~ATM, ~30 DTE, debit capped at TREZO_LONG_OPT_USD
            (default $120) AND 3% of equity -- the debit IS the max loss
          - at most TREZO_LONG_OPT_OPEN (2) long options open at once,
            one shot per underlying per day, one new entry per tick
          - exits live in the hourly re-score: +40% harvest, -50% cut,
            and always out by DTE <= 3 (no expiry roulette)
        Kill switch: TREZO_LONG_OPTIONS=0."""
        import os as _oso
        out: list[AgentMessage] = []
        if _oso.getenv("TREZO_LONG_OPTIONS", "1") != "1":
            return out
        try:
            from app.data.market_universe import SECTOR_BIAS
            gens = list(SECTOR_BIAS.get("generals") or [])
        except Exception:  # noqa: BLE001
            gens = []
        if not gens:
            return out
        try:
            from app.brokers.alpaca import (
                alpaca_configured, get_account, submit_option_order,
            )
            if not alpaca_configured():
                return out
            acct = await get_account()
            _eq = float(getattr(acct, "equity", 0) or 0)
            if int(getattr(acct, "options_approved_level", 0) or 0) < 2:
                return out      # long options need approval level >= 2
            uid = _oso.getenv("TREZO_PRIMARY_USER_ID", "")
            if not uid or await _user_halted(client, uid):
                return out
            _cap_usd = float(_oso.getenv("TREZO_LONG_OPT_USD", "120"))
            _max_open = int(_oso.getenv("TREZO_LONG_OPT_OPEN", "2"))
            _min_d3 = float(_oso.getenv("TREZO_LONG_OPT_MIN_D3", "2.5"))

            def _q_open():
                return (client.table("options_positions")
                        .select("id, underlying")
                        .eq("user_id", uid).eq("status", "open")
                        .like("strategy", "long_%").execute())
            _open = (await asyncio.to_thread(_q_open)).data or []
            if len(_open) >= _max_open:
                return out
            _held = {str(x.get("underlying") or "").upper() for x in _open}
            today_s = date.today().isoformat()
            for g in gens[:8]:
                sym = str(g.get("sym") or "").upper()
                try:
                    d3 = float(g.get("d3") or 0)
                except Exception:  # noqa: BLE001
                    continue
                _ck = f"L:{sym}:{today_s}"
                if (not sym or sym in _held or abs(d3) < _min_d3
                        or _ck in OptionsScannerAgent._long_fired):
                    continue
                cnd = await fetch_candles_for(sym, "stock")
                spot = float(cnd[-1].close) if cnd else 0.0
                if spot <= 0:
                    continue
                opt_type = "call" if d3 > 0 else "put"
                from datetime import timedelta as _tdl
                target_exp = (date.today() + _tdl(days=30)).isoformat()
                from app.brokers.alpaca_data import live_option_pick
                pick = await live_option_pick(sym, opt_type, spot, target_exp)
                if not pick:
                    continue
                prem = float(getattr(pick, "premium", 0) or 0)
                debit = prem * 100.0
                if prem <= 0 or debit > min(_cap_usd, 0.03 * max(_eq, 1.0)):
                    continue
                OptionsScannerAgent._long_fired.add(_ck)
                order, err = await submit_option_order(
                    str(pick.occ), 1, "buy", time_in_force="day",
                    limit_price=round(prem * 1.05, 2))
                from app.agents.activity_log import record as _arec
                if err or not order:
                    _arec("option_long_blocked", sym,
                          reason=f"long {opt_type} not placed: {str(err)[:100]}",
                          extra={"user_id": uid})
                    continue

                def _ins(s=sym, ot=opt_type, pk=pick, db=debit, dd=d3):
                    return client.table("options_positions").insert({
                        "user_id": uid,
                        "underlying": s,
                        "strategy": f"long_{ot}",
                        "direction": "long",
                        "option_type": ot,
                        "strike": float(pk.strike),
                        "expiration": str(pk.expiration),
                        "contracts": 1,
                        "net_premium_usd": -round(db, 2),
                        "legs": [{"action": "buy", "type": ot,
                                  "strike": float(pk.strike),
                                  "premium": float(pk.premium)}],
                        "notes": (f"Long {ot} on sector general ({dd:+.1f}% "
                                  f"3d). Placed via Alpaca. Exits: +40% "
                                  f"harvest / -50% cut / DTE<=3."),
                    }).execute()
                await asyncio.to_thread(_ins)
                _arec("option_long_open", sym, strategy=f"long_{opt_type}",
                      reason=(f"bought 1 {opt_type.upper()} {pick.strike:g} "
                              f"exp {str(pick.expiration)[:10]} at "
                              f"~{prem:.2f} (${debit:.0f} max risk) -- "
                              f"{sym} leading its sector {d3:+.1f}% over 3d"),
                      extra={"user_id": uid})
                out.append(AgentMessage(
                    agent=self.name, kind="execute",
                    payload={"user_id": uid, "event": "long_option_open",
                             "underlying": sym, "occ": str(pick.occ),
                             "debit_usd": round(debit, 2)}))
                break   # one new long option per tick, by design
        except Exception:  # noqa: BLE001
            pass
        return out

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

        # Held-option RE-SCORE (Mike 2026-07-02: "re-evaluate the IV score
        # ... for a current trade it is holding even though it has a stop
        # in"). Hourly, every open (non-expired) option row gets its thesis
        # re-measured from live data: current premium vs the credit
        # collected (the practical IV read for short premium), moneyness,
        # and days-to-expiry. ADVISORY by design -- exits keep the
        # drawback-ladder + expiry flow; this makes the risk VISIBLE.
        try:
            import time as _t
            if (_t.time() - OptionsScannerAgent._last_rescore) >= 3600.0:
                OptionsScannerAgent._last_rescore = _t.time()

                def _sync_open_live():
                    return (
                        client.table("options_positions")
                        .select("id, user_id, underlying, strategy, "
                                "option_type, strike, contracts, "
                                "net_premium_usd, expiration")
                        .eq("status", "open")
                        .gt("expiration", today)
                        .execute()
                    )
                _live = (await asyncio.to_thread(_sync_open_live)).data or []
                for lr in _live[:12]:
                    try:
                        _u = str(lr.get("underlying") or "").upper()
                        _strike = float(lr.get("strike") or 0)
                        _otype = str(lr.get("option_type") or "put").lower()
                        _exp = str(lr.get("expiration") or "")
                        _credit = float(lr.get("net_premium_usd") or 0)
                        _ct = int(lr.get("contracts") or 1)
                        if not _u or _strike <= 0 or len(_exp) < 10:
                            continue
                        _cnd = await fetch_candles_for(_u, "stock")
                        _spot = float(_cnd[-1].close) if _cnd else 0.0
                        _dte = (date.fromisoformat(_exp[:10])
                                - date.today()).days
                        _occ = (f"{_u}{_exp[2:4]}{_exp[5:7]}{_exp[8:10]}"
                                f"{'C' if _otype.startswith('c') else 'P'}"
                                f"{int(round(_strike * 1000)):08d}")
                        from app.brokers.alpaca_data import get_option_quote
                        _prem_now = await get_option_quote(_occ)
                        _entry_prem = (abs(_credit) / (100.0 * _ct)
                                       if _credit and _ct else None)
                        _ratio = ((float(_prem_now) / _entry_prem)
                                  if _prem_now and _entry_prem else None)
                        _money = ((_spot - _strike) / _strike * 100.0
                                  if _spot > 0 else None)
                        _risk = bool(
                            (_ratio is not None and _ratio >= 2.0)
                            or (_money is not None and _dte <= 5
                                and ((_otype.startswith("p") and _money < 2.0)
                                     or (_otype.startswith("c")
                                         and _money > -2.0))))
                        from app.agents.activity_log import record as _arec
                        _arec("reeval_option", _u,
                              strategy=str(lr.get("strategy") or ""),
                              reason=(f"{_otype.upper()} {_strike:g} exp "
                                      f"{_exp[:10]} (DTE {_dte}): premium now "
                                      + (f"{float(_prem_now):.2f}" if _prem_now else "?")
                                      + " vs entry "
                                      + (f"{_entry_prem:.2f}" if _entry_prem else "?")
                                      + (f" ({_ratio:.1f}x)" if _ratio else "")
                                      + (f", spot {_money:+.1f}% vs strike"
                                         if _money is not None else "")
                                      + (" -- RISK: thesis deteriorating"
                                         if _risk else " -- healthy")),
                              extra={"user_id": str(lr.get("user_id"))})
                        # EARLY PREMIUM HARVEST (Mike 2026-07-14: "collect
                        # the premium and avoid having to wait for the end
                        # of the contract"). Short premium that has already
                        # earned most of its credit gets bought back NOW:
                        # >=60% of max profit any time, or >=35% inside 5
                        # DTE. Real limit order at the live quote; the
                        # reconcile pass books the exact realized P&L when
                        # the leg clears. Long options exit here too:
                        # +40% harvest, -50% cut, always out by DTE<=3.
                        try:
                            import os as _oso
                            _strat_l = str(lr.get("strategy") or "")
                            _short = not _strat_l.startswith("long_")
                            _hk = f"h:{lr.get('id')}"
                            _fresh = _hk not in OptionsScannerAgent._harvested
                            if _fresh and _ratio is not None and _prem_now:
                                _fire = None
                                if _short:
                                    _h_at = float(_oso.getenv(
                                        "TREZO_OPT_HARVEST_AT", "0.40"))
                                    _h_dte = int(_oso.getenv(
                                        "TREZO_OPT_HARVEST_DTE", "5"))
                                    _h_da = float(_oso.getenv(
                                        "TREZO_OPT_HARVEST_DTE_AT", "0.65"))
                                    if (_ratio <= _h_at
                                            or (_dte <= _h_dte
                                                and _ratio <= _h_da)):
                                        _fire = ("buy",
                                                 round(max(0.01, float(_prem_now)) * 1.05, 2),
                                                 (f"buying back {_otype.upper()} {_strike:g} exp "
                                                  f"{_exp[:10]} to bank ~{(1.0 - _ratio) * 100:.0f}% "
                                                  f"of the premium early"))
                                else:
                                    if (_ratio >= 1.40 or _ratio <= 0.50
                                            or _dte <= 3):
                                        _why = ("+40% target hit" if _ratio >= 1.40
                                                else ("-50% cut" if _ratio <= 0.50
                                                      else "DTE<=3 time exit"))
                                        _fire = ("sell",
                                                 round(max(0.01, float(_prem_now)) * 0.95, 2),
                                                 (f"selling to close {_otype.upper()} {_strike:g} "
                                                  f"exp {_exp[:10]} -- {_why}"))
                                if _fire:
                                    OptionsScannerAgent._harvested.add(_hk)
                                    from app.brokers.alpaca import submit_option_order as _soo
                                    _o2, _e2 = await _soo(
                                        _occ, _ct, _fire[0],
                                        time_in_force="day",
                                        limit_price=_fire[1])
                                    _arec("option_harvest", _u,
                                          strategy=_strat_l,
                                          reason=(_fire[2] + f" (limit {_fire[1]:.2f})"
                                                  if not _e2 else
                                                  f"harvest order failed: {str(_e2)[:90]}"),
                                          extra={"user_id": str(lr.get("user_id"))})
                        except Exception:  # noqa: BLE001
                            pass
                        if _risk:
                            out.append(AgentMessage(
                                agent=self.name, kind="alert",
                                payload={
                                    "user_id": lr.get("user_id"),
                                    "underlying": _u,
                                    "note": (f"Held option risk: {_otype} "
                                             f"{_strike:g} exp {_exp[:10]} -- "
                                             "premium "
                                             + (f"{_ratio:.1f}x entry"
                                                if _ratio else "n/a")
                                             + f", DTE {_dte}. Advisory only."),
                                },
                            ))
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            pass

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
                # 2026-07-14 (Mike saw a wall of $0 rows): recover the TRUE
                # exit instead of booking zero. Find the closing fill at
                # Alpaca for this OCC and book credit-vs-debit properly:
                # short premium -> credit kept minus the buy-back cost;
                # long options -> sale proceeds minus the debit paid.
                realized = 0.0
                exit_note = " · Reconciled — not present at broker."
                try:
                    _credit = float(r.get("net_premium_usd") or 0)
                    _ctr = int(r.get("contracts") or 1)
                    _is_long = str(r.get("strategy") or "").startswith("long_")
                    _occ_r = (f"{str(r['underlying']).upper()}"
                              f"{str(r['expiration'])[2:4]}{str(r['expiration'])[5:7]}"
                              f"{str(r['expiration'])[8:10]}"
                              f"{'C' if str(r['option_type']).lower().startswith('c') else 'P'}"
                              f"{int(round(float(r['strike']) * 1000)):08d}")
                    from app.brokers.alpaca import get_recent_closed_orders as _grco
                    _fills = await _grco(_occ_r, token=token, limit=8)
                    for f in _fills:
                        if str(f.get("status", "")) != "filled":
                            continue
                        _px = float(f.get("filled_avg_price") or 0)
                        if _px <= 0:
                            continue
                        _amt = _px * 100.0 * _ctr
                        _side = str(f.get("side", ""))
                        if _is_long and _side.startswith("sell"):
                            realized = round(_amt - abs(_credit), 2)
                            exit_note = (f" · Sold to close at {_px:.2f} -> "
                                         f"realized ${realized:+.2f}.")
                            break
                        if (not _is_long) and _side.startswith("buy"):
                            realized = round(_credit - _amt, 2)
                            exit_note = (f" · Bought back at {_px:.2f} -> "
                                         f"realized ${realized:+.2f}.")
                            break
                except Exception:  # noqa: BLE001
                    pass

                def _sync_close(rid=r["id"], pnl=realized, en=exit_note):
                    return (
                        client.table("options_positions")
                        .update({
                            "status": "closed_manual",
                            "realized_pnl_usd": pnl,
                            "closed_at": "now()",
                            "notes": (notes + en).strip(" ·"),
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

        # Pre-gates (2026-06-12): yesterday produced 120x "options market
        # orders are only allowed during market hours" (fired at night)
        # and 190x "insufficient options buying power" (retried every
        # tick) -- both knowable BEFORE submitting. Check the clock and
        # the collateral requirement first; skip QUIETLY when closed
        # (the suggestion row already exists for the Wheel page) and
        # once-per-tick loudly when underfunded.
        try:
            from app.brokers.alpaca import get_clock
            clock = await get_clock(token=token)
            if not clock or not clock.get("is_open"):
                return None  # market closed - try again next tick
        except Exception:  # noqa: BLE001
            pass  # clock unavailable -> let Alpaca decide
        if strategy == "wheel_csp":
            try:
                collateral = float(pick.strike) * 100.0 * int(leg.contracts or 1)
                opt_bp = float(getattr(acct, "options_buying_power", 0) or
                               getattr(acct, "buying_power", 0) or 0)
                # Wheel collateral allowance (2026-07-06, found live: three
                # CSPs consumed 95% of equity and $0 BP 403'd every stock
                # order). CSP cash is reserved-not-spent, but it still
                # starves every other lane -- cap TOTAL open CSP collateral
                # at TREZO_WHEEL_COLLATERAL_PCT (default 50%) of equity.
                try:
                    import os as _os
                    _eq = float(getattr(acct, "equity", 0) or 0)
                    # Posture-scaled wheel limits (Mike 2026-07-08: "an
                    # account this small should focus on growth and should
                    # NOT be locking capital for 30 days across 3 trades").
                    # Small/growth accounts: 1 CSP, <=21 DTE, 25% collateral.
                    # The caps loosen as the account grows into balanced /
                    # income postures. Env overrides trump posture defaults.
                    _limits = {"growth": (0.25, 1, 21),
                               "balanced": (0.40, 2, 35),
                               "income": (0.50, 3, 45)}
                    try:
                        from app.paper.allocation import default_posture
                        from app.runtime.settings import get_bot_settings as _gbs
                        _post = str(getattr(_gbs(), "account_posture", "auto") or "auto")
                        if _post not in _limits:
                            _post = default_posture(_eq)
                    except Exception:  # noqa: BLE001
                        _post = "growth"
                    _d_pct, _d_max, _d_dte = _limits.get(_post, _limits["growth"])
                    _cap_pct = float(_os.getenv("TREZO_WHEEL_COLLATERAL_PCT",
                                                str(_d_pct)))
                    _max_csp = int(float(_os.getenv("TREZO_WHEEL_MAX_OPEN_CSP",
                                                    str(_d_max))))
                    _max_dte = int(float(_os.getenv("TREZO_WHEEL_MAX_DTE",
                                                    str(_d_dte))))
                    # DTE gate: no long lock-ups on small accounts.
                    try:
                        from datetime import date as _dd
                        _exp = str(getattr(leg, "expiration", None)
                                   or getattr(pick, "expiration", "") or "")[:10]
                        if len(_exp) == 10:
                            _dte_v = (_dd.fromisoformat(_exp) - _dd.today()).days
                            if _dte_v > _max_dte:
                                from app.agents.activity_log import record as _arecd
                                _arecd("wheel_limit", underlying,
                                       reason=(f"CSP skipped: {_dte_v} DTE exceeds the "
                                               f"{_post}-posture cap of {_max_dte} days "
                                               f"- no long capital lock-ups at this size"),
                                       extra={"user_id": str(user_id)})
                                return AgentMessage(
                                    agent=self.name, kind="info",
                                    payload={"user_id": user_id,
                                             "event": "wheel_limit",
                                             "underlying": underlying,
                                             "reason": f"DTE {_dte_v} > {_max_dte} ({_post})",
                                             "routed_via": routed})
                    except Exception:  # noqa: BLE001
                        pass
                    if _eq > 0 and _cap_pct > 0:
                        from app.runtime.settings import _supabase as _sb
                        _cl = _sb()
                        if _cl is None:
                            raise RuntimeError("no client")
                        def _q_csp():
                            return (_cl.table("options_positions")
                                    .select("strike, contracts")
                                    .eq("user_id", user_id)
                                    .eq("status", "open")
                                    .eq("strategy", "wheel_csp")
                                    .execute())
                        import asyncio as _aio
                        _open_csp = (await _aio.to_thread(_q_csp)).data or []
                        _held_coll = sum(
                            float(x.get("strike") or 0) * 100.0
                            * int(x.get("contracts") or 1)
                            for x in _open_csp)
                        # Concurrent-CSP gate (posture-scaled).
                        if len(_open_csp) >= _max_csp:
                            from app.agents.activity_log import record as _arecc
                            _arecc("wheel_limit", underlying,
                                   reason=(f"CSP skipped: {len(_open_csp)} already "
                                           f"open = the {_post}-posture max "
                                           f"({_max_csp}) - capital stays free "
                                           f"for the growth lanes"),
                                   extra={"user_id": str(user_id)})
                            return AgentMessage(
                                agent=self.name, kind="info",
                                payload={"user_id": user_id,
                                         "event": "wheel_limit",
                                         "underlying": underlying,
                                         "reason": f"open CSPs {len(_open_csp)} >= {_max_csp} ({_post})",
                                         "routed_via": routed})
                        if _held_coll + collateral > _cap_pct * _eq:
                            try:
                                from app.agents.activity_log import record as _arec
                                _arec("wheel_collateral_cap", underlying,
                                      reason=(f"CSP skipped: ${_held_coll:,.0f} already "
                                              f"reserved + ${collateral:,.0f} new would pass "
                                              f"{_cap_pct * 100:.0f}% of equity (${_eq:,.0f}) "
                                              f"- other lanes keep their buying power"),
                                      extra={"user_id": str(user_id)})
                            except Exception:  # noqa: BLE001
                                pass
                            return AgentMessage(
                                agent=self.name, kind="info",
                                payload={
                                    "user_id": user_id,
                                    "event": "wheel_collateral_cap",
                                    "underlying": underlying,
                                    "reason": (
                                        f"Wheel collateral allowance reached "
                                        f"({_cap_pct * 100:.0f}% of equity) - "
                                        f"skipped so other lanes keep buying power."),
                                    "routed_via": routed,
                                },
                            )
                except Exception:  # noqa: BLE001
                    pass
                # 2026-06-16: dropped the "opt_bp and" guard. When buying
                # power is 0 (small account fully deployed by existing CSPs),
                # the old guard let the order through to Alpaca, which rejected
                # it as an ERROR every tick. Treat 0/insufficient BP as a quiet
                # info skip instead of hammering the broker.
                if collateral > opt_bp:
                    return AgentMessage(
                        agent=self.name, kind="info",
                        payload={
                            "user_id": user_id,
                            "event": "wheel_auto_blocked",
                            "underlying": underlying,
                            "strategy": strategy,
                            "reason": (
                                f"CSP needs ${collateral:,.0f} collateral but "
                                f"account buying power is ${opt_bp:,.0f} "
                                f"(account fully deployed). Skipped without "
                                f"hitting Alpaca."
                            ),
                            "routed_via": routed,
                        },
                    )
            except Exception:  # noqa: BLE001
                pass

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
                    # Fixed 2026-06-12: broker_order_id and source_payload
                    # are NOT columns on options_positions -- their
                    # presence made PostgREST reject the whole insert, so
                    # the ARCC put fired at Alpaca but was never tracked
                    # (wheel_auto_tracking_failed). Fold them into notes.
                    "notes": (note + " · Placed via Alpaca · auto-fired"
                              + f" · occ={pick.occ}"
                              + f" · order_id={order_id}"
                              + f" · routed={routed}"),
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

        mem_id = self._log_to_mem0(
            action="wheel_auto_placed",
            ticker=underlying,
            reasoning=note,
            metadata={
                "user_id": user_id,
                "strategy": strategy,
                "occ": pick.occ,
                "strike": pick.strike,
                "expiration": pick.expiration,
                "contracts": int(leg.contracts or 1),
                "premium_per_share": pick.premium,
                "credit_usd": float(pick.premium or 0) * 100 * int(leg.contracts or 1),
                "alpaca_order_id": order_id,
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
                "options_scanner_memory_id": mem_id,
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
                        # 2026-06-16: skip names the broker recently rejected
                        # so a failing CSP/CC is not re-submitted every tick
                        # (that retry loop flooded the ticker with ERROR
                        # "wheel auto blocked"). Retried after the cooldown.
                        if _wheel_in_cooldown(user_id, leg.underlying, strategy):
                            continue
                        # AUTO-FIRE PATH
                        autofire = await self._wheel_auto_fire(
                            user_id=user_id,
                            underlying=leg.underlying,
                            leg=leg,
                            strategy=strategy,
                            priced=priced,
                        )
                        if autofire is not None:
                            ev = (autofire.payload or {}).get("event")
                            if ev in ("wheel_auto_blocked",
                                      "wheel_auto_tracking_failed"):
                                _wheel_set_cooldown(
                                    user_id, leg.underlying, strategy)
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
                    # Phase C: DTE gate on wheel legs (delta is not
                    # computed for the WheelLeg; only DTE applies).
                    passed_wheel, reason_wheel = self._greek_filter(
                        expiration=leg.expiration,
                        is_premium_sell=True,
                        modeled_iv=getattr(leg, "modeled_iv", None),
                        user_id=user_id,
                    )
                    if not passed_wheel:
                        self._log_to_mem0(
                            action="wheel_suggestion_filtered",
                            ticker=leg.underlying,
                            reasoning=f"Filtered: {reason_wheel}",
                            metadata={"strategy": strategy,
                                      "expiration": leg.expiration},
                        )
                        continue

                    # Phase E: include similar-past-setups summary
                    try:
                        recall = recall_decision_context(
                            ticker=leg.underlying, strategy=strategy,
                            extra_query="wheel",
                        )
                    except Exception:
                        recall = {"available": False}

                    mem_id = self._log_to_mem0(
                        action="wheel_suggestion",
                        ticker=leg.underlying,
                        reasoning=suggestion_note,
                        metadata={
                            "user_id": user_id,
                            "strategy": strategy,
                            "credit_usd": leg.credit_usd,
                            "strike": leg.strike,
                            "expiration": leg.expiration,
                            "live_chain": getattr(leg, "live", False),
                        },
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
                            "options_scanner_memory_id": mem_id,
                            "learning_context": recall,
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
                mem_id_modeled = self._log_to_mem0(
                    action="wheel_modeled_open",
                    ticker=leg.underlying,
                    reasoning=nt,
                    metadata={
                        "user_id": user_id,
                        "strategy": strategy,
                        "credit_usd": leg.credit_usd,
                        "strike": leg.strike,
                        "expiration": leg.expiration,
                        "modeled": True,
                    },
                )
                out.append(AgentMessage(
                    agent=self.name, kind="execute",
                    payload={
                        "user_id": user_id,
                        "underlying": leg.underlying,
                        "strategy": strategy,
                        "credit_usd": leg.credit_usd,
                        "strike": leg.strike,
                        "modeled": not getattr(leg, "live", False),
                        "options_scanner_memory_id": mem_id_modeled,
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
            from app.strategies.options_strategies import (
                build_bear_call_spread, build_butterfly, build_long_put,
            )
            for builder in (build_long_call, build_long_put,
                            build_bull_call_spread, build_bear_call_spread,
                            build_cash_secured_put, build_bull_put_spread,
                            build_iron_condor, build_butterfly):
                play = builder(underlying, candles)
                if not play:
                    continue
                    continue
                # Phase D: tag the bucket. Ideas are broadcast (no
                # user_id), so per-user cap enforcement happens
                # downstream in Risk Manager / UI. We still surface
                # the bucket so the rendering can warn.
                bucket = self._strategy_bucket(play.strategy)

                # Phase C Greek filter - skip plays that violate user's
                # Greek thresholds, but log the skip so the user can see
                # what was suppressed and adjust thresholds.
                is_premium_sell = play.direction == "income" or play.strategy in (
                    "cash_secured_put", "bull_put_spread", "iron_condor",
                    "bear_call_spread",
                )
                is_scalp = play.strategy in ("iron_condor",) or (
                    play.direction == "income" and play.contracts <= 3
                )
                passed, reason = self._greek_filter(
                    expiration=play.expiration,
                    net_delta=play.net_delta,
                    is_premium_sell=is_premium_sell,
                    modeled_iv=play.modeled_iv,
                    is_scalp_play=is_scalp,
                    contracts=int(getattr(play, "contracts", 1) or 1),
                    n_legs=len(getattr(play, "legs", None) or []) or 1,
                )
                if not passed:
                    self._log_to_mem0(
                        action="options_idea_filtered",
                        ticker=play.underlying,
                        reasoning=f"Filtered: {reason}",
                        metadata={
                            "strategy": play.strategy,
                            "expiration": play.expiration,
                            "net_delta": play.net_delta,
                            "net_delta_units": "share_equivalent",
                            "leg_delta": self.leg_delta_of(
                                play.net_delta, play.contracts),
                            "n_legs": len(getattr(play, "legs", None) or []) or 1,
                            "filter_rule": reason[:120],
                            "modeled_iv": play.modeled_iv,
                        },
                    )
                    continue

                mem_id_idea = self._log_to_mem0(
                    action="options_idea",
                    ticker=play.underlying,
                    reasoning=str(play.notes or play.strategy),
                    metadata={
                        "strategy": play.strategy,
                        "direction": play.direction,
                        "expiration": play.expiration,
                        "contracts": play.contracts,
                        "net_premium_usd": play.net_premium_usd,
                        "max_loss_usd": play.max_loss_usd,
                        "max_gain_usd": play.max_gain_usd,
                        "net_delta": play.net_delta,
                        "net_delta_units": "share_equivalent",
                        "leg_delta": self.leg_delta_of(
                            play.net_delta, play.contracts),
                        "net_theta": play.net_theta,
                    },
                )
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
                        "net_delta_units": "share_equivalent",
                        "leg_delta": self.leg_delta_of(
                            play.net_delta, play.contracts),
                        "net_gamma": play.net_gamma,
                        "net_theta": play.net_theta,
                        "net_vega": play.net_vega,
                        "legs": play.legs,
                        "notes": play.notes,
                        "options_scanner_memory_id": mem_id_idea,
                        "bucket": bucket,
                    },
                ))
        return out
