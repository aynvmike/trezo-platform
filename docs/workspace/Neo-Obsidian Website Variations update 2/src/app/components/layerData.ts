import { LayerData } from "./LayerPage";

const buildSeries = (vals: number[]) =>
  vals.map((v, i) => ({ t: `D${i + 1}`, v }));

export const layerData: Record<string, LayerData> = {
  crypto: {
    id: 1, name: "Crypto", tagline: "The outer ring — BTC, ETH, and altcoin momentum take the first hit of volatility.",
    status: "active", accent: "var(--treasure)",
    strategy: "Momentum + RSI reversal", cadence: "4H / 1H scans · intraday",
    riskBucket: "Very High · Active sleeve",
    todayPnl: 417.50, weekPnl: 1284.20, openPositions: 2, winRate: "73%", avgHold: "2.4h", trades30d: 84,
    capitalAllocated: 25000, capitalUsed: 14600,
    pnlSeries: buildSeries([0, 220, 180, 480, 360, 720, 540, 980, 1240, 1080, 1340, 1180, 1284]),
    positions: [
      { ticker: "BTC-PERP", side: "LONG", entry: 67240, current: 68910, qty: 0.25, pnl: 417.50, pct: 2.49 },
      { ticker: "ETH-PERP", side: "LONG", entry: 3185, current: 3090, qty: 1.5, pnl: -142.50, pct: -2.98 },
    ],
    signals: [
      { ticker: "SOL-PERP", bias: "Bullish", type: "Perp · Spot Long", entry: "$148–151", exit: "$162", stop: "$143", confidence: 8, reasoning: "Reclaim of $148 with rising 1H momentum and BTC stabilization above $68k. Volume confirms breakout intent." },
      { ticker: "AVAX-PERP", bias: "Bearish", type: "Perp · Short", entry: "$36.20–36.80", exit: "$33.40", stop: "$37.60", confidence: 6, reasoning: "Failed retest of $36.50 resistance, 4H bearish divergence. Risk-defined short with tight invalidation." },
    ],
    activity: [
      { time: "15:47", action: "Opened BTC-PERP long at 67,240", reason: "RSI reset at 4H support, MACD bullish cross", type: "open" },
      { time: "13:22", action: "Closed BTC-PERP for +$280", reason: "Hit first target — locked profit, trailing stop on runner", type: "exit" },
      { time: "10:04", action: "Risk alert — ETH volatility spike", reason: "Trailing stop tightened automatically to -4%", type: "alert" },
    ],
  },

  stock: {
    id: 2, name: "Stock", tagline: "Equity breakouts and pullbacks on daily trend — patient, trend-following.",
    status: "active", accent: "var(--sky)",
    strategy: "Breakout + pullback on daily trend", cadence: "Daily close + intraday confirm",
    riskBucket: "High · Active sleeve",
    todayPnl: 221.25, weekPnl: 842.00, openPositions: 2, winRate: "68%", avgHold: "1.8d", trades30d: 42,
    capitalAllocated: 30000, capitalUsed: 12800,
    pnlSeries: buildSeries([0, 120, 80, 280, 420, 380, 560, 720, 680, 780, 740, 820, 842]),
    positions: [
      { ticker: "NVDA", side: "LONG", entry: 874.20, current: 891.45, qty: 10, pnl: 172.50, pct: 1.97 },
      { ticker: "AAPL", side: "SHORT", entry: 192.40, current: 189.15, qty: 15, pnl: 48.75, pct: 1.69 },
    ],
    signals: [
      { ticker: "MSFT", bias: "Bullish", type: "Stock · Long swing", entry: "$418–421", exit: "$435", stop: "$413", confidence: 7, reasoning: "Daily breakout from 3-week range, riding 20EMA. Earnings drift narrative intact." },
    ],
    activity: [
      { time: "14:32", action: "Partial exit NVDA ×5 at 891.45", reason: "Price reached first target, locking 50% gain", type: "exit" },
      { time: "11:20", action: "Opened AAPL short ×15", reason: "Overbought on daily, rejection at resistance zone", type: "open" },
    ],
  },

  options: {
    id: 3, name: "Options", tagline: "Directional debit spreads — defined risk, no naked exposure.",
    status: "active", accent: "var(--amber)",
    strategy: "Directional debit spreads, low IV rank only", cadence: "Daily setups, 2–7 DTE",
    riskBucket: "High · Quick-Options sleeve",
    todayPnl: 545.00, weekPnl: 1820.00, openPositions: 2, winRate: "61%", avgHold: "4.2d", trades30d: 28,
    capitalAllocated: 15000, capitalUsed: 4800,
    pnlSeries: buildSeries([0, 180, 240, 420, 320, 680, 540, 920, 1240, 1080, 1480, 1620, 1820]),
    positions: [
      { ticker: "SPY 560C 06/21", side: "LONG", entry: 3.80, current: 5.10, qty: 5, pnl: 650.00, pct: 34.21 },
      { ticker: "MSFT 420P 06/28", side: "LONG", entry: 2.15, current: 1.80, qty: 3, pnl: -105.00, pct: -16.28 },
    ],
    signals: [
      { ticker: "QQQ", bias: "Bullish", type: "Debit Call Spread", strikeExpiry: "480/485 · 06/28", entry: "$1.65", exit: "$3.20", stop: "$0.80", confidence: 8, reasoning: "Low IV rank (18%), uptrend intact, tech leadership strong. 1:1 risk-reward with 65% probability." },
    ],
    activity: [
      { time: "13:15", action: "Opened SPY 560C 06/21 ×5", reason: "IV rank low, momentum aligning with weekly trend", type: "open" },
    ],
  },

  "stock-weekly": {
    id: 4, name: "Stock Weekly", tagline: "Weekly chart patterns only — the patient ring, no day-trading.",
    status: "idle", accent: "var(--muted-foreground)",
    strategy: "Weekly chart patterns only", cadence: "Weekly close, no intraday",
    riskBucket: "Medium · Active sleeve",
    todayPnl: 0, weekPnl: 0, openPositions: 0, winRate: "72%", avgHold: "5.1d", trades30d: 6,
    capitalAllocated: 20000, capitalUsed: 0,
    pnlSeries: buildSeries([0, 120, 80, 60, 220, 180, 160, 280, 240, 320, 280, 240, 0]),
    positions: [],
    signals: [],
    activity: [
      { time: "Mon", action: "No entry signal this session", reason: "Weekly bar still inside last week's range", type: "alert" },
    ],
    idleReason: "Waiting for a weekly close above the 20W MA to re-engage.",
  },

  wheel: {
    id: 5, name: "Wheel", tagline: "Cash-secured puts cycling into covered calls — the income engine.",
    status: "active", accent: "var(--emerald)",
    strategy: "CSP → CC cycle on dividend-paying stocks", cadence: "Weekly rolls",
    riskBucket: "Medium · Holding sleeve",
    todayPnl: 180.00, weekPnl: 640.00, openPositions: 1, winRate: "89%", avgHold: "8.3d", trades30d: 12,
    capitalAllocated: 40000, capitalUsed: 28400,
    pnlSeries: buildSeries([0, 60, 120, 180, 220, 280, 340, 400, 460, 520, 560, 600, 640]),
    positions: [
      { ticker: "TSLA 240 CSP", side: "SHORT", entry: 4.80, current: 2.10, qty: 2, pnl: 540.00, pct: 56.25 },
    ],
    signals: [
      { ticker: "AAPL", bias: "Bullish", type: "Cash-Secured Put", strikeExpiry: "185 · 06/28", entry: "$1.20", exit: "Expire", stop: "Roll if ITM", confidence: 9, reasoning: "Strong support at $185, willing to own at this price. 0.95% weekly yield on collateral." },
    ],
    activity: [
      { time: "12:58", action: "TSLA CSP expired worthless — full premium captured", reason: "Underlying stayed above $240, $960 premium kept", type: "exit" },
      { time: "Mon", action: "Sold TSLA 240 CSP ×2", reason: "Premium target met at 1.2% weekly yield", type: "open" },
    ],
  },

  dividends: {
    id: 6, name: "Dividends", tagline: "High-yield dividend capture — the slow drip layer.",
    status: "paused", accent: "var(--sky)",
    strategy: "High-yield dividend capture", cadence: "Around ex-div dates only",
    riskBucket: "Low · Holding sleeve",
    todayPnl: 0, weekPnl: 0, openPositions: 0, winRate: "94%", avgHold: "22d", trades30d: 3,
    capitalAllocated: 35000, capitalUsed: 0,
    pnlSeries: buildSeries([0, 0, 80, 80, 80, 140, 140, 220, 220, 220, 280, 280, 0]),
    positions: [],
    signals: [],
    activity: [
      { time: "Mon", action: "Paused — no near-term ex-div dates", reason: "SCHD, O, JEPI all ex-div more than 3 weeks out", type: "alert" },
    ],
    idleReason: "Will re-activate when SCHD, O, or JEPI ex-div dates fall within 2 weeks.",
  },

  kindrip: {
    id: 7, name: "KINDRIP", tagline: "The treasure core — responsible, long-only ETFs held for years.",
    status: "active", accent: "var(--treasure)",
    strategy: "Kind & responsible investing, long-only ETF cores", cadence: "Monthly rebalance",
    riskBucket: "Very Low · Holding sleeve · Children's vault",
    todayPnl: 92.00, weekPnl: 380.00, openPositions: 3, winRate: "91%", avgHold: "45d", trades30d: 2,
    capitalAllocated: 60000, capitalUsed: 58200,
    pnlSeries: buildSeries([0, 40, 80, 120, 160, 200, 240, 280, 310, 340, 360, 370, 380]),
    positions: [
      { ticker: "VTI", side: "LONG", entry: 268.40, current: 271.20, qty: 80, pnl: 224.00, pct: 1.04 },
      { ticker: "BND", side: "LONG", entry: 73.80, current: 74.10, qty: 200, pnl: 60.00, pct: 0.41 },
      { ticker: "ESGV", side: "LONG", entry: 89.20, current: 90.40, qty: 50, pnl: 60.00, pct: 1.35 },
    ],
    signals: [],
    activity: [
      { time: "10:00", action: "Rebalanced VTI/BND allocation to 70/30", reason: "Monthly rebalance window — risk parity check", type: "open" },
    ],
  },
};
