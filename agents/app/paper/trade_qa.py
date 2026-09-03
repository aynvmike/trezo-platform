"""Trade QA -- the inspector on the line.

Mike, 2026-09-02: "is there a way to get a checker to loop and make sure
that everything is up to code with each trade. Like a Quality Assurance
person on a line -- if there is something wrong it can be sent back to
get checked and inspected and priced."

THE CASE THIS EXISTS FOR. Order edefd889-bc5c-4cf3-9c0a-03eee25e0162 on
the 75k book: SELL 1 NOBL260918P00055000, a cash-secured put. Submitted
17:07:11Z. NOT filled when the executor looked. Filled 18:25:20Z -- 78
minutes later -- 1 contract at 0.05. `paper_positions` has zero NOBL rows
in any status on any book. The broker holds a short put; the ledger does
not know it exists, so it has no stop, no target, no ladder and no owner.
An alert fired. Alerting is all that happened.

THE CLASS OF BUG, not the instance: the executor writes the ledger row
from the SUBMIT result, and nothing in the platform owns the question
"what became of the orders I sent?" There is no pending-order ledger and
no post-trade verification, so late fills, partial fills, and fills that
land after a restart all fall through the same hole.

WHY THE RECONCILERS THAT CAME BEFORE MADE IT WORSE. They compare POSITION
SNAPSHOTS and then guess. A broker position with no row got adopted with
INVENTED geometry (adoption._default_geometry clamps a stop 4% under the
CURRENT price -- that is how a DOT position ended up with a -13.6% stop).
A row with no broker position got closed at a modelled price with "no
closing fill found so P/L unknown". That guessing is what produced the
close-and-re-adopt loops: one DOT position closed and re-adopted seven
times in four days, each cycle resetting its clock and its geometry.

WHAT IS DIFFERENT HERE -- HOUSE RULE 6. Alpaca keeps the authoritative
paperwork and nothing read it. /v2/orders?status=all gives every order id
and status; /v2/account/activities gives every fill with qty, price and
time. A reconciliation grounded in a RECEIPT (an order id plus fill
records) is not a guess, it is bookkeeping. So:

    NOTHING here is written without a receipt. Absence is never evidence.
    "Not in the snapshot" does not close a row, does not void an order and
    does not create anything. Ambiguity is quarantined and named, never
    averaged and never resolved by preferring one source.

WHAT SHIPS LIVE vs WHAT IS SWITCHED OFF
  LIVE, and read-only at the ledger: the working-order SHIELD, every
  invariant, every finding, every activity row, every alert.
  BEHIND TREZO_QA_AUTOFIX (default "0" = OFF): all five repair actions.
  With it off, each one emits a `qa_would_fix` row stating exactly what it
  WOULD have written. A week of those rows is the pre-flight evidence for
  turning it on -- it is not a "recommended posture", it is the default.

WHAT THIS NEVER DOES
  * Never places, cancels, replaces or modifies a broker order. Read-only
    at the venue by construction. A missing bracket is FLAGGED.
  * Never writes stop_price or target_price. Not a default percentage,
    not clamped to the mark, not inherited, not remembered from a ticket.
    A fill receipt records what HAPPENED and contains no intent. There is
    deliberately no _default_geometry equivalent in this module for anyone
    to reach for later. A QA-created row is born quarantined and stopless
    and says so, loudly, until a human prices it.
  * Never calls engine.record_external_position (engine.py:673 requires
    stop_price/target_price positionally AND merges into an existing open
    row by weighted average -- routing a create through it makes QA the
    next phantom generator on day one).
  * Never writes to options_positions, never reopens a closed row, never
    corrects entry_at, never adds a status value.

HOUSE RULE 2: every book is its own book. Every read happens inside
bind_for_user + route_guard.check_route, and every row written or logged
carries user_id. ops_health_alerts has no user_id column, so the book is
encoded in `target_name` as "<book>:<symbol>" -- HR2 honoured in
behaviour, not in the column type.

HOUSE RULE 3: all three reads are strict, and a window that could not be
read to EXHAUSTION counts as a failed read. ANY None skips the WHOLE book
for that sweep -- no writes, no tickets, one qa_skipped_unreadable row
naming alpaca.last_read_error(). Never a partial sweep: a positions read
paired with a failed orders read is exactly the snapshot-only reasoning
that lost NOBL.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Knobs. Read at CALL time, never captured at import, so the deploy gate and
# ops can change posture without a restart -- and so a test can set one.
# ---------------------------------------------------------------------------


def _env(name: str, default: str) -> str:
    return str(os.getenv(name, default) or default)


def _envf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _envi(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def autofix_on() -> bool:
    """OFF is the shipped default. A week of qa_would_fix rows earns write
    access; nothing else does."""
    return _env("TREZO_QA_AUTOFIX", "0").strip().lower() in ("1", "true", "yes", "on")


def lookback_h() -> float:
    return _envf("TREZO_QA_LOOKBACK_H", 72.0)


def max_writes() -> int:
    return _envi("TREZO_QA_MAX_WRITES", 5)


def sweep_interval_s() -> float:
    """Full sweep cadence. book_health ticks every 300s and its checks are
    cheap; three broker reads plus a ledger inspection are not, so the full
    pass rides every Nth tick instead of every tick."""
    return _envf("TREZO_QA_INTERVAL_S", 1800.0)


def shield_refresh_s() -> float:
    """The SHIELD refreshes far more often than the full sweep: it is one
    orders read, and a shield answered from a 30-minute-old snapshot would
    return a stale False for exactly the orders it exists to catch."""
    return _envf("TREZO_QA_SHIELD_REFRESH_S", 300.0)


def shield_ttl_s() -> float:
    """Two refresh cycles. Past this the shield answers None, never False."""
    return shield_refresh_s() * 2.0


def shield_max_h() -> float:
    return _envf("TREZO_QA_SHIELD_MAX_H", 24.0)


def stuck_min_for(asset_type: str) -> float:
    """D2 proposed a 5-minute blanket. On the option lane that is noise
    before it is signal -- an option order resting for 8 minutes is a
    Tuesday -- so the lanes are split and both are tunable from a week of
    rows."""
    if asset_type == "option":
        return _envf("TREZO_QA_STUCK_MIN_OPTION", 20.0)
    return _envf("TREZO_QA_STUCK_MIN_STOCK", 5.0)


def entry_drift_min() -> float:
    return _envf("TREZO_QA_ENTRY_DRIFT_MIN", 15.0)


def stop_credit_mult() -> float:
    """I5b: how many times the received credit a short option's stop may
    imply as a buy-back loss before it is called out. NOBL's live geometry
    is 0.315 against a 0.05 credit -- 6.3x. The other eight short option
    rows on the platform sit between 1.2x and 2.1x."""
    return _envf("TREZO_QA_STOP_CREDIT_MULT", 3.0)


def adoption_on() -> bool:
    """position_monitor's orphan adopter. If it is running, QA must not
    also create rows -- two creators racing on the same orphan is the
    'changing two reconcilers at once' mistake, arriving through the door
    the plan left open."""
    return _env("TREZO_ADOPT_ORPHANS", "1").strip().lower() not in ("0", "false", "no", "off")


# ---------------------------------------------------------------------------
# Tolerances. Two independent broker records must AGREE before anything is
# written. Crypto is relative on both axes -- fractional quantities forbid
# absolute tolerances (0.00000001 BTC is not "close to zero", it is a real
# holding, and 1e-6 absolute would swallow a whole DOGE position).
# ---------------------------------------------------------------------------

_TOL = {
    "stock":  {"qty_abs": 1e-6, "px_abs": 0.01},
    "option": {"qty_abs": 1e-6, "px_abs": 0.005},
    "crypto": {"qty_rel": 1e-8, "px_rel": 5e-4},   # 5 bps
}


# ---------------------------------------------------------------------------
# Symbol normalisation. ONE function, used before EVERY comparison and every
# write. The rule is adoption._ledger_ticker's rule (coins bare, options as
# the OCC verbatim, everything else upper-cased); test_trade_qa asserts the
# two agree, so a change to one is caught by the gate rather than by a
# duplicate BTC row.
# ---------------------------------------------------------------------------


def asset_class_of(broker_row: dict) -> str:
    """stock | option | crypto, from the broker's own asset_class first."""
    ac = str(broker_row.get("asset_class") or "").strip().lower()
    if ac in ("us_option", "option"):
        return "option"
    if ac == "crypto":
        return "crypto"
    if ac in ("us_equity", "stock", "equity"):
        return "stock"
    sym = str(broker_row.get("symbol") or "")
    if len(sym) >= 15 and any(c.isdigit() for c in sym):
        return "option"
    if "/" in sym or (sym.upper().endswith("USD") and len(sym) > 4):
        return "crypto"
    return "stock"


