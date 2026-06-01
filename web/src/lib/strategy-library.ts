// Strategy Library — display mirror of agents/app/strategies/library.py.
//
// The Python module is the source of truth the agents read and reason
// over. This TypeScript copy exists only so the dashboard can show the
// library to the user. Keep the two in sync when the library changes.

export type StrategyCard = {
  id: string;
  name: string;
  family: string;
  thesis: string;
  bestRegimes: string[];
  riskProfile: "conservative" | "moderate" | "aggressive";
  trezoLayer: number | null;
};

export const STRATEGY_LIBRARY: StrategyCard[] = [
  { id: "ma_crossover", name: "Moving-Average Crossover", family: "trend",
    thesis: "Ride sustained trends: go long when a fast moving average crosses above a slow one, and step aside when it crosses back.",
    bestRegimes: ["trending_up", "trending_down"], riskProfile: "moderate", trezoLayer: null },
  { id: "relative_strength_momentum", name: "Relative-Strength Momentum", family: "momentum",
    thesis: "Buy the strongest names over the last 3-12 months; winners tend to keep winning until the trend breaks.",
    bestRegimes: ["trending_up"], riskProfile: "moderate", trezoLayer: null },
  { id: "rsi2_mean_reversion", name: "RSI(2) Mean Reversion", family: "mean_reversion",
    thesis: "Buy short-term oversold dips inside a longer uptrend and sell the bounce a few days later.",
    bestRegimes: ["choppy", "low_volatility"], riskProfile: "moderate", trezoLayer: null },
  { id: "bollinger_reversion", name: "Bollinger Band Reversion", family: "mean_reversion",
    thesis: "Fade stretched moves to the outer Bollinger band back toward the moving-average mean.",
    bestRegimes: ["choppy", "low_volatility"], riskProfile: "moderate", trezoLayer: null },
  { id: "donchian_breakout", name: "Donchian Channel Breakout", family: "breakout",
    thesis: "Enter when price breaks a 20/55-day high — the classic trend-following turtle entry.",
    bestRegimes: ["trending_up", "high_volatility"], riskProfile: "moderate", trezoLayer: null },
  { id: "opening_gap_momentum", name: "Opening-Gap Momentum", family: "momentum",
    thesis: "Trade small-caps gapping up hard on heavy volume in the first hour of the session.",
    bestRegimes: ["trending_up", "high_volatility"], riskProfile: "aggressive", trezoLayer: 2 },
  { id: "vwap_reversion", name: "VWAP Reversion", family: "mean_reversion",
    thesis: "Intraday: buy dips below VWAP and sell rallies above it when no strong trend is in control.",
    bestRegimes: ["choppy"], riskProfile: "moderate", trezoLayer: null },
  { id: "post_earnings_drift", name: "Post-Earnings-Announcement Drift", family: "event_driven",
    thesis: "After a large earnings surprise, price keeps drifting the same direction for several weeks.",
    bestRegimes: ["trending_up", "low_volatility"], riskProfile: "moderate", trezoLayer: null },
  { id: "news_catalyst_momentum", name: "News-Catalyst Momentum", family: "event_driven",
    thesis: "Trade the short-term drift after a confirmed material headline — M&A, guidance, approvals, contract wins.",
    bestRegimes: ["high_volatility", "trending_up"], riskProfile: "aggressive", trezoLayer: null },
  { id: "dividend_capture", name: "Dividend Capture", family: "event_driven",
    thesis: "Hold a quality payer across its ex-dividend date to collect the distribution, then exit once the price recovers.",
    bestRegimes: ["low_volatility"], riskProfile: "conservative", trezoLayer: 6 },
  { id: "covered_call_wheel", name: "Cash-Secured Put / Covered-Call Wheel", family: "income",
    thesis: "Sell cash-secured puts on names worth owning; if assigned, sell covered calls — collecting premium each cycle.",
    bestRegimes: ["low_volatility", "trending_up"], riskProfile: "conservative", trezoLayer: 5 },
  { id: "volatility_contraction", name: "Volatility-Contraction Breakout", family: "volatility",
    thesis: "Buy tight, low-volatility consolidations as they break out on expanding volume.",
    bestRegimes: ["low_volatility", "trending_up"], riskProfile: "moderate", trezoLayer: null },
  { id: "sector_rotation", name: "Sector Rotation", family: "rotation",
    thesis: "Rotate capital into the leading sectors and out of the laggards on a monthly cadence.",
    bestRegimes: ["trending_up", "trending_down"], riskProfile: "moderate", trezoLayer: null },
  { id: "pairs_trading", name: "Statistical Pairs Trading", family: "arbitrage",
    thesis: "Trade the spread between two correlated names — long the laggard, short the leader — staying market-neutral.",
    bestRegimes: ["choppy", "risk_off"], riskProfile: "moderate", trezoLayer: null },
  { id: "quality_trend_core", name: "Quality-Trend Core Holding", family: "trend",
    thesis: "Hold quality, low-beta names while price stays above its long-term trend; step aside when that trend breaks.",
    bestRegimes: ["trending_up", "low_volatility"], riskProfile: "conservative", trezoLayer: 7 }
];

export type RegimePlay = {
  summary: string;
  favor: string[];
  reduce: string[];
  pause: string[];
};

export const REGIME_PLAYBOOK: Record<string, RegimePlay> = {
  trending_up: { summary: "Broad uptrend — let winners run, lean into strength.",
    favor: ["trend", "momentum", "breakout"], reduce: ["mean_reversion"], pause: [] },
  trending_down: { summary: "Sustained downtrend — defend capital, avoid catching knives.",
    favor: ["arbitrage"], reduce: ["trend", "mean_reversion"], pause: ["momentum", "breakout", "income"] },
  choppy: { summary: "Directionless chop — fade extremes, distrust breakouts.",
    favor: ["mean_reversion", "arbitrage"], reduce: ["trend", "momentum"], pause: ["breakout"] },
  high_volatility: { summary: "Elevated volatility — size down, widen stops, be selective.",
    favor: ["event_driven"], reduce: ["trend", "momentum", "mean_reversion"], pause: ["breakout"] },
  low_volatility: { summary: "Calm, low-volatility market — favor income and clean trends.",
    favor: ["income", "volatility", "trend"], reduce: [], pause: [] },
  risk_off: { summary: "Risk-off — capital preservation first; only market-neutral edges.",
    favor: ["arbitrage"], reduce: ["trend"], pause: ["momentum", "breakout", "event_driven", "income"] }
};

export const REGIME_LABEL: Record<string, string> = {
  trending_up: "Trending up",
  trending_down: "Trending down",
  choppy: "Choppy",
  high_volatility: "High volatility",
  low_volatility: "Low volatility",
  risk_off: "Risk-off"
};
