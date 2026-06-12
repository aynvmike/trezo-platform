"""Alpaca WebSocket streaming scaffold (Task #75).

This is a SCAFFOLD - not wired into the bus yet. Real WebSocket work
requires:
  - websocket-client or alpaca-trade-api lifecycle management
  - reconnect with exponential backoff
  - message routing into the bus
  - subscription set sync with open positions + watchlist
  - dedicated background task that survives uvicorn reloads

Mike: when ready to ship this fully, follow Alpaca docs:
  https://docs.alpaca.markets/us/docs/websocket-streaming

For now Position Monitor + Pattern Detection still poll candles via
the REST API every tick. The batched persistence + scanner_pulse
aggregation reduce that load substantially - WebSocket is a 2x-5x
win on top of those, not a 100x win, so it's not blocking.
"""

from __future__ import annotations


async def start_alpaca_stream() -> None:
    """Not yet implemented. Wire to the bus as a kind="market_tick"
    event source. Position Monitor + Pattern Detection switch from
    polling to listening for these ticks."""
    raise NotImplementedError("Task #75 - real WS lifecycle work pending")
