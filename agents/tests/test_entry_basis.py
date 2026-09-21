"""Broker entry receipts must replace quote estimates with explicit provenance."""
from __future__ import annotations

import ast
import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config

stub_config()
eb = load_module("app.brokers.entry_basis")
NOW = datetime(2026, 9, 18, 14, tzinfo=timezone.utc)


def _receipt(**changes):
    return {"id": "entry-1", "symbol": "SOL/USD", "side": "buy",
            "status": "filled", "filled_qty": "2", "filled_avg_price": "105.5",
            "filled_at": NOW.isoformat(), **changes}


def _basis(order=None, **changes):
    kwargs = dict(order_id="entry-1", ticker="SOL", asset_type="crypto", side="long",
                  requested_quantity=2, reference_price=96.87, now=NOW)
    kwargs.update(changes)
    return eb.entry_basis(_receipt() if order is None else order, **kwargs)


def test_confirmed_stock_price_uses_receipt_without_slippage():
    answer = _basis(_receipt(symbol="AAPL"), ticker="AAPL", asset_type="stock")
    assert answer.price == 105.5 and answer.quantity == 2
    assert answer.metadata["entry_basis_verified"] is True
    assert answer.metadata["entry_fees_known"] is False


def test_crypto_cost_includes_measured_coin_fee_once():
    arrival = SimpleNamespace(quantity=1.99, receipt_qty=2, settled=True)
    answer = _basis(arrival=arrival)
    assert abs(answer.quantity * answer.price - 211) < 1e-10
    assert answer.metadata["entry_basis_verified"] is True
    assert answer.metadata["entry_cost_includes_measured_coin_fee"] is True


def test_receipt_without_wallet_arrival_is_still_provisional():
    answer = _basis()
    assert answer.price == 105.5 and answer.quantity == 2
    assert answer.metadata["entry_basis_verified"] is False


def test_pending_partial_or_invalid_receipt_never_verifies_basis():
    for change in ({"status": "accepted"}, {"status": "partially_filled"},
                   {"id": "another-order"}, {"symbol": "LINK/USD"},
                   {"side": "sell"}, {"filled_avg_price": "NaN"},
                   {"filled_qty": "Infinity"}, {"filled_qty": "3"},
                   {"filled_at": "2026-09-18T14:01:00Z"}, {"filled_at": None}):
        answer = _basis(_receipt(**change))
        assert answer.metadata["entry_basis_verified"] is False, change
        assert answer.price == 96.87, change


def test_canceled_unfilled_entry_does_not_create_a_position():
    for zero in ("0", "0.0", "0.000000000", 0, -0.0):
        answer = _basis(_receipt(status="canceled", filled_qty=zero, filled_avg_price=None))
        assert answer.record_position is False and answer.quantity == 0


def test_terminal_partial_fill_books_only_actual_quantity():
    answer = _basis(_receipt(symbol="AAPL", status="canceled", filled_qty="1"),
                    asset_type="stock", ticker="AAPL")
    assert answer.record_position and answer.quantity == 1 and answer.price == 105.5


def _drive_crypto(quote_available=True):
    """Drive the real submitted-order path without booting the scheduler."""
    source = Path(__file__).resolve().parents[1] / "app/agents/trade_execution.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TradeExecutionAgent")
    method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_execute_alpaca_crypto")
    namespace = {"AgentMessage": lambda **kw: SimpleNamespace(**kw), "_lane_cap_f": lambda p: None}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    load_module("app.runtime.asset_policy")
    alp = load_module("app.brokers.alpaca")
    quote_mod = load_module("app.brokers.execution_price")
    sizing = load_module("app.paper.sizing")
    engine = load_module("app.paper.engine")
    settle = load_module("app.paper.crypto_settle")
    settings = load_module("app.runtime.settings")
    activity = load_module("app.agents.activity_log")
    captured = {"submitted": 0}
    tokens = ModuleType("app.integrations.web_tokens")

    async def no_token(*a): return None
    tokens.get_user_broker_token = no_token
    async def account(**kw):
        return SimpleNamespace(equity=5000, trading_blocked=False, non_marginable_buying_power=1000)
    async def allocation(*a): return ("crypto", 1000, 0, 1000, "balanced")
    async def quote(*a, **kw):
        assert kw["action"] == "open"
        return SimpleNamespace(price=105, timestamp=NOW, source="alpaca:crypto:us") if quote_available else None
    def plan(**kw):
        captured["sizing"] = kw
        return SimpleNamespace(ok=True, quantity=2)
    async def submit(**kw):
        captured["submitted"] += 1
        return _receipt(status="accepted", filled_qty="0", filled_avg_price=None), None
    async def strict_order(*a, **kw): return _receipt(), None
    async def before(*a, **kw): return 0, ""
    async def arrival(**kw):
        return SimpleNamespace(quantity=1.99, receipt_qty=2, settled=True, source="arrival", reason="")
    async def record(**kw): captured["row"] = kw
    with ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules, {"app.integrations.web_tokens": tokens}))
        for module, attrs in ((alp, {"get_account": account, "submit_crypto_order": submit, "get_order_strict": strict_order}),
                              (quote_mod, {"execution_price": quote}), (sizing, {"plan_position": plan}),
                              (engine, {"record_external_position": record}),
                              (settle, {"position_qty": before, "arrived_buy_quantity": arrival}),
                              (settings, {"get_bot_settings": lambda u: SimpleNamespace(risk_per_trade_pct=.01)}),
                              (activity, {"record": lambda *a, **kw: None})):
            for name, value in attrs.items():
                stack.enter_context(patch.object(module, name, value))
        messages = asyncio.run(namespace["_execute_alpaca_crypto"](
            SimpleNamespace(name="trade_execution", _allocation_gate=allocation),
            "book-a", "SOL", "long", 96.87, .05, .1, "crypto_swing", {}))
    return captured, messages


def test_real_crypto_executor_uses_fresh_quote_then_actual_cost_basis():
    captured, messages = _drive_crypto()
    assert captured["sizing"]["entry_price"] == 105
    assert captured["sizing"]["stop_price"] == 99.75
    assert captured["row"]["quantity"] == 1.99
    assert abs(captured["row"]["entry_price"] * 1.99 - 211) < 1e-9
    assert captured["row"]["source_payload"]["entry_basis_verified"]
    assert captured["row"]["entry_at"] == NOW.isoformat()
    assert messages[0].payload["entry_basis_verified"]


def test_real_crypto_executor_refuses_missing_fresh_quote_before_submission():
    captured, messages = _drive_crypto(False)
    assert captured["submitted"] == 0 and "row" not in captured
    assert messages[0].kind == "error" and "quote unavailable" in messages[0].payload["error"]


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
