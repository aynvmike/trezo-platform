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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
