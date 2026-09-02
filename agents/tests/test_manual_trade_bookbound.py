"""Guards for TE-10 and TE-18 (audit 2026-09-01): two order paths that
ran with NO account bound.

TE-10  /admin/manual-trade called TradeExecutionAgent._execute_for_user
       directly. Nothing bound the requesting book, so a manual order
       for the 25k or 75k book went to whatever the ContextVar held --
       the PRIMARY account. Its docstring also claimed the order went
       through the Risk Manager; it never did.
TE-18  The Exit Advisor's auto_exit_advisor close called
       close_position_broker_aware -> liquidate_position unbound, so an
       urgent giveback on a 25k/75k row liquidated at the primary.

Both fixes are the same shape as trade_execution's own paths:
bind_for_user(user_id) + route_guard.check_route BEFORE the broker
call; an unresolvable book is refused with a logged reason and NOTHING
is placed. These tests drive the REAL code -- the handler body pulled
out of main.py unedited, the real ExitAdvisorAgent._diagnose_and_alert
-- with only the external seams (account registry, engine close/trim,
Trade Execution submit, the bus) swapped and always restored.

Deliberately dependency-free (no pytest, no .env, no network) so the
deploy guard can run them in a bare checkout.
"""

from __future__ import annotations

import asyncio
import ast
import contextlib
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
accounts = load_module("app.brokers.accounts")
route_guard = load_module("app.brokers.route_guard")
settings_mod = load_module("app.runtime.settings")
engine = load_module("app.paper.engine")
te = load_module("app.agents.trade_execution")
bus_mod = load_module("app.runtime.bus")
ea = load_module("app.agents.exit_advisor")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module/class attributes and always put the originals back.
    run_all imports every suite into ONE process, so a leaked patch
    would poison later suites."""
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


# --- a two-book registry, no credentials read anywhere -------------------

BOOK_25K = "25k-book-user-id"
BOOK_75K = "75k-book-user-id"
UNKNOWN = "nobody-owns-this-book"

ACCT_25K = accounts.BrokerAccount(
    account_id="acct2", label="25k", owner_id="mike", account_key=BOOK_25K,
    key_id="A" * 26, secret="a" * 44)
ACCT_75K = accounts.BrokerAccount(
    account_id="acct3", label="75k", owner_id="mike", account_key=BOOK_75K,
    key_id="B" * 26, secret="b" * 44)
_BOOKS = {BOOK_25K: ACCT_25K, BOOK_75K: ACCT_75K}


def _for_user(uid):
    return _BOOKS.get(uid)


@contextlib.contextmanager
def _registry(multi=True):
    """Two known books, one unknown. route_guard imports the registry
    helpers BY NAME, so both modules are patched together."""
    with _patched(accounts, account_for_user=_for_user,
                  multi_account_active=lambda: multi), \
         _patched(route_guard, account_for_user=_for_user,
                  multi_account_active=lambda: multi):
        yield


@contextlib.contextmanager
def _mismatch_log():
    seen = []

    def _rec(ticker, user_id, note, where):
        seen.append({"ticker": ticker, "user_id": user_id,
                     "note": note, "where": where})
    with _patched(route_guard, record_mismatch=_rec):
        yield seen


class _Msg:
    def __init__(self, kind, payload=None, agent="trade_execution"):
        self.kind = kind
        self.payload = payload or {}
        self.agent = agent


# =========================================================================
# TE-10: /admin/manual-trade
# =========================================================================

def _load_manual_trade():
    """Pull the REAL admin_manual_trade body out of main.py and exec it
    against a stub logger. Importing main.py boots FastAPI + the agent
    routers, which a guard must never do; executing the handler's own
    source, unedited, is the next best thing (same trick as
    test_silent_failure_nets._load_router)."""
    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "admin_manual_trade")
    body = textwrap.dedent(ast.get_source_segment(src, node))
    logged = []

    class _Log:
        def error(self, *a, **k):
            logged.append((a, k))
        info = warning = error

    ns = {"log": _Log(), "asyncio": asyncio}
    exec(compile(body, "main.py", "exec"), ns)
    return ns["admin_manual_trade"], logged


@contextlib.contextmanager
def _exec_seam(result_kind="execute"):
    """Replace TradeExecutionAgent._execute_for_user on the REAL class
    with a recorder that notes which account was bound at the moment
    of the call -- the whole point of TE-10."""
    calls = []

    async def _fake(self, user_id, ticker, side, payload):
        calls.append({"user_id": user_id, "ticker": ticker, "side": side,
                      "bound": accounts.current_account()})
        return [_Msg(result_kind, {"ticker": ticker, "user_id": user_id,
                                   "venue": "paper", "quantity": 1,
                                   "fill_price": 10.0})]

    published = []

    class _Bus:
        async def publish(self, m):
            published.append(m)

    with _patched(te.TradeExecutionAgent, _execute_for_user=_fake), \
         _patched(bus_mod, bus=_Bus()):
        yield calls, published


def test_manual_trade_places_under_the_requested_book():
    handler, logged = _load_manual_trade()
    with _registry(multi=True), _mismatch_log() as mm, _exec_seam() as (calls, published):
        res = _run(handler(BOOK_75K, "amzn", "long"))
    assert res.get("ok") is True, res
    assert len(calls) == 1, calls
    assert calls[0]["user_id"] == BOOK_75K
    assert calls[0]["ticker"] == "AMZN"
    assert calls[0]["bound"] is ACCT_75K, (
        f"order submitted with {calls[0]['bound']!r} bound, not the 75k book")
    assert not mm, mm
    assert published and published[0].kind == "execute"
    # the binding is released after the handler returns
    assert accounts._active.get() is None


def test_manual_trade_for_a_different_book_binds_that_book():
    """Two calls, two books, two different accounts -- the ContextVar
    binding is per call, not a sticky global."""
    handler, _ = _load_manual_trade()
    with _registry(multi=True), _exec_seam() as (calls, _):
        _run(handler(BOOK_25K, "KO", "long"))
        _run(handler(BOOK_75K, "KO", "short"))
    assert [c["bound"] for c in calls] == [ACCT_25K, ACCT_75K]
    assert [c["side"] for c in calls] == ["long", "short"]


def test_manual_trade_for_an_unresolvable_book_places_nothing():
    """The failure TE-10 is about: multi-account is on, the book is not
    in the registry. Old code would have submitted on the primary."""
    handler, logged = _load_manual_trade()
    with _registry(multi=True), _mismatch_log() as mm, _exec_seam() as (calls, published):
        res = _run(handler(UNKNOWN, "AMZN", "long"))
    assert res.get("ok") is False, res
    assert "refusing" in res.get("error", ""), res
    assert calls == [], "AN ORDER WAS PLACED FOR A BOOK NOBODY OWNS"
    assert published == [], "nothing should reach the bus when refused"
    assert mm and mm[0]["where"] == "manual_trade", mm
    assert mm[0]["user_id"] == UNKNOWN
    assert logged and logged[0][0][0] == "admin.manual_trade.route_refused", logged


def test_manual_trade_single_account_mode_is_unchanged():
    """With one account there is nothing to cross; the existing
    behaviour (place it) stands. bind_for_user yields None here and
    check_route answers 'single-account'."""
    handler, _ = _load_manual_trade()
    with _registry(multi=False), _mismatch_log() as mm, _exec_seam() as (calls, _):
        res = _run(handler(UNKNOWN, "AMZN", "long"))
    assert res.get("ok") is True, res
    assert len(calls) == 1
    assert not mm


@contextlib.contextmanager
def _sizing_retry_seams():
    """The 'Sizing produced 0 shares' retry path (rv:main-exit-advisor
    coverage gap, 2026-09-01). The FIRST _execute_for_user answers with
    that exact error; the handler then reads alpaca.get_account and the
    tape, bumps risk to fit one share and submits AGAIN. TE-10 moved that
    whole block inside the binding -- this seam records which account
    was bound at the account read and at BOTH submits."""
    alpaca = load_module("app.brokers.alpaca")
    candles = load_module("app.data.candles")
    calls, reads = [], []

    async def _fake(self, user_id, ticker, side, payload):
        calls.append({"user_id": user_id, "ticker": ticker, "side": side,
                      "payload": dict(payload),
                      "bound": accounts.current_account()})
        if len(calls) == 1:
            return [_Msg("error", {"ticker": ticker, "user_id": user_id,
                                   "error": "Sizing produced 0 shares"})]
        return [_Msg("execute", {"ticker": ticker, "user_id": user_id,
                                 "venue": "paper", "quantity": 1,
                                 "fill_price": 200.0})]

    class _Acct:
        buying_power = 5_000.0
        equity = 25_000.0

    async def _get_account(token=None):
        reads.append({"bound": accounts.current_account()})
        return _Acct()

    class _Bar:
        close = 200.0

    async def _fetch(symbol, asset_type):
        return [_Bar()]

    class _Bus:
        async def publish(self, m):
            pass

    with _patched(te.TradeExecutionAgent, _execute_for_user=_fake), \
         _patched(alpaca, alpaca_configured=lambda: True, get_account=_get_account), \
         _patched(candles, fetch_candles_for=_fetch), \
         _patched(bus_mod, bus=_Bus()):
        yield calls, reads


def test_manual_trade_sizing_retry_stays_under_the_requested_book():
    """rv:main-exit-advisor (2026-09-01): the retry submit and the
    get_account read it depends on were the two broker calls TE-10 moved
    inside `with _bind_acct(user_id)`. Drive the real handler through
    that branch and check every one of them saw the 75k book bound."""
    handler, _ = _load_manual_trade()
    with _registry(multi=True), _mismatch_log() as mm, \
            _sizing_retry_seams() as (calls, reads):
        res = _run(handler(BOOK_75K, "AMZN", "long"))
    assert res.get("ok") is True, res
    assert res.get("risk_override_applied") is True, res
    assert len(calls) == 2, calls
    assert [c["bound"] for c in calls] == [ACCT_75K, ACCT_75K], (
        "the sizing retry submitted under a different account than the "
        "first attempt -- the retry escaped the binding")
    assert calls[1]["payload"].get("force_min_qty") == 1
    assert 0 < calls[1]["payload"].get("risk_pct_override", 0) <= 0.25
    assert len(reads) == 1 and reads[0]["bound"] is ACCT_75K, (
        f"buying power read from {reads!r}, not the 75k book")
    assert not mm
    assert accounts._active.get() is None


def test_manual_trade_docstring_no_longer_claims_risk_manager():
    """The old docstring promised 'Risk Manager -> Trade Execution'. It
    never went through the Risk Manager. Keep the honest version."""
    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "admin_manual_trade")
    doc = ast.get_docstring(node) or ""
    assert "BYPASSES the Risk Manager" in doc, doc
    assert "Risk\n    Manager → Trade Execution" not in doc
    assert "bind_for_user" in doc


# =========================================================================
# TE-18: Exit Advisor auto-close
# =========================================================================

class _Advisor(ea.ExitAdvisorAgent):
    """The real agent with only its Supabase alert seams silenced."""

    def __init__(self):
        self.alerts = []

    async def _has_open_alert(self, client, pid, kind):
        return False

    async def _raise_alert(self, client, **kw):
        self.alerts.append(kw)


class _Settings:
    auto_exit_advisor = True


class _Client:
    """Only the warn-path trim reads the row's broker through it."""

    def table(self, *_a, **_k):
        raise AssertionError("client must not be touched on the urgent path")


