"""Guards for the book-bound reconcilers (audit 2026-09-01: TE-16, TE-17,
LT-05, KS-4).

The live proof behind these: on 2026-09-01 all three books' paper_accounts
rows read IDENTICAL cash to the cent, because the hourly balance reconcile
looped every book with NO account bound -- get_account() resolved to the
primary every time and stamped the primary's cash onto acct2 and acct3.
The orphan-option importer had the same hole (primary's contracts imported
into every book) plus a second one: it deduped only against
options_positions while the engine's real option legs live in
paper_positions(asset_type='option'), so it re-imported tracked legs
every sweep -- 232 churn rows, phantom collateral on acct3.

What these pin:
  * every broker read happens INSIDE that book's binding,
  * an unresolvable book is skipped with a logged reason (never the
    primary's numbers) -- and skipped BEFORE binding, without a
    route_mismatch record, which is reserved for a known book bound
    wrong (rv:stocks_reconcile :590),
  * a failed (None) read writes nothing -- on the stock pass too, which
    now uses the STRICT read (rv:bound-hunter :136),
  * a leg already open in the real ledger is never re-imported,
  * the integrity sweep ADOPTS before it imports, so a broker-held leg
    lands in paper_positions once, not in two tables with two managers
    (rv:stocks_reconcile :664),
  * the oversell cover names its book (rv:position_monitor :182),
  * a ghost close resets ONLY that book's reject window.

The code under test is the REAL module (loaded via _bootstrap.load_module);
only the seams -- Supabase client, account binding, route check, broker
reads, token lookup -- are swapped, and always put back. No pytest, no
.env, no network, so the deploy gate can run this in a bare checkout.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
# app.runtime must be stubbed BEFORE position_monitor imports
# app.runtime.asset_policy, or the real package __init__ boots the bus.
load_module("app.runtime.asset_policy")
alp = load_module("app.brokers.alpaca")
accounts = load_module("app.brokers.accounts")
route_guard = load_module("app.brokers.route_guard")
web_tokens = load_module("app.integrations.web_tokens")
book_scope = load_module("app.runtime.book_scope")
killswitch = load_module("app.paper.killswitch")
sr = load_module("app.paper.stocks_reconcile")
adoption = load_module("app.paper.adoption")
pm = load_module("app.agents.position_monitor")
trade_qa = load_module("app.paper.trade_qa")

import supabase  # noqa: E402  -- real package; only create_client is swapped


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


_MISSING = object()


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and always put the originals back. Sentinel
    based (rv:test-contract): a real attribute whose value is None is
    restored as None, never deleted."""
    old = {k: getattr(mod, k, _MISSING) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is _MISSING:
                if hasattr(mod, k):
                    delattr(mod, k)
            else:
                setattr(mod, k, v)


@contextlib.contextmanager
def _no_activity_files():
    """activity_log.record writes jsonl side-files unless told not to."""
    import os
    _prev = os.environ.get("TREZO_ACTIVITY_LOG")
    os.environ["TREZO_ACTIVITY_LOG"] = "0"
    try:
        yield
    finally:
        if _prev is None:
            os.environ.pop("TREZO_ACTIVITY_LOG", None)
        else:
            os.environ["TREZO_ACTIVITY_LOG"] = _prev


# --- a tiny in-memory Supabase stand-in -----------------------------------

class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.op = ("select", None)
        self.eqs: list[tuple] = []
        self.neqs: list[tuple] = []
        self.single_row = False

    def select(self, *_a, **_k):
        self.op = ("select", None)
        return self

    def update(self, payload):
        self.op = ("update", payload)
        return self

    def insert(self, payload):
        self.op = ("insert", payload)
        return self

    def eq(self, k, v):
        self.eqs.append((k, v))
        return self

    def neq(self, k, v):
        self.neqs.append((k, v))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def single(self):
        self.single_row = True
        return self

    def execute(self):
        return self.client._execute(self)


class FakeClient:
    """Rows in, writes out. Every update/insert is recorded so a test can
    assert 'nothing was written' -- the property that matters here."""

    def __init__(self, tables: dict):
        self.tables = {k: list(v) for k, v in tables.items()}
        self.writes: list[dict] = []

    def table(self, name):
        return _Query(self, name)

    def _execute(self, q: _Query):
        kind, payload = q.op
        if kind == "select":
            rows = self.tables.get(q.table_name, [])
            out = [r for r in rows
                   if all(r.get(k) == v for k, v in q.eqs)
                   and all(r.get(k) != v for k, v in q.neqs)]
            if q.single_row:
                return _Resp(out[0] if out else None)
            return _Resp(out)
        self.writes.append({"table": q.table_name, "op": kind,
                            "payload": payload, "eq": list(q.eqs)})
        return _Resp([payload] if kind == "insert" else [])


async def _no_token(user_id, broker):
    return None


class _Acct:
    def __init__(self, cash):
        self.cash = cash
        self.account_number = f"PA{int(cash)}"


class _Binder:
    """Records which book is bound while a broker read runs. bind_for_user
    is a contextmanager in the real module; this one is too."""

    def __init__(self):
        self.bound = None
        self.seen: list[str] = []

    @contextlib.contextmanager
    def __call__(self, user_id):
        self.seen.append(str(user_id))
        prev, self.bound = self.bound, str(user_id)
        try:
            yield str(user_id)
        finally:
            self.bound = prev


# --- TE-16: balance reconcile ------------------------------------------------

UIDS = ["primary-book", "acct2-book", "acct3-book"]
BROKER_CASH = {"primary-book": 5000.0, "acct2-book": 25000.0,
               "acct3-book": 75000.0}


def _balance_tables():
    return {"paper_accounts": [
        {"user_id": u, "current_cash_usd": 1.0} for u in UIDS]}


def test_each_book_reads_its_own_cash_under_its_own_binding():
    """THE 2026-09-01 symptom: three books, one number. Each read must run
    inside that book's binding and each write must carry the value read
    under it -- not the primary's."""
    binder = _Binder()
    reads: list[tuple] = []

    async def _get_account(token=None):
        # the read is only meaningful if it happens while bound
        assert binder.bound is not None, "get_account called UNBOUND"
        reads.append((binder.bound, token))
        return _Acct(BROKER_CASH[binder.bound])

    client = FakeClient(_balance_tables())
    with _patched(supabase, create_client=lambda *_a, **_k: client), \
         _patched(accounts, bind_for_user=binder), \
         _patched(route_guard, check_route=lambda uid: (True, "ok"),
                  record_mismatch=lambda *a, **k: None), \
         _patched(alp, get_account=_get_account,
                  alpaca_configured=lambda: True), \
         _patched(web_tokens, get_user_broker_token=_no_token):
        out = _run(sr.reconcile_account_balances_all_users())

    assert out["ok"], out
    assert binder.seen == UIDS, binder.seen
    assert [r[0] for r in reads] == UIDS, reads
    written = {w["eq"][0][1]: w["payload"]["current_cash_usd"]
               for w in client.writes if w["table"] == "paper_accounts"}
    assert written == BROKER_CASH, written
    assert out["synced"] == 3, out


def test_a_failed_bound_read_writes_nothing_for_that_book():
    """None from the broker is ANSWERLESS. The other books still sync."""
    binder = _Binder()

    async def _get_account(token=None):
        if binder.bound == "acct2-book":
            return None                       # 429 / timeout / 5xx
        return _Acct(BROKER_CASH[binder.bound])

    client = FakeClient(_balance_tables())
    with _patched(supabase, create_client=lambda *_a, **_k: client), \
         _patched(accounts, bind_for_user=binder), \
         _patched(route_guard, check_route=lambda uid: (True, "ok"),
                  record_mismatch=lambda *a, **k: None), \
         _patched(alp, get_account=_get_account,
                  alpaca_configured=lambda: True), \
         _patched(web_tokens, get_user_broker_token=_no_token):
        out = _run(sr.reconcile_account_balances_all_users())

    touched = [w["eq"][0][1] for w in client.writes]
    assert "acct2-book" not in touched, touched
    assert sorted(touched) == ["acct3-book", "primary-book"], touched
    assert {s["user_id"] for s in out["skipped"]} == {"acct2-book"}, out


def test_an_unresolvable_book_is_skipped_and_logged_never_defaulted():
    """route_guard refuses acct3: no read, no write, one loud mismatch
    record naming the book. The primary's cash must NOT land on it."""
    binder = _Binder()
    reads: list[str] = []
    mismatches: list[tuple] = []

    async def _get_account(token=None):
        reads.append(binder.bound)
        return _Acct(BROKER_CASH.get(binder.bound, 5000.0))

    def _check(uid):
        if uid == "acct3-book":
            return False, "unknown book acct3-bo -- refusing"
        return True, "ok"

    client = FakeClient(_balance_tables())
    with _patched(supabase, create_client=lambda *_a, **_k: client), \
         _patched(accounts, bind_for_user=binder), \
         _patched(route_guard, check_route=_check,
                  record_mismatch=lambda t, uid, note, where:
                  mismatches.append((uid, note, where))), \
         _patched(alp, get_account=_get_account,
                  alpaca_configured=lambda: True), \
         _patched(web_tokens, get_user_broker_token=_no_token):
        out = _run(sr.reconcile_account_balances_all_users())

    assert "acct3-book" not in reads, reads
    touched = [w["eq"][0][1] for w in client.writes]
    assert "acct3-book" not in touched, touched
    assert mismatches and mismatches[0][0] == "acct3-book", mismatches
    assert mismatches[0][2] == "balance_reconcile", mismatches
    assert out["skipped"] == [{"user_id": "acct3-book",
                               "reason": "unknown book acct3-bo -- refusing"}]


# --- TE-17 + LT-05: orphan option import --------------------------------------

OCC_TRACKED = "AGNC260918P00010500"      # already open in paper_positions
OCC_ORPHAN = "PG260918P00138000"         # genuinely untracked


def _orphan_tables(ledger_rows=None):
    return {
        "paper_accounts": [{"user_id": "acct3-book"}],
        "options_positions": [],
        "paper_positions": ledger_rows if ledger_rows is not None else [
            {"user_id": "acct3-book", "ticker": OCC_TRACKED,
             "status": "open", "asset_type": "option"},
        ],
    }


def _broker_rows():
    return [
        {"symbol": OCC_TRACKED, "asset_class": "us_option", "qty": "-2",
         "avg_entry_price": "0.05"},
        {"symbol": OCC_ORPHAN, "asset_class": "us_option", "qty": "-1",
         "avg_entry_price": "1.20"},
    ]


def test_a_leg_open_in_the_real_ledger_is_never_reimported():
    """LT-05 replay: AGNC is tracked in paper_positions (asset_type=option),
    options_positions is empty. Only PG -- the true orphan -- is inserted."""
    binder = _Binder()

    async def _opts(token=None):
        assert binder.bound == "acct3-book", "option read UNBOUND"
        return _broker_rows()

    client = FakeClient(_orphan_tables())
    with _patched(supabase, create_client=lambda *_a, **_k: client), \
         _patched(accounts, bind_for_user=binder), \
         _patched(route_guard, check_route=lambda uid: (True, "ok"),
                  record_mismatch=lambda *a, **k: None), \
         _patched(alp, get_option_positions_strict=_opts,
                  alpaca_configured=lambda: True), \
         _patched(web_tokens, get_user_broker_token=_no_token):
        out = _run(sr.import_orphan_options_all_users())

    inserts = [w for w in client.writes if w["op"] == "insert"]
    assert len(inserts) == 1, inserts
    row = inserts[0]["payload"]
    assert inserts[0]["table"] == "options_positions"
    assert row["underlying"] == "PG" and row["strategy"] == "wheel_csp", row
    assert row["user_id"] == "acct3-book", row
    assert OCC_TRACKED not in row["notes"]
    assert out["imported"] == 1, out


def test_a_ledger_leg_matches_by_contract_key_not_just_ticker_spelling():
    """Same contract, ledger ticker in lower case: still tracked."""
    binder = _Binder()

    async def _opts(token=None):
        return [_broker_rows()[0]]

    client = FakeClient(_orphan_tables(ledger_rows=[
        {"user_id": "acct3-book", "ticker": OCC_TRACKED.lower(),
         "status": "open", "asset_type": "option"}]))
    with _patched(supabase, create_client=lambda *_a, **_k: client), \
         _patched(accounts, bind_for_user=binder), \
         _patched(route_guard, check_route=lambda uid: (True, "ok"),
                  record_mismatch=lambda *a, **k: None), \
         _patched(alp, get_option_positions_strict=_opts,
                  alpaca_configured=lambda: True), \
         _patched(web_tokens, get_user_broker_token=_no_token):
        out = _run(sr.import_orphan_options_all_users())
    assert client.writes == [], client.writes
    assert out["imported"] == 0, out


def test_a_failed_option_read_imports_nothing():
    """None is answerless. Nothing is inserted, and the report says why."""
    binder = _Binder()

    async def _opts(token=None):
        return None

    client = FakeClient(_orphan_tables())
    with _patched(supabase, create_client=lambda *_a, **_k: client), \
         _patched(accounts, bind_for_user=binder), \
         _patched(route_guard, check_route=lambda uid: (True, "ok"),
                  record_mismatch=lambda *a, **k: None), \
         _patched(alp, get_option_positions_strict=_opts,
                  alpaca_configured=lambda: True), \
         _patched(web_tokens, get_user_broker_token=_no_token):
        out = _run(sr.import_orphan_options_all_users())
    assert client.writes == [], client.writes
    assert out["imported"] == 0
    assert out["details"] == [{"user_id": "acct3-book",
                               "skipped": "broker read failed"}], out


def test_orphan_import_skips_an_unresolvable_book_without_reading():
    binder = _Binder()
    reads = {"n": 0}

    async def _opts(token=None):
        reads["n"] += 1
        return _broker_rows()

    client = FakeClient(_orphan_tables())
    with _patched(supabase, create_client=lambda *_a, **_k: client), \
         _patched(accounts, bind_for_user=binder), \
         _patched(route_guard,
                  check_route=lambda uid: (False, "bound primary but book "
                                                  "acct3-bo belongs to acct3"),
                  record_mismatch=lambda *a, **k: None), \
         _patched(alp, get_option_positions_strict=_opts,
                  alpaca_configured=lambda: True), \
         _patched(web_tokens, get_user_broker_token=_no_token):
        out = _run(sr.import_orphan_options_all_users())
    assert reads["n"] == 0, "read the broker for a book it could not bind"
    assert client.writes == [], client.writes
    assert out["details"][0]["user_id"] == "acct3-book"
    assert "belongs to acct3" in out["details"][0]["skipped"], out


def test_the_wrong_table_drift_detector_is_gone():
    """It had zero call sites and read options_positions (always empty).
    A detector pointed at the wrong table reports confidently and wrongly;
    broker_truth.py is the real one."""
    assert not hasattr(sr, "detect_option_drift_all_users")


# --- KS-4: the ghost-close reset is per book ---------------------------------

def test_a_ghost_close_resets_only_that_books_reject_window():
    """Broker holds AMZN; ledger holds AMZN + SOFI. SOFI is a ghost and is
    closed; the reject reset that follows must name THIS book, not wipe
    every book's window."""
    resets: list = []

    async def _positions(token=None):
        return [{"symbol": "AMZN", "asset_class": "us_equity", "qty": "1",
                 "avg_entry_price": "100"}]

    async def _no_orders(sym, token=None):
        return []

    client = FakeClient({
        "paper_accounts": [{"user_id": "acct2-book"}],
        "paper_positions": [
            {"id": 1, "user_id": "acct2-book", "ticker": "AMZN",
             "side": "long", "quantity": 1, "entry_price": 100,
             "status": "open", "asset_type": "stock"},
            {"id": 2, "user_id": "acct2-book", "ticker": "SOFI",
             "side": "long", "quantity": 5, "entry_price": 10,
             "status": "open", "asset_type": "stock"},
        ],
    })
    import os
    _prev = os.environ.get("TREZO_ACTIVITY_LOG")
    os.environ["TREZO_ACTIVITY_LOG"] = "0"      # no jsonl side-files
    try:
        with _patched(supabase, create_client=lambda *_a, **_k: client), \
             _patched(trade_qa, has_working_order=lambda uid, sym, side=None: False), \
             _patched(accounts, set_account_for_user=lambda uid: True,
                      should_skip_unresolved=lambda uid: False), \
             _patched(book_scope, verify=lambda uid: (True, "ok"),
                      invalidate=lambda uid=None: None), \
             _patched(alp, get_positions_strict=_positions,
                      get_recent_closed_orders=_no_orders,
                      alpaca_configured=lambda: True), \
             _patched(killswitch,
                      reset_broker_rejects=lambda user_id=None:
                      resets.append(user_id)), \
             _patched(web_tokens, get_user_broker_token=_no_token):
            out = _run(sr.reconcile_stocks_all_users())
    finally:
        if _prev is None:
            os.environ.pop("TREZO_ACTIVITY_LOG", None)
        else:
            os.environ["TREZO_ACTIVITY_LOG"] = _prev

    assert out["closed"] == 1, out
    closes = [w for w in client.writes if w["op"] == "update"
              and w["payload"].get("status") == "closed_manual"]
    assert [w["eq"][0][1] for w in closes] == [2], closes
    assert resets == ["acct2-book"], resets


def test_reset_broker_rejects_with_a_book_leaves_other_books_alone():
    """The consumer side of KS-4, on the real killswitch: clearing one
    book's window must not touch another's or the unattributed bucket."""
    ts = killswitch._broker_reject_ts
    saved = {k: list(v) for k, v in ts.items()}
    try:
        ts.clear()
        ts["acct2-book"] = [1.0, 2.0]
        ts["primary-book"] = [3.0]
        ts[""] = [4.0]
        killswitch.reset_broker_rejects("acct2-book")
        assert "acct2-book" not in ts
        assert ts["primary-book"] == [3.0] and ts[""] == [4.0], dict(ts)
    finally:
        ts.clear()
        ts.update(saved)


# --- rv:stocks_reconcile :590 -- unresolved books skip BEFORE binding ---------

def test_balance_reconcile_skips_an_unresolved_book_before_binding_quietly():
    """A sim / paper-only paper_accounts row under multi-account is not a
    book. It is skipped before bind_for_user, with a plain reason and NO
    route_mismatch record -- that record is for a known book bound wrong
    and was firing hourly for every such row."""
    binder = _Binder()
    reads: list = []
    mismatches: list = []

    async def _get_account(token=None):
        reads.append(binder.bound)
        return _Acct(BROKER_CASH.get(binder.bound, 5000.0))

    client = FakeClient({"paper_accounts": [
        {"user_id": u, "current_cash_usd": 1.0}
        for u in ["primary-book", "sim-row"]]})
    with _patched(supabase, create_client=lambda *_a, **_k: client), \
         _patched(accounts, bind_for_user=binder,
                  should_skip_unresolved=lambda uid: uid == "sim-row"), \
         _patched(route_guard, check_route=lambda uid: (True, "ok"),
                  record_mismatch=lambda t, uid, note, where:
                  mismatches.append((uid, where))), \
         _patched(alp, get_account=_get_account,
                  alpaca_configured=lambda: True), \
         _patched(web_tokens, get_user_broker_token=_no_token):
        out = _run(sr.reconcile_account_balances_all_users())

    assert binder.seen == ["primary-book"], binder.seen
    assert reads == ["primary-book"], reads
    assert mismatches == [], mismatches
    assert out["skipped"] == [{"user_id": "sim-row",
                               "reason": "unresolved book"}], out
    touched = [w["eq"][0][1] for w in client.writes]
    assert touched == ["primary-book"], touched


def test_orphan_import_skips_an_unresolved_book_before_binding_quietly():
    binder = _Binder()
    reads = {"n": 0}
    mismatches: list = []

    async def _opts(token=None):
        reads["n"] += 1
        return _broker_rows()

    client = FakeClient({"paper_accounts": [{"user_id": "sim-row"}],
                         "options_positions": [], "paper_positions": []})
    with _patched(supabase, create_client=lambda *_a, **_k: client), \
         _patched(accounts, bind_for_user=binder,
                  should_skip_unresolved=lambda uid: uid == "sim-row"), \
         _patched(route_guard, check_route=lambda uid: (True, "ok"),
                  record_mismatch=lambda t, uid, note, where:
                  mismatches.append((uid, where))), \
         _patched(alp, get_option_positions_strict=_opts,
                  alpaca_configured=lambda: True), \
         _patched(web_tokens, get_user_broker_token=_no_token):
        out = _run(sr.import_orphan_options_all_users())
    assert binder.seen == [] and reads["n"] == 0, (binder.seen, reads)
    assert mismatches == [] and client.writes == []
    assert out["details"] == [{"user_id": "sim-row",
                               "skipped": "unresolved book"}], out


# --- rv:bound-hunter :136 -- the stock pass reads STRICT ----------------------

def _stock_tables(uid="acct2-book"):
    return {
        "paper_accounts": [{"user_id": uid}],
        "paper_positions": [
            {"id": 1, "user_id": uid, "ticker": "AMZN", "side": "long",
             "quantity": 1, "entry_price": 100, "status": "open",
             "asset_type": "stock"},
            {"id": 2, "user_id": uid, "ticker": "SOFI", "side": "long",
             "quantity": 5, "entry_price": 10, "status": "open",
             "asset_type": "stock"},
        ],
    }


@contextlib.contextmanager
def _stock_seams(client, positions, **alp_extra):
    async def _no_orders(sym, token=None):
        return []

    # 2026-09-02, the QA shield: stocks_reconcile now asks trade_qa whether
    # an ENTRY order for this symbol is still working before it treats
    # "not at the broker" as a close, and it skips the close on True AND on
    # None. False is "checked, nothing in flight" -- the condition under
    # which every close below is the correct outcome, and the one production
    # is in whenever the 5-minute shield refresh has run. The shield's own
    # behaviour is asserted separately, in the two tests below this file's
    # ghost-close cases.
    with _no_activity_files(), \
         _patched(trade_qa, has_working_order=lambda uid, sym, side=None: False), \
         _patched(supabase, create_client=lambda *_a, **_k: client), \
         _patched(accounts, set_account_for_user=lambda uid: True,
                  should_skip_unresolved=lambda uid: False), \
         _patched(book_scope, verify=lambda uid: (True, "ok"),
                  invalidate=lambda uid=None: None), \
         _patched(alp, get_positions_strict=positions,
                  get_recent_closed_orders=_no_orders,
                  alpaca_configured=lambda: True, **alp_extra), \
         _patched(killswitch, reset_broker_rejects=lambda user_id=None: None), \
         _patched(web_tokens, get_user_broker_token=_no_token):
        yield


def test_a_failed_stock_read_skips_the_book_and_closes_nothing():
    """None is 'the read FAILED'. Before this the display read turned a
    429 into [] and only trust_close stood between it and a phantom
    close; now the book is skipped with a reason and nothing is written."""
    async def _none(token=None):
        return None

    client = FakeClient(_stock_tables())
    with _stock_seams(client, _none):
        out = _run(sr.reconcile_stocks_all_users())
    assert client.writes == [], client.writes
    assert out["closed"] == 0 and out["users_touched"] == 0, out
    assert out["skipped"] == [{"user_id": "acct2-book",
                               "reason": "broker read failed"}], out


def test_a_working_buy_order_stops_the_ghost_close():
    """THE SHIELD, bound at stocks_reconcile. trust_close only proves the
    positions read was non-empty; it never asks whether an order for this
    symbol is still in flight. A buy that has not filled yet looks exactly
    like a position that is gone."""
    async def _strict(token=None):
        return [{"symbol": "AMZN", "asset_class": "us_equity", "qty": "1",
                 "avg_entry_price": "100"}]

    client = FakeClient(_stock_tables())
    with _stock_seams(client, _strict), \
            _patched(trade_qa, has_working_order=lambda uid, sym, side=None: True):
        out = _run(sr.reconcile_stocks_all_users())
    assert out["closed"] == 0, out
    assert client.writes == [], client.writes


def test_an_unanswerable_shield_also_stops_the_ghost_close():
    """None means COULD NOT CHECK. Read as False it is a green light, and
    that is the reasoning that closed DOT seven times (house rule 3)."""
    async def _strict(token=None):
        return [{"symbol": "AMZN", "asset_class": "us_equity", "qty": "1",
                 "avg_entry_price": "100"}]

    client = FakeClient(_stock_tables())
    with _stock_seams(client, _strict), \
            _patched(trade_qa, has_working_order=lambda uid, sym, side=None: None):
        out = _run(sr.reconcile_stocks_all_users())
    assert out["closed"] == 0, out
    assert client.writes == [], client.writes


def test_the_stock_pass_never_calls_the_collapsing_read():
    """Patch the display read to explode: the pass must not reach it."""
    async def _boom(token=None):
        raise AssertionError("get_positions() (non-strict) was called")

    async def _strict(token=None):
        return [{"symbol": "AMZN", "asset_class": "us_equity", "qty": "1",
                 "avg_entry_price": "100"}]

    client = FakeClient(_stock_tables())
    with _stock_seams(client, _strict, get_positions=_boom):
        out = _run(sr.reconcile_stocks_all_users())
    assert out["closed"] == 1, out          # SOFI is a real ghost


# --- rv:position_monitor :182 -- the oversell cover names its book -----------

def test_the_oversell_cover_is_throttled_under_the_rows_own_book():
    """A negative stock qty at the broker is covered through
    _throttled_liquidate; the call must carry THIS book's user_id so the
    BI-05 throttle slot is the book's own, not the ContextVar's."""
    calls: list = []

    async def _neg(token=None):
        return [{"symbol": "DRAM", "asset_class": "us_equity", "qty": "-2",
                 "avg_entry_price": "20"}]

    async def _no_open(path, token=None):
        return []

    async def _liq(symbol, asset_type="stock", user_id=None):
        calls.append((symbol, asset_type, user_id))
        return {"id": "cover"}, "ok"

    client = FakeClient(_stock_tables(uid="acct3-book"))
    with _stock_seams(client, _neg, _get=_no_open), \
         _patched(pm, _throttled_liquidate=_liq):
        out = _run(sr.reconcile_stocks_all_users())
    assert calls == [("DRAM", "stock", "acct3-book")], calls
    assert out["closed"] == 0, "a short is never reconciled as a long row"


# --- rv:stocks_reconcile :664 -- the sweep adopts BEFORE it imports ----------

def test_the_integrity_sweep_adopts_before_it_imports_orphans():
    """Drives the real run_integrity_sweep and the real orphan importer.
    Adoption (stubbed at its seam) writes the broker-held leg into
    paper_positions FIRST; the importer then sees the ledger row and
    imports nothing into options_positions -- one contract, one manager."""
    import os
    order: list = []
    binder = _Binder()
    client = FakeClient({
        "paper_accounts": [{"user_id": "acct3-book"}],
        "options_positions": [],
        "paper_positions": [],
    })

    async def _balances():
        order.append("balances")
        return {"ok": True, "synced": 0}

    async def _stocks():
        order.append("stocks")
        return {"ok": True, "closed": 0}

    async def _adopt(*, dry_run=False):
        order.append("adopted")
        client.tables["paper_positions"].append(
            {"user_id": "acct3-book", "ticker": OCC_ORPHAN,
             "status": "open", "asset_type": "option"})
        return {"ok": True, "adopted": 1}

    async def _opts(token=None):
        order.append("options-read")
        return [_broker_rows()[1]]            # the PG contract only

    _prev = os.environ.get("TREZO_ADOPT_ORPHANS")
    os.environ["TREZO_ADOPT_ORPHANS"] = "1"
    try:
        with _patched(sr, reconcile_account_balances_all_users=_balances,
                      reconcile_stocks_all_users=_stocks), \
             _patched(adoption, adopt_all_books=_adopt), \
             _patched(supabase, create_client=lambda *_a, **_k: client), \
             _patched(accounts, bind_for_user=binder), \
             _patched(route_guard, check_route=lambda uid: (True, "ok"),
                      record_mismatch=lambda *a, **k: None), \
             _patched(alp, get_option_positions_strict=_opts,
                      alpaca_configured=lambda: True), \
             _patched(web_tokens, get_user_broker_token=_no_token):
            out = _run(sr.run_integrity_sweep())
    finally:
        if _prev is None:
            os.environ.pop("TREZO_ADOPT_ORPHANS", None)
        else:
            os.environ["TREZO_ADOPT_ORPHANS"] = _prev

    assert order == ["balances", "stocks", "adopted", "options-read"], order
    assert list(out) == ["ok", "balances", "stocks", "adopted", "options"], list(out)
    assert out["options"]["imported"] == 0, out["options"]
    inserts = [w for w in client.writes if w["op"] == "insert"]
    assert inserts == [], "the adopted leg was imported a second time"


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))


