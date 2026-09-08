# Trezo learning loop: findings and local implementation

September 8, 2026. Source baseline: `4163078bdd11aafdfeb481070f2e2749e43d904a`, plus local review changes. Companion: [adaptive strategy specification](TREZO_ADAPTIVE_STRATEGY_SPEC.md).

Status: code-path audit and read-only database inspection completed. A bounded internal research pilot, backtest-isolation fix, reporting qualifications and Mem0 read diagnostics are implemented in this release. The pilot creates restricted rule combinations, tests and refines them, retains a durable SQLite journal and exports versioned JSON artifacts. It is directly bound to the existing discovery tick behind an explicit research configuration. A general LLM inventor, distributed worker service, forward-paper promotion controller and internal allocation engine are **not implemented by this change**. No production deployment, remote database mutation, broker trade or transfer was performed. The running Windows engine's SHA has not been verified.

## Product intent

Agents should create strategy hypotheses, test all attempted variants, retain evidence, recognize deterioration and improve the available strategies without routine manual intervention. Market reports must produce traceable research work when a qualifying trigger occurs. A desired income amount is a planning goal, not an instruction to force trades or increase risk until that amount is reached.

Use the confirmed $1,000 and $5,000 research balances and preserve every book's existing risk policy. Optimize net performance within that policy, with an explicit research-compute/data budget. A high win rate does not establish positive expectancy or a sustainable withdrawal amount. Small accounts must include their share of fixed platform costs in evaluations.

Mike clarified that **internal means agents create and test strategies within Trezo**, without routing reports through Discord and reading them back at unnecessary API/model cost. Research jobs, candidate definitions and results must pass directly through internal services and durable storage. The earlier question about allocating money to another or child account remains a separate requirement; its legal account type and transfer scope have not been selected.

## Confirmed source and database findings

| Finding | Evidence and implication |
| --- | --- |
| Baseline discovery reports did not schedule research | `StrategyDiscoveryAgent.tick` emitted `performance_review_due` with no research consumer. The event has UI renderers. The database contains recent discovery metrics and review alerts. The new local pilot calls its daily research cycle directly rather than depending on this alert. |
| No recently saved historical tests | The read-only database snapshot contained 269 `backtest_runs`; the newest was July 14, 2026. This proves missing recent records in this table, not whether an external/manual experiment happened elsewhere. |
| Milestone detection is unreliable | `compute_performance` uses `n % 25 == 0`: 24 -> 26 skips a milestone, and an unchanged 25 repeats it. A durable checkpoint is required before this can drive jobs. |
| Discord is outbound notification | `runtime/alerts.py` POSTs a webhook. It has no incoming research-task consumer. Existing telemetry persistence can drop failed batches, so `agent_messages` must not serve as the durable job queue. |
| Existing manual replay has narrower scope | `/learning/rule_replay` calls `learning.rule_replay.replay`/`replay_sweep` for crypto exit variants with fixed recorded entries and cost/ambiguity diagnostics. This is useful existing infrastructure, not a general strategy inventor or automatic promotion loop. |
| Comparing strategies loses failed trials | The dashboard comparison route persists the winner only and does not inspect the returned persistence error. Averaging stored winners cannot support independent evaluation. |
| Backtest selection crossed book boundaries | `pattern_detection._backtest_history` used a service-role global query and shared cache. The local fix scopes both query and cache to the active book and exercises the real scanner tick/selector in tests. |
| Recorded P&L has mixed meanings | Internal full closes subtract fees; external closes do not consistently do so. Internal partial-exit fees can be deducted again at final close. A blanket subtraction of `fees_usd` would also double-charge some rows. |
| Position rows are not independent trades | External partials create closed slices; internal partials use different recording paths. Some outcomes refer to an original position rather than its closed slice, and the recorder has no unique execution-event key. Multiple outcomes per position are not automatically duplicates. |
| Broker labels do not certify execution prices | The partial-profit monitor can record a quote immediately after submitting an order, before receipt of its actual fill. Adoption and historical correction records also require distinct provenance. |
| Account return lacks necessary inputs | Account resets retain older closed rows while overwriting starting capital. No complete marked-equity history and external cash-flow ledger was found. Account counters and closed-row sums require reconciliation of periods, resets, corrections and partials. |

