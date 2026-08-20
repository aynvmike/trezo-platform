# Trezo — What the Agents Would Change

_Written by the agents from their own logged evidence. Nothing here is self-applied: these are proposals for Mike, the same way the Rulebook is a record of decisions already made._

_Last updated 2026-08-12 17:33 UTC · 18 open · 1 shipped_

---

## 101 unknown setups missed the bar by 3 points or less

**Area:** Confidence floor  ·  **Raised by:** risk_manager  ·  **Observed 64×** since 2026-07-27

**What the agents keep seeing:** In 24 hours, 101 unknown signals scored within 3 points of the floor and were refused. That is a crowd at the door, not a trickle.

**Evidence:** 101 near-miss refusals in 24h for unknown.

**Why it matters:** These may be the cheapest available additional trades -- or the exact trades that should stay refused. Only a shadow test can tell.

**Proposed change:** Do NOT lower the floor on a hunch. Run these near-misses in shadow: record what they WOULD have returned for two weeks, then move the floor only if the shadow ledger is profitable. Evidence first, dial second.

`proposal key: near_miss:unknown`

---

## crypto_dca is not paying for itself (PF 0.20 over 28 trades)

**Area:** Strategy weighting  ·  **Raised by:** learning_loop  ·  **Observed 62×** since 2026-07-30

**What the agents keep seeing:** crypto_dca closed 28 trades in 21 days: 16 wins, $22.54 gross won against $111.70 gross lost.

**Evidence:** PF 0.20, win rate 57%, net $-89.16 over 28 closed trades. SIGNIFICANCE: with 28 trades the 95% interval for average P&L per trade is $-6.40 to $-0.48, which does NOT straddle zero -- this result is distinguishable from luck. GEOMETRY: its realised win/loss sizes demand a 87% win rate just to break even; it is running at 57%.

**Why it matters:** Capital committed here is earning less than it loses.

**Proposed change:** Either raise crypto_dca's confidence bar so only its best setups trade, or shrink its allocation until the record recovers. The outcome loop can do this itself once its sample threshold is met -- this proposal is the human-visible version of that same evidence.

`proposal key: strategy_weak:crypto_dca`

---

## crypto_scalp is not paying for itself (PF 0.27 over 30 trades)

**Area:** Strategy weighting  ·  **Raised by:** learning_loop  ·  **Observed 62×** since 2026-07-30

**What the agents keep seeing:** crypto_scalp closed 30 trades in 21 days: 16 wins, $34.45 gross won against $126.91 gross lost.

**Evidence:** PF 0.27, win rate 53%, net $-92.46 over 30 closed trades. SIGNIFICANCE: with 30 trades the 95% interval for average P&L per trade is $-6.38 to $-0.14, which does NOT straddle zero -- this result is distinguishable from luck. GEOMETRY: its realised win/loss sizes demand a 71% win rate just to break even; it is running at 53%.

**Why it matters:** Capital committed here is earning less than it loses.

**Proposed change:** Either raise crypto_scalp's confidence bar so only its best setups trade, or shrink its allocation until the record recovers. The outcome loop can do this itself once its sample threshold is met -- this proposal is the human-visible version of that same evidence.

`proposal key: strategy_weak:crypto_scalp`

---

## forex_swing is earning its keep (PF 14.99 over 10 trades)

**Area:** Strategy weighting  ·  **Raised by:** learning_loop  ·  **Observed 50×** since 2026-07-30

**What the agents keep seeing:** forex_swing closed 10 trades in 21 days with 9 wins and a profit factor of 14.99.

**Evidence:** PF 14.99, win rate 90%, net $+4.70 over 10 closed trades. SIGNIFICANCE: with 10 trades the 95% interval for average P&L per trade is $+0.20 to $+0.74, which does NOT straddle zero -- this result is distinguishable from luck.

**Why it matters:** This lane is currently the most reliable source of daily income.

**Proposed change:** Consider giving forex_swing a larger share of the daily capital, or letting it take more concurrent shots, while the record holds. Re-check after every 10 further closes -- a good record is a lease, not a deed.

`proposal key: strategy_strong:forex_swing`

---

## extended is earning its keep (PF 2.17 over 36 trades)

**Area:** Strategy weighting  ·  **Raised by:** learning_loop  ·  **Observed 31×** since 2026-07-27