# --- 2026-09-02: a TRACKED short is held, not a phantom and not a double-sell

def test_a_tracked_short_is_held_not_closed_and_not_covered():
    """XLF/XLP: side='short' ledger rows against a NEGATIVE broker quantity
    were popped out of the holdings map, read as 'broker no longer holds
    it', closed with P/L unknown, and re-adopted -- every hour. They must
    read as HELD, and the oversell cover must leave them alone."""
    calls: list = []

    async def _short(token=None):
        return [{"symbol": "XLF", "asset_class": "us_equity", "qty": "-340",
                 "avg_entry_price": "57.53"}]

    async def _liq(symbol, asset_type="stock", user_id=None):
        calls.append((symbol, asset_type, user_id))
        return {"id": "cover"}, "ok"

    tables = {
        "paper_accounts": [{"user_id": "acct3-book"}],
        "paper_positions": [
            {"id": 7, "user_id": "acct3-book", "ticker": "XLF", "side": "short",
             "quantity": 340, "entry_price": 57.53, "status": "open",
             "asset_type": "stock"},
        ],
    }
    client = FakeClient(tables)
    with _stock_seams(client, _short), _patched(pm, _throttled_liquidate=_liq):
        out = _run(sr.reconcile_stocks_all_users())
    assert out["closed"] == 0, out
    assert calls == [], f"a tracked short must not be covered: {calls}"
    assert all("closed" not in str(w).lower() for w in client.writes), client.writes


