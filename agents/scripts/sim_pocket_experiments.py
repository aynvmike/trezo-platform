"""Sim lab: pocket-size experiments from LIVE trade outcomes (Mike 2026-07-02).

"If we can get the simulated labs to change to a direction that allows the
agents to see if the different pocket sizes and strategies ... will be much
more beneficial in a realistic setting."

This reads the REAL closed trades (paper_positions) since the window start,
groups them into the allocation lanes (stocks / crypto / options+income /
forex), and reports each lane's actual performance. It then projects, for a
few candidate pocket splits, what the same trading would have earned if each
lane's capital had been scaled to that split -- a LINEAR projection with the
honest caveat that more capital does not always find more good trades.

Rerun anytime:  [PowerShell]  cd C:\Trezo\trezo-platform\agents
                .venv\Scripts\python.exe scripts\sim_pocket_experiments.py
"""
import json
import os
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
env = {}
for line in open(os.path.join(HERE, "..", ".env")):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
URL = (env.get("SUPABASE_URL") or "").rstrip("/")
KEY = (env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_SERVICE_KEY")
       or env.get("SUPABASE_KEY") or env.get("SUPABASE_ANON_KEY", ""))
WINDOW_START = "2026-06-01"

# Candidate pocket splits to compare (fractions of equity).
SPLITS = {
    "growth (current)": {"stocks": .42, "crypto": .32, "options+income": .20, "forex": .06},
    "mike-example":     {"stocks": .17, "crypto": .33, "options+income": .33, "forex": .17},
    "equal-4":          {"stocks": .25, "crypto": .25, "options+income": .25, "forex": .25},
    "stock-heavy":      {"stocks": .60, "crypto": .20, "options+income": .15, "forex": .05},
}


def lane_for(asset_type: str, strategy: str) -> str:
    s = (strategy or "").lower()
    at = (asset_type or "").lower()
    if at == "forex" or s.startswith("forex"):
        return "forex"
    if at == "crypto" or s.startswith("crypto"):
        return "crypto"
    if at == "option" or s.startswith(("wheel", "options", "cash_secured")):
        return "options+income"
    return "stocks"


def q(path):
    req = urllib.request.Request(URL + "/rest/v1/" + path,
                                 headers={"apikey": KEY,
                                          "Authorization": "Bearer " + KEY})
    return json.load(urllib.request.urlopen(req, timeout=20))


if __name__ == "__main__":
    rows = q("paper_positions?select=asset_type,strategy,realized_pnl_usd,"
             "entry_price,quantity,exit_at&status=like.closed*"
             f"&exit_at=gte.{WINDOW_START}&limit=2000")
    lanes = defaultdict(lambda: {"n": 0, "pnl": 0.0, "wins": 0, "deployed": 0.0})
    for r in rows:
        lane = lane_for(r.get("asset_type"), r.get("strategy"))
        pnl = float(r.get("realized_pnl_usd") or 0)
        notional = (float(r.get("entry_price") or 0)
                    * float(r.get("quantity") or 0))
        d = lanes[lane]
        d["n"] += 1
        d["pnl"] += pnl
        d["wins"] += 1 if pnl > 0 else 0
        d["deployed"] += notional
    print(f"LIVE lane performance since {WINDOW_START} "
          f"({sum(d['n'] for d in lanes.values())} closed trades):")
    ret = {}
    for lane, d in sorted(lanes.items()):
        per_dollar = (d["pnl"] / d["deployed"]) if d["deployed"] > 0 else 0.0
        ret[lane] = per_dollar
        print(f"  {lane:15s} {d['n']:>4d} trades  P/L ${d['pnl']:>+9.2f}  "
              f"win {d['wins'] / max(d['n'], 1) * 100:>3.0f}%  "
              f"${d['deployed']:,.0f} traded  "
              f"({per_dollar * 100:+.2f}% per $ traded)")
    print("\nPROJECTION per $10k equity if each lane's capital scaled to the "
          "split\n(linear -- assumes the lane finds proportionally more of "
          "the same trades; thin\nlanes with 0 trades project $0 until they "
          "have history):")
    for name, split in SPLITS.items():
        proj = sum(10_000 * frac * ret.get(lane, 0.0) * 4  # ~4 turns/window
                   for lane, frac in split.items())
        parts = " / ".join(f"{lane.split('+')[0]} {int(frac * 100)}%"
                           for lane, frac in split.items())
        print(f"  {name:18s} -> ${proj:>+8.0f}   ({parts})")
    print("\nCAVEATS: linear scaling, one window, paper fills; forex/options "
          "lanes are\nyoung -- rerun weekly as history accumulates before "
          "moving real pocket sizes.")
