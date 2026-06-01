"""KINDRIP allocation - the child portfolio mix.

Phase 9a; glide-path rebuild Phase 9.5b. Each KINDRIP child account
auto-invests received contributions into a conservative index mix:
SCHD (dividend growth), VTI (total US market), BND (bonds), and a cash
slice. The mix is either:

  - 'auto'   : an age-based glide path picks the mix from the child's
               age - almost all stocks for a young child, gliding
               smoothly toward bonds and cash as college nears. This is
               the same model 529 college-savings plans use.
  - 'custom' : the parent sets the four sleeve weights by hand.

The OBBB Future Index Account requires US-index funds; SCHD and VTI both
qualify, BND is the bond ballast, and cash is the buffer.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

# Tradeable sleeves; 'cash' is the fourth, held as cash.
KINDRIP_ETFS = ("SCHD", "VTI", "BND")
SLEEVES = ("schd", "vti", "bnd", "cash")

# The spec's default mix (TREZO_WOVEN_BASKET.md) - used when age is unknown.
DEFAULT_MIX = {"schd": 0.40, "vti": 0.30, "bnd": 0.20, "cash": 0.10}

# Glide-path endpoints. The stock share starts high at birth and glides
# down linearly to a college-doorstep floor by age 18; cash is held flat.
_GLIDE_START_AGE = 0
_GLIDE_END_AGE = 18
_STOCK_AT_START = 0.92   # age 0  - almost all stocks, decades to compound
_STOCK_AT_END = 0.20     # age 18 - mostly bonds and cash, protect the pot
_CASH_FLOOR = 0.06       # steady cash buffer at every age
# Within the stock portion: VTI (broad-market growth) vs SCHD (dividend).
_VTI_SHARE_OF_STOCK = 0.60


def child_age(birth_year, today: Optional[date] = None) -> Optional[int]:
    """The child's age in whole years, or None if birth_year is unknown."""
    if not birth_year:
        return None
    try:
        yr = (today or date.today()).year
        return max(0, yr - int(birth_year))
    except (TypeError, ValueError):
        return None


def stock_pct_for_age(age: int) -> float:
    """The glide-path stock share for a given age (linear, clamped 0-18)."""
    a = max(_GLIDE_START_AGE, min(int(age), _GLIDE_END_AGE))
    span = _GLIDE_END_AGE - _GLIDE_START_AGE
    progress = (a - _GLIDE_START_AGE) / span  # 0.0 at birth -> 1.0 at 18
    return _STOCK_AT_START - (_STOCK_AT_START - _STOCK_AT_END) * progress


def glide_mix(age: int) -> dict:
    """The age-based glide-path mix for a given whole-year age."""
    stock = stock_pct_for_age(age)
    cash = _CASH_FLOOR
    bond = max(0.0, 1.0 - stock - cash)
    vti = stock * _VTI_SHARE_OF_STOCK
    schd = stock - vti
    return normalize({"schd": schd, "vti": vti, "bnd": bond, "cash": cash})


def auto_mix(birth_year, today: Optional[date] = None) -> dict:
    """The age-appropriate index mix for a KINDRIP child (glide path)."""
    age = child_age(birth_year, today)
    if age is None:
        return dict(DEFAULT_MIX)
    return glide_mix(age)


def normalize(weights: dict) -> dict:
    """Normalize the four sleeve weights so they sum to 1.0."""
    vals = {k: max(0.0, float(weights.get(k, 0) or 0)) for k in SLEEVES}
    total = sum(vals.values())
    if total <= 0:
        return dict(DEFAULT_MIX)
    return {k: round(v / total, 4) for k, v in vals.items()}


def resolve_mix(allocation_mode: str, birth_year,
                custom_weights: Optional[dict] = None) -> dict:
    """The mix a KINDRIP contribution should be invested into."""
    if allocation_mode == "custom" and custom_weights:
        return normalize(custom_weights)
    return auto_mix(birth_year)


def split_contribution(amount_usd: float, mix: dict) -> dict:
    """Split a contribution dollar amount across the four sleeves."""
    m = normalize(mix)
    return {k: round(amount_usd * m[k], 2) for k in SLEEVES}


def explain_mix(mix: dict) -> str:
    """A short human-readable description of a mix."""
    m = normalize(mix)
    return (f"{m['vti'] * 100:.0f}% VTI, {m['schd'] * 100:.0f}% SCHD, "
            f"{m['bnd'] * 100:.0f}% BND, {m['cash'] * 100:.0f}% cash")


def glide_explanation(birth_year, today: Optional[date] = None) -> str:
    """A plain-language note on why the Auto mix looks the way it does."""
    age = child_age(birth_year, today)
    if age is None:
        return ("With no birth year set, KINDRIP uses a balanced starter "
                "mix. Add the child's age to switch on the glide path.")
    stock = round(stock_pct_for_age(age) * 100)
    if age <= 5:
        horizon = "The money is decades from being needed"
    elif age <= 11:
        horizon = "There is still a long runway before college"
    elif age <= 16:
        horizon = "College is getting close"
    else:
        horizon = "College is right around the corner"
    return (f"{horizon}, so the Auto mix holds about {stock}% in stocks "
            f"and glides the rest into bonds and cash as the child grows - "
            f"the same approach a 529 college-savings plan uses.")