**What the agents keep seeing:** extended closed 36 trades in 21 days with 28 wins and a profit factor of 2.17.

**Evidence:** PF 2.17, win rate 78%, net $+134.85 over 36 closed trades.

**Why it matters:** This lane is currently the most reliable source of daily income.

**Proposed change:** Consider giving extended a larger share of the daily capital, or letting it take more concurrent shots, while the record holds. Re-check after every 10 further closes -- a good record is a lease, not a deed.

`proposal key: strategy_strong:extended`

---

## The broker keeps refusing the same order shape (3× in 24h)

**Area:** Execution / broker  ·  **Raised by:** trade_execution  ·  **Observed 11×** since 2026-08-05

**What the agents keep seeing:** “Alpaca rejected the order: Bracket rejected locally: short take-profit” was rejected 3 times in 24 hours. Repeated rejects of one shape are a construction bug, not market conditions.

**Evidence:** 3 identical-shape rejects in 24h out of 14 errors.

**Why it matters:** Rejects count toward the kill-switch, so a recurring malformed order can pause every lane -- including the 24/7 ones.

**Proposed change:** Validate this order shape locally before submission so a malformed order never reaches the broker or the halt counter.

`proposal key: broker_reject:alpaca_rejected_the_order:_bracket_rejec`

---

## crypto_swing is not paying for itself (PF 0.29 over 16 trades)

**Area:** Strategy weighting  ·  **Raised by:** learning_loop  ·  **Observed 7×** since 2026-08-11

**What the agents keep seeing:** crypto_swing closed 16 trades in 21 days: 10 wins, $38.77 gross won against $133.37 gross lost.

**Evidence:** PF 0.29, win rate 62%, net $-94.61 over 16 closed trades. SIGNIFICANCE: with only 16 trades the 95% interval for average P&L per trade runs $-15.06 to $+1.92, which STRADDLES ZERO. This sample cannot yet tell profit from noise, so treat the figure above as a signal to keep watching rather than as a finding. GEOMETRY: its realised win/loss sizes demand a 82% win rate just to break even; it is running at 62%.

**Why it matters:** Capital committed here is earning less than it loses.

**Proposed change:** Either raise crypto_swing's confidence bar so only its best setups trade, or shrink its allocation until the record recovers. The outcome loop can do this itself once its sample threshold is met -- this proposal is the human-visible version of that same evidence.

`proposal key: strategy_weak:crypto_swing`

---

## reconciled is not paying for itself (PF 0.66 over 21 trades)

**Area:** Strategy weighting  ·  **Raised by:** learning_loop  ·  **Observed 5×** since 2026-08-11

**What the agents keep seeing:** reconciled closed 21 trades in 21 days: 13 wins, $18.97 gross won against $28.96 gross lost.

**Evidence:** PF 0.66, win rate 62%, net $-9.99 over 21 closed trades. SIGNIFICANCE: with only 21 trades the 95% interval for average P&L per trade runs $-1.67 to $+0.68, which STRADDLES ZERO. This sample cannot yet tell profit from noise, so treat the figure above as a signal to keep watching rather than as a finding. GEOMETRY: its realised win/loss sizes demand a 63% win rate just to break even; it is running at 62%.

**Why it matters:** Capital committed here is earning less than it loses.

**Proposed change:** Either raise reconciled's confidence bar so only its best setups trade, or shrink its allocation until the record recovers. The outcome loop can do this itself once its sample threshold is met -- this proposal is the human-visible version of that same evidence.

`proposal key: strategy_weak:reconciled`

---

## One refusal is doing 62% of the vetoing: “Kill-switch [day] - Daily loss limit: down $75 (-3.0%) today”

**Area:** Gates / capacity  ·  **Raised by:** ops_watchdog  ·  **Observed 4×** since 2026-08-07

**What the agents keep seeing:** Of 512 refusals in the last 24h, 315 were the same reason. When one gate accounts for nearly half of every 'no', it is shaping the book more than the strategies are.

**Evidence:** 315/512 vetoes (62%) in 24h; 0 approvals and 0 executions in the same window.

**Why it matters:** Signals that pass every quality test are being turned away by a capacity or configuration limit, not by their own merit.

**Proposed change:** Review whether this limit is still the right size for the account. If it is a position/slot cap, raising it one notch converts refused signals into shots on goal; if it is a data or config gate, fixing the source removes the refusals entirely.