def _urgent_position(uid):
    # entry 10 x 100 = $1,000 cost; peak +$100 (10% -> 'small-win'
    # tier, urgent at 40% giveback); now +$30 = 70% given back -> URGENT.
    return {"id": "pos-1", "user_id": uid, "ticker": "AMZN", "side": "long",
            "stop_price": 0, "entry_at": None, "entry_price": 10.0,
            "quantity": 100.0}


@contextlib.contextmanager
def _engine_seam():
    closes, trims = [], []

    async def _close(user_id, position_id, market_price, reason="manual"):
        closes.append({"user_id": user_id, "position_id": position_id,
                       "price": market_price, "reason": reason,
                       "bound": accounts.current_account()})
        return engine.FillResult(ok=True)

    async def _trim(user_id, position_id, fraction=0.5, price=0.0, reason="trim"):
        trims.append({"user_id": user_id, "bound": accounts.current_account()})
        return engine.FillResult(ok=True)

    with _patched(engine, close_position_broker_aware=_close, trim_position=_trim), \
         _patched(settings_mod, get_bot_settings=lambda uid=None: _Settings()):
        yield closes, trims


def test_auto_close_runs_under_the_rows_own_book():
    adv = _Advisor()
    with _registry(multi=True), _mismatch_log() as mm, _engine_seam() as (closes, trims):
        raised = _run(adv._diagnose_and_alert(
            _Client(), _urgent_position(BOOK_25K),
            peak=100.0, peak_price=11.0, pnl=30.0, price=10.3))
    assert raised == 1 and adv.alerts and adv.alerts[0]["severity"] == "urgent", adv.alerts
    assert len(closes) == 1, "auto_exit_advisor ON + urgent must close"
    assert closes[0]["user_id"] == BOOK_25K
    assert closes[0]["bound"] is ACCT_25K, (
        f"close ran with {closes[0]['bound']!r} bound -- that is the TE-18 bug")
    assert "urgent" in closes[0]["reason"]
    assert trims == [] and not mm


