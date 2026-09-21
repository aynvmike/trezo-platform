"""Explicit, verified paper-book binding for owner-scoped HTTP handlers."""
from contextlib import contextmanager


class BookRouteUnavailable(ValueError):
    pass


@contextmanager
def paper_book_route(book_id: str):
    from app.brokers.accounts import account_for_user, bind_for_user
    from app.brokers.endpoints import paper_base_url
    from app.brokers import alpaca
    if not isinstance(book_id, str) or not book_id.strip():
        raise BookRouteUnavailable("Select a specific trading account.")
    account = account_for_user(book_id)
    if account is None:
        raise BookRouteUnavailable("This book has no registered broker route; no default account was substituted.")
    try:
        endpoint = paper_base_url(account.base_url)
    except ValueError as exc:
        raise BookRouteUnavailable("This account is not configured for the supported paper venue.") from exc
    with bind_for_user(book_id) as bound:
        try:
            valid = (bound is not None and bound.account_key == book_id
                     and bool(account.key_id and account.secret)
                     and alpaca.broker_venue() == "paper"
                     and alpaca._base_url() == endpoint
                     and alpaca._headers_for(None) == account.headers())
        except Exception:
            valid = False
        if not valid:
            raise BookRouteUnavailable("This book's paper broker route could not be verified.")
        yield bound