`proposal key: veto_dominant:kill-switch_[day]_-_daily_loss_limit:_do`

---

## One refusal is doing 60% of the vetoing: “Kill-switch [session] - 3 broker order rejects in the last 6”

**Area:** Gates / capacity  ·  **Raised by:** ops_watchdog  ·  **Observed 3×** since 2026-07-31

**What the agents keep seeing:** Of 315 refusals in the last 24h, 190 were the same reason. When one gate accounts for nearly half of every 'no', it is shaping the book more than the strategies are.

**Evidence:** 190/315 vetoes (60%) in 24h; 6 approvals and 0 executions in the same window.

**Why it matters:** Signals that pass every quality test are being turned away by a capacity or configuration limit, not by their own merit.

**Proposed change:** Review whether this limit is still the right size for the account. If it is a position/slot cap, raising it one notch converts refused signals into shots on goal; if it is a data or config gate, fixing the source removes the refusals entirely.

`proposal key: veto_dominant:kill-switch_[session]_-_3_broker_order_r`

---

## One refusal is doing 56% of the vetoing: “Kill-switch [day] - 5 losing trades in a row (limit 5)”

**Area:** Gates / capacity  ·  **Raised by:** ops_watchdog  ·  **Observed 2×** since 2026-08-09

**What the agents keep seeing:** Of 508 refusals in the last 24h, 286 were the same reason. When one gate accounts for nearly half of every 'no', it is shaping the book more than the strategies are.

**Evidence:** 286/508 vetoes (56%) in 24h; 4 approvals and 4 executions in the same window.

**Why it matters:** Signals that pass every quality test are being turned away by a capacity or configuration limit, not by their own merit.

**Proposed change:** Review whether this limit is still the right size for the account. If it is a position/slot cap, raising it one notch converts refused signals into shots on goal; if it is a data or config gate, fixing the source removes the refusals entirely.

`proposal key: veto_dominant:kill-switch_[day]_-_5_losing_trades_in_a`

---

## One refusal is doing 53% of the vetoing: “Open-signal cap reached (14)”

**Area:** Gates / capacity  ·  **Raised by:** ops_watchdog  ·  **Observed 1×** since 2026-07-30

**What the agents keep seeing:** Of 360 refusals in the last 24h, 191 were the same reason. When one gate accounts for nearly half of every 'no', it is shaping the book more than the strategies are.

**Evidence:** 191/360 vetoes (53%) in 24h; 2 approvals and 1 executions in the same window.

**Why it matters:** Signals that pass every quality test are being turned away by a capacity or configuration limit, not by their own merit.

**Proposed change:** Review whether this limit is still the right size for the account. If it is a position/slot cap, raising it one notch converts refused signals into shots on goal; if it is a data or config gate, fixing the source removes the refusals entirely.

`proposal key: veto_dominant:open-signal_cap_reached_(14)`

---

## The broker keeps refusing the same order shape (6× in 24h)

**Area:** Execution / broker  ·  **Raised by:** trade_execution  ·  **Observed 1×** since 2026-08-03

**What the agents keep seeing:** “Alpaca rejected the crypto order: HTTP 403: insufficient balance for U” was rejected 6 times in 24 hours. Repeated rejects of one shape are a construction bug, not market conditions.

**Evidence:** 6 identical-shape rejects in 24h out of 6 errors.

**Why it matters:** Rejects count toward the kill-switch, so a recurring malformed order can pause every lane -- including the 24/7 ones.

**Proposed change:** Validate this order shape locally before submission so a malformed order never reaches the broker or the halt counter.

`proposal key: broker_reject:alpaca_rejected_the_crypto_order:_http_4`

---

## The crypto regime switch reads closing prices only -- it cannot see a violent day that closes flat

**Area:** Crypto regime selection  ·  **Raised by:** options_desk  ·  **Observed 1×** since 2026-08-05

**What the agents keep seeing:** The SWING/SCALP decision in crypto turns on Bollinger Band width, which is measured from daily CLOSING prices. A coin that opens at 100, runs to 108, drops to 96 and closes at 100 -- every day for a month -- produces a NARROW band, so it is classified as quiet range-bound tape and routed to SCALP. It is in fact one of the most violent charts on the board. The same flaw was just found and fixed on the options side, where it was mispricing every contract in choppy-but-flat tape.

