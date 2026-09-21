"""Owner activation preflight: no broker calls or external writes."""
from __future__ import annotations
import runpy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import run_tests

_ops = Path(__file__).resolve().parents[2] / 'ops'
sys.path.insert(0, str(_ops))
try:
    activation = runpy.run_path(str(_ops / 'enable_books.py'))
finally:
    sys.path.remove(str(_ops))
OWNER = '11111111-1111-4111-8111-111111111111'
A = '22222222-2222-4222-8222-222222222222'
B = '33333333-3333-4333-8333-333333333333'
OTHER = '44444444-4444-4444-8444-444444444444'

def book(key, owner=OWNER, paper=True):
    return {'owner_id': owner, 'account_key': key, 'is_paper': paper}

def env(extra=''):
    return (f'TREZO_OWNER_ID={OWNER}\nTREZO_PRIMARY_USER_ID={A}\n'
            f'TREZO_ACCOUNT_USER_ID_2={B}\nTREZO_ACCOUNT_USER_ID_3={OTHER}\n'
            f'TREZO_ACCOUNT_OWNER_ID_3={OTHER}\nTREZO_ACCOUNTS_ENABLED=primary\n' + extra)

def reject(fn):
    try: fn()
    except ValueError: return
    raise AssertionError('Invalid book mapping must fail before writes')

def test_activation_adds_only_selected_owned_paper_slots():
    updates = activation['environment_updates'](env(), [book(A), book(B)], OWNER)
    assert updates['TREZO_ACCOUNTS_ENABLED'] == 'primary,acct2'
    assert updates['TREZO_SETTINGS_SINGLE_ROW'] == '0'
    assert 'acct3' not in updates['TREZO_ACCOUNTS_ENABLED']

def test_existing_other_owner_slot_is_preserved_without_new_activation():
    source = env('TREZO_ACCOUNTS_ENABLED=acct3\n')
    updates = activation['environment_updates'](source, [book(A), book(B)], OWNER)
    assert updates['TREZO_ACCOUNTS_ENABLED'] == 'acct3,primary,acct2'

def test_missing_duplicate_mismatched_and_live_mappings_refuse_activation():
    fn = activation['environment_updates']
    reject(lambda: fn(env(), [book(A), book(B), book(OTHER)], OWNER))
    reject(lambda: fn(env(f'TREZO_ACCOUNT_USER_ID_3={A}\n'), [book(A), book(B)], OWNER))
    reject(lambda: fn(env('ALPACA_BASE_URL_2=https://api.alpaca.markets\n'), [book(A), book(B)], OWNER))
    reject(lambda: fn(env(), [book('55555555-5555-4555-8555-555555555555')], OWNER))

def test_selection_excludes_other_owners_and_real_money():
    selected = activation['selected_books']([book(A), book(B, paper=False), book(OTHER, OTHER)], OWNER)
    assert [x['account_key'] for x in selected] == [A]

def test_environment_rewrite_preserves_unrelated_values_and_removes_duplicate_controls():
    source = 'UNRELATED="literal value"\nexport TREZO_ACCOUNTS_ENABLED=primary\nTREZO_ACCOUNTS_ENABLED=acct3\n'
    result = activation['rewrite_environment'](source, {'TREZO_ACCOUNTS_ENABLED': 'acct2'})
    assert 'UNRELATED="literal value"' in result
    assert result.count('TREZO_ACCOUNTS_ENABLED=') == 1
    assert 'TREZO_ACCOUNTS_ENABLED=acct2' in result
    enabled = activation['ENABLED']
    assert enabled['autonomy_mode'] == 'full'
    assert all(value is True for name, value in enabled.items() if name != 'autonomy_mode')
    assert not any(name in enabled for name in ('risk_per_trade_pct', 'max_open_positions', 'trading_halted'))

if __name__ == '__main__':
    raise SystemExit(run_tests(globals()))
