import { WovenBasketHero, type HeroLayer } from "@/components/dashboard/woven-basket-hero";
import { DepthTilt } from "@/components/dashboard/depth-tilt";

export type OVLayer = {
  id: number;
  name: string;
  status: string;
  pnl: number;
  agents: number;
  risk: string;
  idleReason?: string;
};

export type OVActivity = {
  total: number;
  counts: Record<string, number>;
  last: { ts: string | null; event: string | null; ticker: string | null; reason: string | null }[];
};

export type OverviewData = {
  portfolioValue: number;
  weekPnl: number;
  todayPnl: number;
  deployed: number;
  deployedPct: number | null;
  layersActive: number;
  week: { d: string; v: number }[];
  layers: OVLayer[];
  live: boolean;
  agentsOnline: boolean;
  buyingPower: number | null;
  stale: boolean;
  asOf: string | null;
  activity?: OVActivity | null;
};

const SAMPLE: OverviewData = {
  portfolioValue: 142380,
  weekPnl: 3227,
  todayPnl: 2147,
  deployed: 8420,
  deployedPct: 5.9,
  layersActive: 5,
  week: [
    { d: "Mon", v: 380 },
    { d: "Tue", v: 820 },
    { d: "Wed", v: -120 },
    { d: "Thu", v: 2147 },
    { d: "Fri", v: 0 },
  ],
  layers: [
    { id: 1, name: "Crypto", status: "active", pnl: 417.5, agents: 1, risk: "High" },
    { id: 2, name: "Stock", status: "active", pnl: 221.25, agents: 1, risk: "Medium" },
    { id: 3, name: "Options", status: "active", pnl: 545.0, agents: 1, risk: "High" },
    { id: 4, name: "Stock Weekly", status: "idle", pnl: 0, agents: 0, risk: "Low", idleReason: "Waiting for entry signal" },
    { id: 5, name: "Wheel", status: "active", pnl: 180.0, agents: 1, risk: "Low" },
    { id: 6, name: "Dividends", status: "paused", pnl: 0, agents: 0, risk: "Very Low", idleReason: "Ex-div dates 3 weeks out" },
    { id: 7, name: "KINDRIP", status: "active", pnl: 92.0, agents: 1, risk: "Low" },
  ],
  live: false,
  agentsOnline: false,
  buyingPower: null,
  stale: false,
  asOf: null,
  activity: null,
};

const STATUS_TEXT: Record<string, string> = {
  active: "text-emerald-500",
  idle: "text-[rgb(var(--muted-foreground))]",
  paused: "text-amber-500",
};
const STATUS_DOT: Record<string, string> = {
  active: "bg-emerald-500",
  idle: "bg-[rgb(var(--muted-foreground))]",
  paused: "bg-amber-500",
};

function money(n: number) {
  return (n < 0 ? "-" : "+") + "$" + Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function money0(n: number) {
  return (n < 0 ? "-" : "") + "$" + Math.abs(Math.round(n)).toLocaleString();
}
function agoLabel(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 60_000) return "just now";
  if (ms < 3_600_000) return Math.floor(ms / 60_000) + "m ago";
  if (ms < 86_400_000) return Math.floor(ms / 3_600_000) + "h ago";
  return Math.floor(ms / 86_400_000) + "d ago";
}
function signed0(n: number) {
  return (n >= 0 ? "+" : "-") + "$" + Math.abs(Math.round(n)).toLocaleString();
}

function Kpi(props: { label: string; value: string; sub: string; pill?: string; pillClass?: string; delta?: string; up?: boolean }) {
  return (
    <div className="depth-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-[rgb(var(--muted-foreground))]">{props.label}</span>
        {props.pill ? <span className={"rounded-full px-1.5 py-0.5 font-mono text-[10px] " + (props.pillClass || "text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))]")}>{props.pill}</span> : null}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="font-mono text-[22px] text-[rgb(var(--foreground))]" style={{ fontWeight: 600 }}>{props.value}</span>
        {props.delta ? <span className={"font-mono text-[12px] " + (props.up ? "text-emerald-500" : "text-red-500")}>{props.up ? "▲" : "▼"} {props.delta}</span> : null}
      </div>
      <p className="mt-1 text-[11px] text-[rgb(var(--muted-foreground))]">{props.sub}</p>
    </div>
  );
}

