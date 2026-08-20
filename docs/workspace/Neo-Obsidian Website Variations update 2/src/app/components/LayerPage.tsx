import { motion } from "motion/react";
import { Activity, AlertCircle, Pause, Play, ChevronRight, TrendingUp } from "lucide-react";
import { KpiTile } from "./KpiTile";
import { MiniAreaChart } from "./MiniAreaChart";

export type LayerData = {
  id: number;
  name: string;
  tagline: string;
  status: "active" | "idle" | "paused";
  accent: string;
  strategy: string;
  cadence: string;
  riskBucket: string;
  todayPnl: number;
  weekPnl: number;
  openPositions: number;
  winRate: string;
  avgHold: string;
  trades30d: number;
  capitalAllocated: number;
  capitalUsed: number;
  pnlSeries: { t: string; v: number }[];
  positions: { ticker: string; side: "LONG" | "SHORT"; entry: number; current: number; qty: number; pnl: number; pct: number }[];
  signals: {
    ticker: string;
    bias: "Bullish" | "Bearish";
    type: string;
    strikeExpiry?: string;
    entry: string;
    exit: string;
    stop: string;
    confidence: number;
    reasoning: string;
  }[];
  activity: { time: string; action: string; reason: string; type: "open" | "exit" | "alert" }[];
  idleReason?: string;
};

const statusStyles: Record<string, { color: string; bg: string; label: string }> = {
  active: { color: "var(--emerald)", bg: "rgba(16,185,129,0.12)", label: "Active" },
  idle: { color: "var(--muted-foreground)", bg: "var(--muted)", label: "Idle" },
  paused: { color: "var(--amber)", bg: "rgba(245,158,11,0.12)", label: "Paused" },
};

const actionTypeColors: Record<string, string> = {
  open: "var(--emerald)",
  exit: "var(--sky)",
  alert: "var(--amber)",
};

