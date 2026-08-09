"""Bot tuning settings - read tunable parameters from `bot_settings`.

Per-user capable (Phase 5b / #119): get_bot_settings(user_id) reads that
user's row; get_bot_settings() with no argument keeps the global
"most-recently-updated row" behaviour, so existing callers are
unaffected. Cached per user_id for 30 seconds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from app.config import get_settings


@dataclass
class BotSettings:
    tcs_threshold: int = 70   # 0-100 scale (2026-07-08)
    max_open_positions: int = 3
    consecutive_loss_limit: int = 3
    risk_per_trade_pct: float = 0.05
    default_stop_pct: float = 0.05
    default_target_pct: float = 0.10
    pattern_enabled: bool = True
    stms_enabled: bool = True
    extended_enabled: bool = True
    crypto_enabled: bool = True
    autonomy_mode: str = "guarded"
    account_posture: str = "auto"
    allocation_overrides: dict | None = None
    pattern_weights: dict | None = None
    # Reward-to-risk floor enforced by sizing.py. Default 1.5 (target
    # must be at least 1.5x the stop). Lower = more aggressive (allow
    # scalper-style 1:1 setups). Higher = stricter. Range 0.3-3.0.
    min_reward_risk: float = 1.5
    # High-level risk profile preset: 'conservative' / 'balanced' /
    # 'aggressive' / 'expert'. The UI maps the preset to sensible
    # defaults for stop/target/risk/RR. Expert unlocks raw sliders +
    # writes an audit row each time the user enters/exits expert mode.
    risk_profile: str = "balanced"
    # Per-stock strategy switching friction (anti-whipsaw). When the
    # Strategy Engine picks the best strategy per stock each tick, a
    # tiny TCS change shouldn't flip the pick. Modes:
    #   off       - every tick can flip (legacy).
    #   fixed     - new TCS > prev * (1 + advantage_pct/100).
    #   adaptive  - advantage scales inversely with tcs_threshold.
    #               Lower TCS = noisier = bigger gap required.
    #   tiered    - three explicit bands keyed on the NEW pick's TCS.
    switching_mode: str = "adaptive"
    switching_advantage_pct: int = 10
    # Wheel auto-execute - Mike 2026-05-30. When True AND Alpaca options
    # approval >= 1, the Options Scanner's _run_wheel() pass auto-fires
    # CSP / CC orders instead of emitting only suggestions. Routes through
    # the same primitives as the /wheel/place-leg manual button. Honors
    # kill-switches + consecutive-loss limit. Default off; flip on once
    # paper trading has proven the chain end-to-end.
    wheel_auto_execute: bool = False
    # Expert mode - Mike Phase 13a follow-up (2026-05-30). When True
    # the Bot Tuning UI surfaces the Expert Overrides section
    # (per-stock strategy pin + disable list). The underlying
    # overrides apply whether this toggle is on or off; the toggle
    # just gates the UI so casual users don't see the advanced
    # surface. Default off.
    expert_mode_enabled: bool = False
    # Auto-trade toggle - Mike 2026-06-01. When ON (default), approved
    # signals route to the paper/live engine. When OFF, signals still
    # score, Risk Manager still approves, post-mortem still records the
    # would-have-done, but no open_position fires. Pure learn-only mode.
    auto_trade_enabled: bool = True
    # Phase C+D options filters - per-user override of env defaults.
    # Empty/None means "fall through to global Settings from .env".
    options_min_dte: int | None = None
    options_max_premium_delta: float | None = None
    options_min_iv_rank_scalp: float | None = None
    options_hopeful_allocation_cap_pct: float | None = None
    # Crypto HODL per-coin allocation cap (Mike 2026-06-13, crypto Part 2).
    # Hard ceiling on TOTAL open exposure to a single coin as a share of
    # account equity, summed across every open row for that coin. Keeps
    # cross-day HODL accumulation from quietly concentrating the book in
    # one name. Default 10%. Tunable from Bot Tuning once migration 0044
    # adds the column; the code default already enforces it.
    hodl_per_coin_cap_pct: float = 0.10
    # Hours between HODL/DCA accumulation adds on the same coin -- turns
    # "buy the dip" into "across days" instead of every scanner tick.
    # Default 18h, derived restart-safe from the coin's most recent row.
    crypto_accumulate_cooldown_hours: float = 18.0


_DEFAULTS = BotSettings()
# key: user_id (or None for the global row) -> (settings, fetched_at)
_cache: dict[Optional[str], tuple[BotSettings, float]] = {}
_TTL = 30.0


def _primary_user_id():
    """The settings row every consumer anchors to.

    Reads Settings FIRST. This lived in agents/.env from 2026-07-06 but
    was fetched with os.getenv, which never sees that file -- so single-row
    mode silently never engaged and get_bot_settings() fell through to
    'most recently updated row'. Found 2026-08-09 while wiring multi-account.
    The os.getenv fallback stays for a real process-level override.
    """
    try:
        from app.config import get_settings as _gs
        v = (getattr(_gs(), "trezo_primary_user_id", "") or "").strip()
        if v:
            return v
    except Exception:  # noqa: BLE001
        pass
    import os as _o
    v = (_o.getenv("TREZO_PRIMARY_USER_ID") or "").strip()
    return v or None


def _single_row_mode() -> bool:
    import os as _o
    return _o.getenv("TREZO_SETTINGS_SINGLE_ROW", "1") != "0"


def clear_settings_cache() -> None:
    """Force every consumer's next get_bot_settings() to re-read the
    database -- the audit page's 'Sync agents now' action (2026-07-06)."""
    _cache.clear()


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:
        return None


