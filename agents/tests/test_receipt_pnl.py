import sys
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, stub_config, run_tests
from _income_support import run, patched, Client
stub_config()
p = load_module('app.paper.receipt_pnl')
START, END = p.window('2026-09-21')


def fill(oid, side, qty, price, *, hour=15, day=21, sym='ABC', aid=None):
    return {'id': aid or oid, 'order_id': oid, 'activity_type': 'FILL',
            'side': side, 'qty': str(qty), 'price': str(price), 'symbol': sym,
            'transaction_time': f'2026-09-{day:02d}T{hour:02d}:00:00Z'}


def report(fills, fees=None, **kw):
    return p.build_report(fills, fees if fees is not None else [], start=START, end=END,
                          opening=kw.pop('opening', {}), **kw)


def test_fifo_partials_aggregate_orders_and_leave_open_lot():
    r = report([fill('buy', 'buy', 2, 100, hour=12, aid='b1'),
                fill('buy', 'buy', 3, 102, hour=13, aid='b2'),
                fill('sell', 'sell', 1, 110, hour=14, aid='s1'),
                fill('sell', 'sell', 2, 111, hour=15, aid='s2')], lanes={'buy': 'scalp'})
    assert r['totals']['trades'] == 1
    assert abs(r['totals']['gross_pnl_usd']-30) < 1e-8
    assert r['leftover_lots']['ABC'] == 2
    assert r['lanes']['scalp']['day_trades'] == 1


def test_same_session_and_overnight_are_distinct():
    r = report([fill('buy', 'buy', 1, 10, hour=14, day=20), fill('sell', 'sell', 1, 12)])
    assert r['totals']['day_trades'] == 0 and r['totals']['trades'] == 1


def test_crypto_fallback_is_labeled_and_posted_fees_replace_it():
    fills = [fill('buy', 'buy', 1, 100, hour=14, sym='SOL/USD'),
             fill('sell', 'sell', 1, 110, sym='SOL/USD')]
    r = report(fills)
    assert r['round_trips'][0]['fee_sources'] == ['model']
    assert abs(r['totals']['fees_usd']-.546) < 1e-9
    fees = [{'id': 'f1', 'order_id': 'buy', 'net_amount': '-.2'},
            {'id': 'f2', 'order_id': 'sell', 'net_amount': '-.3'}]
    r = report(fills, fees)
    assert r['round_trips'][0]['fee_sources'] == ['posted'] and r['totals']['fees_usd'] == .5


def test_short_fifo_and_options_multiplier():
    r = report([fill('s', 'sell', 2, 10, hour=14), fill('b', 'buy', 2, 8)])
    assert r['totals']['gross_pnl_usd'] == 4
    r = report([fill('b', 'buy', 1, 2, hour=14, sym='ABC260925C00010000'),
                fill('s', 'sell', 1, 3, sym='ABC260925C00010000')])
    assert r['totals']['gross_pnl_usd'] == 100


def test_failed_read_and_unknown_opening_basis_are_not_zero_profit():
    r = report(None)
    assert r['status'] == 'unknown' and r['totals'] is None
    r = report([fill('s', 'sell', 1, 50)], opening={'ABC': 1})
    assert r['status'] == 'partial' and r['unknown_basis_matches'] == 1


def test_three_books_never_share_fifo_lots():
    fills = [fill('b', 'buy', 1, 100, hour=14), fill('s', 'sell', 1, 110)]
    for _ in range(3):
        assert report(fills)['totals']['gross_pnl_usd'] == 10
    assert report([fill('s', 'sell', 1, 110)], opening={'ABC': 1})['unknown_basis_matches'] == 1


def test_reconciliation_reports_residual_and_missing_marks_stay_unknown():
    fills = [fill('b', 'buy', 1, 100, hour=14), fill('s', 'sell', 1, 110)]
    r = report(fills, equity_delta=16, mtm_delta=2, cash_flow=1)
    assert r['unexplained_usd'] == 3
    r = report(fills, equity_delta=16)
    assert r['unexplained_usd'] is None and r['equity_delta_minus_known_net_usd'] == 6
    assert r['measured_spread_usd'] is None and r['friction_share_of_equity'] is None


def test_duplicate_receipts_and_unattributed_lane_are_honest():
    b = fill('b', 'buy', 1, 100, hour=14)
    r = report([b, b, fill('s', 'sell', 1, 110)])
    assert r['totals']['gross_pnl_usd'] == 10 and 'unattributed' in r['lanes']
    assert p.order_lanes([{'broker_order_id': 'b', 'strategy': 'scalp'},
                          {'broker_order_id': 'b', 'strategy': 'extended'}])['b'] == 'unattributed'


def test_nightly_schedule_and_morning_callsite_are_reachable():
    class Scheduler:
        def add_job(self, fn, **kw): self.fn, self.kw = fn, kw
    s = Scheduler()
    p.schedule_receipt_pnl(s)
    assert s.kw['hour'] == 21 and s.kw['minute'] == 30 and s.kw['timezone'] == 'America/New_York'
    root = Path(__file__).parents[1]/'app'
    assert 'schedule_receipt_pnl(_scheduler)' in (root/'runtime/scheduler.py').read_text()
    assert 'await morning_scorecards()' in (root/'agents/market_desk.py').read_text()


