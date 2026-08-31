"""Wires the agents into the registry and connects the bus.

Called once at FastAPI startup. Idempotent.
"""

from __future__ import annotations

import structlog

from app.agents.base import AgentMessage
from app.agents.adaptive_scope import AdaptiveScopeAgent
from app.agents.crypto_scanner import CryptoScannerAgent
from app.agents.cycle_awareness import CycleAwarenessAgent
from app.agents.exit_advisor import ExitAdvisorAgent
from app.agents.exit_advisor_options import ExitAdvisorOptionsAgent
from app.agents.archivist import ArchivistAgent
from app.agents.book_health import BookHealthAgent
from app.agents.ops_watchdog import OpsWatchdogAgent
from app.agents.portfolio_architect import PortfolioArchitectAgent
from app.agents.market_desk import MarketDeskAgent
from app.agents.relay_ingest import RelayIngestAgent
from app.agents.dividend_manager import DividendManagerAgent
from app.agents.dividend_lt_agent import DividendLTAgent
from app.agents.broker_truth_agent import BrokerTruthAgent
from app.agents.extended_scanner import ExtendedScannerAgent
from app.agents.kindrip_agent import KindripAgent
from app.agents.market_horizon import MarketHorizonAgent
from app.agents.market_sentiment import MarketSentimentAgent
from app.agents.options_scanner import OptionsScannerAgent
from app.agents.orb_scanner import ORBScannerAgent
from app.agents.pattern_detection import PatternDetectionAgent
from app.agents.position_monitor import PositionMonitorAgent
from app.agents.research import ResearchAgent
from app.agents.risk_manager import RiskManagerAgent
from app.agents.stms_scanner import STMSScannerAgent
from app.agents.strategy_discovery import StrategyDiscoveryAgent
from app.agents.tax_optimizer import TaxOptimizerAgent
from app.agents.trade_execution import TradeExecutionAgent
from app.agents.forex_scanner import ForexScannerAgent
from app.agents.user_support import UserSupportAgent

from .bus import bus
from .registry import registry


log = structlog.get_logger("trezo.bootstrap")


