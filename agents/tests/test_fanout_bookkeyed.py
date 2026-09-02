"""Guards: the execution fan-out judges EVERY book as its own book.

Audit 2026-09-01. The equity lane was dark (rank 4): Risk Manager
harmonized stop = target / floor against the SIGNAL user's
min_reward_risk (0.4) while sizing judged each EXECUTING book against
its own floor (0.5) through a bare get_bot_settings() -- 134 rejections
'Reward:risk 0.4 below your 0.5 floor' (RR-2 / RR-3 / RM-6). Around it,
four per-book gates that existed upstream but never reached the book:
the daily $ brake (KS-12), the per-coin bench (benched_books), the
recovery conviction bump (KS-5) and the margin-territory bump (TE-19).
And two contracts: a kill-switch state that cannot be read fails CLOSED
(KS-11), and 'long' is a long (TE-07).

Review 2026-09-01 added three more: BI-03 at the fan-out (an unscoped
signal approved at the LOWEST book floor executes only on the books
whose own floor it clears); the SINGLE-BOOK path (user_id + book_scoped)
runs the same per-book gate as the fan-out -- one helper, _gate_book,
so the two cannot drift; and NEQ-05 / G3 (an approval carrying
no_price_stop is never re-harmonized, is sized by notional, reaches a
PLAIN buy with no bracket legs, and lands on the ledger with NULL
stop/target and no_price_stop=True in source_payload).

These drive the REAL TradeExecutionAgent.on_message ->
_execute_for_all_users -> book_gate.admits, with only the external
seams stubbed (persistence client, account binding, route guard, the
two kill-switch reads, settings, the broker account read) and
_execute_for_user recorded. Every stub is restored on exit; nothing is
planted in sys.modules -- run_all imports every suite into one process.

Run: python -m tests.run_all   (the deploy gate)   or pytest.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
te = load_module("app.agents.trade_execution")
AgentMessage = load_module("app.agents.base").AgentMessage
accounts = load_module("app.brokers.accounts")
route_guard = load_module("app.brokers.route_guard")
ks = load_module("app.paper.killswitch")
settings_mod = load_module("app.runtime.settings")
persistence = load_module("app.runtime.persistence")
alpaca = load_module("app.brokers.alpaca")
sizing = load_module("app.paper.sizing")

BOOK_A = "book-a-0000"      # the signal user's floor (0.4)
BOOK_B = "book-b-1111"      # a stricter book (0.5)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and ALWAYS put the originals back."""
    old = {k: getattr(mod, k, None) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                if hasattr(mod, k):
                    delattr(mod, k)
            else:
                setattr(mod, k, v)


@contextlib.contextmanager
def _quiet_activity_log():
    """No logs/activity-*.jsonl writes from a guard test."""
    prev = os.environ.get("TREZO_ACTIVITY_LOG")
    os.environ["TREZO_ACTIVITY_LOG"] = "0"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("TREZO_ACTIVITY_LOG", None)
        else:
            os.environ["TREZO_ACTIVITY_LOG"] = prev


# --- fakes -----------------------------------------------------------------

class _Res:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        return _Res(list(self._rows))


class _FakeClient:
    """Canned paper_accounts rows; no open positions anywhere."""

    def __init__(self, user_ids):
        self._tables = {
            "paper_accounts": [{"user_id": u} for u in user_ids],
            "paper_positions": [],
        }

    def table(self, name):
        return _Query(self._tables.get(name, []))


class Book:
    """One book's BotSettings row."""

    def __init__(self, **kw):
        self.auto_trade_enabled = True
        self.crypto_enabled = True
        self.extended_enabled = True
        self.stms_enabled = True
        self.pattern_enabled = True
        self.tcs_threshold = 70
        self.min_reward_risk = 0.5
        self.risk_per_trade_pct = 0.05
        self.max_open_positions = 14
        self.allocation_overrides = None
        for k, v in kw.items():
            setattr(self, k, v)


def _books():
    return {BOOK_A: Book(min_reward_risk=0.4),
            BOOK_B: Book(min_reward_risk=0.5)}


def _acct(cash, equity):
    return alpaca.AlpacaAccount(
        equity=float(equity), last_equity=float(equity), cash=float(cash),
        buying_power=float(equity) * 2, currency="USD", status="ACTIVE",
        pattern_day_trader=False, daytrade_count=0, trading_blocked=False)


def _payload(**kw):
    p = {"ticker": "XLE", "direction": "bullish", "tcs": 75,
         "strategy": "swing", "asset_type": "stock",
         "stop_pct": 0.05, "target_pct": 0.02}      # R:R 0.4
    p.update(kw)
    return p


def _recovering():
    return ks.KillSwitch(halted=True, scope="week",
                         reason="weekly loss limit", mode="recovery")


_UNSET = object()
_RAISE = object()


class Harness:
    """Real agent, real fan-out, real book_gate; seams stubbed.

    Records, per book, the payload and side _execute_for_user received,
    which book was bound when the broker account was read, and every
    message the fan-out emitted.
    """

    def __init__(self, books, *, states=_UNSET, dollar_over=frozenset(),
                 accounts_by_book=None):
        self.books = books
        self.states = {} if states is _UNSET else states
        self.dollar_over = dollar_over
        self.accounts_by_book = accounts_by_book or {}
        self.executed: dict[str, dict] = {}
        self.sides: dict[str, str] = {}
        self.account_reads: list[str] = []
        self._current = None
        self.agent = te.TradeExecutionAgent()

        async def _exec_user(uid, ticker, side, payload):
            self.executed[str(uid)] = dict(payload)
            self.sides[str(uid)] = side
            return [AgentMessage(agent="trade_execution", kind="execute",
                                 confidence=1.0,
                                 payload={"user_id": uid, "ticker": ticker,
                                          "side": side})]

        self.agent._execute_for_user = _exec_user

    @contextlib.contextmanager
    def _bind(self, uid):
        prev, self._current = self._current, str(uid)
        try:
            yield object()
        finally:
            self._current = prev

    async def _check_states(self, _client):
        if self.states is _RAISE:
            raise RuntimeError("paper_accounts read blew up")
        return self.states

    async def _dollar_over(self, _client):
        return self.dollar_over

    async def _get_account(self, token=None):
        self.account_reads.append(self._current)
        return self.accounts_by_book.get(self._current)

    def _settings(self, user_id=None):
        return self.books[str(user_id)]

    def run(self, payload, *, via_on_message=False):
        client = _FakeClient(list(self.books))
        with _quiet_activity_log(), \
             _patched(persistence, _client=lambda: client), \
             _patched(accounts, bind_for_user=self._bind), \
             _patched(route_guard, check_route=lambda uid: (True, "stub")), \
             _patched(ks, check_states=self._check_states,
                      daily_dollar_over=self._dollar_over), \
             _patched(settings_mod, get_bot_settings=self._settings), \
             _patched(alpaca, get_account=self._get_account,
                      alpaca_configured=lambda: True):
            if via_on_message:
                msg = AgentMessage(agent="risk_manager", kind="approve",
                                   confidence=0.6, payload=payload)
                return _run(self.agent.on_message(msg))
            return _run(self.agent._execute_for_all_users(
                payload["ticker"], "long", dict(payload)))


def _events(out, event, uid=None):
    return [m for m in out
            if m.payload.get("event") == event
            and (uid is None or m.payload.get("user_id") == uid)]


# --- (1) RR-2 / RR-3 / RM-6: geometry calibrated to the executing book ------

def test_stop_is_reharmonized_to_the_executing_books_own_floor():
    h = Harness(_books())
    h.run(_payload())
    assert set(h.executed) == {BOOK_A, BOOK_B}
    assert h.executed[BOOK_A]["stop_pct"] == 0.05, \
        "0.4 floor: 0.02/0.05 = 0.4 is not under it -- geometry untouched"
    assert "rr_reharmonized" not in h.executed[BOOK_A]
    assert h.executed[BOOK_B]["stop_pct"] == 0.04, \
        "0.5 floor: stop must become target / 0.5, as the global harmonizer does"
    assert h.executed[BOOK_B]["rr_reharmonized"]["book_floor"] == 0.5
    assert h.executed[BOOK_B]["target_pct"] == 0.02, "the target is never touched"


def test_reharmonized_geometry_clears_the_real_sizing_floor_for_that_book():
    """The re-harmonized stop must satisfy sizing's OWN floor read for the
    book it is told about (strict '<' on a 2-dp ratio) or the fix is
    cosmetic. And the original geometry must still fail it, or the test
    proves nothing."""
    h = Harness(_books())
    h.run(_payload())
    p = h.executed[BOOK_B]
    seen: list = []

    def _gbs(user_id=None):
        seen.append(user_id)
        return h.books[str(user_id)]

    with _patched(settings_mod, get_bot_settings=_gbs):
        good = sizing.plan_position(
            equity=50_000, entry_price=100.0,
            stop_price=100.0 * (1 - p["stop_pct"]),
            target_price=100.0 * (1 + p["target_pct"]),
            risk_pct=0.02, asset_type="stock", buying_power=100_000,
            user_id=BOOK_B)
        bad = sizing.plan_position(
            equity=50_000, entry_price=100.0,
            stop_price=95.0, target_price=102.0,           # the old 0.4 geometry
            risk_pct=0.02, asset_type="stock", buying_power=100_000,
            user_id=BOOK_B)
    assert good.ok, good.reject_reason
    assert not bad.ok and "0.5 floor" in (bad.reject_reason or "")
    assert BOOK_B in seen, "sizing must read the floor for the book it was told, by name"


def test_a_rounded_up_stop_is_nudged_until_sizing_agrees():
    """RV-1: round(target / floor, 4) can land half a bp ABOVE target/floor
    (0.0032 / 0.75 = 0.004266 -> 0.0043) and sizing's 2-dp ratio then reads
    0.74 < 0.75 -- the rejection the re-harmonizer exists to prevent. The
    fan-out must judge the rounded stop the way sizing will and step one
    bp tighter; the real plan_position is the arbiter."""
    books = {BOOK_A: Book(min_reward_risk=0.4),
             BOOK_B: Book(min_reward_risk=0.75)}
    h = Harness(books)
    h.run(_payload(stop_pct=0.005, target_pct=0.0032))      # R:R 0.64
    assert h.executed[BOOK_A]["stop_pct"] == 0.005, "0.64 clears a 0.4 floor"
    p = h.executed[BOOK_B]
    assert p["stop_pct"] == 0.0042, p["stop_pct"]
    seen: list = []

    def _gbs(user_id=None):
        seen.append(user_id)
        return books[str(user_id)]

    with _patched(settings_mod, get_bot_settings=_gbs):
        plan = sizing.plan_position(
            equity=50_000, entry_price=100.0,
            stop_price=100.0 * (1 - p["stop_pct"]),
            target_price=100.0 * (1 + p["target_pct"]),
            risk_pct=0.02, asset_type="stock", buying_power=100_000,
            user_id=BOOK_B)
    assert plan.ok, plan.reject_reason
    assert BOOK_B in seen


def test_crypto_geometry_is_left_alone_as_upstream_does():
    h = Harness(_books())
    h.run(_payload(ticker="ETH", strategy="crypto_swing", asset_type="crypto"))
    assert set(h.executed) == {BOOK_A, BOOK_B}
    assert h.executed[BOOK_B]["stop_pct"] == 0.05
    assert "rr_reharmonized" not in h.executed[BOOK_B]


def test_both_broker_paths_size_by_book_name():
    assert "user_id" in inspect.signature(sizing.plan_position).parameters
    for fn in (te.TradeExecutionAgent._execute_alpaca,
               te.TradeExecutionAgent._execute_alpaca_crypto):
        src = inspect.getsource(fn)
        call = re.search(r"plan_position\((.*?)\n\s*\)", src, re.S)
        assert call and "user_id=user_id" in call.group(1), \
            f"{fn.__name__} must pass the executing book to plan_position"


# --- (2) benched_books ------------------------------------------------------

def test_a_benched_book_is_skipped_and_the_others_execute():
    h = Harness(_books())
    out = h.run(_payload(benched_books=[BOOK_A]))
    assert BOOK_A not in h.executed and BOOK_B in h.executed
    skips = _events(out, "coin_loss_halt_skip")
    assert [m.payload["user_id"] for m in skips] == [BOOK_A]


def test_a_payload_without_benched_books_benches_nobody():
    h = Harness(_books())
    p = _payload()
    p.pop("benched_books", None)
    h.run(p)
    assert set(h.executed) == {BOOK_A, BOOK_B}


# --- (3) KS-12: the per-book daily $ brake ----------------------------------

def test_a_book_over_its_daily_dollar_limit_is_skipped():
    h = Harness(_books(), dollar_over={BOOK_B})
    out = h.run(_payload())
    assert BOOK_A in h.executed and BOOK_B not in h.executed
    assert [m.payload["user_id"] for m in _events(out, "daily_dollar_limit_skip")] \
        == [BOOK_B]


def test_an_unreadable_dollar_limit_is_unknown_not_a_brake():
    h = Harness(_books(), dollar_over=None)
    h.run(_payload())
    assert set(h.executed) == {BOOK_A, BOOK_B}


# --- (4) KS-11: unreadable kill-switch state fails CLOSED -------------------

def test_unreadable_killswitch_state_executes_nothing_and_says_so():
    for states in (None, _RAISE):
        h = Harness(_books(), states=states)
        out = h.run(_payload())
        assert h.executed == {}, "no book may execute on an unknown state"
        assert len(out) == 1 and out[0].kind == "error"
        p = out[0].payload
        assert p.get("event") == "execute_error"
        assert p.get("lane") == "stock"
        assert "fail closed" in (p.get("reason") or "")


def test_an_empty_state_map_is_a_real_answer_and_trades():
    h = Harness(_books(), states={})
    h.run(_payload())
    assert set(h.executed) == {BOOK_A, BOOK_B}


# --- (5) TE-07: 'long' is a long; anything unknown is refused ---------------

def test_direction_words_map_to_the_right_side():
    for direction, want in (("long", "long"), ("bullish", "long"),
                            ("LONG", "long"), ("short", "short"),
                            ("bearish", "short")):
        h = Harness(_books())
        h.run(_payload(direction=direction), via_on_message=True)
        assert h.sides == {BOOK_A: want, BOOK_B: want}, \
            f"{direction!r} must execute as {want}"


def test_an_unknown_direction_is_refused_not_shorted():
    for direction in ("neutral", "income", "sideways", "", None):
        h = Harness(_books())
        out = h.run(_payload(direction=direction), via_on_message=True)
        assert h.executed == {}, f"{direction!r} must not execute"
        assert len(out) == 1 and out[0].kind == "error"
        assert out[0].payload.get("event") == "execute_error"
        assert out[0].payload.get("lane") == "stock"
        assert "refusing" in out[0].payload.get("error", "")


# --- (6) KS-5: a recovering book faces floor + RECOVERY_TCS_BUMP -----------

def test_a_recovering_book_faces_its_floor_plus_the_recovery_bump():
    h = Harness(_books(), states={BOOK_B: _recovering()})
    out = h.run(_payload(tcs=75))          # clears 70, not 70 + 10
    assert BOOK_A in h.executed and BOOK_B not in h.executed
    declined = _events(out, "book_declined", BOOK_B)
    assert len(declined) == 1
    assert f"floor of {70 + ks.RECOVERY_TCS_BUMP}" in declined[0].payload["note"]
    assert declined[0].payload.get("tcs_bump") == ks.RECOVERY_TCS_BUMP


def test_a_recovering_book_with_the_conviction_trades_tightened():
    h = Harness(_books(), states={BOOK_B: _recovering()})
    h.run(_payload(tcs=70 + ks.RECOVERY_TCS_BUMP))
    p = h.executed[BOOK_B]
    assert p.get("_recovery_mode") is True
    assert abs(p["risk_pct_override"] - 0.05 * ks.RECOVERY_SIZE_FACTOR) < 1e-9
    assert h.executed[BOOK_A].get("_recovery_mode") is None, \
        "the healthy book is not tightened by its neighbour's recovery"


# --- TE-19: margin territory, per book, under its own binding --------------

def _margin_env():
    return (float(os.getenv("TREZO_MARGIN_CASH_FRACTION", "0.15")),
            int(float(os.getenv("TREZO_MARGIN_TCS_BUMP", "8"))))


def test_margin_territory_raises_only_the_cash_thin_books_bar():
    frac, bump = _margin_env()
    h = Harness(_books(), accounts_by_book={
        BOOK_A: _acct(cash=100_000 * frac * 4, equity=100_000),
        BOOK_B: _acct(cash=100_000 * frac / 2, equity=100_000)})
    out = h.run(_payload(tcs=75))
    assert BOOK_A in h.executed and BOOK_B not in h.executed
    declined = _events(out, "book_declined", BOOK_B)
    assert len(declined) == 1
    assert f"floor of {70 + bump}" in declined[0].payload["note"]
    assert "margin territory" in declined[0].payload["note"]
    assert h.account_reads == [BOOK_A, BOOK_B], \
        "each book's account is read once, under THAT book's binding"


def test_a_failed_account_read_means_no_bump_not_a_guess():
    h = Harness(_books(), accounts_by_book={})       # get_account -> None
    h.run(_payload(tcs=75))
    assert set(h.executed) == {BOOK_A, BOOK_B}


def test_crypto_is_exempt_from_the_margin_bump_and_reads_no_account():
    frac, _bump = _margin_env()
    h = Harness(_books(), accounts_by_book={
        BOOK_A: _acct(cash=0, equity=100_000),
        BOOK_B: _acct(cash=0, equity=100_000)})
    h.run(_payload(ticker="ETH", strategy="crypto_swing", asset_type="crypto",
                   tcs=75))
    assert set(h.executed) == {BOOK_A, BOOK_B}
    assert h.account_reads == []


# --- outcome-message contract (consumer: ops_watchdog) ---------------------

def test_stock_path_rejections_carry_event_and_lane():
    wt = load_module("app.integrations.web_tokens")
    agent = te.TradeExecutionAgent()

    async def _no_token(_uid, _broker):
        return None

    async def _open(token=None):
        return {"is_open": True}

    async def _no_acct(token=None):
        return None

    with _quiet_activity_log(), \
         _patched(wt, get_user_broker_token=_no_token), \
         _patched(alpaca, get_clock=_open, get_account=_no_acct):
        out = _run(agent._execute_alpaca(
            "u", "XLE", "long", 100.0, 0.05, 0.10, "swing", {}))
    assert len(out) == 1 and out[0].kind == "error"
    assert out[0].payload.get("event") == "execute_error"
    assert out[0].payload.get("lane") == "stock"


def test_stock_path_refuses_an_unknown_side_instead_of_selling():
    wt = load_module("app.integrations.web_tokens")
    agent = te.TradeExecutionAgent()

    async def _no_token(_uid, _broker):
        return None

    async def _open(token=None):
        return {"is_open": True}

    async def _acct_ok(token=None):
        return _acct(cash=50_000, equity=100_000)

    async def _gate(_uid, _equity, _strategy, _at):
        return ("stocks", 10_000.0, 0.0, 10_000.0, "auto")

    agent._allocation_gate = _gate
    with _quiet_activity_log(), \
         _patched(wt, get_user_broker_token=_no_token), \
         _patched(alpaca, get_clock=_open, get_account=_acct_ok):
        out = _run(agent._execute_alpaca(
            "u", "XLE", "sideways", 100.0, 0.05, 0.10, "swing", {}))
    assert len(out) == 1 and out[0].kind == "error"
    assert "unknown side" in out[0].payload.get("error", "")
    assert out[0].payload.get("lane") == "stock"


# --- BI-03 at the fan-out: floors 40 / 70, an unscoped 55 -------------------
# Risk Manager now approves a scanner signal at the LOWEST enabled floor
# (tests/test_risk_manager_bookkeyed proves that half); this is where each
# book's OWN floor binds. The approve payload below is exactly the shape
# RM emits for that case: no user_id, no benched_books.

def test_an_unscoped_signal_at_55_executes_only_on_the_40_floor_book():
    books = {BOOK_A: Book(tcs_threshold=40), BOOK_B: Book(tcs_threshold=70)}
    h = Harness(books)
    out = h.run(_payload(tcs=55, stop_pct=0.02, target_pct=0.05),
                via_on_message=True)
    assert set(h.executed) == {BOOK_A}, h.executed
    declined = _events(out, "book_declined", BOOK_B)
    assert len(declined) == 1, out
    assert "floor of 70" in declined[0].payload["note"]
    assert _events(out, "book_declined", BOOK_A) == []


def test_an_unscoped_signal_under_both_floors_executes_nowhere():
    books = {BOOK_A: Book(tcs_threshold=40), BOOK_B: Book(tcs_threshold=70)}
    h = Harness(books)
    out = h.run(_payload(tcs=35), via_on_message=True)
    assert h.executed == {}
    assert {m.payload["user_id"] for m in _events(out, "book_declined")} == {BOOK_A, BOOK_B}


# --- the single-book path runs the SAME gates as the fan-out ----------------
# (review 2026-09-01, rv:killswitch-contracts / rv:bound-hunter :168). A
# user_id + book_scoped approval used to go straight to _execute_for_user
# with none of the gates below. The dividend lane is user-scoped.

def _pinned(**kw):
    return _payload(user_id=BOOK_B, book_scoped=True, **kw)


def _halted():
    return ks.KillSwitch(halted=True, scope="day",
                         reason="Daily loss limit: down $400 (4.0%) today",
                         mode="halt")


def test_pinned_approval_fails_closed_when_the_kill_switch_state_is_unreadable():
    for states in (None, _RAISE):
        h = Harness(_books(), states=states)
        out = h.run(_pinned(), via_on_message=True)
        assert h.executed == {}, "no book may execute on an unknown state"
        assert len(out) == 1 and out[0].kind == "error", out
        p = out[0].payload
        assert p.get("event") == "execute_error" and p.get("lane") == "stock"
        assert "fail closed" in (p.get("reason") or "")
        assert p.get("user_id") == BOOK_B, "the refusal names the pinned book"


def test_pinned_approval_on_a_halted_book_is_skipped():
    h = Harness(_books(), states={BOOK_B: _halted()})
    out = h.run(_pinned(), via_on_message=True)
    assert h.executed == {}, h.executed
    skips = _events(out, "book_halted_skip", BOOK_B)
    assert len(skips) == 1 and "Daily loss limit" in skips[0].payload["note"]


def test_pinned_approval_on_a_healthy_book_executes_there_only():
    """A halted NEIGHBOUR changes nothing for the pinned book -- and the
    pin holds: nothing fans out to the neighbour either."""
    h = Harness(_books(), states={BOOK_A: _halted()})
    h.run(_pinned(), via_on_message=True)
    assert set(h.executed) == {BOOK_B}, h.executed


def test_pinned_approval_over_its_daily_dollar_limit_is_skipped():
    h = Harness(_books(), dollar_over={BOOK_B})
    out = h.run(_pinned(), via_on_message=True)
    assert h.executed == {}
    assert [m.payload["user_id"] for m in _events(out, "daily_dollar_limit_skip")] == [BOOK_B]
    h2 = Harness(_books(), dollar_over={BOOK_A})
    h2.run(_pinned(), via_on_message=True)
    assert set(h2.executed) == {BOOK_B}, "a neighbour's $ limit is not this book's"


def test_pinned_approval_on_a_benched_book_is_skipped():
    h = Harness(_books())
    out = h.run(_pinned(benched_books=[BOOK_B]), via_on_message=True)
    assert h.executed == {}
    assert [m.payload["user_id"] for m in _events(out, "coin_loss_halt_skip")] == [BOOK_B]


def test_pinned_approval_is_reharmonized_to_its_own_books_floor():
    h = Harness(_books())
    h.run(_pinned(), via_on_message=True)              # 0.02 / 0.05 = R:R 0.4
    p = h.executed[BOOK_B]
    assert p["stop_pct"] == 0.04, p
    assert p["rr_reharmonized"]["book_floor"] == 0.5
    assert p["target_pct"] == 0.02


def test_pinned_approval_on_a_recovering_book_faces_the_bump_and_tightens():
    h = Harness(_books(), states={BOOK_B: _recovering()})
    out = h.run(_pinned(tcs=75), via_on_message=True)   # clears 70, not 80
    assert h.executed == {}
    declined = _events(out, "book_declined", BOOK_B)
    assert len(declined) == 1
    assert f"floor of {70 + ks.RECOVERY_TCS_BUMP}" in declined[0].payload["note"]
    h2 = Harness(_books(), states={BOOK_B: _recovering()})
    h2.run(_pinned(tcs=70 + ks.RECOVERY_TCS_BUMP), via_on_message=True)
    p = h2.executed[BOOK_B]
    assert p.get("_recovery_mode") is True
    assert abs(p["risk_pct_override"] - 0.05 * ks.RECOVERY_SIZE_FACTOR) < 1e-9


def test_pinned_approval_on_a_recovering_book_suspends_speculative_lanes():
    h = Harness(_books(), states={BOOK_B: _recovering()})
    out = h.run(_pinned(strategy="orb", tcs=95), via_on_message=True)
    assert h.executed == {}
    assert len(_events(out, "recovery_suspend_skip", BOOK_B)) == 1


def test_pinned_approval_gets_the_margin_bump_under_its_own_binding():
    frac, bump = _margin_env()
    h = Harness(_books(), accounts_by_book={
        BOOK_A: _acct(cash=100_000 * frac * 4, equity=100_000),
        BOOK_B: _acct(cash=100_000 * frac / 2, equity=100_000)})
    out = h.run(_pinned(tcs=75), via_on_message=True)
    assert h.executed == {}
    declined = _events(out, "book_declined", BOOK_B)
    assert len(declined) == 1 and "margin territory" in declined[0].payload["note"]
    assert h.account_reads == [BOOK_B], "only the pinned book's account, under ITS binding"


def test_both_paths_call_the_one_gate_helper():
    """The point of the refactor: a gate added to _gate_book reaches both
    paths. Source-shape guard so a re-inlined copy fails loudly."""
    for fn in (te.TradeExecutionAgent.on_message,
               te.TradeExecutionAgent._execute_for_all_users):
        src = inspect.getsource(fn)
        assert "self._gate_book(" in src, f"{fn.__name__} bypasses _gate_book"
        assert "self._read_book_brakes(" in src, f"{fn.__name__} bypasses _read_book_brakes"


# --- NEQ-05 / G3: no_price_stop through the fan-out and the single path ----

def test_no_price_stop_approval_is_never_reharmonized():
    """Contradictory input on purpose (a stop AND the flag): the flag is
    the contract, so the 0.5-floor book leaves the geometry alone."""
    h = Harness(_books())
    h.run(_pinned(no_price_stop=True), via_on_message=True)
    p = h.executed[BOOK_B]
    assert "rr_reharmonized" not in p and p["stop_pct"] == 0.05, p
    h2 = Harness(_books())
    h2.run(_payload(no_price_stop=True))                  # the fan-out
    for uid in (BOOK_A, BOOK_B):
        assert "rr_reharmonized" not in h2.executed[uid], uid


def _alpaca_no_stop_run(payload, *, side="long", remaining=10_000.0,
                        acct=None, price=100.0):
    """Drive the REAL _execute_alpaca with the broker seams stubbed.
    Returns (out, calls): calls['buy'] / ['bracket'] / ['rows']."""
    wt = load_module("app.integrations.web_tokens")
    engine = load_module("app.paper.engine")
    agent = te.TradeExecutionAgent()
    calls: dict = {"buy": [], "bracket": [], "rows": []}
    _a = acct or _acct(cash=50_000, equity=100_000)      # BP 200k

    async def _no_token(_uid, _broker):
        return None

    async def _open(token=None):
        return {"is_open": True}

    async def _acct_ok(token=None):
        return _a

    async def _gate(_uid, _equity, _strategy, _at):
        return ("income", 10_000.0, 0.0, remaining, "auto")

    async def _buy(symbol, qty, token=None, **kw):
        calls["buy"].append((symbol, qty, token))
        return {"id": "ord-1"}, None

    async def _bracket(**kw):
        calls["bracket"].append(kw)
        return {"id": "never"}, None

    async def _rec(**kw):
        calls["rows"].append(kw)
        return engine.FillResult(ok=True, position_id="p1",
                                 fill_price=kw["entry_price"])

    agent._allocation_gate = _gate
    with _quiet_activity_log(), \
         _patched(wt, get_user_broker_token=_no_token), \
         _patched(alpaca, get_clock=_open, get_account=_acct_ok,
                  submit_market_buy=_buy, submit_bracket_order=_bracket), \
         _patched(engine, record_external_position=_rec), \
         _patched(settings_mod, get_bot_settings=lambda uid=None: Book()):
        out = _run(agent._execute_alpaca(
            BOOK_B, "PG", side, price, None, None, "dividend_lt", payload))
    return out, calls


def test_no_price_stop_approve_reaches_a_plain_buy_sized_by_the_notional_cap():
    out, calls = _alpaca_no_stop_run(
        {"no_price_stop": True, "max_notional": 420.0, "tcs": 75,
         "strategy": "dividend_lt"})
    assert calls["bracket"] == [], "NO bracket legs on a no-price-stop entry"
    assert calls["buy"] == [("PG", 4.0, None)], calls["buy"]   # int(420 / 100)
    row = calls["rows"][0]
    assert row["stop_price"] is None and row["target_price"] is None, row
    assert row["source_payload"]["no_price_stop"] is True
    assert row["source_payload"]["broker_order_id"] == "ord-1"
    assert row["quantity"] == 4.0 and row["side"] == "long"
    assert len(out) == 1 and out[0].kind == "execute", out
    assert out[0].payload["lane"] == "stock" and out[0].payload["no_price_stop"] is True


def test_no_price_stop_pocket_and_buying_power_still_cap_the_notional():
    _, calls = _alpaca_no_stop_run(
        {"no_price_stop": True, "max_notional": 420.0}, remaining=250.0)
    assert calls["buy"] == [("PG", 2.0, None)], calls["buy"]   # min(420, 250) / 100
    _, calls = _alpaca_no_stop_run(
        {"no_price_stop": True, "max_notional": 420.0},
        acct=alpaca.AlpacaAccount(
            equity=100_000.0, last_equity=100_000.0, cash=150.0,
            buying_power=150.0, currency="USD", status="ACTIVE",
            pattern_day_trader=False, daytrade_count=0,
            trading_blocked=False))
    assert calls["buy"] == [("PG", 1.0, None)], calls["buy"]   # BP 150 / 100


def test_no_price_stop_in_recovery_is_half_size():
    _, calls = _alpaca_no_stop_run(
        {"no_price_stop": True, "max_notional": 420.0, "_recovery_mode": True})
    assert calls["buy"] == [("PG", 2.0, None)], calls["buy"]   # 420 * 0.5 / 100


def test_no_price_stop_without_max_notional_is_refused_not_guessed():
    out, calls = _alpaca_no_stop_run({"no_price_stop": True})
    assert calls["buy"] == [] and calls["rows"] == [] and calls["bracket"] == []
    assert len(out) == 1 and out[0].kind == "error", out
    assert out[0].payload.get("event") == "execute_error"
    assert out[0].payload.get("lane") == "stock"
    assert "max_notional" in out[0].payload.get("error", "")


def test_no_price_stop_short_is_refused():
    out, calls = _alpaca_no_stop_run(
        {"no_price_stop": True, "max_notional": 420.0}, side="short")
    assert calls["buy"] == [] and calls["rows"] == []
    assert out[0].kind == "error" and "long-only" in out[0].payload.get("error", "")


def test_no_price_stop_never_reaches_the_modeled_engine_with_a_default_stop():
    """The modeled engine cannot open without a stop; refusing beats the
    5% default it would otherwise plant (the NEQ-05 hole itself)."""
    agent = te.TradeExecutionAgent()
    opened: list = []

    async def _open_position(**kw):
        opened.append(kw)
        return load_module("app.paper.engine").FillResult(ok=True)

    with _quiet_activity_log(), _patched(te, open_position=_open_position):
        out = _run(agent._execute_internal(
            BOOK_B, "PG", "stock", "long", 100.0, None, None, "dividend_lt",
            {"no_price_stop": True, "max_notional": 420.0}))
    assert opened == [], "open_position must not run for a no-price-stop lane"
    assert out[0].kind == "error" and out[0].payload.get("event") == "execute_error"
    assert out[0].payload.get("lane") == "stock"
    assert "no_price_stop" in out[0].payload.get("error", "")


# --- alpaca.submit_market_buy: a bare buy, no legs ------------------------

def test_submit_market_buy_posts_a_bare_market_order_with_no_legs():
    posted: list = []

    async def _post(path, body, token=None):
        posted.append((path, body, token))
        return {"id": "o1"}, None

    with _patched(alpaca, _post=_post):
        order, err = _run(alpaca.submit_market_buy("pg", 4.0, token=None))
    assert err is None and order == {"id": "o1"}
    path, body, _ = posted[0]
    assert path == "/v2/orders"
    assert body == {"symbol": "PG", "qty": "4", "side": "buy",
                    "type": "market", "time_in_force": "day"}, body
    for k in ("order_class", "take_profit", "stop_loss"):
        assert k not in body


def test_submit_market_buy_refuses_a_zero_share_quantity_without_posting():
    posted: list = []

    async def _post(path, body, token=None):
        posted.append((path, body, token))
        return {"id": "o1"}, None

    with _patched(alpaca, _post=_post):
        order, err = _run(alpaca.submit_market_buy("PG", 0.4))
    assert order is None and err and posted == []


def test_every_error_and_fill_message_in_the_module_carries_a_lane():
    """Source-shape guard for the contract: each kind="error" and
    kind="execute" AgentMessage built in trade_execution carries "lane"
    in its payload dict."""
    src = inspect.getsource(te)
    starts = [m.start() for m in re.finditer(r'kind="(error|execute)"', src)]
    assert starts, "no outcome messages found?"
    for s in starts:
        window = src[s:s + 900]
        payload_start = window.find("payload=")
        assert payload_start >= 0, src[s:s + 200]
        # the payload dict ends at the first ')' that closes AgentMessage(
        depth, end = 0, None
        for i, ch in enumerate(window[payload_start:], payload_start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        assert end is not None, window[:200]
        assert '"lane"' in window[payload_start:end], \
            "outcome message without a lane:\n" + window[:end]


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars(sys.modules[__name__]))))
