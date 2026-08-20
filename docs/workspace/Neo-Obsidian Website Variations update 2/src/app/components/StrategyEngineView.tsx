import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Brain, ChevronDown, ChevronUp, Check, X, TrendingUp, TrendingDown, Pause as PauseIcon, Newspaper, Activity } from "lucide-react";
import { PageHeader } from "./PageHeader";

type Proposal = {
  id: string;
  action: "favour" | "trim" | "pause";
  strategy: string;
  layer: string;
  layerId: number;
  reasoning: string;
  evidence: string[];
  createdAt: string;
};

const proposals: Proposal[] = [
  {
    id: "p1",
    action: "favour",
    strategy: "Momentum Breakout",
    layer: "Stock",
    layerId: 2,
    reasoning: "This strategy is outperforming its 30-day baseline by 18%. Win rate climbed from 62% to 73% over the last two weeks. The bot wants to scale its position sizing up by ~15% within Active sleeve limits.",
    evidence: [
      "30-day win rate: 73% (was 62%)",
      "Avg holding period: 1.8 days — within sleeve rules",
      "Last 12 trades: 9 winners, 3 losers",
    ],
    createdAt: "12 min ago",
  },
  {
    id: "p2",
    action: "trim",
    strategy: "RSI Reversal (Crypto)",
    layer: "Crypto",
    layerId: 1,
    reasoning: "Volatility regime shifted — RSI extremes are no longer mean-reverting as cleanly. The bot recommends lowering position size by 25% and raising the TCS threshold from 700 to 760 until the regime settles.",
    evidence: [
      "Realized win rate dropped from 71% to 54%",
      "Avg loss size increased 34% week-over-week",
      "BTC 30-day realized vol up to 58%",
    ],
    createdAt: "1 hr ago",
  },
  {
    id: "p3",
    action: "pause",
    strategy: "Weekly Patterns (Stock Weekly)",
    layer: "Stock Weekly",
    layerId: 4,
    reasoning: "No qualifying setups in 14 sessions. Market is range-bound on the weekly timeframe. Suggest pausing until a weekly close breaks the 20-week range high or low.",
    evidence: [
      "0 entries in last 14 weekly sessions",
      "Indexes within ±2% of 20W average",
      "Re-engage trigger: weekly close outside ±5%",
    ],
    createdAt: "3 hr ago",
  },
];

const actionMeta: Record<string, { color: string; icon: React.ReactNode; label: string; bg: string }> = {
  favour: { color: "var(--emerald)", icon: <TrendingUp size={13} />, label: "Favour", bg: "rgba(16,185,129,0.12)" },
  trim: { color: "var(--amber)", icon: <TrendingDown size={13} />, label: "Trim", bg: "rgba(245,158,11,0.12)" },
  pause: { color: "var(--rose)", icon: <PauseIcon size={13} />, label: "Pause", bg: "rgba(244,63,94,0.12)" },
};

const strategies = [
  { id: "momentum", name: "Momentum Breakout", layers: [1, 2], desc: "Catches strength continuation on hourly+ timeframes" },
  { id: "rsi-reversal", name: "RSI Reversal", layers: [1], desc: "Buys mean-reversion at extreme oversold readings" },
  { id: "weekly-patterns", name: "Weekly Patterns", layers: [4], desc: "Trades only on weekly closes — slow cadence" },
  { id: "debit-spreads", name: "Debit Spreads", layers: [3], desc: "Defined-risk directional options plays" },
  { id: "wheel-cycle", name: "Wheel Cycle", layers: [5], desc: "CSP → CC rotation on dividend equities" },
];

