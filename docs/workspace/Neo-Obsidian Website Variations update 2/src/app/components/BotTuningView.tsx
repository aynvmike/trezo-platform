import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  ShieldCheck, Check, X, ChevronDown, Upload, FileText, AlertTriangle,
  Info, Lightbulb,
} from "lucide-react";
import { PageHeader } from "./PageHeader";

const strategies = [
  { id: "momentum", label: "Momentum Breakout" },
  { id: "rsi", label: "RSI Reversal" },
  { id: "weekly", label: "Weekly Patterns" },
  { id: "debit", label: "Debit Spreads" },
  { id: "wheel", label: "Wheel Cycle" },
  { id: "dividend", label: "Dividend Capture" },
];

const auditRows = [
  { key: "risk_profile", saved: "Balanced", live: "Balanced" },
  { key: "tcs_threshold", saved: "720", live: "720" },
  { key: "max_open_positions", saved: "8", live: "8" },
  { key: "daily_profit_target", saved: "$150", live: "$150" },
  { key: "daily_loss_limit", saved: "$500", live: "$500" },
  { key: "auto_trade", saved: "OFF", live: "OFF" },
  { key: "switching_mode", saved: "adaptive", live: "adaptive" },
];

const learningRows = [
  { strategy: "Momentum Breakout", winRate: "73%", avgWin: "+$84", avgLoss: "-$42", medTcs: 772 },
  { strategy: "RSI Reversal", winRate: "54%", avgWin: "+$62", avgLoss: "-$58", medTcs: 708 },
  { strategy: "Weekly Patterns", winRate: "72%", avgWin: "+$210", avgLoss: "-$110", medTcs: 748 },
  { strategy: "Debit Spreads", winRate: "61%", avgWin: "+$130", avgLoss: "-$80", medTcs: 731 },
  { strategy: "Wheel Cycle", winRate: "89%", avgWin: "+$48", avgLoss: "-$140", medTcs: 692 },
];

const tradePatterns = [
  { label: "Held too long", count: 14, color: "var(--rose)" },
  { label: "Exited too early", count: 22, color: "var(--amber)" },
  { label: "Optimal exit", count: 61, color: "var(--emerald)" },
  { label: "Missed entry", count: 9, color: "var(--sky)" },
];

const suggestions = [
  { tone: "good", text: "Momentum Breakout is your strongest strategy — consider raising its sleeve allocation by 10%." },
  { tone: "warn", text: "RSI Reversal win rate dropped 17 pts in 2 weeks. Try raising its TCS floor from 700 to 760." },
  { tone: "info", text: "You're exiting Wheel positions too early on average. Trust the cycle — let the CSPs expire when possible." },
];

const toneStyles: Record<string, { color: string; icon: React.ReactNode }> = {
  good: { color: "var(--emerald)", icon: <Check size={11} /> },
  warn: { color: "var(--amber)", icon: <AlertTriangle size={11} /> },
  info: { color: "var(--sky)", icon: <Info size={11} /> },
};

