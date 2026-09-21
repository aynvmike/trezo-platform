"""Run one read-only broker scorecard pass; never start the trading engine."""
import argparse
import asyncio
from datetime import date
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat,
                        help="Nightly window ending 21:30 ET on YYYY-MM-DD")
    parser.add_argument("--report-dir", default=None)
    args = parser.parse_args()
    agents = Path(__file__).resolve().parents[1]
    os.chdir(agents)
    sys.path.insert(0, str(agents))
    from app.paper.receipt_pnl import run_nightly
    messages = asyncio.run(run_nightly(args.date, report_dir=args.report_dir))
    for message in messages:
        print(f"{message.payload['user_id']}: {message.payload['status']}")
    return 0 if messages and all(m.payload["status"] == "complete" for m in messages) else 1


if __name__ == "__main__":
    raise SystemExit(main())
