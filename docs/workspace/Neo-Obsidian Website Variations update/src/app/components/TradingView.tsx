import { useState } from "react";
import { motion } from "motion/react";
import { KpiTile } from "./KpiTile";
import { MiniAreaChart } from "./MiniAreaChart";
import { RefreshCw, Info } from "lucide-react";

const pnlData = [
  { t: "09:30", v: 0 }, { t: "10:00", v: 420 }, { t: "10:30", v: 310 },
  { t: "11:00", v: 780 }, { t: "11:30", v: 650 }, { t: "12:00", v: 920 },
  { t: "12:30", v: 1100 }, { t: "13:00", v: 870 }, { t: "13:30", v: 1350 },
  { t: "14:00", v: 1580 }, { t: "14:30", v: 1420 }, { t: "15:00", v: 1760 },
  { t: "15:30", v: 1890 }, { t: "16:00", v: 2147 },
];

const positions = [
  { id: 1, ticker: "NVDA", side: "LONG", layer: "Stock", chip: 2, entry: 874.20, current: 891.45, qty: 10, pnl: 172.50, pct: 1.97 },
  { id: 2, ticker: "BTC-PERP", side: "LONG", layer: "Crypto", chip: 1, entry: 67240, current: 68910, qty: 0.25, pnl: 417.50, pct: 2.49 },
  { id: 3, ticker: "SPY 560C 06/21", side: "LONG", layer: "Options", chip: 3, entry: 3.80, current: 5.10, qty: 5, pnl: 650.00, pct: 34.21 },
  { id: 4, ticker: "AAPL", side: "SHORT", layer: "Stock", chip: 2, entry: 192.40, current: 189.15, qty: 15, pnl: 48.75, pct: 1.69 },
  { id: 5, ticker: "ETH-PERP", side: "LONG", layer: "Crypto", chip: 1, entry: 3185, current: 3090, qty: 1.5, pnl: -142.50, pct: -2.98 },
  { id: 6, ticker: "MSFT 420P 06/28", side: "LONG", layer: "Options", chip: 3, entry: 2.15, current: 1.80, qty: 3, pnl: -105.00, pct: -16.28 },
];

const agentFeed = [
  { id: 1, time: "15:47", agent: "Crypto Bot", action: "Opened BTC-PERP long", reason: "RSI reset at 4H support, MACD bullish cross", layer: 1, type: "open" },
  { id: 2, time: "14:32", agent: "Stock Bot", action: "Partial exit NVDA ×5", reason: "Price reached first target, locking 50% gain", layer: 2, type: "exit" },
  { id: 3, time: "13:15", agent: "Options Bot", action: "Opened SPY 560C 06/21 ×5", reason: "IV rank low, momentum aligning with weekly trend", layer: 3, type: "open" },
  { id: 4, time: "12:58", agent: "Wheel Bot", action: "Closed TSLA CSP expired worthless", reason: "Options expired OTM, premium captured in full", layer: 5, type: "exit" },
  { id: 5, time: "11:20", agent: "Stock Bot", action: "Opened AAPL short ×15", reason: "Overbought on daily, rejection at resistance zone", layer: 2, type: "open" },
  { id: 6, time: "10:04", agent: "Crypto Bot", action: "Risk alert — ETH volatility spike", reason: "Trailing stop tightened automatically to -4%", layer: 1, type: "alert" },
];

const marketCtx = [
  { label: "SPY", value: "557.82", delta: "+0.84%", dir: "up" },
  { label: "QQQ", value: "478.14", delta: "+1.12%", dir: "up" },
  { label: "VIX", value: "13.4", delta: "−1.8", dir: "down" },
  { label: "BTC", value: "$68,910", delta: "+2.49%", dir: "up" },
  { label: "10Y", value: "4.28%", delta: "+0.03%", dir: "up" },
  { label: "DXY", value: "104.2", delta: "−0.21%", dir: "down" },
];

const layerChipColors: Record<number, string> = {
  1: "var(--treasure)",
  2: "var(--sky)",
  3: "var(--amber)",
  5: "var(--emerald)",
};

const actionTypeColors: Record<string, string> = {
  open: "var(--emerald)",
  exit: "var(--sky)",
  alert: "var(--amber)",
};