def test_auto_close_for_an_unresolvable_book_is_skipped_and_logged():
    """Multi-account on, the row's book is unknown. Old code liquidated
    at the primary. Now: no close, no trim, a route_mismatch line, and
    the alert stays so Mike can act by hand."""
    adv = _Advisor()
    with _registry(multi=True), _mismatch_log() as mm, _engine_seam() as (closes, trims):
        raised = _run(adv._diagnose_and_alert(
            _Client(), _urgent_position(UNKNOWN),
            peak=100.0, peak_price=11.0, pnl=30.0, price=10.3))
    assert raised == 1 and adv.alerts, "the alert itself must still be raised"
    assert closes == [], "A POSITION ON AN UNKNOWN BOOK WAS CLOSED AT THE PRIMARY"
    assert trims == []
    assert mm and mm[0]["where"] == "exit_advisor.auto_close", mm
    assert mm[0]["user_id"] == UNKNOWN and mm[0]["ticker"] == "AMZN"


def test_auto_close_off_never_touches_the_engine():
    """auto_exit_advisor OFF is alert-only, resolved book or not."""
    adv = _Advisor()

    class _Off:
        auto_exit_advisor = False
    with _registry(multi=True), _engine_seam() as (closes, trims), \
         _patched(settings_mod, get_bot_settings=lambda uid=None: _Off()):
        raised = _run(adv._diagnose_and_alert(
            _Client(), _urgent_position(BOOK_75K),
            peak=100.0, peak_price=11.0, pnl=30.0, price=10.3))
    assert raised == 1 and closes == [] and trims == []


def test_exit_advisor_descriptions_stopped_lying():
    """Module docstring and registry text used to say the advisor never
    closes a trade. It does, when auto_exit_advisor is ON."""
    doc = ea.__doc__ or ""
    assert "NEVER closes" not in doc
    assert "auto_exit_advisor" in doc and "bind_for_user" in doc
    boot = (Path(__file__).resolve().parents[1] / "app" / "runtime"
            / "bootstrap.py").read_text(encoding="utf-8")
    line = next(l for l in boot.splitlines()
                if "registry.register(exit_adv," in l)
    assert "Never closes a trade" not in line
    assert "auto_exit_advisor" in line and "CLOSES" in line


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