Private account amounts, identifiers and raw database extracts are deliberately absent from this repository document. [audit_learning_evidence.sql](../../agents/scripts/audit_learning_evidence.sql) reproduces the read-only diagnostic as one SQL statement. It labels returns unverified and never repairs records. Its output is private account data and should not be committed to a public repository.

## Establish trustworthy percentages first

Create an append-only realization/event ledger from confirmed fills, fees, assignment/expiry events, deposits, withdrawals, resets and internal allocations. Use immutable execution IDs and idempotent processing. Record gross P&L, allocated entry fees, exit fees and net P&L explicitly. Keep modeled fills and unverified legacy records identifiable. Reconcile historical discrepancies against receipts; do not invent balancing entries.

Capture per-book broker equity and cash at a stated valuation time, including open positions and liabilities. Record external cash flows with timestamps and reset epochs. Compute account returns from comparable valuation intervals, adjusting for external flows; use time-weighted returns when measuring strategy/manager performance across contributions and an appropriate money-weighted measure for the user's cash-flow experience. Report return method and coverage. An internal movement within one portfolio is neither investment gain nor an external contribution to that portfolio.

Show separate metrics: recorded closed-row win rate, complete trade-lifecycle net expectancy, net account return, marked-equity drawdown, costs, and income available under the owner's reserve policy. Missing history must remain unknown. Never replace missing broker truth with a zero balance or positive eligibility result.

