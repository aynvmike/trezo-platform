# Kill-Switch Freeze — Bug Report & Auto-Repair Spec

**For:** the Nova working in `trezo-platform`
**From:** Nova (sentinel run, 2026-08-17 ~16:55 UTC / 12:55 ET)
**Repo HEAD at diagnosis:** `536e626`
**Primary file:** `agents/app/paper/killswitch.py`
**Severity:** HIGH — all three paper books took **zero new entries today**.

---

## 1. What Mike is seeing

Two of three books show `trading_halted = true` with
`halt_reason = "5 losing trades in a row (limit 5)"`, while the same rows
report `consecutive_losses = 0` and a today-realized P&L of only **-$3.41**.
The reason and the counter contradict each other, which is the tell.

Live `paper_accounts` at time of run:

| Book | user_id | halted | halt_reason | consecutive_losses | today P&L | halted_at |
|---|---|---|---|---|---|---|
| primary | `cf1b0460` | false | — | — | — | — |
| 25k | `6ce61054` | **true** | 5 losing trades in a row (limit 5) | **0** | -$3.41 | `2026-08-17T00:00:02.681944Z` |
| 75k | `49acafdd` | **true** | 5 losing trades in a row (limit 5) | **0** | -$3.41 | `2026-08-17T00:00:03.802258Z` |

Both halted **within 3 seconds of midnight UTC** — the daily-reset boundary.
That timestamp is the whole story: this was not a trading event, it was a
race with the roll.

### Measured impact

- **`paper_positions` entries today: 0** (all three books). For scale: 8/14 = 48 entries, 8/15 = 1, 8/16 = 1.
- **168 of the last 245 `risk_manager` vetoes** (3-hour window) carry the reason `Kill-switch [day] - 5 losing trades in a row (limit 5)` — the single largest veto bucket by 7x.
- The books still went green today (+0.52% / +1.60% / +0.91%) purely on mark-to-market of positions opened **before** the freeze, plus three exits (LINK +$370.10 / +$101.88 / +$108.86). So the freeze is invisible in the equity line — it only shows up as missing entries.
- Alpaca is clean on all three: `status=ACTIVE`, no `trading_blocked` / `account_blocked`. **This is entirely our own gate, not the broker.**

---

## 2. Root cause — a 30-second cache that outlives the daily reset

Four defects chain together. Fixing only one leaves the freeze reachable.

### Defect 1 — `_ROWSUM_CACHE` has no period key and survives the roll  *(the trigger)*

`killswitch.py:29`

```python
_ROWSUM_CACHE: dict[str, tuple] = {}   # user -> (ts, wk, dy, streak) 30s TTL
```

Keyed by `user_id` only. The tuple holds a **loss streak scanned over
"this week", where "this week" is computed at write time** (`killswitch.py:289`):

```python
_monday_s = (date.today() - timedelta(days=date.today().weekday())).isoformat()
```

Sequence that fired at midnight:

1. **23:59:5x Sun 8/16** — a signal arrives. `_monday_s` is still `2026-08-10`, so the row scan covers 8/10 onward. Walking newest-first, the trailing closes were:

   | exit_at | ticker | realized |
   |---|---|---|
   | 8/16 00:02 | XRP | -2.47 |
   | 8/15 01:21 | SOL | -27.10 |
   | 8/14 19:04 | CIFR | -1.54 |
   | 8/14 18:31 | SNXX | -0.05 |
   | 8/14 17:58 | XLRE | -0.60 |
   | 8/14 17:56 | AMD | **+2.90**  ← streak stops here |

   **`_streak = 5`.** Cached at `killswitch.py:316` with a 30s TTL.

2. **00:00:00 Mon 8/17** — `period_updates()` rolls the day *and* the week: `consecutive_losses := 0`, `last_reset_date := 2026-08-17`, day-halt cleared. Written to the DB. Correct behaviour.

3. **00:00:02 Mon 8/17** — next signal, ~2s later. The cache entry is still inside its 30s TTL, so `check_all` takes the **cache branch** (`killswitch.py:280-286`) instead of re-querying. `_monday_s` would now be `2026-08-17` and a fresh scan would return **0 rows** — but the fresh scan never runs.

4. The freshly-zeroed counter is overwritten with the pre-midnight streak of 5 → `evaluate()` trips → halt persisted.

