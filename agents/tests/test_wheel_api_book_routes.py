"""Drive actual Wheel HTTP bodies without booting runtime or submitting orders."""
from __future__ import annotations

import asyncio
import ast
from contextlib import ExitStack, contextmanager
from datetime import date, timedelta
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config
stub_config()
accounts = load_module("app.brokers.accounts")
alpaca = load_module("app.brokers.alpaca")
active = load_module("app.brokers.active")
routes = load_module("app.brokers.book_routes")
scanner = load_module("app.agents.options_scanner")
kill = load_module("app.paper.killswitch")


def book(slot="primary", url="https://paper-api.alpaca.markets"):
    marker = "A" if slot == "primary" else "B"
    return accounts.BrokerAccount(slot, slot, "test-owner", "book-"+marker,
                                   marker*26, marker.lower()*44, url)


async def no_token(*args):
    return None


@contextmanager
def transport(books):
    cfg = SimpleNamespace(alpaca_api_key="", alpaca_secret_key="",
                           alpaca_base_url="https://paper-api.alpaca.markets",
                           trezo_default_account="primary")
    with ExitStack() as patches:
        patches.enter_context(patch.object(accounts, "load_accounts", lambda: books))
        patches.enter_context(patch.object(accounts, "get_settings", lambda: cfg))
        patches.enter_context(patch.object(alpaca, "get_settings", lambda: cfg))
        patches.enter_context(patch.object(alpaca, "_live_active", lambda: False))
        patches.enter_context(patch.dict(sys.modules, {"app.integrations.web_tokens":
                                                       SimpleNamespace(get_user_broker_token=no_token)}))
        yield


def handlers():
    source = (Path(__file__).resolve().parents[1]/"app"/"main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"wheel_live_quotes", "_wheel_live_quotes_for", "wheel_positions",
             "_wheel_positions_for", "wheel_reconcile", "_wheel_reconcile_for", "wheel_place_leg"}
    namespace = {}
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name in names:
            exec(compile(ast.get_source_segment(source, node), "actual_wheel_handler", "exec"), namespace)
    assert names <= namespace.keys()
    return namespace


def test_active_snapshot_reaches_lone_secondary_without_any_primary_credentials():
    secondary = book("acct2")
    calls = []
    async def read(token=None):
        calls.append((accounts.bound_account().account_key, alpaca._headers_for(token)))
        return alpaca.AlpacaAccount(1200, 1200, 400, 400, "USD", "ACTIVE", False, 0, False)
    with transport([secondary]), patch.object(alpaca, "get_account", read):
        assert asyncio.run(active.active_broker_name(secondary.account_key)) == "alpaca"
        snapshot = asyncio.run(active.active_broker_snapshot(secondary.account_key))
        assert snapshot.equity == 1200
        assert asyncio.run(active.active_broker_name("unknown")) == "modeled"
        assert asyncio.run(active.active_broker_snapshot("unknown")) is None
    assert calls == [(secondary.account_key, secondary.headers())]
    assert accounts.bound_account() is None


def test_all_wheel_handlers_refuse_absent_unknown_and_nonpaper_books_before_io():
    functions = handlers()
    async def forbidden(*args, **kwargs):
        raise AssertionError("unresolved book must not reach any broker or reconciliation")
    with transport([book()]):
        for name in ("_wheel_live_quotes_for", "_wheel_positions_for", "_wheel_reconcile_for"):
            functions[name] = forbidden
        for user_id in ("", "unknown"):
            outputs = [asyncio.run(functions["wheel_live_quotes"]("AMD", user_id)),
                       asyncio.run(functions["wheel_positions"](user_id)),
                       asyncio.run(functions["wheel_reconcile"](user_id)),
                       asyncio.run(functions["wheel_place_leg"](user_id, "cc", "AMD", 100,
                                       (date.today()+timedelta(days=7)).isoformat()))]
            assert all(result.get("error") for result in outputs)
    invalid = book("acct2", "https://api.alpaca.markets")
    with transport([invalid]):
        result = asyncio.run(functions["wheel_positions"](invalid.account_key))
        assert result["configured"] is False and "paper" in result["error"]


