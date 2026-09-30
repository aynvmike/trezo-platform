import sys
from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, stub_config, run_tests
from _income_support import NOW, run, patched, Client, none
stub_config()
d = load_module('app.paper.entry_discipline')


def close(minutes=100, **changes):
    return {'user_id': 'A', 'ticker': 'SOL', 'asset_type': 'crypto',
            'exit_at': (NOW-timedelta(minutes=minutes)).isoformat(), 'exit_price': 100,
            'status': 'closed_stop', 'side': 'long', **changes}


def test_cooldown_and_cost_band_are_both_required():
    assert d.reentry_verdict(close(89), 110, 'crypto', 'long', NOW)['rule'] == 'cooldown'
    assert d.reentry_verdict(close(), 100.1, 'crypto', 'long', NOW)['rule'] == 'cost_band'
    for side in ('long', 'short'):
        for price in (99, 101):
            assert d.reentry_verdict(close(), price, 'crypto', side, NOW) is None


def test_first_entry_add_and_old_close_untouched():
    assert run(d.check_reentry(Client(), 'A', 'SOL', 'crypto', 'long', now=NOW)) is None
    assert run(d.check_reentry(None, 'A', 'SOL', 'crypto', 'long', held=True, now=NOW)) is None
    assert d.reentry_verdict(close(1441), None, 'crypto', 'long', NOW) is None


def test_full_close_only_and_each_book_independent():
    client = Client(paper_positions=[close(30), close(1, user_id='B', status='closed_partial')])
    assert run(d.check_reentry(client, 'A', 'SOL', 'crypto', 'long', now=NOW))['rule'] == 'cooldown'
    assert run(d.check_reentry(client, 'B', 'SOL', 'crypto', 'long', now=NOW)) is None


def test_failed_read_or_quote_never_grants_reentry():
    assert run(d.check_reentry(None, 'A', 'SOL', 'crypto', 'long', now=NOW))
    with patched(d, fresh_entry_price=none):
        assert run(d.check_reentry(Client(paper_positions=[close()]), 'A', 'SOL', 'crypto', 'long', now=NOW))['rule'] == 'evidence_unknown'


def test_real_executor_emits_book_scoped_refusal():
    te = load_module('app.agents.trade_execution')
    log = load_module('app.agents.activity_log')
    rows = []
    with patched(log, record=lambda *a, **k: rows.append((a, k))), \
         patched(d, check_reentry=lambda *a, **k: asyncio_result({'rule': 'cooldown'})):
        message = run(te.TradeExecutionAgent()._entry_discipline(
            Client(), 'A', 'SOL', 'long', {'strategy': 'crypto_scalp'},
            SimpleNamespace(goal_lock_enabled=True), 'crypto', held=False))
    assert message.payload['event'] == 'reentry_refused'
    assert message.payload['user_id'] == 'A' and rows[0][1]['extra']['user_id'] == 'A'


async def asyncio_result(value): return value


def test_executor_guard_sits_between_hold_and_capacity_and_is_counted():
    import inspect
    te = load_module('app.agents.trade_execution')
    source = inspect.getsource(te.TradeExecutionAgent._execute_for_all_users)
    assert source.index('"event": "book_already_holds"') < source.index('await self._entry_discipline') < source.index('"event": "book_at_capacity"')
    wd = load_module('app.agents.ops_watchdog')
    assert 'reentry_refused' in wd._DELIBERATE_REFUSALS


def test_reentry_price_requires_a_fresh_sided_uncrossed_quote():
    data = load_module('app.brokers.alpaca_data')
    q = SimpleNamespace(symbol='SOL/USD', bid=99, ask=101, ts=NOW.isoformat())
    async def quote(*a): return q
    with patched(data, get_crypto_quote=quote):
        assert run(d.fresh_entry_price('SOL', 'crypto', 'long', NOW)) == 101
        assert run(d.fresh_entry_price('SOL', 'crypto', 'short', NOW)) == 99
        q.ts = (NOW-timedelta(minutes=2)).isoformat()
        assert run(d.fresh_entry_price('SOL', 'crypto', 'long', NOW)) is None
        q.ts, q.bid = NOW.isoformat(), 102
        assert run(d.fresh_entry_price('SOL', 'crypto', 'long', NOW)) is None


if __name__ == '__main__': raise SystemExit(run_tests(globals()))
