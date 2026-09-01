import type { ReactNode } from "react";

type LayerMeta = {
  name: string;
  tagline: string;
  accent: string;
  strategy: string;
  cadence: string;
  risk: string;
};

const LAYER_META: Record<number, LayerMeta> = {
  1: { name: "Crypto Bot", tagline: "24/7 crypto scanner — SCALP / SWING / DCA / HODL by RSI, Bollinger width and volume.", accent: "#c4964a", strategy: "Momentum + RSI reversal", cadence: "24/7", risk: "High" },
  2: { name: "Stock Bot", tagline: "Intraday momentum (STMS) on liquid stocks outside a Wheel cycle.", accent: "#38bdf8", strategy: "Small-cap momentum (STMS)", cadence: "7–11 AM ET", risk: "Medium" },
  3: { name: "Options Engine", tagline: "Directional debit spreads and single-leg options in low IV-rank windows.", accent: "#f59e0b", strategy: "Directional debit spreads", cadence: "Market hours", risk: "High" },
  4: { name: "Stock Weekly", tagline: "Multi-day swings and event plays on the extended window.", accent: "#a78bfa", strategy: "Swing + events", cadence: "8:30 AM–6:30 PM ET", risk: "Medium" },
  5: { name: "Wheel (Options)", tagline: "Cash-secured puts rolling into covered calls on dividend stocks.", accent: "#10b981", strategy: "Cash-secured puts → covered calls", cadence: "Daily", risk: "Low" },
  6: { name: "Dividends", tagline: "High-yield dividend capture and YieldMax income tracking.", accent: "#34d399", strategy: "High-yield dividend capture", cadence: "Ex-div cycles", risk: "Very Low" },
  7: { name: "KINDRIP", tagline: "Long-only, kind and responsible ETFs — the inner vault.", accent: "#c4964a", strategy: "Responsible long-only ETFs", cadence: "Long horizon", risk: "Low" },
};

function money(n: number): string {
  return (n < 0 ? "-" : "+") + "$" + Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="depth-card p-4">
      <p className="text-[11px] text-[rgb(var(--muted-foreground))]">{label}</p>
      <p className="mt-1 font-mono text-[20px] text-[rgb(var(--foreground))]" style={{ fontWeight: 600 }}>{value}</p>
      {sub ? <p className="mt-1 text-[11px] text-[rgb(var(--muted-foreground))]">{sub}</p> : null}
    </div>
  );
}

/**
 * LayerHero — the Figma Neo-Obsidian hero for a wealth-layer page: the
 * numbered ring badge, layer name, status, strategy/cadence/risk row, and
 * a KPI strip. Replaces the plain PageHeader on each layer page, wired to
 * that layer's real numbers. The page's own content stays below.
 */
export function LayerHero({
  id,
  openCount,
  todayPnl,
  weekPnl,
  status,
  action,
}: {
  id: number;
  openCount?: number;
  todayPnl?: number | null;
  weekPnl?: number | null;
  status?: "active" | "idle" | "paused";
  action?: ReactNode;
}) {
  const m = LAYER_META[id] ?? LAYER_META[2];
  // PAGES-05: no data is not "active". A page that passes no openCount
  // (or whose read failed) gets "idle", never a green "Trading" badge.
  const st = status ?? (openCount != null && openCount > 0 ? "active" : "idle");
  const stClass =
    st === "active" ? "text-emerald-500 bg-emerald-500/10"
      : st === "paused" ? "text-amber-500 bg-amber-500/10"
        : "text-[rgb(var(--muted-foreground))] bg-[rgb(var(--muted))]";

  return (
    <div className="space-y-4">
      <div className="depth-card relative overflow-hidden p-6">
        <div
          className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full"
          style={{ background: `radial-gradient(circle, ${m.accent} 0%, transparent 65%)`, opacity: 0.14, filter: "blur(36px)" }}
        />
        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-4">
            <div
              className="grid h-14 w-14 shrink-0 place-items-center rounded-xl font-mono text-[24px]"
              style={{ background: m.accent, color: "rgb(var(--background))", fontWeight: 500, boxShadow: `0 8px 24px ${m.accent}40` }}
            >
              {id}
            </div>
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-treasure-400">Layer {id} of 7</p>
              <h1 className="font-serif text-[28px] leading-tight text-[rgb(var(--foreground))]">{m.name}</h1>
              <p className="mt-1 max-w-md text-[13px] text-[rgb(var(--muted-foreground))]">{m.tagline}</p>
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <span className={"rounded-full px-3 py-1 text-[11px] capitalize " + stClass}>{st}</span>
            {action}
          </div>
        </div>
        <div className="relative mt-6 grid grid-cols-1 gap-4 border-t border-[rgb(var(--border))] pt-5 md:grid-cols-3">
          {[
            { label: "Strategy", value: m.strategy },
            { label: "Cadence", value: m.cadence },
            { label: "Risk bucket", value: m.risk },
          ].map((it) => (
            <div key={it.label}>
              <p className="mb-1 text-[10px] uppercase tracking-wider text-[rgb(var(--muted-foreground))]">{it.label}</p>
              <p className="text-[13px] text-[rgb(var(--foreground))]">{it.value}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="Today's P&L" value={todayPnl == null ? "—" : money(todayPnl)} sub="Realized today" />
        <Tile label="Week P&L" value={weekPnl == null ? "—" : money(weekPnl)} sub="Rolling 7-day" />
        <Tile label="Open positions" value={openCount == null ? "—" : String(openCount)} sub="Live in this layer" />
        <Tile label="Status" value={st === "active" ? "Trading" : st === "paused" ? "Paused" : "Idle"} sub={m.cadence} />
      </div>
    </div>
  );
}
