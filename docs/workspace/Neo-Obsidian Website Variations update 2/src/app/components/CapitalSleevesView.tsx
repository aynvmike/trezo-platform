import { motion } from "motion/react";
import { Zap, Clock, Anchor } from "lucide-react";
import { PageHeader } from "./PageHeader";

type Sleeve = {
  id: string;
  name: string;
  icon: React.ReactNode;
  accent: string;
  horizon: string;
  budget: number;
  used: number;
  profitRule: string;
  holdRule: string;
  layers: { id: number; name: string }[];
  velocity: string;
};

const sleeves: Sleeve[] = [
  {
    id: "active",
    name: "Active",
    icon: <Zap size={16} />,
    accent: "var(--emerald)",
    horizon: "Intraday → next-day",
    budget: 2000,
    used: 1340,
    profitRule: "Fast bite ~30% of position, 5-day max hold",
    holdRule: "Closed by EOD unless trend confirms hold",
    velocity: "Fast — recycles 3–5× per week",
    layers: [
      { id: 1, name: "Crypto" },
      { id: 2, name: "Stock" },
      { id: 4, name: "Stock Weekly" },
    ],
  },
  {
    id: "quick-options",
    name: "Quick Options",
    icon: <Clock size={16} />,
    accent: "var(--amber)",
    horizon: "2 – 3 day",
    budget: 1000,
    used: 480,
    profitRule: "Take profit at +30% and recycle",
    holdRule: "4-day max hold, hard stop at -50%",
    velocity: "Medium — recycles 2× per week",
    layers: [
      { id: 3, name: "Options" },
    ],
  },
  {
    id: "holding",
    name: "Holding",
    icon: <Anchor size={16} />,
    accent: "var(--sky)",
    horizon: "Days → indefinite",
    budget: 2000,
    used: 1820,
    profitRule: "Held by design — premium / dividend / accumulation",
    holdRule: "Rebalanced monthly, no time exit",
    velocity: "Slow — anchors the basket",
    layers: [
      { id: 5, name: "Wheel" },
      { id: 6, name: "Dividends" },
      { id: 7, name: "KINDRIP" },
    ],
  },
];