def _from_row(r: dict) -> BotSettings:
    return BotSettings(
        tcs_threshold=(lambda _v: int(round(_v / 10.0))
                       if _v > 100 else int(_v))(
            float(r.get("tcs_threshold", 70) or 70)),  # old-scale writes self-heal (2026-07-16)
        max_open_positions=int(r.get("max_open_positions", 3)),
        consecutive_loss_limit=int(r.get("consecutive_loss_limit", 3)),
        risk_per_trade_pct=float(r.get("risk_per_trade_pct", 0.05)),
        default_stop_pct=float(r.get("default_stop_pct", 0.05)),
        default_target_pct=float(r.get("default_target_pct", 0.10)),
        pattern_enabled=bool(r.get("pattern_enabled", True)),
        stms_enabled=bool(r.get("stms_enabled", True)),
        extended_enabled=bool(r.get("extended_enabled", True)),
        crypto_enabled=bool(r.get("crypto_enabled", True)),
        autonomy_mode=str(r.get("autonomy_mode", "guarded") or "guarded"),
        account_posture=str(r.get("account_posture", "auto") or "auto"),
        allocation_overrides=(r.get("allocation_overrides") or None),
        pattern_weights=(r.get("pattern_weights") or None),
        min_reward_risk=float(r.get("min_reward_risk", 1.5) or 1.5),
        risk_profile=str(r.get("risk_profile", "balanced") or "balanced"),
        switching_mode=str(r.get("switching_mode", "adaptive") or "adaptive"),
        switching_advantage_pct=int(r.get("switching_advantage_pct", 10) or 10),
        wheel_auto_execute=bool(r.get("wheel_auto_execute", False)),
        expert_mode_enabled=bool(r.get("expert_mode_enabled", False)),
        auto_trade_enabled=bool(r.get("auto_trade_enabled", True)),
        options_min_dte=(int(r["options_min_dte"]) if r.get("options_min_dte") is not None else None),
        options_max_premium_delta=(float(r["options_max_premium_delta"]) if r.get("options_max_premium_delta") is not None else None),
        options_min_iv_rank_scalp=(float(r["options_min_iv_rank_scalp"]) if r.get("options_min_iv_rank_scalp") is not None else None),
        options_hopeful_allocation_cap_pct=(float(r["options_hopeful_allocation_cap_pct"]) if r.get("options_hopeful_allocation_cap_pct") is not None else None),
        hodl_per_coin_cap_pct=float(r.get("hodl_per_coin_cap_pct", 0.10) or 0.10),
        crypto_accumulate_cooldown_hours=float(r.get("crypto_accumulate_cooldown_hours", 18.0) or 18.0),
    )