export function LayerPage({ data }: { data: LayerData }) {
  const status = statusStyles[data.status];
  const capacityPct = (data.capitalUsed / data.capitalAllocated) * 100;

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-8">

      {/* Hero — layer identity */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        className="relative rounded-2xl border border-border obsidian-panel overflow-hidden p-6"
        style={{ background: "var(--card)" }}
      >
        {/* Accent glow */}
        <motion.div
          className="absolute rounded-full pointer-events-none"
          style={{
            width: 320, height: 320,
            right: "-80px", top: "-80px",
            background: `radial-gradient(circle, ${data.accent} 0%, transparent 65%)`,
            opacity: 0.14, filter: "blur(40px)",
          }}
          animate={{ scale: [1, 1.15, 1] }}
          transition={{ duration: 6, repeat: Infinity, ease: "easeInOut" }}
        />

        <div className="relative flex items-start justify-between gap-6">
          <div className="flex items-start gap-4">
            <motion.div
              className="w-14 h-14 rounded-xl flex items-center justify-center text-[24px]"
              style={{
                background: data.accent,
                color: "var(--background)",
                fontFamily: "var(--font-mono)",
                fontWeight: 500,
                boxShadow: `0 8px 24px ${data.accent}40`,
              }}
              animate={{ boxShadow: [`0 8px 24px ${data.accent}30`, `0 8px 32px ${data.accent}50`, `0 8px 24px ${data.accent}30`] }}
              transition={{ duration: 3.2, repeat: Infinity, ease: "easeInOut" }}
            >
              {data.id}
            </motion.div>
            <div>
              <div className="text-[10px] uppercase tracking-widest mb-1" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
                Layer {data.id} of 7
              </div>
              <h1 style={{ fontFamily: "var(--font-serif)", fontSize: "28px", fontWeight: 500, lineHeight: 1.1 }}>
                {data.name}
              </h1>
              <p className="text-[13px] mt-1 max-w-md" style={{ color: "var(--muted-foreground)" }}>
                {data.tagline}
              </p>
            </div>
          </div>

          <div className="flex flex-col items-end gap-2">
            <span
              className="text-[11px] px-3 py-1 rounded-full"
              style={{ background: status.bg, color: status.color }}
            >
              {status.label}
            </span>
            <button
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border text-[12px] transition-colors hover:bg-muted"
              style={{ color: "var(--muted-foreground)" }}
            >
              {data.status === "active" ? <Pause size={12} /> : <Play size={12} />}
              {data.status === "active" ? "Pause" : "Resume"}
            </button>
          </div>
        </div>

        {/* Idle reason banner */}
        {data.idleReason && (
          <div className="relative mt-4 flex items-start gap-2 px-3 py-2 rounded-lg border border-dashed" style={{ borderColor: "var(--border)", background: "var(--muted)" }}>
            <AlertCircle size={13} style={{ color: "var(--amber)", marginTop: "1px", flexShrink: 0 }} />
            <p className="text-[12px]" style={{ color: "var(--muted-foreground)" }}>{data.idleReason}</p>
          </div>
        )}

        {/* Strategy + cadence + risk row */}
        <div className="relative mt-6 grid grid-cols-1 md:grid-cols-3 gap-4 pt-5 border-t border-border">
          {[
            { label: "Strategy", value: data.strategy },
            { label: "Cadence", value: data.cadence },
            { label: "Risk bucket", value: data.riskBucket },
          ].map((item) => (
            <div key={item.label}>
              <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
                {item.label}
              </div>
              <div className="text-[13px]" style={{ color: "var(--foreground)" }}>{item.value}</div>
            </div>
          ))}
        </div>
      </motion.div>

      {/* KPIs */}
      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiTile
          index={0}
          label="Today's P&L"
          value={`${data.todayPnl >= 0 ? "+" : ""}$${Math.abs(data.todayPnl).toFixed(2)}`}
          sub="Realized + unrealized today"
        />
        <KpiTile
          index={1}
          label="Week P&L"
          value={`${data.weekPnl >= 0 ? "+" : ""}$${Math.abs(data.weekPnl).toFixed(2)}`}
          sub="Rolling 7-day net"
        />
        <KpiTile
          index={2}
          label="Open Positions"
          value={`${data.openPositions}`}
          sub={`Win rate ${data.winRate} · avg hold ${data.avgHold}`}
        />
        <KpiTile
          index={3}
          label="30d Trades"
          value={`${data.trades30d}`}
          sub={`Avg ${(data.trades30d / 30).toFixed(1)}/day`}
        />
      </section>

      {/* Chart + capacity */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="md:col-span-2 rounded-xl border border-border obsidian-panel p-4" style={{ background: "var(--card)" }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-[13px]" style={{ fontWeight: 500 }}>P&L Trend</h3>
              <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>Cumulative over the last 14 sessions</p>
            </div>
            <span
              style={{
                color: data.pnlSeries[data.pnlSeries.length - 1].v >= 0 ? "var(--emerald)" : "var(--rose)",
                fontFamily: "var(--font-mono)",
                fontSize: "13px",
              }}
            >
              {data.pnlSeries[data.pnlSeries.length - 1].v >= 0 ? "+" : ""}${data.pnlSeries[data.pnlSeries.length - 1].v}
            </span>
          </div>
          <MiniAreaChart
            data={data.pnlSeries}
            color={data.pnlSeries[data.pnlSeries.length - 1].v >= 0 ? "var(--emerald)" : "var(--rose)"}
            height={150}
            formatValue={(v) => `${v >= 0 ? "+" : ""}$${Math.abs(v)}`}
          />
        </div>

        {/* Capacity */}
        <div className="rounded-xl border border-border obsidian-panel p-4" style={{ background: "var(--card)" }}>
          <h3 className="text-[13px] mb-1" style={{ fontWeight: 500 }}>Capital Allocated</h3>
          <p className="text-[11px] mb-4" style={{ color: "var(--muted-foreground)" }}>Per-layer sleeve capacity</p>
          <div className="flex items-end justify-between mb-2">
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "20px", fontWeight: 500, color: "var(--foreground)" }}>
              ${data.capitalUsed.toLocaleString()}
            </span>
            <span className="text-[11px]" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
              of ${data.capitalAllocated.toLocaleString()}
            </span>
          </div>
          <div className="relative h-2 rounded-full overflow-hidden" style={{ background: "var(--muted)" }}>
            <motion.div
              className="absolute top-0 left-0 h-full rounded-full"
              style={{ background: data.accent }}
              initial={{ width: 0 }}
              animate={{ width: `${capacityPct}%` }}
              transition={{ duration: 0.9, delay: 0.3, ease: [0.22, 1, 0.36, 1] }}
            />
          </div>
          <div className="flex items-center justify-between mt-2 text-[10px]" style={{ color: "var(--muted-foreground)" }}>
            <span style={{ fontFamily: "var(--font-mono)" }}>{capacityPct.toFixed(0)}% deployed</span>
            <span style={{ fontFamily: "var(--font-mono)" }}>${(data.capitalAllocated - data.capitalUsed).toLocaleString()} free</span>
          </div>
        </div>
      </section>

      {/* Open positions */}
      {data.positions.length > 0 && (
        <section>
          <div className="rounded-xl border border-border obsidian-panel overflow-hidden" style={{ background: "var(--card)" }}>
            <div className="px-5 py-4 border-b border-border flex items-center justify-between">
              <div>
                <h3 className="text-[13px]" style={{ fontWeight: 500 }}>Open Positions</h3>
                <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>Live in this layer right now</p>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border)" }}>
                    {["Ticker", "Side", "Entry", "Current", "Qty", "P&L"].map((c) => (
                      <th key={c} className="px-5 py-3 text-left" style={{ color: "var(--muted-foreground)", fontWeight: 500, fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.positions.map((p, i) => (
                    <motion.tr
                      key={i}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.3, delay: 0.2 + i * 0.05, ease: [0.22, 1, 0.36, 1] }}
                      style={{ borderBottom: i < data.positions.length - 1 ? "1px solid var(--border)" : "none" }}
                      onMouseEnter={e => (e.currentTarget.style.background = "var(--muted)")}
                      onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
                    >
                      <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", fontWeight: 500 }}>{p.ticker}</td>
                      <td className="px-5 py-3">
                        <span
                          className="text-[11px] px-1.5 py-0.5 rounded"
                          style={{
                            background: p.side === "LONG" ? "rgba(16,185,129,0.12)" : "rgba(244,63,94,0.12)",
                            color: p.side === "LONG" ? "var(--emerald)" : "var(--rose)",
                            fontFamily: "var(--font-mono)",
                          }}
                        >
                          {p.side}
                        </span>
                      </td>
                      <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                        ${p.entry.toLocaleString()}
                      </td>
                      <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)" }}>${p.current.toLocaleString()}</td>
                      <td className="px-5 py-3" style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{p.qty}</td>
                      <td className="px-5 py-3">
                        <span style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: p.pnl >= 0 ? "var(--emerald)" : "var(--rose)" }}>
                          {p.pnl >= 0 ? "+" : ""}${p.pnl.toFixed(2)}
                        </span>
                        <span className="text-[10px] ml-1.5" style={{ color: p.pct >= 0 ? "var(--emerald)" : "var(--rose)", fontFamily: "var(--font-mono)", opacity: 0.75 }}>
                          {p.pct >= 0 ? "+" : ""}{p.pct.toFixed(2)}%
                        </span>
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      {/* Signal cards */}
      {data.signals.length > 0 && (
        <section>
          <h2 className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
            Active Signals
          </h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {data.signals.map((s, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, delay: 0.1 + i * 0.07 }}
                whileHover={{ y: -2 }}
                className="rounded-xl border border-border obsidian-panel p-4 flex flex-col gap-3"
                style={{ background: "var(--card)" }}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span style={{ fontFamily: "var(--font-mono)", fontWeight: 500, fontSize: "14px" }}>{s.ticker}</span>
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded"
                        style={{
                          background: s.bias === "Bullish" ? "rgba(16,185,129,0.12)" : "rgba(244,63,94,0.12)",
                          color: s.bias === "Bullish" ? "var(--emerald)" : "var(--rose)",
                          fontFamily: "var(--font-mono)",
                        }}
                      >
                        {s.bias.toUpperCase()}
                      </span>
                    </div>
                    <div className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
                      {s.type}{s.strikeExpiry ? ` · ${s.strikeExpiry}` : ""}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 px-2 py-1 rounded-md" style={{ background: "rgba(196,150,74,0.1)" }}>
                    <TrendingUp size={11} style={{ color: "var(--treasure)" }} />
                    <span className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: "var(--treasure)", fontWeight: 500 }}>
                      {s.confidence}/10
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2 py-2 border-y border-border">
                  {[
                    { l: "Entry", v: s.entry },
                    { l: "Target", v: s.exit },
                    { l: "Stop", v: s.stop },
                  ].map((row) => (
                    <div key={row.l}>
                      <div className="text-[9px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>{row.l}</div>
                      <div className="text-[11px] mt-0.5" style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>{row.v}</div>
                    </div>
                  ))}
                </div>

                <p className="text-[12px] leading-relaxed" style={{ color: "var(--muted-foreground)" }}>{s.reasoning}</p>
              </motion.div>
            ))}
          </div>
        </section>
      )}

      {/* Activity feed */}
      {data.activity.length > 0 && (
        <section>
          <div className="rounded-xl border border-border obsidian-panel overflow-hidden" style={{ background: "var(--card)" }}>
            <div className="px-5 py-4 border-b border-border">
              <h3 className="text-[13px]" style={{ fontWeight: 500 }}>Recent Activity</h3>
              <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>What this bot has been doing</p>
            </div>
            <div>
              {data.activity.map((row, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.3, delay: 0.15 + i * 0.06 }}
                  className="px-5 py-3.5 flex items-start gap-4 transition-colors hover:bg-muted/50"
                  style={{ borderBottom: i < data.activity.length - 1 ? "1px solid var(--border)" : "none" }}
                >
                  <span className="text-[11px] shrink-0 mt-0.5" style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", minWidth: "36px" }}>
                    {row.time}
                  </span>
                  <div className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0" style={{ background: actionTypeColors[row.type] }} />
                  <div className="flex-1 min-w-0">
                    <div className="text-[12px]" style={{ fontWeight: 500 }}>{row.action}</div>
                    <p className="text-[12px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>{row.reason}</p>
                  </div>
                </motion.div>
              ))}
            </div>
          </div>
        </section>
      )}

      <div className="h-4" />
    </div>
  );
}
