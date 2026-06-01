"""ISO 20022-aligned cryptocurrency registry.

Mike's call (2026-05-31): if Trezo is building on the ISO 20022 rails
(Fedwire / FedNow / RTP / SWIFT MX), the crypto side of the watchlist
should reflect the same horizon. The coins below are commonly cited
in the crypto press as positioned to interoperate with ISO 20022
messaging when traditional banking and crypto rails meet.

IMPORTANT FRAMING — the ISO 20022 standard itself does NOT endorse
specific coins. These tokens are positioned by their respective
projects as technically compatible with ISO 20022-formatted messages
(e.g. message-passing layers, value-transfer fields). The list is
useful for AWARENESS — knowing which coins the institutional payments
narrative names — not as investment guidance. Trezo's risk rules
still apply per-coin: the rough, less-liquid names get wider stops
and tighter sizing.

Source of the list: coincodex.com/article/27964/iso-20022-crypto/
plus widely-cited industry references. Subject to change as projects
evolve their integration plans.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CoinMeta:
    """Metadata about an ISO 20022-aligned coin.

    `liquidity_tier` drives default stop/target sizing in the crypto
    strategy module — 'a' = highest liquidity, 'c' = thinnest.
    """
    symbol: str
    coingecko_id: str
    name: str
    project: str
    liquidity_tier: str         # 'a' | 'b' | 'c'
    role_blurb: str             # short user-facing explanation


# Curated list. Each entry needs a CoinGecko id Trezo can fetch.
# Order chosen to put higher-liquidity / longer-established projects first.
ISO20022_COINS: list[CoinMeta] = [
    CoinMeta(
        symbol="XRP",
        coingecko_id="ripple",
        name="XRP",
        project="Ripple",
        liquidity_tier="a",
        role_blurb=(
            "Cross-border settlement. Ripple's payments product targets "
            "the same bank-to-bank corridors that Fedwire and SWIFT MX run."
        ),
    ),
    CoinMeta(
        symbol="XLM",
        coingecko_id="stellar",
        name="Stellar Lumens",
        project="Stellar",
        liquidity_tier="a",
        role_blurb=(
            "Remittance + tokenised-asset rails. Used by MoneyGram and "
            "asset issuers; ISO 20022-shaped message paths in the protocol."
        ),
    ),
    CoinMeta(
        symbol="ALGO",
        coingecko_id="algorand",
        name="Algorand",
        project="Algorand Foundation",
        liquidity_tier="a",
        role_blurb=(
            "Layer-1 with central-bank pilots (e.g. Marshall Islands SOV) "
            "and standards alignment for institutional settlement."
        ),
    ),
    CoinMeta(
        symbol="HBAR",
        coingecko_id="hedera-hashgraph",
        name="Hedera",
        project="Hedera Hashgraph",
        liquidity_tier="a",
        role_blurb=(
            "Council-governed DLT with explicit enterprise + payments "
            "focus; among the most-cited ISO 20022-positioned networks."
        ),
    ),
    CoinMeta(
        symbol="QNT",
        coingecko_id="quant-network",
        name="Quant",
        project="Quant Network",
        liquidity_tier="b",
        role_blurb=(
            "Overledger interop layer. Designed to bridge legacy "
            "banking messages (ISO 20022 included) with multiple DLTs."
        ),
    ),
    CoinMeta(
        symbol="XDC",
        coingecko_id="xdce-crowd-sale",
        name="XDC Network",
        project="XinFin",
        liquidity_tier="b",
        role_blurb=(
            "Hybrid blockchain targeted at trade finance and tokenised "
            "real-world assets; positions as ISO 20022-message friendly."
        ),
    ),
    CoinMeta(
        symbol="IOTA",
        coingecko_id="iota",
        name="IOTA",
        project="IOTA Foundation",
        liquidity_tier="b",
        role_blurb=(
            "Feeless DAG-based ledger; EU-backed trial usage for "
            "machine-to-machine settlement; protocol-level message alignment."
        ),
    ),
    CoinMeta(
        symbol="XYO",
        coingecko_id="xyo-network",
        name="XYO",
        project="XYO Network",
        liquidity_tier="c",
        role_blurb=(
            "Geospatial proof-of-location layer. Smallest of the cluster; "
            "Trezo treats this as a high-volatility candidate."
        ),
    ),
]


# Convenience lookups -------------------------------------------------------

ISO20022_COIN_MAP: dict[str, str] = {
    c.symbol: c.coingecko_id for c in ISO20022_COINS
}

ISO20022_SYMBOLS: list[str] = [c.symbol for c in ISO20022_COINS]


# Default per-coin risk parameters by liquidity tier. The crypto module
# imports these to expand its COIN_PARAMS without hard-coding per symbol.
TIER_DEFAULT_PARAMS: dict[str, dict[str, float]] = {
    "a": {"stop_pct": 0.030, "target_pct": 0.060},
    "b": {"stop_pct": 0.050, "target_pct": 0.100},
    "c": {"stop_pct": 0.060, "target_pct": 0.120},
}


def default_params_for(symbol: str) -> Optional[dict[str, float]]:
    """Return the default stop/target % for a known symbol."""
    for c in ISO20022_COINS:
        if c.symbol == symbol.upper():
            return TIER_DEFAULT_PARAMS[c.liquidity_tier]
    return None


def is_iso20022_aligned(symbol: str) -> bool:
    return symbol.upper() in ISO20022_COIN_MAP