def test_position_reads_use_selected_key_and_restore_outer_book():
    first, second = book(), book("acct2")
    functions, calls = handlers(), []
    async def get(path, token=None):
        calls.append((path, accounts.bound_account().account_key, alpaca._headers_for(token)))
        await asyncio.sleep(0)
        assert accounts.bound_account().account_key == second.account_key
        return []
    with transport([first, second]), patch.object(alpaca, "_get", get), accounts.use_account(first):
        result = asyncio.run(functions["wheel_positions"](second.account_key))
        assert result["configured"] is True and result["options"] == []
        assert accounts.bound_account() == first
    assert calls == [("/v2/positions", second.account_key, second.headers())]


def test_quotes_and_reconciliation_forward_only_the_explicit_selected_book():
    first, second = book(), book("acct2")
    functions, calls = handlers(), []
    receipts = []
    async def quotes(symbols, user_id):
        calls.append(("quotes", user_id, accounts.bound_account().account_key))
        return {"configured": True}
    async def reconcile(self, client, *, user_id=None):
        calls.append(("reconcile", user_id, accounts.bound_account().account_key))
        return receipts
    functions["_wheel_live_quotes_for"] = quotes
    cfg = SimpleNamespace(supabase_url="https://example.invalid",supabase_service_role_key="test-placeholder")
    config = sys.modules["app.config"]
    with transport([first, second]), patch.object(config,"get_settings",lambda:cfg), \
         patch.dict(sys.modules, {"supabase":SimpleNamespace(create_client=lambda *args:object())}), \
         patch.object(scanner.OptionsScannerAgent,"_reconcile_with_broker",reconcile):
        assert asyncio.run(functions["wheel_live_quotes"]("AMD",second.account_key))["configured"]
        assert asyncio.run(functions["wheel_reconcile"](second.account_key))["ok"]
        receipts.append(SimpleNamespace(kind="info", payload={"user_id": second.account_key,
                        "status": "failed", "reason": "broker positions unreadable"}))
        failure = asyncio.run(functions["wheel_reconcile"](second.account_key))
        assert failure["ok"] is False and failure["error"] == "broker positions unreadable"
    assert calls == [("quotes",second.account_key,second.account_key),
                     ("reconcile",second.account_key,second.account_key),
                     ("reconcile",second.account_key,second.account_key)]


def test_manual_route_preserves_limit_checks_own_risk_and_returns_single_tracking_receipt():
    first, second = book(), book("acct2")
    functions, calls = handlers(), []
    states = {first.account_key:kill.KillSwitch(True,"day","test halt"),
              second.account_key:kill.KillSwitch(False,None,None)}
    daily = {first.account_key}
    async def brakes(client): return states
    async def dollars(client): return daily
    async def checked(self, user_id, underlying, leg, strategy, priced, **kwargs):
        calls.append((user_id, accounts.bound_account().account_key, kwargs))
        assert kwargs["manual"] is True and kwargs["limit_price"] == 1.25
        return SimpleNamespace(payload={"event":"wheel_auto_placed", "routed_via":"env-keys",
               "contracts":1,"strike":101,"expiration":leg.expiration,
               "premium_per_share":1.3,"occ":"AMD261218C00101000", "alpaca_order_id":"test-order",
               "alpaca_order_status":"accepted"})
    args=(second.account_key,"cc","AMD",100,(date.today()+timedelta(days=7)).isoformat())
    with transport([first,second]), patch.object(scanner,"_supabase",lambda:object()), \
         patch.object(scanner,"_book_kill_states",brakes),patch.object(kill,"daily_dollar_over",dollars), \
         patch.object(scanner.OptionsScannerAgent,"_wheel_auto_fire",checked),accounts.use_account(first):
        success=asyncio.run(functions["wheel_place_leg"](*args,contracts=2,limit_price=1.25))
        assert success["ok"] is True and success["recorded"] is True
        assert success["contracts"] == 1 and success["strike"] == 101
        assert accounts.bound_account() == first
        del states[second.account_key]
        assert asyncio.run(functions["wheel_place_leg"](*args))["ok"] is False
        states[second.account_key]=kill.KillSwitch(True,"day","own halt")
        assert "own halt" in asyncio.run(functions["wheel_place_leg"](*args))["error"]
        states[second.account_key]=kill.KillSwitch(False,None,None)
        daily.add(second.account_key)
        assert asyncio.run(functions["wheel_place_leg"](*args))["ok"] is False
        daily.clear()
        assert asyncio.run(functions["wheel_place_leg"](*args,contracts=0))["ok"] is False
        assert asyncio.run(functions["wheel_place_leg"](*args,limit_price=float("nan")))["ok"] is False
    assert len(calls) == 1 and calls[0][:2] == (second.account_key,second.account_key)


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