def required_switch_advantage(
    mode: str,
    base_pct: int,
    tcs_threshold: int,
    new_tcs: int,
) -> float:
    """How much fractionally better must the new strategy's TCS be
    than the current pick's TCS before the Strategy Engine flips?

    Returns a fraction (0.10 = 10%). 0.0 means "any improvement is
    enough" (off mode).

    Modes:
      off       - always 0.0 (legacy behavior).
      fixed     - base_pct / 100.
      adaptive  - base_pct scaled by (800 / current TCS threshold).
                  At threshold=500 with base=10 you get 16%; at
                  threshold=800 you get 10%. Lower TCS = noisier =
                  bigger gap to flip.
      tiered    - three bands keyed on the NEW pick's TCS:
                  >= 700 needs 5%,  500-699 needs 10%,  < 500 needs 20%.
                  Ignores base_pct.

    Anchored to TCS=800 (the conservative ceiling) so the adaptive
    multiplier is >= 1.0 - friction never gets EASIER than the base.
    """
    m = (mode or "adaptive").strip().lower()
    if m == "off":
        return 0.0
    if m == "fixed":
        return max(0.0, float(base_pct)) / 100.0
    if m == "tiered":
        if new_tcs >= 700:
            return 0.05
        if new_tcs >= 500:
            return 0.10
        return 0.20
    # adaptive (default)
    base = max(0.0, float(base_pct)) / 100.0
    if tcs_threshold <= 0:
        return base
    scale = 80.0 / float(tcs_threshold)
    if scale < 1.0:
        scale = 1.0  # never make friction EASIER than the base
    return base * scale


def get_bot_settings(user_id: Optional[str] = None) -> BotSettings:
    """Active bot settings, cached 30s per user.

    With a user_id, reads that user's `bot_settings` row. With no
    argument, reads the most-recently-updated row (the global,
    single-user default). Falls back to defaults on any miss.
    """
    # Single-row mode (2026-07-06): one operator, ONE settings row. The
    # web app saves the signed-in user's row while engine signals carry
    # the paper-engine's user id -- two rows drifted apart and Bot Tuning
    # edits stopped reaching the trades. With TREZO_PRIMARY_USER_ID set,
    # EVERY consumer (global or per-user) resolves to that row.
    # Single-row mode exists (2026-07-06) because the web app saved the
    # signed-in user's row while engine signals carried the paper engine's
    # id -- two rows drifted and Bot Tuning edits stopped reaching trades.
    # Collapsing EVERY lookup to one row is the right fix for one operator
    # with one book. It is the WRONG fix once a person holds several: it
    # would tie every account to the main account's settings, which is
    # precisely what multi-account has to avoid (Mike, 2026-08-09). So the
    # anchor generalises -- to THIS account when there is more than one.
    _multi = False
    _acct_key = None
    try:
        from app.brokers.accounts import (
            multi_account_active as _maa, current_user_id as _cuid,
        )
        _multi = _maa()
        if _multi:
            _acct_key = _cuid()
    except Exception:  # noqa: BLE001
        _multi = False

    if _multi:
        # Each book keeps its own row. An explicit user_id IS an account
        # key and is honoured; a bare call resolves to the bound account.
        if not user_id:
            user_id = _acct_key or _primary_user_id()
    else:
        _prim = _primary_user_id()
        if _prim and _single_row_mode():
            user_id = _prim
    now = time.time()
    hit = _cache.get(user_id)
    if hit is not None and (now - hit[1]) < _TTL:
        return hit[0]

    client = _supabase()
    if not client:
        _cache[user_id] = (_DEFAULTS, now)
        return _DEFAULTS

    try:
        q = client.table("bot_settings").select("*")
        if user_id:
            q = q.eq("user_id", user_id)
        res = q.order("updated_at", desc=True).limit(1).execute()
        rows = res.data or []
        bs = _from_row(rows[0]) if rows else _DEFAULTS
        _cache[user_id] = (bs, now)
        return bs
    except Exception:
        _cache[user_id] = (_DEFAULTS, now)
        return _DEFAULTS