export function TradingView() {
  const [sortCol, setSortCol] = useState<string | null>(null);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-8">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 style={{ fontFamily: "var(--font-serif)", color: "var(--foreground)" }}>Trading</h1>
          <p className="text-[13px] mt-1" style={{ color: "var(--muted-foreground)" }}>
            Live session · Thu Jun 18, 2026 · US Market Open
          </p>
        </div>
        <button
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-[12px] transition-colors hover:bg-muted"
          style={{ color: "var(--muted-foreground)" }}
        >
          <RefreshCw size={12} />
          Refresh
        </button>
      </div>

      {/* Block 1 — KPI Tiles */}
      <section>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <KpiTile index={0} label="Portfolio Value" value="$142,380" sub="Across all 7 wealth layers" pill="Live" pillColor="var(--emerald)" />
          <KpiTile index={1} label="Today's P&L" value="+$2,147" delta="1.53%" deltaDir="up" sub="Since market open at 9:30 AM" />
          <KpiTile index={2} label="Open Risk" value="$8,420" sub="Total capital at risk in open positions" pill="5.9% deployed" pillColor="var(--sky)" />
          <KpiTile index={3} label="Agents Active" value="4 / 7" sub="Crypto, Stock, Options, Wheel running" pill="3 idle" pillColor="var(--muted-foreground)" />
        </div>
      </section>

      {/* Block 2 — P&L Chart + Market Context */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* Intraday chart */}
        <div className="md:col-span-2 rounded-xl border border-border obsidian-panel p-4" style={{ background: "var(--card)" }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-[13px]" style={{ fontWeight: 500 }}>Intraday P&L</h3>
              <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>Cumulative gain/loss since market open</p>
            </div>
            <span style={{ color: "var(--emerald)", fontFamily: "var(--font-mono)", fontSize: "13px" }}>+$2,147</span>
          </div>
          <MiniAreaChart data={pnlData} color="var(--emerald)" height={140} formatValue={(v) => `$${v.toLocaleString()}`} />
        </div>

        {/* Market context */}
        <div className="rounded-xl border border-border obsidian-panel p-4" style={{ background: "var(--card)" }}>
          <h3 className="text-[13px] mb-3" style={{ fontWeight: 500 }}>Market Context</h3>
          <div className="space-y-2.5">
            {marketCtx.map((item) => (
              <div key={item.label} className="flex items-center justify-between">
                <span className="text-[12px]" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                  {item.label}
                </span>
                <div className="flex items-center gap-2">
                  <span className="text-[12px]" style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>
                    {item.value}
                  </span>
                  <span
                    className="text-[11px]"
                    style={{ fontFamily: "var(--font-mono)", color: item.dir === "up" ? "var(--emerald)" : "var(--rose)" }}
                  >
                    {item.delta}
                  </span>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 pt-3 border-t border-border">
            <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>
              Low VIX = calm market. Your options strategies perform better in this environment.
            </p>
          </div>
        </div>
      </section>

      {/* Block 3 — Open Positions */}
      <section>
        <div className="rounded-xl border border-border obsidian-panel overflow-hidden" style={{ background: "var(--card)" }}>
          <div className="flex items-center justify-between px-5 py-4 border-b border-border">
            <div>
              <h3 className="text-[13px]" style={{ fontWeight: 500 }}>Open Positions</h3>
              <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
                6 open — {positions.filter(p => p.pnl > 0).length} winning, {positions.filter(p => p.pnl < 0).length} losing
              </p>
            </div>
            <span className="text-[12px]" style={{ color: "var(--emerald)", fontFamily: "var(--font-mono)", fontWeight: 500 }}>
              Net +$1,041.25
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {["Ticker", "Layer", "Side", "Entry", "Current", "Qty", "P&L", ""].map((col) => (
                    <th
                      key={col}
                      className="px-5 py-3 text-left"
                      style={{ color: "var(--muted-foreground)", fontWeight: 500, fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.map((pos, i) => (
                  <motion.tr
                    key={pos.id}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.3, delay: 0.15 + i * 0.05, ease: [0.22, 1, 0.36, 1] }}
                    className="transition-colors"
                    style={{
                      borderBottom: i < positions.length - 1 ? "1px solid var(--border)" : "none",
                    }}
                    onMouseEnter={e => (e.currentTarget.style.background = "var(--muted)")}
                    onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
                  >
                    <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: "var(--foreground)" }}>
                      {pos.ticker}
                    </td>
                    <td className="px-5 py-3">
                      <span
                        className="px-2 py-0.5 rounded-md text-[11px]"
                        style={{
                          background: `${layerChipColors[pos.chip] || "var(--muted)"}18`,
                          color: layerChipColors[pos.chip] || "var(--muted-foreground)",
                          fontFamily: "var(--font-mono)",
                        }}
                      >
                        {pos.chip} · {pos.layer}
                      </span>
                    </td>
                    <td className="px-5 py-3">
                      <span
                        className="text-[11px] px-1.5 py-0.5 rounded"
                        style={{
                          background: pos.side === "LONG" ? "rgba(16,185,129,0.12)" : "rgba(244,63,94,0.12)",
                          color: pos.side === "LONG" ? "var(--emerald)" : "var(--rose)",
                          fontFamily: "var(--font-mono)",
                        }}
                      >
                        {pos.side}
                      </span>
                    </td>
                    <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                      {typeof pos.entry === "number" && pos.entry > 1000
                        ? `$${pos.entry.toLocaleString()}`
                        : `$${pos.entry.toFixed(2)}`}
                    </td>
                    <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>
                      {typeof pos.current === "number" && pos.current > 1000
                        ? `$${pos.current.toLocaleString()}`
                        : `$${pos.current.toFixed(2)}`}
                    </td>
                    <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                      {pos.qty}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex flex-col">
                        <span
                          style={{
                            fontFamily: "var(--font-mono)",
                            fontWeight: 500,
                            color: pos.pnl >= 0 ? "var(--emerald)" : "var(--rose)",
                          }}
                        >
                          {pos.pnl >= 0 ? "+" : ""}${pos.pnl.toFixed(2)}
                        </span>
                        <span
                          className="text-[10px]"
                          style={{ color: pos.pct >= 0 ? "var(--emerald)" : "var(--rose)", fontFamily: "var(--font-mono)", opacity: 0.75 }}
                        >
                          {pos.pct >= 0 ? "+" : ""}{pos.pct.toFixed(2)}%
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-3">
                      <button
                        className="text-[11px] px-2 py-1 rounded-md border border-border transition-colors hover:bg-muted"
                        style={{ color: "var(--muted-foreground)" }}
                      >
                        Manage
                      </button>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* Block 4 — Agent Activity */}
      <section>
        <div className="rounded-xl border border-border obsidian-panel overflow-hidden" style={{ background: "var(--card)" }}>
          <div className="px-5 py-4 border-b border-border">
            <h3 className="text-[13px]" style={{ fontWeight: 500 }}>Agent Activity</h3>
            <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
              What your bots have been doing today, in plain English
            </p>
          </div>
          <div className="divide-y" style={{ borderColor: "var(--border)" }}>
            {agentFeed.map((row, i) => (
              <motion.div
                key={row.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3, delay: 0.1 + i * 0.06, ease: [0.22, 1, 0.36, 1] }}
                className="px-5 py-3.5 flex items-start gap-4 transition-colors hover:bg-muted/50"
              >
                <span
                  className="text-[11px] shrink-0 mt-0.5"
                  style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", minWidth: "36px" }}
                >
                  {row.time}
                </span>
                <div
                  className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0"
                  style={{ background: actionTypeColors[row.type] || "var(--muted-foreground)" }}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[12px]" style={{ fontWeight: 500, color: "var(--foreground)" }}>
                      {row.action}
                    </span>
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded"
                      style={{
                        background: `${layerChipColors[row.layer] || "var(--muted)"}18`,
                        color: layerChipColors[row.layer] || "var(--muted-foreground)",
                        fontFamily: "var(--font-mono)",
                      }}
                    >
                      {row.layer} · {row.agent}
                    </span>
                  </div>
                  <p className="text-[12px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
                    {row.reason}
                  </p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Block 5 — Settings Preview */}
      <section>
        <div className="rounded-xl border border-border obsidian-panel p-5" style={{ background: "var(--card)" }}>
          <div className="flex items-center gap-2 mb-4">
            <h3 className="text-[13px]" style={{ fontWeight: 500 }}>Session Settings</h3>
            <span className="text-[11px] px-2 py-0.5 rounded-full border border-dashed" style={{ borderColor: "rgba(245,158,11,0.4)", color: "var(--amber)", fontFamily: "var(--font-mono)" }}>
              Paper Mode
            </span>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {[
              { label: "Trading Mode", value: "Paper", note: "No real orders. Safe to test." },
              { label: "Auto-Trade", value: "OFF", note: "Bots signal but don't execute." },
              { label: "Risk Limit / Day", value: "$500", note: "Max drawdown before bots pause." },
            ].map((item) => (
              <div key={item.label} className="rounded-lg p-3 border border-border" style={{ background: "var(--muted)" }}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{item.label}</span>
                  <Info size={11} style={{ color: "var(--muted-foreground)" }} />
                </div>
                <div className="text-[13px]" style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: "var(--foreground)" }}>
                  {item.value}
                </div>
                <p className="text-[11px] mt-1" style={{ color: "var(--muted-foreground)" }}>{item.note}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="h-4" />
    </div>
  );
}
