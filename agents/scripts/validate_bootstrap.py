"""Bootstrap import / registration validator (Task #31 companion).

Mike's 2026-06-03 silence: agents service returned `registered: 0
agents` from /agents even though /health was OK. That means
bootstrap_agents() failed silently somewhere — most likely an
ImportError in one of the agent modules or runtime helpers.

Run: `python -m scripts.validate_bootstrap` from agents venv.

This script:
  1. Imports each agent class one at a time and reports per-class
     success/failure with full traceback.
  2. Calls bootstrap_agents() in isolation and reports the registry
     count + any exception raised.
  3. Lists what the registry says vs what we expect.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def hr(): print("-" * 72)
def head(s):
    print()
    print("=" * 72)
    print(f"  {s}")
    print("=" * 72)


AGENT_IMPORTS = [
    ("app.agents.adaptive_scope",    "AdaptiveScopeAgent"),
    ("app.agents.crypto_scanner",    "CryptoScannerAgent"),
    ("app.agents.cycle_awareness",   "CycleAwarenessAgent"),
    ("app.agents.exit_advisor",      "ExitAdvisorAgent"),
    ("app.agents.exit_advisor_options", "ExitAdvisorOptionsAgent"),
    ("app.agents.dividend_manager",  "DividendManagerAgent"),
    ("app.agents.extended_scanner",  "ExtendedScannerAgent"),
    ("app.agents.kindrip_agent",     "KindripAgent"),
    ("app.agents.market_horizon",    "MarketHorizonAgent"),
    ("app.agents.market_sentiment",  "MarketSentimentAgent"),
    ("app.agents.options_scanner",   "OptionsScannerAgent"),
    ("app.agents.ops_watchdog",      "OpsWatchdogAgent"),
    ("app.agents.orb_scanner",       "ORBScannerAgent"),
    ("app.agents.pattern_detection", "PatternDetectionAgent"),
    ("app.agents.position_monitor",  "PositionMonitorAgent"),
    ("app.agents.research",          "ResearchAgent"),
    ("app.agents.risk_manager",      "RiskManagerAgent"),
    ("app.agents.stms_scanner",      "STMSScannerAgent"),
    ("app.agents.strategy_discovery","StrategyDiscoveryAgent"),
    ("app.agents.tax_optimizer",     "TaxOptimizerAgent"),
    ("app.agents.trade_execution",   "TradeExecutionAgent"),
    ("app.agents.user_support",      "UserSupportAgent"),
]


def main() -> int:
    head("1. Import every agent class one-by-one")
    print()
    failures = []
    for module_path, class_name in AGENT_IMPORTS:
        try:
            mod = __import__(module_path, fromlist=[class_name])
            cls = getattr(mod, class_name)
            print(f"  ✓  {module_path:36s}.{class_name}")
        except Exception as e:
            print(f"  ✗  {module_path:36s}.{class_name}")
            print(f"     {type(e).__name__}: {e}")
            failures.append((module_path, class_name, e))

    if failures:
        head("FIRST IMPORT FAILURE — FULL TRACEBACK")
        m, c, e = failures[0]
        print(f"  importing {m}.{c}:")
        print()
        try:
            __import__(m, fromlist=[c])
        except Exception:
            traceback.print_exc()
        print()
        print(f"  *** This import error is almost certainly why bootstrap_agents()")
        print(f"  *** returns 0 registered agents in production.")
        return 1

    head("2. Run bootstrap_agents() in isolation")
    try:
        from app.runtime.bootstrap import bootstrap_agents
        from app.runtime.registry import registry
        bootstrap_agents()
        agents = registry.all()
        print(f"  ✓ bootstrap_agents() completed without raising.")
        print(f"  registered count: {len(agents)}")
        for state in agents:
            print(f"    - {state.name} (role={state.role}, enabled={state.enabled})")
    except Exception:
        print("  ✗ bootstrap_agents() RAISED:")
        traceback.print_exc()
        return 1

    head("3. Cross-check against expected list")
    try:
        from app.agents.ops_watchdog import EXPECTED_AGENTS
        registered = {s.name for s in registry.all()}
        expected = {n for n, _ in EXPECTED_AGENTS}
        missing = expected - registered
        extra = registered - expected
        print(f"  registered: {len(registered)} | expected: {len(expected)}")
        if missing:
            print(f"  ⚠ MISSING: {sorted(missing)}")
        if extra:
            print(f"  ℹ extra:   {sorted(extra)}")
        if not missing and not extra:
            print("  ✓ all expected agents are registered.")
    except Exception as e:
        print(f"  ✗ cross-check failed: {e}")

    print()
    print("DONE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
