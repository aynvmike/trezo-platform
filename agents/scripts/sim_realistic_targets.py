"""Sim lab: Mike's 'realistic move' vs 'defined win' -- rerunnable evidence.

Standalone (stdlib only; reads agents/.env for Alpaca data keys). Compares,
per symbol over ~7 months of daily bars, entering EVERY day (worst case --
the live bot gates entries on TCS signals):

  A: defined win  -- target +8.5%, stop -4.5%, max 10 sessions
  B: realistic    -- target 1.2x ATR%, stop 0.8x ATR%, out by next close

Run:  [PowerShell]  cd C:\Trezo\trezo-platform\agents
      .venv\Scripts\python.exe scripts\sim_realistic_targets.py

2026-07-02 result: quick-realistic loses on calm megas (stop wick-outs),
wins big on high-ATR movers (SNDK +$11.7k, 55% win). Trade what MOVES.
"""
import json
import os
import statistics
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
env = {}
for line in open(os.path.join(HERE, "..", ".env")):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
H = {"APCA-API-KEY-ID": env.get("ALPACA_API_KEY") or env.get("APCA_API_KEY_ID", ""),
     "APCA-API-SECRET-KEY": env.get("ALPACA_SECRET_KEY") or env.get("APCA_API_SECRET_KEY", "")}
SLIP = 0.0005
NOTIONAL = 10_000.0
SYMS = ("AAPL", "MSFT", "WMT", "BRK.B", "NVDA", "SNDK")
START = "2025-11-15T00:00:00Z"


def bars(sym):
    u = (f"https://data.alpaca.markets/v2/stocks/{sym}/bars"
         f"?timeframe=1Day&start={START}&limit=200&adjustment=split")
    d = json.load(urllib.request.urlopen(
        urllib.request.Request(u, headers=H), timeout=15))
    return d.get("bars") or []


def atr_pct(bs, i, period=14):
    if i < period:
        return None
    trs = []
    for j in range(i - period + 1, i + 1):
        h, l, pc = bs[j]["h"], bs[j]["l"], bs[j - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return (sum(trs) / period) / bs[i]["c"]


def run(sym):
    bs = bars(sym)
    if len(bs) < 60:
        return None
    A = dict(p=0.0, w=0, n=0, h=[])
    B = dict(p=0.0, w=0, n=0, h=[])
    i = 15
    while i < len(bs) - 1:
        e = bs[i]["o"] * (1 + SLIP)
        tgt, stp, done = e * 1.085, e * 0.955, False
        for j in range(i, min(i + 10, len(bs))):
            if bs[j]["l"] <= stp:
                A["p"] += NOTIONAL * ((stp * (1 - SLIP) - e) / e)
                A["h"].append(j - i + 1); i = j + 1; done = True
                break
            if bs[j]["h"] >= tgt:
                A["p"] += NOTIONAL * ((tgt * (1 - SLIP) - e) / e)
                A["w"] += 1; A["h"].append(j - i + 1); i = j + 1; done = True
                break
        if not done:
            j = min(i + 9, len(bs) - 1)
            pnl = NOTIONAL * ((bs[j]["c"] * (1 - SLIP) - e) / e)
            A["p"] += pnl; A["w"] += 1 if pnl > 0 else 0
            A["h"].append(j - i + 1); i = j + 1
        A["n"] += 1
    i = 15
    while i < len(bs) - 1:
        ap = atr_pct(bs, i - 1)
        if not ap:
            i += 1
            continue
        e = bs[i]["o"] * (1 + SLIP)
        tgt, stp, done = e * (1 + 1.2 * ap), e * (1 - 0.8 * ap), False
        for j in range(i, min(i + 2, len(bs))):
            if bs[j]["l"] <= stp:
                B["p"] += NOTIONAL * ((stp * (1 - SLIP) - e) / e)
                B["h"].append(j - i + 1); i = j + 1; done = True
                break
            if bs[j]["h"] >= tgt:
                B["p"] += NOTIONAL * ((tgt * (1 - SLIP) - e) / e)
                B["w"] += 1; B["h"].append(j - i + 1); i = j + 1; done = True
                break
        if not done:
            j = min(i + 1, len(bs) - 1)
            pnl = NOTIONAL * ((bs[j]["c"] * (1 - SLIP) - e) / e)
            B["p"] += pnl; B["w"] += 1 if pnl > 0 else 0
            B["h"].append(j - i + 1); i = j + 1
        B["n"] += 1
    return sym, A, B, len(bs)


if __name__ == "__main__":
    print(f"{'SYM':6s} | {'A: defined-win 8.5/4.5 max10d':^40s} |"
          f" {'B: realistic 1.2xATR quick-out':^40s}")
    totA = totB = 0.0
    for sym in SYMS:
        r = run(sym)
        if not r:
            print(f"{sym:6s} | insufficient data")
            continue
        sym, A, B, nb = r
        totA += A["p"]; totB += B["p"]
        print(f"{sym:6s} | ${A['p']:>+8.0f} {A['n']:>3d}t "
              f"win{A['w'] / max(A['n'], 1) * 100:>4.0f}% "
              f"hold{statistics.mean(A['h']):>5.1f}d "
              f"| ${B['p']:>+8.0f} {B['n']:>3d}t "
              f"win{B['w'] / max(B['n'], 1) * 100:>4.0f}% "
              f"hold{statistics.mean(B['h']):>5.1f}d")
    print(f"{'TOTAL':6s} | ${totA:>+8.0f} {'':31s} | ${totB:>+8.0f}")