function GoldSparkline({ data }: { data: number[] }) {
  const w = 600;
  const h = 140;
  const pad = 8;
  const safe = data.length >= 2 ? data : [0, 0];
  const min = Math.min(...safe, 0);
  const max = Math.max(...safe, 0);
  const span = max - min || 1;
  const pts = safe.map((v, i) => {
    const x = (i / (safe.length - 1)) * w;
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return x.toFixed(1) + " " + y.toFixed(1);
  });
  const line = "M " + pts.join(" L ");
  const area = line + " L " + w + " " + h + " L 0 " + h + " Z";
  return (
    <svg viewBox={"0 0 " + w + " " + h} className="w-full" style={{ height: 140 }} preserveAspectRatio="none">
      <defs>
        <linearGradient id="weekg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgb(var(--primary))" stopOpacity={0.28} />
          <stop offset="100%" stopColor="rgb(var(--primary))" stopOpacity={0.02} />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#weekg)" />
      <path d={line} fill="none" stroke="rgb(var(--primary))" strokeWidth={2} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function OverviewViewRedesign({ data }: { data?: OverviewData }) {
  const d = data ?? SAMPLE;
  const total = d.layers.reduce((s, l) => s + l.pnl, 0);
  const heroLayers: HeroLayer[] = d.layers.map((l) => ({ id: l.id, name: l.name, status: l.status, pnl: l.pnl }));
  const withPnl = d.layers.filter((l) => l.pnl !== 0);
  return (
    <div className="space-y-8 depth-page">
      {d.live ? null : (
        <div className="rounded-lg border border-dashed border-amber-500/40 bg-amber-500/5 px-4 py-2 text-[12px] text-[rgb(var(--muted-foreground))]">
          Design preview &mdash; Neo Obsidian Overview with sample data.
        </div>
      )}

      <div>
        <h1 className="font-serif text-[28px] text-[rgb(var(--foreground))]">Overview</h1>
        <p className="mt-1 text-[13px] text-[rgb(var(--muted-foreground))]">At-a-glance health across all seven wealth layers</p>
      </div>

      {d.live ? (
        <div className="depth-card flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 text-[12px]">
          <span className="flex items-center gap-1.5">
            <span className={"h-2 w-2 rounded-full " + (d.agentsOnline ? "bg-emerald-500" : "bg-red-500")} />
            <span className="text-[rgb(var(--muted-foreground))]">Agents</span>
            <span className={"font-medium " + (d.agentsOnline ? "text-emerald-500" : "text-red-500")}>{d.agentsOnline ? "Live" : "Offline"}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="text-[rgb(var(--muted-foreground))]">Buying power</span>
            <span className="font-mono font-medium text-[rgb(var(--foreground))]">{d.buyingPower != null ? money0(d.buyingPower) : "—"}</span>
          </span>
          {d.agentsOnline ? (
            d.buyingPower === 0 ? (
              <span className="text-[11px] text-[rgb(var(--muted-foreground))]">Agents are live, but the account has $0 buying power to trade.</span>
            ) : null
          ) : d.stale ? (
            <span className="text-[11px] text-amber-500">Showing last known data{d.asOf ? " · as of " + agoLabel(d.asOf) : ""} — agents offline. Start the service on port 8001 for live numbers.</span>
          ) : (
            <span className="text-[11px] text-[rgb(var(--muted-foreground))]">Live numbers unavailable while the agents service is offline (start it on port 8001).</span>
          )}
        </div>
      ) : null}

      <DepthTilt><WovenBasketHero layers={heroLayers} /></DepthTilt>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Portfolio Value" value={money0(d.portfolioValue)} sub="All layers combined" pill={!d.live ? "Sample" : d.agentsOnline ? "Live" : d.stale ? "Last known" : "Offline"} pillClass={!d.live ? "text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))]" : d.agentsOnline ? "text-emerald-500 bg-emerald-500/10" : d.stale ? "text-amber-500 bg-amber-500/10" : "text-red-500 bg-red-500/10"} />
        <Kpi label="Week P&L" value={signed0(d.weekPnl)} up={d.weekPnl >= 0} sub="Realized, last 7 days" />
        <Kpi label="Total Open Risk" value={money0(d.deployed)} sub={d.deployedPct != null ? d.deployedPct.toFixed(1) + "% of portfolio deployed" : "Capital in open positions"} />
        <Kpi label="Layers Active" value={d.layersActive + " / 7"} sub="Layers holding a position now" />
      </div>

      {d.activity && d.activity.total > 0 ? (
        <div className="depth-card p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-[13px] font-medium text-[rgb(var(--foreground))]">Agent Activity Today</h3>
              <p className="text-[11px] text-[rgb(var(--muted-foreground))]">Every decision the agents made — straight from the activity log</p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {[
                ["approve", "approvals", "text-emerald-500 bg-emerald-500/10"],
                ["submitted", "orders", "text-emerald-500 bg-emerald-500/10"],
                ["veto", "vetoes", "text-red-400 bg-red-500/10"],
                ["pocket_skip", "pocket skips", "text-amber-500 bg-amber-500/10"],
                ["profit_step", "profit steps", "text-emerald-500 bg-emerald-500/10"],
                ["reeval_check", "re-checks", "text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))]"],
              ].map(([key, lbl, cls]) =>
                d.activity!.counts[key] ? (
                  <span key={key} className={"rounded-full px-2 py-0.5 font-mono text-[10px] " + cls}>
                    {d.activity!.counts[key]} {lbl}
                  </span>
                ) : null
              )}
            </div>
          </div>
          <div className="space-y-1.5">
            {d.activity.last.slice(0, 8).map((ev, i) => (
              <div key={i} className="flex items-baseline gap-2 text-[11px]">
                <span className="shrink-0 font-mono text-[10px] text-[rgb(var(--muted-foreground))]">
                  {ev.ts ? String(ev.ts).slice(11, 16) + "Z" : "--:--"}
                </span>
                <span className={"shrink-0 rounded px-1.5 font-mono text-[10px] " + (ev.event === "approve" || ev.event === "submitted" || ev.event === "profit_step" ? "text-emerald-500 bg-emerald-500/10" : ev.event === "veto" ? "text-red-400 bg-red-500/10" : ev.event === "pocket_skip" ? "text-amber-500 bg-amber-500/10" : "text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))]")}>
                  {ev.event}
                </span>
                <span className="shrink-0 font-mono font-medium text-[rgb(var(--foreground))]">{ev.ticker}</span>
                <span className="truncate text-[rgb(var(--muted-foreground))]">{ev.reason}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="depth-card p-4 md:col-span-2">
          <div className="mb-4">
            <h3 className="text-[13px] font-medium text-[rgb(var(--foreground))]">{"Week P&L"}</h3>
            <p className="text-[11px] text-[rgb(var(--muted-foreground))]">Daily realized net, last 7 days</p>
          </div>
          <GoldSparkline data={d.week.map((x) => x.v)} />
        </div>
        <div className="depth-card p-4">
          <h3 className="text-[13px] font-medium text-[rgb(var(--foreground))]">P&L by Layer</h3>
          <p className="mb-3 text-[11px] text-[rgb(var(--muted-foreground))]">{d.live ? "Open positions, mark-to-market" : "Breakdown by layer"}</p>
          <div className="space-y-2">
            {withPnl.length === 0 ? (
              <p className="text-[12px] italic text-[rgb(var(--muted-foreground))]">No open P&L across the layers right now.</p>
            ) : withPnl.map((l) => (
              <div key={l.id} className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded bg-[rgb(var(--muted))] font-mono text-[10px] text-[rgb(var(--muted-foreground))]">{l.id}</span>
                  <span className="text-[12px] text-[rgb(var(--foreground))]">{l.name}</span>
                </div>
                <span className={"font-mono text-[12px] font-medium " + (l.pnl >= 0 ? "text-emerald-500" : "text-red-500")}>{money(l.pnl)}</span>
              </div>
            ))}
            <div className="mt-2 flex items-center justify-between border-t border-[rgb(var(--border))] pt-2">
              <span className="text-[12px] font-medium text-[rgb(var(--muted-foreground))]">Total</span>
              <span className={"font-mono text-[13px] font-medium " + (total >= 0 ? "text-emerald-500" : "text-red-500")}>{money(total)}</span>
            </div>
          </div>
        </div>
      </div>

      <div>
        <h2 className="mb-3 font-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-treasure-400">Wealth Layers</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {d.layers.map((layer) => (
            <div key={layer.id} className="flex flex-col gap-2.5 depth-card p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="flex h-5 w-5 items-center justify-center rounded bg-[rgb(var(--muted))] font-mono text-[11px] font-medium text-[rgb(var(--muted-foreground))]">{layer.id}</span>
                  <span className="text-[13px] font-medium text-[rgb(var(--foreground))]">{layer.name}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className={"h-1.5 w-1.5 rounded-full " + (STATUS_DOT[layer.status] || "bg-[rgb(var(--muted-foreground))]")} />
                  <span className={"text-[11px] capitalize " + (STATUS_TEXT[layer.status] || "text-[rgb(var(--muted-foreground))]")}>{layer.status}</span>
                </div>
              </div>
              {layer.pnl !== 0 ? (
                <div>
                  <div className={"font-mono text-[18px] font-medium " + (layer.pnl >= 0 ? "text-emerald-500" : "text-red-500")}>{money(layer.pnl)}</div>
                  <div className="text-[11px] text-[rgb(var(--muted-foreground))]">open P&L</div>
                </div>
              ) : (
                <div>
                  <div className="text-[13px] italic text-[rgb(var(--muted-foreground))]">No position today</div>
                  {layer.idleReason ? <div className="mt-0.5 text-[11px] text-[rgb(var(--muted-foreground))]">{layer.idleReason}</div> : null}
                </div>
              )}
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-[rgb(var(--muted-foreground))]">Risk: {layer.risk}</span>
                <span className="text-[11px] text-[rgb(var(--muted-foreground))]">{layer.agents} agent{layer.agents !== 1 ? "s" : ""}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
