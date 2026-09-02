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

from dataclasses import dataclass
from typing import Optional

from app.data.candles import fetch_candles_for
from app.paper.engine import open_position
from app.runtime.trading_mode import get_trading_mode

from .base import Agent, AgentMessage

# Single source of truth for "is this ticker a crypto?" 2026-06-13:
# was a hardcoded 4-symbol set, which misclassified the ISO 20022
# coins (XLM/HBAR/ALGO/IOTA/QNT/XDC/XYO) as STOCKS -> they were routed
# to Alpaca's stock path instead of the modeled crypto engine, so the
# agents could never take a position in them. Derive from COIN_MAP
# (every symbol we have crypto price data for: majors + ISO cluster).
def _all_crypto_symbols() -> set:
    try:
        from app.data.candles import COIN_MAP
        return {s.upper() for s in COIN_MAP.keys()}
    except Exception:  # noqa: BLE001
        return {"XRP", "ETH", "SOL", "BTC"}

CRYPTO_SYMBOLS = _all_crypto_symbols()

# Priority-rotation throttle (2026-07-02): at most N weakest-hold
# rotations per day, process-local; the activity log carries each one.
_ROTATIONS_TODAY: dict = {"day": "", "n": 0}


def _lane_cap_f(source_payload) -> float | None:
    """The lane's own max_notional, if the signal carries one (>0)."""
    try:
        v = (source_payload or {}).get("max_notional")
        if v is not None and float(v) > 0:
            return float(v)
    except (TypeError, ValueError):
        pass
    return None


def _lane_of(ticker: str, payload) -> str:
    """Lane label carried on execution outcome messages ('stock' |
    'crypto' | 'option' | 'forex' | ...): the rule the fan-out has always
    used for admission -- a COIN_MAP ticker is crypto whatever the payload
    says, otherwise the signal's declared asset_type, else stock.
    ops_watchdog keys its per-lane nets on payload["lane"]."""
    if str(ticker or "").upper() in CRYPTO_SYMBOLS:
        return "crypto"
    return str((payload or {}).get("asset_type") or "stock").lower()


@dataclass
class _BookGate:
    """One book's pre-execution verdict (TradeExecutionAgent._gate_book).

    `skip` set means: emit that message INSTEAD of executing on this
    book. Otherwise `payload` is what _execute_for_user must receive for
    this book -- a copy whenever the book changed it, because the source
    dict is shared across the fan-out. `tcs_bump` / `lev_note` are what
    book_gate.admits judged with; `rr_note` is the re-harmonization line
    for the activity log, set even when the book is later declined (as
    the inline code always did)."""

    payload: dict
    skip: Optional[AgentMessage] = None
    tcs_bump: int = 0
    lev_note: str = ""
    rr_note: Optional[str] = None


