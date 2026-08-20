import { useState } from "react";
import { motion } from "motion/react";
import { Shield, Lock } from "lucide-react";
import { PageHeader } from "./PageHeader";

type Filter = {
  id: string;
  label: string;
  desc: string;
  defaultOn?: boolean;
};

const filters: Filter[] = [
  { id: "weapons", label: "Weapons & defense", desc: "Lockheed, Raytheon, Northrop, small-arms manufacturers", defaultOn: true },
  { id: "tobacco", label: "Tobacco & nicotine", desc: "Altria, Philip Morris, vapor manufacturers", defaultOn: true },
  { id: "fossil", label: "Fossil fuel majors", desc: "Integrated oil & gas, coal extraction", defaultOn: true },
  { id: "gambling", label: "Gambling & casinos", desc: "Casinos, sportsbooks, gaming operators" },
  { id: "adult", label: "Adult entertainment", desc: "Adult media and related industries" },
  { id: "predatory", label: "Predatory lending", desc: "Payday lenders, subprime aggregators" },
  { id: "private-prison", label: "Private prisons", desc: "For-profit detention and corrections" },
  { id: "fast-fashion", label: "Fast fashion sweatshop chains", desc: "Suppliers flagged by ILO or human-rights watchdogs" },
];

const alwaysOn = [
  { id: "rights", label: "Human rights violations", desc: "Companies sanctioned for forced or child labor" },
  { id: "ofac", label: "OFAC sanctions list", desc: "Entities prohibited by US Treasury" },
  { id: "fraud", label: "Active fraud / SEC enforcement", desc: "Companies under active enforcement action" },
];

export function EthicalFiltersView() {
  const [enabled, setEnabled] = useState<Record<string, boolean>>(
    Object.fromEntries(filters.map((f) => [f.id, !!f.defaultOn]))
  );

  const toggle = (id: string) => setEnabled((cur) => ({ ...cur, [id]: !cur[id] }));
  const blockedCount = Object.values(enabled).filter(Boolean).length;

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
      <PageHeader
        eyebrow="Settings — Ethical Filters"
        title="What Trezo refuses to invest in"
        subtitle="A treasure built on the backs of others isn't a treasure. Toggle the categories Trezo will block when adding tickers."
      />

      {/* Summary card */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="rounded-xl border border-border obsidian-panel p-4 flex items-center gap-4"
        style={{ background: "var(--card)" }}
      >
        <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: "rgba(196,150,74,0.12)", color: "var(--treasure)" }}>
          <Shield size={18} />
        </div>
        <div className="flex-1">
          <div className="text-[13px]" style={{ fontWeight: 500 }}>
            Blocking <span style={{ color: "var(--treasure)", fontFamily: "var(--font-mono)" }}>{blockedCount}</span> categories
          </div>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
            Tickers in these categories won't pass the add-to-watchlist filter or be entered by any agent.
          </p>
        </div>
      </motion.div>

      {/* User-controlled toggles */}
      <section>
        <h2 className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
          Your filters
        </h2>
        <div className="rounded-xl border border-border obsidian-panel divide-y divide-border overflow-hidden" style={{ background: "var(--card)" }}>
          {filters.map((f, i) => (
            <motion.div
              key={f.id}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.04 }}
              className="flex items-center gap-4 px-5 py-3.5"
            >
              <div className="flex-1">
                <div className="text-[13px]" style={{ fontWeight: 500, color: "var(--foreground)" }}>{f.label}</div>
                <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>{f.desc}</p>
              </div>
              <Toggle on={!!enabled[f.id]} onClick={() => toggle(f.id)} />
            </motion.div>
          ))}
        </div>
      </section>

      {/* Always-on defaults */}
      <section>
        <h2 className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
          Always on
        </h2>
        <p className="text-[12px] mb-3" style={{ color: "var(--muted-foreground)" }}>
          These default screens can't be turned off. Trezo refuses to invest in any of these, no matter what.
        </p>
        <div className="rounded-xl border border-border obsidian-panel divide-y divide-border overflow-hidden" style={{ background: "var(--card)" }}>
          {alwaysOn.map((f) => (
            <div key={f.id} className="flex items-center gap-4 px-5 py-3.5">
              <Lock size={13} style={{ color: "var(--treasure)", flexShrink: 0 }} />
              <div className="flex-1">
                <div className="text-[13px]" style={{ fontWeight: 500, color: "var(--foreground)" }}>{f.label}</div>
                <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>{f.desc}</p>
              </div>
              <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: "rgba(196,150,74,0.12)", color: "var(--treasure)", fontFamily: "var(--font-mono)" }}>
                LOCKED
              </span>
            </div>
          ))}
        </div>
      </section>

      <div className="h-4" />
    </div>
  );
}

function Toggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="relative w-10 h-6 rounded-full transition-colors shrink-0"
      style={{ background: on ? "var(--treasure)" : "var(--muted)" }}
      aria-pressed={on}
    >
      <motion.span
        className="absolute top-0.5 w-5 h-5 rounded-full shadow-md"
        style={{ background: "var(--background)" }}
        animate={{ x: on ? 18 : 2 }}
        transition={{ type: "spring", stiffness: 500, damping: 30 }}
      />
    </button>
  );
}