**Evidence:** Measured on 40 synthetic daily bars of exactly that shape: close-to-close volatility reads 15.0% (its clamp floor -- it literally sees nothing), while the Yang-Zhang range estimator reads 128.1%. On 120 bars of realistic tape, rolling 20-bar windows: close-to-close wobbles 5.18 percentage points, Yang-Zhang 2.28 -- less than half the noise. Crypto candles are daily (fetch_crypto_ohlc days=90), so intrabar range is exactly what is being discarded. Estimator shipped and live on the options lanes as of commit 3c32d03.

**Why it matters:** Wrong regime means the wrong strategy fires: SCALP entries with tight stops get taken out by ranges the selector never saw. It also affects which coins clear the floor at all.

**Proposed change:** Do NOT swap the regime input on a hunch -- this changes which trades fire, and a bad switch is worse than a blind one. Run it in SHADOW first: on every crypto scan, log the Yang-Zhang range volatility alongside the BB-width reading and record which regime EACH would have chosen. After two weeks, compare the outcomes of the trades the two selectors disagreed on. Move the input only if the shadow ledger says the range-based read picked better. iv_from_candles() in app/options/pricing.py is ready to call -- the measurement is free, the behaviour change is not.

`proposal key: vol_blind_spot:crypto_bb_regime`

---

## SCALP shrinks the target more than the stop, turning a designed 1:2 into 1:1.67

**Area:** Crypto scalp geometry  ·  **Raised by:** position_monitor  ·  **Observed 1×** since 2026-08-05

**What the agents keep seeing:** Every coin is configured with a clean 1:2 reward-to-risk -- risk 3% to make 6% on the tier-a names, 5%/10% on tier-b. But the SCALP branch in strategies/crypto.py rescales BOTH numbers by DIFFERENT factors: the stop by 0.6 and the target by 0.5. ALGO, XLM and HBAR therefore enter with a 1.8% stop against a 3.0% target, which is 1:1.67, not 1:2. Nothing logs this as a change -- the thesis line reads "untiered-cap formulas sized the geometry", which is doubly misleading because the cap-tier block is skipped for crypto entirely and no cap formula ran at all.

**Evidence:** Four stop-outs on 2026-07-27 cluster at -1.87%, -1.88%, -1.91% and -1.93% across THREE different coins whose configured stops are all 3.0%. A 1.8% stop plus 5bps slippage and round-trip fees lands exactly there. The thesis lines confirm it in words: "exit: target +3.0%, stop -1.8%". Scaling both legs by the SAME factor would preserve the ratio -- 0.6/0.6 gives 1.8%/3.6%, 0.5/0.5 gives 1.5%/3.0%, both still 1:2.

**Why it matters:** This compounds with the net-edge exit. The scalp lane takes profit at +0.63% while carrying a 1.8% stop, so the geometry it actually realises is roughly 1:2.9 AGAINST. Two independent leaks in the same lane, and the lane is the most active one in the book.

**Proposed change:** Make the two multipliers equal so the designed ratio survives the rescale. Which value to use is a real choice and should be measured, not assumed: 0.6/0.6 keeps more room and takes fewer stop-outs, 0.5/0.5 turns capital over faster and suits the velocity mandate. Run both through the rule replay before picking. Separately, fix the thesis text so it stops claiming a cap formula sized geometry that crypto never passes through -- a log line that names the wrong cause costs more time than no log line at all.

`proposal key: geometry_leak:crypto_scalp_multipliers`

---

## Cheap options are a buying opportunity, not merely a bad sale -- scout them

**Area:** Options -- buy side  ·  **Raised by:** options_desk  ·  **Observed 1×** since 2026-08-05

**What the agents keep seeing:** The variance-premium measurement built for the wheel answers a question in both directions, but was only being read one way. RICH means the seller is overpaid. CHEAP -- an option pricing LESS movement than the underlying is actually delivering -- means the BUYER is underpaid for. Mike raised this: a small account can buy thin, cheap contracts that a large fund cannot touch without moving the price against itself. That capacity asymmetry is real and it favours a ,900 account.