class TradeExecutionAgent(Agent):
    name = "trade_execution"
    tick_interval_seconds = 0  # event-driven

    async def tick(self) -> list[AgentMessage]:
        return []

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        if message.kind != "approve":
            return []

        ticker = message.payload.get("ticker", "?")
        direction = str(message.payload.get("direction") or "").strip().lower()
        user_id = message.payload.get("user_id")
        # TE-07: 'bullish' / 'long' -> long, 'bearish' / 'short' -> short,
        # anything else is REFUSED. The old one-liner sent every value
        # that was not exactly 'bullish' -- 'long' itself, 'income', a
        # missing field, a typo -- SHORT, with nothing in the log.
        if direction in ("bullish", "long"):
            side = "long"
        elif direction in ("bearish", "short"):
            side = "short"
        else:
            _lane = _lane_of(ticker, message.payload)
            _why = (f"unknown direction {direction!r} -- refusing rather "
                    f"than defaulting to short")
            try:
                from app.agents.activity_log import record as _arec
                _arec("execute_error", ticker,
                      strategy=message.payload.get("strategy"),
                      reason=_why[:180],
                      extra={"user_id": str(user_id or ""), "lane": _lane})
            except Exception:  # noqa: BLE001
                pass
            return [AgentMessage(
                agent=self.name, kind="error", confidence=1.0,
                payload={"user_id": user_id, "ticker": ticker,
                         "event": "execute_error", "lane": _lane,
                         "error": _why})]

        # Platform-default routing (Mike 2026-08-20): "by default all
        # accounts and books have access to the platform - we adjust in
        # the settings." A user_id on an approve payload is PROVENANCE -
        # which book's scan raised the signal - not a fence around who
        # may act on it. The tape is global; the appetite is per book,
        # and the per-book answer already lives at the fan-out
        # (book_gate.admits: lane toggles, TCS floor, auto-trade, each
        # judged with THAT book's settings). Before this, a
        # pattern_detection signal carried its origin book's id and
        # executed on that book alone: the 25k and 75k books took their
        # last scanner-driven stock entry on 08-14 and nobody chose
        # that - they simply had no watchlist for the per-user scanner
        # to walk. Only a payload that says book_scoped=True stays
        # pinned to its book: flows that are genuinely one book's
        # business (a wheel leg on its own account, a manual UI order).
        if user_id and not message.payload.get("book_scoped"):
            fanout_payload = dict(message.payload)
            fanout_payload["origin_book"] = user_id
            fanout_payload.pop("user_id", None)
            return await self._execute_for_all_users(
                ticker, side, fanout_payload)

        # Auto-trade toggle (Mike 2026-06-01). When the user has flipped
        # auto_trade_enabled OFF, every signal still scored + approved
        # + recorded - but no open_position fires. The post-mortem loop
        # gets a "would_have_traded" event so learning continues even
        # in observe-only mode.
        try:
            from app.runtime.settings import get_bot_settings
            cfg = get_bot_settings(user_id)
            # 2026-08-18: only when the signal names a book. Without a
            # user_id this read the GLOBAL row and returned here, so the
            # primary's Auto-trade toggle silenced all three books --
            # and, flipped on, spoke for books that had it off. The
            # fan-out below asks each book for itself.
            if user_id and not cfg.auto_trade_enabled:
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

        # SINGLE-BOOK path (user_id + book_scoped). Review 2026-09-01
        # (rv:killswitch-contracts, rv:bound-hunter :168): this branch
        # went straight to _execute_for_user with NONE of the fan-out's
        # per-book gates -- no kill-switch, no daily $ brake, no bench,
        # no R:R re-harmonization, no recovery / margin bump -- so the
        # first producer to pin a signal (the dividend ladder) would
        # have executed on a hard-halted book. Both paths now run the
        # SAME reads (_read_book_brakes) and the SAME gate (_gate_book),
        # so they cannot drift. Capacity (max_open_positions per pocket)
        # stays a fan-out concern: a pinned signal is one book's own
        # decision about its own ladder.
        from app.runtime.persistence import _client as _pclient
        _lane = _lane_of(ticker, message.payload)
        _book_ks, _dollar_over, _closed = await self._read_book_brakes(
            _pclient(), ticker, side, message.payload, 1, user_id=user_id)
        if _closed is not None:
            return [_closed]
        _benched = {str(b) for b in
                    (message.payload.get("benched_books") or []) if b}

        # Bind THIS book's broker credentials before placing its order.
        # trade_execution already fans out across paper_accounts rows, but
        # nothing bound the account -- so every book's orders would have
        # gone to the primary Alpaca account (2026-08-09).
        from app.brokers.accounts import bind_for_user as _bind_acct
        from app.brokers.route_guard import check_route, record_mismatch
        from app.runtime.settings import get_bot_settings as _bot_settings
        with _bind_acct(user_id):
            _ok, _note = check_route(user_id)
            if not _ok:
                # Refuse rather than mis-route: 7 orders landed on the
                # wrong broker account on 8/10-11 with no error anywhere.
                record_mismatch(ticker, user_id, _note, "execute.single")
                return [AgentMessage(
                    agent=self.name, kind="error", confidence=1.0,
                    payload={"user_id": user_id, "ticker": ticker,
                             "event": "execute_error",
                             "lane": _lane,
                             "error": f"route check failed: {_note}"})]
            _g = await self._gate_book(
                user_id, ticker, side, message.payload,
                cfg=_bot_settings(user_id),
                ks_state=_book_ks.get(str(user_id)),
                dollar_over=_dollar_over, benched=_benched, lane=_lane)
            if _g.rr_note:
                self._log_rr_notes(ticker, message.payload, _lane,
                                   [_g.rr_note])
            if _g.skip is not None:
                return [_g.skip]
            return await self._execute_for_user(user_id, ticker, side,
                                                _g.payload)

    async def _book_open_tickers(self) -> dict | None:
        """{user_id: {TICKER, ...}} of OPEN positions - one query serving
        the whole fan-out, so each book is measured against its own
        holdings (book-first, Mike 2026-08-20). None on any failure:
        fail OPEN, the historical behavior - a capacity gate that turns
        a Supabase blip into a frozen platform is worse than the
        oversized minute it might allow."""
        try:
            import asyncio
            from app.runtime.persistence import _client
            client = _client()
            if client is None:
                return None

            def _fetch():
                return (client.table("paper_positions")
                        .select("user_id, ticker, asset_type")
                        .eq("status", "open").execute())

            res = await asyncio.to_thread(_fetch)
            out: dict = {}
            for row in (res.data or []):
                u = str(row.get("user_id") or "")
                t = (row.get("ticker") or "").strip().upper()
                a = (row.get("asset_type") or "stock").strip().lower()
                if u and t:
                    out.setdefault(u, {})[t] = a
            return out
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _pocket_cap(cfg, asset_type: str, book_cap: int) -> int:
        """How many of this book's slots belong to THIS pocket.

        Per-pocket capacity (Mike 2026-08-21: "the open positions was
        supposed to be for each pocket available in the book, not the
        total amount of the positions possible"). The book-wide cap
        fixed on 08-20 stopped books from judging each other, but one
        hot lane could still fill all 14 slots and starve the rest.
        Slots now split across the pockets the book actually funds, in
        proportion to allocation_overrides; every funded pocket keeps
        at least 1 slot. A book with no allocation_overrides keeps the
        old behavior (book-wide cap only).
        """
        pockets = getattr(cfg, "allocation_overrides", None) or {}
        if not isinstance(pockets, dict) or not pockets:
            return book_cap
        # settings pockets are keyed stocks/options/crypto/forex/income;
        # paper_positions.asset_type says stock/option/crypto/forex.
        _key = {"stock": "stocks", "option": "options",
                "crypto": "crypto", "forex": "forex",
                "income": "income"}.get(asset_type, "stocks")
        # UNPINNED IS NOT UNFUNDED (2026-09-02). A lane ABSENT from the
        # pins is sized by the posture split in build_allocation, so it
        # carries no slot pin either -- it gets the book-wide cap. This
        # used to return 0 for a missing key, which meant that clearing a
        # book's stocks dollar pin (the way to let the widened posture
        # split govern) silently gave the stock lane ZERO slots and every
        # new stock name was refused. An explicit 0 still means "not
        # funded on this book" -- that is a deliberate setting.
        if _key not in pockets:
            return book_cap
        total = sum(float(v or 0) for v in pockets.values())
        alloc = float(pockets.get(_key, 0) or 0)
        if total <= 0:
            return book_cap
        if alloc <= 0:
            return 0  # pocket not funded on this book
        return max(1, round(book_cap * alloc / total))

    @staticmethod
    def _pocket_open(held: dict, asset_type: str) -> int:
        """Open positions in this pocket. `held` maps TICKER->asset_type."""
        _norm = {"stock": "stock", "option": "option", "crypto": "crypto",
                 "forex": "forex", "income": "income"}
        want = _norm.get(asset_type, "stock")
        return sum(1 for a in held.values() if a == want)

    async def _margin_territory_bump(self, user_id, ticker: str,
                                     asset_type: str) -> tuple[int, str]:
        """TE-19: the margin-territory TCS bump, per book, under ITS binding.

        Mike 2026-07-17: agents may dip into margin buying power, but
        leverage multiplies both directions, so it must be earned. When
        THIS book's broker cash thins below TREZO_MARGIN_CASH_FRACTION of
        its equity (default 15% -- roughly one position's notional), its
        next stock entry is margin territory and the bar rises
        +TREZO_MARGIN_TCS_BUMP (default 8). Crypto/forex exempt (no
        margin at the venue; the engine keeps them cash-only).

        Copied from the Risk Manager block that never fired: it read the
        account as a dict (`.get`) while get_account returns an
        AlpacaAccount, so the AttributeError was swallowed and the bump
        was 0 for every signal -- and it read ONE account for all books.
        Snapshot cached 60s per book; a failed read (None) means no bump
        and no cache, never a guess. Must be called inside
        bind_for_user(user_id): get_account reads whichever account is
        bound.
        """
        if str(asset_type or "").lower() in ("crypto", "forex"):
            return 0, ""
        try:
            from app.data.candles import COIN_MAP as _CM
            if str(ticker or "").upper() in _CM:
                return 0, ""
        except Exception:  # noqa: BLE001
            pass
        try:
            import os as _os
            import time as _t
            snaps = getattr(self, "_margin_snaps", None)
            if snaps is None:
                snaps = self._margin_snaps = {}
            snap = snaps.get(str(user_id)) or {}
            if _t.time() - float(snap.get("ts") or 0) > 60:
                from app.brokers.alpaca import alpaca_configured, get_account
                if not alpaca_configured():
                    return 0, ""
                acct = await get_account()
                if acct is None:
                    return 0, ""
                snap = {"cash": float(getattr(acct, "cash", 0) or 0),
                        "equity": float(getattr(acct, "equity", 0) or 0),
                        "ts": _t.time()}
                snaps[str(user_id)] = snap
            cash, equity = snap.get("cash"), snap.get("equity")
            if cash is None or not equity or float(equity) <= 0:
                return 0, ""
            try:
                frac = float(_os.getenv("TREZO_MARGIN_CASH_FRACTION", "0.15"))
            except (TypeError, ValueError):
                frac = 0.15
            if float(cash) < float(equity) * frac:
                try:
                    bump = int(float(_os.getenv("TREZO_MARGIN_TCS_BUMP", "8")))
                except (TypeError, ValueError):
                    bump = 8
                return bump, (f"margin territory +{bump} (cash "
                              f"${float(cash):,.0f} < {frac:.0%} of "
                              f"${float(equity):,.0f} equity)")
        except Exception:  # noqa: BLE001
            pass
        return 0, ""

    async def _read_book_brakes(self, client, ticker: str, side: str,
                                source_payload: dict, n_books: int, *,
                                user_id=None):
        """The two per-approval kill-switch reads BOTH execution paths
        make before any book is gated (review 2026-09-01: the single-book
        path made neither).

        check_states -> {user_id: KillSwitch}. KS-11: None (not {}) means
        the paper_accounts read FAILED -- "cannot evaluate" -- and
        execution is the enforcement point, so NO book executes on this
        approval: returns the execute_error to emit as the third item. A
        dead database used to read as "no halts anywhere". An exception
        is the same answer.

        daily_dollar_over -> the books at their user-set daily $ limit
        (KS-12), read once next to the percent brake. None is "unknown"
        (read failed): said in the log, then proceeds -- the percent
        brake still holds and the risk gate already applied this one.

        Returns (states, dollar_over, fail_closed_msg)."""
        _lane = _lane_of(ticker, source_payload)
        _book_ks: dict | None = None
        try:
            from app.paper.killswitch import check_states as _ck_states
            _book_ks = await _ck_states(client)
        except Exception:  # noqa: BLE001
            _book_ks = None
        if _book_ks is None:
            _ks_err = ("kill-switch state unreadable — fail closed: "
                       f"{ticker} {side} not executed for any of "
                       f"{n_books} book(s)")
            try:
                from app.agents.activity_log import record as _arec
                _arec("execute_error", ticker,
                      strategy=source_payload.get("strategy"),
                      reason=_ks_err[:180],
                      extra={"lane": _lane, "books": n_books,
                             **({"user_id": str(user_id)} if user_id
                                else {})})
            except Exception:  # noqa: BLE001
                pass
            return None, None, AgentMessage(
                agent=self.name, kind="error", confidence=1.0,
                payload={**({"user_id": user_id} if user_id else {}),
                         "ticker": ticker, "side": side,
                         "event": "execute_error", "lane": _lane,
                         "reason": "kill-switch state unreadable — fail closed",
                         "error": _ks_err})
        _dollar_over: set | None = None
        try:
            from app.paper.killswitch import daily_dollar_over as _ddo
            _dollar_over = await _ddo(client)
        except Exception:  # noqa: BLE001
            _dollar_over = None
        if _dollar_over is None:
            try:
                from app.agents.activity_log import record as _arec
                _arec("daily_dollar_limit_unknown", ticker,
                      strategy=source_payload.get("strategy"),
                      reason=("daily $ loss limits unreadable -- proceeding "
                              "on the percent brake alone"),
                      extra={"lane": _lane})
            except Exception:  # noqa: BLE001
                pass
        return _book_ks, _dollar_over, None

    def _log_rr_notes(self, ticker: str, source_payload: dict, lane: str,
                      notes: list) -> None:
        """RR-2 / RR-3 / RM-6: one activity line per approval naming each
        book whose geometry was re-harmonized to ITS floor (before ->
        after). Shared by both execution paths."""
        if not notes:
            return
        try:
            from app.agents.activity_log import record as _arec
            _arec("rr_reharmonized", ticker,
                  strategy=source_payload.get("strategy"),
                  reason="; ".join(notes)[:290],
                  extra={"lane": lane, "books": len(notes)})
        except Exception:  # noqa: BLE001
            pass

    async def _gate_book(self, uid, ticker: str, side: str,
                         source_payload: dict, *, cfg, ks_state,
                         dollar_over, benched, lane: str) -> _BookGate:
        """Every per-book gate short of capacity, judged for ONE book with
        ITS settings row, under ITS binding. The one place the fan-out and
        the single-book path share (review 2026-09-01), so a gate added
        here reaches both and neither can drift.

        In order, exactly as the fan-out always ran them: this book's own
        kill-switch verdict (hard halt -> skip; weekly recovery -> the
        speculative lanes skip, everything else trades half size with the
        KS-5 conviction bump and tighter stops downstream), its daily $
        brake (KS-12), its per-coin bench (benched_books), its R:R
        geometry against ITS min_reward_risk (RR-2/RR-3/RM-6 -- skipped
        for a no_price_stop lane, NEQ-05), its margin-territory bump
        (TE-19, read under its binding), then book_gate.admits (lane
        toggles, auto-trade, its TCS floor plus the bumps).

        Must be called inside bind_for_user(uid) after check_route: the
        margin read goes to whichever account is bound."""
        from app.runtime.book_gate import admits as _admits
        _sp_uid = source_payload
        _tcs_bump = 0    # KS-5 + TE-19, this book's own
        _lev_note = ""
        _rr_note: Optional[str] = None
        _strat_b = str(source_payload.get("strategy") or "")

        def _skip(event: str, note: str, **extra) -> _BookGate:
            return _BookGate(payload=_sp_uid, skip=AgentMessage(
                agent=self.name, kind="info", confidence=1.0,
                payload={"user_id": uid, "ticker": ticker, "side": side,
                         "lane": lane, "event": event, "note": note,
                         **extra}))

        # THIS book's own kill-switch verdict (2026-08-27). Hard halt
        # (daily / streak / session) -> this book sits out; the others
        # keep working. Weekly recovery -> speculative lanes sit out and
        # everything else trades tightened (half size, tighter stops,
        # done via the per-book payload below).
        if ks_state is not None:
            if ks_state.halted and ks_state.mode != "recovery":
                return _skip("book_halted_skip",
                             f"[{ks_state.scope}] {ks_state.reason}")
            if ks_state.mode == "recovery":
                from app.paper.killswitch import (
                    RECOVERY_SIZE_FACTOR, RECOVERY_TCS_BUMP,
                    recovery_policy)
                if recovery_policy(_strat_b) == "suspend":
                    return _skip("recovery_suspend_skip",
                                 (f"weekly recovery suspends {_strat_b}: "
                                  f"{ks_state.reason}"),
                                 strategy=_strat_b)
                # Tighten, per THIS book: half the book's own risk
                # fraction (risk_pct_override is honored by every
                # execution path) and flag the payload so stops tighten
                # downstream. Copy, never mutate — the dict is shared
                # across the fan-out.
                try:
                    _base_risk = float(
                        source_payload.get("risk_pct_override")
                        or getattr(cfg, "risk_per_trade_pct", 0.05)
                        or 0.05)
                except (TypeError, ValueError):
                    _base_risk = 0.05
                _sp_uid = {**source_payload,
                           "_recovery_mode": True,
                           "risk_pct_override":
                           _base_risk * RECOVERY_SIZE_FACTOR}
                # KS-5: a recovering book's conviction bar rises by
                # RECOVERY_TCS_BUMP. Risk Manager adds it only when
                # EVERY book is recovering (or for a user-scoped
                # signal's own book); the per-book verdict belongs here.
                _tcs_bump += int(RECOVERY_TCS_BUMP)
        # KS-12 per book: at its own daily $ loss limit.
        if dollar_over is not None and str(uid) in dollar_over:
            return _skip("daily_dollar_limit_skip",
                         (f"{ticker}: this book is at its daily $ loss "
                          f"limit (profiles.daily_loss_limit_usd) - "
                          f"skipped"))
        # Per-coin loss halt tripped on THIS book (benched_books).
        if str(uid) in (benched or ()):
            return _skip("coin_loss_halt_skip",
                         (f"{ticker}: per-coin daily loss halt is tripped "
                          f"on this book (benched_books) - skipped"))
        _atype = _lane_of(ticker, _sp_uid)
        # RR-2 / RR-3 / RM-6: Risk Manager harmonized the stop against
        # the SIGNAL user's min_reward_risk (0.4) while sizing judges
        # each EXECUTING book against its own floor (0.5) -- 134
        # rejections 'Reward:risk 0.4 below your 0.5 floor' and a dark
        # equity lane. Re-harmonize per book, exactly as the global
        # harmonizer does: stop = max(target / floor, 0.004), only ever
        # tightening; crypto exempt there too. The floor values and the
        # learned target are untouched.
        # NEQ-05: a no_price_stop lane has no stop to harmonize -- and
        # must not be handed one here.
        if _atype != "crypto" and not _sp_uid.get("no_price_stop"):
            try:
                _sf = _sp_uid.get("stop_pct")
                _tf = _sp_uid.get("target_pct")
                if _sf and _tf and float(_sf) > 0:
                    _rrf = float(getattr(cfg, "min_reward_risk", 1.5) or 1.5)
                    # Judge against the floor sizing will actually apply
                    # (it clamps to [0.3, 3.0]); the row's value is not
                    # changed (review 2026-09-01, rv:trade_execution :589).
                    _rrf = max(0.3, min(3.0, _rrf))
                    if float(_tf) / float(_sf) < _rrf:
                        _new_s = max(round(float(_tf) / max(_rrf, 0.1), 4),
                                     0.004)
                        # RV-1 (review 2026-09-01): round() can land the
                        # 4-dp stop half a bp ABOVE target/floor
                        # (0.0032/0.75 = 0.004266 -> 0.0043) and sizing's
                        # 2-dp ratio then reads 0.74 < 0.75 -- the exact
                        # rejection this block exists to prevent. Judge
                        # it the way sizing will; one bp tighter always
                        # clears a half-bp round-up.
                        if (_new_s > 0.004
                                and round(float(_tf) / _new_s, 2) < _rrf):
                            _new_s = round(_new_s - 0.0001, 4)
                        if _new_s < float(_sf):
                            _sp_uid = {
                                **_sp_uid, "stop_pct": _new_s,
                                "rr_reharmonized": {
                                    "book_floor": _rrf,
                                    "stop_pct_from": float(_sf),
                                    "stop_pct_to": _new_s}}
                            _rr_note = (
                                f"{str(uid)[:8]}: floor {_rrf:g}, "
                                f"stop {float(_sf) * 100:.2f}% -> "
                                f"{_new_s * 100:.2f}% (target "
                                f"{float(_tf) * 100:.2f}%, R:R "
                                f"{float(_tf) / float(_sf):.2f} -> "
                                f"{float(_tf) / _new_s:.2f})")
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        # TE-19: margin-territory bump -- THIS book's cash vs THIS book's
        # equity, read under its binding.
        _lev_bump, _lev_note = await self._margin_territory_bump(
            uid, ticker, _atype)
        _tcs_bump += int(_lev_bump or 0)
        _v = _admits(
            cfg,
            asset_type=_atype,
            strategy=str(_sp_uid.get("strategy") or ""),
            tcs=_sp_uid.get("tcs"),
            tcs_bump=_tcs_bump)
        if not _v.ok:
            return _BookGate(
                payload=_sp_uid, tcs_bump=_tcs_bump, lev_note=_lev_note,
                rr_note=_rr_note,
                skip=AgentMessage(
                    agent=self.name, kind="info", confidence=1.0,
                    payload={"user_id": uid, "ticker": ticker,
                             "side": side, "lane": _atype,
                             "event": _v.event,
                             "strategy": source_payload.get("strategy"),
                             "tcs": source_payload.get("tcs"),
                             "tcs_bump": _tcs_bump,
                             "note": (f"{ticker}: {_v.reason}"
                                      + (f"; {_lev_note}"
                                         if _lev_note else ""))}))
        return _BookGate(payload=_sp_uid, tcs_bump=_tcs_bump,
                         lev_note=_lev_note, rr_note=_rr_note)

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

        Every per-book gate runs here, under bind_for_user(uid), because
        this is the first line where a book has a name: route check, then
        _gate_book (its own kill-switch verdict with the KS-5 bump, its
        daily $ brake KS-12, its per-coin bench, its R:R geometry against
        ITS floor RR-2/RR-3, its margin-territory bump TE-19, then
        book_gate.admits) -- shared with the single-book path -- and
        finally capacity. A kill-switch state that cannot be read fails
        CLOSED for every book (KS-11, _read_book_brakes).
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
                    "event": "execute_error",
                    "lane": _lane_of(ticker, source_payload),
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
        from app.brokers.accounts import bind_for_user as _bind_acct
        from app.brokers.route_guard import check_route as _check_route
        from app.brokers.route_guard import record_mismatch as _rec_mm
        from app.runtime.settings import get_bot_settings as _bot_settings
        # Book-first capacity (Mike 2026-08-20): "make the agents look
        # at the books as a default and not the account. no matter
        # what." The old open-signal cap counted every book's positions
        # in one bucket and judged the total against ONE book's
        # max_open_positions - three books x ~10 positions read as
        # 14/14 and 516 entries died in a day with every book holding
        # spare slots. Count each book by name, once per signal.
        open_by_book = await self._book_open_tickers()
        # PER-BOOK kill-switch states (Mike 2026-08-27: "the agents are
        # not treating each book as their own book"). Fetched once per
        # signal (row sums are 30s-cached inside); each book is then
        # judged on ITS OWN halt/recovery in _gate_book — a tripped
        # primary no longer decides anything for the 25k or the 75k.
        # KS-11 (None -> fail closed for every book) and KS-12 (the $
        # brake, None -> unknown, logged) live in _read_book_brakes,
        # shared with the single-book path.
        _lane = _lane_of(ticker, source_payload)
        _book_ks, _dollar_over, _closed = await self._read_book_brakes(
            client, ticker, side, source_payload, len(users))
        if _closed is not None:
            return [_closed]
        # Per-coin loss halt, measured PER BOOK by Risk Manager
        # (killswitch.coin_loss_halt_by_book) and carried on the approval
        # as benched_books. Read defensively -- older producers omit it.
        _benched = {str(b) for b in
                    (source_payload.get("benched_books") or []) if b}
        # RR-2 / RR-3 / RM-6: books whose stop was re-harmonized to THEIR
        # floor, logged once per approval after the loop.
        _rr_notes: list[str] = []
        for uid in users:
            try:
                # Each book's order must go to ITS OWN broker account.
                # This loop already existed -- Trezo has always fanned out
                # across paper_accounts -- but with one global credential
                # every book's orders landed on the primary (2026-08-09).
                with _bind_acct(uid):
                    _ok, _note = _check_route(uid)
                    if not _ok:
                        _rec_mm(ticker, uid, _note, "execute.fanout")
                        continue
                    # Per-book appetite (2026-08-18). A scanner signal
                    # carries no user_id, so every settings read upstream
                    # of here -- the scanner's own toggle, the TCS floor
                    # Risk Manager judged it against -- resolved to the
                    # GLOBAL row. One book's opinion then applied to all
                    # three: turning crypto off on the 25k did nothing,
                    # because the primary's crypto_enabled was what the
                    # scanner read. This is the first line where a book
                    # has a name, so it is where its own answer counts.
                    _cfg = _bot_settings(uid)
                    # Every per-book gate short of capacity: kill-switch
                    # (halt / recovery + KS-5 bump), daily $ brake, bench,
                    # R:R re-harmonization to ITS floor, margin bump
                    # (TE-19), book_gate.admits -- one helper, shared with
                    # the single-book path so the two cannot drift.
                    _g = await self._gate_book(
                        uid, ticker, side, source_payload, cfg=_cfg,
                        ks_state=_book_ks.get(str(uid)),
                        dollar_over=_dollar_over, benched=_benched,
                        lane=_lane)
                    if _g.rr_note:
                        _rr_notes.append(_g.rr_note)
                    if _g.skip is not None:
                        out.append(_g.skip)
                        continue
                    _sp_uid = _g.payload
                    _atype = _lane_of(ticker, _sp_uid)
                    # THIS book's slot count vs THIS book's cap. A book
                    # already holding the ticker may still add to it
                    # (accumulation) - a full book only refuses NEW names.
                    # And within the book, THIS POCKET's count vs THIS
                    # POCKET's share of the slots (Mike 2026-08-21) - a
                    # crypto run can no longer occupy the stock pocket's
                    # chairs.
                    if open_by_book is not None:
                        _held = open_by_book.get(str(uid), {})
                        _cap = int(getattr(_cfg, "max_open_positions", 14)
                                   or 14)
                        # THE STACKING GUARD, per book (Mike 2026-09-02).
                        # Risk Manager used to refuse the whole signal when
                        # ANY book held the name -- one book's ETH silenced
                        # ETH for all three (the APPROVAL STARVATION
                        # alerts). That refusal now lives here, where each
                        # book's OPEN rows are read live for this very
                        # signal: a book that holds the name is skipped,
                        # the books that do not are executed. Accumulation
                        # lanes (crypto HODL/DCA) may still add, exactly as
                        # before -- Risk Manager has already applied their
                        # cooldown and per-coin cap upstream.
                        try:
                            from app.strategies.crypto import (
                                is_accumulation_strategy as _is_accum)
                            _accum_ok = _is_accum(_sp_uid.get("strategy")
                                                  or source_payload.get("strategy"))
                        except Exception:  # noqa: BLE001
                            _accum_ok = False
                        if ticker.upper() in _held and not _accum_ok:
                            try:
                                from app.agents.activity_log import record as _arec
                                _arec("book_already_holds", ticker,
                                      strategy=str(_sp_uid.get("strategy") or ""),
                                      reason=(f"this book already holds "
                                              f"{ticker} - skipped to avoid "
                                              f"stacking; other books are "
                                              f"judged on their own rows"),
                                      extra={"user_id": str(uid),
                                             "market_type": _atype})
                            except Exception:  # noqa: BLE001
                                pass
                            out.append(AgentMessage(
                                agent=self.name, kind="info",
                                confidence=1.0,
                                payload={"user_id": uid, "ticker": ticker,
                                         "side": side,
                                         "event": "book_already_holds",
                                         "note": (f"{ticker}: this book "
                                                  f"already holds it - no "
                                                  f"stacking")}))
                            continue
                        _pcap = self._pocket_cap(_cfg, _atype, _cap)
                        _popen = self._pocket_open(_held, _atype)
                        if (ticker.upper() not in _held
                                and len(_held) >= _cap):
                            out.append(AgentMessage(
                                agent=self.name, kind="info",
                                confidence=1.0,
                                payload={"user_id": uid, "ticker": ticker,
                                         "side": side,
                                         "event": "book_at_capacity",
                                         "note": (f"{ticker}: book holds "
                                                  f"{len(_held)}/{_cap} open "
                                                  f"positions - no free "
                                                  f"slot")}))
                            continue
                        if (ticker.upper() not in _held
                                and _popen >= _pcap):
                            out.append(AgentMessage(
                                agent=self.name, kind="info",
                                confidence=1.0,
                                payload={"user_id": uid, "ticker": ticker,
                                         "side": side,
                                         "event": "pocket_at_capacity",
                                         "note": (f"{ticker}: '{_atype}' "
                                                  f"pocket holds "
                                                  f"{_popen}/{_pcap} of this "
                                                  f"book's slots - other "
                                                  f"pockets keep their "
                                                  f"chairs")}))
                            continue
                    msgs = await self._execute_for_user(uid, ticker, side,
                                                        _sp_uid)
                out.extend(msgs or [])
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(
                    agent=self.name, kind="error", confidence=1.0,
                    payload={
                        "user_id": uid,
                        "ticker": ticker,
                        "side": side,
                        "event": "execute_error", "lane": _lane,
                        "error": f"execute failed for user: {e}",
                    },
                ))
        # RR-2 / RR-3 / RM-6: one line per approval naming each book whose
        # geometry was re-harmonized to ITS floor (before -> after).
        self._log_rr_notes(ticker, source_payload, _lane, _rr_notes)
        return out

    async def _execute_for_user(
        self,
        user_id: str,
        ticker: str,
        side: str,
        source_payload: dict,
    ) -> list[AgentMessage]:
        # Forex (2026-07-02): the signal declares its own asset_type;
        # ticker-derived detection stays the fallback for stock/crypto.
        _declared = str(source_payload.get("asset_type") or "").lower()
        if _declared == "forex":
            asset_type = "forex"
        else:
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
                payload={"user_id": user_id, "ticker": ticker,
                         "event": "execute_error", "lane": asset_type,
                         "error": "No price data"},
            )]
        market_price = float(candles[-1].close)

        stop_pct = source_payload.get("stop_pct")
        target_pct = source_payload.get("target_pct")

        # Weekly recovery (Mike 2026-08-27): stops 25% tighter for a
        # recovering book — "tighten up the spread to make things work
        # away from the loss". Applied here, the one point every
        # execution path (internal, Alpaca stock, both crypto routes)
        # flows through. Size halving rides risk_pct_override, set at
        # the fan-out from THIS book's own risk fraction.
        if (source_payload or {}).get("_recovery_mode"):
            try:
                from app.paper.killswitch import RECOVERY_STOP_FACTOR
                if isinstance(stop_pct, (int, float)) and stop_pct > 0:
                    stop_pct = float(stop_pct) * RECOVERY_STOP_FACTOR
            except Exception:  # noqa: BLE001
                pass

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

        # Crypto Part 2 (2026-06-13): real exchange connector (Coinbase/
        # Kraken) for the ISO coins Alpaca cannot trade. SCAFFOLD + OFF:
        # is_configured() is False until keys are added, so this never
        # fires today and crypto stays on the modeled engine. Part 3 fills
        # in crypto_exchange.submit_order and routes the full ISO list to a
        # live venue. Long-only.
        if asset_type == "crypto":
            try:
                from app.brokers.crypto_exchange import (
                    is_configured as _cx_ready,
                    exchange_supports as _cx_supports,
                )
                if _cx_ready() and _cx_supports(ticker):
                    return await self._execute_crypto_exchange(
                        user_id, ticker, side, market_price,
                        stop_pct, target_pct, strategy, source_payload,
                    )
            except Exception:  # noqa: BLE001
                pass  # connector error -> fall through to the modeled engine

        if asset_type == "stock" and alpaca_configured():
            return await self._execute_alpaca(
                user_id, ticker, side, market_price,
                stop_pct, target_pct, strategy, source_payload,
            )

        return await self._execute_internal(
            user_id, ticker, asset_type, side, market_price,
            stop_pct, target_pct, strategy, source_payload,
        )

    async def _execute_crypto_exchange(
        self, user_id, ticker, side, market_price,
        stop_pct, target_pct, strategy, source_payload,
    ) -> list[AgentMessage]:
        # Scaffold path (crypto Part 2). The connector's submit_order
        # raises NotImplementedError today; we catch it and fall back to
        # the modeled engine so flipping the flag early can never strand a
        # signal. Part 3 replaces this body with real fill handling.
        try:
            from app.brokers import crypto_exchange as _cx
            await _cx.submit_order(
                user_id=user_id, ticker=ticker, side=side,
                price=market_price, stop_pct=stop_pct, target_pct=target_pct,
            )
        except NotImplementedError:
            # AUDIT 2026-08-27: this fallback used to be silent -- the
            # connector's own header calls exit management "the step that
            # risks real money", and routing to the modeled engine
            # without saying so made a modeled fill indistinguishable
            # from a venue fill in the feed. The fallback is correct;
            # the silence was not.
            try:
                from app.agents.activity_log import record as _kfrec
                _kfrec("venue_fallback_modeled", ticker,
                       strategy=strategy,
                       reason=("Kraken order path not implemented -- "
                               "routed to the MODELED engine instead. "
                               "This fill is simulated, not a venue "
                               "fill."))
            except Exception:  # noqa: BLE001
                pass
            return await self._execute_internal(
                user_id, ticker, "crypto", side, market_price,
                stop_pct, target_pct, strategy, source_payload,
            )
        except Exception as e:  # noqa: BLE001
            return [AgentMessage(
                agent=self.name, kind="error",
                payload={"user_id": user_id, "ticker": ticker,
                         "event": "execute_error", "lane": "crypto",
                         "error": f"crypto_exchange submit failed: {e}"},
            )]
        # REACHABLE silent path (re-audit 2026-08-28): submit_order in
        # validate-only mode returns successfully and we fall through to
        # a MODELED fill — the NotImplementedError branch above is
        # unreachable by construction (router requires is_configured,
        # the raise requires credentials ABSENT). Say it here, where it
        # actually happens.
        try:
            from app.agents.activity_log import record as _kfrec2
            _kfrec2("venue_fallback_modeled", ticker,
                    strategy=strategy,
                    reason=("crypto_exchange connector accepted the "
                            "order in validate-only mode -- the FILL is "
                            "from the MODELED engine, not the venue."))
        except Exception:  # noqa: BLE001
            pass
        return await self._execute_internal(
            user_id, ticker, "crypto", side, market_price,
            stop_pct, target_pct, strategy, source_payload,
        )

    async def _allocation_gate(self, user_id, equity, strategy, asset_type):
        from app.paper.allocation import (
            build_allocation, deployed_capital, market_type_for,
            effective_equity,
        )
        # Pockets size from BROKER-truth equity (2026-07-02) -- the internal
        # ledger had drifted below the broker and was shrinking every pocket.
        try:
            _true_eq = await effective_equity(user_id)
            if _true_eq > 0:
                equity = _true_eq
        except Exception:  # noqa: BLE001
            pass
        from app.runtime.settings import get_bot_settings
        # Per book. Posture and allocation overrides are exactly the kind
        # of setting that must not leak between accounts (2026-08-18).
        cfg = get_bot_settings(user_id)
        mt = market_type_for(strategy, asset_type)
        alloc = build_allocation(
            equity,
            posture_setting=cfg.account_posture,
            overrides=cfg.allocation_overrides,
        )
        budget = float(alloc.budgets.get(mt, 0.0))
        # Small-account soft pockets (Mike 2026-07-02): hard pockets work
        # at size, but at low equity they SQUEEZE -- a 10% pocket of a
        # $5k account cannot fund one option, and swing holds starve the
        # fast lanes. Below TREZO_HARD_POCKET_MIN_EQUITY the pockets act
        # as soft WEIGHTS: each lane stretches by TREZO_SMALL_ACCT_POCKET_
        # STRETCH (capped at 60% of equity per lane). At size, pockets
        # harden back to exact fractions automatically.
        try:
            import os as _os2
            _min_eq = float(_os2.getenv("TREZO_HARD_POCKET_MIN_EQUITY", "25000"))
            if equity and float(equity) < _min_eq:
                _stretch = float(_os2.getenv(
                    "TREZO_SMALL_ACCT_POCKET_STRETCH", "1.75"))
                budget = min(budget * max(1.0, _stretch),
                             float(equity) * 0.60)
        except Exception:  # noqa: BLE001
            pass
        # Intraday overflow (2026-07-02): multi-day swing holds were
        # filling the stocks pocket and STARVING every intraday idea
        # (found live: TSLL/BITO/TZA approvals skipped all morning).
        # Self-liquidating strategies (scalp/orb/stms exit by 3:45) may
        # run the pocket over by a bounded fraction -- they give the
        # capital back the same session.
        try:
            import os as _os
            _s = (strategy or "").lower()
            # 2026-07-14 (Mike): crypto and forex round-trip the same day
            # too -- their capital should be as flexible as the stock
            # intraday lanes, not pinched by held-position conservatism.
            if (_s.startswith(("scalp", "orb", "stms"))
                    or str(mt) in ("crypto", "forex")):
                _ov = float(_os.getenv("TREZO_INTRADAY_OVERFLOW_PCT", "0.25"))
                # SURGE days (Mike 2026-07-14): when the generals run on
                # heavy volume, the fast lanes stretch +50% -- catch the
                # wave, sell by the rules, recycle the capital.
                try:
                    from app.data.market_universe import surge_day
                    if surge_day():
                        _ov = max(_ov, float(_os.getenv(
                            "TREZO_SURGE_OVERFLOW_PCT", "0.50")))
                        import datetime as _dtm
                        _tdy = _dtm.date.today().isoformat()
                        if getattr(surge_day, "_logged", "") != _tdy:
                            surge_day._logged = _tdy  # type: ignore[attr-defined]
                            from app.agents.activity_log import record as _arec
                            _arec("pocket_surge", "MARKET",
                                  reason=("hot-volume day: fast-lane pockets "
                                          "stretched +50% (surge overflow) -- "
                                          "catch the wave, sell by the rules, "
                                          "recycle"),
                                  extra={})
                except Exception:  # noqa: BLE001
                    pass
                budget = budget * (1.0 + max(0.0, _ov))
        except Exception:  # noqa: BLE001
            pass
        deployed = float((await deployed_capital(user_id)).get(mt, 0.0))
        remaining = max(0.0, budget - deployed)
        return mt, budget, deployed, remaining, alloc.posture

    async def _budget_skip(self, user_id, ticker, mt, budget, deployed,
                           posture):
        # Priority rotation (Mike 2026-07-02: "the bots should weigh out
        # the decision to actually take certain trades over others").
        # When live demand keeps hitting a FULL pocket, the lane's weakest
        # stale hold (36h+ old, entry conviction under 550) is asked to
        # leave through the normal close_requested flow -- capital
        # recycles to fresher, higher-priority demand in the SAME lane.
        # Income lanes are never rotated for fast lanes; max N/day.
        try:
            import os as _os3
            if (_os3.getenv("TREZO_PRIORITY_ROTATION", "1") != "0"
                    and mt in ("stocks", "crypto", "forex")):
                from datetime import date as _date
                from datetime import datetime, timezone
                global _ROTATIONS_TODAY
                _today = _date.today().isoformat()
                if _ROTATIONS_TODAY.get("day") != _today:
                    _ROTATIONS_TODAY = {"day": _today, "n": 0}
                _max_rot = int(float(_os3.getenv(
                    "TREZO_PRIORITY_ROTATION_MAX_PER_DAY", "2")))
                if _ROTATIONS_TODAY["n"] < _max_rot:
                    from app.runtime.settings import _supabase
                    client = _supabase()
                    if client is not None:
                        import asyncio as _aio

                        def _q():
                            return (client.table("paper_positions")
                                    .select("id, ticker, entry_at, "
                                            "source_payload, strategy")
                                    .eq("user_id", user_id)
                                    .eq("status", "open")
                                    .eq("close_requested", False)
                                    .execute())
                        rows = (await _aio.to_thread(_q)).data or []
                        from app.paper.allocation import market_type_for
                        now = datetime.now(timezone.utc)
                        cands = []
                        for r in rows:
                            if market_type_for(r.get("strategy"), None) != mt:
                                continue
                            if str(r.get("ticker") or "").upper() == str(ticker).upper():
                                continue
                            try:
                                ea = datetime.fromisoformat(
                                    str(r.get("entry_at")).replace("Z", "+00:00"))
                                held_h = (now - ea).total_seconds() / 3600.0
                            except Exception:  # noqa: BLE001
                                continue
                            _tcs0 = int(((r.get("source_payload") or {})
                                         .get("tcs")) or 0)
                            if held_h >= 36 and _tcs0 < 55:
                                cands.append((held_h, _tcs0, r))
                        if cands:
                            cands.sort(key=lambda x: (x[1], -x[0]))
                            _held_h, _tcs0, victim = cands[0]

                            def _flag(rid=victim["id"]):
                                return (client.table("paper_positions")
                                        .update({"close_requested": True})
                                        .eq("id", rid).execute())
                            await _aio.to_thread(_flag)
                            _ROTATIONS_TODAY["n"] += 1
                            try:
                                from app.agents.activity_log import record as _arec
                                _arec("priority_rotation",
                                      str(victim.get("ticker")),
                                      reason=(f"{mt} pocket full while demand "
                                              f"queues ({ticker}) - weakest hold "
                                              f"(entry TCS {_tcs0}, held "
                                              f"{_held_h:.0f}h) asked to leave; "
                                              f"capital recycles to stronger "
                                              f"signals"),
                                      extra={"user_id": str(user_id),
                                             "displaced_by": str(ticker)})
                            except Exception:  # noqa: BLE001
                                pass
        except Exception:  # noqa: BLE001
            pass
        # Visibility pack (2026-07-01): pocket-full skips are the #1 silent
        # trade-dropper -- make every one visible with the pocket numbers.
        try:
            from app.agents.activity_log import record as _arec
            _arec("pocket_skip", ticker,
                  reason=f"{mt} pocket full under the {posture} posture "
                         f"(${deployed:,.0f} of ${budget:,.0f} deployed) - trade skipped",
                  extra={"user_id": str(user_id), "market_type": mt,
                         "budget_usd": round(budget, 2),
                         "deployed_usd": round(deployed, 2)})
        except Exception:  # noqa: BLE001
            pass
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

        # NEQ-05 / G3: the modeled engine sizes from a stop distance and
        # writes stop_price on the row -- it has no stop-free entry.
        # Refusing beats planting the 5% default on a lane that asked
        # for none (that default IS the NEQ-05 failure). The broker
        # stock path has the plain-buy entry (_execute_alpaca_no_stop).
        if (source_payload or {}).get("no_price_stop"):
            _why = ("no_price_stop entries need the broker stock path "
                    "(plain buy, no bracket); the modeled engine has no "
                    "stop-free entry -- refused rather than planting a "
                    "default stop")
            try:
                from app.agents.activity_log import record as _arec
                _arec("execute_error", ticker, strategy=strategy,
                      reason=_why[:180],
                      extra={"user_id": str(user_id), "lane": asset_type})
            except Exception:  # noqa: BLE001
                pass
            return [AgentMessage(
                agent=self.name, kind="error",
                payload={"user_id": user_id, "ticker": ticker,
                         "event": "execute_error", "lane": asset_type,
                         "error": _why},
            )]

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
            if not (source_payload or {}).get("coverage_trade"):
                return await self._budget_skip(user_id, ticker, mt, budget, deployed, posture)

        kwargs: dict = {
            "user_id": user_id,
            "ticker": ticker,
            "asset_type": asset_type,
            "side": side,
            "market_price": market_price,
            "strategy": strategy,
            "source_payload": source_payload,
            # 2026-08-27: honor risk_pct_override like the Alpaca paths
            # already do — it is how per-book recovery halves size on
            # the internal engine too.
            "risk_pct": (float(source_payload.get("risk_pct_override"))
                         if (source_payload or {}).get("risk_pct_override")
                         else get_bot_settings(user_id).risk_per_trade_pct),
            # AUDIT 2026-08-27: this key used to be assigned `remaining`
            # unconditionally, OVERWRITING any cap the signal itself
            # carried -- the dividend lane's U3 per-name concentration
            # cap (spec: "enforced, not warned") was set upstream and
            # never read. The binding rule: the tighter of the pocket's
            # remaining budget and whatever the lane asked for.
            "max_notional": remaining,
        }
        try:
            _lane_cap = (source_payload or {}).get("max_notional")
            if _lane_cap is not None and float(_lane_cap) > 0:
                kwargs["max_notional"] = min(float(remaining),
                                             float(_lane_cap))
        except (TypeError, ValueError):
            pass
        if isinstance(stop_pct, (int, float)) and stop_pct > 0:
            kwargs["stop_pct"] = float(stop_pct)
        if isinstance(target_pct, (int, float)) and target_pct > 0:
            kwargs["target_pct"] = float(target_pct)

        fill = await open_position(**kwargs)
        if not fill.ok:
            # Outcome-message contract: every rejection carries
            # event="execute_error" and its lane for ops_watchdog.
            return [AgentMessage(
                agent=self.name, kind="error",
                payload={"user_id": user_id, "ticker": ticker,
                         "event": "execute_error", "lane": asset_type,
                         "error": fill.error},
            )]
        return [AgentMessage(
            agent=self.name, kind="execute", confidence=1.0,
            payload={
                "user_id": user_id,
                "ticker": ticker,
                "side": side,
                "lane": asset_type,
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
            # Visibility (2026-07-06): execution-stage rejections were
            # INVISIBLE in the activity feed -- approvals showed, then
            # silence (the R:R-floor incident). Every _err now logs.
            try:
                from app.agents.activity_log import record as _arec
                _arec("execute_error", ticker, strategy=strategy,
                      reason=str(msg)[:180],
                      extra={"user_id": str(user_id)})
            except Exception:  # noqa: BLE001
                pass
            # Outcome-message contract: event + lane so ops_watchdog can
            # count rejections per lane.
            return [AgentMessage(
                agent=self.name, kind="error",
                payload={"user_id": user_id, "ticker": ticker,
                         "broker": "alpaca", "event": "execute_error",
                         "lane": "stock", "error": msg},
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
            if not (source_payload or {}).get("coverage_trade"):
                return await self._budget_skip(user_id, ticker, mt, budget, deployed, posture)

        # NEQ-05 / G3: a no-price-stop lane never reaches the bracket
        # path below -- that path invents a 5% stop when none was sent
        # (`sp = ... else 0.05`), sizes from it, and hands the venue a
        # stop leg the lane said it does not want.
        if (source_payload or {}).get("no_price_stop"):
            return await self._execute_alpaca_no_stop(
                user_id, ticker, side, market_price, strategy,
                source_payload, acct=acct, remaining=remaining,
                token=token, routed=routed, err=_err)

        sp = float(stop_pct) if isinstance(stop_pct, (int, float)) and stop_pct > 0 else 0.05
        tp = float(target_pct) if isinstance(target_pct, (int, float)) and target_pct > 0 else 0.10
        if side == "long":
            stop_price = market_price * (1 - sp)
            target_price = market_price * (1 + tp)
            order_side = "buy"
        elif side == "short":
            stop_price = market_price * (1 + sp)
            target_price = market_price * (1 - tp)
            order_side = "sell"
        else:
            # TE-07: never let an unknown side become a SHORT sale.
            return _err(f"unknown side {side!r} -- refusing rather than "
                        f"defaulting to short")

        risk_pct = source_payload.get("risk_pct_override")
        if risk_pct is None:
            # Per book (2026-08-18). A bare get_bot_settings() here meant
            # every book could be SIZED from one book's risk_per_trade_pct
            # -- the 75k's appetite applied to the 25k, or the reverse.
            # Sizing is the last place a setting should leak.
            risk_pct = get_bot_settings(user_id).risk_per_trade_pct
        plan = plan_position(
            equity=acct.equity,
            entry_price=market_price,
            stop_price=stop_price,
            target_price=target_price,
            risk_pct=float(risk_pct),
            asset_type="stock",
            # RR-3: THIS book's R:R floor and concentration cap, by name.
            user_id=user_id,
            # Tightest of broker BP, pocket remainder, and the lane's own
            # cap (2026-08-28 — the cap used to die in _execute_internal,
            # a function the live stock path never calls).
            buying_power=min([x for x in (
                acct.buying_power, remaining,
                _lane_cap_f(source_payload)) if x is not None]),
        )
        # Coverage trades stay SMALL (Mike 2026-07-02): one labeled test
        # position per strategy, capped near TREZO_COVERAGE_TRADE_USD.
        if plan.ok and (source_payload or {}).get("coverage_trade"):
            try:
                import dataclasses as _dc
                import os as _osc
                _cov = float(_osc.getenv("TREZO_COVERAGE_TRADE_USD", "150"))
                _maxq = max(1.0, float(int(_cov / max(market_price, 0.01))))
                if plan.quantity > _maxq:
                    plan = _dc.replace(plan, quantity=_maxq,
                                       notional_usd=round(_maxq * market_price, 2))
            except Exception:  # noqa: BLE001
                pass
        # Probation half-size (Mike 2026-07-14): the regime playbook keeps
        # breakout LIVE in rough weather but at reduced size. Risk Manager
        # sets size_scale on the approval; we honor it here.
        if plan.ok:
            try:
                _ss = float((source_payload or {}).get("size_scale") or 0)
                if 0.0 < _ss < 1.0:
                    import dataclasses as _dcs
                    _q2 = plan.quantity * _ss
                    if str(asset_type or "stock") not in ("crypto", "forex"):
                        _q2 = max(1.0, float(int(_q2)))
                    plan = _dcs.replace(
                        plan, quantity=_q2,
                        notional_usd=round(_q2 * market_price, 2))
            except Exception:  # noqa: BLE001
                pass
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

        # Fixed 2026-06-12 (the AAPL incident): bracket exit legs with
        # tif="day" DIE at the 4 PM close while the position lives on --
        # so any multi-day trade went naked overnight (AAPL "default"
        # strategy targets +10%, a multi-day journey, but its stop/target
        # expired same-day). Only true intraday strategies (STMS/ORB,
        # which also have hard time stops) keep day legs; everything
        # else gets GTC legs that survive until filled or cancelled.
        _s = (strategy or "").lower()
        tif = "day" if (_s.startswith("stms") or _s.startswith("orb")) else "gtc"
        # Broker sanity clamps (2026-07-07, from the morning's rejects):
        # (1) Alpaca 422: take_profit must sit >= base+0.01 and the stop
        #     <= base-0.01 -- tight ATR targets can round INTO the base.
        # (2) Alpaca 403: risk-based sizing with tight stops can explode
        #     notional past buying power -- cap at max_position_pct of
        #     equity AND 90% of current BP. Three of these rejects tripped
        #     the session kill-switch and killed the whole day.
        try:
            # DIRECTION-AWARE clamp (fixed 2026-08-11). The 7/7 version
            # assumed every trade was a LONG: it forced take-profit above
            # market and stop below market. Applied to a SHORT, that takes
            # correct levels and INVERTS them -- TP dragged above the stop
            # -- so every short bracket died on the local orientation
            # guard ("short take-profit must sit BELOW stop"). IREN,
            # 2026-08-11 13:31, and the 6 rejects of 8/5 are this bug.
            _tick = max(0.01, round(float(market_price) * 0.001, 2))
            if order_side == "sell":
                # Short: profit BELOW market, stop ABOVE market.
                if target_price is not None:
                    target_price = min(float(target_price),
                                       round(float(market_price) - _tick, 2))
                if stop_price is not None:
                    stop_price = max(float(stop_price),
                                     round(float(market_price) + _tick, 2))
            else:
                if target_price is not None:
                    target_price = max(float(target_price),
                                       round(float(market_price) + _tick, 2))
                if stop_price is not None:
                    stop_price = min(float(stop_price),
                                     round(float(market_price) - _tick, 2))
        except Exception:  # noqa: BLE001
            pass
        try:
            import dataclasses as _dc
            from app.config import get_settings as _gcfg
            try:
                from app.paper.allocation import position_pct_for_equity
                _mp_pct = position_pct_for_equity(float(acct.equity or 0))
            except Exception:  # noqa: BLE001
                _mp_pct = float(getattr(_gcfg(), "max_position_pct", 0.25) or 0.25)
            _cap_usd = min(_mp_pct * float(acct.equity or 0),
                           0.90 * float(acct.buying_power or 0))
            if _cap_usd > 0 and plan.ok:
                _maxq2 = max(1.0, float(int(_cap_usd / max(market_price, 0.01))))
                if plan.quantity > _maxq2:
                    plan = _dc.replace(plan, quantity=_maxq2,
                                       notional_usd=round(_maxq2 * market_price, 2))
        except Exception:  # noqa: BLE001
            pass
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
            record_broker_reject(str(user_id))  # THIS book's reject, not the platform's
            try:
                from app.agents.activity_log import record as _arec
                _arec("broker_reject", ticker, strategy=strategy,
                      reason=str(err)[:200],
                      extra={"user_id": str(user_id), "asset_type": "stock"})
            except Exception:  # noqa: BLE001
                pass
            return _err(f"Alpaca rejected the order: {err}")

        order_id = order.get("id")
        try:
            from app.agents.activity_log import record as _arec
            _arec("submitted", ticker, strategy=strategy,
                  reason=f"{side} {plan.quantity} @ ~{market_price} "
                         f"(stop {stop_price}, target {target_price})",
                  extra={"user_id": str(user_id), "asset_type": "stock"})
        except Exception:  # noqa: BLE001
            pass
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
                    "lane": "stock",
                    "broker": "alpaca",
                    "broker_order_id": order_id,
                    "strategy": strategy,
                    "note": f"Submitted {ticker} {side} via Alpaca, order_id={order_id}",
                },
            )
        ]


    async def _execute_alpaca_no_stop(
        self, user_id, ticker, side, market_price, strategy,
        source_payload, *, acct, remaining, token, routed, err,
    ) -> list[AgentMessage]:
        """NEQ-05 / G3: the no-price-stop stock entry (the dividend
        ladder). Called from _execute_alpaca after the clock, account and
        pocket gates, so those hold here too.

        The ladder holds through drawdowns by design -- its exits are the
        spec's (dividend cut, payout breach, recycling ratio), not a
        price -- so there is no stop distance to size from and no exit
        leg to hand the venue. Sized by NOTIONAL instead: the tightest of
        the lane's own max_notional (the per-name concentration cap it
        computed for THIS book), the pocket's remaining budget, the
        broker's buying power, and the same concentration clamp the
        bracket path applies (max_position_pct of equity, 90% of BP);
        weekly recovery halves it like every other entry. Whole shares.
        Submits a PLAIN market buy -- no bracket legs -- and writes the
        ledger row with stop_price / target_price NULL and
        no_price_stop=True in source_payload so position_monitor honours
        it. Long-only; REFUSES (execute_error) rather than guess when the
        lane sent no max_notional or the side is not long."""
        from app.brokers.alpaca import submit_market_buy
        from app.paper.engine import record_external_position

        if side != "long":
            return err("no_price_stop is long-only -- refusing a short "
                       "with no stop rather than defaulting")
        _cap = _lane_cap_f(source_payload)
        if _cap is None:
            return err("no_price_stop without max_notional -- refusing "
                       "rather than guessing a size")
        try:
            _bp = float(getattr(acct, "buying_power", 0) or 0)
            _eq = float(getattr(acct, "equity", 0) or 0)
        except (TypeError, ValueError):
            _bp, _eq = 0.0, 0.0
        notional = min(float(_cap), float(remaining), _bp)
        # Weekly recovery: half size, per book (the fan-out / single-book
        # gate set _recovery_mode for THIS book).
        if (source_payload or {}).get("_recovery_mode"):
            try:
                from app.paper.killswitch import RECOVERY_SIZE_FACTOR
                notional *= float(RECOVERY_SIZE_FACTOR)
            except Exception:  # noqa: BLE001
                notional *= 0.5
        # The bracket path's concentration clamp, same numbers: the
        # account-size curve (or THIS book's own max_position_pct slider
        # when set, as sizing honours it) and 90% of buying power.
        try:
            from app.paper.allocation import position_pct_for_equity
            _mp_pct = float(position_pct_for_equity(_eq))
        except Exception:  # noqa: BLE001
            _mp_pct = 0.25
        try:
            from app.runtime.settings import get_bot_settings as _gbs_ns
            _user_cap = getattr(_gbs_ns(user_id), "max_position_pct", None)
            if _user_cap is not None and 0.01 <= float(_user_cap) <= 1.0:
                _mp_pct = float(_user_cap)
        except Exception:  # noqa: BLE001
            pass
        _clamp_usd = min(_mp_pct * _eq, 0.90 * _bp)
        if _clamp_usd > 0:
            notional = min(notional, _clamp_usd)
        qty = float(int(notional / max(float(market_price), 0.01)))
        if qty < 1:
            return err(f"no_price_stop sizing produced 0 shares: notional "
                       f"cap ${notional:,.2f} at ${float(market_price):,.2f} "
                       f"(lane cap ${float(_cap):,.2f}, pocket "
                       f"${float(remaining):,.2f}, BP ${_bp:,.2f})")
        order, oerr = await submit_market_buy(symbol=ticker, qty=qty,
                                              token=token)
        if oerr or not order:
            from app.paper.killswitch import record_broker_reject
            record_broker_reject(str(user_id))  # THIS book's reject
            try:
                from app.agents.activity_log import record as _arec
                _arec("broker_reject", ticker, strategy=strategy,
                      reason=str(oerr)[:200],
                      extra={"user_id": str(user_id), "asset_type": "stock"})
            except Exception:  # noqa: BLE001
                pass
            return err(f"Alpaca rejected the order: {oerr}")
        order_id = order.get("id")
        try:
            from app.agents.activity_log import record as _arec
            _arec("submitted", ticker, strategy=strategy,
                  reason=(f"long {qty:g} @ ~{market_price} (plain buy, NO "
                          f"price stop; notional cap ${notional:,.2f})"),
                  extra={"user_id": str(user_id), "asset_type": "stock",
                         "no_price_stop": True})
        except Exception:  # noqa: BLE001
            pass
        await record_external_position(
            user_id=user_id,
            ticker=ticker,
            asset_type="stock",
            side=side,
            quantity=qty,
            entry_price=market_price,
            stop_price=None,
            target_price=None,
            strategy=strategy,
            broker="alpaca",
            broker_order_id=order_id,
            source_payload={**source_payload, "broker": "alpaca",
                            "broker_order_id": order_id,
                            "no_price_stop": True},
        )
        return [
            AgentMessage(
                agent=self.name, kind="execute", confidence=1.0,
                payload={
                    "user_id": user_id,
                    "ticker": ticker,
                    "side": side,
                    "lane": "stock",
                    "broker": "alpaca",
                    "broker_order_id": order_id,
                    "strategy": strategy,
                    "quantity": qty,
                    "no_price_stop": True,
                    "routed_via": routed,
                    "note": (f"Submitted {ticker} {side} via Alpaca (plain "
                             f"buy, no price stop), order_id={order_id}"),
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
            # Visibility (2026-07-06): execution-stage rejections were
            # INVISIBLE in the activity feed -- approvals showed, then
            # silence (the R:R-floor incident). Every _err now logs.
            try:
                from app.agents.activity_log import record as _arec
                _arec("execute_error", ticker, strategy=strategy,
                      reason=str(msg)[:180],
                      extra={"user_id": str(user_id)})
            except Exception:  # noqa: BLE001
                pass
            # Outcome-message contract: event + lane so ops_watchdog can
            # count rejections per lane.
            return [AgentMessage(
                agent=self.name, kind="error",
                payload={"user_id": user_id, "ticker": ticker,
                         "broker": "alpaca", "asset_type": "crypto",
                         "event": "execute_error", "lane": "crypto",
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
            if not (source_payload or {}).get("coverage_trade"):
                return await self._budget_skip(user_id, ticker, mt, budget, deployed, posture)

        sp = float(stop_pct) if isinstance(stop_pct, (int, float)) and stop_pct > 0 else 0.05
        tp = float(target_pct) if isinstance(target_pct, (int, float)) and target_pct > 0 else 0.10
        if side == "long":
            stop_price = market_price * (1 - sp)
            target_price = market_price * (1 + tp)
            order_side = "buy"
        elif side == "short":
            stop_price = market_price * (1 + sp)
            target_price = market_price * (1 - tp)
            order_side = "sell"
        else:
            # TE-07: never let an unknown side become a SHORT sale.
            return _err(f"unknown side {side!r} -- refusing rather than "
                        f"defaulting to short")

        risk_pct = source_payload.get("risk_pct_override")
        if risk_pct is None:
            # Per book (2026-08-18). A bare get_bot_settings() here meant
            # every book could be SIZED from one book's risk_per_trade_pct
            # -- the 75k's appetite applied to the 25k, or the reverse.
            # Sizing is the last place a setting should leak.
            risk_pct = get_bot_settings(user_id).risk_per_trade_pct
        # Crypto spends NON-MARGINABLE USD at Alpaca (2026-07-23: six
        # approvals died as HTTP 403 "insufficient balance for USD,
        # available: 0" while options collateral pledged every dollar,
        # and the rejects tripped the session kill-switch). Check the
        # right bucket BEFORE the broker does: when the USD wallet is
        # collateral-locked, skip cleanly -- one visible line, no 403
        # storm, no kill-switch trips.
        # Shots on goal (Mike 2026-07-27: "crypto trades are producing a
        # way to make income in the dailies"). The 15%-of-equity
        # concentration cap let ONE coin swallow ~$730 -- two positions
        # emptied the wallet and the 24/7 lane went quiet until an exit.
        # Slice the crypto pocket into TREZO_CRYPTO_MAX_CONCURRENT
        # (default 5) equal shots instead: same capital at risk, several
        # independent chances at a daily win, and a stop on one coin no
        # longer benches the whole lane. Scales with the pocket, so it
        # grows automatically as the account grows.
        try:
            import os as _os_cx
            _cx_n = max(1, int(float(
                _os_cx.getenv("TREZO_CRYPTO_MAX_CONCURRENT", "5"))))
        except (TypeError, ValueError):
            _cx_n = 5
        _cx_slice = max(25.0, float(budget) / _cx_n) if budget else 1e12
        _crypto_usd = float(getattr(
            acct, "non_marginable_buying_power", 0.0) or 0.0)
        # FEE HEADROOM (Mike 2026-08-03: repeated 403s at "requested:
        # 65.66, available: 64.35"). Sizing spent the wallet to the last
        # cent, but Alpaca needs room for fees and price drift between
        # the quote and the fill, so orders missed by ~2% and were
        # rejected -- and each reject counted toward the kill-switch.
        # Keep a small buffer back; a slightly smaller order fills,
        # a perfectly-sized one does not.
        try:
            import os as _os_hr
            _hair = float(_os_hr.getenv("TREZO_CRYPTO_USD_HAIRCUT", "0.96"))
        except (TypeError, ValueError):
            _hair = 0.96
        _crypto_usd = _crypto_usd * max(0.5, min(1.0, _hair))
        if _crypto_usd < 25.0:
            try:
                from app.agents.activity_log import record as _arec
                _arec("crypto_skip_no_usd", ticker, strategy=strategy,
                      reason=(f"crypto entry skipped: USD wallet "
                              f"collateral-locked at the broker "
                              f"(available ${_crypto_usd:,.2f}); frees as "
                              f"option collateral releases"),
                      extra={"user_id": str(user_id)})
            except Exception:  # noqa: BLE001
                pass
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"user_id": user_id, "ticker": ticker,
                         "event": "crypto_skip_no_usd",
                         "note": (f"{ticker}: crypto entry skipped -- USD "
                                  f"wallet collateral-locked "
                                  f"(${_crypto_usd:,.2f} available)")},
            )]
        plan = plan_position(
            equity=acct.equity,
            entry_price=market_price,
            stop_price=stop_price,
            target_price=target_price,
            risk_pct=float(risk_pct),
            asset_type="crypto",
            # RR-3: THIS book's R:R floor and concentration cap, by name.
            user_id=user_id,
            buying_power=min([x for x in (
                _crypto_usd, remaining, _cx_slice,
                _lane_cap_f(source_payload)) if x is not None]),
        )
        if plan.ok and (source_payload or {}).get("coverage_trade"):
            try:
                import dataclasses as _dc
                import os as _osc
                _cov = float(_osc.getenv("TREZO_COVERAGE_TRADE_USD", "150"))
                _maxq = _cov / max(market_price, 1e-9)
                if plan.quantity > _maxq:
                    plan = _dc.replace(plan, quantity=_maxq,
                                       notional_usd=round(_maxq * market_price, 2))
            except Exception:  # noqa: BLE001
                pass
        if not plan.ok:
            return _err(plan.reject_reason or "Sizing rejected the trade")

        # ALPACA CRYPTO MINIMUM (2026-08-09). Alpaca rejects any crypto order
        # whose cost basis is under $10 -- "cost basis must be >= minimal
        # amount of order 10". On 8/9 that produced 12 rejects, and THREE
        # rejects inside an hour trip the session kill-switch, so a sizing
        # problem cascaded into an hour-long trading pause. Skipping the
        # order cleanly costs one trade; sending it costs the hour.
        import os as _os_min      # module has NO top-level `import os`
        _min_notional = float(_os_min.getenv("TREZO_CRYPTO_MIN_ORDER_USD", "10"))
        _notional = float(plan.quantity) * float(market_price)
        if _notional < _min_notional:
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"user_id": user_id, "ticker": ticker,
                         "event": "crypto_skip_below_min",
                         "note": (f"{ticker}: order would be ${_notional:,.2f}, "
                                  f"below Alpaca's ${_min_notional:,.0f} crypto "
                                  f"minimum -- skipped before the broker could "
                                  f"reject it and trip the kill-switch")},
            )]

        order, err = await submit_crypto_order(
            symbol=ticker,
            side=order_side,
            qty=plan.quantity,
            token=token,
        )
        if err or not order:
            from app.paper.killswitch import record_broker_reject
            record_broker_reject(str(user_id))  # THIS book's reject, not the platform's
            try:
                from app.agents.activity_log import record as _arec
                _arec("broker_reject", ticker, strategy=strategy,
                      reason=str(err)[:200],
                      extra={"user_id": str(user_id), "asset_type": "crypto"})
            except Exception:  # noqa: BLE001
                pass
            return _err(f"Alpaca rejected the crypto order: {err}")

        order_id = order.get("id")
        try:
            from app.agents.activity_log import record as _arec
            _arec("submitted", ticker, strategy=strategy,
                  reason=f"{side} {plan.quantity} crypto @ ~{market_price}",
                  extra={"user_id": str(user_id), "asset_type": "crypto"})
        except Exception:  # noqa: BLE001
            pass
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
                    "lane": "crypto",
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