def bootstrap_agents() -> None:
    if registry.all():
        return  # already bootstrapped

    pattern   = PatternDetectionAgent()
    stms      = STMSScannerAgent()
    orb       = ORBScannerAgent()
    extended  = ExtendedScannerAgent()
    crypto    = CryptoScannerAgent()
    forex_scanner = ForexScannerAgent()
    options   = OptionsScannerAgent()
    risk      = RiskManagerAgent()
    execution = TradeExecutionAgent()
    monitor   = PositionMonitorAgent()
    tax       = TaxOptimizerAgent()
    kindrip   = KindripAgent()
    sentiment = MarketSentimentAgent()
    research  = ResearchAgent()
    adaptive  = AdaptiveScopeAgent()
    support   = UserSupportAgent()
    discovery = StrategyDiscoveryAgent()
    dividend  = DividendManagerAgent()
    dividend_lt = DividendLTAgent()
    broker_truth = BrokerTruthAgent()
    horizon   = MarketHorizonAgent()
    cycles    = CycleAwarenessAgent()
    exit_adv  = ExitAdvisorAgent()
    exit_opts = ExitAdvisorOptionsAgent()
    watchdog  = OpsWatchdogAgent()
    bookhealth = BookHealthAgent()
    archivist  = ArchivistAgent()
    architect = PortfolioArchitectAgent()
    relay_in  = RelayIngestAgent()
    mkt_desk  = MarketDeskAgent()

    registry.register(pattern,   "Detects candlestick patterns and scores trade confidence (0-1000).",                  role="observer")
    registry.register(stms,      "Small-cap momentum scanner. Active 7-11 AM ET. Looks for $1-$20 stocks up 10%+ on 5x volume with TCS 750+.", role="observer")
    registry.register(orb,       "Opening Range Breakout scanner. Active 8:30 AM-12:00 PM ET. Trades confirmed breakouts of the first 5-minute range (best size 8:30-10:30, reduced 10:30-12:00).", role="observer")
    registry.register(extended,  "Extended Strategy scanner (Layer 4). The multi-day swing layer - EMA50 pullbacks, breakout holds, earnings-gap continuations, stair-steppers.", role="observer")
    registry.register(crypto,    "24/7 crypto scanner for XRP/ETH/SOL. Detects SCALP / SWING / DCA modes from RSI, Bollinger width and volume.", role="observer")
    registry.register(forex_scanner, "Forex scanner (Task #77). Watches major pairs (EUR/USD, USD/JPY, GBP/USD, USD/CHF, AUD/USD). Data source IS wired (Kraken OHLC) and the scanner defaults ON, but the lane is DORMANT while broker-only mode is set without TREZO_FOREX_MODELED_OK -- Alpaca has no FX venue, so Risk Manager would veto every signal. It skips the scan rather than manufacturing guaranteed vetoes.", role="observer")
    registry.register(options,   "Runs the Dividend Wheel (cash-secured puts) and surfaces options-strategy ideas. Pricing is modeled (Black-Scholes).", role="actor")
    registry.register(risk,      "Highest-authority gatekeeper. Approves or vetoes every signal; enforces Adaptive Scope, kill-switches and market filters.", role="observer")
    registry.register(architect, "Portfolio Architect. Daily structural review using the library work: does each lane have a measurable edge (bootstrap), what bet size does that evidence support (optimal f), how should capital split across the lanes that qualify (hierarchical risk parity), and has the market changed underneath them (CUSUM structural break). Proposes only -- never changes a rule.", role="observer")
    registry.register(execution, "Routes approved signals - stock trades to Alpaca paper, crypto to the internal paper engine.", role="actor")
    registry.register(monitor,   "Watches every open position. Closes on stop/target, runs day-trade management, reconciles Alpaca fills.", role="actor")
    registry.register(tax,       "Tracks tax impact of every executed trade in real time.",                             role="observer")
    registry.register(kindrip,   "KINDRIP (Layer 7). Runs scheduled contributions into children's Future Index Accounts and auto-invests them.", role="actor")
    registry.register(sentiment, "Pulls company news across the watchlist, scores sentiment, and flags material events (earnings, M&A, guidance, legal).", role="observer")
    registry.register(research,  "Watches the earnings and ex-dividend calendar and warns ahead of upcoming events.",   role="observer")
    registry.register(adaptive,  "Reads the market regime and breaking news, then adjusts strategy scope within guardrails.", role="observer")
    registry.register(support,   "Answers the user's questions about decisions, blocked trades, and outcomes.",         role="observer")
    registry.register(discovery, "Computes win/loss performance metrics and flags a review every 25 trades.",          role="observer")
    registry.register(dividend,  "Dividend Manager. Credits modeled distributions on dividend holdings and reinvests them (DRIP) so positions compound.", role="actor")
    registry.register(dividend_lt, "Dividends (Long-Term) lane (2026-08-22). Every 30 min sizes the lane from each book's income pocket, screens the MARKET-WIDE pool through the spec's entry screen (payout ratio, raise streak, cut history) rather than a curated list, and proposes ladder entries under the per-name concentration cap. Signals only -- Risk Manager still judges every one. Never writes covered calls: GROWTH-tier names are held for their payout growth, not called away.", role="observer")
    registry.register(broker_truth, "Broker Truth (2026-08-23). Every 15 min asks Alpaca what option positions it ACTUALLY holds and makes the ledger agree. Closes only the unambiguous case -- expired, settled out of the money, nothing to move -- and loudly flags everything else: a live contract missing at the broker is a routing incident, an expired ITM one is an assignment, and neither gets guessed at. Written after four short puts expired 8/21 and sat open all weekend, holding collateral hostage on two books.", role="observer")
    registry.register(horizon,   "Market Horizon. Every 15 min reads the whole landscape - stocks, crypto, gold, USD, bonds, income ETFs - and notes who leads and whether the classic cross-asset relationships still hold.", role="observer")
    registry.register(cycles,    "Cycle Awareness (Phase 13). Every 6h reads upcoming earnings + ex-dividend dates per watchlist ticker; tags signals with cycle context so the bot picks strategies around the rhythm pros watch (IV crush, dividend capture).", role="observer")
    registry.register(exit_adv,  "Exit Advisor (Phase 13d). Every 5 min watches every open position for the held-too-long pattern - tracks the running peak unrealized P&L and raises a dashboard alert when the position gives back 30%+ of its peak gain. Never closes a trade; surfaces suggestions for the user to act on.", role="observer")
    registry.register(exit_opts, "Exit Advisor - Options edition (Phase B). Every 5 min watches open option positions and applies Mike's rules: contract-count drives target (1-10 -> 30-50%, >10 -> 15%), drawback ladder (39/30/25%), catalyst-aware urgency bump. Never closes; surfaces alerts.", role="observer")
    registry.register(watchdog,  "Operations Watchdog (Task #31, 21st agent). Every 5 min checks the runtime registry vs the expected-agent list and the last-tick time of every registered agent. Raises ops_health_alerts when an agent is missing or has gone silent during market hours.", role="observer")
    registry.register(bookhealth, "Book integrity monitor (2026-08-18). Every 5 min asks one question per book: does it add up? Alarms on UNMANAGED NOTIONAL (broker holds it, the ledger has no row -- nothing is stopping it), positions sitting past their own stop, and a halt whose condition has already cleared. Sends OUT through the alert webhook rather than into a table nobody reads.", role="observer")
    registry.register(relay_in,  "Relay Ingest (2026-08-21). Every 5 min drains Nova's skill briefings (relay_briefings: market context, daily wrap, health verdicts), validates each against its schema, files it into shared agent memory separated by kind, and announces it. Context only -- never emits events, never changes scope/posture/sizing. A brief that doesn't fit is rejected with the reason, never dropped.", role="observer")
    registry.register(mkt_desk,  "Market Desk (2026-08-25, Mike: 'an agent that can go through the reports and process for each agent'). Every 5 min digests the newest market_context briefing -- regime, indices, vix, breadth, movers, catalysts -- into ONE MarketView served via current_market_view(). Consumers may only TIGHTEN on it; a missing or stale report is 'no opinion' and leaves every lane untouched. Holds no opinions, moves no levers.", role="observer")
    registry.register(archivist, "Archivist (2026-08-18). Hourly: activity logs, runtime caches and a point-in-time copy of every book to Supabase Storage. Weekly: the same bundle to Dropbox, a deliberately different vendor. Nothing should exist only on the server -- then the server is disposable and you rebuild rather than restore.", role="observer")

    # Wire on_message handlers - agents react to each other's messages.
    #
    # A HANDLER CRASH USED TO BE INVISIBLE (2026-08-31, the four-day
    # approval outage). This except logged to stdout and continued, so
    # when risk_manager.on_message raised UnboundLocalError on every
    # actionable signal, the platform stopped trading for four days with
    # no bus message, no activity row and no alert -- the log just looked
    # quiet. A swallowed exception in the message path is now announced:
    # onto the bus (so it lands in agent_messages and the dashboard),
    # into the activity log, and -- first time per agent+error -- out
    # through the alert webhook.
    _handler_fail_seen: dict[tuple[str, str], int] = {}

    async def _route(message):
        # Don't loop back into the same agent's own messages
        for state in registry.all():
            if state.impl is None or state.impl.name == message.agent or not state.enabled:
                continue
            try:
                follow_ups = await state.impl.on_message(message)
            except Exception as e:  # noqa: BLE001
                log.error("agent.on_message.failed", agent=state.name, error=str(e))
                await _announce_handler_failure(state, message, e)
                continue
            for m in follow_ups or []:
                state.message_count += 1
                await bus.publish(m)

    async def _announce_handler_failure(state, message, exc):
        """Make a swallowed handler exception impossible to miss.

        Everything here is best-effort and must never raise: the router
        is the platform's spine, and a reporting bug cannot be allowed
        to become a second outage.
        """
        try:
            _payload_in = message.payload if isinstance(message.payload, dict) else {}
            _key = (str(state.name), f"{type(exc).__name__}: {str(exc)[:80]}")
            _n = _handler_fail_seen.get(_key, 0) + 1
            _handler_fail_seen[_key] = _n
            _note = (
                f"{state.name}.on_message raised "
                f"{type(exc).__name__}: {str(exc)[:160]} while handling a "
                f"'{message.kind}' from {message.agent} "
                f"(ticker {_payload_in.get('ticker') or '-'}). "
                f"The message was DROPPED -- whatever this handler does "
                f"for that message is not happening."
            )
            # 1. The bus. NOTE the agent name: this message is published
            #    AS the failing agent so _route skips that agent when it
            #    routes this one -- a handler that crashes on everything
            #    cannot crash on its own failure report and loop.
            try:
                await bus.publish(AgentMessage(
                    agent=state.name, kind="error",
                    payload={"event": "handler_failed",
                             "agent": state.name,
                             "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                             "trigger_agent": message.agent,
                             "trigger_kind": message.kind,
                             "ticker": _payload_in.get("ticker"),
                             "occurrences": _n,
                             "note": _note}))
            except Exception:  # noqa: BLE001
                pass
            # 2. The activity log (survives a bus/Supabase outage).
            try:
                from app.agents.activity_log import record as _arec
                _arec("handler_failed", str(_payload_in.get("ticker") or "SYSTEM"),
                      strategy=_payload_in.get("strategy"),
                      reason=_note, extra={"agent": state.name,
                                           "occurrences": _n})
            except Exception:  # noqa: BLE001
                pass
            # 3. The webhook, ONCE per agent+error (dedupe key), because
            #    the same crash repeats on every message and nobody needs
            #    a thousand pings -- one is what four days were missing.
            if _n == 1:
                try:
                    from app.runtime.alerts import notify
                    await notify(f"Trezo: {state.name} is dropping messages",
                                 _note, severity="urgent",
                                 key=f"handler_failed:{state.name}")
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            return

    bus.subscribe(_route)

    # Persistence subscriber - every message that crosses the bus is written.
    from .persistence import persist_message

    async def _persist(message):
        user_id = message.payload.get("user_id") if isinstance(message.payload, dict) else None
        await persist_message(message, user_id=user_id)

    bus.subscribe(_persist)

    # Shared capability library -> seed into shared agent memory so every
    # agent is aware of the available risk/exit/profit toolbox (Mike 6/23).
    try:
        from app.runtime.capabilities import seed_shared_capabilities
        import asyncio as _aio
        try:
            _aio.get_running_loop().create_task(seed_shared_capabilities())
        except RuntimeError:
            _aio.run(seed_shared_capabilities())
    except Exception as e:  # noqa: BLE001
        log.warning("capabilities.seed.failed", error=str(e))

    # BOOT BEACON (2026-08-26). Three deploys this week were marked
    # "done" while the OLD process kept running -- the relay's restart
    # handler dies with the service it restarts, and nothing verified
    # that a new process actually came up. The engine ran Tuesday-morning
    # code for two days while every deploy reported success.
    #
    # This line is the proof-of-boot: an activity event stamped with the
    # pid and the EXACT commit the process loaded. The log push carries
    # it to ops_log_tail within minutes, where `relay.py deploy` now
    # polls for it and refuses to claim success without it. A deploy is
    # not done when the restart command returns; it is done when a new
    # process says hello and names the commit it is running.
    try:
        import os as _os
        import subprocess as _sp
        _commit = "unknown"
        try:
            _commit = _sp.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=10,
                cwd=str(__import__("pathlib").Path(__file__).resolve()
                        .parents[2]),
            ).stdout.strip() or "unknown"
        except Exception:  # noqa: BLE001
            pass
        from app.agents.activity_log import record as _arec
        _arec("engine_boot", "SYSTEM",
              reason=(f"engine process started: pid={_os.getpid()} "
                      f"commit={_commit} agents={len(registry.all())}"))
    except Exception as e:  # noqa: BLE001
        log.warning("boot_beacon.failed", error=str(e))

    log.info("agents.bootstrap.complete", count=len(registry.all()))
