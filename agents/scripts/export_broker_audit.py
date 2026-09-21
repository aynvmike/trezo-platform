"""Export three paper accounts using GET only; never starts the agent runtime.

Run using agents/.venv/Scripts/python.exe scripts/export_broker_audit.py
Optional: --after 2026-09-01T00:00:00Z --until 2026-09-18T00:00:00Z
          --output broker-audit.json
Output files are exclusively created; existing files are never overwritten.
"""

import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--after", help="Timezone-aware start, exclusive; default: 24 hours before end")
    parser.add_argument("--until", help="Timezone-aware end, exclusive; default: now; maximum window: 3660 days")
    parser.add_argument("--max-pages", type=int, default=20, help="1-100 pages per order/activity collection")
    parser.add_argument("--output", type=Path, help="New file; relative paths use the invoking directory")
    args = parser.parse_args()
    output = args.output.resolve() if args.output else None
    if output and output.exists():
        print('{"error":"output_exists"}', file=sys.stderr)
        return 2
    try:
        agents = Path(__file__).resolve().parents[1]
        os.chdir(agents)  # Pydantic reads agents/.env; no dotenv or runtime imports.
        sys.path.insert(0, str(agents))
        from app.config import get_settings
        from app.brokers.accounts import load_accounts, validation_report
        from app.brokers.reporting import export_audit, ReadFailed
        if str(get_settings().trading_mode).strip().lower() != "paper":
            raise ReadFailed("configured_mode_is_not_paper")
        if validation_report():
            raise ReadFailed("account_registry_invalid")
        report = export_audit(load_accounts(), after=args.after, until=args.until,
                              max_pages=args.max_pages)
        encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if output:
            with output.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
        else:
            print(encoded, end="")
        return 0 if report["complete"] else 1
    except Exception as exc:
        # No exception text, traceback, settings, credentials or response bodies.
        category = str(exc) if type(exc).__name__ == "ReadFailed" else "export_failed"
        print(json.dumps({"error": category}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
