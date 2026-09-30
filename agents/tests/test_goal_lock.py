import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, stub_config, run_tests
from _income_support import NOW, run, patched
stub_config()
d = load_module('app.paper.entry_discipline')
goals = load_module('app.paper.daily_goal')


class Locks:
    def __init__(self):
        self.values = {}
        self.realized = {'A': 60, 'B': 0}
        self.day = '2026-09-21'
    def rpc(self, name, args):
        assert name == 'observe_daily_goal'
        uid = args['p_user_id']
        key = (uid, self.day)
        first = key not in self.values and self.realized[uid] >= args['p_goal']
        if first: self.values[key] = self.realized[uid]
        return SimpleNamespace(execute=lambda: SimpleNamespace(data={
            'ok': True, 'locked': key in self.values, 'goal': args['p_goal'],
            'label': args['p_label'], 'day': self.day, 'first_refusal': first,
            'realized_at_lock': self.values.get(key)}))


async def state(uid):
    return {'goal': 50, 'label': 'grind', 'known': True}


def test_hit_book_is_locked_unhit_and_swing_are_not():
    db = Locks()
    events = []
    with patched(goals, goal_state=state), patched(d, emit=lambda *a: events.append(a)):
        assert run(d.goal_lock('A', SimpleNamespace(), 'scalp', client=db))['rule'] == 'daily_goal_banked'
        assert run(d.goal_lock('B', SimpleNamespace(), 'scalp', client=db)) is None
        assert run(d.goal_lock('A', SimpleNamespace(), 'extended', client=db)) is None
        assert run(d.goal_lock('A', SimpleNamespace(goal_lock_enabled=False), 'scalp', client=db)) is None
    assert len(events) == 1 and events[0][0] == 'goal_locked'


def test_giveback_stays_locked_and_next_day_resets():
    db = Locks()
    with patched(goals, goal_state=state), patched(d, emit=lambda *a: None):
        assert run(d.goal_lock('A', SimpleNamespace(), 'orb', client=db))
        db.realized['A'] = 10
        assert run(d.goal_lock('A', SimpleNamespace(), 'orb', client=db))
        db.day = '2026-09-22'
        assert run(d.goal_lock('A', SimpleNamespace(), 'orb', client=db)) is None


def test_unknown_counter_or_missing_migration_refuses_intraday():
    async def missing(uid): return {'known': False}
    with patched(goals, goal_state=missing):
        assert run(d.goal_lock('A', SimpleNamespace(), 'scalp', client=Locks()))['rule'] == 'goal_state_unknown'


def test_shared_counter_source_and_persistent_trigger_are_pinned():
    import inspect
    source = inspect.getsource(goals.today_realized)
    assert 'paper_accounts' in source and 'today_realized_pnl_usd' in source
    assert 'paper_positions' not in source and '_ROWSUM_CACHE' not in source
    engine = (Path(__file__).parents[1]/'app/paper/engine.py').read_text()
    assert engine.count('await _apply_close_to_account(') >= 2
    migration = next((Path(__file__).parents[2]/'supabase/migrations').glob('*day_trade_income.sql')).read_text()
    assert 'after update of today_realized_pnl_usd on public.paper_accounts' in migration
    assert 'locked_at is null' in migration and 'default true' in migration


def test_settings_default_on_and_false_is_respected():
    settings = load_module('app.runtime.settings')
    assert settings.BotSettings().goal_lock_enabled is True
    assert settings._from_row({'goal_lock_enabled': False}).goal_lock_enabled is False


def test_counter_reads_are_book_scoped_and_rollover_must_be_complete():
    from _income_support import Client
    from datetime import datetime
    settings = load_module('app.runtime.settings')
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    client = Client(paper_accounts=[
        {'user_id': 'A', 'last_reset_date': '2026-09-21', 'today_realized_pnl_usd': 60},
        {'user_id': 'B', 'last_reset_date': '2026-09-20', 'today_realized_pnl_usd': 500}])
    with patched(settings, _supabase=lambda: client), patched(goals, datetime=Clock):
        assert run(goals.today_realized('A')) == 60
        assert run(goals.today_realized('B')) is None
        assert run(goals.today_realized('C')) is None


def test_goal_refusal_reaches_real_executor_bus_and_activity():
    from _income_support import none
    te = load_module('app.agents.trade_execution')
    events = []
    db = Locks()
    with patched(goals, goal_state=state), patched(d, check_reentry=none,
            pdt_verdict=lambda *a, **k: None, emit=lambda *a: events.append(a)):
        agent = te.TradeExecutionAgent()
        agent._margin_snaps = {'A': {'ts': float('inf'), 'daytrade_count': 0}}
        message = run(agent._entry_discipline(db, 'A', 'ABC', 'long',
                      {'strategy': 'scalp'}, SimpleNamespace(), 'stock', held=False))
    assert message.payload['event'] == 'goal_lock_refused'
    assert [e[0] for e in events] == ['goal_locked', 'goal_lock_refused']


if __name__ == '__main__': raise SystemExit(run_tests(globals()))
