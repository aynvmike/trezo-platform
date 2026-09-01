"""Unwind the 2026-08-28 phantom-close P&L (audit PH-2 / PH-5).

WHAT HAPPENED
  Between 2026-08-25 and 2026-08-29 the crypto reconcile loop on the 75k
  book repeatedly "closed" a DOT position it had itself just re-adopted:
  identical quantity 13060.3846, identical entry 0.925859 (pinned at the
  broker's average while the market fell -- a real re-buy would have
  reset it), close -> re-adopt minutes apart. Each loop booked a realized
  loss that never happened at the venue. The strict-read fix landed
  2026-08-29 21:06 UTC, after the last phantom close. The 2026-09-01 audit
  re-derived the damage to the cent: 10 proven rows on the 75k book
  summing -7,462.53, plus three rows on the primary book (-13.12).

WHAT THIS DOES
  DRY RUN (default): selects and prints the candidate rows by the proven
  signature, the primary book's three rows by id, and -- separately, as
  NOT IN SCOPE -- the ambiguous 8/24 row 584cad86 (different basis;
  settle against Alpaca order history) and the 25k book's rows. Refuses
  to go further if the counts or sums differ from the audited figures.

  --apply: for every in-scope paper_positions row, sets
  realized_pnl_usd = 0 and merges a `phantom_unwind` object into
  source_payload {original_pnl, original_status, unwound_at, why} so the
  original is preserved and the change is reversible. Then does the same
  on the matching trade_outcomes rows (source_table='paper_positions',
  position_id in the set): realized_pnl_usd = 0, original merged into
  entry_payload (the forensics jsonb, 0032). trade_outcomes has no
  separate `pnl` column -- realized_pnl_usd is the only P&L field there.
  Nothing is DELETED, ever. Prints the before/after verification query.

WHAT THIS NEVER TOUCHES
  paper_accounts counters and kill-switch baselines. The audit verified
  them clean -- the phantoms live in row truth only -- and since the 8/31
  weekly roll they sit outside the kill-switch window.

RUN
  cd agents
  .venv\\Scripts\\python.exe tools\\unwind_phantom_pnl.py           # dry run
  .venv\\Scripts\\python.exe tools\\unwind_phantom_pnl.py --apply   # after Mike's approval

Reads agents/.env through app.config.get_settings (pydantic). Prints key
NAMES only, never values.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Same convention as agents/tests: put the agents dir on sys.path so
# `app.*` imports resolve without installing the package.
AGENTS_DIR = Path(__file__).resolve().parents[1]
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

# ---- The proven signature (audit §2.6 / engine record PH-2) -----------
BOOK_75K = "49acafdd-1c86-4740-a1b1-f94aa7abce08"     # Trezo Inc. 2 - 75k
BOOK_25K = "6ce61054-7ffd-41b5-80c3-1cd0220c79eb"     # Trezo Inc. 3 - 25k
BOOK_PRIMARY = "cf1b0460-039d-40ac-adc8-7ca3ef17c5bb"  # trezo_claudecowork
BOOK_LABELS = {BOOK_75K: "75k", BOOK_25K: "25k", BOOK_PRIMARY: "primary"}

TICKER = "DOT"
QTY_LO, QTY_HI = 13060.38, 13060.39
ENTRY_LO, ENTRY_HI = 0.9258, 0.9259
EXIT_FROM, EXIT_TO = "2026-08-25", "2026-08-30"   # [from, to)
# Wider window used only to LIST what sits next to the signature.
CONTEXT_FROM = "2026-08-24"

PRIMARY_IDS = [
    "d3ceef0b-bd05-4495-bb6c-d0384bba8ed6",
    "00797270-ef4d-4411-ba3c-5802b01e8d86",
    "c9331ced-369b-4c2f-8f51-066fb87f7aed",
]
AMBIGUOUS_PREFIX = "584cad86"   # -182.61, different basis: NOT in scope

EXPECTED_75K_COUNT = 10
EXPECTED_75K_SUM = Decimal("-7462.53")
EXPECTED_PRIMARY_COUNT = 3
EXPECTED_PRIMARY_SUM = Decimal("-13.12")
TOLERANCE = Decimal("0.005")

TAG = "phantom_unwind"
WHY = "2026-08-28 phantom-close loop; audit PH-2"

POS_COLS = ("id,user_id,ticker,status,quantity,entry_price,exit_price,"
            "exit_at,realized_pnl_usd,source_payload")
OUT_COLS = ("id,user_id,position_id,ticker,status,exit_reason,quantity,"
            "entry_price,exit_price,realized_pnl_usd,closed_at,entry_payload")


# ---- plumbing ---------------------------------------------------------

def _client():
    # Settings(env_file=".env") is cwd-relative, so load from agents/.
    os.chdir(AGENTS_DIR)
    from app.config import get_settings
    s = get_settings()
    missing = [k for k, v in (("SUPABASE_URL", s.supabase_url),
                              ("SUPABASE_SERVICE_ROLE_KEY", s.supabase_service_role_key))
               if not v]
    if missing:
        sys.exit(f"refusing: {', '.join(missing)} not set in agents/.env")
    from supabase import create_client
    return create_client(s.supabase_url, s.supabase_service_role_key)


def _dec(v) -> Decimal:
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


def _money(v) -> str:
    return f"{_dec(v):,.2f}"


def _original_pnl(row: dict, payload_col: str) -> Decimal:
    """P&L as it stood BEFORE any unwind -- so a re-run still verifies
    against the audited sums instead of against zeros."""
    tag = ((row.get(payload_col) or {}).get(TAG)) if isinstance(row.get(payload_col), dict) else None
    if tag and "original_pnl" in tag:
        return _dec(tag["original_pnl"])
    return _dec(row.get("realized_pnl_usd"))


def _already(row: dict, payload_col: str) -> bool:
    p = row.get(payload_col)
    return isinstance(p, dict) and TAG in p


def _print_rows(title: str, rows: list[dict], payload_col: str = "source_payload") -> None:
    print(f"\n{title} ({len(rows)} row{'s' if len(rows) != 1 else ''})")
    if not rows:
        print("  (none)")
        return
    for r in rows:
        flag = "  [already unwound]" if _already(r, payload_col) else ""
        when = r.get("exit_at") or r.get("closed_at") or ""
        print(f"  {r['id']}  {BOOK_LABELS.get(r.get('user_id'), r.get('user_id'))[:8]:<8} "
              f"{r.get('ticker', ''):<5} {str(r.get('status') or r.get('exit_reason') or ''):<16} "
              f"qty={_dec(r.get('quantity')):.6f} entry={_dec(r.get('entry_price')):.6f} "
              f"exit={_dec(r.get('exit_price')):.6f} at={str(when)[:19]} "
              f"pnl={_money(r.get('realized_pnl_usd')):>10}{flag}")


# ---- selection --------------------------------------------------------

def select_candidates(client) -> dict:
    pp = client.table("paper_positions")

    sig = (pp.select(POS_COLS)
           .eq("user_id", BOOK_75K).eq("ticker", TICKER).like("status", "closed%")
           .gte("quantity", QTY_LO).lte("quantity", QTY_HI)
           .gte("entry_price", ENTRY_LO).lte("entry_price", ENTRY_HI)
           .gte("exit_at", EXIT_FROM).lt("exit_at", EXIT_TO)
           .order("exit_at").execute().data or [])
    sig_ids = {r["id"] for r in sig}

    # Everything else DOT/closed on the 75k book around the window: the
    # ambiguous row and anything unexpected -- listed, never touched.
    ctx_75k = (pp.select(POS_COLS)
               .eq("user_id", BOOK_75K).eq("ticker", TICKER).like("status", "closed%")
               .gte("exit_at", CONTEXT_FROM).lt("exit_at", EXIT_TO)
               .order("exit_at").execute().data or [])
    out_75k = [r for r in ctx_75k if r["id"] not in sig_ids]
    ambiguous = [r for r in out_75k if str(r["id"]).startswith(AMBIGUOUS_PREFIX)]
    other_75k = [r for r in out_75k if not str(r["id"]).startswith(AMBIGUOUS_PREFIX)]

    primary = (pp.select(POS_COLS).in_("id", PRIMARY_IDS)
               .order("exit_at").execute().data or [])

    rows_25k = (pp.select(POS_COLS)
                .eq("user_id", BOOK_25K).eq("ticker", TICKER).like("status", "closed%")
                .gte("exit_at", CONTEXT_FROM).lt("exit_at", EXIT_TO)
                .order("exit_at").execute().data or [])

    targets = sig + primary
    target_ids = [r["id"] for r in targets]
    outcomes = []
    if target_ids:
        outcomes = (client.table("trade_outcomes").select(OUT_COLS)
                    .eq("source_table", "paper_positions").in_("position_id", target_ids)
                    .order("closed_at").execute().data or [])

    return {
        "sig": sig, "primary": primary, "ambiguous": ambiguous,
        "other_75k": other_75k, "rows_25k": rows_25k,
        "targets": targets, "outcomes": outcomes,
    }


def check(sel: dict) -> list[str]:
    """Return the list of reasons to REFUSE; empty means proceed."""
    problems: list[str] = []

    sig_sum = sum((_original_pnl(r, "source_payload") for r in sel["sig"]), Decimal("0"))
    if len(sel["sig"]) != EXPECTED_75K_COUNT:
        problems.append(f"75k signature: expected {EXPECTED_75K_COUNT} rows, found {len(sel['sig'])}")
    if abs(sig_sum - EXPECTED_75K_SUM) > TOLERANCE:
        problems.append(f"75k signature: expected sum {EXPECTED_75K_SUM}, found {sig_sum}")

    prim_sum = sum((_original_pnl(r, "source_payload") for r in sel["primary"]), Decimal("0"))
    if len(sel["primary"]) != EXPECTED_PRIMARY_COUNT:
        problems.append(f"primary ids: expected {EXPECTED_PRIMARY_COUNT} rows, found {len(sel['primary'])}")
    if abs(prim_sum - EXPECTED_PRIMARY_SUM) > TOLERANCE:
        problems.append(f"primary ids: expected sum {EXPECTED_PRIMARY_SUM}, found {prim_sum}")
    for r in sel["primary"]:
        if r.get("user_id") != BOOK_PRIMARY:
            problems.append(f"primary id {r['id']} belongs to book {r.get('user_id')}, not the primary")
        if r.get("ticker") != TICKER or not str(r.get("status", "")).startswith("closed"):
            problems.append(f"primary id {r['id']} is {r.get('ticker')}/{r.get('status')}, expected DOT/closed*")

    for r in sel["sig"]:
        if str(r["id"]).startswith(AMBIGUOUS_PREFIX):
            problems.append(f"ambiguous row {r['id']} matched the signature -- must never be in scope")
    for r in sel["targets"]:
        if r.get("user_id") == BOOK_25K:
            problems.append(f"25k-book row {r['id']} is in the target set -- must never be in scope")

    # trade_outcomes: a position may have 0 or 1 outcome rows (0033's
    # delete policy lets the owner remove them); more than one is odd.
    seen: dict[str, int] = {}
    for o in sel["outcomes"]:
        seen[o["position_id"]] = seen.get(o["position_id"], 0) + 1
    dupes = [pid for pid, n in seen.items() if n > 1]
    if dupes:
        problems.append(f"trade_outcomes has multiple rows for position(s) {dupes}")

    return problems


# ---- verification -----------------------------------------------------

def verify(client, target_ids: list[str], label: str) -> None:
    """The before/after query: sums and tag counts over the target set."""
    pos = (client.table("paper_positions").select("id,realized_pnl_usd,source_payload")
           .in_("id", target_ids).execute().data or [])
    outs = (client.table("trade_outcomes").select("id,position_id,realized_pnl_usd,entry_payload")
            .eq("source_table", "paper_positions").in_("position_id", target_ids).execute().data or [])
    pos_sum = sum((_dec(r.get("realized_pnl_usd")) for r in pos), Decimal("0"))
    out_sum = sum((_dec(r.get("realized_pnl_usd")) for r in outs), Decimal("0"))
    pos_tag = sum(1 for r in pos if _already(r, "source_payload"))
    out_tag = sum(1 for r in outs if _already(r, "entry_payload"))
    pos_orig = sum((_original_pnl(r, "source_payload") for r in pos), Decimal("0"))
    print(f"\n== verification: {label} ==")
    print(f"  paper_positions  rows={len(pos):<3} realized_pnl_usd sum={_money(pos_sum):>12}  "
          f"tagged={pos_tag}  (original sum preserved in tags: {_money(pos_orig)})")
    print(f"  trade_outcomes   rows={len(outs):<3} realized_pnl_usd sum={_money(out_sum):>12}  "
          f"tagged={out_tag}")


# ---- apply ------------------------------------------------------------

def apply(client, sel: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    done = skipped = 0
    for r in sel["targets"]:
        if _already(r, "source_payload"):
            skipped += 1
            continue
        payload = dict(r.get("source_payload") or {})
        payload[TAG] = {
            "original_pnl": float(_dec(r.get("realized_pnl_usd"))),
            "original_status": r.get("status"),
            "unwound_at": now,
            "why": WHY,
        }
        (client.table("paper_positions")
         .update({"realized_pnl_usd": 0, "source_payload": payload})
         .eq("id", r["id"]).execute())
        done += 1
    print(f"\npaper_positions: {done} unwound, {skipped} already tagged (left alone)")

    done = skipped = 0
    for o in sel["outcomes"]:
        if _already(o, "entry_payload"):
            skipped += 1
            continue
        payload = dict(o.get("entry_payload") or {})
        payload[TAG] = {
            "original_pnl": float(_dec(o.get("realized_pnl_usd"))),
            "position_id": o.get("position_id"),
            "unwound_at": now,
            "why": WHY,
        }
        (client.table("trade_outcomes")
         .update({"realized_pnl_usd": 0, "entry_payload": payload})
         .eq("id", o["id"]).execute())
        done += 1
    print(f"trade_outcomes:  {done} unwound, {skipped} already tagged (left alone)")


# ---- main -------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="write the unwind (default is a dry run that changes nothing)")
    args = ap.parse_args(argv)

    client = _client()
    sel = select_candidates(client)

    print("PHANTOM P&L UNWIND -- " + ("APPLY" if args.apply else "DRY RUN (nothing written)"))
    _print_rows("IN SCOPE: 75k book, proven signature", sel["sig"])
    print(f"  sum = {_money(sum((_original_pnl(r, 'source_payload') for r in sel['sig']), Decimal('0')))}"
          f"  (expected {EXPECTED_75K_SUM:,}, {EXPECTED_75K_COUNT} rows)")
    _print_rows("IN SCOPE: primary book, by id", sel["primary"])
    print(f"  sum = {_money(sum((_original_pnl(r, 'source_payload') for r in sel['primary']), Decimal('0')))}"
          f"  (expected {EXPECTED_PRIMARY_SUM:,}, {EXPECTED_PRIMARY_COUNT} rows)")
    _print_rows("NOT IN SCOPE: ambiguous 8/24 row (settle against Alpaca order history)", sel["ambiguous"])
    _print_rows("NOT IN SCOPE: other 75k DOT closes in the window", sel["other_75k"])
    _print_rows("NOT IN SCOPE: 25k book DOT closes in the window", sel["rows_25k"])
    _print_rows("trade_outcomes rows that will be zeroed with their positions",
                sel["outcomes"], payload_col="entry_payload")

    problems = check(sel)
    if problems:
        print("\nREFUSING -- the rows do not match the audited figures:")
        for p in problems:
            print(f"  - {p}")
        print("Nothing was written. Re-verify against the audit before changing the constants.")
        return 2

    target_ids = [r["id"] for r in sel["targets"]]
    print(f"\nchecks passed: {len(target_ids)} positions, {len(sel['outcomes'])} outcome rows in scope")
    verify(client, target_ids, "BEFORE")

    if not args.apply:
        print("\ndry run complete -- re-run with --apply to write the unwind.")
        return 0

    apply(client, sel)
    verify(client, target_ids, "AFTER")
    print("\ndone. paper_accounts was not touched. Originals live under "
          f"source_payload.{TAG} / entry_payload.{TAG} for reversal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
