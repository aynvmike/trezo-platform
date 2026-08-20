import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { ShieldCheck, ChevronDown, Check, AlertCircle, RefreshCw } from "lucide-react";
import { PageHeader } from "./PageHeader";

type Broker = {
  id: string;
  name: string;
  desc: string;
  connected?: boolean;
  health?: "healthy" | "degraded" | "reconnect";
  lastRefresh?: string;
  expiry?: string;
};

type Category = {
  id: string;
  label: string;
  desc: string;
  brokers: Broker[];
};

const categories: Category[] = [
  {
    id: "stocks",
    label: "Stocks & ETFs",
    desc: "Equities, ETFs, and fractional shares",
    brokers: [
      { id: "alpaca", name: "Alpaca", desc: "Commission-free API broker · Paper + Live", connected: true, health: "healthy", lastRefresh: "2 min ago", expiry: "Oct 14, 2026" },
      { id: "ibkr", name: "Interactive Brokers", desc: "Global multi-asset · Pro tier", connected: false, health: "reconnect" },
      { id: "tradier", name: "Tradier", desc: "Options-friendly equity broker", connected: false },
      { id: "schwab", name: "Charles Schwab", desc: "Full-service brokerage", connected: false },
    ],
  },
  {
    id: "options",
    label: "Options",
    desc: "Listed equity and index options",
    brokers: [
      { id: "tastytrade", name: "tastytrade", desc: "Options-first platform · Levels 1–4", connected: true, health: "degraded", lastRefresh: "47 min ago", expiry: "Aug 02, 2026" },
      { id: "ibkr-opt", name: "Interactive Brokers (Options)", desc: "Same connection as stocks · separate approval" },
    ],
  },
  {
    id: "crypto",
    label: "Crypto",
    desc: "Spot crypto and perpetuals",
    brokers: [
      { id: "coinbase", name: "Coinbase", desc: "Spot trading · regulated US exchange", connected: false },
      { id: "kraken", name: "Kraken", desc: "Spot + futures · API key flow", connected: false },
      { id: "alpaca-crypto", name: "Alpaca Crypto", desc: "Bundled with the Alpaca equities connection" },
    ],
  },
];

const healthMeta: Record<string, { color: string; label: string }> = {
  healthy: { color: "var(--emerald)", label: "Healthy" },
  degraded: { color: "var(--amber)", label: "2 failures" },
  reconnect: { color: "var(--rose)", label: "Reconnect" },
};

const recentAttempts = [
  { time: "15:47", status: "ok", broker: "Alpaca", detail: "Token refresh succeeded" },
  { time: "15:00", status: "ok", broker: "Alpaca", detail: "Token refresh succeeded" },
  { time: "14:13", status: "warn", broker: "tastytrade", detail: "Slow response (3.2s) — retried" },
  { time: "13:47", status: "ok", broker: "tastytrade", detail: "Token refresh succeeded" },
  { time: "12:00", status: "fail", broker: "IBKR", detail: "Refresh token expired — requires manual reconnect" },
];

