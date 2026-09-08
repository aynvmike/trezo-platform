"""Run the internal research pilot on an explicit offline OHLC JSON dataset.

Example (cost inputs are required research assumptions, not market estimates):
python -m app.research --input candles.json --db research.sqlite3 --book demo \
    --symbol SPY --capital 1000 --commission-bps 2 --slippage-bps 5
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .cycle import run_cycle


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline, internal strategy research; no orders or model calls.")
    parser.add_argument("--input", required=True, help="JSON array of timestamped OHLC candles")
    parser.add_argument("--db", required=True, help="Durable research SQLite journal")
    parser.add_argument("--book", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--capital", required=True, type=float)
    parser.add_argument("--commission-bps", required=True, type=float)
    parser.add_argument("--slippage-bps", required=True, type=float)
    parser.add_argument("--cycle-key", help="Optional idempotent cycle label; default uses dataset hash")
    parser.add_argument("--output", help="Optional JSON report file; stdout otherwise")
    args = parser.parse_args(argv)
    try:
        candles = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = run_cycle(args.db, book_id=args.book, symbol=args.symbol,
                           candles=candles, starting_capital=args.capital,
                           commission_bps=args.commission_bps,
                           slippage_bps=args.slippage_bps, cycle_key=args.cycle_key)
        serialized = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            Path(args.output).write_text(serialized, encoding="utf-8")
        else:
            print(serialized, end="")
        return 0 if result.get("status") == "completed" else 1
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
