"""Trezo Strategy Library — the agents' shared knowledge base of proven
quantitative trading strategies.

Phase 7.5. This module is a *resource*, not a runnable strategy. Every
agent can import it to answer questions like:
  - "Which strategies suit the current market regime?"
  - "What family does the signal I just emitted belong to?"
  - "When news flips the regime to risk-off, which strategies do I pause?"

The library starts with a curated, proven core set drawn from the
well-known quant canon. It is deliberately small — Trezo favors a handful
of strategies it understands deeply over hundreds it cannot supervise.

Sources span the classic literature: Chan, Quantitative Trading (2008);
Connors & Alvarez, Short Term Trading Strategies; Jegadeesh & Titman on
momentum; Bernard & Thomas on post-earnings drift; plus the QuantConnect
and Composer strategy libraries and Fidelity's sector research.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


LIBRARY_VERSION = "1.0"

# --- Vocabulary -------------------------------------------------------

# Strategy families — the broad approach a strategy takes.
FAMILIES = (
    "trend",           # ride sustained directional moves
    "momentum",        # buy strength, sell weakness
    "mean_reversion",  # fade extremes back toward an average
    "breakout",        # enter as price clears a level
    "income",          # collect premium / dividends
    "event_driven",    # trade around news and corporate events
    "volatility",      # trade expansions / contractions in volatility
    "rotation",        # move capital between sectors / assets
    "arbitrage",       # exploit a relative-value spread
)

# Market regimes — the adaptive engine classifies the market into one of
# these, and the library says which strategies suit each.
REGIMES = (
    "trending_up",
    "trending_down",
    "choppy",
    "high_volatility",
    "low_volatility",
    "risk_off",
)

RISK_PROFILES = ("conservative", "moderate", "aggressive")


@dataclass(frozen=True)
class StrategyCard:
    """One proven strategy, described so an agent can reason about it."""

    id: str
    name: str
    family: str
    thesis: str                       # one plain-English sentence
    signals: tuple[str, ...]          # inputs / indicators it relies on
    best_regimes: tuple[str, ...]     # regimes where it tends to work
    avoid_regimes: tuple[str, ...]    # regimes where it tends to fail
    risk_profile: str                 # conservative | moderate | aggressive
    typical_hold: str                 # human-readable holding period
    default_stop_pct: Optional[float]
    default_target_pct: Optional[float]
    trezo_layer: Optional[int]        # which Woven Basket layer it serves
    maps_to: Optional[str]            # existing Trezo strategy module, if any
    source: str

    def to_dict(self) -> dict:
        return asdict(self)


# --- The curated core set --------------------------------------------

LIBRARY: tuple[StrategyCard, ...] = (
    StrategyCard(
        id="ma_crossover",
        name="Moving-Average Crossover",
        family="trend",
        thesis="Ride sustained trends: go long when a fast moving average "
               "crosses above a slow one, and step aside when it crosses back.",
        signals=("EMA fast/slow", "ADX trend strength"),
        best_regimes=("trending_up", "trending_down"),
        avoid_regimes=("choppy",),
        risk_profile="moderate",
        typical_hold="days to weeks",
        default_stop_pct=8.0,
        default_target_pct=20.0,
        trezo_layer=None,
        maps_to="pattern",
        source="Chan, Quantitative Trading (2008)",
    ),
    StrategyCard(
        id="relative_strength_momentum",
        name="Relative-Strength Momentum",
        family="momentum",
        thesis="Buy the strongest names over the last 3-12 months; winners "
               "tend to keep winning until the trend breaks.",
        signals=("3/6/12-month return", "cross-sectional rank"),
        best_regimes=("trending_up",),
        avoid_regimes=("risk_off", "high_volatility"),
        risk_profile="moderate",
        typical_hold="weeks to months",
        default_stop_pct=10.0,
        default_target_pct=25.0,
        trezo_layer=None,
        maps_to=None,
        source="Jegadeesh & Titman; QuantConnect strategy library",
    ),
    StrategyCard(
        id="rsi2_mean_reversion",
        name="RSI(2) Mean Reversion",
        family="mean_reversion",
        thesis="Buy short-term oversold dips inside a longer uptrend and "
               "sell the bounce a few days later.",
        signals=("RSI(2)", "200-day moving-average filter"),
        best_regimes=("choppy", "low_volatility"),
        avoid_regimes=("trending_down", "risk_off"),
        risk_profile="moderate",
        typical_hold="1-5 days",
        default_stop_pct=5.0,
        default_target_pct=8.0,
        trezo_layer=None,
        maps_to="crypto",
        source="Connors & Alvarez, Short Term Trading Strategies",
    ),
    StrategyCard(
        id="bollinger_reversion",
        name="Bollinger Band Reversion",
        family="mean_reversion",
        thesis="Fade stretched moves to the outer Bollinger band back "
               "toward the moving-average mean.",
        signals=("Bollinger %B", "bandwidth"),
        best_regimes=("choppy", "low_volatility"),
        avoid_regimes=("high_volatility", "trending_down"),
        risk_profile="moderate",
        typical_hold="1-5 days",
        default_stop_pct=6.0,
        default_target_pct=8.0,
        trezo_layer=None,
        maps_to="crypto",
        source="Bollinger on Bollinger Bands; Composer strategy library",
    ),
    StrategyCard(
        id="donchian_breakout",
        name="Donchian Channel Breakout",
        family="breakout",
        thesis="Enter when price breaks a 20/55-day high — the classic "
               "trend-following turtle entry.",
        signals=("Donchian high/low", "ATR"),
        best_regimes=("trending_up", "high_volatility"),
        avoid_regimes=("choppy",),
        risk_profile="moderate",
        typical_hold="weeks",
        default_stop_pct=10.0,
        default_target_pct=30.0,
        trezo_layer=None,
        maps_to="pattern",
        source="Turtle Traders; Chan (2008)",
    ),
    StrategyCard(
        id="opening_gap_momentum",
        name="Opening-Gap Momentum",
        family="momentum",
        thesis="Trade small-caps gapping up hard on heavy volume in the "
               "first hour of the session.",
        signals=("pre-market gap %", "relative volume", "float"),
        best_regimes=("trending_up", "high_volatility"),
        avoid_regimes=("risk_off",),
        risk_profile="aggressive",
        typical_hold="minutes to hours",
        default_stop_pct=5.0,
        default_target_pct=10.0,
        trezo_layer=2,
        maps_to="stms",
        source="STMS spec; day-trading canon",
    ),
    StrategyCard(
        id="vwap_reversion",
        name="VWAP Reversion",
        family="mean_reversion",
        thesis="Intraday: buy dips below VWAP and sell rallies above it "
               "when no strong trend is in control.",
        signals=("VWAP distance", "volume"),
        best_regimes=("choppy",),
        avoid_regimes=("trending_down", "high_volatility"),
        risk_profile="moderate",
        typical_hold="intraday",
        default_stop_pct=3.0,
        default_target_pct=5.0,
        trezo_layer=None,
        maps_to=None,
        source="Intraday execution canon",
    ),
    StrategyCard(
        id="post_earnings_drift",
        name="Post-Earnings-Announcement Drift (PEAD)",
        family="event_driven",
        thesis="After a large earnings surprise, price keeps drifting the "
               "same direction for several weeks.",
        signals=("earnings surprise %", "reaction gap", "volume"),
        best_regimes=("trending_up", "low_volatility"),
        avoid_regimes=("risk_off",),
        risk_profile="moderate",
        typical_hold="2-8 weeks",
        default_stop_pct=8.0,
        default_target_pct=20.0,
        trezo_layer=None,
        maps_to=None,
        source="Bernard & Thomas; NYU Glucksman research",
    ),
    StrategyCard(
        id="news_catalyst_momentum",
        name="News-Catalyst Momentum",
        family="event_driven",
        thesis="Trade the short-term drift after a confirmed material "
               "headline — M&A, guidance, approvals, contract wins.",
        signals=("headline sentiment", "volume spike", "reaction gap"),
        best_regimes=("high_volatility", "trending_up"),
        avoid_regimes=("risk_off",),
        risk_profile="aggressive",
        typical_hold="hours to days",
        default_stop_pct=6.0,
        default_target_pct=12.0,
        trezo_layer=None,
        maps_to=None,
        source="Event-driven trading literature",
    ),
    StrategyCard(
        id="dividend_capture",
        name="Dividend Capture",
        family="event_driven",
        thesis="Hold a quality payer across its ex-dividend date to collect "
               "the distribution, then exit once the price recovers.",
        signals=("ex-dividend calendar", "yield", "price stability"),
        best_regimes=("low_volatility",),
        avoid_regimes=("high_volatility", "risk_off"),
        risk_profile="conservative",
        typical_hold="days",
        default_stop_pct=5.0,
        default_target_pct=4.0,
        trezo_layer=6,
        maps_to=None,
        source="Income-strategy canon; Fidelity research",
    ),
    StrategyCard(
        id="covered_call_wheel",
        name="Cash-Secured Put / Covered-Call Wheel",
        family="income",
        thesis="Sell cash-secured puts on names worth owning; if assigned, "
               "sell covered calls — collecting premium on every cycle.",
        signals=("implied volatility", "~0.30-delta strikes", "support"),
        best_regimes=("low_volatility", "trending_up"),
        avoid_regimes=("trending_down", "high_volatility"),
        risk_profile="conservative",
        typical_hold="monthly cycle",
        default_stop_pct=None,
        default_target_pct=None,
        trezo_layer=5,
        maps_to="wheel",
        source="TREZO_STRATEGY_RULES.md section 3",
    ),
    StrategyCard(
        id="volatility_contraction",
        name="Volatility-Contraction Breakout (VCP)",
        family="volatility",
        thesis="Buy tight, low-volatility consolidations as they break out "
               "on expanding volume.",
        signals=("ATR contraction", "base tightness", "volume dry-up"),
        best_regimes=("low_volatility", "trending_up"),
        avoid_regimes=("high_volatility", "choppy"),
        risk_profile="moderate",
        typical_hold="weeks",
        default_stop_pct=8.0,
        default_target_pct=24.0,
        trezo_layer=None,
        maps_to="pattern",
        source="Minervini; QuantConnect strategy library",
    ),
    StrategyCard(
        id="sector_rotation",
        name="Sector Rotation",
        family="rotation",
        thesis="Rotate capital into the leading sectors and out of the "
               "laggards on a monthly cadence.",
        signals=("sector relative strength", "market breadth"),
        best_regimes=("trending_up", "trending_down"),
        avoid_regimes=("choppy",),
        risk_profile="moderate",
        typical_hold="monthly",
        default_stop_pct=12.0,
        default_target_pct=30.0,
        trezo_layer=None,
        maps_to=None,
        source="Composer strategy library; Fidelity sector research",
    ),
    StrategyCard(
        id="pairs_trading",
        name="Statistical Pairs Trading",
        family="arbitrage",
        thesis="Trade the spread between two correlated names — long the "
               "laggard, short the leader — staying market-neutral.",
        signals=("cointegration", "spread z-score"),
        best_regimes=("choppy", "risk_off"),
        avoid_regimes=("trending_up",),
        risk_profile="moderate",
        typical_hold="days to weeks",
        default_stop_pct=6.0,
        default_target_pct=8.0,
        trezo_layer=None,
        maps_to=None,
        source="Chan; SSRN statistical-arbitrage literature",
    ),
    StrategyCard(
        id="quality_trend_core",
        name="Quality-Trend Core Holding",
        family="trend",
        thesis="Hold quality, low-beta names while price stays above its "
               "long-term trend; step aside when that trend breaks.",
        signals=("200-day moving average", "beta", "fundamental quality"),
        best_regimes=("trending_up", "low_volatility"),
        avoid_regimes=("risk_off",),
        risk_profile="conservative",
        typical_hold="months",
        default_stop_pct=15.0,
        default_target_pct=40.0,
        trezo_layer=7,
        maps_to=None,
        source="Long-horizon allocation canon",
    ),
)

_BY_ID: dict[str, StrategyCard] = {c.id: c for c in LIBRARY}


# --- Lookups ----------------------------------------------------------

def all_strategies() -> tuple[StrategyCard, ...]:
    return LIBRARY


def get_strategy(strategy_id: str) -> Optional[StrategyCard]:
    return _BY_ID.get(strategy_id)


def by_family(family: str) -> list[StrategyCard]:
    return [c for c in LIBRARY if c.family == family]


def for_regime(regime: str) -> list[StrategyCard]:
    """Strategies whose edge tends to hold up in the given regime."""
    return [c for c in LIBRARY if regime in c.best_regimes]


def avoided_in(regime: str) -> list[StrategyCard]:
    """Strategies that tend to fail in the given regime."""
    return [c for c in LIBRARY if regime in c.avoid_regimes]


def for_layer(layer: int) -> list[StrategyCard]:
    return [c for c in LIBRARY if c.trezo_layer == layer]


def maps_to(module: str) -> list[StrategyCard]:
    """Library cards backed by a live Trezo strategy module."""
    return [c for c in LIBRARY if c.maps_to == module]


# --- Regime playbook --------------------------------------------------
# When the Adaptive Scope engine classifies the market into a regime,
# this is its rulebook: which families to lean into, which to trade
# smaller, and which to stop entering entirely.

@dataclass(frozen=True)
class RegimePlay:
    regime: str
    summary: str
    favor: tuple[str, ...]    # families to lean into
    reduce: tuple[str, ...]   # families to trade at reduced size
    pause: tuple[str, ...]    # families to stop entering

    def to_dict(self) -> dict:
        return asdict(self)


REGIME_PLAYBOOK: dict[str, RegimePlay] = {
    "trending_up": RegimePlay(
        regime="trending_up",
        summary="Broad uptrend — let winners run, lean into strength.",
        favor=("trend", "momentum", "breakout"),
        reduce=("mean_reversion",),
        pause=(),
    ),
    "trending_down": RegimePlay(
        regime="trending_down",
        summary="Sustained downtrend — defend capital, avoid catching knives.",
        favor=("arbitrage",),
        reduce=("trend", "mean_reversion"),
        pause=("momentum", "breakout", "income"),
    ),
    "choppy": RegimePlay(
        regime="choppy",
        summary="Directionless chop — fade extremes, distrust breakouts.",
        favor=("mean_reversion", "arbitrage"),
        reduce=("trend", "momentum"),
        pause=("breakout",),
    ),
    "high_volatility": RegimePlay(
        regime="high_volatility",
        summary="Elevated volatility — size down, widen stops, be selective.",
        favor=("event_driven",),
        reduce=("trend", "momentum", "mean_reversion"),
        pause=("breakout",),
    ),
    "low_volatility": RegimePlay(
        regime="low_volatility",
        summary="Calm, low-volatility market — favor income and clean trends.",
        favor=("income", "volatility", "trend"),
        reduce=(),
        pause=(),
    ),
    "risk_off": RegimePlay(
        regime="risk_off",
        summary="Risk-off — capital preservation first; only market-neutral edges.",
        favor=("arbitrage",),
        reduce=("trend",),
        pause=("momentum", "breakout", "event_driven", "income"),
    ),
}


def playbook_for(regime: str) -> Optional[RegimePlay]:
    return REGIME_PLAYBOOK.get(regime)


# --- Digest -----------------------------------------------------------

def summarize(regime: Optional[str] = None) -> str:
    """A compact text digest of the library — handy to drop into an agent
    message or reasoning step. With a regime, narrows to fitting strategies."""
    lines = [f"Trezo Strategy Library v{LIBRARY_VERSION} — {len(LIBRARY)} strategies."]
    if regime:
        play = playbook_for(regime)
        if play:
            lines.append(f"Regime '{regime}': {play.summary}")
            lines.append(f"  favor: {', '.join(play.favor) or 'none'}")
            lines.append(f"  reduce: {', '.join(play.reduce) or 'none'}")
            lines.append(f"  pause: {', '.join(play.pause) or 'none'}")
        cards = for_regime(regime)
        lines.append(f"Strategies suited to a '{regime}' market:")
    else:
        cards = list(LIBRARY)
    for c in cards:
        lines.append(f"  - {c.name} [{c.family}] — {c.thesis}")
    return "\n".join(lines)
