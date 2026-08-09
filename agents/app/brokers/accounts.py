"""Broker account registry -- run N Alpaca accounts side by side.

WHY THIS FILE EXISTS
Trezo already isolates trading STATE by user_id: app/paper/engine.py
references user_id 46 times, killswitch.py 8, allocation.py 4. Positions,
pockets, equity and the daily drawdown baseline all separate on it. What
was missing was a way to say WHICH broker credentials a given user_id
trades through -- app/brokers/alpaca.py read one global key out of
Settings. This module supplies that mapping. An account is therefore just
a user_id that owns its own credentials, and no new isolation layer is
needed.

WHAT BELONGS HERE -- AND WHAT MUST NOT
Here: credentials, base url, label, and the user_id used for state.
NOT here: posture, lanes, risk_per_trade, max_open, watchlist, TCS floor.
Those live in the per-user `bot_settings` row that the web UI already
writes. Mike, 2026-08-09: "each account should have their own
possibilities and not tied to the main account settings... the actions
the user wants, not being able to change any of the coding." Putting a
single behaviour knob in this file would put it back in code and break
exactly that. Behaviour is settings; this file is plumbing.

CONCURRENCY
The active account is a ContextVar, not a module global. When the loop
fans out into three concurrent asyncio tasks, each keeps its own value.
A plain global would let one account's cycle leak into another's order --
which is the single worst failure mode available here.

SAFETY POSTURE
- Only accounts named in TREZO_ACCOUNTS_ENABLED load. Default: "primary",
  so nothing changes until it is set deliberately.
- An account whose credentials are malformed, duplicated, or missing a
  user_id is DROPPED with a stated reason. It is never silently repaired,
  because a silently repaired account trades the wrong book.
- Secrets never appear in repr(), describe(), or any log line.

BACKGROUND (2026-08-09): three credential sets were pasted into agents/.env
as repeated ALPACA_API_KEY / ALPACA_SECRET_KEY blocks. Duplicate keys do
not create accounts -- dotenv keeps only the LAST value per name, which
had already paired account #2's key id with account #3's secret. Hence
the suffixed field names and the duplicate check below.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterator, Optional

from app.config import get_settings

PAPER_BASE_URL = "https://paper-api.alpaca.markets"

# Alpaca credential shapes. Used to catch a truncated paste, not to
# validate the secret itself -- only the broker can do that.
_KEY_ID_LEN = 26
_SECRET_LEN = 44


@dataclass(frozen=True)
class BrokerAccount:
    """One broker account.

    TWO IDENTITIES, deliberately separate (2026-08-09):

    `owner_id`   -- the PERSON. Owns the profile, the KINDRIP children,
                    payment details, the subscription. One person can hold
                    several accounts: individual, IRA, joint. Mike's three
                    paper books all sit under one Alpaca login, which is
                    exactly this case.
    `account_key`-- the BOOK. Owns positions, pockets, equity, the
                    kill-switch baseline, bot_settings, watchlists.

    The state layer calls the second one `user_id`, because it predates
    the distinction -- `paper_accounts` already holds one row per
    `user_id`, so that column has always meant "account". The `user_id`
    property below preserves that call signature without pretending an
    account is a person.
    """

    account_id: str
    label: str
    owner_id: str
    account_key: str
    key_id: str = field(repr=False)
    secret: str = field(repr=False)
    base_url: str = PAPER_BASE_URL

    @property
    def user_id(self) -> str:
        """What the state layer calls user_id. It is the ACCOUNT key."""
        return self.account_key

    def headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self.key_id,
            "APCA-API-SECRET-KEY": self.secret,
        }

    def describe(self) -> dict:
        """Safe for logs, the API surface, and the web UI."""
        return {
            "account_id": self.account_id,
            "label": self.label,
            "owner_id": self.owner_id,
            "account_key": self.account_key,
            "base_url": self.base_url,
            "key_id_prefix": self.key_id[:4] + "..." if self.key_id else "",
        }

    def __repr__(self) -> str:  # never leak the secret
        return (f"BrokerAccount({self.account_id!r}, label={self.label!r}, "
                f"owner={self.owner_id!r}, account_key={self.account_key!r})")


def _normalise_base_url(raw: str) -> str:
    """Strip a trailing /v2 -- the callers append /v2/... themselves.

    A base url of '.../markets/v2' produces '.../v2/v2/account', which
    404s on every request. This was live in agents/.env on 2026-08-09.
    """
    u = (raw or "").strip().rstrip("/")
    if not u:
        return PAPER_BASE_URL
    if u.endswith("/v2"):
        u = u[: -len("/v2")]
    return u


def _slot_values(s, slot: str) -> tuple:
    """Read one credential slot. '' is primary; '_2'/'_3' are the rest."""
    # Owner defaults to the single configured person. Set the per-slot
    # override only when accounts genuinely belong to different people --
    # the real platform case, not Mike's three books under one login.
    default_owner = ((getattr(s, "trezo_owner_id", "") or "").strip()
                     or (getattr(s, "trezo_primary_user_id", "") or "").strip())
    if slot == "":
        return (
            getattr(s, "alpaca_api_key", "") or "",
            getattr(s, "alpaca_secret_key", "") or "",
            getattr(s, "alpaca_base_url", "") or "",
            (getattr(s, "trezo_primary_user_id", "") or ""),
            "Primary",
            default_owner,
        )
    return (
        getattr(s, f"alpaca_api_key{slot}", "") or "",
        getattr(s, f"alpaca_secret_key{slot}", "") or "",
        getattr(s, f"alpaca_base_url{slot}", "") or "",
        getattr(s, f"trezo_account_user_id{slot}", "") or "",
        getattr(s, f"trezo_account_label{slot}", "") or f"Account{slot}",
        (getattr(s, f"trezo_account_owner_id{slot}", "") or "").strip() or default_owner,
    )


_SLOTS = {"primary": "", "acct2": "_2", "acct3": "_3"}


def _build() -> tuple[list, list]:
    """Return (accounts, problems). Never raises."""
    s = get_settings()
    wanted = [a.strip() for a in
              (getattr(s, "trezo_accounts_enabled", "primary") or "primary").split(",")
              if a.strip()]
    accounts: list = []
    problems: list = []
    seen_keys: dict = {}
    seen_users: dict = {}

    for account_id in wanted:
        slot = _SLOTS.get(account_id)
        if slot is None:
            problems.append(f"{account_id}: unknown account id "
                            f"(expected one of {', '.join(_SLOTS)})")
            continue
        (key_id, secret, base_url, account_key, label,
         owner_id) = _slot_values(s, slot)

        if not key_id or not secret:
            problems.append(f"{account_id}: missing credentials -- set "
                            f"ALPACA_API_KEY{slot} and ALPACA_SECRET_KEY{slot}")
            continue
        if len(key_id) != _KEY_ID_LEN or len(secret) != _SECRET_LEN:
            problems.append(
                f"{account_id}: credential looks truncated "
                f"(key id {len(key_id)} chars, expected {_KEY_ID_LEN}; "
                f"secret {len(secret)} chars, expected {_SECRET_LEN})")
            continue
        if not account_key:
            _var = ("TREZO_PRIMARY_USER_ID" if slot == ""
                    else f"TREZO_ACCOUNT_USER_ID{slot}")
            problems.append(
                f"{account_id}: no user_id -- set {_var}. "
                f"Without it this account cannot own separate positions, "
                f"pockets or a kill-switch baseline.")
            continue

        # A shared key id means two 'accounts' are one book.
        if key_id in seen_keys:
            problems.append(f"{account_id}: same API key id as "
                            f"'{seen_keys[key_id]}' -- these are one account")
            continue
        # A shared user_id merges two books' positions. Worst case here.
        # Two accounts sharing an account_key merge into one book. Two
        # accounts sharing an OWNER is normal and expected.
        if account_key in seen_users:
            problems.append(f"{account_id}: same account key as "
                            f"'{seen_users[account_key]}' -- their positions "
                            f"would merge into one book")
            continue

        seen_keys[key_id] = account_id
        seen_users[account_key] = account_id
        accounts.append(BrokerAccount(
            account_id=account_id, label=label,
            owner_id=owner_id or account_key, account_key=account_key,
            key_id=key_id, secret=secret,
            base_url=_normalise_base_url(base_url),
        ))

    return accounts, problems


@lru_cache(maxsize=1)
def _cached() -> tuple:
    return _build()


def load_accounts() -> list:
    """Every enabled, valid account. Cached; call reset_cache() after edits."""
    return list(_cached()[0])


def validation_report() -> list:
    """Why an enabled account did not load. Empty means all clean."""
    return list(_cached()[1])


def reset_cache() -> None:
    _cached.cache_clear()


def get_account(account_id: str):
    for a in load_accounts():
        if a.account_id == account_id:
            return a
    return None


def account_for_user(user_id: str):
    """Account whose BOOK key matches. Kept for existing callers."""
    for a in load_accounts():
        if a.account_key == user_id:
            return a
    return None


def accounts_for_owner(owner_id: str) -> list:
    """Every book a person holds. The combined-view primitive."""
    return [a for a in load_accounts() if a.owner_id == owner_id]


def owner_of(account_key: str):
    """Which person owns this book."""
    a = account_for_user(account_key)
    return a.owner_id if a else None


def owners() -> list:
    """Distinct people across all loaded accounts."""
    seen: list = []
    for a in load_accounts():
        if a.owner_id not in seen:
            seen.append(a.owner_id)
    return seen


def primary_account():
    """The primary account, or the first that loaded, or None."""
    return get_account("primary") or (load_accounts() or [None])[0]


def multi_account_active() -> bool:
    return len(load_accounts()) > 1


# ---- active account context -----------------------------------------------
# ContextVar so concurrent per-account cycles never see each other's account.
_active: contextvars.ContextVar = contextvars.ContextVar(
    "trezo_active_account", default=None)


def current_account():
    """The account this task is acting for; falls back to primary."""
    return _active.get() or primary_account()


@contextmanager
def use_account(account) -> Iterator:
    """Bind an account for the duration of a block.

        with use_account(acct):
            await submit_order(...)   # goes to acct, not the primary
    """
    token = _active.set(account)
    try:
        yield account
    finally:
        _active.reset(token)


@contextmanager
def bind_for_user(user_id: str) -> Iterator:
    """Bind the account that owns this book, by its book key.

    Call sites that already know WHICH BOOK they are acting on should use
    this rather than relying on an outer caller to have bound the right
    account. Sizing one book from another book's equity is the 2026-07-02
    pockets bug and the 2026-08-07 kill-switch bug wearing a new costume,
    and both were silent. A book we do not recognise yields None and the
    caller keeps its existing behaviour.
    """
    a = account_for_user(user_id) if user_id else None
    if a is None:
        yield None
        return
    with use_account(a):
        yield a


def set_account_for_user(user_id: str) -> bool:
    """Bind by book key WITHOUT a context manager.

    `bind_for_user` is preferable, but some loop bodies are hundreds of
    lines long and wrapping them in `with` would mean re-indenting all of
    it -- a large mechanical edit in code that manages live exits. This
    sets the ContextVar directly instead; each iteration overwrites the
    previous, and callers should clear_account() after the loop.

    Returns True when the book resolved. An unrecognised book binds None,
    which falls back to the primary account -- correct while there IS only
    a primary, DANGEROUS once there are several, because an action meant
    for an unknown book would land on the primary one. So callers must
    check the return value and skip when it is False AND multi-account is
    active. `should_skip_unresolved()` packages that test.
    """
    a = account_for_user(user_id) if user_id else None
    _active.set(a)
    return a is not None


def should_skip_unresolved(user_id: str) -> bool:
    """True when this row's book cannot be resolved and acting would be
    unsafe. Always False while single-account, so behaviour is unchanged
    until multi-account is deliberately turned on."""
    if not multi_account_active():
        return False
    return account_for_user(user_id) is None


def clear_account() -> None:
    """Drop any inline binding set by set_account_for_user()."""
    _active.set(None)


def current_user_id() -> Optional[str]:
    """The BOOK key for the account this task is acting for."""
    a = current_account()
    return a.account_key if a else None


def current_owner_id() -> Optional[str]:
    """The PERSON behind the account this task is acting for."""
    a = current_account()
    return a.owner_id if a else None