Confirmation: **zero positions closed between 8/16 20:00Z and 8/17 01:00Z.** No trade caused this halt. The streak was resurrected from a cache written before the reset.

`_ROWSUM_CACHE` is also read externally at `agents/app/paper/daily_goal.py:86` and `:132`, so the same stale-period tuple leaks into goal reporting.

### Defect 2 — `max()` makes the reset unable to win  *(the amplifier)*

`killswitch.py:285` (cache branch) and `killswitch.py:314` (fresh branch):

```python
"consecutive_losses": max(int(acct.get("consecutive_losses") or 0), _streak)
```

The `max()` was added so drifted counters could only ratchet **up** — sensible
when the DB counter is suspect. But it also means a *deliberate reset to 0 can
never take effect* while any scan or cache still reports a streak. The roll
writes 0; `max()` immediately discards it. Reset and row-truth are fighting,
and row-truth always wins.

### Defect 3 — no self-heal: sticky flag + a clear path that only runs on a date change  *(why it lasts 24h)*

`killswitch.py:182`, first statement of `evaluate()`:

```python
if account.get("trading_halted"):
    return KillSwitch(True, account.get("halt_scope"),
                      account.get("halt_reason") or "Trading halted")
```

The flag is trusted and the underlying condition is **never re-derived**. Today
those books have closed LINK +$370.10 / +$101.88 and BAC +$0.42; the real
streak is 0 by any measure. They stay halted anyway.

And the only day-halt clear (`killswitch.py:157-166`) is gated on the date having
changed:

```python
if str(account.get("last_reset_date") or "") != today.isoformat():
    ...
    if account.get("halt_scope") == "day":
        upd["trading_halted"] = False
```

Because the halt landed **2 seconds after** `last_reset_date` was already set to
today, that branch is dead for the rest of the day. **A day-scope halt set at any
point after its own reset is stuck for a full 24 hours with no path out.** There
is no time-based expiry, so nothing heals it.

Note the codebase already rejects this pattern elsewhere — the broker-reject
halt was converted to a rolling window on 2026-07-27 (`killswitch.py:36-45`),
with the comment: *"A reject storm should pause trading briefly, not forever...
Same philosophy as everywhere else: conditions, never permanent bans."* The
streak halt never got that treatment.

### Defect 4 — one book's halt freezes all three  *(the blast radius)*