export function ConnectionsView() {
  const [logOpen, setLogOpen] = useState(false);
  const [statuses, setStatuses] = useState<Record<string, boolean>>(
    Object.fromEntries(
      categories.flatMap((c) => c.brokers.map((b) => [b.id, !!b.connected]))
    )
  );

  const toggleConnect = (id: string) => setStatuses((cur) => ({ ...cur, [id]: !cur[id] }));

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
      <PageHeader
        eyebrow="Settings — Connections"
        title="Connect a broker"
        subtitle="One-click sign-in across providers. You authenticate on the broker's own page — Trezo never sees a password or key."
      />

      {/* Security reassurance */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="flex items-start gap-3 px-4 py-3 rounded-xl border border-border obsidian-panel"
        style={{ background: "var(--card)" }}
      >
        <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ background: "rgba(16,185,129,0.12)", color: "var(--emerald)" }}>
          <ShieldCheck size={16} />
        </div>
        <div>
          <div className="text-[13px]" style={{ fontWeight: 500 }}>OAuth sign-in, encrypted at rest</div>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
            You sign in on the broker's page. They hand Trezo a refresh token that's encrypted with your account key — we can't trade outside the permissions you grant, and you can revoke any connection anytime.
          </p>
        </div>
      </motion.div>

      {/* Provider grid by category */}
      {categories.map((cat, ci) => (
        <section key={cat.id}>
          <div className="flex items-center gap-3 mb-3">
            <div className="w-0.5 h-5 rounded-full" style={{ background: "var(--treasure)" }} />
            <div>
              <h2 className="text-[14px]" style={{ fontWeight: 500, fontFamily: "var(--font-serif)" }}>{cat.label}</h2>
              <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{cat.desc}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {cat.brokers.map((b, bi) => {
              const connected = statuses[b.id];
              const health = b.health;
              return (
                <motion.div
                  key={b.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.35, delay: ci * 0.05 + bi * 0.04 }}
                  whileHover={{ y: -2 }}
                  className="rounded-xl border obsidian-panel p-4 flex items-start justify-between gap-3"
                  style={{
                    background: "var(--card)",
                    borderColor: connected ? "var(--treasure)" : "var(--border)",
                  }}
                >
                  <div className="flex items-start gap-3 flex-1 min-w-0">
                    <div
                      className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                      style={{
                        background: connected ? "rgba(196,150,74,0.15)" : "var(--muted)",
                        color: connected ? "var(--treasure)" : "var(--muted-foreground)",
                        fontFamily: "var(--font-serif)",
                        fontWeight: 500,
                      }}
                    >
                      {b.name[0]}
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-[13px]" style={{ fontWeight: 500, color: "var(--foreground)" }}>{b.name}</span>
                        {connected && health && healthMeta[health] && (
                          <span
                            className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full"
                            style={{ background: `${healthMeta[health].color}1f`, color: healthMeta[health].color }}
                          >
                            <span className="w-1 h-1 rounded-full" style={{ background: healthMeta[health].color }} />
                            {healthMeta[health].label}
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] mt-0.5 truncate" style={{ color: "var(--muted-foreground)" }}>{b.desc}</p>
                      {connected && b.lastRefresh && (
                        <div className="text-[10px] mt-1.5" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                          Refreshed {b.lastRefresh} · expires {b.expiry}
                        </div>
                      )}
                    </div>
                  </div>

                  <button
                    onClick={() => toggleConnect(b.id)}
                    className="text-[11px] px-3 py-1.5 rounded-md whitespace-nowrap shrink-0 transition-colors"
                    style={{
                      background: connected ? "var(--muted)" : "var(--treasure)",
                      color: connected ? "var(--muted-foreground)" : "var(--background)",
                      fontWeight: 500,
                    }}
                  >
                    {connected ? "Disconnect" : "Connect"}
                  </button>
                </motion.div>
              );
            })}
          </div>
        </section>
      ))}

      {/* Refresh log disclosure */}
      <div className="rounded-xl border border-border obsidian-panel overflow-hidden" style={{ background: "var(--card)" }}>
        <button onClick={() => setLogOpen((v) => !v)} className="w-full px-5 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <RefreshCw size={13} style={{ color: "var(--muted-foreground)" }} />
            <span className="text-[13px]" style={{ fontWeight: 500 }}>Recent token-refresh attempts</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded-full" style={{ background: "var(--muted)", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
              {recentAttempts.length}
            </span>
          </div>
          <motion.span animate={{ rotate: logOpen ? 180 : 0 }} transition={{ duration: 0.2 }} style={{ color: "var(--muted-foreground)" }}>
            <ChevronDown size={14} />
          </motion.span>
        </button>
        <AnimatePresence initial={false}>
          {logOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25 }}
              style={{ overflow: "hidden" }}
            >
              <div className="divide-y divide-border border-t border-border">
                {recentAttempts.map((a, i) => {
                  const color = a.status === "ok" ? "var(--emerald)" : a.status === "warn" ? "var(--amber)" : "var(--rose)";
                  const Icon = a.status === "ok" ? Check : AlertCircle;
                  return (
                    <div key={i} className="flex items-center gap-3 px-5 py-2.5">
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--muted-foreground)", minWidth: "40px" }}>{a.time}</span>
                      <Icon size={11} style={{ color, flexShrink: 0 }} />
                      <span className="text-[12px]" style={{ fontWeight: 500 }}>{a.broker}</span>
                      <span className="text-[11px] flex-1" style={{ color: "var(--muted-foreground)" }}>{a.detail}</span>
                    </div>
                  );
                })}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="h-4" />
    </div>
  );
}
