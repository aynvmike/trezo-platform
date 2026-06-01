"""Crypto Scanner Agent.

Runs 24/7 (crypto never closes). Ticks every 60 seconds. For XRP/ETH/SOL:
  - Fetches recent OHLC candles (CoinGecko)
  - Runs SCALP/SWING/DCA mode detection
  - If a mode triggers, computes a Trade Confidence Score and emits a
    `signal` carrying the mode + mode-specific stop_pct/target_pct

The signal flows through Risk Manager → Trade Execution → paper engine
exactly like STMS, but tagged `strategy="crypto_<mode>"`.
"""

from __future__ import annotations

from app.data.candles import fetch_candles_for
from app.patterns.scoring import calculate_score, MarketContext
from app.strategies.crypto import CRYPTO_WATCHLIST, detect_mode

from .base import Agent, AgentMessage


class CryptoScannerAgent(Agent):
    name = "crypto_scanner"
    tick_interval_seconds = 60  # 24/7, every minute

    # Crypto signals can be acted on with a slightly lower TCS bar than
    # stocks — the per-coin stops are tighter. Still gated by Risk Manager.
    MIN_TCS = 650

    async def tick(self) -> list[AgentMessage]:
        from app.runtime.settings import get_bot_settings
        # Honor the user's Bot Tuning TCS slider. Crypto stays slightly
        # under the stock floor (per-coin stops are tighter) so if the
        # user sets a stock floor of 500, crypto effectively runs at 500
        # too — the user's slider drives everything.
        _cfg = get_bot_settings()
        tcs_floor = int(_cfg.tcs_threshold or self.MIN_TCS)
        if not _cfg.crypto_enabled:
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"note": "Crypto strategy disabled in Bot Tuning settings."},
            )]

        out: list[AgentMessage] = []
        scanned = 0
        triggered = 0

        for coin in CRYPTO_WATCHLIST:
            try:
                candles = await fetch_candles_for(coin, "crypto")
                if not candles:
                    continue
                scanned += 1

                sig = detect_mode(coin, candles)
                if not sig:
                    continue

                score = calculate_score(candles, MarketContext(), strategy=f"crypto_{sig.mode}")
                if score.tcs < tcs_floor:
                    continue

                triggered += 1
                out.append(AgentMessage(
                    agent=self.name,
                    kind="signal",
                    confidence=score.tcs / 1000.0,
                    payload={
                        "ticker": coin,
                        "tcs": score.tcs,
                        "direction": sig.direction,
                        "strategy": f"crypto_{sig.mode}",
                        "mode": sig.mode,
                        "stop_pct": sig.stop_pct,
                        "target_pct": sig.target_pct,
                        "crypto_signal": {
                            "rsi": round(sig.rsi, 1),
                            "bb_width_pct": round(sig.bb_width_pct, 2),
                            "volume_ratio": round(sig.volume_ratio, 2),
                            "reason": sig.reason,
                        },
                    },
                ))
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(
                    agent=self.name, kind="error",
                    payload={"ticker": coin, "error": str(e)},
                ))

        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={
                "note": "Crypto scan complete",
                "coins_scanned": scanned,
                "modes_triggered": triggered,
            },
        ))
        return out
