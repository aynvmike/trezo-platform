"""Central configuration for the Trezo agents service."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Service
    env: str = "development"
    # Trading mode - "paper" (default) or "live".
    # See runtime/trading_mode.py - live stays inert until Phase 10b.
    trading_mode: str = "paper"
    log_level: str = "INFO"
    port: int = 8001

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # Anthropic
    anthropic_api_key: str = ""

    # Market data
    finnhub_api_key: str = ""
    # Nasdaq Data Link API key for the macro adapter's Nasdaq backend.
    # Free signup at https://data.nasdaq.com. Pulls US Treasury yield
    # curve (public domain, redistribution-clean). Optional - other
    # backends can fill in via TREZO_MACRO_* fields below.
    nasdaq_data_link_api_key: str = ""

    # Twelve Data macro backend - free 800 req/day at twelvedata.com.
    # Provides VIX + treasury yields without FRED's redistribution issues.
    # See agents/app/data/macro/twelve_data.py for setup.
    twelve_data_api_key: str = ""

    # Alpha Vantage macro backend - free 25 req/day at alphavantage.co.
    # Has VIX + treasury yields + Fed Funds directly. Slightly more
    # complete than Twelve Data but tighter rate limit.
    alpha_vantage_api_key: str = ""

    # Capital safety knobs (Task #87, Mike's 2026-06-05 rule):
    # bot must defer to platform settings, never use code constants
    # for trading decisions. These are surfaced as defaults in
    # bot_settings - the user can override via Bot Tuning UI.
    #
    # max_position_pct: per-position concentration cap (% of equity).
    #   Default 0.25 = 25% of equity per trade. Replaces hardcoded
    #   NOTIONAL_CAP_PCT. Low-vol ETFs no longer eat 58% (XLF fix).
    max_position_pct: float = 0.25
    # min_reward_risk_floor: refuse trades below this R:R. Default 1.5.
    # User can tighten or loosen via Bot Tuning.
    min_reward_risk_floor: float = 1.5
    # max_open_signals: max concurrent open approved signals across
    # all strategies. Replaces the Risk Manager class constant.
    max_open_signals: int = 20

    # Task #77 (2026-06-05): forex_enabled toggle. Default off because
    # data source for FX isn't wired yet (scaffold only).
    forex_enabled: bool = False

    # Task #92 (2026-06-10, Mike's rule): Exit Advisor auto-action.
    # Off = surface alerts only (legacy spec). On = bot acts on its own
    # giveback rules: urgent -> close, warn -> trim 50%.
    auto_exit_advisor: bool = False

    # Massive (massive.com) - free tier. Used today as macro backend
    # (stub - Task #84 finishes). Eventual: full data spine for stocks
    # + options + forex + crypto + news + WebSocket (Task #80).
    massive_api_key: str = ""

    # Manual macro backend - Mike types the current values directly.
    # Empty string means "not set" -> picker falls through to next
    # backend (or "unavailable" when nothing is set).
    trezo_macro_vix: str = ""
    trezo_macro_yield_spread: str = ""
    trezo_macro_fed_funds: str = ""

    # Broker - Alpaca paper trading
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = ""
    # Broker - Alpaca LIVE (Phase 10b). Empty until the go-live step;
    # used only when the live executor is enabled and TRADING_MODE=live.
    alpaca_live_api_key: str = ""
    alpaca_live_secret_key: str = ""
    # Account-identity guard (2026-06-16). When set, the startup self-check
    # asserts the live Alpaca account_number matches this value and raises a
    # loud ops alert on mismatch so the bot never silently trades the wrong
    # account. Empty = no pin (just logs whichever account it bound to).
    alpaca_expected_account: str = ""

    # Liquidity floor (2026-06-16). Minimum 20-day average share volume a
    # symbol must clear to be tradable. Tunable via env TREZO_MIN_AVG_VOLUME
    # so Mike can adjust without a code change. Lowered from the old
    # hardcoded 1,000,000 (which vetoed ~all market-wide candidates) to
    # 250,000. Per-strategy lanes in market_filter.py still apply floors.
    min_avg_volume: int = 250_000

    # Experience-driven risk gate (2026-06-16, OPT-IN, default OFF). When
    # true, the risk manager nudges the per-strategy TCS floor from realized
    # outcomes: a proven "favor" strategy trades a bit more freely (-25), a
    # proven "avoid" one needs higher conviction (+75). Bounded + data-gated
    # (>=8 closed trades). Set TREZO_OUTCOME_GATE_TUNING_ENABLED=true to enable.
    outcome_gate_tuning_enabled: bool = False

    # Cache
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    # Encryption
    fernet_encryption_key: str = ""

    # Web tier callback - used by the agents service to POST to
    # /api/cron/refresh-broker-tokens. Both must be set for the
    # refresh-token poller to run; otherwise it logs once and skips.
    trezo_web_base_url: str = ""
    cron_secret: str = ""

    # Mem0 hosted memory layer - the shared brain across agents.
    # See agents/app/memory/ for the wrapper. Empty -> agents run
    # without memory (graceful degradation, never blocks trading).
    mem0_api_key: str = ""
    # Mem0 usage budget (2026-06-12, after the 10k ADD quota burned in
    # under 2 weeks on veto noise). Tunable in agents/.env. Adds are the
    # scarce resource; retrievals get a generous ceiling so the agents
    # can ALWAYS consult their memory before decisions.
    mem0_max_adds_per_day: int = 400      # ~2,800/week
    mem0_max_adds_per_week: int = 2500    # hard weekly stop
    mem0_max_searches_per_day: int = 2000

    # Phase F (2026-06-04): route crypto signals to Alpaca paper
    # crypto when enabled AND the symbol is in the broker allowlist.
    # Default OFF - crypto stays on the internal modeled paper
    # engine, identical to today. Set ALPACA_CRYPTO_ENABLED=true
    # in agents/.env to opt in. To remove entirely, comment out
    # this line (the routing branch in trade_execution.py treats
    # missing flag as False).
    alpaca_crypto_enabled: bool = False

    # Crypto Part 2 (2026-06-13): real crypto-exchange connector
    # (Coinbase / Kraken) for the ISO 20022 coins Alpaca cannot trade.
    # SCAFFOLD + OFF by default. Wired into routing but reports "not
    # configured" until BOTH the flag is on AND a key/secret are set, so
    # nothing can fire by accident. Set in agents/.env once you have an
    # exchange account; Part 3 fills in the REST calls.
    crypto_exchange_enabled: bool = False
    crypto_exchange: str = "coinbase"   # 'coinbase' | 'kraken'
    crypto_exchange_api_key: str = ""
    crypto_exchange_api_secret: str = ""
    # Kraken-specific creds. Mike set Kraken_API_KEY / Kraken_Private_Key in
    # agents/.env; pydantic-settings is case-insensitive so these map to them.
    # The connector prefers the generic crypto_exchange_* pair if set, else
    # falls back to these.
    kraken_api_key: str = ""
    kraken_private_key: str = ""
    # Kraken FUTURES (demo/paper first) - Futures Phase 1 (2026-06-13).
    # SEPARATE demo API key from demo-futures.kraken.com/settings/api (the spot
    # key won't work). Demo by default; live futures is a separate explicit
    # step. Leverage range 1x-10x: default 10x so agent learning is not limited;
    # absolute 10x safety ceiling in code (kraken_futures.LEVERAGE_HARD_CAP).
    kraken_futures_enabled: bool = False
    kraken_futures_demo: bool = True
    kraken_futures_api_key: str = ""
    kraken_futures_api_secret: str = ""
    futures_max_leverage: float = 10.0

    # Task #59 (2026-06-05): skip persistence of 'signal' kind messages.
    # Default True - cuts agent_messages writes by ~90%. Signals still
    # flow on the in-process bus to Risk Manager / Trade Execution; they
    # just don't land in Supabase. Scanners emit a single scanner_pulse
    # summary row per tick (Task #60) so the trace panel still shows
    # what was scanned + how many fired.
    skip_signal_persist: bool = True

    # ---- Phase C options Greek-aware filters --------------------------
    # min_dte: Options Scanner skips emit when expiration is within this
    # many days. Mike's rule 7: avoid long-call recommendations inside
    # 7 DTE unless setup explicitly accounts for theta burn. Default 7.
    options_min_dte: int = 7
    # max_premium_delta: skip premium-sell setups whose |net_delta| is
    # above this. High |delta| premium sells are basically short-stock
    # proxies; not what the Wheel is for. Default 0.45.
    options_max_premium_delta: float = 0.45
    # min_iv_rank_scalp: scalp/short-DTE setups need elevated IV to be
    # worth the theta. Default 30.0 (percentile). 0 disables this filter.
    options_min_iv_rank_scalp: float = 30.0
    # Phase D - hopeful-holds allocation cap. Mike's rule 5: holds a
    # call outside the Wheel maybe 3% of the time. Default 3% (0.03).
    # The cap is applied against total open option capital (sum of
    # cash_secured + premium-at-risk across open positions). 0 disables.
    options_hopeful_allocation_cap_pct: float = 0.03


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
