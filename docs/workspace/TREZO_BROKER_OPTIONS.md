# Which Broker Unlocks What — a decision note

_Written 2026-08-05 after Mike asked whether IBKR or another venue offers what
Alpaca does not, having realised that dormant lanes are costing diversification._

---

## Why this matters, in one line

Portfolio Sharpe = sleeve Sharpe × √(effective bets). Trezo currently gets
**6.83 effective bets**, with 64% of risk in a single factor. Every genuinely
independent lane that starts working lowers the Sharpe each sleeve has to
produce. At today's effective-bet count, the 0.2%/day target needs only ~0.75
Sharpe per sleeve — "decent", not "elite". **More working lanes is the cheapest
route to the goal**, and dormant lanes are therefore expensive.

## What is actually dormant, and why

Trezo has **three venues already scaffolded and switched off**:

| lane | code that exists | why it is dark |
|---|---|---|
| **Forex** (Layer 6) | full strategy + signals | **Alpaca has no forex venue.** Under broker-only mode forex can only ever be modelled, so it is paused. 66 vetoes on 8/5 alone. |
| **Futures** | `brokers/kraken_futures.py`, Phase 1 complete (data + read) | Phase 2 — scanner and demo orders — was never built. **Kraken's demo is free.** |
| **ISO 20022 crypto** | `brokers/crypto_exchange.py` scaffold | Coinbase/Kraken connector for coins Alpaca cannot list. Feature-flagged off, `is_configured()` returns False. |

The architecture is ready for them. `brokers/active.py` is an explicit adapter
layer whose own docstring says "Webull, Robinhood, IBKR, etc. plug in by
implementing the same BrokerAdapter shape", and Webull and Robinhood are already
stubbed. The read-side surface is two functions per broker.

**One honest correction to that optimism:** `active.py` covers *reading*
(snapshot, option chain). *Execution* still routes through
`trade_execution.py`, which branches to Alpaca-specific calls. Adding a venue
that can actually place orders is a larger job than the adapter file suggests.

## The venue comparison, checked rather than recalled

### Interactive Brokers — most capability, worst fit

IBKR covers everything Trezo lacks: real spot forex, futures, international
equities, bonds, global options. On capability alone it is the obvious answer.

**But its authentication model fights unattended operation.** Per IBKR's own
documentation, automating access via token schemes such as OAuth is available
for certain integrations, while **individual retail clients using the Client
Portal Gateway must complete a manual login with username and password**. The
gateway is a Java process that must stay running, and sessions require periodic
tickling and re-authentication. Third-party tools such as IBeam exist precisely
to work around this, which tells you the problem is real.

> Mike is migrating Trezo to a VM **specifically so it runs without him**. A
> broker that needs a human to type a password into a desktop gateway is
> pulling in the opposite direction. This is the deciding factor, not capability.

### OANDA — narrow, but the right shape

Forex and CFDs only — no stocks, no options. But for the lane that is actually
dark:

- **A bearer token generated in the account portal that does not expire unless
  revoked.** No daily login, no gateway process, no re-auth loop.
- 90+ currency pairs plus metals, real-time and deep historical data.
- Plain REST, which is exactly what Trezo's existing adapters speak.

It unlocks Layer 6 and nothing else — but Layer 6 is a whole dormant sleeve, and
forex is genuinely uncorrelated with crypto and equities, which is precisely
what the effective-bet count needs.

### Kraken Futures — already half-built and free

`kraken_futures.py` exists, Phase 1 is done, and the demo environment mirrors
production over the same API with only the base URL differing. **No real money
is required to make this lane real.** Leverage is capped 1–10x by Mike's own
earlier decision.

Cheapest unlock available, by a distance.

---

## Recommended order, and the reasoning

**1. Finish repairing crypto first.** The exit rule was fixed 8/5; the
asymmetric SCALP multipliers still need to go. Adding venues while an existing
lane leaks multiplies the leak rather than diluting it — and a negative sleeve
does not diversify, it subtracts.

**2. Kraken Futures demo.** Already scaffolded, free, genuinely uncorrelated,
and no money at risk while the agents learn it. Highest value per hour of work.