export function BotTuningView() {
  const [riskProfile, setRiskProfile] = useState("Balanced");
  const [tcs, setTcs] = useState(720);
  const [maxPos, setMaxPos] = useState(8);
  const [profitTarget, setProfitTarget] = useState(150);
  const [lossLimit, setLossLimit] = useState(500);
  const [autoTrade, setAutoTrade] = useState(false);
  const [switching, setSwitching] = useState<"off" | "fixed" | "adaptive" | "tiered">("adaptive");
  const [expertOpen, setExpertOpen] = useState(false);
  const [strategyOn, setStrategyOn] = useState<Record<string, boolean>>(
    Object.fromEntries(strategies.map((s) => [s.id, true]))
  );
  const [equity] = useState(5000);
  const [importStep, setImportStep] = useState<"idle" | "review" | "done">("idle");

  // Sizing preview: position size = equity * (risk multiplier) / max positions
  const riskMult = riskProfile === "Conservative" ? 0.5 : riskProfile === "Balanced" ? 1 : riskProfile === "Aggressive" ? 1.5 : 2;
  const positionSize = Math.round((equity * 0.1 * riskMult) / 2);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
      <PageHeader
        eyebrow="Settings — Bot Tuning"
        title="How the bot behaves"
        subtitle="The dials that drive every agent. Changes apply on the next tick — no restart needed."
      />

      {/* Auto-trade banner — front and center */}
      <motion.div
        layout
        className="relative rounded-xl border-2 overflow-hidden p-4 flex items-center justify-between gap-4"
        style={{
          background: autoTrade
            ? "linear-gradient(135deg, rgba(16,185,129,0.10) 0%, var(--card) 60%)"
            : "linear-gradient(135deg, rgba(108,108,108,0.06) 0%, var(--card) 60%)",
          borderColor: autoTrade ? "var(--emerald)" : "var(--border)",
        }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center"
            style={{
              background: autoTrade ? "var(--emerald)" : "var(--muted)",
              color: autoTrade ? "var(--background)" : "var(--muted-foreground)",
            }}
          >
            {autoTrade ? <Check size={18} /> : <X size={18} />}
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-widest" style={{ color: autoTrade ? "var(--emerald)" : "var(--muted-foreground)", letterSpacing: "0.12em", fontWeight: 600 }}>
              Auto-trade
            </div>
            <div style={{ fontFamily: "var(--font-serif)", fontSize: "20px", fontWeight: 500, color: "var(--foreground)" }}>
              {autoTrade ? "ON · bots will execute" : "OFF · signals only, no orders"}
            </div>
          </div>
        </div>
        <Toggle on={autoTrade} onClick={() => setAutoTrade((v) => !v)} large />
      </motion.div>

      {/* BLOCK 1 — DIALS */}
      <Block title="Dials" desc="The settings every agent reads on its next tick">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-5">
          {/* Risk profile */}
          <div>
            <Label text="Risk profile" hint="Sets default sizing, stop tightness, and TCS floors" />
            <div className="flex flex-wrap gap-1.5">
              {["Conservative", "Balanced", "Aggressive", "Expert"].map((r) => (
                <button
                  key={r}
                  onClick={() => setRiskProfile(r)}
                  className="px-2.5 py-1.5 rounded-md text-[11px] border transition-colors"
                  style={{
                    background: riskProfile === r ? "var(--accent)" : "var(--background)",
                    borderColor: riskProfile === r ? "var(--treasure)" : "var(--border)",
                    color: riskProfile === r ? "var(--treasure)" : "var(--foreground)",
                  }}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>

          {/* TCS threshold */}
          <SliderRow label="Confidence (TCS) threshold" hint="Signals below this won't fire" value={tcs} setValue={setTcs} min={400} max={950} step={10} suffix="" />

          {/* Max positions */}
          <SliderRow label="Max open positions" hint="Across all sleeves combined" value={maxPos} setValue={setMaxPos} min={1} max={20} step={1} suffix="" />

          {/* Daily profit target */}
          <SliderRow label="Daily profit target" hint="Bots ease off after hitting this" value={profitTarget} setValue={setProfitTarget} min={50} max={2000} step={25} prefix="$" />

          {/* Daily loss limit */}
          <SliderRow label="Daily loss limit" hint="Everything pauses if breached" value={lossLimit} setValue={setLossLimit} min={100} max={5000} step={50} prefix="$" tone="rose" />

          {/* Switching mode */}
          <div>
            <Label text="Strategy switching" hint="How aggressively the bot rotates strategies" />
            <div className="flex flex-wrap gap-1.5">
              {([
                { id: "off", label: "Off" },
                { id: "fixed", label: "Fixed" },
                { id: "adaptive", label: "Adaptive" },
                { id: "tiered", label: "Tiered" },
              ] as const).map((m) => (
                <button
                  key={m.id}
                  onClick={() => setSwitching(m.id)}
                  className="px-2.5 py-1.5 rounded-md text-[11px] border transition-colors"
                  style={{
                    background: switching === m.id ? "var(--accent)" : "var(--background)",
                    borderColor: switching === m.id ? "var(--treasure)" : "var(--border)",
                    color: switching === m.id ? "var(--treasure)" : "var(--foreground)",
                  }}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Per-strategy toggles */}
        <div className="mt-5 pt-5 border-t border-border">
          <div className="text-[10px] uppercase tracking-wider mb-3" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
            Per-strategy on/off
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {strategies.map((s) => (
              <div key={s.id} className="flex items-center justify-between px-3 py-2 rounded-md border border-border" style={{ background: "var(--background)" }}>
                <span className="text-[12px]" style={{ color: "var(--foreground)" }}>{s.label}</span>
                <Toggle on={strategyOn[s.id]} onClick={() => setStrategyOn((cur) => ({ ...cur, [s.id]: !cur[s.id] }))} />
              </div>
            ))}
          </div>
        </div>

        {/* Live sizing preview */}
        <div className="mt-5 pt-5 border-t border-border flex items-center justify-between flex-wrap gap-3">
          <div>
            <div className="text-[10px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              Live sizing preview
            </div>
            <div className="text-[11px] mt-1" style={{ color: "var(--muted-foreground)" }}>
              At ${equity.toLocaleString()} equity · {riskProfile} risk
            </div>
          </div>
          <div className="text-right">
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "22px", fontWeight: 500, color: "var(--treasure)" }}>
              ~${positionSize}
            </div>
            <div className="text-[10px]" style={{ color: "var(--muted-foreground)" }}>Per new position</div>
          </div>
        </div>

        {/* Expert mode */}
        <div className="mt-5 pt-5 border-t border-border">
          <button onClick={() => setExpertOpen((v) => !v)} className="flex items-center gap-2 text-[12px]" style={{ color: "var(--muted-foreground)" }}>
            <motion.span animate={{ rotate: expertOpen ? 0 : -90 }} transition={{ duration: 0.2 }}>
              <ChevronDown size={12} />
            </motion.span>
            <span>Expert overrides</span>
          </button>
          <AnimatePresence initial={false}>
            {expertOpen && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.22 }}
                style={{ overflow: "hidden" }}
              >
                <div className="pt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                  {["Pin AAPL — always trade", "Pin NVDA — always trade", "Disable GME — never trade", "Disable AMC — never trade"].map((rule) => (
                    <div key={rule} className="flex items-center justify-between px-3 py-2 rounded-md border border-dashed border-border" style={{ background: "var(--muted)" }}>
                      <span className="text-[11px]" style={{ color: "var(--foreground)", fontFamily: "var(--font-mono)" }}>{rule}</span>
                      <button className="text-[10px]" style={{ color: "var(--rose)" }}>Remove</button>
                    </div>
                  ))}
                </div>
                <button className="mt-3 text-[11px] px-3 py-1.5 rounded-md border border-dashed border-border" style={{ color: "var(--muted-foreground)" }}>
                  + Add override
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </Block>

      {/* BLOCK 2 — PROOF */}
      <Block title="Settings audit" desc="Proves what you saved is what the agents actually see right now">
        <div className="rounded-md border border-border overflow-hidden" style={{ background: "var(--background)" }}>
          <table className="w-full text-[12px]">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Key", "Saved value", "Live in runtime", ""].map((c) => (
                  <th key={c} className="px-4 py-2.5 text-left" style={{ color: "var(--muted-foreground)", fontWeight: 500, fontFamily: "var(--font-mono)", fontSize: "10px", letterSpacing: "0.05em" }}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {auditRows.map((row, i) => {
                const matches = row.saved === row.live;
                return (
                  <tr key={row.key} style={{ borderBottom: i < auditRows.length - 1 ? "1px solid var(--border)" : "none" }}>
                    <td className="px-4 py-2.5" style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{row.key}</td>
                    <td className="px-4 py-2.5" style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>{row.saved}</td>
                    <td className="px-4 py-2.5" style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>{row.live}</td>
                    <td className="px-4 py-2.5">
                      <span className="flex items-center gap-1 text-[10px]" style={{ color: matches ? "var(--emerald)" : "var(--rose)" }}>
                        {matches ? <Check size={11} /> : <X size={11} />}
                        {matches ? "Match" : "Drift"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="flex items-center gap-2 mt-3 text-[11px]" style={{ color: "var(--emerald)" }}>
          <ShieldCheck size={12} />
          <span>All {auditRows.length} settings are live in the agent runtime. No hidden overrides.</span>
        </div>
      </Block>

      {/* BLOCK 3 — LEARNING INSIGHTS */}
      <Block title="Learning insights" desc="What the post-mortem analyzer has learned from your trade history">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Per-strategy table */}
          <div className="rounded-md border border-border overflow-hidden" style={{ background: "var(--background)" }}>
            <table className="w-full text-[12px]">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {["Strategy", "Win", "Avg W", "Avg L", "Med TCS"].map((c) => (
                    <th key={c} className="px-3 py-2 text-left" style={{ color: "var(--muted-foreground)", fontWeight: 500, fontFamily: "var(--font-mono)", fontSize: "10px", letterSpacing: "0.05em" }}>
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {learningRows.map((r, i) => (
                  <tr key={r.strategy} style={{ borderBottom: i < learningRows.length - 1 ? "1px solid var(--border)" : "none" }}>
                    <td className="px-3 py-2 text-[11px]" style={{ color: "var(--foreground)" }}>{r.strategy}</td>
                    <td className="px-3 py-2" style={{ fontFamily: "var(--font-mono)", color: "var(--emerald)" }}>{r.winRate}</td>
                    <td className="px-3 py-2" style={{ fontFamily: "var(--font-mono)", color: "var(--emerald)" }}>{r.avgWin}</td>
                    <td className="px-3 py-2" style={{ fontFamily: "var(--font-mono)", color: "var(--rose)" }}>{r.avgLoss}</td>
                    <td className="px-3 py-2" style={{ fontFamily: "var(--font-mono)", color: "var(--treasure)" }}>{r.medTcs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Trade pattern grid */}
          <div>
            <div className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              Your trade patterns (last 30 days)
            </div>
            <div className="grid grid-cols-2 gap-2">
              {tradePatterns.map((p, i) => (
                <motion.div
                  key={p.label}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.1 + i * 0.05 }}
                  className="rounded-md border border-border p-3"
                  style={{ background: "var(--background)" }}
                >
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "20px", fontWeight: 500, color: p.color }}>
                    {p.count}
                  </div>
                  <div className="text-[10px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>{p.label}</div>
                </motion.div>
              ))}
            </div>
          </div>
        </div>

        {/* Suggestions */}
        <div className="mt-5 pt-5 border-t border-border">
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--treasure)", letterSpacing: "0.08em", fontWeight: 600 }}>
            <Lightbulb size={11} /> Tuning suggestions
          </div>
          <div className="space-y-2">
            {suggestions.map((s, i) => {
              const t = toneStyles[s.tone];
              return (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.06 }}
                  className="flex items-start gap-2.5 px-3 py-2 rounded-md border border-border"
                  style={{ background: "var(--background)" }}
                >
                  <span className="mt-0.5" style={{ color: t.color }}>{t.icon}</span>
                  <span className="text-[12px]" style={{ color: "var(--muted-foreground)" }}>{s.text}</span>
                </motion.div>
              );
            })}
          </div>
        </div>
      </Block>

      {/* BLOCK 4 — TRADE IMPORT */}
      <Block title="Trade import" desc="Feed historical trades into the learning layer">
        {importStep === "idle" && (
          <motion.button
            whileHover={{ scale: 1.005 }}
            onClick={() => setImportStep("review")}
            className="w-full px-5 py-6 rounded-lg border-2 border-dashed flex flex-col items-center gap-2"
            style={{ borderColor: "var(--border)", color: "var(--muted-foreground)" }}
          >
            <Upload size={18} />
            <span className="text-[13px]" style={{ color: "var(--foreground)" }}>Upload CSV, PDF, image, or XLSX</span>
            <span className="text-[11px]">Two steps — review extracted rows before importing</span>
          </motion.button>
        )}

        {importStep === "review" && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 px-3 py-2 rounded-md border border-dashed" style={{ borderColor: "rgba(196,150,74,0.4)", background: "rgba(196,150,74,0.05)" }}>
              <FileText size={13} style={{ color: "var(--treasure)" }} />
              <span className="text-[12px]" style={{ color: "var(--foreground)" }}>june-trades.csv</span>
              <span className="ml-auto text-[11px]" style={{ color: "var(--muted-foreground)" }}>42 rows extracted</span>
            </div>
            <div className="rounded-md border border-border overflow-hidden" style={{ background: "var(--background)" }}>
              <table className="w-full text-[11px]">
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border)" }}>
                    {["Date", "Ticker", "Side", "Qty", "P&L"].map((c) => (
                      <th key={c} className="px-3 py-2 text-left" style={{ color: "var(--muted-foreground)", fontWeight: 500, fontFamily: "var(--font-mono)" }}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[
                    { d: "06/15", t: "NVDA", s: "LONG", q: 5, p: 142.50 },
                    { d: "06/14", t: "AAPL", s: "SHORT", q: 10, p: -32.10 },
                    { d: "06/13", t: "TSLA", s: "LONG", q: 3, p: 78.40 },
                  ].map((row, i) => (
                    <tr key={i} style={{ borderBottom: i < 2 ? "1px solid var(--border)" : "none" }}>
                      <td className="px-3 py-1.5" style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{row.d}</td>
                      <td className="px-3 py-1.5" style={{ fontFamily: "var(--font-mono)", fontWeight: 500 }}>{row.t}</td>
                      <td className="px-3 py-1.5">
                        <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: row.s === "LONG" ? "rgba(16,185,129,0.12)" : "rgba(244,63,94,0.12)", color: row.s === "LONG" ? "var(--emerald)" : "var(--rose)", fontFamily: "var(--font-mono)" }}>
                          {row.s}
                        </span>
                      </td>
                      <td className="px-3 py-1.5" style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{row.q}</td>
                      <td className="px-3 py-1.5" style={{ fontFamily: "var(--font-mono)", color: row.p >= 0 ? "var(--emerald)" : "var(--rose)" }}>
                        {row.p >= 0 ? "+" : ""}${row.p.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="px-3 py-2 text-[10px] text-center border-t border-border" style={{ background: "var(--muted)", color: "var(--muted-foreground)" }}>
                + 39 more rows
              </div>
            </div>
            <div className="flex items-center justify-end gap-2">
              <button onClick={() => setImportStep("idle")} className="px-3 py-2 rounded-md text-[12px] border border-border" style={{ color: "var(--muted-foreground)" }}>
                Cancel
              </button>
              <button onClick={() => setImportStep("done")} className="px-4 py-2 rounded-md text-[12px]" style={{ background: "var(--treasure)", color: "var(--background)", fontWeight: 500 }}>
                Import 42 trades
              </button>
            </div>
          </div>
        )}

        {importStep === "done" && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-center py-8">
            <div className="w-12 h-12 mx-auto rounded-full flex items-center justify-center mb-3" style={{ background: "rgba(16,185,129,0.15)", color: "var(--emerald)" }}>
              <Check size={20} />
            </div>
            <div className="text-[14px]" style={{ fontWeight: 500 }}>42 trades imported</div>
            <p className="text-[12px] mt-1" style={{ color: "var(--muted-foreground)" }}>The learning layer will recompute insights on its next pass.</p>
            <button onClick={() => setImportStep("idle")} className="mt-4 text-[11px] underline" style={{ color: "var(--treasure)" }}>
              Import another
            </button>
          </motion.div>
        )}
      </Block>

      <div className="h-4" />
    </div>
  );
}

/* ─── helpers ───────────────────────────────────────────────────── */

function Block({ title, desc, children }: { title: string; desc: string; children: React.ReactNode }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="rounded-xl border border-border obsidian-panel p-5"
      style={{ background: "var(--card)" }}
    >
      <div className="mb-4">
        <h3 className="text-[14px]" style={{ fontWeight: 500, fontFamily: "var(--font-serif)" }}>{title}</h3>
        <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>{desc}</p>
      </div>
      {children}
    </motion.section>
  );
}

function Label({ text, hint }: { text: string; hint?: string }) {
  return (
    <div className="mb-2">
      <div className="text-[10px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>{text}</div>
      {hint && <div className="text-[10px] mt-0.5" style={{ color: "var(--muted-foreground)", opacity: 0.75 }}>{hint}</div>}
    </div>
  );
}

function SliderRow({ label, hint, value, setValue, min, max, step, prefix, suffix, tone }: {
  label: string; hint?: string; value: number; setValue: (v: number) => void;
  min: number; max: number; step: number; prefix?: string; suffix?: string; tone?: string;
}) {
  const color = tone === "rose" ? "var(--rose)" : "var(--treasure)";
  return (
    <div>
      <Label text={label} hint={hint} />
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={min} max={max} step={step}
          value={value}
          onChange={(e) => setValue(parseFloat(e.target.value))}
          className="flex-1"
          style={{ accentColor: color }}
        />
        <span className="text-[13px] min-w-[60px] text-right" style={{ fontFamily: "var(--font-mono)", color, fontWeight: 500 }}>
          {prefix || ""}{value.toLocaleString()}{suffix || ""}
        </span>
      </div>
    </div>
  );
}

function Toggle({ on, onClick, large = false }: { on: boolean; onClick: () => void; large?: boolean }) {
  const w = large ? 52 : 40;
  const h = large ? 30 : 24;
  const dot = large ? 24 : 20;
  return (
    <button
      onClick={onClick}
      className="relative rounded-full transition-colors shrink-0"
      style={{ width: w, height: h, background: on ? "var(--treasure)" : "var(--muted)" }}
      aria-pressed={on}
    >
      <motion.span
        className="absolute top-1/2 rounded-full shadow-md"
        style={{ background: "var(--background)", width: dot, height: dot, marginTop: -dot / 2 }}
        animate={{ x: on ? w - dot - 3 : 3 }}
        transition={{ type: "spring", stiffness: 500, damping: 30 }}
      />
    </button>
  );
}
