import sys
from pathlib import Path
from types import SimpleNamespace
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, stub_config, run_tests
from _income_support import NOW, run, patched, Client, none
stub_config()
d = load_module('app.paper.entry_discipline')


def snap(equity, count=3):
    return {'equity': equity, 'daytrade_count': count, 'pattern_day_trader': False,
            'pdt_state_known': True, 'ts': NOW.timestamp()}


def test_small_and_buffer_books_refuse_large_book_allows():
    for equity in (4700, 26600):
        assert d.pdt_verdict(snap(equity), 'scalp', 'stock')['rule'] == 'day_trade_limit'
        assert d.pdt_verdict(snap(equity), 'extended', 'stock') is None
    assert d.pdt_verdict(snap(76000), 'scalp', 'stock') is None
    assert d.pdt_verdict(snap(1999, 0), 'scalp', 'stock')['rule'] == 'below_minimum_equity'
    assert d.pdt_verdict(snap(4700, 2), 'scalp', 'stock') is None


def test_unknown_account_refuses_only_intraday_stock():
    assert d.pdt_verdict({}, 'orb', 'stock')['rule'] == 'account_state_unknown'
    assert d.pdt_verdict({}, 'crypto_scalp', 'crypto') is None
    assert d.pdt_verdict({}, 'wheel', 'option') is None
    assert d.pdt_verdict({**snap(5000, 0), 'pattern_day_trader': True}, 'orb', 'stock')


def test_intraday_classification_is_shared_with_monitor():
    import inspect
    pm = load_module('app.agents.position_monitor')
    assert 'is_intraday(strat)' in inspect.getsource(pm._decide_time_stop)
    for strategy in ('scalp', 'stms_breakout', 'orb_long'):
        assert d.is_intraday(strategy)
    for strategy in ('extended', 'dividend_lt', 'wheel', 'crypto_scalp'):
        assert not d.is_intraday(strategy)


def test_pdt_rejection_does_not_increment_storm_but_normal_reject_does():
    ks = load_module('app.paper.killswitch')
    with patched(ks, _broker_reject_ts={}):
        assert ks.record_broker_reject('A', error='403: day trading protection') == 0
        assert ks.record_broker_reject('A', error='403 insufficient balance') == 1
        assert ks.broker_reject_count('B') == 0
    source = (Path(__file__).parents[1]/'app/agents/trade_execution.py').read_text()
    assert '"pdt_reject"' in source and 'error=oerr' in source and 'error=err' in source


def test_real_executor_uses_two_books_own_cached_snapshots():
    te = load_module('app.agents.trade_execution')
    log = load_module('app.agents.activity_log')
    agent = te.TradeExecutionAgent()
    agent._margin_snaps = {'A': snap(4700), 'B': snap(76000)}
    with patched(d, check_reentry=none, goal_lock=none), patched(time, time=lambda: NOW.timestamp()), patched(log, record=lambda *a, **k: None):
        a = run(agent._entry_discipline(Client(), 'A', 'ABC', 'long', {'strategy': 'scalp'}, SimpleNamespace(), 'stock', held=False))
        b = run(agent._entry_discipline(Client(), 'B', 'ABC', 'long', {'strategy': 'scalp'}, SimpleNamespace(), 'stock', held=False))
    assert a.payload['event'] == 'pdt_guard' and a.payload['equity'] == 4700
    assert b is None


def test_fresh_submission_account_blocks_a_fourth_day_trade():
    te = load_module('app.agents.trade_execution')
    alpaca = load_module('app.brokers.alpaca')
    tokens = load_module('app.integrations.web_tokens')
    log = load_module('app.agents.activity_log')
    submitted = []
    async def account(**kw): return SimpleNamespace(**snap(4700), trading_blocked=False)
    async def clock(**kw): return {'is_open': True}
    async def submit(**kw):
        submitted.append(kw)
        raise AssertionError('PDT guard must run before submit')
    with patched(alpaca, get_account=account, get_clock=clock, submit_bracket_order=submit), \
         patched(tokens, get_user_broker_token=none), patched(log, record=lambda *a, **k: None):
        messages = run(te.TradeExecutionAgent()._execute_alpaca(
            'A', 'ABC', 'long', 100, .05, .1, 'scalp', {}))
    assert messages[0].payload['event'] == 'pdt_guard' and not submitted


if __name__ == '__main__': raise SystemExit(run_tests(globals()))
