"""Multi-timeframe confluence detection.

When the same pattern appears across multiple timeframes the signal is
stronger — this calculates a bonus to add to the base 0-100 score.
"""

from __future__ import annotations

from .candle import Candle
from .library import detect_all


def confluence_bonus(timeframe_candles: dict[str, list[Candle]]) -> dict:
    """Run detection on each timeframe; find patterns hitting on 2+ timeframes.

    Returns:
        {
          "bonus": int,                  # 0..100 bonus to add to score
          "shared_patterns": [           # list of patterns hit on multiple TFs
              {"pattern": "Hammer", "timeframes": ["5min", "1h"]}
          ],
        }
    """
    detections: dict[str, set[str]] = {}
    for tf, candles in timeframe_candles.items():
        if not candles:
            continue
        hits = {p for p, ok in detect_all(candles).items() if ok}
        detections[tf] = hits

    if not detections:
        return {"bonus": 0, "shared_patterns": []}

    all_patterns = set().union(*detections.values())

    shared: list[dict] = []
    for p in all_patterns:
        tfs = [tf for tf, hits in detections.items() if p in hits]
        if len(tfs) >= 2:
            shared.append({"pattern": p, "timeframes": tfs})

    if not shared:
        return {"bonus": 0, "shared_patterns": []}

    max_tfs = max(len(s["timeframes"]) for s in shared)
    # Phase plan: 2 TFs = +30, 3 = +60, 4+ = +100
    bonus_map = {2: 30, 3: 60, 4: 100}
    bonus = bonus_map.get(max_tfs, 100 if max_tfs >= 4 else 0)

    return {"bonus": bonus, "shared_patterns": shared}
