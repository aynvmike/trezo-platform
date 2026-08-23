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
# Finnhub returns NO market cap / NAV for funds on this tier (see the
# fund branch below: an ETF comes back with 19 price-technical keys and
# not one company fundamental), so the spec's AUM floor is not directly
# measurable. Average daily DOLLAR VOLUME is measurable, and it answers
# the question the AUM floor was actually asked to answer -- can this
# lane get in and out without wearing the spread. Named for what it is
# rather than dressed up as AUM.
MIN_FUND_DOLLAR_VOLUME = 2_000_000.0
MIN_QUALIFYING_YIELD = 0.015          # below this it is not a dividend name
GROWTH_TIER_MAX_YIELD = 0.040         # >= this yields wheel; below compounds

# --- The raise-streak PROXY (2026-08-23, found by the 3-month replay).
#
# The spec asks for a >= 10-year raise streak and no cut in 10 years.
# Both need the DIVIDEND PAYMENT SERIES, and Finnhub's /stock/dividend
# is NOT on this account's tier -- it answers "you don't have access to
# this resource". The first version of this module treated that as
# UNVERIFIED, which is honest but had a consequence nobody saw until the
# replay ran it: EVERY name came back UNVERIFIED, so `passed` was never
# true and the screen admitted NOTHING. A gate that blocks everything is
# not a strict gate, it is a broken one.
#
# `dividendGrowthRate5Y` IS available and stands in -- with two guards,
# because the raw number inverts the rule it is proxying:
#
#   REINSTATEMENT ARTIFACT. A company that cut to zero and restarted, or
#   initiated a dividend recently, shows an astronomical 5Y CAGR off a
#   near-zero base. In the replay TMUS printed 123.7% and F 38.1% --
#   and the ranking duly put both at the TOP of the ladder. Those are
#   precisely the names "no cut in 10 years" exists to exclude. Any
#   growth rate above MAX_PLAUSIBLE_GROWTH is read as an artifact, not
#   as excellence.
#
#   SHRINKING NOW. A 5Y average can stay positive while the CURRENT
#   payout falls. Ford's TTM dividend/share sat BELOW its annual figure.
#   So the trailing payment is compared against the annual rate too.
MAX_PLAUSIBLE_GROWTH = 0.25   # >25%/yr for 5 straight years is an artifact
MIN_TTM_VS_ANNUAL = 0.95      # TTM below 95% of annual = shrinking now

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
    dividend_growth_5y: Optional[float] = None
    next_ex_date: Optional[str] = None
    last_dividend_rate: Optional[float] = None
    window_years: Optional[int] = None
    sector: Optional[str] = None
    is_fund: bool = False
    # Fund-only evidence (spec §4's fund rule). Kept on the result so
    # the UI can show the actual arithmetic behind "this fund is paying
    # you back your own capital" -- a claim that has to show its work.
    dist_yield: Optional[float] = None
    trailing_total_return: Optional[float] = None
    reverse_split_24m: bool = False
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
        # Finnhub is down, rate-limited (60/min, and each name costs TWO
        # calls), or the key is missing.
        #
        # We deliberately do NOT fall through to the Alpaca-only path
        # here, even though Alpaca could answer most of it. Without the
        # metric payload there is no way to tell a FUND from a COMPANY:
        # the discriminator is WHICH company fundamentals are absent, and
        # an outage makes ALL of them absent. Guessing would route stocks
        # through the fund rule and funds through the raise-streak rule —
        # the exact category error this screen was just fixed for. Saying
        # "not measured" is the smaller failure.
        result.tier = "UNVERIFIED"
        # These keys must stay in step with `decisive` below; they were
        # out of step ("raise_streak", "no_cut") since the trend checks
        # were consolidated, which made this branch's checks dict a dead
        # letter that no downstream reader could match.
        result.checks = {k: "unverified" for k in
                         ("yield", "payout_ratio", "dividend_trend")}
        result.reasons = ["no fundamentals available "
                          "(Finnhub unavailable or rate-limited)"]
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

    # --- dividend trend, from the REAL payment series.
    #
    # Alpaca's corporate-actions feed gives ex_date, rate and special
    # flags back to 2016, free, AND covers ETFs -- which is what finally
    # closed this gap. Finnhub's /stock/dividend is not on this tier and
    # its fundamentals do not cover funds at all, so SCHD/VYM/JEPI were
    # permanently UNVERIFIED under both earlier designs.
    from app.data.corporate_actions import dividend_profile

    price = None
    try:
        from app.data.candles import fetch_candles_for
        _c = await fetch_candles_for(sym, "stock")
        price = float(_c[-1].close) if _c else None
    except Exception:  # noqa: BLE001
        price = None

    prof = await dividend_profile(sym, price)
    result.next_ex_date = prof.get("next_ex_date")
    result.last_dividend_rate = prof.get("last_rate")
    result.window_years = prof.get("window_years")

    if prof.get("verified"):
        result.source = "alpaca:corporate_actions"

        # FUND DETECTION (2026-08-23). Finnhub's profile2 returns an
        # EMPTY object for ETFs, so `is_fund` stayed False and the
        # earnings payout ratio fell through to "unverified" -- which
        # blocked VYM and every other fund on a metric that does not
        # apply to them. A name that distributes cash but has no company
        # fundamentals at all is a fund; judging it on an earnings
        # payout ratio is the same category error the spec already names
        # for REITs.
        # Finnhub returns no payout ratio for funds (its profile2 gives
        # an empty object for ETFs), so VYM and DGRO were failing on a
        # metric that does not apply to them. When there is no payout
        # ratio BUT there is a verified multi-year payment record, the
        # payout ratio's actual question -- "is this dividend
        # sustainable?" -- has already been answered by a decade of
        # observed behaviour. Marked n/a rather than blocking, and the
        # dividend_trend check still has to pass on its own.
        if (result.payout_ratio is None
                and result.checks.get("payout_ratio") == "unverified"):
            result.checks["payout_ratio"] = "n/a"
            # A name that distributes cash but has NO issuer fundamentals
            # at all is a fund. Verified live 2026-08-23: Finnhub returns
            # exactly 19 keys for an ETF -- 52-week high/low, beta,
            # relative-strength, average volume -- and not one company
            # figure. Stocks come back with 126-133. So the discriminator
            # is not a `type` field (profile2 returns {} for funds on
            # this tier, which is why the old `if not m` test never fired
            # and every ETF was silently judged as a company).
            if (m.get("marketCapitalization") is None
                    and m.get("payoutRatioAnnual") is None
                    and m.get("payoutRatioTTM") is None
                    and m.get("dividendYieldIndicatedAnnual") is None):
                result.is_fund = True
        result.raise_streak_years = prof.get("raise_streak_years")
        result.cut_in_lookback = prof.get("had_cut")

        # ETF yield. Finnhub returns nothing for funds, so a distribution
        # yield computed from actual payments is the only yield they get.
        if result.yield_pct is None and prof.get("trailing_yield"):
            result.yield_pct = float(prof["trailing_yield"])
            result.checks["yield"] = (
                "pass" if result.yield_pct >= MIN_QUALIFYING_YIELD else "fail")
            if result.checks["yield"] == "fail":
                result.reasons.append(
                    f"trailing distribution yield "
                    f"{result.yield_pct*100:.2f}% below "
                    f"{MIN_QUALIFYING_YIELD*100:.1f}% minimum")

        streak = result.raise_streak_years
        window = int(prof.get("window_years") or 0)

        if result.is_fund:
            # ---- THE FUND RULE (spec §4: "for any fund: AUM >= $100M,
            # no reverse split in 24 months, trailing payout <= trailing
            # total return").
            #
            # Mike asked the question that found this: "is it going to
            # possibly do this to other Dividend Funds and not just fix
            # for REIT?" It was. Running the raise-streak rule over every
            # fund type failed SEVEN OF EIGHT covered-call ETFs -- JEPI,
            # QYLD, RYLD, XYLD, FEPI, NVDY, TSLY -- because a variable
            # distribution is their DESIGN, not a cut. NVDY paid 5.05,
            # then 19.53, then 12.14: that is option premium tracking
            # volatility, and reading it as a dividend cut is a category
            # error. It would have rejected the entire asset class the
            # original 24-fund capture study was built on.
            #
            # For a fund the question is not "did it raise every year"
            # but "IS THE DISTRIBUTION FUNDED BY RETURNS, OR IS IT EATING
            # NAV?" -- which is exactly the finding from that study: cash
            # yield near-uniform at ~17.6% across six positions while
            # total return ran -17.0% to +22.6%. The payout carried no
            # information about the outcome. THIS is the test that makes
            # the payout informative.
            from app.data.corporate_actions import fund_health
            fh = await fund_health(sym, price)
            result.dist_yield = fh.get("dist_yield")
            result.trailing_total_return = fh.get("trailing_total_return")
            result.reverse_split_24m = bool(fh.get("reverse_splits"))

            if not fh.get("verified"):
                result.checks["dividend_trend"] = "unverified"
            elif not fh.get("passed"):
                result.checks["dividend_trend"] = "fail"
                result.reasons.extend(fh.get("reasons") or [])
            else:
                result.checks["dividend_trend"] = "pass"
        else:
            # ---- THE COMPANY RULE. An operating business that cuts its
            # dividend has told you something about the business; a fund
            # whose distribution moved has told you about its inputs.
            # Different instruments, deliberately.
            #
            # The spec asks for a 10-year streak. Alpaca's history begins
            # in 2016, so ten COMPLETE years yield at most NINE
            # year-over-year comparisons -- a literal 10 is not yet
            # expressible and would reject every name on earth. The rule
            # is therefore "unbroken across everything visible, up to the
            # 10-year target", which is honest today and tightens on its
            # own as history accumulates.
            required = min(MIN_RAISE_STREAK_YEARS, max(0, window - 1))

            if streak is None or window < 3:
                result.checks["dividend_trend"] = "unverified"
            elif result.cut_in_lookback:
                result.checks["dividend_trend"] = "fail"
                result.reasons.append(
                    f"dividend was cut within the {window}-year record")
            elif streak >= required:
                result.checks["dividend_trend"] = "pass"
            else:
                result.checks["dividend_trend"] = "fail"
                result.reasons.append(
                    f"raise streak {streak}y under the {required}y required "
                    f"across a {window}-year record")
    else:
        # No corporate-actions history -> fall back to the growth-rate
        # proxy, with the guards that stop a reinstatement reading as a
        # raise streak. Clearly labelled so the difference is visible.
        result.source = "finnhub:growth_proxy"
        g = m.get("dividendGrowthRate5Y")
        dps_annual = m.get("dividendPerShareAnnual")
        dps_ttm = m.get("dividendPerShareTTM")
        try:
            growth = float(g) / 100.0 if g is not None else None
        except (TypeError, ValueError):
            growth = None
        result.dividend_growth_5y = growth

        if growth is None:
            result.checks["dividend_trend"] = "unverified"
        elif growth > MAX_PLAUSIBLE_GROWTH:
            result.checks["dividend_trend"] = "fail"
            result.reasons.append(
                f"5Y dividend growth {growth*100:.0f}% is implausible as a "
                f"sustained raise streak — reads as a reinstatement or a "
                f"recent initiation, which the no-cut rule excludes")
        elif growth < 0:
            result.checks["dividend_trend"] = "fail"
            result.reasons.append(
                f"5Y dividend growth {growth*100:.1f}% — the payout has "
                f"been shrinking, not raised")
        else:
            result.checks["dividend_trend"] = "pass"

        try:
            if (dps_annual and dps_ttm
                    and float(dps_ttm) < float(dps_annual) * MIN_TTM_VS_ANNUAL):
                result.checks["dividend_trend"] = "fail"
                result.reasons.append(
                    f"trailing dividend ${float(dps_ttm):.2f} is below the "
                    f"${float(dps_annual):.2f} annual rate — shrinking now")
        except (TypeError, ValueError):
            pass

    # --- funds: size floor (spec §4). AUM where we can get it, average
    # daily dollar volume where we cannot -- which on this tier is
    # always, because Finnhub returns no market cap or NAV for a fund.
    # The substitution is stated rather than hidden: a liquidity floor
    # and an AUM floor are not the same measurement, they merely fail
    # the same tiny funds.
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
        if aum is not None:
            if aum < MIN_FUND_AUM_USD:
                result.checks["fund_size"] = "fail"
                result.reasons.append(
                    f"fund AUM ${aum/1e6:.0f}M under "
                    f"${MIN_FUND_AUM_USD/1e6:.0f}M floor")
            else:
                result.checks["fund_size"] = "pass"
        else:
            dollar_vol = None
            try:
                # Finnhub reports this in MILLIONS of shares.
                vol_m = m.get("10DayAverageTradingVolume")
                if vol_m is not None and price:
                    dollar_vol = float(vol_m) * 1e6 * float(price)
            except (TypeError, ValueError):
                dollar_vol = None
            if dollar_vol is None:
                result.checks["fund_size"] = "unverified"
            elif dollar_vol < MIN_FUND_DOLLAR_VOLUME:
                result.checks["fund_size"] = "fail"
                result.reasons.append(
                    f"fund trades ${dollar_vol/1e6:.1f}M/day, under the "
                    f"${MIN_FUND_DOLLAR_VOLUME/1e6:.0f}M liquidity floor "
                    f"standing in for the AUM floor")
            else:
                result.checks["fund_size"] = "pass"

    # --- verdict. `passed` requires NO fails AND no unverified among the
    # checks that decide eligibility. Silence is not consent.
    # The decisive set is what this data tier can actually answer. It
    # deliberately does NOT include checks we have no source for: a gate
    # that waits forever on data that will never arrive blocks the whole
    # lane (which is exactly what shipped this morning).
    decisive = ("yield", "payout_ratio", "dividend_trend")
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
        # Funds get their OWN bucket. Finnhub returns no industry for a
        # fund, so before this every ETF fell into "UNKNOWN" -- sharing
        # one 2-slot bucket with any STOCK whose profile lookup happened
        # to fail. A network blip on one name could therefore evict a
        # fund from the ladder, which is a concentration cap enforcing
        # something that is not a concentration.
        if getattr(r, "is_fund", False):
            sector = "FUND"
        elif any(c.lower() in sector.lower() for c in CASHFLOW_PAYERS):
            sector = "CASHFLOW_PAYER"     # REIT + BDC share one bucket
        if counts.get(sector, 0) >= max_per_sector:
            continue
        counts[sector] = counts.get(sector, 0) + 1
        kept.append(r)
    return kept
