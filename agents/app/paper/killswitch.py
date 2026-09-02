"""Kill-switches — the daily and weekly safety halts.

Phase 8c, from TREZO_NOVA_BOT_TRADE_RULES.md Section 1. When any switch
trips, the Risk Manager vetoes every new signal:

  - Daily:   today's realized loss reaches 3% of the day-start equity (HARD stop)
  - Weekly:  this week's realized loss reaches 6% of the week-start equity
             — RECOVERY mode since 2026-08-27, never a full stop
  - Streak:  3 losing trades in a row (hard stop)
  - Rejects: 3+ broker order rejects in a rolling 60-minute window

Every switch is PER BOOK (Mike 2026-08-27: "every single book or
account should be treated as its own... I would not want it to
interrupt each other in general"): counted per book, enforced per
book — one account's trouble never interrupts another's trading.

Daily and streak halts clear at the next daily roll; weekly recovery
clears the moment the book earns back above the line, or at the
Monday roll.

The reject window is ROLLING (default 60 minutes, TREZO_REJECT_WINDOW),
not session-scoped — the session-scoped version once silenced a whole
weekend. The slippage halt is LIVE (2026-07-02, comment corrected
2026-08-27 — this line said "deferred" for seven weeks after the
tracker below shipped): stocks_reconcile measures every real fill and
feeds record_fill_slippage(). Only the market-data quality halt from
the rules doc remains deferred.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

_log = logging.getLogger(__name__)

DAILY_DRAWDOWN_PCT = 0.03
WEEKLY_DRAWDOWN_PCT = 0.06
MAX_CONSECUTIVE_LOSSES = 3
MAX_BROKER_REJECTS = 3
MAX_SLIPPAGE_BREACHES = 3   # fills slipping worse than the limit / session

_ROWSUM_CACHE: dict[str, tuple] = {}   # user -> (ts, wk, dy, streak) 30s TTL
_LAST_MODE: dict[str, str] = {}        # user -> last seen mode, for transition records


class _RowsumCached(Exception):
    """Internal flow control: row-truth served from cache."""


# --- Broker-reject counter on a ROLLING WINDOW (in-process) -----------
# Mike 2026-07-27: this halt was "session"-scoped with no expiry, so
# three rejects on Friday afternoon silenced the WHOLE weekend -- 293
# blocked signals in the 24/7 market that is supposed to earn dailies.
# A reject storm should pause trading briefly, not forever. Rejects now
# AGE OUT after TREZO_BROKER_REJECT_WINDOW_MIN (default 60), so the halt
# heals itself the same way the bad-symbol rest list expires. Same
# philosophy as everywhere else: conditions, never permanent bans.
import os as _os_ks
import time as _time_ks

# PER BOOK (Mike 2026-08-27: "every single book or account should be
# treated as its own when it comes to the broker... I would not want it
# to interrupt each other in general"). Rejects happen on ONE book's
# brokerage account; a reject storm there must never bench the others.
# Key "" holds legacy unattributed rejects — those count toward every
# book (they cannot be pinned, so conservative is correct).
_broker_reject_ts: dict[str, list[float]] = {}


def _reject_window_s() -> float:
    try:
        return max(60.0, float(
            _os_ks.getenv("TREZO_BROKER_REJECT_WINDOW_MIN", "60")) * 60.0)
    except (TypeError, ValueError):
        return 3600.0


def _prune_rejects() -> None:
    cutoff = _time_ks.time() - _reject_window_s()
    for _b in list(_broker_reject_ts):
        _lst = _broker_reject_ts[_b]
        while _lst and _lst[0] < cutoff:
            _lst.pop(0)
        if not _lst:
            _broker_reject_ts.pop(_b, None)


def record_broker_reject(user_id: str | None = None) -> int:
    _prune_rejects()
    _b = str(user_id or "")
    _broker_reject_ts.setdefault(_b, []).append(_time_ks.time())
    return broker_reject_count(user_id)


def broker_reject_count(user_id: str | None = None) -> int:
    """THIS book's rejects plus any unattributed ones. Called with no
    user_id it returns the platform-wide total (old behavior)."""
    _prune_rejects()
    if user_id is None:
        return sum(len(v) for v in _broker_reject_ts.values())
    return (len(_broker_reject_ts.get(str(user_id), []))
            + len(_broker_reject_ts.get("", [])))


def reset_broker_rejects(user_id: str | None = None) -> None:
    """Clear the rolling reject window.

    KS-4: with a user_id this clears ONLY that book's bucket — a ghost
    reconciled on the 75k must not wipe the primary's reject history
    (every book is its own book). The '' unattributed bucket is left
    alone because it counts toward every book. With None it clears
    everything — the admin /clear-session-halt action only."""
    if user_id is None:
        _broker_reject_ts.clear()
        return
    _broker_reject_ts.pop(str(user_id), None)


# --- Session-scoped slippage tracker (2026-07-02) ---------------------
# Rules doc §1's slippage halt, LIVE since 2026-07-02: the reconciler
# (stocks_reconcile.py) measures each fill (decision price vs the
# broker's avg fill) and feeds breaches here. "Session-scoped" means
# process lifetime — cleared only by /admin/clear-session-halt or a
# restart, never by the daily roll.
# Per book, same isolation rule as the reject counter above.
_slippage_breaches: dict[str, list[float]] = {}


def record_fill_slippage(bps: float, user_id: str | None = None) -> int:
    """Track one measured fill's ADVERSE slippage (bps, positive = worse
    than the decision price). Counts a breach when it exceeds
    TREZO_SLIPPAGE_HALT_BPS (default 75). Returns the session breach count."""
    import os as _o
    try:
        limit = float(_o.getenv("TREZO_SLIPPAGE_HALT_BPS", "75"))
    except (TypeError, ValueError):
        limit = 75.0
    if bps > limit:
        _slippage_breaches.setdefault(str(user_id or ""), []).append(float(bps))
    return slippage_breach_count(user_id)


def slippage_breach_count(user_id: str | None = None) -> int:
    if user_id is None:
        return sum(len(v) for v in _slippage_breaches.values())
    return (len(_slippage_breaches.get(str(user_id), []))
            + len(_slippage_breaches.get("", [])))


def reset_slippage_breaches() -> None:
    _slippage_breaches.clear()


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def account_equity(account: dict, broker_equity: float | None = None) -> float:
    """Equity the loss limits are measured against.

    THE BUG THIS FIXES (2026-08-07). This used to be cash + vault ONLY --
    it excluded the market value of open positions. So on a fully deployed
    book, cash collapsed and the baseline collapsed with it: day-start
    equity was recording about $151 against a real account of $4,901, which
    turned the 3% daily loss limit into $4.52 instead of $147. Trading
    halted 33x earlier than intended, and the harder the agents worked the
    smaller their own limit became.

    The identical class of drift was found on 2026-07-02 in the allocation
    pockets (ledger $2.8k vs broker $4.8k, shrinking every pocket by 40%)
    and fixed there with effective_equity. This applies the same fix to the
    kill-switch, which was missed at the time.
    """
    if broker_equity and broker_equity > 0:
        return float(broker_equity)
    return _f(account.get("current_cash_usd")) + _f(account.get("vault_balance_usd"))


@dataclass
class KillSwitch:
    halted: bool
    scope: str | None       # 'day' | 'week' | 'session' | None
    reason: str | None
    # 2026-08-27 (Mike): "we should not have a weekly kill limit that
    # truly stops all trading — it should suspend the lane from making
    # any crazy investment and tighten up the spread to make things work
    # away from the loss." mode='halt' = the old behavior (daily, streak,
    # session halts — hard stops). mode='recovery' = the weekly limit's
    # new behavior: the book keeps trading, but speculative lanes are
    # suspended and everything else runs at half size, +RECOVERY_TCS_BUMP
    # conviction, and tighter stops. Recovery is recomputed from row
    # sums on every check, so a book that earns its way back above the
    # line exits recovery immediately — no waiting for Monday.
    mode: str | None = None  # 'halt' | 'recovery' | None


# --- Weekly recovery policy (Mike 2026-08-27, chosen explicitly) -------
# Suspended while a book is in weekly recovery — the "no crazy
# investments" list: same-day options, small-cap momentum, opening-range
# breakouts, directional option buys, crypto scalping.
RECOVERY_SUSPENDED_PREFIXES: tuple = (
    "option_day", "stms", "orb", "crypto_scalp",
    "long_call", "long_put", "bull_call_spread", "butterfly",
)
RECOVERY_TCS_BUMP = 10        # extra conviction required in recovery
RECOVERY_SIZE_FACTOR = 0.5    # half size
RECOVERY_STOP_FACTOR = 0.75   # stops 25% tighter — cut losers faster


def recovery_policy(strategy: str) -> str:
    """'suspend' | 'tighten' for a strategy on a book in weekly
    recovery. Everything not on the suspended list keeps trading with
    the tightened rules — the point is to work AWAY from the loss, not
    to freeze."""
    s = str(strategy or "").lower()
    if s.startswith(RECOVERY_SUSPENDED_PREFIXES):
        return "suspend"
    return "tighten"


def period_updates(account: dict,
                   broker_equity: float | None = None) -> dict:
    """If the day or week has rolled over, return the column updates that
    re-baseline the account (and clear a scoped halt). Empty dict if there
    is nothing to roll."""
    upd: dict = {}
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    equity = account_equity(account, broker_equity)

    if str(account.get("last_reset_date") or "") != today.isoformat():
        upd["last_reset_date"] = today.isoformat()
        upd["day_start_equity_usd"] = round(equity, 2)
        upd["today_realized_pnl_usd"] = 0
        upd["consecutive_losses"] = 0
        upd["daily_target_hit_today"] = False
        if account.get("halt_scope") == "day":
            upd["trading_halted"] = False
            upd["halt_reason"] = None
            upd["halt_scope"] = None
    elif not account.get("day_start_equity_usd"):
        upd["day_start_equity_usd"] = round(equity, 2)

    if str(account.get("week_start_date") or "") != monday.isoformat():
        upd["week_start_date"] = monday.isoformat()
        upd["week_start_equity_usd"] = round(equity, 2)
        upd["week_realized_pnl_usd"] = 0
        if account.get("halt_scope") == "week":
            upd["trading_halted"] = False
            upd["halt_reason"] = None
            upd["halt_scope"] = None
    elif not account.get("week_start_equity_usd"):
        upd["week_start_equity_usd"] = round(equity, 2)

    return upd


def evaluate(account: dict, consec_limit: int = MAX_CONSECUTIVE_LOSSES) -> KillSwitch:
    """Evaluate every kill-switch for one (already period-rolled) account."""
    _legacy_week_recovery: KillSwitch | None = None
    if account.get("trading_halted"):
        # A PERSISTED weekly halt is a leftover from the pre-2026-08-27
        # behavior (weekly used to hard-halt and write trading_halted).
        # Soften it to recovery so the change takes effect without
        # waiting for Monday's roll; check_states clears the stale flag.
        # KS-2 residual (rv:killswitch-contracts :271): do NOT return
        # here -- the hard stops below still run for such a row, and the
        # softened verdict is only handed back if none of them trips.
        if str(account.get("halt_scope") or "") == "week":
            _legacy_week_recovery = KillSwitch(
                False, "week",
                account.get("halt_reason") or "Weekly loss limit — recovery mode",
                mode="recovery")
        else:
            return KillSwitch(True, account.get("halt_scope"),
                              account.get("halt_reason") or "Trading halted",
                              mode="halt")

    # KS-2: the HARD stops (daily %, streak, rejects, slippage) are
    # evaluated BEFORE the weekly-recovery verdict. Recovery used to
    # return first, so a book already in weekly recovery could lose
    # another 3% today, or take three rejects, and never hard-halt —
    # the anti-spiral brake was disarmed on exactly the book that
    # needed it most. A fresh trip now halts a recovering book too.
    dse = _f(account.get("day_start_equity_usd"))
    dpnl = _f(account.get("today_realized_pnl_usd"))
    # STALENESS GUARD: a stored baseline far below true equity is left over
    # from a fully-deployed day and would halt on a trivial loss. Never let
    # it shrink the limit; the limit may only be as tight as real equity says.
    _true = _f(account.get("_broker_equity"))
    if _true > 0 and dse > 0 and dse < 0.5 * _true:
        dse = _true
    if dse > 0 and dpnl <= -DAILY_DRAWDOWN_PCT * dse:
        return KillSwitch(True, "day",
                          f"Daily loss limit: down ${abs(dpnl):,.0f} "
                          f"({dpnl / dse * 100:.1f}%) today", mode="halt")

    cl = int(account.get("consecutive_losses") or 0)
    if cl >= consec_limit:
        return KillSwitch(True, "day",
                          f"{cl} losing trades in a row (limit {consec_limit})",
                          mode="halt")

    rj = broker_reject_count(str(account.get("user_id")) if account.get("user_id") else None)
    if rj >= MAX_BROKER_REJECTS:
        _mins = int(_reject_window_s() / 60)
        return KillSwitch(True, "session",
                          f"{rj} broker order rejects in the last {_mins} "
                          f"min - trading pauses until they age out",
                          mode="halt")

    sb = slippage_breach_count(str(account.get("user_id")) if account.get("user_id") else None)
    if sb >= MAX_SLIPPAGE_BREACHES:
        return KillSwitch(True, "session",
                          f"{sb} fills slipped past the limit this session "
                          f"- execution quality halt",
                          mode="halt")

    wse = _f(account.get("week_start_equity_usd"))
    wpnl = _f(account.get("week_realized_pnl_usd"))
    _tw = _f(account.get("_broker_equity"))
    if _tw > 0 and wse > 0 and wse < 0.5 * _tw:
        wse = _tw
    if wse > 0 and wpnl <= -WEEKLY_DRAWDOWN_PCT * wse:
        # RECOVERY, not a halt (Mike 2026-08-27). The book keeps trading:
        # speculative lanes suspended, the rest at half size / +10 TCS /
        # tighter stops. Recomputed from row sums every check, so
        # clawing back above the line ends recovery on its own.
        return KillSwitch(False, "week",
                          f"Weekly loss limit: down ${abs(wpnl):,.0f} "
                          f"({wpnl / wse * 100:.1f}%) this week — "
                          f"recovery mode (speculative lanes suspended, "
                          f"half size, +{RECOVERY_TCS_BUMP} TCS)",
                          mode="recovery")

    if _legacy_week_recovery is not None:
        return _legacy_week_recovery
    return KillSwitch(False, None, None)


async def check_states(client) -> dict[str, KillSwitch] | None:
    """Roll periods and evaluate every kill-switch PER BOOK.

    2026-08-27 (Mike): "the agents are not treating each book as their
    own book and it is causing major issues." The old single-verdict
    wrapper summed each book's own rows — the MEASUREMENT was always per
    book — but returned one answer ("single-user assumption"), so one
    tripped book vetoed every book's signals. On 2026-08-27 the primary's
    -8.0% week froze two healthy books (25k at -1.6%, 75k at -2.7%) for
    1,162 vetoes. This returns {user_id: KillSwitch} so the Risk Manager
    and the execution fan-out can treat each book as its own book.

    Returns None — NOT {} — when there is no client or the paper_accounts
    read fails (KS-11). An empty dict is a real answer ("no books"); None
    is "could not evaluate". Callers must not fall through to trading on
    None: the execution fan-out skips every book and says so in the log;
    the risk gate logs and proceeds (the fan-out is the enforcement
    point). Before this, a failed read returned {} and the fan-out read
    "no halts anywhere" — a dead database looked like a healthy one.
    """
    if not client:
        return None

    def _fetch():
        return client.table("paper_accounts").select("*").execute()

    try:
        res = await asyncio.to_thread(_fetch)
    except Exception:  # noqa: BLE001
        return None

    states: dict[str, KillSwitch] = {}
    # 2026-08-18 (Mike: "the agents are not responding to each book's own
    # setting"). He was right. consecutive_loss_limit was read ONCE, here,
    # OUTSIDE the loop, with no book bound -- so get_bot_settings() fell
    # back to whichever bot_settings row was updated last, and one book's
    # loss limit governed all three. A conservative book could be halted
    # on an aggressive book's threshold, or worse, the reverse.
    #
    # The limit is a per-book setting. Read it per book, inside the loop.
    from app.runtime.settings import get_bot_settings
    for acct in (res.data or []):
        try:
            consec_limit = int(get_bot_settings(
                str(acct.get("user_id") or "")).consecutive_loss_limit)
        except Exception:  # noqa: BLE001
            consec_limit = MAX_CONSECUTIVE_LOSSES
        _beq = 0.0
        try:
            from app.paper.allocation import effective_equity
            _beq = float(await effective_equity(str(acct.get("user_id") or "")) or 0)
        except Exception:  # noqa: BLE001
            _beq = 0.0
        if _beq > 0:
            acct = {**acct, "_broker_equity": _beq}
        upd = period_updates(acct, broker_equity=_beq or None)
        if upd:
            acct = {**acct, **upd}

            def _roll(uid=acct["user_id"], u=upd):
                return client.table("paper_accounts").update(u).eq("user_id", uid).execute()

            try:
                await asyncio.to_thread(_roll)
            except Exception:  # noqa: BLE001
                pass

        # Row-truth override (2026-07-02): the counters drift (WMT's -$61
        # bracket stop never rolled them; manual closes booked $0 until the
        # 7/1 fix). The kill-switch now SUMS this week's closed rows itself,
        # so it is correct regardless of which close path wrote the row.
        # 2026-07-07: cached 30s per user -- check_states runs per SIGNAL,
        # and during a veto storm the uncached sums hammered the nano DB.
        try:
            import time as _t
            _ck = str(acct.get("user_id"))
            _hit = _ROWSUM_CACHE.get(_ck)
            if _hit and (_t.time() - _hit[0]) < 30.0:
                acct = {**acct,
                        "week_realized_pnl_usd": _hit[1],
                        "today_realized_pnl_usd": _hit[2],
                        "consecutive_losses": max(
                            int(acct.get("consecutive_losses") or 0), _hit[3])}
                raise _RowsumCached()
            _today_s = date.today().isoformat()
            _monday_s = (date.today()
                         - timedelta(days=date.today().weekday())).isoformat()

            def _rows(uid=acct["user_id"], m=_monday_s):
                return (client.table("paper_positions")
                        .select("realized_pnl_usd, exit_at")
                        .eq("user_id", uid)
                        .gte("exit_at", m)
                        .like("status", "closed%")
                        .order("exit_at", desc=True)
                        .limit(500).execute())
            _rr = (await asyncio.to_thread(_rows)).data or []
            _wk = sum(float(x.get("realized_pnl_usd") or 0) for x in _rr)
            _dy = sum(float(x.get("realized_pnl_usd") or 0) for x in _rr
                      if str(x.get("exit_at") or "")[:10] == _today_s)
            _streak = 0
            for x in _rr:
                _p = float(x.get("realized_pnl_usd") or 0)
                if _p < 0:
                    _streak += 1
                elif _p > 0:
                    break
            acct = {**acct,
                    "week_realized_pnl_usd": round(_wk, 2),
                    "today_realized_pnl_usd": round(_dy, 2),
                    "consecutive_losses": max(
                        int(acct.get("consecutive_losses") or 0), _streak)}
            _ROWSUM_CACHE[_ck] = (_t.time(), round(_wk, 2), round(_dy, 2),
                                  _streak)
        except _RowsumCached:
            pass
        except Exception:  # noqa: BLE001
            pass

        ks = evaluate(acct, consec_limit)
        states[str(acct.get("user_id") or "")] = ks

        # RECOVERY AS A LEARNED SKILL (Mike 2026-08-27: "the way the
        # agents have recovered from a loss when they were under the 5k
        # portfolio start was a recovery method that is a skill... to
        # understand that they can get past and make it forward"). The
        # transitions INTO and OUT of recovery are recorded — the exit
        # note is the lesson: this book worked its way back before, so
        # a drawdown is a condition to trade through, not an ending.
        try:
            _uid_t = str(acct.get("user_id") or "")
            _cur = ks.mode or ("halt" if ks.halted else "clear")
            _prev = _LAST_MODE.get(_uid_t)
            if _prev != _cur:
                _LAST_MODE[_uid_t] = _cur
                _wk_now = _f(acct.get("week_realized_pnl_usd"))
                if _cur == "recovery":
                    from app.agents.activity_log import record as _rrec
                    _rrec("recovery_entered", _uid_t[:8] or "BOOK",
                          reason=(ks.reason or "weekly limit")[:200])
                elif _prev == "recovery" and _cur == "clear":
                    from app.agents.activity_log import record as _rrec
                    _rrec("recovery_completed", _uid_t[:8] or "BOOK",
                          reason=(f"worked back above the weekly line "
                                  f"(week now ${_wk_now:+,.0f}) — "
                                  f"suspended lanes restored"))
                    try:
                        from app.memory.mem0_client import get_memory
                        get_memory().queue_note(
                            "killswitch",
                            (f"recovery[{_uid_t[:8]}]: book entered "
                             f"weekly recovery and traded its way back "
                             f"(week ${_wk_now:+,.0f}). The method works "
                             f"— drawdowns are conditions to trade "
                             f"through, tightened, not endings."))
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            pass

        # Heal a stale PERSISTED weekly halt (written by the pre-08-27
        # behavior): the weekly limit is recovery now, so the hard flag
        # comes off the row — evaluate() already softened the verdict.
        if (acct.get("trading_halted")
                and str(acct.get("halt_scope") or "") == "week"):
            def _unhalt(uid=acct["user_id"]):
                return client.table("paper_accounts").update({
                    "trading_halted": False,
                    "halt_reason": None,
                    "halt_scope": None,
                }).eq("user_id", uid).execute()
            try:
                await asyncio.to_thread(_unhalt)
            except Exception:  # noqa: BLE001
                pass

        # Persist only HARD day-scope halts (daily drawdown / streak).
        # Weekly recovery is never persisted — it is recomputed from row
        # sums each check so a claw-back clears it immediately; session
        # halts live in-process by nature.
        if (ks.halted and ks.mode == "halt" and ks.scope == "day"
                and not acct.get("trading_halted")):
            def _persist(uid=acct["user_id"], k=ks):
                return client.table("paper_accounts").update({
                    "trading_halted": True,
                    "halt_reason": k.reason,
                    "halt_scope": k.scope,
                    "halted_at": datetime.now(timezone.utc).isoformat(),
                }).eq("user_id", uid).execute()

            try:
                await asyncio.to_thread(_persist)
            except Exception:  # noqa: BLE001
                pass
    return states


# KS-10/G11: the check_all() single-verdict wrapper that used to live here
# is gone. It had zero call sites and its shape (worst state across books)
# was the exact cross-book bleed check_states was written to end.


# --- KS-12: user-set daily DOLLAR limit, per book -----------------------

async def daily_dollar_over(client) -> set[str] | None:
    """user_ids whose today's realized loss is at or beyond the dollar
    limit they set themselves (profiles.daily_loss_limit_usd).

    KS-12: this is the per-book DOLLAR brake next to the percent one in
    evaluate(). Moved here from the risk manager so the execution
    fan-out can enforce it too (the risk gate alone was not enough —
    a signal approved before the trip still filled after it). A limit
    of 0 / unset means the user set no dollar brake. Returns None on any
    read failure — a failed read must never read as "nobody is over".
    """
    if not client:
        return None

    def _sync():
        accounts = (client.table("paper_accounts")
                    .select("user_id, today_realized_pnl_usd").execute())
        profiles = (client.table("profiles")
                    .select("user_id, daily_loss_limit_usd").execute())
        return accounts.data or [], profiles.data or []

    try:
        accounts, profiles = await asyncio.to_thread(_sync)
    except Exception:  # noqa: BLE001
        return None
    limit_by_user: dict[str, float] = {}
    for p in profiles:
        try:
            v = float(p.get("daily_loss_limit_usd") or 0)
            if v > 0:
                limit_by_user[p["user_id"]] = v
        except (TypeError, ValueError):
            pass

    over: set[str] = set()
    for a in accounts:
        uid = a["user_id"]
        limit = limit_by_user.get(uid, 0)
        if limit <= 0:
            continue
        try:
            today = float(a.get("today_realized_pnl_usd") or 0)
        except (TypeError, ValueError):
            continue
        if today <= -limit:
            over.add(uid)
    return over


# --- QW6: per-coin crypto daily loss limit -----------------------------

NUM_CRYPTO_COINS = 3                 # XRP / ETH / SOL
PER_COIN_DAILY_LOSS_PCT = 0.10       # of a coin's slice of the crypto budget


def _utc_day_start_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00+00:00")


def _coin_rows_query(client, sym: str, user_id: str | None):
    """Today's closed crypto rows for one coin — filtered to ONE book
    when a user_id is given (BI-04/PH-6). Before this the loss side of
    the per-coin halt summed every book's XRP closes while the budget
    side read one book: the primary's bad morning benched the 75k's
    coin, and a book with no XRP losses at all could be measured over
    its own limit. Loss and budget now come from the same book."""
    q = (client.table("paper_positions")
         .select("realized_pnl_usd, user_id")
         .eq("ticker", sym)
         .eq("asset_type", "crypto")
         .neq("status", "open")
         .gte("exit_at", _utc_day_start_iso()))
    if user_id:
        q = q.eq("user_id", str(user_id))
    return q.execute()


def _crypto_budget_for(acct: dict) -> float:
    """The book's crypto allocation budget from ITS OWN equity, posture
    and overrides. Raises on any failure — callers decide what a missing
    budget means (module-level so tests can seam it)."""
    equity = account_equity(acct)
    from app.paper.allocation import build_allocation
    from app.runtime.settings import get_bot_settings
    cfg = get_bot_settings(str(acct.get("user_id") or ""))
    alloc = build_allocation(equity, posture_setting=cfg.account_posture,
                             overrides=cfg.allocation_overrides)
    return float(alloc.budgets.get("crypto", 0.0))


def _coin_verdict(sym: str, realized: float, crypto_budget: float) -> str | None:
    """The ONE place the per-coin threshold is applied — shared by the
    single-book and the by-book evaluators so they can never drift."""
    if realized >= 0 or crypto_budget <= 0:
        return None
    limit = PER_COIN_DAILY_LOSS_PCT * (crypto_budget / NUM_CRYPTO_COINS)
    if limit > 0 and -realized >= limit:
        return (f"{sym} per-coin daily loss limit: down "
                f"${-realized:,.0f} today (limit ${limit:,.0f})")
    return None


async def coin_loss_halt(client, ticker: str,
                         user_id: str | None = None) -> str | None:
    """Per-coin daily loss limit (TREZO_NOVA_BOT_TRADE_RULES, Section 1).

    A crypto coin is benched for the rest of the UTC day once its realized
    losses on that coin today reach 10% of the coin's slice of the crypto
    allocation budget. This sits alongside the account-wide kill-switches
    so one bad coin can be stopped without halting the others. Returns a
    veto reason string, or None when the coin is clear.

    With a user_id BOTH sides are that book's — its own losses on the
    coin vs its own budget (BI-04/PH-6). Without one (a scanner signal
    not yet fanned out) this keeps the old platform-wide loss sum
    against the first account row; use coin_loss_halt_by_book() there
    to get a verdict per book instead.
    """
    if not client:
        return None
    sym = (ticker or "").upper()

    # Today's realized P&L on this coin (UTC day), on THIS book.
    try:
        res = await asyncio.to_thread(_coin_rows_query, client, sym, user_id)
        realized = sum(_f(r.get("realized_pnl_usd")) for r in (res.data or []))
    except Exception:  # noqa: BLE001
        return None
    if realized >= 0:
        return None

    # The coin's slice of the crypto allocation budget.
    try:
        # 2026-08-18: this took the FIRST account row it found, so a
        # per-coin halt on one book was computed from another book's
        # equity and allocation budget. With a user_id it reads the
        # book actually being judged.
        def _acct(uid=user_id):
            q = client.table("paper_accounts").select("*")
            if uid:
                q = q.eq("user_id", uid)
            return q.limit(1).execute()
        ares = await asyncio.to_thread(_acct)
        acct = (ares.data or [None])[0]
        if not acct:
            return None
        crypto_budget = _crypto_budget_for(acct)
    except Exception:  # noqa: BLE001
        return None
    return _coin_verdict(sym, realized, crypto_budget)


async def coin_loss_halt_by_book(client, ticker: str) -> dict[str, tuple[bool, str]]:
    """The per-coin halt evaluated for EVERY paper_accounts book at once:
    {user_id: (halted, reason)} — each book's own losses on the coin
    today vs its own crypto budget, same threshold as coin_loss_halt().

    BI-04/PH-6: for a scanner signal with no user_id the risk manager
    used to sum every book's losses and veto the coin for all of them.
    Now it benches only the books that are actually over (the approve
    payload's "benched_books") and the fan-out skips those. A book whose
    budget cannot be computed reads as clear — this is a per-coin
    bench, the account kill-switches are the hard guard. On a failed
    ledger read this returns {} (no verdicts, nothing benched) and logs
    why, so the caller can see the difference between "all clear" and
    "could not look".

    rv:killswitch-contracts :696 (audit 2026-09-01), why {} and not None:
    the one consumer (risk_manager on_message) iterates the result
    unguarded, and a dead ledger is already surfaced on the dashboard
    one gate earlier in the same handler -- check_states() reads the
    same paper_accounts table and its None raises the throttled
    kill_switch_unknown activity row. Switching this to None without
    that consumer changing would turn a benign "nothing benched" into
    an exception inside the risk gate.
    """
    if not client:
        return {}
    sym = (ticker or "").upper()
    try:
        ares = await asyncio.to_thread(
            lambda: client.table("paper_accounts").select("*").execute())
        accounts = list(ares.data or [])
        res = await asyncio.to_thread(_coin_rows_query, client, sym, None)
        rows = list(res.data or [])
    except Exception as e:  # noqa: BLE001
        _log.warning("coin_loss_halt_by_book(%s): ledger read failed (%s) "
                     "- no per-book verdict, nothing benched", sym,
                     type(e).__name__)
        return {}

    realized_by_book: dict[str, float] = {}
    for r in rows:
        _u = str(r.get("user_id") or "")
        realized_by_book[_u] = realized_by_book.get(_u, 0.0) + _f(r.get("realized_pnl_usd"))

    out: dict[str, tuple[bool, str]] = {}
    for acct in accounts:
        uid = str(acct.get("user_id") or "")
        if not uid:
            continue
        realized = realized_by_book.get(uid, 0.0)
        reason: str | None = None
        if realized < 0:
            try:
                reason = _coin_verdict(sym, realized, _crypto_budget_for(acct))
            except Exception:  # noqa: BLE001
                reason = None
        out[uid] = (bool(reason), reason or "")
    return out