def test_an_untracked_negative_quantity_is_still_covered():
    """The DRAM -2 case the guard was written for: no ledger row -> cover."""
    calls: list = []

    async def _neg(token=None):
        return [{"symbol": "DRAM", "asset_class": "us_equity", "qty": "-2",
                 "avg_entry_price": "20"}]

    async def _no_open(path, token=None):
        return []

    async def _liq(symbol, asset_type="stock", user_id=None):
        calls.append((symbol, asset_type, user_id))
        return {"id": "cover"}, "ok"

    client = FakeClient(_stock_tables(uid="acct3-book"))
    with _stock_seams(client, _neg, _get=_no_open), _patched(pm, _throttled_liquidate=_liq):
        _run(sr.reconcile_stocks_all_users())
    assert calls == [("DRAM", "stock", "acct3-book")], calls


def test_a_long_row_is_not_matched_by_a_short_broker_quantity():
    """Side-aware lookup: a NEGATIVE broker qty never 'holds' a LONG row."""
    async def _short(token=None):
        return [{"symbol": "AMZN", "asset_class": "us_equity", "qty": "-1",
                 "avg_entry_price": "100"},
                {"symbol": "XLF", "asset_class": "us_equity", "qty": "5",
                 "avg_entry_price": "57"}]

    async def _no_open(path, token=None):
        return []

    calls: list = []

    async def _liq(symbol, asset_type="stock", user_id=None):
        calls.append(symbol)
        return {"id": "cover"}, "ok"

    client = FakeClient(_stock_tables())   # AMZN long 1, SOFI long 5, no short rows
    with _stock_seams(client, _short, _get=_no_open), _patched(pm, _throttled_liquidate=_liq):
        out = _run(sr.reconcile_stocks_all_users())
    assert "AMZN" in calls                    # untracked negative -> covered
    assert out["closed"] >= 1                 # AMZN long row is NOT held by -1 -> ghost-closed
