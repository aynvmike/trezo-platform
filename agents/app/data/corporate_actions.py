"""Dividend truth from Alpaca corporate actions — one source, real dates.

WHY THIS EXISTS (2026-08-23)
The §4 entry screen needs a dividend raise streak, a cut history, and an
ex-date. The first build asked Finnhub for the payment series and got
"you don't have access to this resource", so the screen admitted nothing.
The second build substituted `dividendGrowthRate5Y`, which INVERTS the
rule it proxies: a company that cut to zero and restarted shows a huge
5Y CAGR off a near-zero base, so TMUS (+124%) and Ford (+38%) ranked at
the TOP of a ladder whose screen exists to exclude exactly them.

Then the obvious question got asked -- can one source answer all of it --
and the answer was sitting in the broker we already pay attention to.
Alpaca's /v1/corporate-actions returns, free:

    ex_date, record_date, payable_date, rate, special, symbol

...back to at least 2016 (a full 10-year window for the streak and cut
rules), AND it covers ETFs, which Finnhub's fundamentals do not. SCHD,
VYM and JEPI all return distributions here while Finnhub's profile2
returns an empty object for them.

So this module replaces BOTH earlier approaches with the real series:
  - raise streak and cut history from actual payments, not a CAGR
  - trailing yield computed from actual distributions / price, which is
    the only way ETFs get a yield at all
  - the NEXT ex-date, which the wheel advisor's ex-date guard needs and
    was silently receiving as None

`special: true` payments are excluded from streak and trend maths on
purpose -- a one-off special dividend is not a raise, and counting it as
one would manufacture a streak that breaks the following year.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import time
from collections import defaultdict
from typing import Optional

import structlog

from app.config import get_settings

log = structlog.get_logger("trezo.corporate_actions")

CA_URL = "https://data.alpaca.markets/v1/corporate-actions"

# Payments barely change; a day of cache is generous and keeps the
# screen's per-build cost near zero.
_CACHE_TTL = 24 * 3600
_cache: dict[str, tuple[list, float]] = {}


def _auth() -> Optional[dict]:
    s = get_settings()
    key = getattr(s, "alpaca_api_key", "") or ""
    sec = getattr(s, "alpaca_secret_key", "") or ""
    if not key or not sec:
        return None
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}


async def dividend_history(symbol: str, years: int = 11) -> list:
    """Every cash dividend for `symbol` over the window, oldest first.

    Returns [] when the symbol genuinely pays nothing, and [] on failure
    too — callers must treat an empty list as "no evidence", never as
    "confirmed non-payer". The screen's UNVERIFIED path is what keeps
    that distinction honest.
    """
    sym = (symbol or "").upper().strip()
    if not sym:
        return []
    now = time.time()
    hit = _cache.get(sym)
    if hit and (now - hit[1]) < _CACHE_TTL:
        return hit[0]

    headers = _auth()
    if headers is None:
        return []

    today = _dt.datetime.now(_dt.timezone.utc).date()
    start = today.replace(year=today.year - years)
    # Look FORWARD as well. Announced-but-not-yet-reached ex-dates are
    # the entire point of the ex-date guard, and querying end=today
    # returned none of them -- which is why lane rule 3 was being handed
    # None on every call and could never fire.
    horizon = today + _dt.timedelta(days=150)
    rows: list = []
    page: Optional[str] = None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20.0) as client:
            while True:
                params = {
                    "symbols": sym, "types": "cash_dividend",
                    "start": start.isoformat(), "end": horizon.isoformat(),
                    "limit": 1000,
                }
                if page:
                    params["page_token"] = page
                r = await client.get(CA_URL, params=params, headers=headers)
                if r.status_code != 200:
                    log.warning("corporate_actions.http",
                                symbol=sym, status=r.status_code)
                    return []
                data = r.json() or {}
                block = (data.get("corporate_actions") or {})
                rows.extend(block.get("cash_dividends") or [])
                page = data.get("next_page_token")
                if not page:
                    break
    except Exception as e:  # noqa: BLE001
        log.warning("corporate_actions.failed", symbol=sym, error=str(e)[:160])
        return []

    rows.sort(key=lambda r: str(r.get("ex_date") or ""))
    # Restate every payment in today's shares BEFORE anything compares
    # two years to each other. Without this a 4-for-1 split reads as a
    # 75% dividend cut (see `splits` for the NextEra case).
    _apply_split_adjustment(rows, await splits(sym))
    _cache[sym] = (rows, now)
    return rows


_split_cache: dict[str, tuple[list, float]] = {}


async def splits(symbol: str, years: int = 12) -> list:
    """Every split — forward and reverse — over the window, oldest first.

    WHY THIS EXISTS (2026-08-23). Alpaca reports each dividend at the
    rate DECLARED AT THE TIME, unadjusted for later splits. NextEra split
    4-for-1 on 2020-10-27, so its payment series reads

        2019: 5.00   2020: 4.55   2021: 1.54

    and the cut rule saw a 66% dividend cut at a company that has raised
    every year for two decades. Nothing about the dividend changed; the
    share count did. Every name that has split is misread the same way,
    which is a whole cohort of quality payers silently excluded.
    """
    sym = (symbol or "").upper().strip()
    if not sym:
        return []
    now = time.time()
    hit = _split_cache.get(sym)
    if hit and (now - hit[1]) < _CACHE_TTL:
        return hit[0]
    headers = _auth()
    if headers is None:
        return []
    today = _dt.datetime.now(_dt.timezone.utc).date()
    start = today.replace(year=today.year - years)
    out: list = []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(CA_URL, headers=headers, params={
                "symbols": sym, "types": "forward_split,reverse_split",
                "start": start.isoformat(), "end": today.isoformat(),
                "limit": 500})
            if r.status_code != 200:
                return []
            block = (r.json() or {}).get("corporate_actions") or {}
            out = list(block.get("forward_splits") or [])
            out += list(block.get("reverse_splits") or [])
    except Exception as e:  # noqa: BLE001
        log.warning("corporate_actions.splits_failed",
                    symbol=sym, error=str(e)[:160])
        return []
    out.sort(key=lambda r: str(r.get("ex_date") or ""))
    _split_cache[sym] = (out, now)
    return out


def _apply_split_adjustment(rows: list, split_rows: list) -> None:
    """Stamp every dividend with `adj_rate` — the payment restated in
    TODAY's shares — and leave `rate` untouched as the declared figure.

    A dividend paid before a 4-for-1 split was paid on shares that later
    became four, so per today's share it was worth a quarter as much.
    Dividing by the product of every split ratio that came AFTER the
    payment puts the whole series on one comparable basis. Reverse splits
    fall out of the same arithmetic with a ratio below 1, which is what
    makes a fund's pre-reverse-split distribution look as large as it
    really was.
    """
    ratios = []
    for sp in split_rows:
        try:
            new = float(sp.get("new_rate") or 0)
            old = float(sp.get("old_rate") or 0)
            when = _dt.date.fromisoformat(str(sp.get("ex_date"))[:10])
        except (TypeError, ValueError):
            continue
        if new > 0 and old > 0 and abs(new / old - 1.0) > 1e-9:
            ratios.append((when, new / old))
    for r in rows:
        try:
            rate = float(r.get("rate") or 0)
            ex = _dt.date.fromisoformat(str(r.get("ex_date"))[:10])
        except (TypeError, ValueError):
            r["adj_rate"] = r.get("rate")
            continue
        factor = 1.0
        for when, ratio in ratios:
            if when > ex:
                factor *= ratio
        r["adj_rate"] = rate / factor if factor else rate


def _rate(r: dict) -> float:
    """The split-adjusted payment. Falls back to the declared rate so a
    row that predates the adjustment still reads sensibly."""
    v = r.get("adj_rate")
    if v is None:
        v = r.get("rate")
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# A payment this many times the median of its OWN year is a one-off.
SPECIAL_MULTIPLE = 3.0


# ...and a payment this far BELOW the year's median is a fragment: a
# stub, an adjustment, a partial record. Not part of the regular policy.
MINOR_FRACTION = 1.0 / 3.0


def _is_special(row: dict, year_rates: list) -> bool:
    """Is this payment something other than a REGULAR dividend?

    Two kinds of not-regular, caught at opposite ends of the same
    comparison. Above the norm: a special. Below it: a fragment.

    The fragments matter as much as the specials, because they corrupt
    the payment COUNT and the count is what drives the timing
    normalisation. Allstate's 2023 record carries four 0.89 dividends
    and a stray 0.08; counted as five payments against a norm of four,
    the year was scaled by 4/5 down to 2.91 and Allstate -- which has
    never cut -- came back as a 14% cut. Ares Capital's 2019 record
    holds two 0.40 regulars and two 0.02 fragments, which counts to four
    and hides the fact that half the year is simply missing.

    Alpaca's `special` flag is set on barely any of them -- across a
    120-name universe only 9 rows carried it, and Costco's $7.00 in 2017
    and Equity Residential's $8.00 in 2016 were both unflagged. Left
    uncorrected each one lands in an annual total and the NEXT year reads
    as a 75-85% dividend cut at a company that has never cut.

    Trusting the flag is therefore not an option, and neither is
    comparing against the median of the whole window: a company that
    reinstated a dividend has recent payments many times its ten-year
    median (GE's $0.28 against a $0.08 median) and a company that moved
    from monthly to quarterly has larger payments for the same annual
    cash (STAG). Both would be stripped as "specials" and both are real.

    The discriminator is the payment's own YEAR. A special is an
    outlier among its siblings -- one payment several times the others
    in the same twelve months. A reinstatement or a frequency change
    lifts every payment in the year together, so nothing stands out.
    """
    if bool(row.get("special")):
        return True
    if len(year_rates) < 3:
        return False           # too few siblings to call anything odd
    rate = _rate(row)
    # The plain median of EVERY payment in the year, the payment itself
    # included. An earlier version excluded equal values and indexed the
    # middle of what was left, which inverted on a bimodal year: Ares
    # Capital pays four ~0.43 regulars alongside four 0.03 supplementals,
    # the 0.03s became "the norm", and all four REGULAR dividends were
    # stripped as specials -- turning a $1.87 year into $0.12 and
    # manufacturing the deepest cut in the universe.
    ordered = sorted(year_rates)
    n = len(ordered)
    mid = (ordered[n // 2] if n % 2
           else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0)
    if mid <= 0:
        return False
    return bool(rate > SPECIAL_MULTIPLE * mid
                or rate < MINOR_FRACTION * mid)


def _year_rate_index(rows: list) -> dict:
    out: dict = defaultdict(list)
    for r in rows:
        try:
            out[int(str(r.get("ex_date"))[:4])].append(_rate(r))
        except (TypeError, ValueError):
            continue
    return out


def _by_year(rows: list, *, include_special: bool = False) -> dict:
    """Total ordinary dividends per calendar year, keyed by ex-date year.

    Special dividends are excluded by default: a one-off is not a raise,
    and folding it in would invent a streak that breaks next year.
    """
    out: dict = defaultdict(float)
    index = _year_rate_index(rows)
    for r in rows:
        try:
            _y = int(str(r.get("ex_date"))[:4])
        except (TypeError, ValueError):
            continue
        if not include_special and _is_special(r, index.get(_y, [])):
            continue
        ex = str(r.get("ex_date") or "")
        try:
            year = int(ex[:4])
        except (TypeError, ValueError):
            continue
        rate = _rate(r)          # split-adjusted; see _apply_split_adjustment
        if rate > 0:
            out[year] += rate
    return dict(out)


def _complete_years(rows: list) -> dict:
    """Yearly totals, corrected for payment-TIMING artifacts.

    THE PROBLEM, found on Realty Income (O). It raised its monthly
    dividend every single year 2016->2023, yet the screen scored its
    streak at ZERO. Cause: 2024 recorded 11 payments (total understated
    at 2.869) and 2025 recorded 13 (overstated at 3.487) because one
    monthly payment slipped across a year boundary. Nothing about the
    dividend changed; the calendar moved.

    Dropping short years does not fix it either — that leaves a GAP in
    the year sequence, and a streak that requires consecutive years then
    breaks anyway. That is precisely how a 25-year Dividend Aristocrat
    came back as "raise streak 0y".

    So a year whose payment count is CLOSE to the norm is normalised to
    the modal count (total * modal / actual) rather than discarded: a
    timing shift is corrected, not treated as a dividend change. A year
    that is far off the norm — a genuinely suspended or skipped payout —
    is left RAW, because that is a real reduction and the cut rule
    should see it.

    The current (in-progress) year is always dropped; it is incomplete
    by definition, not by artifact.
    """
    counts: dict = defaultdict(int)
    totals = _by_year(rows)
    index = _year_rate_index(rows)
    for r in rows:
        try:
            y = int(str(r.get("ex_date"))[:4])
        except (TypeError, ValueError):
            continue
        if _is_special(r, index.get(y, [])):
            continue
        counts[y] += 1
    if not counts:
        return {}
    current = _dt.datetime.now(_dt.timezone.utc).year
    freq: dict = defaultdict(int)
    for y, n in counts.items():
        if y != current:
            freq[n] += 1
    if not freq:
        return {}
    # On a tie, take the SMALLER count -- that is the base cadence. The
    # other way round, a single year carrying two supplementals sets the
    # norm at 6, every ordinary 4-payment year is then scaled UP by 1.5x,
    # and the supplemental year reads as a cut against its own inflated
    # neighbours.
    modal = max(freq.items(), key=lambda kv: (kv[1], -kv[0]))[0]

    # Within this many payments of the norm = a timing shift, normalise.
    # Beyond it = a real change in payout behaviour, leave it alone.
    # The band has to scale with the payment frequency. A fixed +/-2 was
    # right for a monthly payer (Realty Income's 11-and-13 problem) and
    # badly wrong for a quarterly one: Accenture's early years hold only
    # TWO of four payments in Alpaca's record, |2-4| = 2 passed the test,
    # and the year was scaled up by 2x on the strength of missing data.
    # A quarter off the norm is the honest boundary either way.
    band = max(1, int(round(modal * 0.25)))

    out: dict = {}
    for y, total in totals.items():
        if y == current:
            continue                       # always incomplete
        n = counts.get(y, 0)
        if n <= 0:
            continue
        if n == modal:
            out[y] = total
        elif abs(n - modal) <= band:
            # A payment slipped across a year boundary. Correct the
            # timing; the dividend itself did not change.
            out[y] = total * (modal / float(n))
        elif n < modal:
            # Materially FEWER payments than the norm. Either the record
            # is truncated (Alpaca's history for a name can start
            # mid-series) or the payout was suspended. We cannot tell
            # which from the count alone, and guessing either way
            # invents a cut or hides one -- so the year is DROPPED and
            # the streak simply does not reach past the gap. Saying
            # "unknown" is the only honest option here.
            continue
        else:
            # MORE payments than the norm -- a supplemental or a
            # frequency change. That is real cash and it is kept raw.
            out[y] = total
    return out


def window_years(rows: list) -> int:
    """How many COMPLETE years of history we actually have."""
    return len(_complete_years(rows))


def raise_streak_years(rows: list) -> Optional[int]:
    """Consecutive COMPLETE years of a higher total dividend, newest
    first. None when there is not enough history to say.

    The current (partial) year is skipped — a year still in progress has
    not failed to raise yet, and counting it would reset every streak in
    January.
    """
    by_year = _complete_years(rows)
    if len(by_year) < 2:
        return None
    current = _dt.datetime.now(_dt.timezone.utc).year
    years = sorted((y for y in by_year if y < current), reverse=True)
    if len(years) < 2:
        return None
    streak = 0
    for a, b in zip(years, years[1:]):
        if a - b != 1:
            break            # a gap in payments ends the streak
        if by_year[a] > by_year[b]:
            streak += 1
        else:
            break
    return streak


def had_cut(rows: list, lookback_years: int = 10) -> Optional[bool]:
    """Did the annual dividend ever FALL year-over-year in the window?

    A >5% drop counts; smaller wobbles are timing noise (a payment that
    lands either side of a year boundary shifts an annual total without
    the dividend having changed).
    """
    by_year = _complete_years(rows)
    if len(by_year) < 2:
        return None
    current = _dt.datetime.now(_dt.timezone.utc).year
    years = sorted((y for y in by_year
                    if y < current and y >= current - lookback_years),
                   reverse=True)
    if len(years) < 2:
        return None
    for a, b in zip(years, years[1:]):
        if a - b != 1:
            continue
        if by_year[a] < by_year[b] * 0.95:
            return True
    return False


# A cut has to be OLD before recovery from it means anything. Three
# complete years of rising payments is the shortest run that is a policy
# rather than a rebound.
CUT_HEAL_YEARS = 3


def cut_profile(rows: list, lookback_years: int = 10) -> dict:
    """Everything about a cut: when, how deep, and whether it is REPAIRED.

    WHY REPAIR MATTERS (2026-08-23). A flat "no cut in ten years" is
    correct about the risk and wrong about the opportunity. It excluded
    Simon Property and Main Street — both of which cut in the pandemic,
    both of which have since climbed back ABOVE where they were and kept
    raising — and would have kept excluding them until roughly 2030, by
    which time the cheap entry is long gone. Mike's read: if we can
    accumulate at a low price while the record is still healing, the
    income compounds for the whole wait.

    So a cut is not forgiven, it is REPAIRED, and repair has to be
    proven on three counts:

      1. RECOVERED  — the annual dividend is back at or above its
                      pre-cut peak. Not "recovering". Back.
      2. RISING     — it has gone up every complete year since the
                      trough, with no second wobble.
      3. HEALED     — at least CUT_HEAL_YEARS complete years have passed
                      since the trough, so this is a policy and not a
                      one-year rebound.

    All three, or the cut still disqualifies. On live data that admits
    SPG (trough 2021, back above its 2019 peak, four straight raises)
    and MAIN (trough 2022, +25% past its peak, three straight), while
    T, F, NLY, VTR, WELL and KHC — every one still paying LESS than
    before its cut — stay out. The rule discriminates between a company
    that recovered and a company that merely stopped falling.
    """
    empty = {"had_cut": None, "cut_year": None, "trough_year": None,
             "pre_cut_peak": None, "latest": None, "recovered": None,
             "repaired": False, "years_since_trough": None}
    by_year = _complete_years(rows)
    if len(by_year) < 2:
        return empty
    current = _dt.datetime.now(_dt.timezone.utc).year
    years = sorted(y for y in by_year
                   if y < current and y >= current - lookback_years)
    if len(years) < 2:
        return empty

    cut_year = None
    for a, b in zip(years, years[1:]):
        if b - a == 1 and by_year[b] < by_year[a] * 0.95:
            cut_year = b
    latest = years[-1]
    if cut_year is None:
        return {**empty, "had_cut": False, "latest": by_year[latest]}

    pre_cut_peak = max(by_year[y] for y in years if y < cut_year)
    post = [y for y in years if y >= cut_year]
    trough_year = min(post, key=lambda y: by_year[y])

    recovered = by_year[latest] >= pre_cut_peak
    years_since_trough = latest - trough_year
    streak = raise_streak_years(rows) or 0
    rising_since_trough = streak >= years_since_trough
    healed = years_since_trough >= CUT_HEAL_YEARS

    return {
        "had_cut": True,
        "cut_year": cut_year,
        "trough_year": trough_year,
        "pre_cut_peak": pre_cut_peak,
        "latest": by_year[latest],
        "recovered": recovered,
        "years_since_trough": years_since_trough,
        "repaired": bool(recovered and rising_since_trough and healed),
    }


def trailing_12mo_dividends(rows: list) -> Optional[float]:
    """Sum of the last 12 months of dividends, specials INCLUDED.

    Specials count here on purpose: this measures cash actually received,
    which is the right basis for a yield even though it is the wrong
    basis for a streak.
    """
    if not rows:
        return None
    today = _dt.datetime.now(_dt.timezone.utc).date()
    cutoff = today - _dt.timedelta(days=365)
    total = 0.0
    seen = False
    for r in rows:
        try:
            ex = _dt.date.fromisoformat(str(r.get("ex_date"))[:10])
        except (TypeError, ValueError):
            continue
        rate = _rate(r)
        if ex >= cutoff and rate > 0:
            total += rate
            seen = True
    return total if seen else None


def trailing_yield(rows: list, price: float) -> Optional[float]:
    """Trailing-12-month yield from ACTUAL distributions.

    This is what gives ETFs a yield at all — Finnhub's fundamentals do
    not cover funds, so SCHD/VYM/JEPI were permanently UNVERIFIED and
    excluded from the ladder. They are the natural core of a ladder at
    small capital, so that hole mattered.
    """
    ttm = trailing_12mo_dividends(rows)
    if ttm is None or not price or price <= 0:
        return None
    return ttm / float(price)


def next_ex_date(rows: list) -> Optional[str]:
    """The next KNOWN ex-date, or None.

    Feeds the wheel advisor's ex-date guard (lane rule 3), which until
    now was being handed None on every call — so the rule that stops a
    covered call losing its dividend to early exercise could never
    actually fire.
    """
    today = _dt.datetime.now(_dt.timezone.utc).date()
    upcoming = []
    for r in rows:
        try:
            ex = _dt.date.fromisoformat(str(r.get("ex_date"))[:10])
        except (TypeError, ValueError):
            continue
        if ex >= today:
            upcoming.append(ex)
    return min(upcoming).isoformat() if upcoming else None


def last_dividend_rate(rows: list) -> Optional[float]:
    """Most recent per-share payment — the amount an early exercise would
    take, which is what the ex-date guard weighs against time value."""
    for r in reversed(rows):
        rate = _rate(r)
        if rate > 0:
            return rate
    return None


async def dividend_profile(symbol: str, price: Optional[float] = None) -> dict:
    """Everything the screen needs about one name's dividend, in one call.

    `verified` says whether the payment series was actually retrieved —
    the screen must not treat a failed fetch as a confirmed non-payer.
    """
    rows = await dividend_history(symbol)
    return {
        "symbol": (symbol or "").upper().strip(),
        "verified": bool(rows),
        "payments": len(rows),
        "raise_streak_years": raise_streak_years(rows),
        "had_cut": had_cut(rows),
        "cut_profile": cut_profile(rows),
        "ttm_dividends": trailing_12mo_dividends(rows),
        "trailing_yield": (trailing_yield(rows, price)
                           if price is not None else None),
        "next_ex_date": next_ex_date(rows),
        "last_rate": last_dividend_rate(rows),
        "years_covered": sorted(_complete_years(rows).keys()),
        # How deep the evidence goes. Alpaca's corporate actions begin in
        # 2016, so a 10-year streak is not yet EXPRESSIBLE -- ten complete
        # years yield at most nine year-over-year comparisons. The screen
        # asks for an unbroken record across everything visible rather
        # than a fixed number, which is honest today and tightens on its
        # own as the history deepens.
        "window_years": window_years(rows),
    }


# --- The FUND path (spec §4: "for any fund: AUM >= $100M, no reverse
# split in 24 months, trailing payout <= trailing total return").
#
# WHY FUNDS NEED THEIR OWN TEST (2026-08-23, Mike asked the right
# question: "is it going to possibly do this to other Dividend Funds and
# not just fix for REIT?"). It was. Running the raise-streak rule over
# every fund type failed SEVEN OF EIGHT covered-call ETFs -- JEPI, QYLD,
# RYLD, XYLD, FEPI, NVDY, TSLY -- because a variable distribution is
# their DESIGN, not a cut. NVDY paid 5.05, then 19.53, then 12.14: that
# is option premium tracking volatility, and calling it a dividend cut is
# a category error. It would have rejected the entire asset class the
# original 24-fund capture study was built on.
#
# The spec already knew. For a fund the question is not "did it raise
# every year" but "IS THE DISTRIBUTION FUNDED BY RETURNS, OR IS IT
# EATING NAV?" -- which is precisely the finding from Mike's own book:
# cash yield 17.6% near-uniform across six positions, total return
# -17.0% to +22.6%. The payout carried no information about the outcome.
# This test is what makes the payout informative.
#
# Measured live 2026-08-23:
#   JEPI  paid  7.9%, earned  9.4%  -> earned it
#   QYLD  paid 11.6%, earned 22.9%  -> earned it
#   NVDY  paid 57.2%, earned 21.8%  -> EATING NAV (price -25.6%)
#   TSLY  paid 64.1%, earned  8.6%  -> EATING NAV, and reverse split 5:1

async def reverse_splits(symbol: str, months: int = 24) -> list:
    """Reverse splits in the window. In a distribution fund a reverse
    split is a tell: it usually means NAV has collapsed far enough that
    the share price needed rescuing. TSLY did 5:1 on 2025-12-01.

    Reads the shared split feed rather than issuing its own request, so
    the fund test and the split adjustment cannot disagree about what
    happened to a symbol.
    """
    cutoff = (_dt.datetime.now(_dt.timezone.utc).date()
              - _dt.timedelta(days=int(months * 30.5)))
    out = []
    for sp in await splits(symbol):
        try:
            new_r = float(sp.get("new_rate") or 0)
            old_r = float(sp.get("old_rate") or 0)
            when = _dt.date.fromisoformat(str(sp.get("ex_date"))[:10])
        except (TypeError, ValueError):
            continue
        if old_r > 0 and new_r > 0 and new_r < old_r and when >= cutoff:
            out.append(sp)
    return out


async def trailing_total_return(symbol: str, days: int = 365
                                ) -> Optional[float]:
    """Total return over the window, distributions included.

    Alpaca's adjustment=all folds distributions into the price series, so
    this is the honest denominator for the fund test -- no reconstruction
    from payment dates, no assumption about reinvestment timing.
    """
    sym = (symbol or "").upper().strip()
    headers = _auth()
    if not sym or headers is None:
        return None
    # End the window YESTERDAY, never today. This account's market-data
    # subscription refuses recent SIP bars -- asking for today returns
    # 403 "subscription does not permit querying recent SIP data", which
    # silently made every fund's total return None and left the whole
    # asset class UNVERIFIED. One day of lag costs nothing on a 365-day
    # measurement and keeps the request inside what the tier allows.
    today = _dt.datetime.now(_dt.timezone.utc).date()
    end = today - _dt.timedelta(days=1)
    start = end - _dt.timedelta(days=days)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.get(
                "https://data.alpaca.markets/v2/stocks/bars",
                headers=headers,
                params={"symbols": sym, "timeframe": "1Day",
                        "start": start.isoformat(), "end": end.isoformat(),
                        "limit": 10000, "adjustment": "all"})
            if r.status_code != 200:
                return None
            bars = ((r.json() or {}).get("bars") or {}).get(sym) or []
    except Exception:  # noqa: BLE001
        return None
    if len(bars) < 2:
        return None
    first, last = bars[0].get("c"), bars[-1].get("c")
    if not first or not last or first <= 0:
        return None
    return last / first - 1.0


async def fund_health(symbol: str, price: Optional[float] = None) -> dict:
    """The spec's fund test. Returns the verdict plus the numbers behind
    it, because "this fund is returning your own capital to you" is a
    claim that has to show its work.
    """
    rows = await dividend_history(symbol)
    ttm = trailing_12mo_dividends(rows)
    tr = await trailing_total_return(symbol)
    splits = await reverse_splits(symbol, 24)

    dist_yield = None
    if ttm is not None and price:
        dist_yield = ttm / float(price)

    checks: dict = {}
    reasons: list = []

    if splits:
        when = (splits[0].get("process_date")
                or splits[0].get("ex_date") or "recently")
        checks["reverse_split"] = "fail"
        reasons.append(
            f"reverse split on {when} — in a distribution fund that "
            f"usually means NAV fell far enough to need rescuing")
    else:
        checks["reverse_split"] = "pass"

    if dist_yield is None or tr is None:
        checks["payout_vs_return"] = "unverified"
    elif dist_yield > tr:
        checks["payout_vs_return"] = "fail"
        reasons.append(
            f"paid out {dist_yield*100:.1f}% while earning "
            f"{tr*100:+.1f}% — the distribution is eating NAV, not "
            f"funded by returns")
    else:
        checks["payout_vs_return"] = "pass"

    return {
        "symbol": (symbol or "").upper().strip(),
        "dist_yield": dist_yield,
        "trailing_total_return": tr,
        "reverse_splits": len(splits),
        "checks": checks,
        "reasons": reasons,
        "passed": not any(v == "fail" for v in checks.values()),
        "verified": checks["payout_vs_return"] != "unverified",
    }