def ledger_symbol(symbol: Any, asset_type: Optional[str] = None) -> str:
    """How the LEDGER spells this instrument.

    Coins are stored bare ('BTC'), which is why a broker 'BTC/USD' or
    'BTCUSD' must be normalised before it is compared to a row or written
    into one. Without this the first crypto orphan gets a duplicate
    paper_positions row under a spelling the ledger does not use, and the
    monitor manages one coin from two rows -- a new phantom generator
    shipped by the component whose whole purpose is to end phantoms.
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return ""
    if asset_type is None:
        asset_type = asset_class_of({"symbol": sym})
    if asset_type == "option":
        return sym                      # OCC verbatim
    if asset_type == "crypto":
        if "/" in sym:
            return sym.split("/", 1)[0]
        if sym.endswith("USD") and len(sym) > 4:
            return sym[:-3]
    return sym


def occ_for_row(row: dict) -> str:
    """The OCC code an options_positions row describes.

    The option lane's close path is keyed on the CONTRACT, not the
    underlying. A shield handed 'NOBL' where NOBL260918P00055000 is
    required protects nothing on the very lane that produced the
    acceptance case.
    """
    try:
        exp = str(row.get("expiration") or "")
        cp = "C" if str(row.get("option_type") or "").lower().startswith("c") else "P"
        return (f"{str(row.get('underlying') or '').upper()}"
                f"{exp[2:4]}{exp[5:7]}{exp[8:10]}{cp}"
                f"{int(round(float(row.get('strike') or 0) * 1000)):08d}")
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Receipt -- the only thing that authorises a write.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Receipt:
    """An order id plus what the venue says actually happened.

    Every write helper below takes one as a REQUIRED POSITIONAL argument.
    There is deliberately no signature in this module that can write
    without one: a receipt cannot be forgotten, only supplied.
    """

    order_id: str
    symbol: str                 # broker spelling, as the receipt carries it
    side: str                   # buy | sell
    filled_qty: float
    filled_avg_price: float
    filled_at: str
    source: str                 # fills | expiry | assignment | order_void

    def as_dict(self) -> dict:
        return {"order_id": self.order_id, "symbol": self.symbol,
                "side": self.side, "filled_qty": self.filled_qty,
                "filled_avg_price": self.filled_avg_price,
                "filled_at": self.filled_at, "source": self.source}


@dataclass
class Finding:
    code: str
    symbol: str
    message: str
    severity: str = "warn"          # info | warn | urgent
    row_id: Optional[str] = None
    order_ids: tuple = ()
    extra: dict = field(default_factory=dict)

    def as_finding(self) -> dict:
        d = {"finding": self.code, "symbol": self.symbol,
             "severity": self.severity, "reason": self.message}
        if self.row_id:
            d["row_id"] = self.row_id
        if self.order_ids:
            d["order_ids"] = list(self.order_ids)
        d.update(self.extra)
        return d


def blank_report(user_id: str) -> dict:
    """D1's report shape, plus `standing`. `skipped_reason` is MANDATORY
    and is None only on a pass that actually ran -- a skipped book must
    never be readable as a clean one.

    `findings` carries the EDGES only -- the conditions that became true
    on this pass. book_health turns each one into a bus message and every
    bus message is persisted, so anything re-reported every sweep is a row
    per condition per book per sweep, forever (ADVISORY B). Conditions
    that are still true and already ticketed go to `standing`, which
    nothing messages and nothing persists.
    """
    return {"user_id": str(user_id or ""), "booked": 0, "rebased": 0,
            "voided": 0, "closed": 0, "flagged": 0, "quarantined": 0,
            "checked": 0, "skipped_reason": None, "findings": [],
            "standing": [], "would_fix": []}


# ---------------------------------------------------------------------------
# Seams. Every broker and log call goes through a module attribute so a test
# can patch the ATTRIBUTE and restore it -- no fakes in sys.modules.
# The activity_log import is LATE, inside the function (house rule 4), so the
# gate's quiet_activity_log stub reaches it.
# ---------------------------------------------------------------------------


def _log(event: str, ticker: str, *, reason: str = "",
         strategy: Optional[str] = None, extra: Optional[dict] = None) -> None:
    try:
        from app.agents.activity_log import record
        record(event, ticker or "-", strategy=strategy,
               reason=reason[:290], extra=extra or {})
    except Exception:  # noqa: BLE001
        pass


async def _notify(title: str, body: str, *, severity: str, key: str,
                  fields: Optional[dict] = None) -> None:
    try:
        from app.runtime.alerts import notify
        await notify(title, body, severity=severity, key=key, fields=fields)
    except Exception:  # noqa: BLE001
        pass


async def _read_positions(user_id: str) -> Optional[list]:
    """Broker positions, FRESH. max_age_s=0 deliberately: book_health's own
    tick populates a 45s-TTL snapshot for free, and judging a trade against
    a snapshot another tick left behind is exactly the stale-set bug QA
    exists to catch. Three extra calls per book per sweep is the price."""
    from app.runtime import book_scope
    return await book_scope.positions(user_id, where="trade_qa", max_age_s=0)


async def _read_orders(after_iso: str) -> Optional[list]:
    from app.brokers import alpaca
    return await alpaca.get_orders_all_strict(after_iso)


async def _read_open_orders() -> Optional[list]:
    """Orders still OPEN at the venue, right now. NOT a historical window.

    Two things need this and neither is answered by the sweep's 72-hour
    status=all read (ADVISORY A and C, review 2026-09-02):

      * the SHIELD only ever asks "is an entry WORKING?", and asking that
        of a 72-hour window costs up to eight pages per book per five
        minutes and becomes permanently unexhaustible past a few thousand
        orders -- which turns the shield off for good;
      * I5 asks "does the broker hold a resting stop for this row?", and
        a stop LEG placed 102 hours ago is not in a 72-hour window at all.
        Judged against that window it reads as absent, which is a false
        'nothing is protecting this position' on a row that is protected.
    """
    from app.brokers import alpaca
    return await alpaca.get_open_orders_all_strict()


async def _read_fills(after_iso: str) -> Optional[list]:
    from app.brokers import alpaca
    return await alpaca.get_fill_activities_strict(after_iso)


async def _read_order(order_id: str) -> tuple:
    from app.brokers import alpaca
    return await alpaca.get_order_strict(order_id)


def _last_read_error() -> str:
    try:
        from app.brokers import alpaca
        return alpaca.last_read_error() or ""
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# THE SHIELD.
#
# FOUR paths close a row when the broker "does not list" its symbol. None of
# them asked whether an order for that symbol was still WORKING. NOBL was
# working for 78 minutes; any close decided inside that window is a phantom
# manufactured from absence. The four, and how often each runs:
#
#   app/paper/stocks_reconcile.py      the 30-minute stock reconcile
#   app/agents/options_scanner.py      the 30-minute option reconcile
#   app/agents/position_monitor.py     the 60-second tick, stock AND option
#                                      rows -- 5-minute fresh-row grace only
#   app/agents/position_monitor.py     the 60-second tick, crypto lane --
#                                      no grace at all
#
# The last two were found unwired by the review of 2026-09-02 (BLOCKER 3):
# they run 30x and 60x more often than the two that shipped shielded, and
# both close at a MODELLED price through record_external_close, so they are
# the paths the acceptance case would have fallen through first.
# test_trade_qa pins the list; add a path there when you add one here.
#
# Deliberately NOT persisted. A cache that survives a restart can shield on
# an answer nobody has re-checked; "unknown" after a restart is the safe
# direction, because unknown skips the close.
# ---------------------------------------------------------------------------

# book -> {"ts": float, "entries": {ledger_symbol: {"ids": [...], "age_s": f}}}
_SHIELD: dict = {}
# book -> unix ts of the last FULL sweep that actually ran
_LAST_SWEEP_OK: dict = {}
# book -> unix ts of the last full sweep ATTEMPT, successful or not. The
# gate backs off on this, not on success: a book whose reads keep failing
# would otherwise retry three broker calls every book_health tick, adding
# load to a venue that is already refusing us. The SHIELD keeps refreshing
# every 300s regardless -- that is the part with a safety job.
_LAST_SWEEP_TRY: dict = {}
# book -> unix ts of the last shield refresh that actually ran
_LAST_SHIELD_OK: dict = {}
# (book, symbol, code) that currently have an open ticket. Edge-triggered,
# modelled on ops_watchdog._open_alerts: the row, the alert and the
# source_payload block are written on TRANSITION only. Without this the
# design writes thousands of identical UPDATEs a day onto live trading rows
# and buries route_mismatch and execute_error in the log Mike reads.
_OPEN_TICKETS: set = set()


def _is_entry_working(order: dict, row_side: Optional[str] = None) -> bool:
    """True when an ENTRY may still arrive for this order.

    A resting protective leg is NOT an entry in flight -- it is protection,
    and it feeds I5. Shielding on it would return True for every bracketed
    stock row and silently switch stocks_reconcile's close path off.

    RE-REVIEW 2026-09-02, BLOCKING: excluding protective TYPES and child
    legs is not enough, because the most common resting order in this book
    is neither. A take-profit is a plain GTC LIMIT with no order_class and
    no legs -- exactly what alpaca.ensure_crypto_take_profit posts (called
    from position_monitor twice) and exactly the shape submit_oco_sell's
    PARENT takes, which alpaca.get_open_orders_for already documents as
    "a lone resting sell limit". Counting one as an entry inverted the
    shield's whole promise: it returned True forever for that symbol, so
    all four close-on-absence paths went silently off (a genuinely phantom
    row was then neither closed NOR flagged -- I2 returns early on the
    shield), and the same order raised an URGENT "working for 1800
    minutes" alert, because a GTC exit rests for days by design.

    So an order only counts as an entry when nothing about it says EXIT:
      * not a protective type, not a child leg (as before);
      * not an OCO -- submit_oco_sell / submit_oco_buy are its only
        producers here and both are exit pairs by construction;
      * not carrying a protective child leg (the OCO/bracket parent);
      * and its side OPENS rather than closes the row we are shielding.
    Side is the decisive one, and it is why `row_side` is threaded in: for
    a long, a sell is an exit; for a short, a buy is. When the side is
    unknown the order is still treated as an entry -- the shield errs
    toward not closing, which is the safe direction for a bookkeeping
    refusal.
    """
    status = str(order.get("status") or "").lower()
    if status not in _entry_statuses():
        return False
    if str(order.get("type") or order.get("order_type") or "").lower() in _protective_types():
        return False
    # A child leg of a bracket carries its parent's id. Alpaca sets
    # `legs` on the PARENT; children are reached only through it, so a
    # flattened list marks them by having no legs and a parent linkage.
    if order.get("_qa_is_leg"):
        return False
    if str(order.get("order_class") or "").lower() in ("oco", "oto", "bracket"):
        return False
    legs = order.get("legs")
    if isinstance(legs, list):
        for _leg in legs:
            if not isinstance(_leg, dict):
                continue
            if str(_leg.get("type") or "").lower() in _protective_types():
                return False        # this is an exit pair's parent
    if _closes_side(order, row_side):
        return False
    return True


def _closes_side(order: dict, row_side: Optional[str]) -> bool:
    """Does this order's side CLOSE a position of `row_side` rather than
    open one? Unknown side -> False (treat as an entry; the shield errs
    toward refusing to close, never toward closing)."""
    side = str(order.get("side") or "").strip().lower()
    rs = str(row_side or "").strip().lower()
    if not side or rs not in ("long", "short"):
        return False
    if rs == "long":
        return side.startswith("sell")
    return side.startswith("buy")


def _entry_statuses() -> frozenset:
    try:
        from app.brokers.alpaca import ENTRY_WORKING_STATUSES
        return ENTRY_WORKING_STATUSES
    except Exception:  # noqa: BLE001
        return frozenset({"new", "pending_new", "accepted",
                          "accepted_for_bidding", "partially_filled",
                          "pending_replace", "calculated"})


def _protective_types() -> frozenset:
    try:
        from app.brokers.alpaca import PROTECTIVE_ORDER_TYPES
        return PROTECTIVE_ORDER_TYPES
    except Exception:  # noqa: BLE001
        return frozenset({"stop", "stop_limit", "trailing_stop"})


def _mark_legs(orders: list) -> list:
    """Tag flattened child legs so the shield can tell an entry from a
    resting exit. _flatten_order_legs emits parents first, then their
    children; a child is any order whose id appeared under some parent's
    `legs`."""
    leg_ids: set = set()
    for o in orders:
        if not isinstance(o, dict):
            continue
        for lg in (o.get("legs") or []):
            if isinstance(lg, dict) and lg.get("id"):
                leg_ids.add(lg["id"])
    out = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        o = dict(o)
        o["_qa_is_leg"] = bool(o.get("id") in leg_ids)
        out.append(o)
    return out


def has_working_order(user_id: str, symbol: str,
                      row_side: Optional[str] = None) -> Optional[bool]:
    """Is an ENTRY order for this instrument still working at the venue?

    True  -> yes. Do not close the row from a position snapshot.
    False -> no working entry, as of a snapshot no older than shield_ttl_s.
    None  -> COULD NOT CHECK. Not a green light (house rule 3): ALL FOUR
             call sites must skip the close on None exactly as on True.

    `symbol` must be the spelling the INSTRUMENT is identified by: an OCC
    code for an option row (build it before calling), a bare coin for
    crypto, the ticker for a stock. It is normalised here anyway, but an
    underlying passed where an OCC belongs cannot be recovered.
    """
    book = str(user_id or "")
    if not book:
        return None
    ent = _SHIELD.get(book)
    if not isinstance(ent, dict):
        return None                     # never swept, or restarted
    if (time.time() - float(ent.get("ts") or 0)) > shield_ttl_s():
        return None                     # stale: unknown, never a stale False
    key = ledger_symbol(symbol)
    if not key:
        return None
    slot = (ent.get("entries") or {}).get(key)
    if not slot:
        return False
    # Side test at QUERY time (re-review 2026-09-02). `row_side` is the
    # side of the row about to be closed; an order whose side would CLOSE
    # that row is an exit resting at the venue -- a take-profit, an OCO
    # parent -- not an entry in flight. Shielding on one turned all four
    # close paths off for every symbol carrying a take-profit, silently.
    # Unknown row_side keeps the old, safer-in-the-close-direction answer.
    sides = slot.get("sides")
    if row_side is None or not isinstance(sides, list) or not sides:
        return True
    return any(not _closes_side({"side": s}, row_side) for s in sides)


def due(user_id: str, *, now: Optional[float] = None) -> bool:
    """Is a FULL sweep due for this book? Backs off on ATTEMPTS, not on
    successes, so a book that cannot be read is not re-read every tick."""
    t = time.time() if now is None else now
    uid = str(user_id or "")
    last = max(float(_LAST_SWEEP_OK.get(uid, 0.0)),
               float(_LAST_SWEEP_TRY.get(uid, 0.0)))
    return (t - last) >= sweep_interval_s()


def shield_due(user_id: str, *, now: Optional[float] = None) -> bool:
    t = time.time() if now is None else now
    return (t - float(_LAST_SHIELD_OK.get(str(user_id or ""), 0.0))) >= shield_refresh_s()


def reset_state() -> None:
    """Tests only: drop every in-memory cache."""
    _SHIELD.clear()
    _LAST_SWEEP_OK.clear()
    _LAST_SWEEP_TRY.clear()
    _LAST_SHIELD_OK.clear()
    _OPEN_TICKETS.clear()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _after_iso(hours: float) -> str:
    """The window start, as a QUERY PARAMETER.

    Z-form, deliberately NOT datetime.isoformat(). isoformat() on a
    tz-aware UTC datetime yields '2026-08-30T22:25:06.904155+00:00', that
    '+' is a legal query sub-delimiter so no HTTP client escapes it, and a
    form-decoder reads it back as a space. alpaca._q() now encodes it at
    the point of use as well -- belt and braces, because this string is
    the input to the one read the SHIELD depends on, and a shield that
    cannot populate refuses every close on the platform (BLOCKER 2,
    2026-09-02).
    """
    return (datetime.now(timezone.utc) - timedelta(hours=hours)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: Any) -> Optional[datetime]:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def refresh_shield_for_book(user_id: str) -> dict:
    """One orders read; repopulate this book's shield entries.

    Runs on EVERY book_health tick (300s), not on the sweep cadence: the
    shield is the only part of this module wired into other agents'
    close paths, and it is worthless if it answers from a half-hour-old
    snapshot. ONE call per book per five minutes -- status=open, which is
    one page essentially always. It used to be a 72-hour status=all window
    at up to eight pages, which past a few thousand orders could never be
    exhausted and so answered None forever (ADVISORY A, 2026-09-02).

    On a failed read the previous entries are LEFT ALONE and simply age
    out to None -- overwriting them with an empty set would turn a broker
    blip into a green light for every close on the book.
    """
    uid = str(user_id or "")
    out = {"user_id": uid, "symbols": 0, "skipped_reason": None}
    try:
        from app.brokers.accounts import bind_for_user
        from app.brokers.route_guard import check_route
    except Exception as e:  # noqa: BLE001
        out["skipped_reason"] = f"cannot bind book: {type(e).__name__}"
        return out
    with bind_for_user(uid) as book:
        if book is None:
            out["skipped_reason"] = f"unresolved book {uid[:8]}"
            return out
        ok, why = check_route(uid)
        if not ok:
            out["skipped_reason"] = f"route refused: {why}"
            return out
        # status=open, not a 72h status=all window -- see _read_open_orders.
        orders = await _read_open_orders()
        if orders is None:
            out["skipped_reason"] = (
                f"orders read failed: {_last_read_error() or 'reason not captured'}")
            return out
        entries: dict = {}
        for o in _mark_legs(orders):
            if not _is_entry_working(o):
                continue
            at = asset_class_of(o)
            key = ledger_symbol(o.get("symbol"), at)
            if not key:
                continue
            slot = entries.setdefault(key, {"ids": [], "oldest": None,
                                            "sides": []})
            if o.get("id"):
                slot["ids"].append(str(o["id"]))
            # The SIDE is kept so the side test can run at QUERY time,
            # where the row being shielded is known. A lone resting
            # take-profit is a plain limit with no class and no legs --
            # only its side, read against the row's side, tells it apart
            # from an entry (re-review 2026-09-02).
            slot["sides"].append(str(o.get("side") or "").strip().lower())
            ts = _parse_ts(o.get("submitted_at") or o.get("created_at"))
            if ts and (slot["oldest"] is None or ts < slot["oldest"]):
                slot["oldest"] = ts
        _SHIELD[uid] = {"ts": time.time(), "entries": entries}
        _LAST_SHIELD_OK[uid] = time.time()
        out["symbols"] = len(entries)
    return out


# ---------------------------------------------------------------------------
# The arithmetic gate (clause c).
# ---------------------------------------------------------------------------


def _tol_for(asset_type: str) -> dict:
    return _TOL.get(asset_type, _TOL["stock"])


def _qty_matches(a: float, b: float, asset_type: str) -> bool:
    t = _tol_for(asset_type)
    if "qty_rel" in t:
        scale = max(abs(a), abs(b), 1e-12)
        return abs(a - b) / scale <= t["qty_rel"]
    return abs(a - b) <= t["qty_abs"]


def _price_matches(a: float, b: float, asset_type: str) -> tuple[bool, str]:
    """(ok, note). The note names a UNIT mismatch rather than swallowing it.

    Option prices are compared as PER-SHARE premium -- 0.05, not 5.00 --
    on both sides, which is how Alpaca reports filled_avg_price. If the
    only way the two agree is a factor of 100, that is reported as a named
    unit disagreement and quarantined: it is a question about the venue's
    reporting, and inventing an answer to it is precisely what house rule 6
    forbids.
    """
    t = _tol_for(asset_type)
    if "px_rel" in t:
        scale = max(abs(a), abs(b), 1e-12)
        if abs(a - b) / scale <= t["px_rel"]:
            return True, ""
    elif abs(a - b) <= t["px_abs"]:
        return True, ""
    if asset_type == "option" and b and abs(a - b / 100.0) <= t["px_abs"]:
        return False, ("price unit disagreement: the position's "
                       f"avg_entry_price {b:g} looks per-CONTRACT while the "
                       f"fills average {a:g} per share -- a human must settle "
                       "the unit before anything is written")
    return False, (f"weighted fill price {a:g} does not match the broker's "
                   f"avg_entry_price {b:g}")


def _arith_gate(position: dict, fills: list, asset_type: str
                ) -> tuple[bool, str, float, float, list]:
    """Do two independent broker records agree?
    (ok, reason, qty, price, OPENING FILLS USED).

    The fills in the window are partitioned BY SIDE against the position's
    direction. The opening-side fills must reconcile to the broker's own
    |qty| and avg_entry_price. Any opposite-side fill for the same symbol
    inside the window means the window contains a round trip -- the
    position on the books may not be the one those fills built -- and that
    is an automatic quarantine, never an averaging.

    Review 2026-09-02 (BLOCKER 1): the fifth element is the whole point.
    The caller used to re-derive the receipt's timestamp from the WHOLE
    window -- every activity for the symbol, including OPEXP/OPASN rows
    that carry no side and so land in NEITHER partition here. An expiry
    dated weeks after the fill therefore became the entry_at written into
    the ledger: a timestamp no fill supports, on the one write path this
    module has. The receipt may only ever be built from the records this
    gate actually reconciled, so this returns them rather than trusting a
    second derivation to pick the same set.
    """
    pos_qty = _f(position.get("qty"))
    if pos_qty == 0:
        return False, "broker reports zero quantity", 0.0, 0.0, []
    long = pos_qty > 0
    open_side = "buy" if long else "sell"
    close_side = "sell" if long else "buy"
    opening = [f for f in fills
               if str(f.get("side") or "").lower().startswith(open_side)]
    closing = [f for f in fills
               if str(f.get("side") or "").lower().startswith(close_side)]
    if closing:
        ids = sorted({str(f.get("order_id") or "?") for f in closing})[:4]
        return (False,
                f"round trip inside the window: {len(closing)} {close_side} "
                f"fill(s) for this symbol too ({', '.join(ids)})", 0.0, 0.0, [])
    if not opening:
        return False, "no opening-side fill in the window", 0.0, 0.0, []
    qty = 0.0
    notional = 0.0
    for f in opening:
        q = abs(_f(f.get("qty")))
        px = _f(f.get("price"))
        if q <= 0 or px <= 0:
            return (False,
                    f"a fill carries no usable qty/price ({q:g} @ {px:g})",
                    0.0, 0.0, [])
        qty += q
        notional += q * px
    px_avg = notional / qty if qty else 0.0
    if not _qty_matches(qty, abs(pos_qty), asset_type):
        return (False,
                f"fills sum to {qty:g} but the broker holds {abs(pos_qty):g}",
                qty, px_avg, [])
    ok_px, note = _price_matches(px_avg, abs(_f(position.get("avg_entry_price"))),
                                 asset_type)
    if not ok_px:
        return False, note, qty, px_avg, []
    return True, "", qty, px_avg, opening


def _entry_fill_at(opening_fills: list, order_id: str) -> str:
    """The EARLIEST timestamp among the opening fills that carry `order_id`.

    MIN, not max, and only over the fills the arithmetic gate used.

    * MIN because a position opened by two partial fills forty minutes
      apart was ENTERED at the first one. Booking the last one puts the
      row's entry_at forty minutes into the future of the trade, and
      entry_at drives time stops -- so a max here moves an exit. It also
      made the module flag its own freshly-written row for
      qa_entry_time_drift, whose reference IS the first fill.
    * only these fills, because anything else in the window (an OPEXP
      weeks later, a fill belonging to a different order) is not part of
      the receipt that authorised this write.

    Returns "" when nothing usable is present; the caller falls back to
    the ORDER's own filled_at, which is still the venue's record and not
    an invention.

    TWO CALLERS AS OF 2026-09-03, and that is deliberate. _handle_orphan
    below uses it for the rows THIS module books; app/paper/entry_receipt.py
    uses this exact function object (and _arith_gate, and ledger_symbol,
    and lookback_h) for the rows ADOPTION books, so the platform has ONE
    answer to "which fill is the entry" instead of two that drift until
    the inspector starts flagging rows the adopter had just written
    correctly. tests/test_entry_receipt.py asserts the identity, so
    renaming or reimplementing either side is a gate failure, not a
    silent divergence. If you change the convention here, that suite is
    where it has to be changed too.
    """
    best_raw = ""
    best_dt = None
    for f in opening_fills:
        if str(f.get("order_id") or "") != str(order_id):
            continue
        raw = str(f.get("transaction_time") or f.get("date") or "").strip()
        if not raw:
            continue
        # PARSED, not string-compared: the venue mixes 'Z' and '+00:00'
        # forms across endpoints, and lexicographic order gets that pair
        # backwards. The raw string is what gets written, so the row still
        # carries the venue's own spelling.
        dt = _parse_ts(raw)
        if dt is None:
            continue
        if best_dt is None or dt < best_dt:
            best_dt, best_raw = dt, raw
    return best_raw


# ---------------------------------------------------------------------------
# Ticketing. Edge-triggered: the activity row, the alert and the
# source_payload.qa block are written on TRANSITION only.
# ---------------------------------------------------------------------------


async def _persist_alert(client, *, kind: str, target: str, severity: str,
                         message: str) -> None:
    """One ops_health_alerts row (0040). The table has NO user_id column, so
    the book is encoded in target_name as '<book>:<symbol>'."""
    if client is None:
        return

    def _sync():
        return client.table("ops_health_alerts").insert({
            "alert_kind": kind, "target_name": target,
            "severity": severity if severity in ("info", "warn", "urgent") else "warn",
            "message": message[:900],
            "raised_at": _iso_now(),
        }).execute()
    try:
        await asyncio.to_thread(_sync)
    except Exception:  # noqa: BLE001
        pass


async def _raise_ticket(client, uid: str, f: Finding, rep: dict) -> bool:
    """Send a finding back down the line, once, on the EDGE.

    Returns True when this was a transition (the ticket was not already
    open) and False when the condition is simply still true.

    Review 2026-09-02 (ADVISORY B). The activity row, the alert and the
    ops_health_alerts insert were already edge-triggered -- but the append
    to rep['findings'] and the counters sat ABOVE the check, so every
    standing condition was re-reported in full on every sweep. That report
    is not a private return value: book_health extends its own findings
    with it and turns EACH ONE into an AgentMessage, and bootstrap's
    _persist subscriber writes every message that crosses the bus to
    Supabase. Driving the real sweep twice produced findings=49 on BOTH
    passes while exactly one alert was sent -- roughly 49 persisted rows
    per book per thirty minutes for a single contract, forever.

    So the edge decides everything now. What is STILL open is not lost:
    it goes to rep['standing'], which nothing turns into a message and a
    human reading a sweep report can still see.
    """
    key = (uid, f.symbol, f.code)
    if key in _OPEN_TICKETS:
        # already open: say nothing again, anywhere
        rep.setdefault("standing", []).append(
            {"finding": f.code, "symbol": f.symbol, "severity": f.severity})
        return False
    rep["findings"].append(f.as_finding())
    rep["flagged"] += 1
    _OPEN_TICKETS.add(key)
    _log("qa_quarantine" if f.severity == "urgent" else "qa_flag", f.symbol,
         reason=f"{f.code}: {f.message}",
         extra={"user_id": uid, "severity": f.severity,
                "row_id": f.row_id or "", "order_ids": list(f.order_ids)})
    await _notify(f"QA: {f.symbol} {f.code}", f.message,
                  severity=f.severity, key=f"qa:{uid}:{f.symbol}:{f.code}",
                  fields={"book": uid[:8], "row": f.row_id or "-"})
    await _persist_alert(client, kind=f.code, target=f"{uid}:{f.symbol}",
                         severity=f.severity, message=f.message)
    return True


def _clear_ticket(uid: str, symbol: str, code: str) -> None:
    key = (uid, symbol, code)
    if key in _OPEN_TICKETS:
        _OPEN_TICKETS.discard(key)
        _log("qa_cleared", symbol, reason=f"{code} no longer holds",
             extra={"user_id": uid})


# ---------------------------------------------------------------------------
# The sweep.
# ---------------------------------------------------------------------------


def _skip(rep: dict, uid: str, reason: str, *, event: str = "qa_skipped_unreadable"
          ) -> dict:
    rep["skipped_reason"] = reason
    _log(event, "-", reason=reason, extra={"user_id": uid})
    return rep


async def qa_sweep_for_book(client, user_id: str, *,
                            dry_run: Optional[bool] = None) -> dict:
    """Inspect every trade on ONE book against the broker's own paperwork.

    Returns D1's report shape. `skipped_reason` is None only when the pass
    actually ran: a book whose reads failed is never reported as clean.
    """
    uid = str(user_id or "")
    rep = blank_report(uid)
    _LAST_SWEEP_TRY[uid] = time.time()
    if dry_run is None:
        dry_run = not autofix_on()

    try:
        from app.brokers.accounts import bind_for_user
        from app.brokers.route_guard import check_route
    except Exception as e:  # noqa: BLE001
        return _skip(rep, uid, f"cannot bind book: {type(e).__name__}")

    # ---- I0 precondition: the book, then the route, then all three reads.
    with bind_for_user(uid) as book:
        if book is None:
            return _skip(rep, uid, f"unresolved book {uid[:8]} -- refusing")
        ok, why = check_route(uid)
        if not ok:
            return _skip(rep, uid, f"route refused: {why}")

        after = _after_iso(lookback_h())
        positions = await _read_positions(uid)
        if positions is None:
            await _maybe_shield_liveness_alert(client, uid, rep)
            return _skip(rep, uid, "positions read failed: "
                         f"{_last_read_error() or 'reason not captured'}")
        orders = await _read_orders(after)
        if orders is None:
            await _maybe_shield_liveness_alert(client, uid, rep)
            return _skip(rep, uid, "orders window unreadable or truncated: "
                         f"{_last_read_error() or 'reason not captured'}")
        fills = await _read_fills(after)
        if fills is None:
            await _maybe_shield_liveness_alert(client, uid, rep)
            return _skip(rep, uid, "fill activities unreadable or truncated: "
                         f"{_last_read_error() or 'reason not captured'}")

        # I5's evidence, and ONLY I5's: what is RESTING at the venue right
        # now. Deliberately NOT one of the three reads above whose failure
        # skips the book -- those three authorise writes, and this one
        # authorises nothing. On None, I5 is simply not asked this pass
        # (a flag withheld is a flag withheld; a flag raised from an
        # unreadable protective-order set is a false alarm on a live row).
        open_orders = await _read_open_orders()
        rep = await _inspect(client, uid, positions, _mark_legs(orders), fills,
                             rep, dry_run=dry_run, open_orders=open_orders)
        _LAST_SWEEP_OK[uid] = time.time()

    _log("qa_sweep", "-",
         reason=(f"checked {rep['checked']} · flagged {rep['flagged']} · "
                 f"quarantined {rep['quarantined']} · booked {rep['booked']} · "
                 f"would-fix {len(rep['would_fix'])} · "
                 f"autofix {'ON' if not dry_run else 'off'}"),
         extra={"user_id": uid, **{k: rep[k] for k in
                                   ("booked", "rebased", "voided", "closed",
                                    "flagged", "quarantined", "checked")}})
    return rep


async def _maybe_shield_liveness_alert(client, uid: str, rep: dict) -> None:
    """The shield is wired into two reconcilers' close paths and answers
    None when it cannot check -- and None skips the close. That is the safe
    direction, but a silent one: a sustained broker read failure would stop
    row-closing platform-wide with only an ABSENT log row as the alarm. So
    the absence gets a voice."""
    last = _LAST_SHIELD_OK.get(uid)
    if last is not None and (time.time() - float(last)) < shield_ttl_s() * 2:
        return
    since = ("since this engine started" if last is None
             else f"for {(time.time() - float(last)) / 60.0:.0f} minutes")
    f = Finding("qa_shield_stale", "-", severity="urgent",
                message=(f"Trezo has not been able to read this book's orders "
                         f"{since}. While that is true the QA shield answers "
                         f"'cannot check', and BOTH reconcilers skip closing "
                         f"rows rather than guess. Nothing is being closed on "
                         f"this book until the broker read recovers. Nothing is "
                         f"at risk from this by itself -- closing a row is "
                         f"bookkeeping, not an exit -- but the ledger will drift "
                         f"until it clears."))
    await _raise_ticket(client, uid, f, rep)


# ---------------------------------------------------------------------------


async def _rows_for_book(client, uid: str) -> Optional[list]:
    def _q():
        return (client.table("paper_positions")
                .select("id, ticker, asset_type, side, quantity, entry_price, "
                        "stop_price, target_price, status, entry_at, exit_at, "
                        "strategy, broker, broker_order_id, source_payload, "
                        "close_requested")
                .eq("user_id", uid).execute())
    try:
        return (await asyncio.to_thread(_q)).data or []
    except Exception:  # noqa: BLE001
        return None


async def _option_rows_for_book(client, uid: str) -> list:
    """options_positions, READ-ONLY. I6 (ledger singularity) cannot be asked
    without looking at both tables, and the wheel lane's laundering -- a
    closed_manual row for a contract the broker still holds -- is only
    visible here. Nothing in this module ever WRITES this table."""
    def _q():
        return (client.table("options_positions")
                .select("id, underlying, option_type, strike, expiration, "
                        "status, contracts, strategy, notes")
                .eq("user_id", uid).execute())
    try:
        return (await asyncio.to_thread(_q)).data or []
    except Exception:  # noqa: BLE001
        return []


async def _inspect(client, uid: str, positions: list, orders: list,
                   fills: list, rep: dict, *, dry_run: bool,
                   open_orders: Optional[list] = None) -> dict:
    rows = await _rows_for_book(client, uid)
    if rows is None:
        return _skip(rep, uid, "ledger read failed -- no partial sweep",
                     event="qa_read_deferred")
    opt_rows = await _option_rows_for_book(client, uid)

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=lookback_h())
    budget = {"left": max_writes()}

    # ---- indexes, all on the LEDGER spelling -------------------------
    orders_by_id = {str(o.get("id")): o for o in orders if o.get("id")}
    fills_by_sym: dict = {}
    for a in fills:
        at = asset_class_of(a)
        key = ledger_symbol(a.get("symbol"), at)
        if key:
            fills_by_sym.setdefault(key, []).append(a)

    open_rows: dict = {}
    rows_by_sym: dict = {}
    order_id_rows: dict = {}
    for r in rows:
        at = str(r.get("asset_type") or "stock").lower()
        key = ledger_symbol(r.get("ticker"), at)
        rows_by_sym.setdefault(key, []).append(r)
        if str(r.get("status") or "") == "open":
            open_rows.setdefault((key, str(r.get("side") or "long")), []).append(r)
        oid = str(r.get("broker_order_id") or "")
        if oid:
            order_id_rows.setdefault(oid, []).append(r)

    pos_by_key: dict = {}
    for p in positions:
        at = asset_class_of(p)
        key = ledger_symbol(p.get("symbol"), at)
        side = "long" if _f(p.get("qty")) >= 0 else "short"
        pos_by_key.setdefault((key, side), []).append(p)

    rep["checked"] = len(positions) + len(rows)

    # ---- I1 (graft): every working order is either young or loud -----
    await _check_orders_stuck(client, uid, orders, now, rep, open_rows)

    # ---- I1: FILL => ROW. The NOBL case. -----------------------------
    for (key, side), plist in sorted(pos_by_key.items()):
        if open_rows.get((key, side)):
            continue                                # I1 satisfied
        for p in plist:
            await _handle_orphan(client, uid, key, side, p, fills_by_sym,
                                 rows_by_sym, order_id_rows, orders_by_id,
                                 rep, budget, dry_run=dry_run)

    # ---- I3: POSITION => EXACTLY ONE OPEN ROW ------------------------
    for (key, side), rlist in sorted(open_rows.items()):
        if len(rlist) > 1:
            ids = [str(r.get("id")) for r in rlist]
            _edge = await _raise_ticket(client, uid, Finding(
                "qa_duplicate_rows", key, severity="urgent",
                message=(f"{len(rlist)} open {side} rows for {key} on one "
                         f"book. Two managers for one position: rows "
                         f"{', '.join(ids)}. Nothing was changed -- a human "
                         f"must say which one is real."),
                order_ids=tuple(ids)), rep)
            if _edge:
                rep["quarantined"] += 1
            continue
        _clear_ticket(uid, key, "qa_duplicate_rows")

    # ---- I2 / I4 / I5 / I5b, per open row ----------------------------
    for (key, side), rlist in sorted(open_rows.items()):
        for r in rlist:
            await _check_row(client, uid, key, side, r, pos_by_key,
                             fills_by_sym, window_start, rep, budget,
                             dry_run=dry_run, open_orders=open_orders)

    # ---- I6: ledger singularity --------------------------------------
    await _check_singularity(client, uid, rows, opt_rows, positions,
                             fills_by_sym, rep)

    # ---- the pre-existing backlog: ONE line, not a per-sweep flood ----
    await _report_legacy_backlog(client, uid, rows, window_start, rep)
    return rep


# ---------------------------------------------------------------------------


async def _check_orders_stuck(client, uid: str, orders: list,
                              now: datetime, rep: dict,
                              open_rows: Optional[dict] = None) -> None:
    """D1's I1. On 2026-09-02 NOBL sat working for 78 minutes and NOTHING
    said so. This is the alarm that did not exist.

    RE-REVIEW 2026-09-02: a resting GTC take-profit is not a stuck entry.
    It rests for days BY DESIGN, so alarming on one produced an urgent
    "working for 1800 minutes" per symbol carrying an exit -- exactly the
    noise that teaches an owner to stop reading the channel. `open_rows`
    is keyed (symbol, side), so an order whose side would CLOSE a row we
    hold is judged an exit and skipped."""
    _sides_held: dict = {}
    for (_k, _sd) in (open_rows or {}):
        _sides_held.setdefault(_k, set()).add(str(_sd or "").lower())
    for o in orders:
        _held_sides = _sides_held.get(
            ledger_symbol(o.get("symbol"), asset_class_of(o))) or set()
        if any(_closes_side(o, _sd) for _sd in _held_sides):
            continue        # a resting exit for a row we hold
        if not _is_entry_working(o):
            continue
        sub = _parse_ts(o.get("submitted_at") or o.get("created_at"))
        if sub is None:
            continue
        age_min = (now - sub).total_seconds() / 60.0
        at = asset_class_of(o)
        sym = ledger_symbol(o.get("symbol"), at)
        oid = str(o.get("id") or "?")
        if age_min < stuck_min_for(at):
            _clear_ticket(uid, sym, "qa_order_stuck")
            continue
        hard = age_min > shield_max_h() * 60.0
        msg = (f"Order {oid} ({str(o.get('side') or '?')} "
               f"{_f(o.get('qty')):g} {o.get('symbol')}) has been working for "
               f"{age_min:.0f} minutes and has not finished. "
               f"Filled so far: {_f(o.get('filled_qty')):g}. "
               f"Until it settles, Trezo will not close any row for this "
               f"instrument -- the shield is holding it open on purpose.")
        if hard:
            msg += (f" It is now past the {shield_max_h():.0f}-hour bound; "
                    f"the shield does NOT flip to 'safe to close' (that would "
                    f"be a green light nobody gave), so this needs a human.")
        await _raise_ticket(client, uid, Finding(
            "qa_stale_working_order" if hard else "qa_order_stuck",
            sym, severity="urgent" if hard else "warn", message=msg,
            order_ids=(oid,)), rep)
        _log("qa_order_stuck", sym,
             reason=f"{oid} working {age_min:.0f}m (lane threshold "
                    f"{stuck_min_for(at):.0f}m)",
             extra={"user_id": uid, "order_id": oid, "age_min": round(age_min, 1)})


async def _handle_orphan(client, uid: str, key: str, side: str, position: dict,
                         fills_by_sym: dict, rows_by_sym: dict,
                         order_id_rows: dict, orders_by_id: dict,
                         rep: dict, budget: dict, *, dry_run: bool) -> None:
    """The broker holds it; the ledger has no open row. THE NOBL CASE.

    This is the one place a receipt can authorise a CREATE, and every one
    of D1's six clauses has to hold first. Anything short of that is a
    ticket and nothing else -- "not in the snapshot" is never a receipt.
    """
    at = asset_class_of(position)
    sym_disp = str(position.get("symbol") or key)
    window_fills = fills_by_sym.get(key, [])

    # (b) A NAMED RECEIPT.
    if not window_fills:
        _edge = await _raise_ticket(client, uid, Finding(
            "qa_orphan_no_receipt", key, severity="urgent",
            message=(f"The broker holds {_f(position.get('qty')):g} "
                     f"{sym_disp} and this book has no open row for it, and "
                     f"there is no fill in the last {lookback_h():.0f} hours "
                     f"that explains it. Nothing is managing this position: "
                     f"no stop, no target, no ladder. Trezo will NOT invent a "
                     f"row for it -- a position with no paperwork is a "
                     f"question for a human, not a guess.")), rep)
        if _edge:
            rep["quarantined"] += 1
        return

    # (c) THE ARITHMETIC CLOSES.
    ok, why, qty, px, opening_fills = _arith_gate(position, window_fills, at)
    if not ok:
        _edge = await _raise_ticket(client, uid, Finding(
            "qa_receipt_conflict", key, severity="urgent",
            message=(f"{sym_disp}: the broker's records do not agree with "
                     f"each other, so nothing was written. {why}. Two "
                     f"independent broker records have to say the same thing "
                     f"before Trezo books anything."),
            order_ids=tuple(sorted({str(f.get('order_id') or '?')
                                    for f in window_fills})[:6])), rep)
        if _edge:
            rep["quarantined"] += 1
        return

    # (f) resolve the order, and (I9) refuse a single leg of a spread.
    # From the OPENING fills the gate reconciled, not from the whole window:
    # an OPEXP/OPASN row carries no order id and a fill for some other order
    # is not part of this receipt (BLOCKER 1, 2026-09-02).
    order_ids = sorted({str(f.get("order_id") or "") for f in opening_fills
                        if f.get("order_id")})
    if not order_ids:
        _edge = await _raise_ticket(client, uid, Finding(
            "qa_orphan_no_receipt", key, severity="urgent",
            message=(f"{sym_disp}: fills exist in the window but none carries "
                     f"an order id, so there is no receipt to book against.")), rep)
        if _edge:
            rep["quarantined"] += 1
        return
    if len(order_ids) > 1:
        _edge = await _raise_ticket(client, uid, Finding(
            "qa_ambiguous_receipt", key, severity="urgent",
            message=(f"{sym_disp}: {len(order_ids)} different orders produced "
                     f"the fills behind this position "
                     f"({', '.join(order_ids[:5])}). Trezo will not pick one. "
                     f"A human has to say which order this row belongs to."),
            order_ids=tuple(order_ids)), rep)
        if _edge:
            rep["quarantined"] += 1
        return
    oid = order_ids[0]

    # Dereference the order itself -- ALWAYS, not "if it happens to be in
    # the window". /v2/orders/{id} has no time filter, and this is the only
    # thing that makes order_class and legs knowable for a multi-day
    # position whose parent order sits outside the lookback.
    order = orders_by_id.get(oid)
    if order is None:
        order, reason = await _read_order(oid)
        if order is None and reason is not None:
            await _raise_ticket(client, uid, Finding(
                "qa_read_deferred", key, severity="warn",
                message=(f"{sym_disp}: could not read order {oid} "
                         f"({reason}). Nothing written; will retry."),
                order_ids=(oid,)), rep)
            return
        if order is None:
            _edge = await _raise_ticket(client, uid, Finding(
                "qa_receipt_conflict", key, severity="urgent",
                message=(f"{sym_disp}: the fills name order {oid} but the "
                         f"broker says there is no such order. Nothing "
                         f"written."), order_ids=(oid,)), rep)
            if _edge:
                rep["quarantined"] += 1
            return

    # I9: A MULTI-LEG ORDER IS ONE TRADE.
    oclass = str(order.get("order_class") or "").lower()
    legs = order.get("legs") or []
    if oclass == "mleg" or (oclass and oclass not in ("simple", "bracket", "oto", "oco") and legs):
        leg_names = [str(l.get("symbol") or "?") for l in legs] or [sym_disp]
        _edge = await _raise_ticket(client, uid, Finding(
            "qa_multileg_refused", key, severity="urgent",
            message=(f"Order {oid} is a {oclass or 'multi-leg'} order covering "
                     f"{', '.join(leg_names)}. Booking one leg of a spread on "
                     f"its own would read as a naked short. The whole order is "
                     f"quarantined; a human has to book it as one trade."),
            order_ids=(oid,)), rep)
        if _edge:
            rep["quarantined"] += 1
        return

    # THE ENTRY TIME. From the opening fills this order produced, earliest
    # first -- see _entry_fill_at. Never from the window at large: that is
    # how an OPEXP dated weeks later became a live row's entry_at.
    fill_at = _entry_fill_at(opening_fills, oid) or str(order.get("filled_at") or "")
    if not fill_at:
        # No timestamp anywhere in the paperwork. entry_at drives time
        # stops, so a blank or invented one is a written value the receipt
        # does not settle -- exactly what house rule 6 forbids. Ticket it.
        _edge = await _raise_ticket(client, uid, Finding(
            "qa_receipt_conflict", key, severity="urgent",
            message=(f"{sym_disp}: order {oid} reconciles on quantity and "
                     f"price, but neither its fills nor the order itself "
                     f"carries a fill TIME. entry_at drives time stops, so "
                     f"Trezo will not book a row with a made-up one. Nothing "
                     f"written."), order_ids=(oid,)), rep)
        if _edge:
            rep["quarantined"] += 1
        return
    receipt = Receipt(order_id=oid, symbol=sym_disp,
                      side="buy" if _f(position.get("qty")) > 0 else "sell",
                      filled_qty=qty, filled_avg_price=px,
                      filled_at=fill_at,
                      source="fills")
    _log("qa_receipt_linked", key,
         reason=(f"order {oid} -> {qty:g} @ {px:g} at {receipt.filled_at} "
                 f"(agrees with the broker's own position)"),
         extra={"user_id": uid, "order_id": oid})

    await _book_row(receipt, client, uid, key, side, position, at,
                    rows_by_sym, order_id_rows, rep, budget, dry_run=dry_run)


async def _book_row(receipt: Receipt, client, uid: str, ledger_sym: str,
                    side: str, position: dict, asset_type: str,
                    rows_by_sym: dict, order_id_rows: dict, rep: dict,
                    budget: dict, *, dry_run: bool) -> None:
    """A1 -- the ONE write a receipt settles beyond doubt.

    Direct insert. NOT engine.record_external_position: that function takes
    stop_price and target_price as required positional floats and MERGES
    into an existing open row for the same (user_id, ticker, side, 'open'),
    rewriting its quantity, entry, stop and target by weighted average. QA
    routing a create through it would silently rewrite a live row's geometry
    the first time it ran.

    stop_price and target_price are OMITTED FROM THE PAYLOAD ENTIRELY (both
    nullable per 0008). Not zero, not a percentage, not the mark -- absent.
    The row is born quarantined as `qa_needs_geometry` and says so until a
    human prices it. `status` stays 'open': no new status value, so the 0051
    CHECK constraint and position_status.py are untouched.
    """
    # (a) for a create: precisely ZERO rows in ANY status, on the LEDGER
    # spelling. Same-pass, re-read, not from the index -- another lane may
    # have written one while this sweep was running.
    def _guard():
        return (client.table("paper_positions")
                .select("id, status, broker_order_id")
                .eq("user_id", uid).eq("ticker", ledger_sym).execute())
    try:
        existing = (await asyncio.to_thread(_guard)).data or []
    except Exception as e:  # noqa: BLE001
        await _raise_ticket(client, uid, Finding(
            "qa_read_deferred", ledger_sym, severity="warn",
            message=(f"Could not re-check {ledger_sym} before booking "
                     f"({type(e).__name__}). Nothing written.")), rep)
        return
    if existing:
        # Idempotence: this order is already on the books. Not a finding.
        if any(str(r.get("broker_order_id") or "") == receipt.order_id
               for r in existing):
            _log("qa_booked", ledger_sym,
                 reason=f"order {receipt.order_id} already on the books -- "
                        f"nothing to do",
                 extra={"user_id": uid, "order_id": receipt.order_id})
            return
        _edge = await _raise_ticket(client, uid, Finding(
            "qa_overbook_refused", ledger_sym, severity="urgent",
            message=(f"{ledger_sym} already has "
                     f"{len(existing)} row(s) on this book "
                     f"({', '.join(str(r.get('id')) for r in existing[:4])}) "
                     f"in status "
                     f"{', '.join(sorted({str(r.get('status')) for r in existing}))}. "
                     f"The broker's position is not accounted for by any OPEN "
                     f"row, but writing a second one would put two managers on "
                     f"one position. Nothing written."),
            order_ids=(receipt.order_id,)), rep)
        if _edge:
            rep["quarantined"] += 1
        return

    payload = {
        "user_id": uid,
        "ticker": ledger_sym,               # LEDGER spelling, always
        "asset_type": asset_type,
        "side": side,
        "quantity": receipt.filled_qty,
        "entry_price": receipt.filled_avg_price,
        "entry_at": receipt.filled_at,      # THE FILL TIME, not now()
        "status": "open",
        "broker": "alpaca",
        "broker_order_id": receipt.order_id,
        "strategy": "qa_unassigned",        # a question, not an answer
        "source_payload": {
            "qa_created": True,
            "qa": {"state": "quarantined", "findings": ["needs_geometry"],
                   "since": _iso_now(), "receipt": receipt.as_dict()},
        },
    }
    # Structural proof of the MUST-NOT, asserted where it is written rather
    # than trusted to review: no geometry key may reach the payload.
    assert "stop_price" not in payload and "target_price" not in payload

    if dry_run:
        rep["would_fix"].append({"action": "A1_create", "payload": payload})
        _log("qa_would_fix", ledger_sym,
             reason=(f"WOULD create an open row: {receipt.filled_qty:g} @ "
                     f"{receipt.filled_avg_price:g} from order "
                     f"{receipt.order_id} filled {receipt.filled_at}. No stop "
                     f"and no target would be written. AUTOFIX is off, so "
                     f"nothing was."),
             extra={"user_id": uid, "order_id": receipt.order_id,
                    "quantity": receipt.filled_qty,
                    "entry_price": receipt.filled_avg_price,
                    "entry_at": receipt.filled_at})
        return

    if adoption_on():
        # Two creators racing on one orphan is how this platform got here.
        await _raise_ticket(client, uid, Finding(
            "qa_create_blocked_adoption", ledger_sym, severity="warn",
            message=("QA autofix is ON but TREZO_ADOPT_ORPHANS is also on, so "
                     "the orphan adopter is still creating rows too. Two "
                     "creators on one position is the exact mistake this "
                     "component exists to stop. Nothing written -- set "
                     "TREZO_ADOPT_ORPHANS=0 first, or turn QA autofix back "
                     "off."), order_ids=(receipt.order_id,)), rep)
        return

    if budget["left"] <= 0:
        _log("qa_write_budget_hit", ledger_sym,
             reason=(f"{max_writes()} writes already made on this book this "
                     f"pass; deferring the rest to the next sweep"),
             extra={"user_id": uid})
        return
    budget["left"] -= 1

    def _insert():
        return client.table("paper_positions").insert(payload).execute()
    try:
        await asyncio.to_thread(_insert)
    except Exception as e:  # noqa: BLE001
        await _raise_ticket(client, uid, Finding(
            "qa_write_failed", ledger_sym, severity="urgent",
            message=f"Insert refused: {type(e).__name__}: {str(e)[:140]}",
            order_ids=(receipt.order_id,)), rep)
        return
    rep["booked"] += 1
    rep["quarantined"] += 1
    _log("qa_booked", ledger_sym,
         reason=(f"Booked from the broker's own receipt: order "
                 f"{receipt.order_id}, {receipt.filled_qty:g} @ "
                 f"{receipt.filled_avg_price:g}, filled {receipt.filled_at}. "
                 f"NO stop and NO target were written -- this row is "
                 f"quarantined until a human prices it."),
         strategy="qa_unassigned",
         extra={"user_id": uid, "order_id": receipt.order_id})
    await _raise_ticket(client, uid, Finding(
        "qa_needs_geometry", ledger_sym, severity="urgent",
        message=(f"Trezo has booked {receipt.filled_qty:g} {ledger_sym} from "
                 f"the broker's fill record ({receipt.filled_avg_price:g} at "
                 f"{receipt.filled_at}) so it is no longer invisible. It has "
                 f"NO STOP and NO TARGET: a fill record says what happened, "
                 f"not what the exit should be, and Trezo will not invent one. "
                 f"This position needs to be priced by hand."),
        order_ids=(receipt.order_id,)), rep)


async def _check_row(client, uid: str, key: str, side: str, r: dict,
                     pos_by_key: dict, fills_by_sym: dict,
                     window_start: datetime, rep: dict, budget: dict,
                     *, dry_run: bool,
                     open_orders: Optional[list] = None) -> None:
    """I2, I4, I5 and I5b for one open row. All read-only at the ledger."""
    at = str(r.get("asset_type") or "stock").lower()
    rid = str(r.get("id") or "")
    held = bool(pos_by_key.get((key, side)))

    # ---- I2: ROW => POSITION, UNLESS AN ORDER IS WORKING -------------
    if not held:
        shielded = has_working_order(uid, key, side)
        if shielded:
            _log("qa_shield", key,
                 reason=("row has no broker position but an entry order is "
                         "still working -- not treated as a phantom"),
                 extra={"user_id": uid, "row_id": rid})
            return
        if shielded is None:
            _log("qa_read_deferred", key,
                 reason="cannot tell whether an order is working; judging "
                        "nothing about this row this pass",
                 extra={"user_id": uid, "row_id": rid})
            return
        # A receipted CLOSING fill is the ONLY thing that may say a row is
        # finished. Absence never is -- that is the DOT/QYLD/AMZN loop.
        close_side = "sell" if side == "long" else "buy"
        closing = [f for f in fills_by_sym.get(key, [])
                   if str(f.get("side") or "").lower().startswith(close_side)]
        expiry = [f for f in fills_by_sym.get(key, [])
                  if str(f.get("activity_type") or "").upper() in ("OPEXP", "OPASN", "OPEXC")]
        if closing:
            px = (sum(abs(_f(f.get("qty"))) * _f(f.get("price")) for f in closing)
                  / max(sum(abs(_f(f.get("qty"))) for f in closing), 1e-12))
            _log("qa_phantom_close_proven", key,
                 reason=(f"row {rid} has a receipted closing fill at {px:g}; "
                         f"a close here would be bookkeeping, not a guess"),
                 extra={"user_id": uid, "row_id": rid})
            rep["would_fix"].append({"action": "A5_close_receipted",
                                     "row_id": rid, "exit_price": px})
            _log("qa_would_fix", key,
                 reason=(f"WOULD close row {rid} at the ACTUAL closing fill "
                         f"price {px:g}. AUTOFIX is off, so nothing was."),
                 extra={"user_id": uid, "row_id": rid})
            return
        if expiry:
            kinds = sorted({str(f.get("activity_type") or "").upper() for f in expiry})
            _log("qa_receipt_linked", key,
                 reason=(f"row {rid} ended by {', '.join(kinds)} -- the wheel's "
                         f"normal outcome, not a phantom"),
                 extra={"user_id": uid, "row_id": rid})
            rep["would_fix"].append({"action": "A5_close_expiry",
                                     "row_id": rid, "kinds": kinds})
            if "OPASN" in kinds:
                await _raise_ticket(client, uid, Finding(
                    "qa_assignment_orphan", key, severity="warn",
                    message=(f"{key} was ASSIGNED. The option leg is finished, "
                             f"but assignment delivers stock -- check that the "
                             f"resulting share position has an owner.")), rep)
            return
        _edge = await _raise_ticket(client, uid, Finding(
            "qa_row_without_position", key, severity="warn",
            message=(f"Row {rid} says this book is {side} {_f(r.get('quantity')):g} "
                     f"{key}, the broker does not hold it, and there is no "
                     f"closing fill, expiry or assignment in the last "
                     f"{lookback_h():.0f} hours that explains where it went. "
                     f"Trezo will NOT close it on absence alone -- that is the "
                     f"loop that closed and re-adopted DOT seven times. Needs a "
                     f"human."), row_id=rid), rep)
        if _edge:
            rep["quarantined"] += 1
        return
    _clear_ticket(uid, key, "qa_row_without_position")

    # ---- I3 continued: side and qty must match the broker ------------
    p = pos_by_key[(key, side)][0]
    row_qty = abs(_f(r.get("quantity")))
    pos_qty = abs(_f(p.get("qty")))
    if row_qty > 0 and pos_qty > 0 and not _qty_matches(row_qty, pos_qty, at):
        await _raise_ticket(client, uid, Finding(
            "qa_quantity_drift", key, severity="warn",
            message=(f"Row {rid} says {row_qty:g} {key}; the broker holds "
                     f"{pos_qty:g}. The ledger and the venue disagree about "
                     f"size, which means the P/L on this row is wrong."),
            row_id=rid), rep)
        rep["would_fix"].append({"action": "A3_correct_quantity",
                                 "row_id": rid, "quantity": pos_qty})
        _log("qa_would_fix", key,
             reason=(f"WOULD set row {rid} quantity to the broker's {pos_qty:g} "
                     f"(from {row_qty:g}). AUTOFIX is off, so nothing was."),
             extra={"user_id": uid, "row_id": rid})
    else:
        _clear_ticket(uid, key, "qa_quantity_drift")

    # ---- I4: ROW => RECEIPT ------------------------------------------
    entry_at = _parse_ts(r.get("entry_at"))
    in_window = entry_at is not None and entry_at >= window_start
    if not str(r.get("broker_order_id") or "") and in_window:
        cands = [f for f in fills_by_sym.get(key, [])
                 if _qty_matches(abs(_f(f.get("qty"))), row_qty, at)
                 and _price_matches(_f(f.get("price")),
                                    abs(_f(r.get("entry_price"))), at)[0]]
        ids = sorted({str(f.get("order_id") or "") for f in cands if f.get("order_id")})
        if len(ids) == 1:
            rep["would_fix"].append({"action": "A4_backfill_order_id",
                                     "row_id": rid, "order_id": ids[0]})
            _log("qa_would_fix", key,
                 reason=(f"WOULD stamp row {rid} with broker_order_id {ids[0]} "
                         f"-- exactly one fill matches its symbol, side, qty "
                         f"and price. AUTOFIX is off, so nothing was."),
                 extra={"user_id": uid, "row_id": rid, "order_id": ids[0]})
        elif len(ids) > 1:
            _edge = await _raise_ticket(client, uid, Finding(
                "qa_ambiguous_receipt", key, severity="warn",
                message=(f"Row {rid} has no order id and {len(ids)} fills match "
                         f"it equally well ({', '.join(ids[:4])}). Trezo will "
                         f"not flip a coin; a human must say which."),
                row_id=rid, order_ids=tuple(ids)), rep)
            if _edge:
                rep["quarantined"] += 1
        else:
            await _raise_ticket(client, uid, Finding(
                "qa_unreceipted_row", key, severity="warn",
                message=(f"Row {rid} was opened inside the last "
                         f"{lookback_h():.0f} hours but carries no broker order "
                         f"id and no fill in the window matches its size and "
                         f"price. Its entry price may not be what actually "
                         f"happened."), row_id=rid), rep)

    # entry_at drift: RECORDED, never corrected -- entry_at drives time
    # stops, so "fixing" it moves an exit.
    if entry_at is not None:
        best = None
        for f in fills_by_sym.get(key, []):
            ts = _parse_ts(f.get("transaction_time") or f.get("date"))
            if ts and (best is None or ts < best):
                best = ts
        if best is not None:
            drift = abs((entry_at - best).total_seconds()) / 60.0
            if drift > entry_drift_min():
                await _raise_ticket(client, uid, Finding(
                    "qa_entry_time_drift", key, severity="info",
                    message=(f"Row {rid} records an entry time {drift:.0f} "
                             f"minutes away from the broker's fill time "
                             f"({best.isoformat()}). NOT corrected: entry_at "
                             f"drives time stops, so changing it would move an "
                             f"exit. Recorded for a human."),
                    row_id=rid, extra={"qa_true_entry_at": best.isoformat()}), rep)

    # ---- I5: ROW => ENFORCEABLE PROTECTION ---------------------------
    await _check_enforceable_stop(client, uid, key, r, rid, at, open_orders, rep)

    # ---- I5b: is the geometry it HAS even sane? (read-only) ----------
    await _check_geometry_sanity(client, uid, key, r, rid, at, side, rep)


# Instrument classes for which the VENUE HOLDS NO STOP BY CONSTRUCTION, so
# "the broker has no resting stop order" is a fact about the venue and not
# a finding about the row (ADVISORY C, review 2026-09-02):
#
#   crypto -- Alpaca has no native bracket or stop for crypto at all. That
#     is why position_monitor enforces crypto stops client-side; a stop on
#     a crypto row is SUPPOSED to exist only inside Trezo.
#   option -- Alpaca does not accept stop or stop-limit orders on options.
#     A short put's stop_price is a buy-back level Trezo watches, and there
#     is no order that could ever be resting for it. Live, this fired on
#     nine short option rows and could never have cleared on any of them:
#     a warning that cannot be acted on is a warning that trains Mike to
#     stop reading the channel.
_NO_VENUE_STOP_CLASSES = frozenset({"crypto", "option"})


async def _check_enforceable_stop(client, uid: str, key: str, r: dict,
                                  rid: str, at: str,
                                  open_orders: Optional[list],
                                  rep: dict) -> None:
    """I5. Does a stop the ledger shows actually exist at the broker?

    Two corrections after the first live read (ADVISORY C, 2026-09-02):

    (1) the evidence is the LIVE open-orders read, not the sweep's 72-hour
        historical window. A bracket's stop leg is placed once, when the
        entry goes on; five stock rows 102-120 hours old had their legs
        resting at the venue and outside the window, and were reported as
        having "no resting stop at the broker". That is a false alarm
        about protection -- the most expensive kind to be wrong about in
        either direction.
    (2) instrument classes the venue holds no stop for are not asked at
        all -- see _NO_VENUE_STOP_CLASSES.

    On an unreadable open-orders set the question is SKIPPED, not
    answered: absence of evidence is not evidence of absence, which is the
    whole thesis of this module.
    """
    stop = _f(r.get("stop_price"))
    if stop <= 0 or at in _NO_VENUE_STOP_CLASSES:
        return
    if open_orders is None:
        _log("qa_read_deferred", key,
             reason=("could not read the venue's live open orders; not "
                     "judging whether row's stop is enforceable this pass"),
             extra={"user_id": uid, "row_id": rid})
        return
    resting = [o for o in open_orders
               if isinstance(o, dict)
               and ledger_symbol(o.get("symbol"), asset_class_of(o)) == key
               and str(o.get("type") or o.get("order_type") or "").lower()
               in _protective_types()
               and str(o.get("status") or "").lower() in _non_terminal()]
    if resting:
        _clear_ticket(uid, key, "qa_unenforceable_stop")
        return
    _log("qa_unenforceable_stop", key,
         reason=(f"row {rid} carries a stop at {stop:g} but the broker "
                 f"has no resting protective order for it -- the stop "
                 f"only exists inside Trezo"),
         extra={"user_id": uid, "row_id": rid})
    await _raise_ticket(client, uid, Finding(
        "qa_unenforceable_stop", key, severity="warn",
        message=(f"Row {rid} shows a stop at {stop:g}, but there is no "
                 f"resting stop order at the broker. If Trezo is down "
                 f"when price reaches it, nothing sells. QA does not "
                 f"place orders -- this is a flag, not a repair."),
        row_id=rid), rep)


def _non_terminal() -> frozenset:
    try:
        from app.brokers.alpaca import NON_TERMINAL_ORDER_STATUSES
        return NON_TERMINAL_ORDER_STATUSES
    except Exception:  # noqa: BLE001
        return frozenset({"new", "pending_new", "accepted", "held",
                          "accepted_for_bidding", "partially_filled",
                          "pending_cancel", "pending_replace", "stopped",
                          "suspended", "calculated"})


async def _check_geometry_sanity(client, uid: str, key: str, r: dict, rid: str,
                                 at: str, side: str, rep: dict) -> None:
    """I5b. Refusing to WRITE geometry is right. Refusing to CHECK it is
    what leaves the acceptance case armed.

    For a SHORT option, entry_price is the credit received per share and
    stop_price is what Trezo would pay to buy it back. If the buy-back
    costs several times the credit, the trade's downside is nothing like
    its upside -- NOBL's live geometry is 0.315 against a 0.05 credit,
    6.3x, while the platform's other eight short option rows sit between
    1.2x and 2.1x. Two numbers already on the row; nothing is written.
    """
    if at != "option" or side != "short":
        return
    credit = abs(_f(r.get("entry_price")))
    stop = _f(r.get("stop_price"))
    if credit <= 0 or stop <= 0:
        return
    mult = stop / credit
    if mult <= stop_credit_mult():
        _clear_ticket(uid, key, "qa_stop_implies_outsized_loss")
        return
    loss = (stop - credit) * 100.0 * abs(_f(r.get("quantity"), 1.0))
    await _raise_ticket(client, uid, Finding(
        "qa_stop_implies_outsized_loss", key, severity="urgent",
        message=(f"{key} was sold for {credit:g} per share and its stop is set "
                 f"at {stop:g} -- {mult:.1f}x the credit received. If that stop "
                 f"fires, this trade loses about ${loss:,.0f} to have made "
                 f"${credit * 100.0 * abs(_f(r.get('quantity'), 1.0)):,.0f}. "
                 f"Nothing has been changed; this needs to be priced by hand."),
        row_id=rid), rep)


async def _check_singularity(client, uid: str, rows: list, opt_rows: list,
                             positions: list, fills_by_sym: dict,
                             rep: dict) -> None:
    """I6: paper_positions XOR options_positions. Read-only on both.

    Two managers for one contract is the churn that produced the wheel
    lane's nine laundered rows: an options_positions row marked
    closed_manual for a contract the broker is still holding.
    """
    held_occ = {ledger_symbol(p.get("symbol"), "option")
                for p in positions if asset_class_of(p) == "option"}
    paper_occ = {ledger_symbol(r.get("ticker"), "option")
                 for r in rows if str(r.get("status") or "") == "open"
                 and str(r.get("asset_type") or "") == "option"}
    for orow in opt_rows:
        occ = occ_for_row(orow)
        if not occ:
            continue
        status = str(orow.get("status") or "")
        if status == "open" and occ in paper_occ:
            _edge = await _raise_ticket(client, uid, Finding(
                "qa_double_managed", occ, severity="urgent",
                message=(f"{occ} has an open row in BOTH paper_positions and "
                         f"options_positions. Two lanes are managing one "
                         f"contract; whichever exits first leaves the other "
                         f"holding a row for something that is gone."),
                row_id=str(orow.get("id") or "")), rep)
            if _edge:
                rep["quarantined"] += 1
            continue
        if status.startswith("closed") and occ in held_occ:
            note = str(orow.get("notes") or "")
            _edge = await _raise_ticket(client, uid, Finding(
                "qa_closed_but_held", occ, severity="urgent",
                message=(f"{occ} is marked {status} in options_positions, but "
                         f"the broker is still holding the contract. The row "
                         f"was closed without the broker agreeing. "
                         f"{'Its notes name ' + note[:80] if note else ''}"
                         f" Nothing was written -- reopening a closed row is "
                         f"where a re-adopt loop starts."),
                row_id=str(orow.get("id") or "")), rep)
            if _edge:
                rep["quarantined"] += 1


async def _report_legacy_backlog(client, uid: str, rows: list,
                                 window_start: datetime, rep: dict) -> None:
    """The rows that predate this component.

    A row opened before QA existed cannot have a receipt inside any lookback
    the activities endpoint can serve. Raising one ticket per sweep for each
    of them would fill the alert channel with permanent false positives
    inside a week, and Mike's rational response would be to stop reading it.
    So: ONE summary line, re-raised only when the COUNT changes.
    """
    legacy = []
    for r in rows:
        if str(r.get("status") or "") != "open":
            continue
        if str(r.get("broker_order_id") or ""):
            continue
        ts = _parse_ts(r.get("entry_at"))
        if ts is not None and ts >= window_start:
            continue                     # judged by I4, not here
        legacy.append(str(r.get("ticker") or "?"))
    if not legacy:
        _clear_ticket(uid, "-", "qa_legacy_backlog")
        return
    code = f"qa_legacy_backlog:{len(legacy)}"
    key = (uid, "-", code)
    entry = {"finding": "qa_legacy_backlog", "count": len(legacy),
             "tickers": sorted(legacy)[:20]}
    if key in _OPEN_TICKETS:
        # Same count as last sweep: nothing changed, so nothing is said.
        # This used to append to findings ABOVE the check, which is one
        # persisted bus message per book per sweep for a MIGRATION ITEM
        # (ADVISORY B). It goes to `standing` instead.
        rep.setdefault("standing", []).append(entry)
        return
    rep["findings"].append(entry)
    for stale in [k for k in _OPEN_TICKETS
                  if k[0] == uid and k[2].startswith("qa_legacy_backlog")]:
        _OPEN_TICKETS.discard(stale)
    _OPEN_TICKETS.add(key)
    _log("qa_flag", "-",
         reason=(f"{len(legacy)} open row(s) predate the QA inspector and have "
                 f"no broker order id: {', '.join(sorted(legacy)[:12])}. They "
                 f"cannot be receipted from any window the broker will serve. "
                 f"Migration item, not a per-sweep finding."),
         extra={"user_id": uid, "count": len(legacy)})


# ---------------------------------------------------------------------------


async def sweep_all_books(*, dry_run: Optional[bool] = None) -> dict:
    """Every book, one after another. Kept as an entry point so promoting
    this to a 31st agent later is mechanical -- today it rides book_health's
    tick, and ops_watchdog.EXPECTED_AGENTS stays at 30."""
    out = {"books": [], "skipped": 0}
    try:
        from app.brokers.accounts import load_accounts
        from app.runtime.persistence import _client
        client = _client()
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    for acct in load_accounts():
        rep = await qa_sweep_for_book(client, acct.account_key, dry_run=dry_run)
        out["books"].append(rep)
        if rep.get("skipped_reason"):
            out["skipped"] += 1
    return out
