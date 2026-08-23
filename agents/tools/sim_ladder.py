"""3-month replay of the Dividends (Long-Term) ladder.

Runs the SHIPPED modules (dividend_lt.size_lane, dividend_screen.
sector_capped) rather than a parallel reimplementation, so what this
measures is the code that is actually deployed.

DATA
  prices    Alpaca daily bars, adjustment=all -> dividend- and
            split-adjusted, so TOTAL RETURN is read directly off the
            series instead of being reconstructed from payment dates.
            (Finnhub's /stock/dividend payment series is NOT on the free
            tier, which is a finding in its own right.)
  screen    Finnhub /stock/metric: yield, payout ratio, 5Y dividend
            growth rate.

WHAT THIS IS NOT
  - Not a verdict. The spec says 12 months is the minimum for a total
    return judgement and 90 days only proves plumbing. Three months of
    one regime is an anecdote with a number attached.
  - No wheel premium. The 25% wheel sleeve would need historical option
    chains, which we do not have. Modeling it would be inventing the
    number the whole exercise is supposed to measure. Ladder only.
  - Lookahead in the screen: names are screened on TODAY's fundamentals,
    so the selection knows which names still look good now. This flatters
    the result and cannot be removed without point-in-time fundamentals.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

sys.path.insert(0, "/tmp/divtest")

from app.strategies.dividend_lt import LaneInputs, per_name_cap_pct, size_lane  # noqa: E402
from app.strategies.dividend_screen import (  # noqa: E402
    CASHFLOW_PAYERS, GROWTH_TIER_MAX_YIELD, MAX_PAYOUT_RATIO,
    MIN_QUALIFYING_YIELD,
)

FIN = os.environ["FINNHUB_API_KEY"]
AK = os.environ["ALPACA_API_KEY"]
AS = os.environ["ALPACA_SECRET_KEY"]

START = "2026-05-23"
END = "2026-08-22"

# The pool the engine actually scans for dividend names (wheel_universe's
# MARKET_WIDE_DIVIDEND_POOL) plus the curated seed.
POOL = """PG KO PEP MDLZ CL KMB GIS K
JNJ ABBV PFE MRK BMY AMGN GILD LLY
JPM BAC C WFC USB PNC TFC
SPG O AMT PLD WELL VTR
XOM CVX COP PSX VLO MPC
NEE DUK SO AEP EXC D
MMM CAT DE HON GE DOW
IBM CSCO INTC ORCL QCOM TXN
T VZ TMUS
SCHD VYM DVY HDV NOBL JEPI JEPQ DGRO
MAIN STAG NLY ARCC F KMI MO KHC KEY HPQ QYLD""".split()

BENCHMARKS = ["SPY", "SCHD", "SGOV"]


def _get(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def finnhub_metric(sym: str) -> dict:
    try:
        d = _get("https://finnhub.io/api/v1/stock/metric?"
                 + urllib.parse.urlencode(
                     {"symbol": sym, "metric": "all", "token": FIN}), {})
        return d.get("metric") or {}
    except Exception:
        return {}


def finnhub_profile(sym: str) -> dict:
    try:
        return _get("https://finnhub.io/api/v1/stock/profile2?"
                    + urllib.parse.urlencode({"symbol": sym, "token": FIN}), {})
    except Exception:
        return {}


def bars(symbols: list, start: str, end: str) -> dict:
    """Adjusted daily bars, chunked. adjustment=all => total return."""
    out = defaultdict(list)
    H = {"APCA-API-KEY-ID": AK, "APCA-API-SECRET-KEY": AS}
    for i in range(0, len(symbols), 40):
        chunk = symbols[i:i + 40]
        page = None
        while True:
            q = {"symbols": ",".join(chunk), "timeframe": "1Day",
                 "start": start, "end": end, "limit": 10000,
                 "adjustment": "all"}
            if page:
                q["page_token"] = page
            try:
                d = _get("https://data.alpaca.markets/v2/stocks/bars?"
                         + urllib.parse.urlencode(q), H)
            except Exception as e:
                print(f"  bars error {chunk[:3]}...: {e}")
                break
            for s, rows in (d.get("bars") or {}).items():
                out[s].extend(rows)
            page = d.get("next_page_token")
            if not page:
                break
        time.sleep(0.25)
    return out


def screen_one_LEGACY(sym: str) -> dict | None:
    """The shipped §4 screen, with the 5Y dividend growth rate standing in
    for the raise-streak/cut checks (see the note in the report: the
    payment series is not available on this Finnhub tier)."""
    m = finnhub_metric(sym)
    if not m:
        return None
    y = m.get("dividendYieldIndicatedAnnual")
    if y is None:
        y = m.get("currentDividendYieldTTM")
    if y is None:
        return None
    y = float(y) / 100.0
    if y < MIN_QUALIFYING_YIELD:
        return {"ticker": sym, "passed": False, "why": f"yield {y*100:.2f}% below floor"}

    growth = m.get("dividendGrowthRate5Y")
    growth = float(growth) if growth is not None else None

    payout = m.get("payoutRatioAnnual")
    payout = float(payout) / 100.0 if payout is not None else None

    prof = finnhub_profile(sym)
    sector = (prof.get("finnhubIndustry") or "").strip() or None
    is_fund = (prof.get("type") or "").upper() in ("ETP", "ETF", "FUND")
    cashflow_payer = bool(sector and any(
        c.lower() in sector.lower() for c in CASHFLOW_PAYERS)) or is_fund

    reasons = []
    if growth is None:
        return {"ticker": sym, "passed": False, "why": "no dividend growth data"}
    if growth < 0:
        reasons.append(f"5Y dividend growth {growth:.1f}% (cut history)")
    if payout is not None and not cashflow_payer and payout > MAX_PAYOUT_RATIO:
        reasons.append(f"payout {payout*100:.0f}% over {MAX_PAYOUT_RATIO*100:.0f}%")

    passed = not reasons
    tier = ("HIGH_YIELD" if y >= GROWTH_TIER_MAX_YIELD else "GROWTH") if passed else "FAIL"
    return {"ticker": sym, "passed": passed, "tier": tier, "yield_pct": y,
            "payout_ratio": payout, "growth_5y": growth, "sector": sector,
            "is_fund": is_fund, "cashflow_payer": cashflow_payer,
            "why": "; ".join(reasons) or "clears the screen"}


class R:
    """sector_capped() expects attribute access."""
    def __init__(self, d):
        self.__dict__.update(d)


def total_return(series: list) -> float | None:
    if not series or len(series) < 2:
        return None
    return series[-1]["c"] / series[0]["c"] - 1.0


def main() -> None:
    print("=" * 74)
    print(f"DIVIDEND LADDER — 3-MONTH REPLAY   {START} to {END}")
    print("=" * 74)

    print(f"\nScreening {len(POOL)} names through the REAL shipped screen...")
    import asyncio
    from app.strategies.dividend_screen import screen as real_screen
    async def _all():
        out=[]
        for s in POOL:
            r = await real_screen(s, force=True)
            out.append({"ticker": r.ticker, "passed": r.passed, "tier": r.tier,
                        "yield_pct": r.yield_pct, "payout_ratio": r.payout_ratio,
                        "growth_5y": (r.dividend_growth_5y*100
                                      if r.dividend_growth_5y is not None else None),
                        "sector": r.sector, "why": (r.reasons[0] if r.reasons else "clears")})
            await asyncio.sleep(0.9)
        return out
    screened = asyncio.run(_all())

    passed = [r for r in screened if r.get("passed")]
    failed = [r for r in screened if not r.get("passed")]
    print(f"  screened {len(screened)} | passed {len(passed)} | failed {len(failed)}")

    print("\n  Rejected (why the screen exists):")
    for r in sorted(failed, key=lambda r: r["ticker"])[:14]:
        print(f"    {r['ticker']:6s} {r.get('why','')[:64]}")

    # The agent's ranking: quality first, yield last.
    passed.sort(key=lambda r: (-(r.get("growth_5y") or 0),
                               (r.get("payout_ratio") if r.get("payout_ratio")
                                is not None else 1.0),
                               -(r.get("yield_pct") or 0)))
    from app.strategies.dividend_screen import sector_capped
    capped = sector_capped([R(r) for r in passed])
    print(f"\n  After the <=2-per-sector cap: {len(capped)} candidates")

    results = {}
    for label, capital in (("25k book (income pocket)", 7_500),
                           ("75k book (income pocket)", 20_000)):
        inp = LaneInputs(capital=capital)
        sizing = size_lane(inp)
        names = [c.ticker for c in capped][:sizing.ladder_names]
        results[label] = {"sizing": sizing, "names": names,
                          "cap_pct": per_name_cap_pct(sizing)}
        print(f"\n  {label}: ladder_capital ${sizing.ladder_capital:,.0f}, "
              f"{sizing.ladder_names} names, cap "
              f"{per_name_cap_pct(sizing)*100:.0f}%/name")
        print(f"    {', '.join(names)}")

    all_syms = sorted({n for v in results.values() for n in v["names"]}
                      | set(BENCHMARKS))
    print(f"\nFetching adjusted bars for {len(all_syms)} symbols...")
    px = bars(all_syms, START, END)

    print("\n" + "=" * 74)
    print("PER-NAME TOTAL RETURN (dividend-adjusted)")
    print("=" * 74)
    trs = {}
    for s in all_syms:
        tr = total_return(px.get(s) or [])
        trs[s] = tr
        if tr is None:
            print(f"  {s:6s}   no data")
    detail = {r["ticker"]: r for r in passed}
    for label, v in results.items():
        print(f"\n  {label}")
        print(f"    {'name':7s}{'tier':12s}{'yield':>7s}{'growth5Y':>10s}{'3mo TR':>9s}")
        for n in v["names"]:
            d = detail.get(n, {})
            tr = trs.get(n)
            print(f"    {n:7s}{d.get('tier',''):12s}"
                  f"{(d.get('yield_pct') or 0)*100:6.2f}%"
                  f"{(d.get('growth_5y') or 0):9.1f}%"
                  f"{(tr*100 if tr is not None else float('nan')):8.2f}%")

    print("\n" + "=" * 74)
    print("LANE RESULT vs BENCHMARKS")
    print("=" * 74)
    for label, v in results.items():
        got = [trs[n] for n in v["names"] if trs.get(n) is not None]
        if not got:
            continue
        # Equal weight at the per-name cap, which is how the agent sizes.
        ladder_tr = sum(got) / len(got)
        cash_w = 1.0 - v["sizing"].w_ladder if hasattr(v["sizing"], "w_ladder") else 0.0
        L = v["sizing"].ladder_capital
        gain = L * ladder_tr
        print(f"\n  {label}")
        print(f"    ladder names priced : {len(got)}/{len(v['names'])}")
        print(f"    ladder total return : {ladder_tr*100:+.2f}%  "
              f"(3 months, equal weight)")
        print(f"    annualized (naive)  : {((1+ladder_tr)**4 - 1)*100:+.2f}%")
        print(f"    on ${L:,.0f} ladder  : ${gain:+,.0f}")
    spy, schd, sgov = trs.get("SPY"), trs.get("SCHD"), trs.get("SGOV")
    print("\n  Benchmarks over the same window:")
    for n, t in (("SPY", spy), ("SCHD (dividend ETF)", schd), ("SGOV (cash)", sgov)):
        if t is not None:
            print(f"    {n:22s}{t*100:+7.2f}%")
    if spy is not None and sgov is not None:
        blend = 0.5 * spy + 0.5 * sgov
        print(f"    {'50% SPY / 50% SGOV':22s}{blend*100:+7.2f}%   <- the spec's benchmark")


if __name__ == "__main__":
    main()
