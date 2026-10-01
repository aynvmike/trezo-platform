"""Drive the real crypto entry path: unavailable data must never reach broker."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

sys.path.insert(0,str(Path(__file__).resolve().parent))
from _bootstrap import load_module, stub_config
stub_config()
entry = load_module("app.runtime.crypto_entry")
te = load_module("app.agents.trade_execution")
alp = load_module("app.brokers.alpaca")
quotes = load_module("app.brokers.alpaca_data")
tokens = load_module("app.integrations.web_tokens")
sizing = load_module("app.paper.sizing")
settings = load_module("app.runtime.settings")
activity = load_module("app.agents.activity_log")
gate = load_module("app.runtime.book_gate")


def quote(age=0, bid=100, ask=100.1):
    return SimpleNamespace(bid=bid,ask=ask,ts=(datetime.now(timezone.utc)-timedelta(seconds=age)).isoformat())


def test_quote_validation_and_costs():
    for q in (None, quote(121),quote(-10),quote(bid=102),quote(ask=float('nan'))):
        assert entry.evaluate_quote(q,.02,26)[1]
    assert entry.evaluate_quote(quote(),.001,26)[1] == "crypto_target_below_estimated_cost"
    evidence,error=entry.evaluate_quote(quote(),.02,26)
    assert error is None and evidence['ask']==100.1
    assert .007 < evidence['round_trip_cost_fraction'] < .008


def test_crypto_only_budget_refuses_generic_stock_and_forex_entries():
    cfg=SimpleNamespace(auto_trade_enabled=True,allocation_overrides={
        'crypto':3000,'stocks':0,'income':0,'options':0,'forex':0})
    for at, strategy in [('stock','default'),('forex','forex_swing'),('option','long_call'),('stock','dividend_lt')]:
        assert not gate.admits(cfg,asset_type=at,strategy=strategy)
    assert gate.admits(cfg,asset_type='crypto',strategy='crypto_swing')
    other=SimpleNamespace(auto_trade_enabled=True,allocation_overrides={'stocks':1000})
    assert gate.admits(other,asset_type='stock',strategy='default')


def test_missing_or_stale_quote_refuses_real_entry_before_order():
    account=SimpleNamespace(trading_blocked=False,equity=5000)
    for q in (None, quote(300)):
        with patch.object(alp,'get_account',AsyncMock(return_value=account)), \
             patch.object(tokens,'get_user_broker_token',AsyncMock(return_value=None)), \
             patch.object(quotes,'get_crypto_quote',AsyncMock(return_value=q)), \
             patch.object(alp,'submit_crypto_order',AsyncMock(side_effect=AssertionError('must not submit'))), \
             patch.object(activity,'record',lambda *a,**kw:None):
            result=asyncio.run(te.TradeExecutionAgent._execute_alpaca_crypto(
                SimpleNamespace(name='trade_execution'),'book-B','BTC','long',1,.02,.02,'crypto_swing',{}))
            assert result[0].payload['user_id']=='book-B'
            assert 'crypto_quote_' in result[0].payload['error']


def test_fresh_quote_drives_actual_sizing_instead_of_old_candle():
    account=SimpleNamespace(trading_blocked=False,equity=5000,non_marginable_buying_power=1000)
    class Sized(Exception):
        pass
    def capture(**kw):
        assert kw['entry_price']==100.1
        assert kw['user_id']=='book-B'
        raise Sized
    agent=SimpleNamespace(name='trade_execution',_allocation_gate=AsyncMock(return_value=('crypto',500,0,500,'growth')))
    with patch.object(alp,'get_account',AsyncMock(return_value=account)), \
         patch.object(tokens,'get_user_broker_token',AsyncMock(return_value=None)), \
         patch.object(quotes,'get_crypto_quote',AsyncMock(return_value=quote())), \
         patch.object(settings,'get_bot_settings',return_value=SimpleNamespace(risk_per_trade_pct=.01)), \
         patch.object(sizing,'plan_position',capture), \
         patch.object(activity,'record',lambda *a,**kw:None):
        try:
            asyncio.run(te.TradeExecutionAgent._execute_alpaca_crypto(
                agent,'book-B','BTC','long',1,.02,.02,'crypto_swing',{}))
        except Sized:
            pass
        else:
            assert False,'fresh quote did not reach sizing'