**Evidence:** premium_verdict now reports buy_premium_ok alongside sell_premium_ok, and the boundary behaves correctly: at 34% implied against 40% realized buying is favoured and selling refused; at exactly equal volatility neither side is favoured, which is the right answer. No live cheap options have been observed yet -- the wheel only refines PUTS it intends to SELL, so nothing currently scans for options worth owning.

**Why it matters:** Buying inverts the payoff shape and therefore the sizing. Modelled on 500 trades: selling premium at a 70% win rate gives optimal f of 0.124; buying genuinely cheap options at a 20% win rate with a 5:1 payoff is positive-expectancy (+0.33/trade) but optimal f falls to 0.066, because every loss is 100% of that ticket. A typical out-of-the-money buy at a 10% win rate has NEGATIVE expectancy and no viable f at all -- so this only works on options that are measurably cheap, never on cheap-looking ones.

**Proposed change:** Observe first, exactly as with the sell side. Extend the scanner to price a few liquid candidates each day, record the CHEAP verdicts, and accumulate them for a few weeks. Only then ask whether the cheap ones actually paid. If a sleeve is ever built it needs a small dedicated allocation sized so that eight consecutive losers is boring -- at a 20% win rate that streak is ordinary, and a sleeve abandoned mid-streak turns a positive-expectancy strategy into a realised loss.

`proposal key: observe:cheap_option_buying`

---

## Paper results at $100k will overstate reality unless slippage scales with position size

**Area:** Cost model / paper realism  ·  **Raised by:** ops_watchdog  ·  **Observed 1×** since 2026-08-06

**What the agents keep seeing:** Mike plans to step the paper account from $5k to $25-30k to $100k to prove Trezo works at any portfolio level. That is a good test of the CODE and a misleading test of the STRATEGY, because the paper engine charges a FLAT 5bps of slippage regardless of position size. At $4,900 a position in a thin coin is invisible to the market. At $100,000 the same position IS the market -- and the paper fill will still assume the price that was on screen.

**Evidence:** app/paper/engine.py SLIPPAGE_BPS = 5, applied identically to every asset and every size. The Harris work of 2026-08-05 already found this understates a thin-alt round trip by more than three times at CURRENT size; the error grows with the position. Trezo now has real spread data via the crypto quote function added the same day, and quote sizes (bid_size, ask_size) are already parsed but unused.

**Why it matters:** The scaling plan is designed to answer 'does this work bigger'. With size-blind slippage it will answer yes for lanes that would actually degrade -- specifically the thin-alt crypto lane, which is where Trezo trades most. The bigger the paper account, the more flattering and the less true the result. The risk is concluding the strategy scales when only the simulation does.

**Proposed change:** Before stepping the paper account up, make slippage a function of order size relative to displayed liquidity: compare intended notional against bid_size/ask_size at the touch and widen the fill accordingly. Even a crude first version -- charge the half-spread when the order is under the displayed size, add a penalty proportional to how far it exceeds it -- would be far more honest than a flat constant. Then run the same strategy at $5k, $25k and $100k and compare. If the edge survives only at $5k, that is exactly the finding the plan was designed to produce.

`proposal key: scaling:slippage_must_grow_with_size`

---

## The broker keeps refusing the same order shape (3× in 24h)

**Area:** Execution / broker  ·  **Raised by:** trade_execution  ·  **Observed 1×** since 2026-08-12

**What the agents keep seeing:** “Alpaca rejected the order: HTTP 403: insufficient buying power” was rejected 3 times in 24 hours. Repeated rejects of one shape are a construction bug, not market conditions.

**Evidence:** 3 identical-shape rejects in 24h out of 34 errors.

**Why it matters:** Rejects count toward the kill-switch, so a recurring malformed order can pause every lane -- including the 24/7 ones.

**Proposed change:** Validate this order shape locally before submission so a malformed order never reaches the broker or the halt counter.

`proposal key: broker_reject:alpaca_rejected_the_order:_http_403:_ins`

---

## Shipped

- **One refusal is doing 59% of the vetoing: “Open-signal cap reached (10)”** — Mike approved 2026-07-27: max_open_positions raised 10 -> 14 (live setting). Same-day option caps also raised 2/4/2 -> 3/8/3 as PDT-era leftovers. (2026-07-27)


## Retired (no longer observed)

- pattern is not paying for itself (PF 0.04 over 10 trades) — last seen 15 days ago

- Reward proven lanes sooner than we punish unproven ones — last seen 16 days ago
