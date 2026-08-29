"""E1a pilot — realized delta of a 5%-OTM ~30-DTE put, measured in-house.

Sources: Alpaca contracts (active+inactive) + option daily bars + SIP stock
bars + corporate-actions dividends; Treasury.gov 1-Mo rate. Greeks are NOT
taken from any vendor: IV is solved from the option's close premium with
Black-Scholes (continuous dividend yield), delta computed from that IV.
"""
import json, math, os, urllib.request, csv, io
from datetime import date, timedelta

H = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
     "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}

def get(url):
    req = urllib.request.Request(url, headers=H)
    return json.load(urllib.request.urlopen(req, timeout=30))

def N(x):  # standard normal CDF
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bs_put(S, K, T, r, q, sig):
    if sig <= 0 or T <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r - q + 0.5 * sig * sig) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    return K * math.exp(-r * T) * N(-d2) - S * math.exp(-q * T) * N(-d1)

def put_delta(S, K, T, r, q, sig):
    d1 = (math.log(S / K) + (r - q + 0.5 * sig * sig) * T) / (sig * math.sqrt(T))
    return -math.exp(-q * T) * N(-d1)

def solve_iv(price, S, K, T, r, q):
    lo, hi = 0.01, 3.0
    if not (bs_put(S, K, T, r, q, lo) <= price <= bs_put(S, K, T, r, q, hi)):
        return None
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if bs_put(S, K, T, r, q, mid) < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)

# --- Treasury 1-Mo rate per year (daily csv, cached per year) ---
_tsy = {}
def rate_for(d: date) -> float:
    yr = d.year
    if yr not in _tsy:
        u = (f"https://home.treasury.gov/resource-center/data-chart-center/"
             f"interest-rates/daily-treasury-rates.csv/{yr}/all?"
             f"type=daily_treasury_yield_curve&field_tdr_date_value={yr}&page&_format=csv")
        raw = urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": "trezo"}), timeout=30
        ).read().decode()
        rows = list(csv.DictReader(io.StringIO(raw)))
        _tsy[yr] = {r["Date"]: r for r in rows}
    # walk back to the latest date <= d
    for back in range(7):
        dd = d - timedelta(days=back)
        key = f"{dd.month}/{dd.day:02d}/{dd.year}"
        alt = dd.strftime("%m/%d/%Y")
        row = _tsy[yr].get(key) or _tsy[yr].get(alt)
        if row:
            v = row.get("1 Mo") or row.get("3 Mo")
            try:
                return float(v) / 100.0
            except (TypeError, ValueError):
                continue
    return 0.043

def spot_on(sym, d: date):
    r = get(f"https://data.alpaca.markets/v2/stocks/bars?symbols={sym}"
            f"&timeframe=1Day&start={d}&end={d + timedelta(days=1)}"
            f"&limit=1&adjustment=raw&feed=sip")
    b = (r.get("bars") or {}).get(sym) or []
    return b[0]["c"] if b else None

def ttm_div_yield(sym, d: date, spot):
    r = get(f"https://data.alpaca.markets/v1/corporate-actions?symbols={sym}"
            f"&types=cash_dividend&start={d - timedelta(days=365)}&end={d}&limit=60")
    divs = (r.get("corporate_actions") or {}).get("cash_dividends") or []
    tot = sum(float(x.get("rate") or 0) for x in divs if not x.get("special"))
    return (tot / spot) if spot else 0.0

def pick_contract(sym, d: date, spot):
    """Nearest to strike=0.95*spot and dte=30 among listed puts."""
    lo, hi = d + timedelta(days=20), d + timedelta(days=45)
    cands = []
    for status in ("inactive", "active"):
        r = get(f"https://paper-api.alpaca.markets/v2/options/contracts"
                f"?underlying_symbols={sym}&type=put&status={status}"
                f"&expiration_date_gte={lo}&expiration_date_lte={hi}&limit=500")
        cands += r.get("option_contracts") or []
    best, bk = None, None
    for c in cands:
        k = float(c["strike_price"])
        exp = date.fromisoformat(c["expiration_date"])
        score = (abs(k - 0.95 * spot) / spot, abs((exp - d).days - 30))
        if bk is None or score < bk:
            bk, best = score, c
    return best

def opt_close_on(occ, d: date):
    r = get(f"https://data.alpaca.markets/v1beta1/options/bars?symbols={occ}"
            f"&timeframe=1Day&start={d}&end={d + timedelta(days=1)}&limit=1")
    b = (r.get("bars") or {}).get(occ) or []
    return b[0]["c"] if b else None

DATES = [date(2024, 3, 4), date(2024, 7, 1), date(2024, 11, 1),
         date(2025, 3, 3), date(2025, 7, 1), date(2025, 11, 3),
         date(2026, 3, 2), date(2026, 7, 1)]

print(f"{'name':4s} {'date':10s} {'spot':>7s} {'strike':>7s} {'dte':>4s} "
      f"{'prem':>6s} {'divy':>6s} {'rate':>6s} {'IV':>6s} {'delta':>7s}")
for sym in ("KO", "O"):
    deltas = []
    for d in DATES:
        try:
            S = spot_on(sym, d)
            if S is None:
                d2 = d + timedelta(days=1)
                S = spot_on(sym, d2)
                if S is None:
                    print(f"{sym:4s} {d} no spot bar"); continue
                d = d2
            c = pick_contract(sym, d, S)
            if not c:
                print(f"{sym:4s} {d} no contract"); continue
            K = float(c["strike_price"])
            exp = date.fromisoformat(c["expiration_date"])
            dte = (exp - d).days
            prem = opt_close_on(c["symbol"], d)
            if prem is None:
                print(f"{sym:4s} {d} {c['symbol']} no option bar"); continue
            q = ttm_div_yield(sym, d, S)
            r = rate_for(d)
            T = dte / 365.0
            iv = solve_iv(prem, S, K, T, r, q)
            if iv is None:
                print(f"{sym:4s} {d} IV unsolvable (prem {prem})"); continue
            dl = put_delta(S, K, T, r, q, iv)
            deltas.append(abs(dl))
            print(f"{sym:4s} {d} {S:7.2f} {K:7.2f} {dte:4d} "
                  f"{prem:6.2f} {q*100:5.1f}% {r*100:5.2f}% {iv*100:5.1f}% {dl:7.3f}")
        except Exception as e:
            print(f"{sym:4s} {d} ERR {str(e)[:80]}")
    if deltas:
        ds = sorted(deltas)
        med = ds[len(ds)//2]
        print(f"  -> {sym}: n={len(ds)} |delta| median {med:.3f} "
              f"range [{ds[0]:.3f}, {ds[-1]:.3f}]  (table asserts 0.25)")
