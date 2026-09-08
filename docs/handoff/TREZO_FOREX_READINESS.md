# Trezo forex readiness

September 8, 2026. Status: **source audit and implementation plan only**. Forex execution was not enabled, no broker was connected, and no account or order was created. This document does not establish forex profitability or a daily income rate. It complements [the learning-loop build plan](TREZO_LEARNING_LOOP_BUILD_PLAN.md).

## What is already bound

| Component | Verified implementation | Consequence |
| --- | --- | --- |
| Agent registration | `agents/app/runtime/bootstrap.py` registers `ForexScannerAgent`; `agents/app/agents/forex_scanner.py` declares a 180-second cadence and ten fiat pairs. | The scanner is registered; it is not a missing-agent scaffold. Its header still describes the older Kraken-only feed. |
| Dormancy | The scanner emits `forex_lane_dormant` when broker-only mode is enabled and `trezo_forex_modeled_ok` is false. `agents/app/agents/risk_manager.py` independently vetoes those forex signals. | Dormancy is intentional: no broker FX route is implemented. This audit does not independently verify the running server's environment values. |
| Data | `agents/app/data/forex.py` calls Twelve Data `time_series` first and falls back to Kraken public OHLC. The scanner requests 4-hour candles. | Historical data plumbing exists, but it is not a strict research dataset contract. Current provider entitlement and quotas were not verified in this audit. |
| Execution | `agents/app/agents/trade_execution.py` recognizes `asset_type=forex` and ultimately calls `_execute_internal` and `agents/app/paper/engine.py`. The broker directory has no dedicated forex adapter. | Enabling the modeled flag creates generic internal simulations, not FX orders at a broker. |
| Account controls | The scanner asks `lane_enabled_any("forex_enabled", default=...)` with an environment default, while `agents/app/runtime/book_gate.py` gates forex using each book's `crypto_enabled`. `agents/app/config.py` separately declares `forex_enabled=False`. | The settings names do not form a single authoritative per-book FX toggle. Trace the actual readers before introducing one. |
| Research | `agents/app/research/bridge.py` accepts only `stock` and `crypto`; the research core is long-only and assumes USD-priced instruments. | The newly added research loop does not currently generate or evaluate forex candidates. |

## Why the existing flag is insufficient

