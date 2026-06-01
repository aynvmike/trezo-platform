"""FastAPI router for pattern detection endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.data.candles import fetch_candles_for
from app.patterns import Candle
from app.patterns.scoring import calculate_score, MarketContext, Score
from app.patterns.confluence import confluence_bonus

router = APIRouter(prefix="/patterns", tags=["patterns"])


class ScanResponse(BaseModel):
    ticker: str
    asset_type: str
    score: int
    tcs: int
    dominant_pattern: Optional[str]
    direction: str
    detected_patterns: list[str]
    breakdown: dict[str, float]
    candle_count: int
    confluence: dict
    candles: list[dict] = []


@router.get("/scan/{ticker}", response_model=ScanResponse)
async def scan(
    ticker: str,
    asset_type: str = Query("auto", description="'auto', 'crypto', or 'stock'"),
    catalyst: bool = Query(False, description="News catalyst today?"),
    iv_rank: Optional[float] = Query(None, description="0-100 IV rank if known"),
    spy_up: Optional[bool] = Query(None, description="Is SPY trending up?"),
):
    """Run pattern detection + scoring on a single ticker.

    Returns Trade Confidence Score (0-1000) plus the full breakdown so the
    front-end can render an attribution view.
    """
    at = None if asset_type == "auto" else asset_type
    candles = await fetch_candles_for(ticker, at)
    if not candles:
        raise HTTPException(
            status_code=404,
            detail=f"No candle data available for {ticker}. May be a malformed symbol or upstream provider is rate-limited.",
        )

    # Multi-timeframe confluence: we currently have one timeframe of data per fetch.
    # When intraday data sources are wired, this will scan multiple TFs.
    # For now we run "lookback windows" of the same series as a proxy.
    tf_split: dict[str, list[Candle]] = {
        "recent_15": candles[-15:] if len(candles) >= 15 else candles,
        "recent_30": candles[-30:] if len(candles) >= 30 else candles,
        "full":      candles,
    }
    conf = confluence_bonus(tf_split)

    ctx = MarketContext(
        spy_trending_up=spy_up,
        iv_rank=iv_rank,
        catalyst_today=catalyst,
        confluence_bonus=float(conf["bonus"]),
    )

    score: Score = calculate_score(candles, ctx)

    # Compact recent OHLC so the front-end can draw a chart snapshot
    # of what the detector saw (Phase 12c). Last ~40 bars.
    candle_snapshot = [
        {"o": round(float(c.open), 4), "h": round(float(c.high), 4),
         "l": round(float(c.low), 4), "c": round(float(c.close), 4)}
        for c in candles[-40:]
    ]

    return ScanResponse(
        ticker=ticker.upper(),
        asset_type=(at or ("crypto" if ticker.upper() in {"XRP", "ETH", "SOL", "BTC"} else "stock")),
        score=score.score,
        tcs=score.tcs,
        dominant_pattern=score.dominant_pattern,
        direction=score.direction,
        detected_patterns=score.detected_patterns,
        breakdown=score.breakdown,
        candle_count=len(candles),
        confluence=conf,
        candles=candle_snapshot,
    )