def test_morning_scorecards_are_read_per_book_and_deduplicated():
    from types import SimpleNamespace
    settings = load_module('app.runtime.settings')
    accounts = load_module('app.brokers.accounts')
    rows = [{'user_id': uid, 'day': '2026-09-20', 'status': 'partial', 'lanes': {uid: {}}} for uid in ('A', 'B', 'C')]
    with patched(settings, _supabase=lambda: Client(book_daily_pnl=rows)), \
         patched(accounts, load_accounts=lambda: [SimpleNamespace(user_id=u) for u in ('A', 'B', 'C')]), \
         patched(p, _MORNING_SEEN=set()):
        results = run(p.morning_scorecards(datetime(2026, 9, 21, 12, tzinfo=timezone.utc)))
        assert len(results) == 3
        assert [m.payload['user_id'] for m in results] == ['A', 'B', 'C']
        assert not run(p.morning_scorecards(datetime(2026, 9, 21, 13, tzinfo=timezone.utc)))


def test_real_collector_binds_all_three_books_and_preserves_failed_read():
    from contextlib import contextmanager
    from types import SimpleNamespace
    accounts = load_module('app.brokers.accounts')
    alpaca = load_module('app.brokers.alpaca')
    guard = load_module('app.brokers.route_guard')
    active, reads = [], []
    books = [SimpleNamespace(user_id=u, account_id=u, headers=lambda u=u: {'test': u}) for u in ('A', 'B', 'C')]
    @contextmanager
    def bind(uid):
        active.append(uid)
        try: yield next(b for b in books if b.user_id == uid)
        finally: active.pop()
    async def activities(*a, **kw):
        uid = active[-1]
        reads.append((uid, kw.get('activity_types', 'fills')))
        if uid == 'C': return None
        if 'activity_types' in kw: return []
        gain = 1 if uid == 'A' else 7
        return [fill('b', 'buy', 1, 100, hour=14), fill('s', 'sell', 1, 100+gain)]
    async def positions(): return []
    async def account(): return SimpleNamespace(equity=5000, daytrade_count=1)
    async def get(path):
        assert path == '/v2/account/portfolio/history?period=1M&timeframe=1D'
        return {'timestamp': [100, 200], 'equity': [5000, 5001]}
    clock = datetime(2026, 9, 22, 1, 30, tzinfo=timezone.utc)
    with patched(accounts, bind_for_user=bind), patched(guard, check_route=lambda uid: (True, 'ok')), \
         patched(alpaca, get_fill_activities_strict=activities, get_positions_strict=positions,
                 get_account=account, _get=get, broker_venue=lambda: 'paper',
                 _headers=lambda: {'test': active[-1]}):
        results = [run(p.collect_book(b, '2026-09-21', client=Client(), now=clock)) for b in books]
    assert results[0]['totals']['gross_pnl_usd'] == 1
    assert results[1]['totals']['gross_pnl_usd'] == 7
    assert results[2]['status'] == 'unknown' and results[2]['totals'] is None
    assert {uid for uid, _ in reads} == {'A', 'B', 'C'}
    assert not active


def test_windows_cover_overnight_crypto_without_gaps_and_future_fills_stay_out():
    next_start, _ = p.window('2026-09-22')
    assert END == next_start
    r = report([fill('b', 'buy', 1, 100, hour=14),
                fill('s', 'sell', 1, 110, day=22, hour=15)])
    assert r['totals']['trades'] == 0 and r['leftover_lots']['ABC'] == 1


def test_stock_ticker_usd_is_not_charged_a_crypto_model_fee():
    r = report([fill('b', 'buy', 1, 100, hour=14, sym='USD'), fill('s', 'sell', 1, 110, sym='USD')])
    assert r['totals']['fees_usd'] == 0


def test_nightly_persists_unknown_as_null_and_requires_write_confirmation():
    from tempfile import TemporaryDirectory
    from types import SimpleNamespace
    settings = load_module('app.runtime.settings')
    accounts = load_module('app.brokers.accounts')
    rows = []
    class Writer:
        confirmed = True
        def table(self, name):
            assert name == 'book_daily_pnl'
            return self
        def upsert(self, row, on_conflict):
            assert on_conflict == 'user_id,day'
            rows.append(row)
            return self
        def execute(self): return SimpleNamespace(data=[rows[-1]] if self.confirmed else [])
    writer = Writer()
    async def collect(*a, **kw): return p.unknown('receipts_unavailable')
    with TemporaryDirectory() as folder, patched(settings, _supabase=lambda: writer), \
         patched(accounts, load_accounts=lambda: [SimpleNamespace(user_id='A', account_id='primary')]), \
         patched(p, collect_book=collect):
        messages = run(p.run_nightly('2026-09-21', report_dir=folder, now=END))
        assert messages[0].payload['status'] == 'unknown'
        assert rows[-1]['net_pnl_usd'] is None and rows[-1]['trades'] is None
        assert rows[-1]['user_id'] == 'A'
        assert 'receipts_unavailable' in (Path(folder)/'pnl-primary-2026-09-21.md').read_text()
        async def complete(*a, **kw): return report([])
        with patched(p, collect_book=complete):
            writer.confirmed = False
            assert run(p.run_nightly('2026-09-21', report_dir=folder, now=END))[0].payload['status'] == 'unknown'


if __name__ == '__main__': raise SystemExit(run_tests(globals()))
