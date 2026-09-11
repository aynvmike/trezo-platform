"""Per-book settings, permission reporting and bound single-account routing."""
from __future__ import annotations
import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config
stub_config()
settings = load_module('app.runtime.settings')
accounts = load_module('app.brokers.accounts')
caps = load_module('app.runtime.capabilities')
alpaca = load_module('app.brokers.alpaca')

@contextlib.contextmanager
def patch(module, **attrs):
    old = {key: getattr(module, key) for key in attrs}
    try:
        for key, value in attrs.items(): setattr(module, key, value)
        yield
    finally:
        for key, value in old.items(): setattr(module, key, value)

class Query:
    def __init__(self, rows): self.rows, self.uid = rows, None
    def select(self, *_): return self
    def eq(self, name, value):
        assert name == 'user_id'
        self.uid = value
        return self
    def order(self, *_, **__): return self
    def limit(self, *_): return self
    def execute(self):
        assert self.uid is not None, 'Unscoped settings query must never run'
        return SimpleNamespace(data=[self.rows[self.uid]] if self.uid in self.rows else [])
class Client:
    def __init__(self, rows): self.rows = rows
    def table(self, name):
        assert name == 'bot_settings'
        return Query(self.rows)

def test_explicit_book_always_owns_its_settings_even_in_single_row_mode():
    rows = {'A': {'tcs_threshold': 70, 'spreads_enabled': False},
            'B': {'tcs_threshold': 50, 'spreads_enabled': True}}
    with patch(settings, _cache={}, _supabase=lambda: Client(rows),
               _primary_user_id=lambda: 'A', _single_row_mode=lambda: True):
        assert settings.get_bot_settings('A').spreads_enabled is False
        assert settings.get_bot_settings('B').spreads_enabled is True
        assert settings.get_bot_settings('B').tcs_threshold == 50
        assert settings.get_bot_settings('A').tcs_threshold == 70

def test_unbound_read_never_selects_primary_or_latest_row():
    def forbidden(): raise AssertionError('Database must not be queried without a book')
    with patch(accounts, bound_account=lambda: None), patch(settings, _cache={}, _supabase=forbidden):
        assert settings.is_fallback_settings(settings.get_bot_settings())

def test_bound_read_uses_secondary_settings_and_missing_row_is_identifiable():
    with patch(accounts, bound_account=lambda: SimpleNamespace(account_key='B')), \
         patch(settings, _cache={}, _supabase=lambda: Client({'B': {'tcs_threshold': 47}})):
        assert settings.get_bot_settings().tcs_threshold == 47
        assert settings.is_fallback_settings(settings.get_bot_settings('missing'))

def snapshot(**overrides):
    row = dict(status='ACTIVE', trading_blocked=False, options_approved_level=3,
               options_trading_level=3, shorting_enabled=True)
    return SimpleNamespace(**(row | overrides))

def rows(cfg=None, account=None, verified=True):
    return {r['id']: r for r in caps._book_capability_rows(
        cfg or settings.BotSettings(), account, settings_verified=verified)}

def test_permissions_and_switches_only_disable_their_own_book():
    a = rows(settings.BotSettings(spreads_enabled=False), snapshot())
    b = rows(settings.BotSettings(), snapshot())
    assert a['spreads']['status'] == 'disabled'
    assert b['spreads']['status'] == 'enabled'
    assert b['stock_short']['status'] == 'enabled'
    restricted = rows(account=snapshot(options_trading_level=1, shorting_enabled=False))
    assert restricted['spreads']['status'] == 'unavailable'
    assert restricted['stock_short']['status'] == 'unavailable'
    assert restricted['wheel_cc']['status'] == 'enabled'

def test_missing_evidence_does_not_claim_enabled_and_unsupported_stays_documented():
    assert rows(account=None)['stock_long']['status'] == 'unverified'
    assert rows(account=snapshot(), verified=False)['wheel_cc']['status'] == 'unverified'
    r = rows(account=snapshot())
    assert r['crypto_short']['status'] == 'unavailable'
    assert r['forex']['status'] == 'unavailable'
    assert r['research']['status'] == 'unavailable'
    assert r['reevaluation']['status'] == 'unavailable'
    assert len([k for k in r if k.startswith('library:')]) > 0

def test_orb_reports_only_directions_that_this_book_can_execute():
    assert rows(account=snapshot())['orb']['directions'] == ['bullish', 'bearish']
    blocked = rows(account=snapshot(shorting_enabled=False))['orb']
    assert blocked['status'] == 'enabled'
    assert blocked['directions'] == ['bullish']
    assert 'shorting is disabled' in blocked['reason']
    unknown = rows(account=snapshot(shorting_enabled=None))['orb']
    assert unknown['directions'] == ['bullish']
    assert 'unverified' in unknown['reason']

def test_absent_new_schema_fields_do_not_enable_unmigrated_books():
    cfg = settings._from_row({})
    assert not any(getattr(cfg, name) for name in (
        'wheel_auto_execute', 'day_options_enabled', 'long_options_enabled',
        'spreads_enabled', 'dividend_lt_enabled', 'reevaluation_enabled',
        'crypto_reevaluation_enabled'))

def test_explicit_single_secondary_broker_binding_is_not_replaced_by_primary_keys():
    secondary = SimpleNamespace(account_key='B')
    with patch(alpaca, _live_active=lambda: False), \
         patch(accounts, bound_account=lambda: secondary, multi_account_active=lambda: False):
        assert alpaca._account_ctx() is secondary

if __name__ == '__main__':
    raise SystemExit(run_tests(globals()))
