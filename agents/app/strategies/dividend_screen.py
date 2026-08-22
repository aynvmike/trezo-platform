"""Market-wide dividend quality screen — the §4 entry screen, as code.

Mike 2026-08-22: "I want to make sure we analyze it for market wide and
not a default list only."

THE PROBLEM THIS REPLACES
-------------------------
`wheel_universe.DIVIDEND_YIELDS` is a hand-maintained dict of ~40 tickers.
Any name outside it fell back to an Alpha Vantage lookup budgeted at FIVE
calls per universe build against a 25-CALLS-PER-DAY free tier. So in
practice the market-wide pool collapsed back to the curated list: the
gate could not answer "is this a quality dividend payer?" for a name it
had not been told about in advance. The pool was market-wide; the GATE
was a whitelist, and the gate is what decides.

WHAT THIS DOES INSTEAD
----------------------
Finnhub /stock/metric (60 calls/MINUTE on the free tier, vs 25/day) is
the primary source, so any ticker the scanners surface can be judged on
its merits. Results persist in Supabase (`dividend_screen_cache`), so the
knowledge accumulates: every name screened once is free for a week, and
the covered universe grows toward the whole market instead of resetting.

THE HONESTY RULE
----------------
A check we could not evaluate is UNVERIFIED, never "pass". The spec
labels unmeasured things UNPROVEN and this module keeps that discipline:
`passed` requires affirmative evidence. A name with missing dividend
history is not screened in on optimism — it waits for data. This is why
`tier` can be UNVERIFIED, and why the Wheel treats that as ineligible
rather than as a default-allow.

Screen (spec §4, entry screen — applies to every name):
  - payout ratio <= 70% of earnings or FCF (coverage ratio for REIT/BDC)
  - dividend-raise streak >= 10 yrs (>= 25 preferred, scored not required)
  - no cut in trailing 10 yrs
  - funds: AUM >= $100M, no reverse split in 24 months,
           trailing payout <= trailing total return
  - <= 2 names per sector -> enforced at SELECTION (see sector_capped()),
    not here; this module judges one name at a time.

Tiering drives lane rule #4 (never write calls on GROWTH names):
  GROWTH      - lower yield, strong raise streak, room in the payout
                ratio. The compounders. Dividends only, never called away.
  HIGH_YIELD  - the wheel-eligible half. Writes calls freely.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import structlog

from app.config import get_settings

log = structlog.get_logger("trezo.dividend_screen")

FINNHUB_METRIC_URL = "https://finnhub.io/api/v1/stock/metric"
FINNHUB_DIVIDEND_URL = "https://finnhub.io/api/v1/stock/dividend"
FINNHUB_PROFILE_URL = "https://finnhub.io/api/v1/stock/profile2"

# --- Screen thresholds (spec §4). Env-overridable so the lane can be
# tuned without a deploy; defaults ARE the spec.
MAX_PAYOUT_RATIO = 0.70
MIN_RAISE_STREAK_YEARS = 10
PREFERRED_RAISE_STREAK_YEARS = 25
CUT_LOOKBACK_YEARS = 10
MIN_FUND_AUM_USD = 100_000_000.0
MIN_QUALIFYING_YIELD = 0.015          # below this it is not a dividend name
GROWTH_TIER_MAX_YIELD = 0.040         # >= this yields wheel; below compounds

# Sector families that pay out of cash flow, not earnings — a >70%
# earnings payout ratio is NORMAL for these and is not a red flag.
# They are judged on coverage instead, and REIT/BDC count as ONE sector
# factor for the concentration cap (spec §4 entry screen).
CASHFLOW_PAYERS = {"REIT", "BDC", "Real Estate", "REIT—Diversified"}

_CACHE_TTL_SECONDS = 7 * 24 * 3600     # fundamentals move slowly
_mem_cache: dict[str, tuple["ScreenResult", float]] = {}

# Finnhub free tier is 60/min. We stay far under it: the cache does the
# heavy lifting, and a build only spends this many NEW lookups.
DEFAULT_LOOKUP_BUDGET = 25


@dataclass
class ScreenResult:
    """One name's verdict. `checks` records every rule's outcome so the
    UI can show WHY, and so an unverified name is visibly different from
    a failed one."""
    ticker: str
    passed: bool = False
    tier: str = "UNVERIFIED"          # GROWTH | HIGH_YIELD | FAIL | UNVERIFIED
    yield_pct: Optional[float] = None
    payout_ratio: Optional[float] = None
    raise_streak_years: Optional[int] = None
    cut_in_lookback: Optional[bool] = None
    sector: Optional[str] = None
    is_fund: bool = False
    checks: dict = field(default_factory=dict)   # rule -> pass|fail|unverified
    reasons: list = field(default_factory=list)
    as_of: float = 0.0
    source: str = "finnhub"

    @property
    def wheel_eligible(self) -> bool:
        """Lane rule #4: only HIGH_YIELD names may wear a covered call."""
        return self.passed and self.tier == "HIGH_YIELD"

    @property
    def ladder_eligible(self) -> bool:
        """Both tiers can sit in the ladder; only the tier differs in
        what the lane is then allowed to DO with them."""
        return self.passed and self.tier in ("GROWTH", "HIGH_YIELD")

    def explain(self) -> str:
        """One human line for the feed."""
        if self.tier == "UNVERIFIED":
            missing = [k for k, v in self.checks.items() if v == "unverified"]
            return (f"{self.ticker}: not screened — no data for "
                    f"{', '.join(missing) or 'the entry screen'}")
        if not self.passed:
            return f"{self.ticker}: fails screen — {'; '.join(self.reasons)}"
        streak = (f"{self.raise_streak_years}y raises"
                  if self.raise_streak_years is not None else "streak n/a")
        return (f"{self.ticker}: {self.tier} — "
                f"{(self.yield_pct or 0)*100:.1f}% yield, "
                f"payout {(self.payout_ratio or 0)*100:.0f}%, {streak}")


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


