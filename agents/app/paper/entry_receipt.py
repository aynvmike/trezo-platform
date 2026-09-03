"""When was this position actually BOUGHT? -- the receipt, not the clock.

THE DEFECT THIS CLOSES (2026-09-03, book acct2 / 6ce61054)
Ledger row 37d36b9e-123b-4692-baf2-ac71f24a11bc, XDTE, 19.325521503 shares
at 38.808267, strategy "reconciled", broker_order_id None. Its entry_at,
created_at and updated_at are the SAME microsecond -- 14:20:53.914599Z --
because `engine.record_external_position` inserts no entry_at at all and
the column defaults to now(). The broker's own paperwork says otherwise:
order 6b0674af-bc72-4e8b-ae9c-e2bd2a2a6faa was submitted at 10:51:27Z,
nearly three hours before the open, and filled in FOUR pieces --
13:30:49.647776 (13 @ 38.80), 13:33:24.270228 (3 @ 38.82), 13:33:52.675383
(2 @ 38.83), 13:33:52.676936 (1.325521503 @ 38.83). The position was
entered at 13:30:49.647776 and sat unowned for 47 minutes; the reconciler
met it at 14:20 and stamped it with the moment of the MEETING.

The PRICE was inherited correctly (38.808267 matches filled_avg_price to
the last digit). Only the TIME was invented. entry_at drives every
time-based exit and the re-score staleness rules, so an adoption silently
resets a position's age to zero -- which is the DOT clock problem in the
stock lane: 2026-08-26..29 a DOT position was phantom-closed and
re-adopted seven times, and every re-adoption restarted its clock, so a
nine-day-old position never once reported itself as stale.

WHAT THIS MODULE IS
The one place that answers "what time does the BROKER say this position
was entered?", for the two paths that create a row for a position the
broker already holds (app/paper/adoption.py, app/paper/stocks_reconcile.py).

HOUSE RULE 6 GOVERNS, AND IT IS THE WHOLE DESIGN.
A wrong entry_at is worse than a late one, because a late one only makes
a position look young and a wrong one silently MOVES AN EXIT. So this
module answers with a timestamp only when the broker's own records settle
it beyond doubt, and otherwise answers "I do not know" and says why. It
never averages, never picks between candidates, never falls back to a
guess. Every refusal is quoted into the row's source_payload and into an
activity row, and the QA inspector's qa_entry_time_drift finding goes on
standing for it.

IT AGREES WITH THE QA INSPECTOR BY CONSTRUCTION, NOT BY COINCIDENCE.
app/paper/trade_qa.py already had to answer this question for the rows it
books (_entry_fill_at) and already reports the drift on rows it does not
(qa_entry_time_drift). Two implementations of "which fill is the entry"
would drift apart and the inspector would end up flagging rows this module
had just written correctly. So this module does not have its own
implementation: it CALLS trade_qa._arith_gate and trade_qa._entry_fill_at
through the module object, reads the same lookback knob, and normalises
symbols with the same ledger_symbol. tests/test_entry_receipt.py asserts
the identity of those objects, so deleting or renaming one is a gate
failure rather than a silent divergence.

THE CONVENTION: the EARLIEST opening fill of the ONE order that built the
position the broker holds right now. Earliest because a position opened by
four partials was entered at the first one -- booking the last would put
entry_at into the future of the trade. "the ONE order" because two orders
behind one position is an ambiguity a human resolves, not a coin flip.
"the position the broker holds right now" is what makes RE-ADOPTION safe:
the arithmetic gate reconciles the fills against the CURRENT qty and
average price, so a re-adopted position is dated from the fills that built
what is actually held -- and if the lookback window also contains the
round trip that closed the previous cycle, the gate refuses outright
rather than dating the new position from the old one.

THE BOUND, which matters because a backdated row can be born OLD.
The evidence is one activity window -- `after = now - trade_qa.lookback_h()`
(72 hours by default) -- so a timestamp this module returns is at or after
that window's start. That is asserted explicitly at the end of resolve()
rather than argued: anything outside [window_start, now] is refused. So
the maximum a freshly created row can be backdated is the lookback, three
days on the shipped default. What that does and does not reach is set out
in the wave notes; the one rule it reaches immediately is the intraday
90-minute time stop, which position_monitor now shields (see
_backdate_shields_time_exit there).

HOUSE RULE 2: one book at a time, bound with bind_for_user before the
read. HOUSE RULE 3: get_fill_activities_strict returns None for a failed
OR unexhausted read, and None here means "could not check" -- never "no
evidence", which would silently become now() with no explanation.
Bounded: ONE activities read per book per pass (BookReceipts.load), plus
at most one /v2/orders/{id} dereference per position and only when the
fills carry no timestamp of their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.paper import trade_qa as _qa

# The maximum number of order dereferences one book's pass may make. The
# fills almost always carry transaction_time, so this is a ceiling on a
# path that should stay empty, not a budget anyone expects to spend.
_MAX_ORDER_READS = 8


# ---------------------------------------------------------------------------
# Seams. Every broker call goes through a module attribute so a test patches
# the ATTRIBUTE and restores it -- no fakes in sys.modules.
# ---------------------------------------------------------------------------


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


def _log(event: str, ticker: str, *, reason: str = "",
         strategy: Optional[str] = None, extra: Optional[dict] = None) -> None:
    """LATE import (house rule 4) so the gate's quiet_activity_log stub
    reaches it. Logging never breaks a write."""
    try:
        from app.agents.activity_log import record
        record(event, ticker, strategy=strategy, reason=reason,
               extra=extra or {})
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# The answer.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntryEvidence:
    """What the broker's paperwork settles about this position's entry.

    `settled` is the only thing a caller should branch on. An unsettled
    answer is NOT an error -- it is the correct answer whenever the
    records do not close the question, and the caller's job then is to
    keep today's behaviour (the column defaults to now()) and carry `why`
    into the row so the next reader knows the clock is the adoption clock
    and not the trade's.
    """

    entry_at: Optional[str] = None          # the venue's own spelling
    broker_order_id: Optional[str] = None
    source: str = ""                        # fills | order_filled_at
    why: str = ""                           # why NOT settled
    read_failed: bool = False
    backdated_min: float = 0.0              # how far before now() it sits
    fills_used: int = 0

    @property
    def settled(self) -> bool:
        return bool(self.entry_at)

    def payload(self) -> dict:
        """The block that rides into paper_positions.source_payload.

        Written on BOTH branches on purpose. A row whose clock could not
        be established says so in its own payload -- that is the
        difference between "adopted with the broker's entry time" and
        "adopted with the adoption clock because nothing settled it", and
        without it the two are indistinguishable a week later.
        """
        if self.settled:
            return {
                "entry_at_source": self.source,
                "entry_at_receipt_order_id": self.broker_order_id,
                "entry_at_backdated_min": round(float(self.backdated_min), 3),
                "entry_at_fills_used": int(self.fills_used),
            }
        return {
            "entry_at_source": "adoption_clock",
            "entry_at_unresolved": self.why or "no receipt",
            "entry_at_read_failed": bool(self.read_failed),
        }


def _unsettled(why: str, *, read_failed: bool = False) -> EntryEvidence:
    return EntryEvidence(why=why, read_failed=read_failed)


# ---------------------------------------------------------------------------
# One book's evidence, read once per pass.
# ---------------------------------------------------------------------------


def _has_time_of_day(raw: str) -> bool:
    """Does this timestamp carry a clock, or only a calendar day?

    A bare 'YYYY-MM-DD' becomes midnight UTC once stored, which is a time
    the venue never reported. Require a separator and a colon before the
    value may be called a fill time (review 2026-09-03).
    """
    t = str(raw or "").strip()
    return ("T" in t or " " in t) and ":" in t


@dataclass
class BookReceipts:
    """The fill activities for ONE book, plus the window they came from.

    Built once per reconcile/adopt pass (`await BookReceipts.load(uid)`)
    and then asked about each position, so N adoptions in one book cost
    ONE broker read and not N.
    """

    user_id: str
    fills_by_sym: dict = field(default_factory=dict)
    window_start: Optional[datetime] = None
    after_iso: str = ""
    read_failed: bool = False
    error: str = ""
    _order_reads: int = 0

    @classmethod
    async def load(cls, user_id: str) -> "BookReceipts":
        """Bind this book and read its fill window. Never raises."""
        uid = str(user_id or "")
        after = _qa._after_iso(_qa.lookback_h())
        start = _qa._parse_ts(after)
        try:
            from app.brokers.accounts import (
                bind_for_user, should_skip_unresolved,
            )
        except Exception as e:  # noqa: BLE001
            return cls(uid, {}, start, after, True,
                       f"account registry unavailable ({type(e).__name__})")
        try:
            if should_skip_unresolved(uid):
                return cls(uid, {}, start, after, True,
                           "this book could not be resolved to a broker "
                           "account, and reading another book's fills is how "
                           "a stranger's timestamp lands in this ledger")
            with bind_for_user(uid) as book:
                if book is None and should_skip_unresolved(uid):
                    return cls(uid, {}, start, after, True,
                               "book did not bind")
                fills = await _read_fills(after)
        except Exception as e:  # noqa: BLE001
            return cls(uid, {}, start, after, True,
                       f"fill read raised {type(e).__name__}: {str(e)[:120]}")
        if fills is None:
            # HOUSE RULE 3. None is "could not check" -- an unexhausted
            # window included. It is never an empty window.
            return cls(uid, {}, start, after, True,
                       (_last_read_error() or "fill read failed")[:160])
        by_sym: dict = {}
        for a in fills:
            if not isinstance(a, dict):
                continue
            at = _qa.asset_class_of(a)
            key = _qa.ledger_symbol(a.get("symbol"), at)
            if key:
                by_sym.setdefault(key, []).append(a)
        return cls(uid, by_sym, start, after, False, "")

    # -- the question ----------------------------------------------------

    async def resolve(self, position: dict, *,
                      asset_type: Optional[str] = None,
                      now: Optional[datetime] = None) -> EntryEvidence:
        """The broker's entry time for the position it is holding, or a
        stated refusal. Never raises, never guesses."""
        try:
            return await self._resolve(position, asset_type, now)
        except Exception as e:  # noqa: BLE001
            # A resolver that throws must not take an adoption down with
            # it: an unsettled answer keeps today's behaviour exactly.
            return _unsettled(
                f"entry-time resolution raised {type(e).__name__}: "
                f"{str(e)[:120]}")

    async def _resolve(self, position: dict, asset_type: Optional[str],
                       now: Optional[datetime]) -> EntryEvidence:
        if self.read_failed:
            return _unsettled(
                f"the broker's fill records could not be read ({self.error}), "
                f"so nothing settles this position's entry time",
                read_failed=True)
        at = str(asset_type or _qa.asset_class_of(position) or "stock").lower()
        key = _qa.ledger_symbol(position.get("symbol"), at)
        if not key:
            return _unsettled("the broker position carries no symbol")
        window = self.fills_by_sym.get(key, [])
        if not window:
            return _unsettled(
                f"no fill in the last {_qa.lookback_h():.0f} hours explains "
                f"this position -- it was built by orders outside the "
                f"lookback, so its entry time is not in evidence")

        # THE ARITHMETIC GATE, trade_qa's own. Two independent broker
        # records (the position and the fills) must agree on quantity and
        # average price before any of those fills may date anything, and a
        # round trip inside the window is an automatic refusal -- which is
        # exactly what makes a RE-ADOPTION honest instead of dated from
        # the cycle before it.
        ok, why, qty, px, opening = _qa._arith_gate(position, window, at)
        if not ok:
            return _unsettled(
                f"the broker's own records do not agree with each other, so "
                f"no fill may date this position: {why}")

        oids = sorted({str(f.get("order_id") or "") for f in opening
                       if f.get("order_id")})
        if not oids:
            return _unsettled(
                "the fills that built this position carry no order id, so "
                "there is no receipt to date it from")
        if len(oids) > 1:
            return _unsettled(
                f"{len(oids)} different orders produced the fills behind this "
                f"position ({', '.join(oids[:4])}); Trezo will not pick one, "
                f"a human has to say which order opened it")
        oid = oids[0]

        # THE EARLIEST OPENING FILL of that order -- trade_qa._entry_fill_at,
        # not a second copy of the same idea. Returns "" when no fill
        # carries a usable timestamp.
        raw = _qa._entry_fill_at(opening, oid)
        source = "fills"
        # REVIEW 2026-09-03, BLOCKING (house rule 6). _entry_fill_at falls
        # back to an activity's `date` when it carries no transaction_time.
        # A date has no time of day, so Postgres stores it as MIDNIGHT --
        # up to 24 hours EARLIER than the real fill, on the column that
        # moves exits, and inside the window so the bound below cannot
        # catch it. That convention is fine for trade_qa's coarser orphan
        # reporting; it is not evidence good enough to stamp an entry.
        if raw and not _has_time_of_day(raw):
            return _unsettled(
                f"order {oid} reports only a DATE ({raw}) with no time of "
                f"day; midnight is not a fill time, so the entry stays "
                f"unresolved rather than up to 24h early")
        if not raw:
            if self._order_reads >= _MAX_ORDER_READS:
                return _unsettled(
                    "no fill carries a timestamp and this pass has already "
                    "spent its order-dereference budget; nothing invented")
            self._order_reads += 1
            order, reason = await _read_order(oid)
            if order is None and reason is not None:
                return _unsettled(
                    f"order {oid} could not be read ({reason}), so its fill "
                    f"time is unknown", read_failed=True)
            if order is None:
                return _unsettled(
                    f"the fills name order {oid} but the broker says there is "
                    f"no such order")
            raw = str(order.get("filled_at") or "").strip()
            source = "order_filled_at"
        if not raw:
            return _unsettled(
                f"order {oid} reconciles on quantity and price, but neither "
                f"its fills nor the order itself carries a fill TIME; "
                f"entry_at drives time stops, so it is not invented here")

        dt = _qa._parse_ts(raw)
        if dt is None:
            return _unsettled(
                f"order {oid} reports a fill time Trezo cannot read "
                f"({raw[:40]!r}); nothing written")

        # THE BOUND, asserted rather than argued (see the module note). A
        # timestamp outside [window_start, now] did not come from the
        # evidence this pass actually read, and a row born older than the
        # window would break the guarantee the exit-side shield rests on.
        _now = now or datetime.now(timezone.utc)
        if self.window_start is None:
            # REVIEW 2026-09-03, BLOCKING. The module SAYS the bound is
            # asserted; with an unparseable window start it was merely
            # skipped, so the lower half of "asserted rather than argued"
            # silently did not exist. No bound, no stamp.
            return _unsettled(
                "the fill window's own start could not be parsed, so there "
                "is no bound to check this timestamp against")
        if dt < self.window_start:
            return _unsettled(
                f"order {oid} reports a fill at {dt.isoformat()}, before the "
                f"{_qa.lookback_h():.0f}-hour window this evidence came from; "
                f"refusing a timestamp the read cannot support")
        if dt > _now:
            return _unsettled(
                f"order {oid} reports a fill at {dt.isoformat()}, in the "
                f"future; refusing it")

        return EntryEvidence(
            entry_at=raw, broker_order_id=oid, source=source,
            backdated_min=max(0.0, (_now - dt).total_seconds() / 60.0),
            fills_used=len([f for f in opening
                            if str(f.get("order_id") or "") == oid]))


# ---------------------------------------------------------------------------
# What the two create paths call.
# ---------------------------------------------------------------------------


def announce(evidence: EntryEvidence, *, user_id: str, ticker: str,
             strategy: Optional[str] = None, asset_type: str = "") -> None:
    """One activity row per created row, on BOTH branches.

    Says either "this row's clock is the broker's" with the order id and
    how far back it sits, or "this row's clock is the adoption clock" with
    the reason -- so the refusals are countable in the feed instead of
    being invisible good behaviour.
    """
    if evidence.settled:
        _log("entry_at_from_receipt", ticker, strategy=strategy,
             reason=(f"entry time taken from the broker's receipt: order "
                     f"{evidence.broker_order_id} first filled at "
                     f"{evidence.entry_at} "
                     f"({evidence.backdated_min:.0f} min before this row was "
                     f"created, {evidence.fills_used} fill(s) on that order). "
                     f"The row is born with the position's real age, so time "
                     f"stops and staleness rules measure the trade and not "
                     f"the moment we noticed it"),
             extra={"user_id": str(user_id), "asset_type": asset_type,
                    "order_id": evidence.broker_order_id,
                    "entry_at": evidence.entry_at,
                    "backdated_min": round(evidence.backdated_min, 1)})
        return
    _log("entry_at_unresolved", ticker, strategy=strategy,
         reason=(f"entry time NOT taken from the broker: {evidence.why}. The "
                 f"row keeps the adoption clock (now()), which makes the "
                 f"position look younger than it is -- a wrong entry_at would "
                 f"move an exit, so it is left for the QA inspector to flag "
                 f"rather than guessed"),
         extra={"user_id": str(user_id), "asset_type": asset_type,
                "read_failed": bool(evidence.read_failed)})