Alpaca paper fills are simulations and omit effects including latency slippage, market impact and some costs; paper success is not proof of achievable live income. [Alpaca paper-trading specification](https://docs.alpaca.markets/us/docs/paper-trading).

## Build the durable research loop

Use a dedicated queue and result store, separate from both `agent_messages` telemetry and `ops_tasks` deployment authority. The local pilot uses SQLite tables for jobs, candidates, trials and events; the broader multi-host design below will need centralized storage. No Supabase migrations were applied.

Use model calls selectively for hypothesis generation or revision. Run numerical backtests, validation, metric computation, queue handling and policy checks as deterministic Python/database operations. Reuse dataset snapshots, cache identical experiments by content hash, deduplicate triggers and cap trials, tokens and compute per book. Do not create an LLM-to-LLM conversation for every job transition, and do not send a report to Discord just so another agent can read it back. Existing human-facing operational alerts can remain independently enabled; Discord is not part of the research control path.

| Component | Required record and behavior |
| --- | --- |
| Research trigger | Per-book scheduled exploration, a crossed durable review milestone, or qualified deterioration/news evidence. Store trigger ID and evidence, with cooldowns and budget checks. |
| `research_jobs` | Unique book/trigger/candidate key; frozen dataset window and hash; status queued/running/completed/failed/blocked; attempt count, lease, heartbeat and retry limit. Atomically claim jobs. A missing evaluator leaves a visible blocked job. |
| `strategy_candidates` | Immutable version/hash, parent, hypothesis, deterministic rules, approved feature IDs, applicable instruments/regimes, and the owner's risk-policy reference. |
| Experiment worker | Run bounded experiments against immutable data without production trading secrets. Retain every attempted variant, failure and rejection. Call the evaluator directly; do not wait for Discord. |
| `research_trials` | Dataset and cost versions, parameters, training/validation/locked-holdout windows, all results, uncertainty, baseline comparisons and trial lineage. Write the result before emitting a notification. |
| Independent evaluator | Recompute acceptance from trusted results under a policy frozen before testing. LLM self-approval is insufficient. Data failure, failed holdout or exceeded cost/risk limits cannot pass. |
| Paper controller | Use eligible versions only after forward-paper evidence; keep the incumbent for comparison. Preserve each open position's original exit policy, and suspend a deteriorating version under predeclared rules. |
| Notification outbox | Notify dashboard/Discord of durable state changes. A delivery failure retries notification without rerunning the experiment or changing its result. |

Start candidate generation with combinations of reviewed indicators, entry conditions, exits and regime filters. Validate a restricted declarative contract. Arbitrary generated Python must not execute inside the order process. Truly new executable primitives require isolated testing and review before they enter the approved feature catalog.

Retests must use chronological information, realistic decision-to-fill timing, fees/spreads/slippage, gaps, liquidity and actual account-size constraints. The existing general backtester still needs these repairs before it can qualify candidates. Multiple testing creates selection bias, so preserve losing trials, budget the search and require locked forward evidence. [Bailey et al., backtest-overfitting research](https://scholarworks.wmich.edu/math_pubs/42/).

News/social data must carry source, publication time, first-observed time and revisions. Treat their text as untrusted data. Seasonality and news response are hypotheses to test, not permissions to change account limits. Models trained on later events can leak hindsight even when their prompt contains only older news; genuinely forward evaluation remains necessary.

## What new-strategy artifacts should look like

A strategy need not create a new Python folder. Its authoritative candidate, trial and transition records should live durably in the database with scoped access. Provide downloadable versioned artifacts for inspection, for example:

| Proposed artifact | Contents |
| --- | --- |
| `candidate.json` | Immutable rules, feature references, hypothesis, parent/version and hash. |
| `dataset_manifest.json` | Instruments, timestamps, source versions, permissible history and hash. |
| `trials.jsonl` | All attempted parameters and results, including failed tests. |
| `evaluation.json` | Frozen policy, measured results, uncertainty and acceptance/rejection reasons. |
| `transitions.jsonl` | Proposed, testing, rejected, shadow, eligible, active-paper or quarantined events. |

These filenames illustrate the future output contract; they are not claims that a generator has created or deployed strategies. The dashboard should expose what is testing, the last successful test, why an idea failed, research costs and the exact active version. A system which only posts market commentary is not satisfying this requirement.

## Implemented single-engine research pilot

The real call path is `StrategyDiscoveryAgent.tick` -> `research.bridge.research_for_book` -> `research.cycle.run_cycle`, run in a background thread. This path does not wait for a review alert, a Discord message, Mem0, or an LLM response. It explores one current-equity case or at most two fixed scenarios per book, one configured stock/crypto symbol and four candidates per cycle. Repeated ticks reuse the first persisted dataset and capital snapshot for that daily scope. Fixed scenarios retain their original capital-based identity; current-equity cycles also identify the broker account and capital source, while allowing the amount to change between daily cycles.

The proposer combines an above-trend condition with a breakout or pullback-recovery entry. It tests the two seeds, chooses a parent using training results only, and creates two bounded parameter refinements. A later cycle can carry forward a previous candidate selected only on training evidence; candidate definitions retain parent IDs. This is deterministic rule composition within a small grammar, not arbitrary new Python or an LLM inventing unrestricted indicators.

Replay uses the next bar's open after a signal, per-leg commission and slippage, gap-aware stops, capped fractional position allocation, cash and marked end-of-bar equity. It uses a chronological 70/30 training/validation split. Every candidate remains rejected or a preliminary `shadow_candidate`; neither state can reach order execution. The three-trade minimum is only a coarse research screen, not statistical proof. There is no multiple-search confidence correction, partial-fill/liquidity model, broker eligibility check, intrabar drawdown estimate or actual forward test. Fixed platform costs default to zero unless supplied to the core API; they remain a required planning consideration.

The SQLite journal atomically claims work with a lease and three-attempt limit. Inputs, candidate specs, trial results and events are immutable through its API. Successful results are exported atomically to `agents/local_state/research_artifacts/<hashed-book>/<hashed-job>.json` by default, with all trials in the job file. `agents/local_state/research.sqlite3` is the default journal. Both are private runtime state excluded from git and must be backed up on the engine host. These local files are not automatically synchronized to Supabase, and the pilot must not be deployed on multiple hosts for the same books without centralized coordination.

Configuration fields are in `agents/app/config.py`. Mike authorized deployment and activation on September 8. The versioned defaults now enable research for SPY/stock with `broker_equity`, a 2 bps commission estimate and a 5 bps slippage estimate per leg. These are initial research assumptions, not measured broker costs; they do not certify profitability. Existing environment overrides remain authoritative. Use `TREZO_RESEARCH_ENABLED=false` to disable the pilot; configure `TREZO_RESEARCH_COMMISSION_BPS` and `TREZO_RESEARCH_SLIPPAGE_BPS` within 0–200 bps per leg as better execution evidence becomes available. Explicit missing costs still produce a visible blocked result. Use `TREZO_RESEARCH_CAPITAL_MODE=fixed_scenario` for the original `TREZO_RESEARCH_CAPITALS=1000,5000` experiments. An optional `TREZO_RESEARCH_DB_PATH` changes the journal location. Historical data requests use existing adapters; the pilot itself makes zero LLM/Mem0 calls. Data and broker reads can still have provider quotas or costs. The adapter discards unfinished daily bars and blocks stale/insufficient data.

For an offline run from `agents/`, use `python -m app.research --help`, then supply an OHLC JSON file, journal path, book, symbol, capital and explicit costs. The CLI is the same core used by the discovery binding. Offline synthetic-data runs verified two successive cycles, eight retained trials and cross-cycle parent continuation; those results demonstrate software behavior, not market profitability.

For the authorized deployment, discovery requests its first scheduled tick 30 seconds after startup, then retains its hourly cadence. This uses the same scheduler job with the existing enabled check, single-instance limit and coalescing. Other agents keep their existing startup timing. The daily research journal still prevents a restart or repeat tick from creating duplicate experiments. A disabled discovery agent or environment override remains authoritative. Verify a new `engine_boot` with the release commit, followed by per-book `internal_research` receipts; queue completion alone does not prove either.

## Variable capital as an account changes

Mike requested that the formulas adapt as the account balance changes. Original starting deposits, current equity, available buying power and investment return are different inputs:

| Input | Treatment |
| --- | --- |
| Original deposits and later cash flows | Preserve as historical accounting events. A deposit raises capital but is not strategy profit. |
| Current equity | Take a fresh, explicitly bound paper-broker account snapshot for the next daily research cycle. Accept increases and decreases; never assume growth. |
| Available trading funds | Keep existing broker buying-power, collateral, reserved-cash and account-policy limits in the execution path. Equity is not automatically spendable cash. |
| Experiment capital | Freeze the actual amount and source used by each experiment. A later balance change must not rewrite its results or restart it repeatedly during the same day. |

`research.capital.read_capital_snapshot` binds the exact book, verifies the actual transport's paper endpoint and credential route before a read, and requires positive finite USD equity, finite cash, an active account and a broker identity. The receipt stores a hashed broker identity and observation time, not raw credentials or account numbers. Unknown books, timeouts, failed reads, invalid numbers and unsupported account states block current-equity research. There is no fallback to another account, the initial deposit, cash-plus-vault or imagined returns. This pilot supports the registered Alpaca paper env-key accounts; other providers, OAuth-only books and a consolidated internal/broker NAV require separate verified adapters.

The route check matters even with a valid context binding: the existing transport ignores registry bindings in single-account mode. If only a secondary slot is enabled but the transport would send primary credentials, research now refuses the mismatch. The execution routing implementation is unchanged.

The first successful daily job freezes its equity and dataset. Later ticks expose a separately labeled `latest_capital_snapshot` while returning the original experiment's `starting_capital` and `capital_snapshot`. A new daily cycle uses the new equity and may carry forward the previous training-selected candidate, then retests it at that amount. A capital change does not create a new strategy version by itself, reset learning, prove better performance, increase risk percentages or permit promotion. Changing the broker identity, cost policy or capital mode separates research lineage. Fixed scenarios remain independent from current-equity research.

Within a replay window, position budgets already use a fraction of remaining simulated cash and therefore respond to realized gains and losses. These remain standalone historical capacity experiments initialized with current equity; they do not reconstruct the owner's actual account history or assume the historical result will recur. The current replay has no order-book liquidity model, so it cannot establish that a strategy retains its edge as account size grows.

The actual stock/crypto execution paths already call `plan_position` with broker equity; Wheel limits also use account snapshots. Existing dollar allocation overrides remain fixed until the owner changes them. Internal modeled cash-plus-vault paths are not marked NAV, and the previously identified P&L reconciliation gaps remain open. [Alpaca account equity and buying-power definitions](https://docs.alpaca.markets/us/docs/account-plans).

## Memory and Market Desk: distinct responsibilities

The code has three distinct mechanisms: transient `AgentMessage` communication; `Agent.remember/recall` backed by Supabase `agent_memory`; and optional semantic lessons/search through `memory/mem0_client.py`. The Supabase store is not an automatic fallback for a failed Mem0 call. Market Desk reads ingested `market_context` records from `relay_briefings`, applies a 24-hour freshness policy, and exposes a process-local `MarketView`; it does not call Mem0 or generically ingest every agent's memories.

Read-only inspection found Supabase memory being updated, but the newest stored Market Desk market-context ingestion was August 28. Recent `learning_context` receipts showed zero recalled decisions/outcomes even when `available` was true. That flag previously established SDK initialization, not a successful service read. Missing configuration, exhausted budgets, request failures, restrictive local filtering and genuine zero matches require distinct diagnoses. The running server's SDK version, key validity and successful Mem0 write/search receipts remain unverified.

The local diagnostics fix returns one `RecallResult` per search, distinguishing `ok`, `ok_empty`, `client_unavailable`, `budget_blocked` and `request_failed`. It preserves the legacy list-returning API while wiring the actual learning-context helper to `retrieval_succeeded`, `retrieval_state`, per-query receipts and the last known same-query success time. Cache hits retain the original successful read's timestamp. The existing `available` flag remains initialization-only for compatibility. These diagnostics do not establish a successful deployed Mem0 connection and do not add a new Market Desk memory consumer.

After deployment, verify the deployed SDK and query contract, retain a write receipt for a known lesson, and retrieve that lesson through the real consuming agent with its book, strategy and evidence provenance intact. Confirm both relevant and irrelevant queries, request failures and budget exhaustion appear correctly in durable logs. Repair the producer of fresh `relay_briefings` separately, then demonstrate that Market Desk exposes that fresh context to its real consumers. A successful semantic search alone cannot satisfy the Desk acceptance check.

Mem0's documented search uses `top_k`, whereas this code calls `limit`, and its dependency is unpinned. Treat this as a compatibility question to validate against the deployed SDK before changing arguments. Separately, fixed global user scope, local post-filtering and missing book/strategy/provenance filters need repair before account-specific learning can be trusted. Simulated outcomes must not be silently merged with broker-paper evidence. [Mem0 search API](https://docs.mem0.ai/api-reference/memory/search-memories), [entity scoping](https://docs.mem0.ai/platform/features/entity-scoped-memory).

Keep immutable experiment and accounting records in their authoritative store; use semantic memory for compact lessons pointing to those records. Mem0 retrieval does not prove a research job ran, a strategy passed evaluation, or a report reached Market Desk. Notion can provide a human-readable research notebook, but it does not replace the proposed transactional journal. No memory-vendor switch is needed to run this pilot. If the suggested Memrise means memrise.com, it is a language-learning product; the intended Graphify product needs its exact URL before comparison. [How Mem0 works](https://docs.mem0.ai/core-concepts/how-it-works), [Notion API](https://developers.notion.com/reference/intro), [Memrise](https://www.memrise.com/).

## Internal reinvestment design

This is a proposed first implementation for the separate allocation requirement, not the meaning of Mike's "internal" clarification or a selected substitute for a real child/brokerage account.

Keep funds at the broker and represent strategy capital, reserves and income allocations in an internal ledger. Each allocation has an owner, parent broker-book key, policy and balance; sibling books never inherit another book's halts or risk settings. The owner's combined view is reporting, not shared execution authority.

Use atomic balanced postings and immutable allocation IDs. Moving $100 from available profit to a reserve debits one allocation and credits another; total account equity stays unchanged. Replaying that event must not move another $100. Assign every position, fee and reserved order commitment to an allocation so the same cash or collateral cannot support two strategies.

The agent may propose reinvestment within an owner-approved policy. Available allocation capacity must reconcile to broker buying power/settled cash as applicable, pending commitments, collateral, prior losses and reserve floors. Winning trade proceeds, deposits, unrealized gains and already allocated profits are not automatically fresh distributable profit. If the reconciled surplus is unknown or nonpositive, no profit allocation occurs.

Existing KINDRIP is not this ledger: it writes modeled child balances and draft payment messages through separate, sometimes swallowed database writes. It also models an unverified seed contribution. Do not reuse that behavior for genuine income reporting or an external transfer. A virtual subaccount is not a legal minor's custodial account; the latter has different ownership and account-opening requirements. [Example custodial-account terms](https://www.schwab.com/custodial-account).

For a future customer product, broker-held assets and minimized credentials do not settle Trezo's legal role. Automated discretionary management can raise investment-adviser duties; transfer authority can separately create custody obligations. Determine the business model and exact broker permissions with qualified counsel before customer launch. Internal allocations do not themselves transfer money externally. [SEC robo-adviser guidance](https://www.sec.gov/investment/im-guidance-2017-02.pdf), [SEC custody guidance](https://www.sec.gov/investment/im-guidance-2017-01.pdf).

## Observable acceptance gates

Local verification completed September 8: `python -m tests.run_all` passed all 71 suites with zero activity-log writes under the harness's network guard; `python -m pytest -q` passed 1,065 tests. This includes 62 new tests for per-book backtest selection, the research cycle and actual discovery binding, history-read completeness, Mem0 diagnostics and dynamic capital, plus startup scheduling. Four scheduling tests verify the first research tick, hourly repetition, enabled checks and invalid-delay handling. The 17 dynamic-capital tests cover strict routing, failed reads, immutable daily balances, subsequent gains/losses, preserved lineage and fixed-scenario compatibility. The real discovery-path test retained 24 synthetic trials across two books and three daily cycles without an order or ledger mutation. Earlier synthetic CLI runs verified two successive cycles and eight trials. These tests establish local behavior; they do not verify a deployed process, vendor connectivity, market profitability or the broader gates below.

1. A seeded qualifying report reaches a durable, correctly scoped research job through the real discovery tick. Crossing a milestone queues it once; repeated ticks and restarts do not duplicate it.
2. A worker claims and completes a job, preserves all variants and resumes safely after a crash. Discord failure cannot lose the result or block later jobs.
3. Malformed candidates, stale/missing data, unaffordable costs, failed validation and failed forward evidence cannot activate a strategy. Research cannot change broker credentials, permissions or risk envelopes.
4. An eligible version reaches the actual paper selector and order path under the correct book; another book's evidence or failure does not alter it. Open-position exits remain attached to their origin version.
5. Every fee is charged once; partials conserve quantity and lifecycle P&L; duplicate fill/allocation events have no second financial effect. Account returns exclude deposits and internal reallocations as gains.
6. Audit counts, costs, freshness and eligibility are visible in the dashboard and durable records. Real deployment requires the deployed SHA, process and observed behavior to be verified, not just green offline tests.

Build in this order: reconciled evidence and reporting; durable jobs plus faithful replay; candidate generation and independent testing; forward-paper promotion and decay handling; internal allocation policies. Research construction can proceed alongside accounting repair, but unresolved accounting cannot certify profitability or activate a new strategy.