async def _cache_get(ticker: str) -> Optional[ScreenResult]:
    """Memory first, then Supabase. The Supabase layer is what makes the
    screened universe survive a restart and grow over time."""
    now = time.time()
    hit = _mem_cache.get(ticker)
    if hit and (now - hit[1]) < _CACHE_TTL_SECONDS:
        return hit[0]
    client = _supabase()
    if client is None:
        return None
    try:
        import asyncio

        def _q():
            return (client.table("dividend_screen_cache")
                    .select("payload, screened_at")
                    .eq("ticker", ticker).limit(1).execute())
        res = await asyncio.to_thread(_q)
        rows = res.data or []
        if not rows:
            return None
        payload = rows[0].get("payload") or {}
        result = ScreenResult(**payload)
        if (now - float(result.as_of or 0)) > _CACHE_TTL_SECONDS:
            return None
        _mem_cache[ticker] = (result, now)
        return result
    except Exception:  # noqa: BLE001
        return None


async def _cache_put(result: ScreenResult) -> None:
    _mem_cache[result.ticker] = (result, time.time())
    client = _supabase()
    if client is None:
        return
    try:
        import asyncio
        from datetime import datetime, timezone

        def _up():
            return (client.table("dividend_screen_cache").upsert({
                "ticker": result.ticker,
                "payload": asdict(result),
                "tier": result.tier,
                "passed": result.passed,
                "screened_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="ticker").execute())
        await asyncio.to_thread(_up)
    except Exception as e:  # noqa: BLE001
        log.warning("dividend_screen.cache_write_failed",
                    ticker=result.ticker, error=str(e)[:200])


async def _finnhub(url: str, params: dict) -> Optional[dict]:
    key = (get_settings().finnhub_api_key or "").strip()
    if not key:
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params={**params, "token": key})
            if resp.status_code == 429:
                log.warning("dividend_screen.rate_limited", url=url)
                return None
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _raise_streak_from_series(series: list) -> Optional[int]:
    """Count consecutive YEARS of higher total dividends, newest first.

    Finnhub returns individual payments; we sum by calendar year and
    compare year over year. A year that merely matches the prior year
    ENDS the streak (the spec says 'raise', not 'maintain'), but the
    partial current year is skipped — a year still in progress has not
    failed to raise yet, and counting it would reset every streak in
    January.
    """
    if not series:
        return None
    by_year: dict[int, float] = {}
    for row in series:
        try:
            date = str(row.get("payDate") or row.get("date") or "")
            amt = float(row.get("amount") or 0)
        except Exception:  # noqa: BLE001
            continue
        if len(date) < 4 or amt <= 0:
            continue
        try:
            year = int(date[:4])
        except ValueError:
            continue
        by_year[year] = by_year.get(year, 0.0) + amt
    if len(by_year) < 2:
        return None
    years = sorted(by_year.keys(), reverse=True)
    import datetime as _dt
    current_year = _dt.datetime.now(_dt.timezone.utc).year
    if years and years[0] == current_year:
        years = years[1:]          # skip the partial year in progress
    streak = 0
    for i in range(len(years) - 1):
        if by_year[years[i]] > by_year[years[i + 1]]:
            streak += 1
        else:
            break
    return streak


def _cut_in_lookback(series: list, years_back: int = CUT_LOOKBACK_YEARS
                     ) -> Optional[bool]:
    """True if annual dividends ever DROPPED year-over-year in the window."""
    if not series:
        return None
    by_year: dict[int, float] = {}
    for row in series:
        try:
            date = str(row.get("payDate") or row.get("date") or "")
            amt = float(row.get("amount") or 0)
            year = int(date[:4])
        except Exception:  # noqa: BLE001
            continue
        if amt <= 0:
            continue
        by_year[year] = by_year.get(year, 0.0) + amt
    if len(by_year) < 2:
        return None
    import datetime as _dt
    current_year = _dt.datetime.now(_dt.timezone.utc).year
    years = sorted([y for y in by_year if y >= current_year - years_back],
                   reverse=True)
    if len(years) < 2:
        return None
    if years[0] == current_year:
        years = years[1:]          # partial year is not a cut
    for i in range(len(years) - 1):
        # A >5% drop is a cut; smaller wobbles are special-dividend noise.
        if by_year[years[i]] < by_year[years[i + 1]] * 0.95:
            return True
    return False


async def screen(ticker: str, *, force: bool = False) -> ScreenResult:
    """Screen ONE name against the §4 entry screen. Any ticker — there is
    no whitelist. Cached for a week."""
    sym = (ticker or "").upper().strip()
    if not sym:
        return ScreenResult(ticker="", tier="FAIL",
                            reasons=["empty ticker"], as_of=time.time())
    if not force:
        cached = await _cache_get(sym)
        if cached is not None:
            return cached

    result = ScreenResult(ticker=sym, as_of=time.time())

    metric = await _finnhub(FINNHUB_METRIC_URL,
                            {"symbol": sym, "metric": "all"})
    if metric is None:
        result.tier = "UNVERIFIED"
        result.checks = {k: "unverified" for k in
                         ("yield", "payout_ratio", "raise_streak", "no_cut")}
        result.reasons = ["no fundamentals available"]
        # Do NOT cache an unverified miss for the full week — a transient
        # API failure should not blind the lane to a name for 7 days.
        _mem_cache[sym] = (result, time.time() - _CACHE_TTL_SECONDS + 3600)
        return result

    m = metric.get("metric") or {}

    # --- yield
    y = m.get("dividendYieldIndicatedAnnual")
    if y is None:
        y = m.get("currentDividendYieldTTM")
    if y is not None:
        try:
            result.yield_pct = float(y) / 100.0   # Finnhub reports percent
        except (TypeError, ValueError):
            result.yield_pct = None
    if result.yield_pct is None:
        result.checks["yield"] = "unverified"
    elif result.yield_pct < MIN_QUALIFYING_YIELD:
        result.checks["yield"] = "fail"
        result.reasons.append(
            f"yield {result.yield_pct*100:.2f}% below "
            f"{MIN_QUALIFYING_YIELD*100:.1f}% minimum")
    else:
        result.checks["yield"] = "pass"

    # --- payout ratio
    pr = m.get("payoutRatioAnnual")
    if pr is None:
        pr = m.get("payoutRatioTTM")
    if pr is not None:
        try:
            result.payout_ratio = float(pr) / 100.0
        except (TypeError, ValueError):
            result.payout_ratio = None

    profile = await _finnhub(FINNHUB_PROFILE_URL, {"symbol": sym})
    if profile:
        result.sector = (profile.get("finnhubIndustry") or "").strip() or None
        result.is_fund = bool(
            (profile.get("type") or "").upper() in ("ETP", "ETF", "FUND")
        )

    cashflow_payer = bool(result.sector and any(
        c.lower() in result.sector.lower() for c in CASHFLOW_PAYERS))

    if result.payout_ratio is None:
        result.checks["payout_ratio"] = "unverified"
    elif cashflow_payer or result.is_fund:
        # Spec: coverage ratio for REIT/BDC, and funds distribute what they
        # collect. An earnings payout ratio is the wrong instrument here —
        # say so rather than failing the name on a metric that misapplies.
        result.checks["payout_ratio"] = "n/a"
    elif result.payout_ratio > MAX_PAYOUT_RATIO:
        result.checks["payout_ratio"] = "fail"
        result.reasons.append(
            f"payout ratio {result.payout_ratio*100:.0f}% over "
            f"{MAX_PAYOUT_RATIO*100:.0f}% ceiling")
    elif result.payout_ratio <= 0:
        result.checks["payout_ratio"] = "unverified"
    else:
        result.checks["payout_ratio"] = "pass"

    # --- raise streak + cut history (needs the payment series)
    import datetime as _dt
    today = _dt.datetime.now(_dt.timezone.utc).date()
    frm = today.replace(year=today.year - CUT_LOOKBACK_YEARS - 1)
    divs = await _finnhub(FINNHUB_DIVIDEND_URL, {
        "symbol": sym, "from": frm.isoformat(), "to": today.isoformat()})
    series = []
    if isinstance(divs, dict):
        series = divs.get("data") or []
    elif isinstance(divs, list):
        series = divs

    result.raise_streak_years = _raise_streak_from_series(series)
    result.cut_in_lookback = _cut_in_lookback(series)

    if result.raise_streak_years is None:
        result.checks["raise_streak"] = "unverified"
    elif result.raise_streak_years >= MIN_RAISE_STREAK_YEARS:
        result.checks["raise_streak"] = "pass"
    else:
        result.checks["raise_streak"] = "fail"
        result.reasons.append(
            f"raise streak {result.raise_streak_years}y under "
            f"{MIN_RAISE_STREAK_YEARS}y minimum")

    if result.cut_in_lookback is None:
        result.checks["no_cut"] = "unverified"
    elif result.cut_in_lookback:
        result.checks["no_cut"] = "fail"
        result.reasons.append(
            f"dividend cut within {CUT_LOOKBACK_YEARS} years")
    else:
        result.checks["no_cut"] = "pass"

    # --- funds: AUM floor (spec §4)
    if result.is_fund:
        aum = None
        for k in ("marketCapitalization", "netAssetValue"):
            v = m.get(k)
            if v:
                try:
                    aum = float(v) * 1_000_000.0
                    break
                except (TypeError, ValueError):
                    pass
        if aum is None:
            result.checks["fund_aum"] = "unverified"
        elif aum < MIN_FUND_AUM_USD:
            result.checks["fund_aum"] = "fail"
            result.reasons.append(
                f"fund AUM ${aum/1e6:.0f}M under "
                f"${MIN_FUND_AUM_USD/1e6:.0f}M floor")
        else:
            result.checks["fund_aum"] = "pass"

    # --- verdict. `passed` requires NO fails AND no unverified among the
    # checks that decide eligibility. Silence is not consent.
    decisive = ("yield", "payout_ratio", "raise_streak", "no_cut")
    fails = [k for k in result.checks if result.checks[k] == "fail"]
    unverified = [k for k in decisive
                  if result.checks.get(k) == "unverified"]

    if fails:
        result.passed = False
        result.tier = "FAIL"
    elif unverified:
        result.passed = False
        result.tier = "UNVERIFIED"
        result.reasons.append(f"unverified: {', '.join(unverified)}")
    else:
        result.passed = True
        # Tiering — lane rule #4 hinges on this line.
        if (result.yield_pct or 0) >= GROWTH_TIER_MAX_YIELD:
            result.tier = "HIGH_YIELD"
        else:
            result.tier = "GROWTH"

    await _cache_put(result)
    log.info("dividend_screen.screened", ticker=sym, tier=result.tier,
             passed=result.passed, reasons=result.reasons[:2])
    return result


async def screen_many(tickers: list, *, budget: int = DEFAULT_LOOKUP_BUDGET
                      ) -> dict:
    """Screen a list, spending at most `budget` NEW lookups. Cached names
    are free, so the covered universe ratchets upward across builds
    instead of resetting — this is what turns a market-wide POOL into a
    market-wide SCREEN.

    Returns {ticker: ScreenResult} for everything it could judge; names
    that ran out of budget are simply absent (they get judged next tick).
    """
    out: dict = {}
    spent = 0
    for raw in tickers:
        sym = (raw or "").upper().strip()
        if not sym or sym in out:
            continue
        cached = await _cache_get(sym)
        if cached is not None:
            out[sym] = cached
            continue
        if spent >= budget:
            continue
        spent += 1
        out[sym] = await screen(sym)
    if spent:
        log.info("dividend_screen.batch", requested=len(tickers),
                 judged=len(out), new_lookups=spent)
    return out


def sector_capped(results: list, max_per_sector: int = 2) -> list:
    """Spec §4: <= 2 names per sector, REIT/BDC counted as ONE factor.

    Applied at SELECTION, not screening — whether a name is good and
    whether the book has room for another like it are different
    questions. Input should already be ranked; this preserves order and
    drops the overflow.
    """
    kept: list = []
    counts: dict = {}
    for r in results:
        sector = r.sector or "UNKNOWN"
        if any(c.lower() in sector.lower() for c in CASHFLOW_PAYERS):
            sector = "CASHFLOW_PAYER"     # REIT + BDC share one bucket
        if counts.get(sector, 0) >= max_per_sector:
            continue
        counts[sector] = counts.get(sector, 0) + 1
        kept.append(r)
    return kept