`check_all` loops every account and collapses the result into a single
`active` KillSwitch (`killswitch.py:229-336`, docstring says *"single-user
assumption"*). `risk_manager.py:861-865` then vetoes unconditionally:

```python
ks = await check_killswitches(_supabase())
if ks.halted:
    return [self._veto(ticker, tcs, f"Kill-switch [{ks.scope}] - {ks.reason}")]
```

No `user_id` scoping. The primary book is **not** halted in its own row, yet it
took 0 entries today because books 2 and 3 are. This is the same
per-account-isolation gap noted on 8/9: state is already isolated per
`user_id`, but this gate reads globally. It also explains why the veto rows
land with `user_id = None`.

---

## 3. Fixes

Ordered by value. 1-3 stop the bleeding; 4 is the auto-repair Mike asked for; 5 contains the blast radius.

### Fix 1 — key the cache by period, and drop it on every roll

Make the cache key carry the week, so a pre-midnight tuple can never be read
after the roll:

```python
_ck = f"{acct.get('user_id')}:{_monday_s}"
```

`_monday_s` must be computed **before** the cache lookup for this to work
(currently it is computed at `:289`, after the lookup at `:280`). Additionally,
when `period_updates()` returns a non-empty `upd`, explicitly evict that user's
entries — belt and braces, and it also fixes the `daily_goal.py` readers.

### Fix 2 — let a reset beat the row scan

Suppress the `max()` ratchet on the tick that just rolled. Simplest correct
form: when `upd` contains `consecutive_losses = 0`, take the scanned streak
**as-is** rather than `max()`-ing it against the pre-reset value — or skip the
row-truth override entirely for that one tick. The ratchet should protect
against *drift*, not against an *intentional* reset.

### Fix 3 — re-derive before trusting the flag

In `evaluate()`, don't return on `trading_halted` alone. Re-check the condition
that set it: if `halt_scope == "day"` and the reason was a loss streak, and the
current streak is now below `consec_limit`, the halt is stale — return
not-halted and let `check_all` write the release (`trading_halted = false`,
`halt_reason = None`, `halt_scope = None`, and stamp e.g. `halt_cleared_at`).
Same logic for the drawdown halts: if today's realized P&L is no longer past
the limit, release.

### Fix 4 — the auto-repair: a time-boxed halt with an expiry  *(what Mike asked for)*

Give every halt a maximum duration and let it heal itself, exactly like the
broker-reject window already does:

- New env knobs, defaulting conservatively:
  - `TREZO_HALT_STREAK_MINUTES` (default **60**) — a losing-streak halt is a cool-off, not a day sentence.
  - `TREZO_HALT_DAY_MINUTES` (default **240**) — drawdown halts get a longer pause but still expire before the roll.
  - Weekly-scope halts keep expiring on the Monday roll (that one is a real risk limit and should stay strict).
- On each `check_all`, if `now - halted_at > expiry_for(halt_scope, halt_reason)`, release the halt and log an `ops_health_alerts` row of kind `halt_auto_released` with the original reason, so a self-repair is visible rather than silent.
- On release, also reset the counter that tripped it (`consecutive_losses = 0`) and evict `_ROWSUM_CACHE` for that user, so it cannot immediately re-trip on the same stale streak.
- Re-arming must be cheap: after a release, a genuinely new streak of `consec_limit` fresh losses should be able to halt again. That is what makes it a cool-off rather than a bypass.

Design note worth stating plainly for Mike: this does **not** weaken the safety
limit. A real streak of 5 losses still stops trading immediately. What changes
is that the stop **ends on its own after an hour** instead of silently eating a
whole trading day, and it can no longer be triggered by a counter that was
already reset.

### Fix 5 — scope the veto to the account

`check_all` should return per-`user_id` halt state (dict or a small dataclass
keyed by user), and `risk_manager` should veto only for the accounts actually
halted. One book's cool-off must not idle the other two. If a full refactor is
too large for this pass, the minimum viable change is to have `risk_manager`
skip the global veto for any account whose own row reads
`trading_halted = false`.

---

## 4. Immediate unblock (safe to run now, before any code lands)

Clearing the two stale flags by hand restores trading today. The condition is
genuinely not met — both books' trailing streak is 0 and today's realized P&L
is -$3.41 against limits of roughly -$746 (25k) and -$2,225 (75k).

`paper_accounts` update on `6ce61054` and `49acafdd`:

```
trading_halted = false
halt_reason    = null
halt_scope     = null
consecutive_losses = 0
```

**Caveat:** without Fix 1, an in-process `_ROWSUM_CACHE` entry could re-trip the
halt within 30 seconds of the clear. If it comes straight back, restart the
`TrezoAgents` service to drop the module-level cache, then clear again.

---

## 5. Regression test worth adding

The bug is a two-tick ordering problem, so a single-tick test will not catch it:

1. Seed an account with 5 closing losses dated in the *previous* week.
2. Call `check_all` at `23:59:55` (freezing time) to populate `_ROWSUM_CACHE` with `streak = 5`.
3. Advance to `00:00:02` the next day and call `check_all` again.
4. **Assert `trading_halted` is false** and `consecutive_losses == 0`.

Second test, for the expiry: set a streak halt with `halted_at` 61 minutes in
the past, call `check_all`, assert the halt released and an
`ops_health_alerts` row was written.

---

## 6. Secondary finding (lower priority, same run)

Three agents raised stuck-agent alerts today and the service appears to have
restarted at least twice (14:06Z and 14:46Z "10 min since boot" alerts):

- `options_scanner` — **urgent**, "registered but has NEVER ticked (60 min since boot, interval 1800s)". Same alert on 8/14. Recurring, so likely a real exception inside its tick.
- `orb_scanner` — urgent at 14:46Z, then warn at 15:46Z (not ticked in 36 min).
- `pattern_detection` — urgent at 14:06Z, but **is ticking normally now** (last message 0.8 min before this run).

Core loop is otherwise healthy: `risk_manager`, `stms_scanner`, `forex_scanner`,
`position_monitor`, `crypto_scanner`, `pattern_detection` all ticked within ~1
minute of the run. Worth a look at `options_scanner` and `orb_scanner`
`last_error` via `GET /agents`, but neither is what froze the books.
