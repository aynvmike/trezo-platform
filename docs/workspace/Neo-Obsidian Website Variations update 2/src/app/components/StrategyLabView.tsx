import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { ChevronDown, Play, TrendingUp, TrendingDown } from "lucide-react";
import { PageHeader } from "./PageHeader";
import { MiniAreaChart } from "./MiniAreaChart";

type Tab = "live" | "backtest" | "simulation";

const patterns = [
  { ticker: "NVDA", tcs: 842, pattern: "Bull Flag", tf: "4H", trend: [110, 112, 109, 114, 118, 116, 121, 125], dir: "up" },
  { ticker: "AAPL", tcs: 612, pattern: "Doji at resistance", tf: "1D", trend: [180, 182, 181, 183, 184, 183, 184, 184], dir: "neutral" },
  { ticker: "TSLA", tcs: 758, pattern: "Inverse H&S", tf: "4H", trend: [240, 238, 235, 240, 244, 246, 250, 254], dir: "up" },
  { ticker: "MSFT", tcs: 891, pattern: "Cup & Handle", tf: "1D", trend: [410, 415, 412, 418, 422, 420, 425, 432], dir: "up" },
  { ticker: "AMD", tcs: 524, pattern: "Bearish Engulf", tf: "1H", trend: [165, 163, 160, 158, 156, 154, 152, 150], dir: "down" },
  { ticker: "META", tcs: 716, pattern: "Golden Cross", tf: "1D", trend: [490, 488, 495, 500, 502, 508, 512, 518], dir: "up" },
  { ticker: "GOOGL", tcs: 433, pattern: "Range bound", tf: "4H", trend: [172, 174, 173, 175, 174, 173, 174, 174], dir: "neutral" },
  { ticker: "AMZN", tcs: 778, pattern: "Ascending Triangle", tf: "1D", trend: [185, 184, 186, 188, 189, 191, 193, 195], dir: "up" },
];

const tcsBreakdown = [
  { label: "Technical / pattern", max: 300 },
  { label: "Options environment", max: 250 },
  { label: "Fundamental / event", max: 200 },
  { label: "Risk / reward", max: 150 },
  { label: "Market", max: 100 },
];

const backtestResults = {
  trades: 142,
  winRate: "68.3%",
  profitFactor: "2.14",
  totalReturn: "+34.8%",
  equity: [10000, 10200, 10180, 10420, 10380, 10720, 11040, 11220, 11540, 11820, 12100, 12340, 12680, 12980, 13280, 13480],
};

const simResults = [
  { ticker: "NVDA", strategy: "Momentum", trades: 14, return: "+12.4%", promote: true },
  { ticker: "MSFT", strategy: "Breakout", trades: 9, return: "+8.7%", promote: true },
  { ticker: "TSLA", strategy: "Reversal", trades: 18, return: "+5.2%", promote: false },
  { ticker: "AAPL", strategy: "Mean Revert", trades: 11, return: "-2.1%", promote: false },
  { ticker: "AMZN", strategy: "Breakout", trades: 12, return: "+9.8%", promote: true },
];

function tcsColor(tcs: number) {
  if (tcs >= 700) return "var(--emerald)";
  if (tcs >= 500) return "var(--treasure)";
  if (tcs >= 300) return "var(--amber)";
  return "var(--muted-foreground)";
}

