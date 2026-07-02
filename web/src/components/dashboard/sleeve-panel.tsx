import { Zap, Clock, Anchor, TrendingUp, Coins, type LucideIcon } from "lucide-react";
import { fetchSleeveSnapshot, type SleeveRow } from "@/lib/sleeve-snapshot";

/**
 * Allocation Pockets panel — the Neo-Obsidian "update 2" card design, wired
 * to the REAL /allocations/snapshot data: the per-market-type budgets the
 * Trade Execution gate enforces (Phase 8a.2). Server component (no
 * framer-motion); animation via CSS + the depth system.
 */

const META: Record<string, { name: string; horizon: string; accent: string; velocity: string; Icon: LucideIcon }> = {
  stocks: { name: "Stocks", horizon: "Day → swing", accent: "16 185 129", velocity: "Fast — day-to-swing plays recycle capital weekly", Icon: TrendingUp },
  crypto: { name: "Crypto", horizon: "Swing → HODL", accent: "245 158 11", velocity: "Mixed — swing trades recycle; HODL accumulates slowly", Icon: Coins },
  options: { name: "Options", horizon: "2–3 day", accent: "168 85 247", velocity: "Fast — short plays, +30% take-profit recycle", Icon: Clock },
  income: { name: "Income", horizon: "Weeks → indefinite", accent: "56 189 248", velocity: "Slow — wheel cycles + dividends anchor the basket", Icon: Anchor },
};