**3. OANDA for forex.** Makes a dead layer real, with an auth model that suits
a 24/7 unattended system. Medium effort, one clean adapter.

**4. IBKR — only if the goal changes.** Revisit if international equities,
bonds or exchange-traded futures become the objective AND the gateway burden is
acceptable. It is the most powerful option and the worst operational fit for
what Trezo is trying to be.

## The trap to avoid

More venues means more surface: more credentials, more failure modes, more
reconciliation, more ways for a position to be real in one place and modelled in
another — which is the exact problem the two-books work solved on 7/28. Each new
venue should earn its place by making a lane genuinely tradeable, not by adding
optionality nobody uses.

**Sources:** IBKR Campus documentation on Client Portal Gateway authentication;
OANDA developer documentation on v20 REST authentication.


---

# ADDENDUM — the coverage map, and the constraint that decides it

_Added after Mike clarified: it does not have to be IBKR, it has to cover what
is missing._

## What each strategy needs, and who provides it

| Trezo strategy | asset | Alpaca | Tastytrade | OANDA | Kraken |
|---|---|---|---|---|---|
| stms, extended, orb | US stocks | ✓ | ✓ | — | — |
| options_strategies, wheel | US options | ✓ | ✓ | — | — |
| crypto scalp/swing/dca/hodl | crypto spot | ✓ (~36) | ✓ | — | ✓ (more coins) |
| **forex_scanner** | **spot FX** | **✗** | **✗** | **✓** | — |
| **futures.py** | **futures** | **✗** | **✓** | — | ✓ (crypto only) |

Two genuine gaps: **forex** and **futures**. Everything else Alpaca already
covers.

## Tastytrade solves the problem that disqualified IBKR

Its API covers equities, options, futures and crypto in one place, and —
critically — **its refresh tokens never expire**. An initial grant is created
once in the web UI, after which a client secret plus refresh token authenticates
indefinitely, with access tokens refreshing automatically every 15 minutes. No
gateway process, no daily password.

That is exactly the operational shape Trezo needs and exactly what IBKR could
not offer a retail client.

## But futures do not fit this account yet — and this is the deciding fact

| instrument | smallest position | % of a $4,902 account |
|---|---|---|
| MES micro S&P future | ~$1,200 margin | **24.5%** |
| MNQ micro Nasdaq future | ~$1,700 margin | **34.7%** |
| MBT micro Bitcoin future | ~$1,000 margin | **20.4%** |
| one SPY option contract | ~$300–600 | 9.2% |
| **OANDA forex, 1,000 units** | **~$30** | **0.6%** |
| Alpaca crypto, fractional | $1 | ~0% |

Vince's work put sane risk at roughly **1% per trade — about $49**. A single
*micro* futures contract is twenty to thirty-five times that. Futures are not
expensive to access; they are **too coarse to size**. There is no way to take a
1% position in a product whose smallest unit is 25% of the account.

> **Forex is the opposite.** OANDA trades arbitrary unit sizes — 100 units or
> 100,000 — so a position can be sized to any risk budget. That granularity is
> precisely what a small account needs, and it is why forex fits now while
> futures do not.

## Revised recommendation

1. **Finish repairing crypto.** Unchanged and still first.
2. **OANDA for forex.** Non-expiring token, arbitrary position sizes, unlocks a
   dormant layer, genuinely uncorrelated. The clear best fit today.
3. **Kraken Futures demo** — for *learning* only. Free, already scaffolded, and
   the agents can develop futures strategy with no capital at risk while the
   account is too small to trade it for real.
4. **Tastytrade — the right venue for futures, at the wrong time.** Revisit when
   equity is large enough that one micro contract is a sane position. At a 1%
   risk budget and ~$1,200 of margin, that is somewhere north of **$25,000**.

The useful reframe: **the blocker on futures is account size, not broker
choice.** Knowing that saves picking a venue for a lane that cannot be traded
yet — and it makes Kraken's free demo the right move, because the agents can
learn the strategy now and the venue decision can wait until it matters.

**Sources:** tastytrade developer documentation on OAuth and session refresh;
Tradovate API documentation; OANDA v20 REST authentication.