export function StrategyLabView() {
  const [tab, setTab] = useState<Tab>("live");
  const [breakdownOpen, setBreakdownOpen] = useState(false);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
      <PageHeader
        eyebrow="Plan & Research"
        title="Score, replay, stress-test"
        subtitle="One engine, three lenses — Live Patterns, Backtest, and Simulation."
        explainer="The Trezo Confidence Score (TCS) ranges from 0–1000. Anything above 700 is the live-trade threshold. Below that, signals show up here for review but never auto-execute."
      />

      {/* Tabs */}
      <div className="relative inline-flex p-1 rounded-lg border border-border" style={{ background: "var(--card)" }}>
        {([
          { id: "live", label: "Live Patterns" },
          { id: "backtest", label: "Backtest" },
          { id: "simulation", label: "Simulation" },
        ] as { id: Tab; label: string }[]).map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className="relative px-4 py-1.5 text-[12px] rounded-md transition-colors z-10"
            style={{ color: tab === t.id ? "var(--background)" : "var(--muted-foreground)" }}
          >
            {tab === t.id && (
              <motion.div
                layoutId="strategy-lab-tab"
                className="absolute inset-0 rounded-md"
                style={{ background: "var(--treasure)" }}
                transition={{ type: "spring", stiffness: 380, damping: 30 }}
              />
            )}
            <span className="relative">{t.label}</span>
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25 }}
        >
          {/* TAB A — Live Patterns */}
          {tab === "live" && (
            <div className="space-y-5">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {patterns.map((p, i) => (
                  <motion.div
                    key={p.ticker}
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.35, delay: i * 0.05 }}
                    whileHover={{ y: -3 }}
                    className="rounded-xl border border-border obsidian-panel p-4 flex flex-col gap-3"
                    style={{ background: "var(--card)" }}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <div style={{ fontFamily: "var(--font-mono)", fontWeight: 500, fontSize: "14px" }}>{p.ticker}</div>
                        <div className="text-[10px] uppercase tracking-wider mt-0.5" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>{p.tf}</div>
                      </div>
                      {p.dir === "up" && <TrendingUp size={14} style={{ color: "var(--emerald)" }} />}
                      {p.dir === "down" && <TrendingDown size={14} style={{ color: "var(--rose)" }} />}
                    </div>

                    {/* TCS — the hero number */}
                    <div>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: "32px", fontWeight: 500, color: tcsColor(p.tcs), lineHeight: 1 }}>
                        {p.tcs}
                      </div>
                      <div className="text-[10px] uppercase tracking-wider mt-1" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
                        TCS · max 1000
                      </div>
                    </div>

                    {/* Score bar */}
                    <div className="h-1 rounded-full overflow-hidden" style={{ background: "var(--muted)" }}>
                      <motion.div
                        className="h-full rounded-full"
                        style={{ background: tcsColor(p.tcs) }}
                        initial={{ width: 0 }}
                        animate={{ width: `${(p.tcs / 1000) * 100}%` }}
                        transition={{ duration: 0.8, delay: 0.2 + i * 0.05 }}
                      />
                    </div>

                    {/* Pattern */}
                    <div className="text-[12px]" style={{ color: "var(--foreground)" }}>{p.pattern}</div>

                    {/* Spark */}
                    <div className="h-10 -mx-1">
                      <Sparkline values={p.trend} color={p.dir === "up" ? "var(--emerald)" : p.dir === "down" ? "var(--rose)" : "var(--muted-foreground)"} />
                    </div>
                  </motion.div>
                ))}
              </div>

              {/* TCS breakdown disclosure */}
              <div className="rounded-xl border border-border obsidian-panel" style={{ background: "var(--card)" }}>
                <button
                  onClick={() => setBreakdownOpen((v) => !v)}
                  className="w-full px-5 py-3 flex items-center justify-between"
                >
                  <span className="text-[13px]" style={{ fontWeight: 500 }}>How the TCS score breaks down</span>
                  <motion.span animate={{ rotate: breakdownOpen ? 180 : 0 }} transition={{ duration: 0.2 }} style={{ color: "var(--muted-foreground)" }}>
                    <ChevronDown size={14} />
                  </motion.span>
                </button>
                <motion.div
                  initial={false}
                  animate={{ height: breakdownOpen ? "auto" : 0 }}
                  transition={{ duration: 0.25 }}
                  style={{ overflow: "hidden" }}
                >
                  <div className="px-5 pb-5 space-y-2.5">
                    {tcsBreakdown.map((row, i) => (
                      <div key={row.label} className="flex items-center gap-3">
                        <span className="text-[12px] w-44" style={{ color: "var(--foreground)" }}>{row.label}</span>
                        <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "var(--muted)" }}>
                          <motion.div
                            className="h-full rounded-full"
                            style={{ background: "var(--treasure)", opacity: 0.7 }}
                            initial={{ width: 0 }}
                            animate={{ width: `${(row.max / 1000) * 100}%` }}
                            transition={{ duration: 0.6, delay: i * 0.06 }}
                          />
                        </div>
                        <span className="text-[12px] w-12 text-right" style={{ fontFamily: "var(--font-mono)", color: "var(--treasure)" }}>{row.max}</span>
                      </div>
                    ))}
                    <p className="text-[11px] pt-2" style={{ color: "var(--muted-foreground)" }}>
                      <span style={{ color: "var(--emerald)", fontFamily: "var(--font-mono)" }}>700+</span> = live-trade threshold. Anything below shows up for review only.
                    </p>
                  </div>
                </motion.div>
              </div>
            </div>
          )}

          {/* TAB B — Backtest */}
          {tab === "backtest" && (
            <div className="space-y-4">
              {/* Form */}
              <div className="rounded-xl border border-border obsidian-panel p-5" style={{ background: "var(--card)" }}>
                <h3 className="text-[13px] mb-4" style={{ fontWeight: 500 }}>Configure backtest</h3>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                  {[
                    { label: "Watchlist", value: "Core 8" },
                    { label: "Strategy", value: "Momentum" },
                    { label: "TCS threshold", value: "700+" },
                    { label: "Stop / Target", value: "−5% / +10%" },
                  ].map((f) => (
                    <div key={f.label}>
                      <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>{f.label}</div>
                      <div className="px-3 py-2 rounded-md border border-border text-[13px]" style={{ background: "var(--background)", color: "var(--foreground)" }}>{f.value}</div>
                    </div>
                  ))}
                </div>
                <button
                  className="mt-4 flex items-center gap-1.5 px-4 py-2 rounded-md text-[12px]"
                  style={{ background: "var(--treasure)", color: "var(--background)", fontWeight: 500 }}
                >
                  <Play size={12} /> Run backtest
                </button>
              </div>

              {/* Results */}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                {[
                  { label: "Trades", value: backtestResults.trades.toString() },
                  { label: "Win Rate", value: backtestResults.winRate, color: "var(--emerald)" },
                  { label: "Profit Factor", value: backtestResults.profitFactor, color: "var(--treasure)" },
                  { label: "Total Return", value: backtestResults.totalReturn, color: "var(--emerald)" },
                ].map((stat, i) => (
                  <motion.div
                    key={stat.label}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.06 }}
                    className="rounded-xl border border-border obsidian-panel p-4"
                    style={{ background: "var(--card)" }}
                  >
                    <div className="text-[10px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>{stat.label}</div>
                    <div className="mt-1.5" style={{ fontFamily: "var(--font-mono)", fontSize: "22px", fontWeight: 500, color: stat.color || "var(--foreground)" }}>
                      {stat.value}
                    </div>
                  </motion.div>
                ))}
              </div>

              {/* Equity curve */}
              <div className="rounded-xl border border-border obsidian-panel p-4" style={{ background: "var(--card)" }}>
                <div className="mb-3">
                  <h3 className="text-[13px]" style={{ fontWeight: 500 }}>Equity Curve</h3>
                  <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>$10,000 starting, simulated over 16 weeks</p>
                </div>
                <MiniAreaChart
                  data={backtestResults.equity.map((v, i) => ({ t: `W${i + 1}`, v }))}
                  color="var(--emerald)"
                  height={160}
                  formatValue={(v) => `$${v.toLocaleString()}`}
                />
              </div>
            </div>
          )}

          {/* TAB C — Simulation */}
          {tab === "simulation" && (
            <div className="space-y-4">
              <div className="rounded-xl border border-border obsidian-panel p-5" style={{ background: "var(--card)" }}>
                <h3 className="text-[13px] mb-4" style={{ fontWeight: 500 }}>Stitched simulation</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {[
                    { label: "Watchlist", value: "Core 8" },
                    { label: "Window", value: "14 days" },
                    { label: "Starting Account", value: "$5,000" },
                  ].map((f) => (
                    <div key={f.label}>
                      <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>{f.label}</div>
                      <div className="px-3 py-2 rounded-md border border-border text-[13px]" style={{ background: "var(--background)", color: "var(--foreground)" }}>{f.value}</div>
                    </div>
                  ))}
                </div>
                <button
                  className="mt-4 flex items-center gap-1.5 px-4 py-2 rounded-md text-[12px]"
                  style={{ background: "var(--treasure)", color: "var(--background)", fontWeight: 500 }}
                >
                  <Play size={12} /> Run simulation
                </button>
              </div>

              <div className="rounded-xl border border-border obsidian-panel overflow-hidden" style={{ background: "var(--card)" }}>
                <div className="px-5 py-3 border-b border-border">
                  <h3 className="text-[13px]" style={{ fontWeight: 500 }}>Results — best strategy per ticker</h3>
                </div>
                <table className="w-full text-[12px]">
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border)" }}>
                      {["Ticker", "Best Strategy", "Trades", "Return", ""].map((c) => (
                        <th key={c} className="px-5 py-3 text-left" style={{ color: "var(--muted-foreground)", fontWeight: 500, fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {simResults.map((r, i) => (
                      <motion.tr
                        key={r.ticker}
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.1 + i * 0.05 }}
                        style={{ borderBottom: i < simResults.length - 1 ? "1px solid var(--border)" : "none" }}
                      >
                        <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", fontWeight: 500 }}>{r.ticker}</td>
                        <td className="px-5 py-3" style={{ color: "var(--muted-foreground)" }}>{r.strategy}</td>
                        <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{r.trades}</td>
                        <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: r.return.startsWith("+") ? "var(--emerald)" : "var(--rose)" }}>
                          {r.return}
                        </td>
                        <td className="px-5 py-3">
                          {r.promote ? (
                            <button
                              className="text-[11px] px-2.5 py-1 rounded-md"
                              style={{ background: "rgba(196,150,74,0.15)", color: "var(--treasure)", fontWeight: 500 }}
                            >
                              Promote to Core Winners
                            </button>
                          ) : (
                            <span className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>—</span>
                          )}
                        </td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      <div className="h-4" />
    </div>
  );
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const W = 200, H = 40;
  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * W;
    const y = H - ((v - min) / range) * H;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: "100%" }}>
      <polyline points={points} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}