export function CapitalSleevesView() {
  const totalBudget = sleeves.reduce((s, x) => s + x.budget, 0);
  const totalUsed = sleeves.reduce((s, x) => s + x.used, 0);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-7">
      <PageHeader
        eyebrow="Plan & Research"
        title="Capital Sleeves"
        subtitle="How capital is split by trade horizon, and how much of each sleeve is working right now."
        explainer="Sleeves bound execution by time-horizon: fast-recycling capital takes a bigger per-trade bite than locked capital. The bot can't borrow across sleeves — each one is governed independently."
      />

      {/* Summary strip */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="rounded-xl border border-border obsidian-panel px-5 py-4 flex flex-wrap items-center gap-6"
        style={{ background: "var(--card)" }}
      >
        {[
          { label: "Risk Profile", value: "Moderate" },
          { label: "Account Equity", value: "$5,000", mono: true },
          { label: "Capacity", value: "Up to 12 positions" },
          { label: "Total Deployed", value: `$${totalUsed.toLocaleString()} / $${totalBudget.toLocaleString()}`, mono: true },
        ].map((item) => (
          <div key={item.label} className="flex flex-col">
            <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              {item.label}
            </span>
            <span
              className="text-[14px] mt-0.5"
              style={{
                fontFamily: item.mono ? "var(--font-mono)" : "var(--font-sans)",
                fontWeight: 500,
                color: "var(--foreground)",
              }}
            >
              {item.value}
            </span>
          </div>
        ))}
        <div className="ml-auto text-[11px] px-3 py-1.5 rounded-full" style={{ background: "rgba(196,150,74,0.1)", color: "var(--treasure)", fontFamily: "var(--font-mono)" }}>
          Plan: Active $2k · Options $1k · Holding $2k
        </div>
      </motion.div>

      {/* Three sleeve cards */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {sleeves.map((s, i) => {
          const usedPct = (s.used / s.budget) * 100;
          const free = s.budget - s.used;

          return (
            <motion.div
              key={s.id}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: i * 0.1, ease: [0.22, 1, 0.36, 1] }}
              whileHover={{ y: -3 }}
              className="relative rounded-xl border border-border obsidian-panel overflow-hidden p-5 flex flex-col gap-5"
              style={{ background: "var(--card)" }}
            >
              {/* Accent glow */}
              <motion.div
                className="absolute rounded-full pointer-events-none"
                style={{
                  width: 200, height: 200,
                  right: "-60px", top: "-60px",
                  background: `radial-gradient(circle, ${s.accent} 0%, transparent 65%)`,
                  opacity: 0.12, filter: "blur(30px)",
                }}
                animate={{ scale: [1, 1.2, 1] }}
                transition={{ duration: 5 + i, repeat: Infinity, ease: "easeInOut" }}
              />

              {/* Header */}
              <div className="relative flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center"
                    style={{ background: `${s.accent}1f`, color: s.accent }}
                  >
                    {s.icon}
                  </div>
                  <div>
                    <h3 className="text-[15px]" style={{ fontWeight: 500, fontFamily: "var(--font-serif)" }}>
                      {s.name}
                    </h3>
                    <div className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{s.horizon}</div>
                  </div>
                </div>
                <span
                  className="text-[10px] px-2 py-0.5 rounded-full"
                  style={{ background: `${s.accent}1f`, color: s.accent, fontFamily: "var(--font-mono)" }}
                >
                  {usedPct.toFixed(0)}%
                </span>
              </div>

              {/* Budget bar — the hero */}
              <div className="relative">
                <div className="flex items-end justify-between mb-2">
                  <div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "22px", fontWeight: 500, color: "var(--foreground)" }}>
                      ${s.used.toLocaleString()}
                    </div>
                    <div className="text-[10px] uppercase tracking-wider mt-0.5" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
                      Used
                    </div>
                  </div>
                  <div className="text-right">
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "14px", color: "var(--muted-foreground)" }}>
                      ${free.toLocaleString()} free
                    </div>
                    <div className="text-[10px] uppercase tracking-wider mt-0.5" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
                      of ${s.budget.toLocaleString()}
                    </div>
                  </div>
                </div>
                <div className="relative h-2.5 rounded-full overflow-hidden" style={{ background: "var(--muted)" }}>
                  <motion.div
                    className="absolute top-0 left-0 h-full rounded-full"
                    style={{ background: s.accent, boxShadow: `0 0 12px ${s.accent}80` }}
                    initial={{ width: 0 }}
                    animate={{ width: `${usedPct}%` }}
                    transition={{ duration: 1, delay: 0.3 + i * 0.1, ease: [0.22, 1, 0.36, 1] }}
                  />
                </div>
              </div>

              {/* Rules */}
              <div className="space-y-2.5">
                <div>
                  <div className="text-[10px] uppercase tracking-wider mb-0.5" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
                    Profit Rule
                  </div>
                  <div className="text-[12px]" style={{ color: "var(--foreground)" }}>{s.profitRule}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider mb-0.5" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
                    Hold Rule
                  </div>
                  <div className="text-[12px]" style={{ color: "var(--foreground)" }}>{s.holdRule}</div>
                </div>
              </div>

              {/* Velocity callout */}
              <div className="px-3 py-2 rounded-lg border border-dashed border-border flex items-start gap-2" style={{ background: "var(--muted)" }}>
                <Zap size={11} style={{ color: s.accent, marginTop: "2px", flexShrink: 0 }} />
                <span className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>
                  <span style={{ color: "var(--foreground)", fontWeight: 500 }}>Velocity:</span> {s.velocity}
                </span>
              </div>

              {/* Layer chips */}
              <div className="pt-3 border-t border-border">
                <div className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
                  Layers feeding this sleeve
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {s.layers.map((l) => (
                    <div
                      key={l.id}
                      className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px]"
                      style={{ background: "var(--muted)" }}
                    >
                      <span
                        className="w-4 h-4 rounded flex items-center justify-center text-[9px]"
                        style={{ background: s.accent, color: "var(--background)", fontFamily: "var(--font-mono)", fontWeight: 500 }}
                      >
                        {l.id}
                      </span>
                      <span style={{ color: "var(--foreground)" }}>{l.name}</span>
                    </div>
                  ))}
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>

      <div className="h-4" />
    </div>
  );
}