function money(n: number): string {
  return "$" + Math.round(n || 0).toLocaleString();
}
function compact(n: number): string {
  return n >= 1000 ? "$" + (n / 1000).toFixed(n % 1000 === 0 ? 0 : 1) + "k" : "$" + Math.round(n || 0);
}
function cap(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

export default async function SleevePanel({ userId }: { userId: string }) {
  const snap = await fetchSleeveSnapshot(userId);
  if (!snap || !snap.configured) {
    return (
      <section className="depth-card p-5 text-sm text-[rgb(var(--muted-foreground))]">
        Capital sleeve data isn&apos;t available right now — start the agents service and reload.
      </section>
    );
  }
  const totalBudget = snap.sleeves.reduce((s, x) => s + x.budget_usd, 0);
  const totalUsed = snap.sleeves.reduce((s, x) => s + x.deployed_usd, 0);
  const planPill = "Plan: " + snap.sleeves.map((s) => `${(META[s.id]?.name ?? s.id)} ${compact(s.budget_usd)}`).join(" · ");

  const facts = [
    { label: "Risk Profile", value: cap(snap.profile), mono: false },
    { label: "Account Equity", value: money(snap.equity_usd), mono: true },
    { label: "Capacity", value: `Up to ${snap.scaled_max_open} positions`, mono: false },
    { label: "Total Deployed", value: `${money(totalUsed)} / ${money(totalBudget)}`, mono: true },
  ];

  return (
    <div className="space-y-5">
      {/* Summary strip */}
      <section className="depth-card flex flex-wrap items-center gap-6 px-5 py-4">
        {facts.map((it) => (
          <div key={it.label} className="flex flex-col">
            <span className="text-[10px] uppercase tracking-wider text-[rgb(var(--muted-foreground))]">{it.label}</span>
            <span className={"mt-0.5 text-[14px] font-medium text-[rgb(var(--foreground))] " + (it.mono ? "font-mono" : "")}>{it.value}</span>
          </div>
        ))}
        <span className="ml-auto rounded-full px-3 py-1.5 font-mono text-[11px]" style={{ background: "rgb(var(--accent) / 0.1)", color: "rgb(var(--accent))" }}>
          {planPill}
        </span>
      </section>

      {/* One card per pocket */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-4">
        {snap.sleeves.map((s) => (
          <SleeveCard key={s.id} s={s} />
        ))}
      </div>
    </div>
  );
}

function SleeveCard({ s }: { s: SleeveRow }) {
  const m = META[s.id] ?? META.stocks;
  const accent = `rgb(${m.accent})`;
  const Icon = m.Icon;
  const usedPct = Math.min(100, Math.max(0, s.used_pct));

  return (
    <div className="depth-card relative flex flex-col gap-5 overflow-hidden p-5">
      {/* Accent glow */}
      <div
        className="pointer-events-none absolute animate-pulse rounded-full"
        style={{ width: 200, height: 200, right: -60, top: -60, background: `radial-gradient(circle, ${accent} 0%, transparent 65%)`, opacity: 0.12, filter: "blur(30px)" }}
      />

      {/* Header */}
      <div className="relative flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg" style={{ background: `rgb(${m.accent} / 0.12)`, color: accent }}>
            <Icon size={16} />
          </div>
          <div>
            <h3 className="font-serif text-[15px] font-medium text-[rgb(var(--foreground))]">{m.name}</h3>
            <div className="text-[11px] text-[rgb(var(--muted-foreground))]">{m.horizon}</div>
          </div>
        </div>
        <span className="rounded-full px-2 py-0.5 font-mono text-[10px]" style={{ background: `rgb(${m.accent} / 0.12)`, color: accent }}>
          {Math.round(usedPct)}%
        </span>
      </div>

      {/* Budget bar — the hero */}
      <div className="relative">
        <div className="mb-2 flex items-end justify-between">
          <div>
            <div className="font-mono text-[22px] font-medium text-[rgb(var(--foreground))]">{money(s.deployed_usd)}</div>
            <div className="mt-0.5 text-[10px] uppercase tracking-wider text-[rgb(var(--muted-foreground))]">Used</div>
          </div>
          <div className="text-right">
            <div className="font-mono text-[14px] text-[rgb(var(--muted-foreground))]">{money(s.free_usd)} free</div>
            <div className="mt-0.5 text-[10px] uppercase tracking-wider text-[rgb(var(--muted-foreground))]">of {money(s.budget_usd)}</div>
          </div>
        </div>
        <div className="relative h-2.5 overflow-hidden rounded-full" style={{ background: "rgb(var(--muted))" }}>
          <div className="absolute left-0 top-0 h-full rounded-full" style={{ width: `${usedPct}%`, background: accent, boxShadow: `0 0 12px ${accent}` }} />
        </div>
      </div>

      {/* Rules */}
      <div className="space-y-2.5">
        <div>
          <div className="mb-0.5 text-[10px] uppercase tracking-wider text-[rgb(var(--muted-foreground))]">Profit Rule</div>
          <div className="text-[12px] text-[rgb(var(--foreground))]">{s.profit}</div>
        </div>
        <div>
          <div className="mb-0.5 text-[10px] uppercase tracking-wider text-[rgb(var(--muted-foreground))]">Hold Rule</div>
          <div className="text-[12px] text-[rgb(var(--foreground))]">{s.hold}</div>
        </div>
      </div>

      {/* Velocity callout */}
      <div className="flex items-start gap-2 rounded-lg border border-dashed border-[rgb(var(--border))] px-3 py-2" style={{ background: "rgb(var(--muted))" }}>
        <Zap size={11} style={{ color: accent, marginTop: 2, flexShrink: 0 }} />
        <span className="text-[11px] text-[rgb(var(--muted-foreground))]">
          <span className="font-medium text-[rgb(var(--foreground))]">Velocity:</span> {m.velocity}
        </span>
      </div>

      {/* Layer chips */}
      {s.layers && s.layers.length ? (
        <div className="border-t border-[rgb(var(--border))] pt-3">
          <div className="mb-2 text-[10px] uppercase tracking-wider text-[rgb(var(--muted-foreground))]">Layers feeding this pocket</div>
          <div className="flex flex-wrap gap-1.5">
            {s.layers.map((l, i) => {
              const mm = l.match(/^(\d+)\s+(.*)$/);
              const id = mm ? mm[1] : "•";
              const name = mm ? mm[2] : l;
              return (
                <div key={i} className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px]" style={{ background: "rgb(var(--muted))" }}>
                  <span className="flex h-4 w-4 items-center justify-center rounded font-mono text-[9px] font-medium" style={{ background: accent, color: "rgb(var(--background))" }}>{id}</span>
                  <span className="text-[rgb(var(--foreground))]">{name}</span>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