export function StrategyEngineView() {
  const [resolved, setResolved] = useState<Record<string, "approved" | "dismissed">>({});
  const [scopeOpen, setScopeOpen] = useState(false);
  const [expanded, setExpanded] = useState<string | null>("p1");

  const resolve = (id: string, action: "approved" | "dismissed") =>
    setResolved((cur) => ({ ...cur, [id]: action }));

  const open = proposals.filter((p) => !resolved[p.id]);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
      <PageHeader
        eyebrow="Settings — Strategy Engine"
        title="Strategy Engine & Adaptive Scope"
        subtitle="Where the bot tells you what it wants to favour, trim, or pause — and the engine that reads market regime + news to adapt on its own."
      />

      {/* The bot is thinking */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="flex items-center gap-3 px-4 py-3 rounded-xl border border-border obsidian-panel"
        style={{ background: "var(--card)" }}
      >
        <div className="relative w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: "rgba(196,150,74,0.12)", color: "var(--treasure)" }}>
          <Brain size={18} />
          <motion.span
            className="absolute inset-0 rounded-lg"
            style={{ border: "1px solid var(--treasure)" }}
            animate={{ opacity: [0.6, 0, 0.6], scale: [1, 1.25, 1] }}
            transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
          />
        </div>
        <div className="flex-1">
          <div className="text-[13px]" style={{ fontWeight: 500 }}>
            {open.length > 0
              ? <>The bot has <span style={{ color: "var(--treasure)", fontFamily: "var(--font-mono)" }}>{open.length}</span> proposal{open.length !== 1 ? "s" : ""} for you</>
              : "No open proposals — the bot is satisfied with current settings"
            }
          </div>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
            Approving applies the change on the next tick. Dismissing keeps things as they are.
          </p>
        </div>
      </motion.div>

      {/* Proposals feed */}
      <section>
        <h2 className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
          Strategy proposals
        </h2>
        <div className="space-y-3">
          <AnimatePresence>
            {proposals.map((p, i) => {
              const meta = actionMeta[p.action];
              const status = resolved[p.id];
              const isOpen = expanded === p.id;

              return (
                <motion.div
                  key={p.id}
                  layout
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: status ? 0.5 : 1, y: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ duration: 0.35, delay: i * 0.06 }}
                  className="rounded-xl border obsidian-panel overflow-hidden"
                  style={{
                    background: "var(--card)",
                    borderColor: status ? "var(--border)" : meta.color + "60",
                  }}
                >
                  {/* Top row */}
                  <div className="px-5 py-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <span
                          className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-md shrink-0"
                          style={{ background: meta.bg, color: meta.color, fontWeight: 600, letterSpacing: "0.05em" }}
                        >
                          {meta.icon} {meta.label.toUpperCase()}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[13px]" style={{ fontWeight: 500, color: "var(--foreground)" }}>{p.strategy}</span>
                            <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "var(--muted)", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                              Layer {p.layerId} · {p.layer}
                            </span>
                            <span className="text-[10px]" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>{p.createdAt}</span>
                          </div>
                          <p className="text-[12px] mt-1.5 leading-relaxed" style={{ color: "var(--muted-foreground)" }}>{p.reasoning}</p>
                        </div>
                      </div>

                      {status ? (
                        <span
                          className="text-[11px] px-2.5 py-1 rounded-md shrink-0"
                          style={{
                            background: status === "approved" ? "rgba(16,185,129,0.12)" : "var(--muted)",
                            color: status === "approved" ? "var(--emerald)" : "var(--muted-foreground)",
                            fontFamily: "var(--font-mono)",
                          }}
                        >
                          {status === "approved" ? "APPROVED" : "DISMISSED"}
                        </span>
                      ) : (
                        <div className="flex items-center gap-1.5 shrink-0">
                          <button
                            onClick={() => resolve(p.id, "dismissed")}
                            className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] border border-border transition-colors hover:bg-muted"
                            style={{ color: "var(--muted-foreground)" }}
                          >
                            <X size={11} /> Dismiss
                          </button>
                          <motion.button
                            onClick={() => resolve(p.id, "approved")}
                            whileHover={{ scale: 1.04 }}
                            whileTap={{ scale: 0.96 }}
                            className="flex items-center gap-1 px-3 py-1.5 rounded-md text-[11px]"
                            style={{ background: "var(--treasure)", color: "var(--background)", fontWeight: 500 }}
                          >
                            <Check size={11} /> Approve
                          </motion.button>
                        </div>
                      )}
                    </div>

                    {/* Evidence disclosure */}
                    <button
                      onClick={() => setExpanded(isOpen ? null : p.id)}
                      className="flex items-center gap-1 text-[11px] mt-3"
                      style={{ color: "var(--muted-foreground)" }}
                    >
                      {isOpen ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                      <span>{isOpen ? "Hide evidence" : "Show evidence"}</span>
                    </button>

                    <AnimatePresence initial={false}>
                      {isOpen && (
                        <motion.ul
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.22 }}
                          className="mt-2 pl-4 space-y-1 list-none overflow-hidden"
                        >
                          {p.evidence.map((e, ei) => (
                            <li key={ei} className="text-[11px] flex items-start gap-2" style={{ color: "var(--muted-foreground)" }}>
                              <span className="w-1 h-1 rounded-full mt-1.5 shrink-0" style={{ background: "var(--treasure)" }} />
                              <span style={{ fontFamily: "var(--font-mono)" }}>{e}</span>
                            </li>
                          ))}
                        </motion.ul>
                      )}
                    </AnimatePresence>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      </section>

      {/* Adaptive Scope explainer */}
      <section>
        <div className="rounded-xl border border-border obsidian-panel overflow-hidden" style={{ background: "var(--card)" }}>
          <button
            onClick={() => setScopeOpen((v) => !v)}
            className="w-full px-5 py-4 flex items-center justify-between text-left"
          >
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: "rgba(196,150,74,0.1)", color: "var(--treasure)" }}>
                <Activity size={15} />
              </div>
              <div>
                <div className="text-[13px]" style={{ fontWeight: 500 }}>Adaptive Scope · how it reasons</div>
                <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>Reads market regime + breaking news and adjusts the dials on its own</p>
              </div>
            </div>
            <motion.span animate={{ rotate: scopeOpen ? 180 : 0 }} transition={{ duration: 0.2 }} style={{ color: "var(--muted-foreground)" }}>
              <ChevronDown size={14} />
            </motion.span>
          </button>
          <AnimatePresence initial={false}>
            {scopeOpen && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.25 }}
                style={{ overflow: "hidden" }}
              >
                <div className="px-5 pb-5 border-t border-border space-y-4 pt-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {[
                      { icon: <Activity size={13} />, title: "Regime sense", body: "Volatility, trend strength, and breadth across the major indexes inform whether the bot tightens stops or widens them." },
                      { icon: <Newspaper size={13} />, title: "News scan", body: "Earnings, macro releases, and breaking-news streams. A surprise on a watchlist ticker can pause its strategy until conditions clear." },
                      { icon: <TrendingUp size={13} />, title: "Confidence shifts", body: "Live win rate per strategy drives the TCS threshold. Strategies on cold streaks need higher confidence to fire." },
                      { icon: <PauseIcon size={13} />, title: "Self-pause", body: "If a strategy drifts more than 3σ below its baseline, it pauses itself and surfaces here as a proposal." },
                    ].map((item) => (
                      <div key={item.title} className="px-3 py-3 rounded-md border border-border" style={{ background: "var(--muted)" }}>
                        <div className="flex items-center gap-2 mb-1" style={{ color: "var(--treasure)" }}>
                          {item.icon}
                          <span className="text-[12px]" style={{ color: "var(--foreground)", fontWeight: 500 }}>{item.title}</span>
                        </div>
                        <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{item.body}</p>
                      </div>
                    ))}
                  </div>

                  <div>
                    <div className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
                      Strategy library
                    </div>
                    <div className="divide-y divide-border rounded-md border border-border overflow-hidden" style={{ background: "var(--background)" }}>
                      {strategies.map((s) => (
                        <div key={s.id} className="flex items-center gap-3 px-3 py-2.5">
                          <div className="flex-1">
                            <div className="text-[12px]" style={{ fontWeight: 500 }}>{s.name}</div>
                            <p className="text-[10px]" style={{ color: "var(--muted-foreground)" }}>{s.desc}</p>
                          </div>
                          <div className="flex gap-1">
                            {s.layers.map((l) => (
                              <span key={l} className="w-4 h-4 rounded text-[9px] flex items-center justify-center" style={{ background: "var(--muted)", color: "var(--treasure)", fontFamily: "var(--font-mono)", fontWeight: 500 }}>
                                {l}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </section>

      <div className="h-4" />
    </div>
  );
}