The generic paper engine calculates notional as quantity multiplied by the pair price and records the resulting cash and P&L in USD. That is not valid for pairs whose quote currency is JPY, GBP, CAD or another non-USD currency. For example, a USD/JPY price difference produces JPY P&L before conversion into the account's currency. The paper engine has no such conversion path. OANDA's U.S. examples explicitly show the required conversion. [P&L calculation](https://www.oanda.com/us-en/trading/how-calculate-profit-loss/)

The engine also applies its generic 5-basis-point slippage on each fill, charges zero forex commission, and has no FX bid/ask spread, financing, rollover, currency-exposure or broker-margin model. Skipping U.S. equity session checks does not establish that the FX venue is open. OANDA's U.S. FX schedule includes a weekend closure and daily breaks; overnight positions may incur financing charges. [Trading hours](https://www.oanda.com/us-en/trading/hours-of-operation/), [financing](https://www.oanda.com/us-en/trading/financing-fees/)

The present data adapter also needs strengthening before it supplies durable research evidence:

- Provider failures collapse into an empty list, without distinguishing authentication, quota, transport failure or no data.
- The cache key includes pair and interval but omits requested history length, so a short cached request can satisfy a later longer request incorrectly.
- Provider identity appears in a debug log rather than accompanying the returned candle series. A fallback therefore changes the source without a durable research receipt.
- Neither provider parser explicitly discards the unfinished candle. Kraken documents that its last OHLC entry is unfinished and that the endpoint supplies at most 720 recent entries; older data cannot be retrieved through `since`.
- Kraken data is a particular exchange's fiat-pair market. It must not silently substitute for the eventual retail FX broker's executable prices or be treated as a consolidated FX volume tape.

[Kraken OHLC specification](https://docs.kraken.com/api-reference/market-data/get-ohlc-data)

## Staged implementation and acceptance

### 1. Strict historical research, execution disabled

Start with EUR/USD, GBP/USD and AUD/USD, whose quote currency matches a USD research account. This narrows the conversion problem; it does not remove trading costs or make the current paper engine broker-equivalent.

Introduce a source-stamped dataset response containing instrument, base and quote currencies, provider, interval, requested range, returned range, fetch time, completed-bar status and error state. Keep provider selection fixed for an experiment. Cache by all request parameters that change the dataset, reject stale, incomplete, duplicated or invalid bars, and retain the exact dataset hash with every trial. Do not silently blend Twelve Data and Kraken observations.

Bind the strict adapter to a separate forex research scope. Record explicit spread, slippage, commission and financing assumptions alongside the current book-equity snapshot. If historical financing is unavailable, either use an explicitly bounded scenario and label the uncertainty or limit the experiment to intraday positions with a defined flattening rule before the financing cutoff. A daily-bar strategy holding overnight cannot simply omit financing. The current long-only grammar may be reused only with that limitation declared; short-strategy support requires separate tests and accounting.

Acceptance:

- A real discovery call produces persistent forex research trials and a visible blocked result when valid data or costs are missing.
- Failed provider reads do not create synthetic prices or a completed empty experiment; a longer history request cannot reuse an inadequate short cache entry.
- Each trial stores source, dataset hash, costs, account scope, capital snapshot and strategy version; repeated runs are idempotent.
- The actual research path has no order-submission call, does not change active strategies, and cannot spend from an account.
- Output says historical research and keeps profitability and promotion eligibility unverified. No paid plugin is established as necessary merely to begin this stage; provider entitlement and platform-use licensing must still be checked.

### 2. Dedicated broker practice integration and FX accounting

OANDA's U.S. service advertises API automation, and its v20 documentation provides a demo-account setup and a distinct practice API host. This is a concrete candidate for a later practice integration, not a verified connection or account approval for Mike. A v20 account and appropriate API access are prerequisites. [OANDA U.S.](https://www.oanda.com/us-en/), [v20 setup](https://developer.oanda.com/rest-live-v20/introduction/), [practice environments](https://developer.oanda.com/rest-live-v20/development-guide/)

Implement a dedicated adapter that permits only the canonical practice hosts and refuses live endpoints. Bind every read and order to the correct book and verified practice account. Use account-specific instrument metadata, quantity precision, bid/ask quotes, home-currency conversion, trading status and broker transactions. The pricing API exposes bid/ask information, conversion factors and instrument candle requests. [Pricing API](https://developer.oanda.com/rest-live-v20/pricing-ep/)

Add FX-specific units/pip calculations, quote-to-USD P&L conversion, financing and commission records, spread-aware fills, margin availability, currency concentration and the venue's session calendar. Crosses such as USD/JPY or EUR/GBP remain unsupported until conversion paths are tested. Separate practice equity, transactions and research lineage from Alpaca books and generic internal simulated fills.

Acceptance:

- Endpoint and account checks prevent accidental live routing and cross-book reads or writes.
- A failed account, position or transaction read is unknown and blocks dependent actions; it cannot be interpreted as an empty account.
- Entry, partial exit, final exit, stop, gap and financing events reconcile to unique broker transaction IDs without guessed corrections or duplicate P&L.
- USD-quoted, inverse-USD and non-USD cross examples produce correct USD values, including costs. Risk and sizing follow the account's verified balance and margin information.
- Practice status, executed version and actual receipt evidence are observable after deployment. No adapter is enabled merely because unit tests pass.

### 3. Walk-forward evaluation and evidence-based progression

Use sequential training windows and untouched later evaluation windows. Retain every attempted variant and failed result; selecting only winners obscures the effect of repeated search. After historical screening, run frozen candidates forward in practice and compare against the incumbent over the same account, period, exposure and cost assumptions.

Review trade paths as well as final outcomes: favorable and adverse excursions when recorded data permits, entry and exit timing, slippage, financing, session, currency exposure and whether the original signal survived. Clearly label unavailable intratrade observations. Replaying past days is research; it does not create new independent forward evidence.

Acceptance:

- Future prices and validation outcomes cannot influence earlier entries or candidate generation.
- Research results and broker-practice results remain separately labeled and traceable.
- Promotion requires a separately implemented controller, predeclared evidence requirements, per-book risk checks and rollback criteria; none is enabled by this audit.
- A newer strategy may be rejected, an older strategy may remain active, and no-trade days remain valid. More markets or more candidates do not establish dependable daily income.

## Instrument scope

This plan concerns fiat foreign-exchange pairs. Crypto/stablecoin pairs, currency futures and CFDs are different instruments with different venues, contracts and account requirements. Do not substitute one for another in datasets, symbol routing, cost assumptions or claims about account eligibility. The broker practice integration described here must use instruments actually available to that U.S. practice account; generic international API examples do not establish U.S. product availability.
