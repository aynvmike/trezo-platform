#!/usr/bin/env python3
"""Enable implemented PAPER capabilities only for one explicitly named owner.

Run the capability migration and deploy/test the code first. Default is a
read-only preview. --apply writes each book's own settings, leaves risk/capital
numbers intact, verifies every result, and never resets a halt or places orders.
"""
from __future__ import annotations
import argparse
import json
import shlex
from pathlib import Path
from urllib.parse import quote
from uuid import UUID
import relay

ENABLED = {name: True for name in (
    'auto_trade_enabled', 'pattern_enabled', 'stms_enabled', 'extended_enabled',
    'crypto_enabled', 'wheel_auto_execute', 'day_options_enabled',
    'spreads_enabled', 'long_options_enabled', 'dividend_lt_enabled',
    'reevaluation_enabled', 'crypto_reevaluation_enabled')}
ENABLED['autonomy_mode'] = 'full'


def selected_books(rows: list[dict], owner_id: str) -> list[dict]:
    """Every owned paper book; never upgrade a real-money account."""
    UUID(owner_id)
    books = [r for r in rows if r.get('owner_id') == owner_id and r.get('is_paper') is True]
    if not books:
        raise ValueError('No paper books belong to the requested owner')
    for row in books:
        UUID(str(row.get('account_key', '')))
    if len({r['account_key'] for r in books}) != len(books):
        raise ValueError('Duplicate account keys; resolve book identity before activation')
    return books


def environment_updates(source: str, books: list[dict], owner_id: str) -> dict[str, str]:
    """Activate only slots whose book and owner match the verified directory.

    Existing enabled slots are preserved. Unknown, duplicated, nonpaper or
    mismatched mappings fail before database writes; never print credentials.
    """
    env = {}
    for raw in source.splitlines():
        line = raw.strip()
        if line.startswith('export '):
            line = line[7:].strip()
        key, sep, value = line.partition('=')
        if sep:
            parsed = shlex.split(value, comments=True, posix=True)
            env[key.strip()] = ' '.join(parsed)
    owned = {b['account_key'] for b in selected_books(books, owner_id)}
    default_owner = env.get('TREZO_OWNER_ID') or env.get('TREZO_PRIMARY_USER_ID', '')
    slots = {'primary': '', 'acct2': '_2', 'acct3': '_3'}
    enabled = [s.strip() for s in env.get('TREZO_ACCOUNTS_ENABLED', 'primary').split(',') if s.strip()]
    if any(s not in slots for s in enabled):
        raise ValueError('Unknown runtime account slot; resolve configuration before activation')
    found = set()
    for slot, suffix in slots.items():
        key = env.get('TREZO_ACCOUNT_USER_ID' + suffix if suffix else 'TREZO_PRIMARY_USER_ID', '')
        if key not in owned:
            continue
        slot_owner = (env.get('TREZO_ACCOUNT_OWNER_ID' + suffix) or default_owner) if suffix else default_owner
        if slot_owner != owner_id:
            raise ValueError(f'{slot}: owner does not match the requested owner')
        if key in found:
            raise ValueError(f'{slot}: duplicate book mapping; books must stay separate')
        base = env.get('ALPACA_BASE_URL' + suffix, 'https://paper-api.alpaca.markets').rstrip('/')
        if base.endswith('/v2'):
            base = base[:-3]
        if base != 'https://paper-api.alpaca.markets':
            raise ValueError(f'{slot}: only a paper broker endpoint can be activated')
        found.add(key)
        if slot not in enabled:
            enabled.append(slot)
    if found != owned:
        raise ValueError('Some owned paper books have no runtime slot; map their account keys before activation')
    return {'TREZO_ACCOUNTS_ENABLED': ','.join(enabled),
            'TREZO_SETTINGS_SINGLE_ROW': '0', 'TREZO_RESEARCH_ENABLED': 'true'}


def rewrite_environment(source: str, updates: dict[str, str]) -> str:
    written, rewritten = set(), []
    for line in source.splitlines():
        key = line.partition('=')[0].strip().removeprefix('export ').strip()
        if key in updates:
            if key not in written:
                rewritten.append(key + '=' + updates[key])
                written.add(key)
        else:
            rewritten.append(line)
    rewritten.extend(key + '=' + value for key, value in updates.items() if key not in written)
    return '\n'.join(rewritten) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-id', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    UUID(args.owner_id)
    env_path = Path(relay._find_env())
    relay._URL, relay._KEY = relay._load_env()
    owner = quote(args.owner_id, safe='')
    books = selected_books(relay.get('/rest/v1/trading_accounts?select=account_key,owner_id,label,is_paper,is_active'
                                     + '&owner_id=eq.' + owner), args.owner_id)
    source = env_path.read_text(encoding='utf-8')
    updates = environment_updates(source, books, args.owner_id)
    # Confirm schema and existing settings for EVERY book before any write.
    prepared = []
    fields = ','.join(['user_id', *ENABLED])
    for book in books:
        key = quote(book['account_key'], safe='')
        path = '/rest/v1/bot_settings?user_id=eq.' + key
        current = relay.get(path + '&select=' + fields)
        if len(current) != 1:
            raise ValueError(f"Book {book['label']}: needs exactly one settings row before activation")
        prepared.append((book, path, current[0]))
    print(json.dumps({'mode': 'apply' if args.apply else 'preview',
                      'runtime_configuration': updates,
                      'books': [{'book_id': b['account_key'], 'label': b['label'],
                                 'before': old, 'enable': ENABLED}
                                for b, _, old in prepared]}, indent=2))
    if not args.apply:
        return
    for book, path, old in prepared:
        relay._req('PATCH', path, ENABLED, {'Prefer': 'return=representation'})
        verified = relay.get(path + '&select=' + fields)
        if len(verified) != 1 or any(verified[0].get(k) != v for k, v in ENABLED.items()):
            raise RuntimeError(f"Settings verification failed for {book['label']}; remaining books untouched")
        active_path = ('/rest/v1/trading_accounts?account_key=eq.' + quote(book['account_key'], safe='')
                       + '&owner_id=eq.' + owner + '&is_paper=eq.true')
        relay._req('PATCH', active_path, {'is_active': True}, {'Prefer': 'return=representation'})
        active = relay.get(active_path + '&select=account_key,is_active')
        if len(active) != 1 or active[0].get('is_active') is not True:
            raise RuntimeError(f"Account activation verification failed for {book['label']}")
        print(json.dumps({'book_id': book['account_key'], 'settings_verified': True,
                          'note': 'Broker permissions, funding and risk checks still decide each entry.'}))

    if env_path.read_text(encoding='utf-8') != source:
        raise RuntimeError('Runtime configuration changed during activation; refusing to overwrite it')
    env_path.write_text(rewrite_environment(source, updates), encoding='utf-8')
    print(json.dumps({'runtime_configuration_updated': list(updates),
                      'restart_required': True,
                      'note': 'Invalid or missing broker credentials remain blocked and visible.'}))


if __name__ == '__main__':
    main()
