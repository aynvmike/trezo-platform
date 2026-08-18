"""Asset-class policy registry -- what each KIND of holding needs from us.

WHY THIS FILE EXISTS (2026-08-17)
The profit ladder stopped at `if at == "stock"`. That one comparison meant
Alpaca-routed crypto could never bank a slice of a winner, no matter how
far it ran -- not because anyone decided crypto shouldn't step out, but
because the check was written when stocks were the only thing that could.
The same shape of bug is waiting for every asset class we have not added
yet: bonds, forex, futures, a 401k sleeve. Each one arrives, someone
forgets one hardcoded string, and a whole class of position silently
stops being managed.

So the question "can this thing bank a partial? does the broker hold its
stop for us? can we trade it at 3am? can we own 0.37 of one?" is answered
HERE, once, per asset class -- and the agents ask instead of assuming.

HOW TO ADD AN ASSET CLASS
Write one AssetPolicy and register() it. Nothing in position_monitor,
the reconciler or the ladder needs to change. If you forget, `policy_for`
returns UNKNOWN_POLICY, which fails CLOSED: Trezo will still watch the
position and enforce its stop client-side, but it will not bank slices or
place clever orders it has no rules for. Loud, safe, and visible in the
guard test (tests/test_asset_policy.py) rather than silent.

WHAT DOES NOT BELONG HERE
Per-user or per-book behaviour (risk per trade, lanes, TCS floor). That
is settings, and settings live in the bot_settings row -- same boundary
brokers/accounts.py draws. This file describes the INSTRUMENT, not the
trader's preference about it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Callable, Optional


@dataclass(frozen=True)
class AssetPolicy:
    """Everything the exit machinery needs to know about one asset class."""

    asset_type: str
    label: str

    # Does the BROKER hold the stop/target itself once we place it?
    # False means Trezo must re-check the exit on every tick, because
    # nothing at the venue will. Alpaca crypto is the live example: no
    # native bracket, so a coin whose row we lose track of is genuinely
    # unprotected.
    native_brackets: bool = True

    # Must the monitor evaluate stop/target client-side each tick?
    # Always True where native_brackets is False; also True for day-TIF
    # equity brackets, whose legs expire at the close.
    client_side_exits: bool = True

    # WHICH ORDER TYPE will this venue hold as a resting stop for us?
    # "" means none, and the monitor is the only thing standing between
    # the position and a drawdown.
    #
    # Corrected 2026-08-18 (Mike, with the receipts): this codebase had
    # said since June that Alpaca holds NO stop for crypto. Half true.
    # It holds no *stop* and no bracket -- but it does hold a STOP-LIMIT,
    # gtc, and Mike had one resting on BTCUSD at 65,000 while the code
    # was still insisting it was impossible. Alpaca's own docs agree:
    # crypto gets market/limit (gtc, ioc) and stop_limit (gtc only);
    # stop, trailing_stop, and bracket/OCO/OTO are equities-only.
    #
    # So a crypto position CAN be protected at the venue, and the stop
    # can ratchet up there -- which is what makes a trailing stop
    # survive an engine outage instead of dying with it.
    #
    # Defaults to "" -- fails CLOSED. A venue we have not confirmed holds
    # a stop must not be assumed to, because the failure is invisible:
    # we would send a stop, it would be rejected, and the position would
    # look protected while being naked. Declare it per class, from the
    # venue's own documentation.
    stop_order_type: str = ""

    # Do we park a STANDALONE resting order at this venue -- one that is
    # not a bracket leg but still reserves the inventory?
    #
    # Added 2026-08-18 for the crypto take-profit. Alpaca gives crypto no
    # bracket, so a coin's target lived only in our ledger and died with
    # the engine; a resting GTC limit sell survives us. But the moment
    # one rests there, the units are RESERVED, and every other sell path
    # -- the ladder's partial, a forced exit -- gets an insufficient
    # balance reject unless it releases them first. This flag is what
    # tells those paths to cancel before they sell.
    #
    # It stays True even when the placement env-switch is off, so a TP
    # placed under an earlier setting is still released. Cancelling when
    # nothing rests costs one no-op call; NOT cancelling when something
    # does costs the sell.
    resting_exits: bool = False

    # May the step-profit ladder sell a FRACTION of the position?
    supports_partial_step: bool = True

    # Can we hold a non-integer amount? Drives slice rounding: whole
    # units for shares and contracts, real numbers for coins.
    fractional: bool = False

    # Smallest slice worth selling, in units.
    min_slice: float = 1.0

    # Must the remainder also be >= min_slice after a step? (An option
    # position of 1 contract cannot be split at all.)
    min_remainder: float = 1.0

    # Is this tradable only during US market hours? Crypto is not; the
    # profit-step harvest defers to the open for everything that is,
    # because bracket legs cannot be cancelled while the venue is shut.
    session_gated: bool = True

    # May we ADOPT a broker position that has no ledger row -- i.e. write
    # a tracking row from broker truth so the agents can manage it?
    adoptable: bool = True

    # How the broker may spell this symbol vs how Trezo stores it.
    # Alpaca reports crypto as BTCUSD or BTC/USD; Trezo stores BTC.
    symbol_variants: Optional[Callable[[str], frozenset]] = None

    venue: str = "alpaca"
    notes: str = ""

    def slice_size(self, quantity: float, fraction: float) -> float:
        """The tradable slice for a step of `fraction`, or 0.0 when this
        position cannot be split. One place, so nothing rounds a coin to
        zero or tries to sell half a contract."""
        try:
            qty = float(quantity)
            frac = float(fraction)
        except (TypeError, ValueError):
            return 0.0
        if qty <= 0 or not (0.0 < frac < 1.0):
            return 0.0
        raw = qty * frac
        slice_qty = raw if self.fractional else float(int(raw))
        if slice_qty < self.min_slice:
            return 0.0
        if (qty - slice_qty) < self.min_remainder:
            return 0.0
        return slice_qty

    @property
    def holds_stop(self) -> bool:
        """True when protection can rest at the venue rather than only
        in our ledger. The single most important question about an asset
        class, because it decides what survives us going down."""
        return bool(self.stop_order_type)

    @property
    def holds_orders(self) -> bool:
        """True when something of ours may be RESTING at the venue for
        this symbol -- a bracket leg or a standalone limit. Any code
        about to sell must release those first."""
        return self.native_brackets or self.resting_exits

    def can_step(self, quantity: float) -> bool:
        """Is this position big enough to bank a slice at all?"""
        if not self.supports_partial_step:
            return False
        try:
            qty = float(quantity)
        except (TypeError, ValueError):
            return False
        return qty >= (self.min_slice + self.min_remainder)


def _crypto_variants(symbol: str) -> frozenset:
    try:
        from app.brokers.alpaca import crypto_symbol_variants
        return crypto_symbol_variants(symbol)
    except Exception:  # noqa: BLE001
        s = (symbol or "").upper().strip()
        return frozenset({s, f"{s}USD", f"{s}/USD"})


# ---- the registry ----------------------------------------------------------

STOCK = AssetPolicy(
    asset_type="stock", label="US equity / ETF",
    native_brackets=True,
    stop_order_type="stop",
    # Day-TIF bracket legs die at the close, so a row that survives into
    # the next session has no protection at the broker until we re-arm it
    # (the 2026-06-11 naked-position case). We check every tick regardless.
    client_side_exits=True,
    supports_partial_step=True, fractional=False,
    min_slice=1.0, min_remainder=1.0,
    session_gated=True, adoptable=True,
)

CRYPTO = AssetPolicy(
    asset_type="crypto", label="Spot crypto",
    # Alpaca has NO native bracket for crypto. This single False is why
    # a crypto row Trezo cannot see is a genuinely naked position.
    native_brackets=False,
    # No bracket and no OCO -- but a stop_limit rests fine, gtc only.
    stop_order_type="stop_limit",
    client_side_exits=True,
    resting_exits=True,
    supports_partial_step=True, fractional=True,
    min_slice=1e-6, min_remainder=1e-6,
    session_gated=False, adoptable=True,
    symbol_variants=_crypto_variants,
    notes="24/7; no bracket or OCO, but a gtc stop_limit rests;"
          " fractional units.",
)

OPTION = AssetPolicy(
    asset_type="option", label="US equity option",
    native_brackets=False,
    client_side_exits=True,
    # Contracts are indivisible and most of our positions are 1-3 lots;
    # the Exit Advisor's drawback ladder manages these, not the slice
    # stepper. A 1-lot cannot be split at all, which can_step() enforces.
    supports_partial_step=True, fractional=False,
    min_slice=1.0, min_remainder=1.0,
    session_gated=True, adoptable=True,
)

FOREX = AssetPolicy(
    asset_type="forex", label="FX pair",
    native_brackets=False,
    client_side_exits=True,
    supports_partial_step=True, fractional=True,
    min_slice=1.0, min_remainder=1.0,
    # FX runs nearly around the clock but not on the equity calendar;
    # it is not session-gated on US hours. Alpaca has no FX venue today,
    # so this policy exists so the lane can be switched on without
    # touching the monitor.
    session_gated=False, adoptable=True,
    venue="external",
)

FUTURE = AssetPolicy(
    asset_type="future", label="Futures contract",
    native_brackets=True,
    stop_order_type="stop",
    client_side_exits=True,
    supports_partial_step=True, fractional=False,
    min_slice=1.0, min_remainder=1.0,
    session_gated=False, adoptable=True,
    venue="external",
    notes="Nearly 24h with a daily halt; margin, not cash.",
)

BOND = AssetPolicy(
    asset_type="bond", label="Bond / fixed income",
    native_brackets=False,
    client_side_exits=True,
    # Bonds are bought to be HELD; slicing one to bank a 0.4% run is not
    # a strategy, it is a fee. The ladder leaves them alone by policy,
    # not by an omitted branch.
    supports_partial_step=False, fractional=True,
    min_slice=1.0, min_remainder=1.0,
    session_gated=True, adoptable=True,
    venue="external",
)

FUND = AssetPolicy(
    asset_type="fund", label="Mutual fund / retirement holding (401k, IRA)",
    native_brackets=False,
    client_side_exits=True,
    # Funds price once a day at NAV. There is no intraday stop to hit and
    # no partial to bank at a live price -- pretending otherwise would
    # have the agents "sell" at a price that does not exist yet.
    supports_partial_step=False, fractional=True,
    min_slice=0.0001, min_remainder=0.0001,
    session_gated=True, adoptable=True,
    venue="external",
    notes="NAV-priced once daily; no intraday exits.",
)

CASH = AssetPolicy(
    asset_type="cash", label="Cash / sweep",
    native_brackets=False, client_side_exits=False,
    supports_partial_step=False, fractional=True,
    session_gated=False, adoptable=False,
    venue="none",
)

# Fails CLOSED: we still watch it and still enforce its stop, but we do
# not invent trading behaviour for an instrument nobody has described.
UNKNOWN_POLICY = AssetPolicy(
    asset_type="unknown", label="Unregistered asset class",
    native_brackets=False,
    client_side_exits=True,
    supports_partial_step=False,
    fractional=False, min_slice=1.0, min_remainder=1.0,
    session_gated=True, adoptable=False,
    notes="No policy registered -- managed defensively, never stepped.",
)

_REGISTRY: dict[str, AssetPolicy] = {}


def register(policy: AssetPolicy, *, overwrite: bool = False) -> AssetPolicy:
    """Add or replace an asset class. Returns the registered policy."""
    key = (policy.asset_type or "").strip().lower()
    if not key:
        raise ValueError("AssetPolicy needs an asset_type")
    if key in _REGISTRY and not overwrite:
        raise ValueError(
            f"asset_type {key!r} is already registered -- pass "
            f"overwrite=True if you really mean to replace it")
    _REGISTRY[key] = replace(policy, asset_type=key)
    return _REGISTRY[key]


for _p in (STOCK, CRYPTO, OPTION, FOREX, FUTURE, BOND, FUND, CASH):
    register(_p, overwrite=True)

# Spellings that arrive from brokers or older rows, mapped to a policy.
ALIASES: dict[str, str] = {
    "us_equity": "stock", "equity": "stock", "etf": "stock", "stocks": "stock",
    "us_option": "option", "options": "option", "opt": "option",
    "crypto_spot": "crypto", "coin": "crypto", "spot": "crypto",
    "fx": "forex", "currency": "forex",
    "futures": "future",
    "fixed_income": "bond", "treasury": "bond", "bonds": "bond",
    "mutual_fund": "fund", "401k": "fund", "ira": "fund",
    "retirement": "fund", "nav": "fund",
}


# Strings that LOOK like an asset type in a comparison but are not one.
# `auto` is an API query parameter meaning "work it out for me" --
# api/patterns.py turns it into None on the next line. Declared here so
# the guard test can tell a sentinel from a class we forgot to register,
# rather than the test being loosened until it stops catching anything.
SENTINELS: frozenset = frozenset({"auto"})


def policy_for(asset_type: Optional[str]) -> AssetPolicy:
    """The policy for this asset class. NEVER raises and never returns
    None -- an unregistered class gets UNKNOWN_POLICY, which is the
    defensive one. Strict mode (TREZO_ASSET_POLICY_STRICT=1) raises
    instead, for tests and for anyone who wants the loud version."""
    key = (asset_type or "").strip().lower()
    if key in _REGISTRY:
        return _REGISTRY[key]
    alias = ALIASES.get(key)
    if alias and alias in _REGISTRY:
        return _REGISTRY[alias]
    if os.getenv("TREZO_ASSET_POLICY_STRICT", "0") == "1":
        raise KeyError(f"no AssetPolicy registered for asset_type {key!r}")
    try:
        from app.agents.activity_log import record
        record("asset_policy_missing", str(asset_type or "?"),
               reason=("no policy registered for this asset class - managing "
                       "it defensively (client-side exits, no profit steps). "
                       "Add one in app/runtime/asset_policy.py."))
    except Exception:  # noqa: BLE001
        pass
    return UNKNOWN_POLICY


def is_registered(asset_type: Optional[str]) -> bool:
    key = (asset_type or "").strip().lower()
    return key in _REGISTRY or ALIASES.get(key, "") in _REGISTRY


def registered_types() -> list[str]:
    return sorted(_REGISTRY)


def describe() -> list[dict]:
    """Safe for the API surface and the ops report."""
    return [{
        "asset_type": p.asset_type, "label": p.label,
        "native_brackets": p.native_brackets,
        "client_side_exits": p.client_side_exits,
        "resting_exits": p.resting_exits,
        "stop_order_type": p.stop_order_type,
        "supports_partial_step": p.supports_partial_step,
        "fractional": p.fractional, "session_gated": p.session_gated,
        "adoptable": p.adoptable, "venue": p.venue, "notes": p.notes,
    } for p in (_REGISTRY[k] for k in registered_types())]


# ---- per-STRATEGY exit policy ---------------------------------------------
# The asset class says what the INSTRUMENT allows; this says what a given
# strategy WANTS. Both were hardcoded as if/elif chains in the monitor,
# which is how crypto DCA ended up with ladder rungs but no continuous
# trail -- the trail was added to SWING and SCALP by hand and DCA was
# simply missed (2026-08-17 audit: XRP ran up and round-tripped with
# nothing between the rungs).



# ---------------------------------------------------------------------------
# Stop-limit offset: how far UNDER the stop the limit sits.
# ---------------------------------------------------------------------------
# A stop_limit is the only resting stop crypto can have at Alpaca, and it
# carries a failure mode a plain stop does not: when the trigger fires,
# the order becomes a LIMIT. If price has already jumped past that limit
# -- which is exactly what happens in the crashes a stop exists for --
# nothing fills, and an unfilled stop is indistinguishable from no stop.
# It fails silently, which is the worst way for protection to fail.
#
# The offset buys fill probability with exit price. Mike named the scale
# on 2026-08-18; the names are his framing (tight = conservative on
# PRICE). Worth saying plainly, because the names point the opposite way
# from the risk: "conservative" is the tightest limit and therefore the
# one MOST likely not to fill at all.
STOP_LIMIT_OFFSETS: dict[str, float] = {
    "conservative": 0.0015,   # 0.15% -- best fill price, worst fill odds
    "balanced": 0.0050,       # 0.5%  -- the default
    "aggressive": 0.0075,     # 0.75%
    "tolerant": 0.0100,       # 1.0%
    "high": 0.0150,           # 1.5%  -- worst price, best odds of being out
}
DEFAULT_STOP_LIMIT_OFFSET = STOP_LIMIT_OFFSETS["balanced"]

# bot_settings.risk_profile speaks a different vocabulary than the scale
# above. Map it rather than making Mike keep two settings in sync.
_RISK_PROFILE_TO_OFFSET = {
    "conservative": "conservative",
    "balanced": "balanced",
    "aggressive": "aggressive",
    "expert": "balanced",     # expert unlocks the raw slider; until it is
                              # set, expert is not a licence to guess
}


def stop_limit_offset(name_or_profile: Optional[str] = None) -> float:
    """Fraction to subtract from a stop to get its limit price.

    Accepts either a scale name ('balanced') or a bot_settings
    risk_profile ('aggressive'). Unknown input returns the default --
    never zero, because a limit AT the stop is the one setting
    guaranteed to miss in a fast market."""
    key = (name_or_profile or "").strip().lower()
    if key in STOP_LIMIT_OFFSETS:
        return STOP_LIMIT_OFFSETS[key]
    mapped = _RISK_PROFILE_TO_OFFSET.get(key)
    if mapped:
        return STOP_LIMIT_OFFSETS[mapped]
    return DEFAULT_STOP_LIMIT_OFFSET


def stop_limit_price(stop: float, side: str = "long",
                     name_or_profile: Optional[str] = None) -> float:
    """The limit that pairs with `stop`. For a long we are SELLING, so
    the limit sits BELOW the stop (accept a worse price to get out); for
    a short we are buying back, so it sits above."""
    off = stop_limit_offset(name_or_profile)
    if side == "short":
        return round(float(stop) * (1.0 + off), 6)
    return round(float(stop) * (1.0 - off), 6)


@dataclass(frozen=True)
class TrailPolicy:
    """How a strategy protects an open gain."""

    strategy: str
    ladder: str = ""          # name of the rung table in strategies.crypto
    continuous_trail: bool = False   # giveback trail between/above rungs
    trail_arm_gain: Optional[float] = None   # None = use the shared default
    arm_breakeven_at_cost: bool = False      # lock breakeven once fees clear
    notes: str = ""


TRAIL_POLICIES: dict[str, TrailPolicy] = {
    "crypto_swing": TrailPolicy(
        "crypto_swing", ladder="SWING_PROFIT_LADDER",
        continuous_trail=True,
        notes="Rungs to the target plus the 30% giveback trail (ETH 7/16)."),
    "crypto_dca": TrailPolicy(
        "crypto_dca", ladder="DCA_PROFIT_LADDER",
        continuous_trail=True, trail_arm_gain=0.02,
        notes=("Rungs start at +3% against a ~6% target, so everything "
               "below the first rung round-tripped -- the 8/17 XRP case. "
               "Given the trail SWING has, but armed at +2% rather than "
               "the shared +3%: arming AT the first rung would add "
               "nothing, and +2% locks 1.40% after a 30% giveback, which "
               "is 2.3x the 0.62% crypto round trip (2 x 26bps fee + "
               "2 x 5bps slippage). Same arithmetic as SCALP's arm.")),
    "crypto_scalp": TrailPolicy(
        "crypto_scalp", ladder="",
        continuous_trail=True, trail_arm_gain=0.02,
        arm_breakeven_at_cost=True,
        notes="Arms breakeven once the gain clears round-trip cost."),
    "crypto_hodl": TrailPolicy(
        "crypto_hodl", ladder="",
        continuous_trail=False,
        notes=("Deliberately NOT trailed on the shared 30% giveback -- a "
               "HODL is meant to ride. It has its own +40%/20% trail and "
               "a catastrophe stop. Change this only on purpose.")),
    "extended": TrailPolicy(
        "extended", ladder="EXTENDED_PROFIT_LADDER",
        continuous_trail=True,
        notes="Stock multi-day swing; ladder plus the shared stock trail."),
}

DEFAULT_TRAIL = TrailPolicy(
    "default", ladder="", continuous_trail=True,
    notes="Anything unnamed still gets the shared profit trail.")


def trail_policy_for(strategy: Optional[str]) -> TrailPolicy:
    """Match a row's strategy tag to its trail policy. Tolerant of shape:
    'crypto_swing', 'swing', 'extended_stair_stepper' all resolve."""
    s = (strategy or "").strip().lower()
    if not s:
        return DEFAULT_TRAIL
    if s in TRAIL_POLICIES:
        return TRAIL_POLICIES[s]
    for name, pol in TRAIL_POLICIES.items():
        if s.startswith(name) or name.endswith(s) or f"_{s}" in name:
            return pol
    # bare mode names: 'swing' -> crypto_swing, etc.
    for mode in ("hodl", "swing", "dca", "scalp"):
        if mode in s and f"crypto_{mode}" in TRAIL_POLICIES:
            return TRAIL_POLICIES[f"crypto_{mode}"]
    return DEFAULT_TRAIL
