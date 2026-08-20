import { motion } from "motion/react";
import { Activity, AlertCircle } from "lucide-react";

const agents = [
  {
    id: 1, name: "Crypto Bot", layer: 1, layerName: "Crypto",
    status: "active", strategy: "Momentum + RSI reversal on 4H/1H",
    openPositions: 2, todayTrades: 4, winRate: "73%", avgHold: "2.4h",
    lastAction: "Opened BTC-PERP long at 67,240",
    lastActionTime: "15:47",
  },
  {
    id: 2, name: "Stock Bot", layer: 2, layerName: "Stock",
    status: "active", strategy: "Breakout + pullback on daily trend",
    openPositions: 2, todayTrades: 6, winRate: "68%", avgHold: "1.8d",
    lastAction: "Partial exit NVDA ×5 at 891.45",
    lastActionTime: "14:32",
  },
  {
    id: 3, name: "Options Bot", layer: 3, layerName: "Options",
    status: "active", strategy: "Directional debit spreads, low IV rank",
    openPositions: 2, todayTrades: 2, winRate: "61%", avgHold: "4.2d",
    lastAction: "Opened SPY 560C 06/21 ×5",
    lastActionTime: "13:15",
  },
  {
    id: 4, name: "Weekly Stock Bot", layer: 4, layerName: "Stock Weekly",
    status: "idle", strategy: "Weekly chart patterns only",
    openPositions: 0, todayTrades: 0, winRate: "72%", avgHold: "5.1d",
    lastAction: "No entry signal this session",
    lastActionTime: "—",
    idleReason: "Waiting for a weekly close above the 20W MA to re-engage",
  },
  {
    id: 5, name: "Wheel Bot", layer: 5, layerName: "Wheel",
    status: "active", strategy: "Cash-secured puts → covered calls cycle",
    openPositions: 1, todayTrades: 1, winRate: "89%", avgHold: "8.3d",
    lastAction: "TSLA CSP expired worthless — full premium captured",
    lastActionTime: "12:58",
  },
  {
    id: 6, name: "Dividends Bot", layer: 6, layerName: "Dividends",
    status: "paused", strategy: "High-yield dividend capture",
    openPositions: 0, todayTrades: 0, winRate: "94%", avgHold: "22d",
    lastAction: "Paused — no ex-dividend dates in the next 3 weeks",
    lastActionTime: "—",
    idleReason: "Will re-activate when SCHD, O, or JEPI ex-div dates fall within 2 weeks",
  },
  {
    id: 7, name: "KINDRIP Bot", layer: 7, layerName: "KINDRIP",
    status: "active", strategy: "Kind & responsible investing, long-only ETFs",
    openPositions: 3, todayTrades: 1, winRate: "91%", avgHold: "45d",
    lastAction: "Rebalanced VTI/BND allocation to 70/30",
    lastActionTime: "10:00",
  },
];

const statusStyles: Record<string, { color: string; bg: string; label: string }> = {
  active: { color: "var(--emerald)", bg: "rgba(16,185,129,0.1)", label: "Active" },
  idle: { color: "var(--muted-foreground)", bg: "var(--muted)", label: "Idle" },
  paused: { color: "var(--amber)", bg: "rgba(245,158,11,0.1)", label: "Paused" },
};

export function AgentsView() {
  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
      <div>
        <h1 style={{ fontFamily: "var(--font-serif)", color: "var(--foreground)" }}>Agents</h1>
        <p className="text-[13px] mt-1" style={{ color: "var(--muted-foreground)" }}>
          Seven autonomous bots — one per wealth layer
        </p>
      </div>

      {/* Summary row */}
      <div className="flex items-center gap-6 py-3 px-4 rounded-xl border border-border obsidian-panel" style={{ background: "var(--card)" }}>
        {[
          { label: "Active", value: agents.filter(a => a.status === "active").length, color: "var(--emerald)" },
          { label: "Idle", value: agents.filter(a => a.status === "idle").length, color: "var(--muted-foreground)" },
          { label: "Paused", value: agents.filter(a => a.status === "paused").length, color: "var(--amber)" },
          { label: "Open Positions", value: agents.reduce((s, a) => s + a.openPositions, 0), color: "var(--foreground)" },
          { label: "Trades Today", value: agents.reduce((s, a) => s + a.todayTrades, 0), color: "var(--foreground)" },
        ].map((stat) => (
          <div key={stat.label} className="flex flex-col">
            <span className="text-[20px]" style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: stat.color }}>
              {stat.value}
            </span>
            <span className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{stat.label}</span>
          </div>
        ))}
      </div>

      {/* Agent cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {agents.map((agent, i) => {
          const style = statusStyles[agent.status];
          return (
            <motion.div
              key={agent.id}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.38, delay: i * 0.07, ease: [0.22, 1, 0.36, 1] }}
              whileHover={{ y: -2, transition: { duration: 0.18 } }}
              className="rounded-xl border border-border obsidian-panel p-5 flex flex-col gap-4"
              style={{ background: "var(--card)" }}
            >
              {/* Header */}
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                    style={{ background: "var(--muted)" }}
                  >
                    <span className="text-[13px]" style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", fontWeight: 500 }}>
                      {agent.layer}
                    </span>
                  </div>
                  <div>
                    <div className="text-[13px]" style={{ fontWeight: 500 }}>{agent.name}</div>
                    <div className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{agent.layerName}</div>
                  </div>
                </div>
                <span
                  className="text-[11px] px-2.5 py-1 rounded-full"
                  style={{ background: style.bg, color: style.color }}
                >
                  {style.label}
                </span>
              </div>

              {/* Strategy */}
              <p className="text-[12px]" style={{ color: "var(--muted-foreground)" }}>
                <span style={{ color: "var(--foreground)", fontWeight: 500 }}>Strategy: </span>
                {agent.strategy}
              </p>

              {/* Idle reason */}
              {agent.idleReason && (
                <div className="flex items-start gap-2 px-3 py-2 rounded-lg border border-dashed" style={{ borderColor: "var(--border)", background: "var(--muted)" }}>
                  <AlertCircle size={13} style={{ color: "var(--amber)", shrink: 0, marginTop: "1px" }} />
                  <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{agent.idleReason}</p>
                </div>
              )}

              {/* Stats */}
              <div className="grid grid-cols-4 gap-2 pt-1 border-t border-border">
                {[
                  { label: "Positions", value: agent.openPositions },
                  { label: "Trades", value: agent.todayTrades },
                  { label: "Win Rate", value: agent.winRate },
                  { label: "Avg Hold", value: agent.avgHold },
                ].map((stat) => (
                  <div key={stat.label} className="text-center">
                    <div className="text-[13px]" style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: "var(--foreground)" }}>
                      {stat.value}
                    </div>
                    <div className="text-[10px]" style={{ color: "var(--muted-foreground)" }}>{stat.label}</div>
                  </div>
                ))}
              </div>

              {/* Last action */}
              <div className="flex items-center gap-2 text-[11px]" style={{ color: "var(--muted-foreground)" }}>
                <Activity size={11} />
                <span className="flex-1" style={{ color: "var(--foreground)" }}>{agent.lastAction}</span>
                <span style={{ fontFamily: "var(--font-mono)" }}>{agent.lastActionTime}</span>
              </div>
            </motion.div>
          );
        })}
      </div>

      <div className="h-4" />
    </div>
  );
}
