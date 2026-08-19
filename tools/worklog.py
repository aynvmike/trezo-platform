#!/usr/bin/env python3
"""Trezo work log -- reconstruct project time from git, for Mike's records.

WHY THIS IS A SCRIPT AND NOT A MAINTAINED FILE (2026-08-19):
a hand-kept tally drifts and quietly goes wrong; git already holds the
evidence, so the log is DERIVED and can be regenerated at any moment,
including months from now. Nothing to keep up to date, nothing to forget.

WHAT ONLY LIVES HERE:
PROJECT_START below is the timestamp on the first Trezo folder Mike
created. The repo does not begin until 2026-06-01, so roughly the first
seventeen days of work exist in NO commit. If this constant is lost, that
period is unrecoverable. Do not "clean it up".

HONESTY OF THE NUMBERS:
the commit-span total is a FLOOR, not an estimate of hours worked. It
counts only days that produced a commit, and only the window between that
day's first and last commit. It credits nothing for the pre-repo days and
nothing for days spent on research, SQL, server operations or incident
triage that produced no commit -- 2026-08-19 is the standing example: a
~22h span whose largest pieces (rung replays, process forensics, migration
testing against a scratch Postgres) left no commit at all. Report it as a
floor. Mike adds untracked hours himself; --csv is built to be appended to.

Usage:
    python3 tools/worklog.py                 # summary + table
    python3 tools/worklog.py --csv out.csv   # export for records
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# The folder Mike created, local time. NOT derivable from git -- see above.
PROJECT_START = datetime(2026, 5, 15, 15, 43, 15)

# A day with any commit represents real work even if every commit landed in
# the same minute; credit an hour rather than zero.
MIN_CREDIT_HOURS = 1.0

REPO = Path(__file__).resolve().parents[1]


def _git_log() -> list[tuple[datetime, str]]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "log", "--format=%ad%x09%s",
         "--date=format:%Y-%m-%d %H:%M"],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        print(f"git log failed: {out.stderr.strip()}", file=sys.stderr)
        raise SystemExit(1)
    rows = []
    for line in out.stdout.splitlines():
        if "\t" not in line:
            continue
        stamp, subject = line.split("\t", 1)
        try:
            rows.append((datetime.strptime(stamp, "%Y-%m-%d %H:%M"), subject))
        except ValueError:
            continue
    return sorted(rows)


def build(now: datetime | None = None) -> tuple[list[dict], dict]:
    commits = _git_log()
    if not commits:
        raise SystemExit("no commits found")
    now = now or datetime.now()

    by_day: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for ts, subject in commits:
        by_day[ts.strftime("%Y-%m-%d")].append((ts, subject))

    days = []
    for d in sorted(by_day):
        entries = sorted(by_day[d])
        span = (entries[-1][0] - entries[0][0]).total_seconds() / 3600.0
        days.append({
            "date": d,
            "commits": len(entries),
            "first": entries[0][0].strftime("%H:%M"),
            "last": entries[-1][0].strftime("%H:%M"),
            "span_hours": round(span, 2),
            "credited_hours": round(max(span, MIN_CREDIT_HOURS), 2),
            # the day's headline: longest commit subject reads as the summary
            "summary": max((s for _, s in entries), key=len).split("\n")[0][:90],
        })

    elapsed = now - PROJECT_START
    first_commit_day = days[0]["date"]
    pre_repo = (datetime.strptime(first_commit_day, "%Y-%m-%d")
                - PROJECT_START).days

    totals = {
        "project_start": PROJECT_START.strftime("%Y-%m-%d %H:%M:%S"),
        "as_of": now.strftime("%Y-%m-%d %H:%M"),
        "elapsed_days": elapsed.days,
        "elapsed_weeks": round(elapsed.total_seconds() / 86400 / 7, 2),
        "pre_repo_days_untracked": pre_repo,
        "commits": len(commits),
        "active_days": len(days),
        "credited_hours_floor": round(sum(d["credited_hours"] for d in days), 1),
    }
    totals["avg_hours_per_active_day"] = (
        round(totals["credited_hours_floor"] / len(days), 1) if days else 0.0)
    return days, totals


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", metavar="PATH", help="write the log to CSV")
    args = ap.parse_args()

    days, t = build()

    print(f"Trezo work log -- as of {t['as_of']}")
    print(f"Project start (folder created): {t['project_start']}")
    print(f"Elapsed: {t['elapsed_days']} days ({t['elapsed_weeks']} weeks)")
    print(f"Pre-repo days with no commit evidence: {t['pre_repo_days_untracked']}")
    print(f"Commits: {t['commits']} across {t['active_days']} active days")
    print(f"Credited hours (FLOOR, see docstring): {t['credited_hours_floor']}")
    print(f"Average per active day: {t['avg_hours_per_active_day']} h")
    print()
    print(f"{'date':<12}{'commits':>8}{'first':>7}{'last':>7}{'hours':>8}  summary")
    for d in days:
        print(f"{d['date']:<12}{d['commits']:>8}{d['first']:>7}{d['last']:>7}"
              f"{d['credited_hours']:>8}  {d['summary']}")

    if args.csv:
        path = Path(args.csv)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["# Trezo work log", f"generated {t['as_of']}"])
            w.writerow(["# project start", t["project_start"]])
            w.writerow(["# NOTE", "credited hours are a FLOOR from git commit "
                                  "spans; pre-repo and non-commit work not "
                                  "included -- append manual rows below"])
            w.writerow([])
            w.writerow(["date", "commits", "first_commit", "last_commit",
                        "hours", "source", "summary"])
            for d in days:
                w.writerow([d["date"], d["commits"], d["first"], d["last"],
                            d["credited_hours"], "git", d["summary"]])
            w.writerow([])
            w.writerow(["# add untracked days below with source=manual"])
        print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
