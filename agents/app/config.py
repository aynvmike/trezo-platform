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

    # Phase F (2026-06-04): route crypto signals to Alpaca paper
    # crypto when enabled AND the symbol is in the broker allowlist.
    # Default OFF - crypto stays on the internal modeled paper
    # engine, identical to today. Set ALPACA_CRYPTO_ENABLED=true
    # in agents/.env to opt in. To remove entirely, comment out
    # this line (the routing branch in trade_execution.py treats
    # missing flag as False).
    alpaca_crypto_enabled: bool = False

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
