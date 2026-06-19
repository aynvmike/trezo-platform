import { Activity, AlertCircle } from "lucide-react";

export type AGAgent = {
  id: number;
  name: string;
  layer: number;
  layerName: string;
  status: string;
  strategy: string;
  openPositions: number;
  todayTrades: number;
  winRate: string;
  avgHold: string;
  lastAction: string;
  lastActionTime: string;
  idleReason?: string;
};

export type AgentsData = { agents: AGAgent[]; live: boolean };

const SAMPLE: AgentsData = {
  live: false,
  agents: [
    { id: 1, name: "Crypto Bot", layer: 1, layerName: "Crypto", status: "active", strategy: "Momentum + RSI reversal on 4H/1H", openPositions: 2, todayTrades: 4, winRate: "73%", avgHold: "2.4h", lastAction: "Opened BTC-PERP long at 67,240", lastActionTime: "15:47" },
    { id: 2, name: "Stock Bot", layer: 2, layerName: "Stock", status: "active", strategy: "Breakout + pullback on daily trend", openPositions: 2, todayTrades: 6, winRate: "68%", avgHold: "1.8d", lastAction: "Partial exit NVDA x5 at 891.45", lastActionTime: "14:32" },
    { id: 3, name: "Options Bot", layer: 3, layerName: "Options", status: "active", strategy: "Directional debit spreads, low IV rank", openPositions: 2, todayTrades: 2, winRate: "61%", avgHold: "4.2d", lastAction: "Opened SPY 560C 06/21 x5", lastActionTime: "13:15" },
    { id: 4, name: "Weekly Stock Bot", layer: 4, layerName: "Stock Weekly", status: "idle", strategy: "Weekly chart patterns only", openPositions: 0, todayTrades: 0, winRate: "72%", avgHold: "5.1d", lastAction: "No entry signal this session", lastActionTime: "-", idleReason: "Waiting for a weekly close above the 20W MA to re-engage" },
    { id: 5, name: "Wheel Bot", layer: 5, layerName: "Wheel", status: "active", strategy: "Cash-secured puts into covered calls cycle", openPositions: 1, todayTrades: 1, winRate: "89%", avgHold: "8.3d", lastAction: "TSLA CSP expired worthless, full premium captured", lastActionTime: "12:58" },
    { id: 6, name: "Dividends Bot", layer: 6, layerName: "Dividends", status: "paused", strategy: "High-yield dividend capture", openPositions: 0, todayTrades: 0, winRate: "94%", avgHold: "22d", lastAction: "Paused, no ex-dividend dates in the next 3 weeks", lastActionTime: "-", idleReason: "Re-activates when SCHD, O, or JEPI ex-div dates fall within 2 weeks" },
    { id: 7, name: "KINDRIP Bot", layer: 7, layerName: "KINDRIP", status: "active", strategy: "Kind and responsible investing, long-only ETFs", openPositions: 3, todayTrades: 1, winRate: "91%", avgHold: "45d", lastAction: "Rebalanced VTI/BND allocation to 70/30", lastActionTime: "10:00" },
  ],
};

const PILL: Record<string, string> = {
  active: "text-emerald-500 bg-emerald-500/10",
  idle: "text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))]",
  paused: "text-amber-500 bg-amber-500/10",
};
const PILL_LABEL: Record<string, string> = { active: "Active", idle: "Idle", paused: "Paused" };
const STAT_COLOR: Record<string, string> = { active: "text-emerald-500", idle: "text-[rgb(var(--muted-foreground))]", paused: "text-amber-500" };

export function AgentsViewRedesign({ data }: { data?: AgentsData }) {
  const d = data ?? SAMPLE;
  const A = d.agents;
  const summary = [
    { label: "Active", value: A.filter((a) => a.status === "active").length, cls: "text-emerald-500" },
    { label: "Idle", value: A.filter((a) => a.status === "idle").length, cls: "text-[rgb(var(--muted-foreground))]" },
    { label: "Paused", value: A.filter((a) => a.status === "paused").length, cls: "text-amber-500" },
    { label: "Open Positions", value: A.reduce((s, a) => s + a.openPositions, 0), cls: "text-[rgb(var(--foreground))]" },
    { label: "Trades Today", value: A.reduce((s, a) => s + a.todayTrades, 0), cls: "text-[rgb(var(--foreground))]" },
  ];
  return (
    <div className="space-y-6 depth-page">
      {d.live ? null : (
        <div className="rounded-lg border border-dashed border-amber-500/40 bg-amber-500/5 px-4 py-2 text-[12px] text-[rgb(var(--muted-foreground))]">
          Design preview &mdash; Neo Obsidian Agents with sample data.
        </div>
      )}

      <div>
        <h1 className="font-serif text-[28px] text-[rgb(var(--foreground))]">Agents</h1>
        <p className="mt-1 text-[13px] text-[rgb(var(--muted-foreground))]">Seven autonomous bots, one per wealth layer</p>
      </div>

      <div className="flex flex-wrap items-center gap-6 depth-card px-4 py-3">
        {summary.map((s) => (
          <div key={s.label} className="flex flex-col">
            <span className={"font-mono text-[20px] font-medium " + s.cls}>{s.value}</span>
            <span className="text-[11px] text-[rgb(var(--muted-foreground))]">{s.label}</span>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {A.map((agent) => (
          <div key={agent.id} className="flex flex-col gap-4 depth-card p-5">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[rgb(var(--muted))]">
                  <span className="font-mono text-[13px] font-medium text-[rgb(var(--muted-foreground))]">{agent.layer}</span>
                </div>
                <div>
                  <div className="text-[13px] font-medium text-[rgb(var(--foreground))]">{agent.name}</div>
                  <div className="text-[11px] text-[rgb(var(--muted-foreground))]">{agent.layerName}</div>
                </div>
              </div>
              <span className={"rounded-full px-2.5 py-1 text-[11px] " + (PILL[agent.status] || PILL.idle)}>{PILL_LABEL[agent.status] || "Idle"}</span>
            </div>

            <p className="text-[12px] text-[rgb(var(--muted-foreground))]">
              <span className="font-medium text-[rgb(var(--foreground))]">Strategy: </span>
              {agent.strategy}
            </p>

            {agent.idleReason ? (
              <div className="flex items-start gap-2 rounded-lg border border-dashed border-[rgb(var(--border))] bg-[rgb(var(--muted))] px-3 py-2">
                <AlertCircle size={13} className="mt-px shrink-0 text-amber-500" />
                <p className="text-[11px] text-[rgb(var(--muted-foreground))]">{agent.idleReason}</p>
              </div>
            ) : null}

            <div className="grid grid-cols-4 gap-2 border-t border-[rgb(var(--border))] pt-1">
              {[
                { label: "Positions", value: agent.openPositions },
                { label: "Trades", value: agent.todayTrades },
                { label: "Win Rate", value: agent.winRate },
                { label: "Avg Hold", value: agent.avgHold },
              ].map((stat) => (
                <div key={stat.label} className="text-center">
                  <div className="font-mono text-[13px] font-medium text-[rgb(var(--foreground))]">{stat.value}</div>
                  <div className="text-[10px] text-[rgb(var(--muted-foreground))]">{stat.label}</div>
                </div>
              ))}
            </div>

            <div className="flex items-center gap-2 text-[11px] text-[rgb(var(--muted-foreground))]">
              <Activity size={11} className={STAT_COLOR[agent.status] || ""} />
              <span className="flex-1 text-[rgb(var(--foreground))]">{agent.lastAction}</span>
              <span className="font-mono">{agent.lastActionTime}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
