"""Validate destinations before paper brokerage credentials leave Trezo."""

from __future__ import annotations

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def paper_base_url(raw: str | None) -> str:
    """Allow only Alpaca's paper origin, with the legacy /v2 suffix.

    The live-mode switch cannot protect an order if a paper account's
    configurable URL points at the live API. Reject that configuration;
    never silently relabel it or send credentials to an arbitrary host.
    Validate the bound book at request time so an invalid book does not
    disable a correctly configured sibling.
    """
    if raw is not None and not isinstance(raw, str):
        raise ValueError("Invalid Alpaca paper endpoint configuration")
    url = (raw or "").strip().rstrip("/")
    if url.endswith("/v2"):
        url = url[:-3]
    if url and url != PAPER_BASE_URL:
        # Do not echo the input: a malformed URL might contain a secret.
        raise ValueError(
            "Paper mode requires https://paper-api.alpaca.markets; "
            "configured broker endpoint refused")
    return PAPER_BASE_URL
