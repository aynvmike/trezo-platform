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
    _spread_fired: set = set()   # 'S:date' one-new-spread-per-day guard
    _day_fired: set = set()      # 'D:date:SYM' same-day entry guards
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

        # --- 6. SPREADS: defined-risk multi-leg, one ticket at Alpaca ------
        spreads = await self._run_spreads(client)
        out.extend(spreads)

        # --- 7. SAME-DAY options: morning gamma, managed on a 60s leash ----
        dayopts = await self._run_same_day(client)
        out.extend(dayopts)

        if not out:
            out.append(AgentMessage(agent=self.name, kind="info",
                                    payload={"note": "Options scan complete — no actions."}))
        return out

    # ----------------------------------------------------------------------

    async def _run_same_day(self, client) -> list[AgentMessage]:
        """SAME-DAY OPTIONS (Mike 2026-07-14: bought early enough, an
        ITM/ATM contract often pays +30% fast -- and if it reverses you
        SELL, because "it reverses way too fast to hope of a comeback").

        Entries MORNING ONLY (~9:35-11:30 ET); exits live in Position
        Monitor on its 60-second tick (+30% fast take, -25% reversal cut,
        force-close 3:45 ET -- never hold into the close). Theta is
        accepted consciously: this lane rents GAMMA, and either it pays
        early or we leave. Strikes lean ITM/ATM so delta stays honest.
        PDT-aware: under $25k equity the 3-day-trades-per-5-sessions
        budget is shared with the stock scalps -- this lane never spends
        the last slot. Kill switch TREZO_DAY_OPTIONS=0."""
        import os as _oso
        out: list[AgentMessage] = []
        if _oso.getenv("TREZO_DAY_OPTIONS", "1") != "1":
            return out
        uid = _oso.getenv("TREZO_PRIMARY_USER_ID", "")
        if not uid:
            return out
        today_s = date.today().isoformat()
        try:
            from datetime import datetime as _dtn
            from datetime import timezone as _tzn
            _now = _dtn.now(_tzn.utc)
            _h = _now.hour + _now.minute / 60.0
            # ~9:35-11:30 ET: 13.58-15.5 UTC in EDT, 14.58-16.5 in EST --
            # accept the union (DST-naive, same approach as STMS).
            if not (13.58 <= _h <= 16.5):
                return out
            from app.brokers.alpaca import (
                alpaca_configured, get_account, get_clock,
                submit_option_order,
            )
            if not alpaca_configured():
                return out
            clock = await get_clock()
            if not clock or not clock.get("is_open"):
                return out
            acct = await get_account()
            _eq = float(getattr(acct, "equity", 0) or 0)
            if int(getattr(acct, "options_approved_level", 0) or 0) < 2:
                return out
            # PDT: FINRA ELIMINATED the pattern-day-trader rule and the
            # $25k minimum effective 2026-06-04 (SEC approved 2026-04-14);
            # only the standard $2k margin-account floor remains. Brokers
            # may phase in until Oct 2027, so we follow the BROKER: gate
            # on the margin floor here, and if Alpaca still rejects a day
            # trade during its phase-in, that reject (caught below) stands
            # the lane down for the rest of the day.
            _pdt_floor = float(_oso.getenv("TREZO_PDT_MIN_EQUITY", "2000"))
            if _eq < _pdt_floor:
                if f"pdt:{today_s}" not in OptionsScannerAgent._day_fired:
                    OptionsScannerAgent._day_fired.add(f"pdt:{today_s}")
                    from app.agents.activity_log import record as _arec
                    _arec("option_day_skip", "ACCOUNT",
                          reason=(f"same-day options paused: equity "
                                  f"${_eq:,.0f} under the ${_pdt_floor:,.0f} "
                                  f"margin floor"),
                          extra={"user_id": uid})
                return out
            if f"pdtstop:{today_s}" in OptionsScannerAgent._day_fired:
                return out
            if await _user_halted(client, uid):
                return out
            # Flexible capital (Mike 2026-07-14): same-day trades give the
            # money back the same session, so they breathe wider than the
            # held-position caps -- $300 or 8% of equity by default.
            _budget = min(float(_oso.getenv("TREZO_DAY_OPT_USD", "300")),
                          float(_oso.getenv("TREZO_DAY_OPT_PCT", "0.08"))
                          * max(_eq, 1.0))
            _max_open = int(_oso.getenv("TREZO_DAY_OPT_OPEN", "1"))
            _max_day = int(_oso.getenv("TREZO_DAY_OPT_PER_DAY", "2"))
            _min_mv = float(_oso.getenv("TREZO_DAY_OPT_MIN_MOVE", "0.008"))

            def _q_open():
                return (client.table("options_positions")
                        .select("id").eq("user_id", uid)
                        .eq("status", "open")
                        .eq("strategy", "option_day").execute())
            _openr = (await asyncio.to_thread(_q_open)).data or []
            if len(_openr) >= _max_open:
                return out
            _fired_today = [k for k in OptionsScannerAgent._day_fired
                            if k.startswith(f"D:{today_s}:")]
            if len(_fired_today) >= _max_day:
                return out
            # Candidates: index ETFs first (true same-day expiries), then
            # the sector generals -- ranked by TODAY's move + volume pace.
            try:
                from app.data.market_universe import SECTOR_BIAS
                _gs = [str(g.get("sym") or "").upper()
                       for g in (SECTOR_BIAS.get("generals") or [])]
            except Exception:  # noqa: BLE001
                _gs = []
            cands = ["SPY", "QQQ"] + [s for s in _gs if s][:8]
            scored = []
            for sym in cands:
                if f"D:{today_s}:{sym}" in OptionsScannerAgent._day_fired:
                    continue
                cnd = await fetch_candles_for(sym, "stock")
                if not cnd or len(cnd) < 22:
                    continue
                spot = float(cnd[-1].close)
                prev = float(cnd[-2].close)
                if spot <= 0 or prev <= 0:
                    continue
                mv = spot / prev - 1.0
                try:
                    _vols = [float(c.volume or 0) for c in cnd[-21:]]
                    _v_avg = sum(_vols[:-1]) / max(len(_vols) - 1, 1)
                    _pace = (_vols[-1] / _v_avg) if _v_avg > 0 else 0.0
                except Exception:  # noqa: BLE001
                    _pace = 0.0
                if abs(mv) >= _min_mv and _pace >= 0.4:
                    scored.append((abs(mv), mv, _pace, sym, spot))
            if not scored:
                return out
            scored.sort(reverse=True)
            _, mv, _pace, sym, spot = scored[0]
            opt_type = "call" if mv > 0 else "put"
            # ITM-lean strike (Mike: "In the Money or directly at the
            # line") -- a touch of intrinsic keeps delta honest.
            strike = round(spot * (0.995 if opt_type == "call" else 1.005), 2)
            from app.brokers.alpaca_data import live_option_pick
            pick = await live_option_pick(sym, opt_type, strike, today_s)
            if not pick:
                return out
            _dte_v = 99
            try:
                _dte_v = (date.fromisoformat(str(pick.expiration)[:10])
                          - date.today()).days
            except Exception:  # noqa: BLE001
                pass
            if _dte_v > 5:
                return out          # this lane trades SHORT-dated only
            prem = float(getattr(pick, "premium", 0) or 0)
            debit = prem * 100.0
            if prem <= 0 or debit > _budget:
                return out
            # Profit-probability screen (Mike 2026-07-14: "not cheap or
            # expensive but the profit probability that can be recovered
            # in the shortest time"): the ITM-lean strike keeps delta
            # responsive, and sub-dime / dust premium (< 0.4% of spot) is
            # lottery-grade -- low odds of a FAST +30%, so it is skipped.
            if prem < max(0.10, 0.004 * spot):
                return out
            # The BUDGET is the cap, not an arbitrary contract count.
            _ctn = max(1, min(int(_oso.getenv("TREZO_DAY_OPT_CT_MAX", "10")),
                              int(_budget // max(debit, 1.0))))
            OptionsScannerAgent._day_fired.add(f"D:{today_s}:{sym}")
            order, err = await submit_option_order(
                str(pick.occ), _ctn, "buy", time_in_force="day",
                limit_price=round(prem * 1.05, 2))
            from app.agents.activity_log import record as _arec
            if err or not order:
                _el = str(err or "").lower()
                if any(t in _el for t in ("pattern day", "day trade", "pdt")):
                    OptionsScannerAgent._day_fired.add(f"pdtstop:{today_s}")
                    _arec("option_day_skip", "ACCOUNT",
                          reason=("broker still enforces day-trade limits "
                                  "(PDT phase-in) -- same-day lane stands "
                                  "down for today"),
                          extra={"user_id": uid})
                _arec("option_day_blocked", sym,
                      reason=(f"same-day {opt_type} not placed: "
                              f"{str(err)[:100]}"),
                      extra={"user_id": uid})
                return out

            def _ins():
                return client.table("options_positions").insert({
                    "user_id": uid,
                    "underlying": sym,
                    "strategy": "option_day",
                    "direction": "long",
                    "option_type": opt_type,
                    "strike": float(pick.strike),
                    "expiration": str(pick.expiration),
                    "contracts": _ctn,
                    "net_premium_usd": -round(debit * _ctn, 2),
                    "legs": [{"action": "buy", "type": opt_type,
                              "strike": float(pick.strike),
                              "premium": prem}],
                    "notes": (f"SAME-DAY rule (Mike): +30% fast take, -25% "
                              f"reversal cut, force-close 3:45 ET; theta "
                              f"accepted -- gamma pays early or we leave. "
                              f"Entry move {mv * 100:+.1f}%, volume pace "
                              f"{_pace:.1f}x, DTE {_dte_v}. "
                              f"Placed via Alpaca."),
                }).execute()
            await asyncio.to_thread(_ins)
            _arec("option_day_open", sym, strategy="option_day",
                  reason=(f"bought {_ctn} same-day {opt_type.upper()} "
                          f"{pick.strike:g} (DTE {_dte_v}) at ~{prem:.2f} "
                          f"(${debit * _ctn:.0f} max risk) -- {sym} moving "
                          f"{mv * 100:+.1f}% on {_pace:.1f}x volume pace; "
                          f"morning-only entry"),
                  extra={"user_id": uid})
            out.append(AgentMessage(
                agent=self.name, kind="execute",
                payload={"user_id": uid, "event": "option_day_open",
                         "underlying": sym, "occ": str(pick.occ),
                         "debit_usd": round(debit * _ctn, 2)}))
        except Exception:  # noqa: BLE001
            pass
        return out

    async def _run_spreads(self, client) -> list[AgentMessage]:
        """DEFINED-RISK MULTI-LEG (Mike 2026-07-14: "I would like for the
        agents to be able to trade them"): a credit spread WITH the trend
        on the strongest general, or an iron condor on SPY when the tape
        is quiet. Fired as ONE ticket at Alpaca (order_class=mleg,
        needs options approval Level 3).

        Guardrails: max loss per spread <= TREZO_SPREAD_RISK_USD ($150 --
        the wings ARE the stop), at most TREZO_SPREAD_OPEN (1) open at a
        time, one NEW spread per day, the credit must be real DOLLARS
        toward the daily goal (TREZO_SPREAD_MIN_CREDIT, default $20;
        10% pennies-vs-wing floor), and the market must be open. Kill
        switch TREZO_SPREADS=0.
        Exits v1: spreads are built to be HELD -- expiry settles them and
        the wings cap the loss; the hourly re-score skips multi-leg rows
        so it never prices one leg as the whole position."""
        import os as _oso
        out: list[AgentMessage] = []
        if _oso.getenv("TREZO_SPREADS", "1") != "1":
            return out
        uid = _oso.getenv("TREZO_PRIMARY_USER_ID", "")
        if not uid:
            return out
        today_s = date.today().isoformat()
        if f"S:{today_s}" in OptionsScannerAgent._spread_fired:
            return out
        try:
            from app.brokers.alpaca import (
                alpaca_configured, get_account, get_clock, submit_mleg_order,
            )
            if not alpaca_configured():
                return out
            clock = await get_clock()
            if not clock or not clock.get("is_open"):
                return out
            acct = await get_account()
            if int(getattr(acct, "options_approved_level", 0) or 0) < 3:
                return out          # spreads need Level 3
            if await _user_halted(client, uid):
                return out
            _risk_cap = float(_oso.getenv("TREZO_SPREAD_RISK_USD", "150"))
            _max_open = int(_oso.getenv("TREZO_SPREAD_OPEN", "1"))

            def _q_open():
                return (client.table("options_positions")
                        .select("id, strategy").eq("user_id", uid)
                        .eq("status", "open")
                        .in_("strategy", ["bull_put_spread",
                                          "bear_call_spread", "iron_condor",
                                          "butterfly", "bull_call_spread"])
                        .execute())
            _open = (await asyncio.to_thread(_q_open)).data or []
            if len(_open) >= _max_open:
                return out

            # Pick the play: ride the leading general when it is moving;
            # sell the quiet range on SPY when nothing is.
            try:
                from app.data.market_universe import SECTOR_BIAS
                gens = list(SECTOR_BIAS.get("generals") or [])
            except Exception:  # noqa: BLE001
                gens = []
            play = None
            if gens:
                g0 = max(gens, key=lambda x: abs(float(x.get("d3") or 0)))
                try:
                    d3 = float(g0.get("d3") or 0)
                except Exception:  # noqa: BLE001
                    d3 = 0.0
                sym0 = str(g0.get("sym") or "").upper()
                if sym0 and abs(d3) >= 2.5:
                    cnd = await fetch_candles_for(sym0, "stock")
                    if cnd:
                        if d3 > 0:
                            play = build_bull_put_spread(sym0, cnd)
                        else:
                            from app.strategies.options_strategies import (
                                build_bear_call_spread as _bcs,
                            )
                            play = _bcs(sym0, cnd)
            if play is None:
                cnd = await fetch_candles_for("SPY", "stock")
                if cnd:
                    play = build_iron_condor("SPY", cnd)
            if not play:
                return out

            # Mike 2026-07-14: "the credit has to be worth the PROFIT,
            # not the 22 percent." The gate is DOLLARS toward the daily
            # goal (>= TREZO_SPREAD_MIN_CREDIT, default $20 -- a real
            # bite of the $50 rung), with only a pennies-vs-wing sanity
            # floor (10%) underneath so the math is never broker-bait.
            _credit0 = float(play.net_premium_usd or 0)
            _wing0 = _credit0 + float(play.max_loss_usd or 0)
            _min_credit = float(_oso.getenv("TREZO_SPREAD_MIN_CREDIT", "20"))
            if (_credit0 < _min_credit or _wing0 <= 0
                    or (_credit0 / _wing0) < 0.10):
                return out
            if float(play.max_loss_usd or 0) > _risk_cap:
                return out

            # Resolve every modeled leg to a REAL listed contract, live-priced.
            from app.brokers.alpaca_data import live_option_pick
            mlegs: list[dict] = []
            seen_occ: dict[str, int] = {}
            net = 0.0
            for leg in play.legs:
                pk = await live_option_pick(
                    play.underlying, str(leg.get("type")),
                    float(leg.get("strike") or 0), str(play.expiration))
                if not pk:
                    return out
                sgn = 1.0 if str(leg.get("action")) == "sell" else -1.0
                net += sgn * float(pk.premium)
                occ = str(pk.occ)
                if occ in seen_occ:
                    mlegs[seen_occ[occ]]["ratio_qty"] += 1
                    continue
                seen_occ[occ] = len(mlegs)
                mlegs.append({
                    "symbol": occ, "ratio_qty": 1,
                    "side": str(leg.get("action")),
                    "position_intent": ("sell_to_open"
                                        if str(leg.get("action")) == "sell"
                                        else "buy_to_open"),
                })
            if len(mlegs) < 2:
                return out
            if net * 100.0 < _min_credit * 0.8:
                return out          # live quotes must still pay real dollars

            # Limit gives 2% toward the fill; negative = net credit (mleg).
            limit = round(-(net * 0.98), 2)
            OptionsScannerAgent._spread_fired.add(f"S:{today_s}")
            order, err = await submit_mleg_order(mlegs, qty=1,
                                                 limit_price=limit)
            from app.agents.activity_log import record as _arec
            if err or not order:
                _arec("option_spread_blocked", play.underlying,
                      reason=f"{play.strategy} not placed: {str(err)[:110]}",
                      extra={"user_id": uid})
                return out
            _short_leg = next((l for l in play.legs
                               if str(l.get("action")) == "sell"),
                              play.legs[0])

            def _ins():
                return client.table("options_positions").insert({
                    "user_id": uid,
                    "underlying": play.underlying,
                    "strategy": play.strategy,
                    "direction": play.direction,
                    "option_type": str(_short_leg.get("type") or "put"),
                    "strike": float(_short_leg.get("strike") or 0),
                    "expiration": str(play.expiration),
                    "contracts": 1,
                    "net_premium_usd": round(net * 100.0, 2),
                    "legs": play.legs,
                    "notes": (f"Placed via Alpaca (mleg): {play.strategy} -- "
                              f"live net credit ${net * 100:.0f}; max loss "
                              f"capped by the wings. "
                              f"{str(play.notes or '')[:130]}"),
                }).execute()
            await asyncio.to_thread(_ins)
            _arec("option_spread_open", play.underlying,
                  strategy=play.strategy,
                  reason=(f"{play.strategy} opened as ONE ticket -- net "
                          f"credit ~${net * 100:.0f}, max loss "
                          f"${float(play.max_loss_usd):.0f} (the wings are "
                          f"the stop)"),
                  extra={"user_id": uid})
            out.append(AgentMessage(
                agent=self.name, kind="execute",
                payload={"user_id": uid, "event": "spread_open",
                         "underlying": play.underlying,
                         "strategy": play.strategy,
                         "net_credit_usd": round(net * 100, 2)}))
        except Exception:  # noqa: BLE001
            pass
        return out

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
            # Mike 2026-07-14: he buys on VOLATILITY and VOLUME -- the
            # day-trade lens. Strongest absolute movers first (puts need
            # the down-leaders as much as calls need the up-leaders).
            _gens_ranked = sorted(
                gens[:10],
                key=lambda x: -abs(float(x.get("d3") or 0)))
            for g in _gens_ranked:
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
                # Volume confirmation: yesterday's tape must run at least
                # 1.2x its 20-day average -- conviction, not drift.
                try:
                    _vols = [float(c.volume or 0) for c in cnd[-21:]]
                    _v_avg = (sum(_vols[:-1]) / max(len(_vols) - 1, 1)
                              if len(_vols) >= 10 else 0.0)
                    _v_ratio = (_vols[-1] / _v_avg) if _v_avg > 0 else 1.0
                except Exception:  # noqa: BLE001
                    _v_ratio = 1.0
                if _v_ratio < float(_oso.getenv(
                        "TREZO_LONG_OPT_VOL_RATIO", "1.2")):
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
                _budget = min(_cap_usd, 0.03 * max(_eq, 1.0))
                if prem <= 0 or debit > _budget:
                    continue
                # Multi-contract when the budget covers cheap contracts
                # (Mike: 3 contracts x $15 profit = the day's 1%) -- the
                # 15% fast-take in the re-score needs the count.
                _ctn = max(1, min(int(_oso.getenv("TREZO_LONG_OPT_CT_MAX", "10")),
                                  int(_budget // max(debit, 1.0))))
                OptionsScannerAgent._long_fired.add(_ck)
                order, err = await submit_option_order(
                    str(pick.occ), _ctn, "buy", time_in_force="day",
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
                        "contracts": _ctn,
                        "net_premium_usd": -round(db * _ctn, 2),
                        "legs": [{"action": "buy", "type": ot,
                                  "strike": float(pk.strike),
                                  "premium": float(pk.premium)}],
                        "notes": (f"Long {ot} on sector general ({dd:+.1f}% "
                                  f"3d). Placed via Alpaca. Exits: +40% "
                                  f"harvest / -50% cut / DTE<=3."),
                    }).execute()
                await asyncio.to_thread(_ins)
                _arec("option_long_open", sym, strategy=f"long_{opt_type}",
                      reason=(f"bought {_ctn} {opt_type.upper()} {pick.strike:g} "
                              f"exp {str(pick.expiration)[:10]} at "
                              f"~{prem:.2f} (${debit * _ctn:.0f} max risk) -- "
                              f"{sym} moving {d3:+.1f}% 3d on {_v_ratio:.1f}x "
                              f"volume"),
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
                                "net_premium_usd, expiration, legs")
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
                        # Multi-leg rows (spreads/condors/flies) are
                        # expiry-managed -- the wings ARE the stop, and
                        # pricing one leg as the whole would lie.
                        if isinstance(lr.get("legs"), list) and len(lr.get("legs") or []) > 1:
                            continue
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
                            _hk = f"h:{lr.get('id')}:{_ct}"
                            _fresh = _hk not in OptionsScannerAgent._harvested
                            if _fresh and _ratio is not None and _prem_now:
                                _fire = None      # (side, limit, reason, qty)
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
                                                  f"of the premium early"),
                                                 _ct)
                                else:
                                    # GOAL-AWARE take-profit (Mike 2026-07-14:
                                    # "I go for the daily goal of making money
                                    # instead of a percentage"). The percent
                                    # needed falls out of the math: dollars
                                    # still needed for the day divided by what
                                    # this position controls. More contracts
                                    # means a smaller percent finishes the job.
                                    _cost = abs(float(_credit) or 0.0)
                                    _tp_min = float(_oso.getenv(
                                        "TREZO_OPT_TP_MIN", "0.10"))
                                    _tp_max = float(_oso.getenv(
                                        "TREZO_OPT_TP_MAX", "0.40"))
                                    _tp = 1.0 + _tp_max
                                    try:
                                        from app.paper.daily_goal import (
                                            goal_state as _dgs2,
                                        )
                                        _g2 = await _dgs2(lr.get("user_id"))
                                        _need = max(
                                            0.0,
                                            float(_g2.get("goal") or 0)
                                            - float(_g2.get("realized") or 0))
                                        if _cost > 0 and _need > 0:
                                            _tp = 1.0 + max(
                                                _tp_min,
                                                min(_tp_max, _need / _cost))
                                    except Exception:  # noqa: BLE001
                                        pass
                                    # GREEK-TURN rule (Mike): a green trade
                                    # whose underlying turns against it gets
                                    # banked -- take the profit, go find the
                                    # next one.
                                    _turn = False
                                    try:
                                        if (_cnd and len(_cnd) >= 2
                                                and float(_cnd[-2].close) > 0):
                                            _d1 = (_spot
                                                   / float(_cnd[-2].close)) - 1.0
                                            _against = (-_d1
                                                        if _otype.startswith("c")
                                                        else _d1)
                                            _turn = bool(_ratio >= 1.05
                                                         and _against >= 0.005)
                                    except Exception:  # noqa: BLE001
                                        _turn = False
                                    if (_ratio >= _tp or _turn
                                            or _ratio <= 0.50 or _dte <= 3):
                                        # STEP-DOWN (Mike): with several
                                        # contracts, bank the ROI first; the
                                        # rest reaches for a higher percent on
                                        # the next step. Cuts, time-outs and
                                        # Greek turns exit in FULL.
                                        _qty = _ct
                                        if (_ct >= 2 and _ratio >= _tp
                                                and not _turn and _ratio > 0.50
                                                and _dte > 3):
                                            _qty = max(1, (_ct + 1) // 2)
                                        _why = (f"+{(_tp - 1) * 100:.0f}% goal-aware target"
                                                if _ratio >= _tp else
                                                ("Greeks turning -- banking the green"
                                                 if _turn else
                                                 ("-50% cut" if _ratio <= 0.50
                                                  else "DTE<=3 time exit")))
                                        _step_t = (f" (step-down: {_qty} of {_ct})"
                                                   if _qty < _ct else "")
                                        _fire = ("sell",
                                                 round(max(0.01, float(_prem_now)) * 0.95, 2),
                                                 (f"selling {_qty}/{_ct} {_otype.upper()} "
                                                  f"{_strike:g} exp {_exp[:10]} -- "
                                                  f"{_why}{_step_t}"),
                                                 _qty)
                                if _fire:
                                    OptionsScannerAgent._harvested.add(_hk)
                                    from app.brokers.alpaca import submit_option_order as _soo
                                    _o2, _e2 = await _soo(
                                        _occ, int(_fire[3]), _fire[0],
                                        time_in_force="day",
                                        limit_price=_fire[1])
                                    _arec("option_harvest", _u,
                                          strategy=_strat_l,
                                          reason=(_fire[2] + f" (limit {_fire[1]:.2f})"
                                                  if not _e2 else
                                                  f"harvest order failed: {str(_e2)[:90]}"),
                                          extra={"user_id": str(lr.get("user_id"))})
                                    # Step-down bookkeeping: shrink the open
                                    # row, book the sold slice at the limit
                                    # (conservative -- a sell fills at limit
                                    # or better).
                                    if ((not _e2) and (not _short)
                                            and int(_fire[3]) < _ct):
                                        try:
                                            _n = int(_fire[3])
                                            _keep = _ct - _n
                                            _entry_ps = float(_entry_prem or 0)
                                            _slice_pnl = round(
                                                (float(_fire[1]) - _entry_ps)
                                                * 100.0 * _n, 2)

                                            def _shrink(rid=lr.get("id"),
                                                        k=_keep,
                                                        ep=_entry_ps):
                                                return (client
                                                        .table("options_positions")
                                                        .update({
                                                            "contracts": k,
                                                            "net_premium_usd":
                                                                -round(ep * 100.0 * k, 2),
                                                        })
                                                        .eq("id", rid)
                                                        .execute())
                                            await asyncio.to_thread(_shrink)

                                            def _slice(n=_n, ep=_entry_ps,
                                                       pnl=_slice_pnl,
                                                       lim=float(_fire[1])):
                                                return (client
                                                        .table("options_positions")
                                                        .insert({
                                                            "user_id": lr.get("user_id"),
                                                            "underlying": _u,
                                                            "strategy": _strat_l,
                                                            "direction": "long",
                                                            "option_type": _otype,
                                                            "strike": _strike,
                                                            "expiration": _exp,
                                                            "contracts": n,
                                                            "net_premium_usd":
                                                                -round(ep * 100.0 * n, 2),
                                                            "status": "closed_partial",
                                                            "realized_pnl_usd": pnl,
                                                            "closed_at": "now()",
                                                            "notes": (f"Step-down: sold {n} of "
                                                                      f"{_ct} at ~{lim:.2f}; ROI "
                                                                      f"banked, remainder reaches "
                                                                      f"for more."),
                                                        }).execute())
                                            await asyncio.to_thread(_slice)
                                        except Exception:  # noqa: BLE001
                                            pass
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
                .execute()
            )
        rows = (await asyncio.to_thread(_sync_open)).data or []
        # 2026-07-15: no early return on empty -- the ADOPT pass below must
        # run even when the books hold nothing (that is exactly the broken
        # state it heals: broker holds an option, books show none).

        by_user: dict[str, list[dict]] = {}
        for r in rows:
            by_user.setdefault(str(r["user_id"]), []).append(r)
        import os as _osr
        _prim = _osr.getenv("TREZO_PRIMARY_USER_ID", "")
        if _prim and _prim not in by_user:
            by_user[_prim] = []

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
                broker_options = None
            if broker_options is None:
                # 2026-07-15 (the F-put disease): a FAILED fetch used to
                # read as "no options at the broker" and closed every row.
                # Absence of evidence is not evidence of absence -- skip.
                continue
            broker_occ = [str(p.get("symbol", "")) for p in broker_options]

            # OCC of every open row (any strategy) -- the adopt pass must
            # never duplicate a position some other lane already tracks.
            row_occs: set = set()
            for _rr in user_rows:
                try:
                    _e0 = str(_rr.get("expiration") or "")
                    row_occs.add(
                        f"{str(_rr.get('underlying') or '').upper()}"
                        f"{_e0[2:4]}{_e0[5:7]}{_e0[8:10]}"
                        f"{'C' if str(_rr.get('option_type') or '').lower().startswith('c') else 'P'}"
                        f"{int(round(float(_rr.get('strike') or 0) * 1000)):08d}")
                except Exception:  # noqa: BLE001
                    continue

            closed_count = 0
            for r in user_rows:
                # Close logic is for the Wheel lanes only; other option
                # strategies are managed by their own exits.
                if str(r.get("strategy") or "") not in ("wheel_csp",
                                                        "wheel_cc"):
                    continue
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

                if (not broker_occ) and realized == 0.0 \
                        and "Reconciled" in exit_note:
                    # Broker returned ZERO options while this row is open
                    # and no closing fill exists -- likely a transient API
                    # gap. HOLD the row instead of closing on no evidence.
                    try:
                        from app.agents.activity_log import record as _hrec
                        _hrec("reconcile_hold", r["underlying"],
                              reason=("kept open: broker options came back "
                                      "empty and no closing fill was found "
                                      "-- not closing on absence of "
                                      "evidence"),
                              extra={"user_id": user_id})
                    except Exception:  # noqa: BLE001
                        pass
                    continue

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

            # ADOPT the other direction (Mike 2026-07-15: the F 12.5 put
            # lived at Alpaca for NINE DAYS with no book row, so the Wheel
            # card showed nothing). Any broker option with no open row
            # becomes a tracked row -- UI, harvest, settle and realized
            # accounting all see it again.
            adopted = 0
            for p in broker_options:
                try:
                    occ = str(p.get("symbol", "") or "").upper()
                    if len(occ) < 16 or occ in row_occs:
                        continue
                    strike = int(occ[-8:]) / 1000.0
                    cp = occ[-9]
                    ymd = occ[-15:-9]
                    und = occ[:-15]
                    if not (und.isalpha() and cp in ("C", "P")
                            and ymd.isdigit()):
                        continue
                    exp = f"20{ymd[0:2]}-{ymd[2:4]}-{ymd[4:6]}"
                    qty = float(p.get("qty") or 0)
                    if qty == 0:
                        continue
                    avg = abs(float(p.get("avg_entry_price") or 0))
                    ct = int(abs(qty))
                    short = qty < 0
                    otype = "put" if cp == "P" else "call"
                    strat = ("wheel_csp" if short and cp == "P"
                             else "wheel_cc" if short
                             else f"long_{otype}")
                    prem = (round(avg * 100 * ct, 2) if short
                            else -round(avg * 100 * ct, 2))

                    def _ins(u=und, st=strat, ot=otype, k=strike, e=exp,
                             c=ct, pr=prem, uid=user_id):
                        return client.table("options_positions").insert({
                            "user_id": uid,
                            "underlying": u,
                            "strategy": st,
                            "direction": ("income" if st.startswith("wheel")
                                          else "long"),
                            "option_type": ot,
                            "strike": k,
                            "expiration": e,
                            "contracts": c,
                            "net_premium_usd": pr,
                            "legs": [{"action": "sell" if pr > 0 else "buy",
                                      "type": ot, "strike": k,
                                      "premium": round(abs(pr) / (100 * c), 4)}],
                            "notes": ("Adopted from the broker by reconcile "
                                      "-- position existed at Alpaca with "
                                      "no book row. Placed via Alpaca."),
                        }).execute()
                    await asyncio.to_thread(_ins)
                    adopted += 1
                    try:
                        from app.agents.activity_log import record as _adr
                        _adr("option_adopted", und,
                             reason=(f"adopted {('short ' if short else '')}"
                                     f"{otype} {strike:g} exp {exp} x{ct} "
                                     f"from the broker -- it had no book "
                                     f"row (the invisible-position fix)"),
                             extra={"user_id": user_id})
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    continue
            if adopted:
                out.append(AgentMessage(
                    agent=self.name, kind="info",
                    payload={"user_id": user_id, "event": "reconcile",
                             "note": (f"Adopted {adopted} broker option "
                                      f"position(s) that had no book row."),
                             "adopted": adopted}))
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
