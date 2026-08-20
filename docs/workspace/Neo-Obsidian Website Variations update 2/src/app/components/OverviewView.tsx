import { motion } from "motion/react";
import { KpiTile } from "./KpiTile";
import { MiniAreaChart } from "./MiniAreaChart";
import { WovenBasketHero } from "./WovenBasketHero";

const weekPnl = [
  { t: "Mon", v: 380 }, { t: "Tue", v: 820 }, { t: "Wed", v: -120 },
  { t: "Thu", v: 2147 }, { t: "Fri", v: 0 },
];

const layers = [
  { id: 1, name: "Crypto", status: "active", pnl: +417.50, agents: 1, risk: "High" },
  { id: 2, name: "Stock", status: "active", pnl: +221.25, agents: 1, risk: "Medium" },
  { id: 3, name: "Options", status: "active", pnl: +545.00, agents: 1, risk: "High" },
  { id: 4, name: "Stock Weekly", status: "idle", pnl: 0, agents: 0, risk: "Low", idleReason: "Waiting for entry signal" },
  { id: 5, name: "Wheel", status: "active", pnl: +180.00, agents: 1, risk: "Low" },
  { id: 6, name: "Dividends", status: "paused", pnl: 0, agents: 0, risk: "Very Low", idleReason: "Ex-div dates 3 weeks out" },
  { id: 7, name: "KINDRIP", status: "active", pnl: +92.00, agents: 1, risk: "Low" },
];

const statusColor: Record<string, string> = {
  active: "var(--emerald)",
  idle: "var(--muted-foreground)",
  paused: "var(--amber)",
};


export function OverviewView() {
  const totalPnl = layers.reduce((s, l) => s + l.pnl, 0);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-8">
      <div>
        <h1 style={{ fontFamily: "var(--font-serif)", color: "var(--foreground)" }}>Overview</h1>
        <p className="text-[13px] mt-1" style={{ color: "var(--muted-foreground)" }}>
          At-a-glance health across all seven wealth layers
        </p>
      </div>

      {/* Hero */}
      <WovenBasketHero />

      {/* KPIs */}
      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiTile index={0} label="Portfolio Value" value="$142,380" sub="All layers combined" pill="Live" pillColor="var(--emerald)" />
        <KpiTile index={1} label="Week P&L" value="+$3,227" delta="2.3%" deltaDir="up" sub="Mon–Thu this week" />
        <KpiTile index={2} label="Total Open Risk" value="$8,420" sub="5.9% of portfolio deployed" />
        <KpiTile index={3} label="Layers Active" value="5 / 7" sub="Dividends paused, Weekly idle" />
      </section>

      {/* Week chart + layer health */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="md:col-span-2 rounded-xl border border-border obsidian-panel p-4" style={{ background: "var(--card)" }}>
          <div className="mb-4">
            <h3 className="text-[13px]" style={{ fontWeight: 500 }}>Week P&L</h3>
            <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>Daily net gain/loss this week</p>
          </div>
          <MiniAreaChart data={weekPnl} color="var(--treasure)" height={140} formatValue={(v) => `${v >= 0 ? "+" : ""}$${Math.abs(v)}`} />
        </div>

        <div className="rounded-xl border border-border obsidian-panel p-4" style={{ background: "var(--card)" }}>
          <h3 className="text-[13px] mb-1" style={{ fontWeight: 500 }}>Today's P&L</h3>
          <p className="text-[11px] mb-3" style={{ color: "var(--muted-foreground)" }}>Breakdown by layer</p>
          <div className="space-y-2">
            {layers.filter(l => l.pnl !== 0).map(l => (
              <div key={l.id} className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span
                    className="w-4 h-4 rounded text-[10px] flex items-center justify-center shrink-0"
                    style={{ background: "var(--muted)", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}
                  >
                    {l.id}
                  </span>
                  <span className="text-[12px]" style={{ color: "var(--foreground)" }}>{l.name}</span>
                </div>
                <span className="text-[12px]" style={{ fontFamily: "var(--font-mono)", color: l.pnl >= 0 ? "var(--emerald)" : "var(--rose)", fontWeight: 500 }}>
                  {l.pnl >= 0 ? "+" : ""}${l.pnl.toFixed(2)}
                </span>
              </div>
            ))}
            <div className="pt-2 mt-2 border-t border-border flex items-center justify-between">
              <span className="text-[12px]" style={{ color: "var(--muted-foreground)", fontWeight: 500 }}>Total</span>
              <span className="text-[13px]" style={{ fontFamily: "var(--font-mono)", color: "var(--emerald)", fontWeight: 500 }}>
                +${totalPnl.toFixed(2)}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* Layer cards */}
      <section>
        <h2 className="text-[13px] mb-3 uppercase tracking-wider" style={{ color: "var(--treasure)", letterSpacing: "0.1em", fontWeight: 600 }}>
          Wealth Layers
        </h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {layers.map((layer, i) => (
            <motion.div
              key={layer.id}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, delay: 0.1 + i * 0.07, ease: [0.22, 1, 0.36, 1] }}
              whileHover={{ y: -2, transition: { duration: 0.18 } }}
              className="rounded-xl border border-border obsidian-panel p-4 flex flex-col gap-2.5"
              style={{ background: "var(--card)" }}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className="w-5 h-5 rounded flex items-center justify-center text-[11px]"
                    style={{ background: "var(--muted)", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", fontWeight: 500 }}
                  >
                    {layer.id}
                  </span>
                  <span className="text-[13px]" style={{ fontWeight: 500 }}>{layer.name}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-1.5 h-1.5 rounded-full" style={{ background: statusColor[layer.status] }} />
                  <span className="text-[11px]" style={{ color: statusColor[layer.status], textTransform: "capitalize" }}>
                    {layer.status}
                  </span>
                </div>
              </div>

              {layer.pnl !== 0 ? (
                <div>
                  <div className="text-[18px]" style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: layer.pnl >= 0 ? "var(--emerald)" : "var(--rose)" }}>
                    {layer.pnl >= 0 ? "+" : ""}${layer.pnl.toFixed(2)}
                  </div>
                  <div className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>today's P&L</div>
                </div>
              ) : (
                <div>
                  <div className="text-[13px]" style={{ color: "var(--muted-foreground)", fontStyle: "italic" }}>No position today</div>
                  {layer.idleReason && (
                    <div className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>{layer.idleReason}</div>
                  )}
                </div>
              )}

              <div className="flex items-center justify-between">
                <span className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>Risk: {layer.risk}</span>
                <span className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{layer.agents} agent{layer.agents !== 1 ? "s" : ""}</span>
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      <div className="h-4" />
    </div>
  );
}
