"""Parse OCC option symbols into their parts.

Format: <root><yymmdd><C|P><strike*1000 zero-padded to 8>
e.g.   AAPL  241227 C 00200000  → AAPL, 2024-12-27, CALL, $200.00

The root can be 1-6 chars and may include digits, so the trick is
that the last 15 chars are always YYMMDD + type + 8-digit strike.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class OptionPart:
    underlying: str
    expiration: str       # ISO date
    type: str             # "call" | "put"
    strike: float
    occ: str


def parse_occ(occ: str) -> Optional[OptionPart]:
    """Return the parsed parts or None when the symbol is not an OCC."""
    if not occ or len(occ) < 15:
        return None
    s = occ.upper().strip()
    # The trailing 15 chars are 6 (date) + 1 (type) + 8 (strike).
    tail = s[-15:]
    if len(tail) != 15:
        return None
    yymmdd = tail[:6]
    typ_char = tail[6]
    strike_raw = tail[7:]
    if typ_char not in ("C", "P"):
        return None
    if not strike_raw.isdigit() or not yymmdd.isdigit():
        return None
    try:
        year = 2000 + int(yymmdd[0:2])
        month = int(yymmdd[2:4])
        day = int(yymmdd[4:6])
        exp = date(year, month, day).isoformat()
    except (ValueError, TypeError):
        return None
    underlying = s[: -15]
    if not underlying:
        return None
    strike = int(strike_raw) / 1000.0
    return OptionPart(
        underlying=underlying,
        expiration=exp,
        type="call" if typ_char == "C" else "put",
        strike=round(strike, 4),
        occ=s,
    )
