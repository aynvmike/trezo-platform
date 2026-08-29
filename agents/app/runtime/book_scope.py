"""Book scope -- the one door every per-book broker read goes through.

WHY THIS FILE EXISTS (2026-08-17)
Position Monitor asked the broker "which symbols do you hold?" ONCE, at
the top of the tick, and then bound each row's account inside the loop --
in that order. So the answer always came from whichever account happened
to be bound first (the primary), and every 25k / 75k row whose symbol the
primary did not also hold failed the membership test and was closed as a
phantom. The books lost sight of nine real positions each. The broker
still held them; Trezo no longer thought it owned them; and because
Alpaca has no native bracket on crypto, those coins had no stop at all.

The bug was not the comparison. It was that "which book am I asking
about?" was answerable in two different places, and the two disagreed.
This module makes it answerable in ONE place, and makes the wrong order
impossible rather than merely discouraged: you cannot get a held-symbol
set out of here without naming the book, and naming the book is what
binds it.

WHAT THIS GUARANTEES
1. Every broker read is bound to the book it is about, at the moment it
   is made -- never inherited from an outer caller.
2. The answer is cached PER BOOK, never globally. Two books can never
   see each other's holdings, which is the failure above.
3. A book we cannot resolve returns None -- "could not check" -- and
   never an empty set. Callers already know that None must not be read
   as "the broker holds nothing", because reading it that way is what
   closes real positions.
4. A mutation attempted for a book other than the bound one raises
   BookScopeError instead of quietly hitting the default account.

SCALING NOTE (Mike, 2026-08-17: "the code could be even more crucial
when there are multiple users")
Nothing here is specific to three books under one login. The cache keys
on the account key, the binding is a ContextVar, and concurrent per-book
tasks cannot leak into each other. Add a hundred users and the shape is
unchanged; what changes is that a global held-symbol set would go from
"wrong for two books" to "wrong for ninety-nine".
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

from app.brokers.accounts import (
    account_for_user, current_account, multi_account_active,
    should_skip_unresolved, use_account,
)


class BookScopeError(RuntimeError):
    """Raised when an action would touch a book other than the bound one."""


# How long one book's broker snapshot stays good. The monitor ticks every
# 60s and asks about each row, so without a cache a 40-position book would
# make 40 identical calls a tick. Shorter than a tick by design: a stale
# holdings set is exactly the input that phantom-closes a position.
CACHE_TTL_S = float(os.getenv("TREZO_BOOK_SCOPE_TTL_S", "45"))

_cache: dict[str, dict[str, Any]] = {}
_lock = asyncio.Lock()

# Swappable so the guard tests can run without a broker or a network.
_POSITIONS_FETCHER: Optional[Callable] = None


def set_positions_fetcher(fn: Optional[Callable]) -> None:
    """Tests only. Pass an async callable returning a list of position
    dicts for the CURRENTLY BOUND account, or None to restore Alpaca."""
    global _POSITIONS_FETCHER
    _POSITIONS_FETCHER = fn
    invalidate()


@dataclass(frozen=True)
class Book:
    """The resolved book an action is being taken for."""

    key: str                 # the account_key / user_id the state layer uses
    account_id: str          # 'primary' | 'acct2' | ...
    label: str
    owner_id: str

    @property
    def user_id(self) -> str:
        return self.key


def resolve(user_id: str) -> Optional[Book]:
    a = account_for_user(str(user_id or "")) if user_id else None
    if a is None:
        return None
    return Book(key=a.account_key, account_id=a.account_id,
                label=a.label, owner_id=a.owner_id)


def current_book() -> Optional[Book]:
    a = current_account()
    if a is None:
        return None
    return Book(key=a.account_key, account_id=a.account_id,
                label=a.label, owner_id=a.owner_id)


@contextmanager
def bind(user_id: str, *, where: str = "") -> Iterator[Optional[Book]]:
    """Bind this book for the duration of the block, verifying the bind
    actually took.

        with book_scope.bind(row["user_id"], where="monitor") as book:
            if book is None:
                continue                 # unresolved: never act
            await liquidate(...)         # goes to THIS book

    Yields None when the book cannot be resolved AND multi-account is
    live -- the caller must skip. In single-account mode it yields the
    single book, so existing behaviour is unchanged.
    """
    uid = str(user_id or "")
    if should_skip_unresolved(uid):
        _record_refusal(uid, where, "unresolved book -- refusing to act")
        yield None
        return
    a = account_for_user(uid)
    if a is None:
        # Single-account mode: nothing to cross, keep the old path.
        yield current_book()
        return
    with use_account(a):
        ok, note = verify(uid)
        if not ok:
            _record_refusal(uid, where, note)
            yield None
            return
        yield Book(key=a.account_key, account_id=a.account_id,
                   label=a.label, owner_id=a.owner_id)


def verify(user_id: str) -> tuple[bool, str]:
    """Is the currently bound account the one that owns this book?
    Thin wrapper over route_guard so there is one answer, not two."""
    try:
        from app.brokers.route_guard import check_route
        return check_route(str(user_id or ""))
    except Exception as e:  # noqa: BLE001
        return True, f"route check unavailable ({str(e)[:60]})"


def assert_bound(user_id: str, where: str = "") -> None:
    """Raise unless the bound account owns this book. Use immediately
    before anything that MOVES MONEY. Inert in single-account mode."""
    if not multi_account_active():
        return
    ok, note = verify(str(user_id or ""))
    if not ok:
        raise BookScopeError(f"[{where or 'broker action'}] {note}")


def _record_refusal(user_id: str, where: str, note: str) -> None:
    try:
        from app.brokers.route_guard import record_mismatch
        record_mismatch("-", user_id, note, where or "book_scope")
    except Exception:  # noqa: BLE001
        pass


# ---- per-book broker snapshot ---------------------------------------------

async def _fetch_positions() -> Optional[list]:
    """Raw positions for the CURRENTLY BOUND account, or None if the call
    itself failed. None and [] mean different things and always will."""
    if _POSITIONS_FETCHER is not None:
        try:
            res = _POSITIONS_FETCHER()
            if asyncio.iscoroutine(res):
                res = await res
            return list(res) if isinstance(res, (list, tuple)) else None
        except Exception:  # noqa: BLE001
            return None
    try:
        from app.brokers.alpaca import (
            alpaca_configured, get_positions_strict,
        )
        if not alpaca_configured():
            return None
        # STRICT read (2026-08-28): get_positions() returns [] on a
        # FAILED fetch, and this module caches whatever it gets as
        # broker truth for the whole tick -- one rate-limited read
        # made every position on the book "gone" and Position Monitor
        # phantom-closed them all (the DOT/QYLD/AMZN loop). The strict
        # variant keeps failure as None, which callers already treat
        # as "could not check, do not act".
        rows = await get_positions_strict()
        return rows if isinstance(rows, list) else None
    except Exception:  # noqa: BLE001
        return None


async def positions(user_id: str, *, where: str = "",
                    max_age_s: Optional[float] = None) -> Optional[list]:
    """Every broker position for THIS book. None = could not check.

    The bind happens inside, so there is no order of operations for a
    caller to get wrong -- which is the whole point of this module.
    """
    uid = str(user_id or "")
    if not uid:
        return None
    ttl = CACHE_TTL_S if max_age_s is None else float(max_age_s)
    now = time.time()
    hit = _cache.get(uid)
    if hit is not None and (now - hit["ts"]) < ttl:
        return hit["rows"]
    async with _lock:
        hit = _cache.get(uid)
        if hit is not None and (time.time() - hit["ts"]) < ttl:
            return hit["rows"]
        with bind(uid, where=where or "book_scope.positions") as book:
            if book is None:
                return None
            rows = await _fetch_positions()
        # Only cache a REAL answer. Caching a failure would turn one
        # transient broker error into 45 seconds of phantom closes.
        if rows is not None:
            _cache[uid] = {"ts": time.time(), "rows": rows}
        return rows


async def held_symbols(user_id: str, *, where: str = "",
                       max_age_s: Optional[float] = None) -> Optional[set]:
    """The symbol set THIS book holds at the broker. None = could not
    check; callers must not read that as 'holds nothing'."""
    rows = await positions(user_id, where=where, max_age_s=max_age_s)
    if rows is None:
        return None
    return {str(p.get("symbol", "")).upper() for p in rows if p.get("symbol")}


async def holds(user_id: str, symbol: str, asset_type: str = "stock",
                *, where: str = "") -> Optional[bool]:
    """Does this book hold this symbol? None = could not check.

    Symbol spelling is asked of the asset policy rather than hardcoded,
    so BTC/BTCUSD/BTC-USD is one question with one answer no matter which
    asset class grows a new spelling next.
    """
    syms = await held_symbols(user_id, where=where)
    if syms is None:
        return None
    from app.runtime.asset_policy import policy_for
    pol = policy_for(asset_type)
    want = (pol.symbol_variants(symbol) if pol.symbol_variants
            else frozenset({str(symbol or "").upper()}))
    return bool(set(want) & syms)


def invalidate(user_id: Optional[str] = None) -> None:
    """Drop the cached snapshot for one book, or all of them."""
    if user_id is None:
        _cache.clear()
    else:
        _cache.pop(str(user_id), None)


def new_cycle() -> None:
    """Call at the top of a tick. Every book re-reads broker truth."""
    _cache.clear()


def cache_state() -> dict:
    """For the ops report: which books are cached and how old."""
    now = time.time()
    return {k: {"age_s": round(now - v["ts"], 1),
                "positions": len(v["rows"] or [])}
            for k, v in _cache.items()}
