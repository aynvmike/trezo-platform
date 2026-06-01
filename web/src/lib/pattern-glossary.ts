// Plain-language explanations of the candlestick patterns and scoring
// factors the Pattern Engine uses. Powers the hover tooltips and the
// "Learning" detail mode on the Pattern Engine page. Phase — Pattern
// Engine learner upgrade.

const PATTERN_INFO: Record<string, string> = {
  "shooting star":
    "A small body with a long upper wick — buyers pushed price up but sellers slammed it back down. Often a sign a rise is running out of steam.",
  hammer:
    "A small body with a long lower wick — sellers pushed price down but buyers fought back. Often a sign a fall is bottoming out.",
  "inverted hammer":
    "A small body with a long upper wick after a decline — an early hint that buyers are testing higher prices.",
  "hanging man":
    "A hammer-shaped candle after a rise — a warning that the uptrend may be tiring.",
  doji:
    "Open and close almost equal — the market is undecided. A pause that can come right before a turn.",
  "bullish engulfing":
    "A green candle that completely covers the prior red one — buyers took firm control.",
  "bearish engulfing":
    "A red candle that completely covers the prior green one — sellers took firm control.",
  "bullish harami":
    "A small green candle tucked inside the prior large red one — selling pressure is easing.",
  "bearish harami":
    "A small red candle tucked inside the prior large green one — buying pressure is easing.",
  "morning star":
    "A three-candle bottoming pattern — a drop, a quiet pause, then a strong push back up.",
  "evening star":
    "A three-candle topping pattern — a rise, a quiet pause, then a strong push back down.",
  "three white soldiers":
    "Three strong green candles in a row — steady, convincing buying.",
  "three black crows":
    "Three strong red candles in a row — steady, convincing selling.",
  "cup and handle":
    "A rounded dip followed by a small pullback — a base that often leads into a breakout.",
  "piercing line":
    "A red candle, then a green one that closes well up into it — buyers stepping in.",
  "dark cloud cover":
    "A green candle, then a red one that closes well down into it — sellers stepping in."
};

/** Plain-language note for a candlestick pattern name. */
export function patternInfo(name: string | null | undefined): string {
  if (!name) return "";
  const key = String(name).toLowerCase().replace(/_/g, " ").trim();
  return (
    PATTERN_INFO[key] ??
    "A candlestick pattern the engine recognised in the recent price action."
  );
}

const FACTOR_INFO: Record<string, { label: string; info: string }> = {
  trend: {
    label: "Trend",
    info: "Which way price has been heading. The engine rewards trading with the trend, not against it."
  },
  momentum: {
    label: "Momentum",
    info: "How much force is behind the recent move (think RSI). Strong momentum scores higher."
  },
  macd: {
    label: "MACD",
    info: "A momentum indicator comparing two moving averages — it flags shifts from falling to rising and back."
  },
  volume: {
    label: "Volume",
    info: "How many shares traded. A move on heavy volume is more convincing than one on light volume."
  },
  breakout: {
    label: "Breakout",
    info: "Whether price has pushed past a recent high or low — a breakout can start a fresh move."
  },
  candle_pattern: {
    label: "Candle pattern",
    info: "Whether a recognised candlestick pattern is present, and how strong it is."
  },
  bb_position: {
    label: "Bollinger position",
    info: "Where price sits inside its Bollinger Bands — near an edge can mean stretched, or about to move."
  },
  vwap_alignment: {
    label: "VWAP alignment",
    info: "Whether price agrees with the volume-weighted average price — a read on the day's fair value."
  },
  market_alignment: {
    label: "Market alignment",
    info: "Whether the broad market (SPY / QQQ) is moving the same way. Trading with the tide scores higher."
  },
  iv_environment: {
    label: "IV environment",
    info: "The implied-volatility backdrop — it shapes how options on the name are priced."
  },
  catalyst: {
    label: "News catalyst",
    info: "Whether there is fresh company news that could drive the move."
  },
  confluence_bonus: {
    label: "Confluence bonus",
    info: "Extra points when the same signal shows up on more than one timeframe — agreement across frames is a stronger signal."
  }
};

/** A friendly label for a score-breakdown factor key. */
export function factorLabel(key: string): string {
  return FACTOR_INFO[key]?.label ?? key.replace(/_/g, " ");
}

/** A plain-language note for a score-breakdown factor key. */
export function factorInfo(key: string): string {
  return FACTOR_INFO[key]?.info ?? "A factor in the Trade Confidence Score.";
}
