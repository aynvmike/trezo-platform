# Trezo — Library Plan
### Turning five books into changes in the engine

_Written 2026-08-05, after Mike bought five books specifically to raise the
agents' understanding. The plan is organised around Trezo's OPEN PROBLEMS, not
around the books, because reading cover-to-cover is the slow way to get value
and none of these were bought to be admired._

---

## What already happened (no action needed)

All five are **text PDFs**, so the agents index them automatically on the next
drop-box sweep — the raw text is searchable by the library the moment the
engine restarts. That is different from Sinclair and Chan, which are scans with
no text layer and can only ever reach the agents through a written note.

One thing had to be fixed for that to be true: the sweep had an **8MB cap with
a silent skip**. Vince (14.7MB), Tharp (10.7MB) and de Prado (8.9MB) were over
it and would have been dropped without a log line. The cap is now 40MB and
configurable, and an oversize file is reported. Commit `8cd6de2`.

## Why a note still matters when the agents can read the book

Raw text gives the agents *retrieval* — they can quote a passage. It does not
give them *judgement*. The Sinclair and Chan notes did three things the raw
text cannot: they extracted the principle, mapped it onto Trezo's actual code
and constants, and named what would have to change. That mapping is the work,
and it is what turns a citation into a rule.

So each phase below produces two things: a **note in the drop-box** (agents
read it daily, and Mike can read it too) and a **proposal** (evidence-backed,
never self-applied).

---

## The order, and why it is this order

The sequence is not by importance. It is by **what unblocks the most**.

### PHASE 1 — de Prado · *Advances in Financial Machine Learning*
**Problem it solves: we are about to change trading rules on the strength of
about 30 trades, and we have no way to know whether that is enough.**

This has to be first. Today alone we produced a giveback sweep whose winner
changed depending on which value we tried, a "worst lane" conclusion I had to
retract twice, and a replay harness that was wrong four times. Every one of
those is a small-sample problem, and every decision queued behind the replay
depends on getting this right. Reading anything else first means making those
decisions with the same blindfold on.

The relevant chapters are already located: **14.7.2 Probabilistic Sharpe
Ratio**, **14.7.3 Deflated Sharpe Ratio**, **Chapter 11 backtest overfitting**,
**Chapter 15.4 The Probability of Strategy Failure**, and purged
cross-validation with embargo (48 and 52 mentions respectively).

One idea from it is already worth stating, because it indicts something I did
today: he argues a backtest must account for **the number of trials it took to
arrive at the strategy**. My giveback sweep tried four values and reported the
best. Four trials means the winner is four times more likely to be luck, and
nothing in my report adjusted for that. The deflated Sharpe exists precisely to
charge you for the trials you ran.

**Deliverables:** a note; a **permutation / deflated-significance gate** the
proposal engine must pass before any floor, giveback or multiplier moves; and
an honest answer to "how many closed trades before a lane's record means
anything."

### PHASE 2 — Vince · *The Mathematics of Money Management*
**Problem it solves: the deployment cap is a round number, and position sizing
and geometry interact in ways we have not modelled.**

Chan gave us the shape — growth is concave in leverage, with a cliff past the
optimum, and at f=31 in his example the growth rate is −1, meaning ruin. Vince
is where that curve comes from, and he goes further into drawdown as the
binding constraint rather than growth.

This matters to Trezo directly: `TREZO_MAX_DEPLOY_X = 1.25` was chosen as a
sensible-looking number, not derived from anything. Vince gives the machinery
to say what fraction of optimal it represents and what drawdown it implies.

**Deliverables:** a note; a derivation of the deploy cap as a deliberate
fraction of estimated optimal with the ruin threshold written down; and a check
on whether the allocation pockets' per-lane budgets are consistent with it.

### PHASE 3 — Natenberg · *Option Volatility & Pricing*
**Problem it solves: the wheel and covered-call lanes sell premium without ever
asking whether the premium is expensive.**

This is the largest named gap left in the options notes. Trezo now measures
volatility properly (the Yang-Zhang estimator shipped today), but it has no
notion of **IV rank** — where today's implied volatility sits in its own
history. Selling a put because a strike is available is different from selling
it because the premium is genuinely rich, and only the second is an edge.

**Deliverables:** a note; an **IV-rank gate** for the wheel and CC lanes; and a
review of whether the harvest ladder's percentages should vary with IV rank
rather than being fixed.

### PHASE 4 — Harris · *Trading and Exchanges*
**Problem it solves: costs killed a whole lane and we only noticed by
accident.**

The crypto scalp lane was exiting at +0.63% because that is what round-trip
cost plus a hair comes to. Fees, spread and liquidity are not an afterthought
in that lane — they are the whole economics of it. Harris is the standard text
on why costs behave the way they do, who is on the other side of a trade, and
what different order types actually cost you.

**Deliverables:** a note; a review of whether Alpaca's real crypto fees are
modelled now that broker-only mode routes there (the code models Kraken's
26bps); and a plain statement of the minimum edge a lane must clear to be worth
running at all.

### PHASE 5 — Tharp · *Trade Your Way to Financial Freedom*
**Problem it solves: position sizing is still the least-examined part of the
system — and this is the one Mike should read himself.**

There is already a Tharp note in the drop-box, written from principle rather
than from the book. The full text adds expectancy, R-multiples and system
quality. It is also by some distance the most readable of the five, which makes
it the natural companion to the teaching layer: the same material serves the
agents and serves Mike's own study.

**Deliverables:** a note that supersedes the existing one; R-multiple reporting
in the daily digest; and the first pass at the teaching-layer glossary, since
Tharp defines most of the vocabulary in plain language.

---

## How long this takes, honestly

Each phase is a session or more. de Prado is 393 pages of dense material and
Tharp is 539. I will not pretend five books can be absorbed in an afternoon,
and a rushed note is worse than none — it produces confident wrong mappings
onto the code, which is exactly the failure mode we spent today fixing.

What makes it tractable is that the books are searchable. I do not read
cover-to-cover; I go to the chapters that answer a named Trezo problem, verify
the mapping against the actual code, and write the note. That is why the plan
is organised by problem.

## The rule that governs all of it

Nothing from a book is applied directly. A book explains **why** a rule might
be better; only Trezo's own ledger can say **whether** it is. Every phase ends
at a proposal with evidence, and Mike decides. That rule is what has kept the
platform honest, and five expensive books do not earn an exemption from it.

## Suggested first move

Phase 1, and specifically the significance gate — because the rule replay is
built and waiting, and the temptation to act on its first output is exactly the
mistake de Prado's book is about.
