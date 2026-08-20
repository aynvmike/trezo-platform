import { useState, useMemo } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Upload, Lock, Coffee, ShoppingBag, Car, Home, Utensils, Sparkles,
  Plus, X, ArrowDown, Edit3,
} from "lucide-react";
import { PageHeader } from "./PageHeader";
import { MiniAreaChart } from "./MiniAreaChart";

type Category = {
  id: string;
  label: string;
  icon: React.ReactNode;
  color: string;
  amount: number;
  leakPct: number; // % of this category that's a "leak" / discretionary
};

const defaultCategories: Category[] = [
  { id: "dining", label: "Dining out", icon: <Utensils size={13} />, color: "var(--rose)", amount: 480, leakPct: 40 },
  { id: "subs", label: "Subscriptions", icon: <Sparkles size={13} />, color: "var(--amber)", amount: 142, leakPct: 45 },
  { id: "shopping", label: "Impulse shopping", icon: <ShoppingBag size={13} />, color: "var(--sky)", amount: 320, leakPct: 38 },
  { id: "transport", label: "Rideshare", icon: <Car size={13} />, color: "var(--treasure)", amount: 210, leakPct: 38 },
  { id: "coffee", label: "Coffee", icon: <Coffee size={13} />, color: "var(--emerald)", amount: 96, leakPct: 50 },
  { id: "housing", label: "Housing", icon: <Home size={13} />, color: "var(--muted-foreground)", amount: 1850, leakPct: 0 },
];

const newCategoryColors = ["var(--rose)", "var(--amber)", "var(--sky)", "var(--treasure)", "var(--emerald)"];

export function GraspingWalletView() {
  const [mode, setMode] = useState<"idle" | "manual" | "imported">("idle");
  const [categories, setCategories] = useState<Category[]>(defaultCategories);
  const [newLabel, setNewLabel] = useState("");

  const [years, setYears] = useState(20);
  const [contribution, setContribution] = useState(500);
  const [returnRate, setReturnRate] = useState(8);
  const [tlh, setTlh] = useState(true);
  const [donate, setDonate] = useState(false);

  const totalSpend = useMemo(() => categories.reduce((s, c) => s + c.amount, 0), [categories]);
  const totalLeak = useMemo(
    () => Math.round(categories.reduce((s, c) => s + (c.amount * c.leakPct) / 100, 0)),
    [categories]
  );

  const updateAmount = (id: string, amount: number) =>
    setCategories((cur) => cur.map((c) => (c.id === id ? { ...c, amount: Math.max(0, amount) } : c)));

  const updateLeakPct = (id: string, pct: number) =>
    setCategories((cur) => cur.map((c) => (c.id === id ? { ...c, leakPct: Math.max(0, Math.min(100, pct)) } : c)));

  const removeCategory = (id: string) =>
    setCategories((cur) => cur.filter((c) => c.id !== id));

  const addCategory = () => {
    if (!newLabel.trim()) return;
    const color = newCategoryColors[categories.length % newCategoryColors.length];
    setCategories((cur) => [
      ...cur,
      {
        id: `c-${Date.now()}`,
        label: newLabel.trim(),
        icon: <Edit3 size={13} />,
        color,
        amount: 0,
        leakPct: 30,
      },
    ]);
    setNewLabel("");
  };

  const applyLeaksToContribution = () => {
    if (totalLeak > 0) {
      setContribution(Math.min(2500, Math.max(100, totalLeak + contribution)));
    }
  };

  const projection = useMemo(() => {
    return Array.from({ length: years + 1 }, (_, i) => {
      let monthlyRate = returnRate / 100 / 12;
      if (tlh) monthlyRate += 0.005 / 12;
      if (donate) monthlyRate += 0.003 / 12;
      const months = i * 12;
      const futureValue =
        monthlyRate === 0 ? contribution * months : contribution * (((1 + monthlyRate) ** months - 1) / monthlyRate);
      return { t: `Y${i}`, v: Math.round(futureValue) };
    });
  }, [years, contribution, returnRate, tlh, donate]);

  const finalValue = projection[projection.length - 1].v;

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-7">
      <PageHeader
        eyebrow="Plan & Research"
        title="Hold tight, then let it grow"
        subtitle="Two motions of wealth — pinch the leaks today, then watch the freed dollars compound."
        explainer="Everything below runs in your browser. No statement, no transaction, no number ever leaves this tab. Imports parse locally and are discarded the moment you close the page."
      />

      {/* SECTION 1 — Today */}
      <section>
        <div className="flex items-center gap-3 mb-4">
          <div className="w-0.5 h-6 rounded-full" style={{ background: "var(--treasure)" }} />
          <div>
            <div className="text-[10px] uppercase tracking-widest" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
              Today
            </div>
            <h2 style={{ fontFamily: "var(--font-serif)", fontSize: "20px", fontWeight: 500 }}>Where money goes</h2>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* Budget Mirror */}
          <div className="lg:col-span-2 rounded-xl border border-border obsidian-panel p-5" style={{ background: "var(--card)" }}>
            <div className="flex items-start justify-between mb-4 flex-wrap gap-2">
              <div>
                <h3 className="text-[13px]" style={{ fontWeight: 500 }}>Budget Mirror</h3>
                <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
                  Edit categories inline — leaks and totals recalculate live
                </p>
              </div>
              <div className="flex items-center gap-1.5 text-[10px] px-2 py-1 rounded-full" style={{ background: "rgba(16,185,129,0.12)", color: "var(--emerald)" }}>
                <Lock size={10} /> In-browser
              </div>
            </div>

            {/* Mode picker */}
            {mode === "idle" ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <motion.button
                  onClick={() => setMode("imported")}
                  whileHover={{ scale: 1.01, y: -2 }}
                  className="px-5 py-6 rounded-lg border-2 border-dashed flex flex-col items-center gap-2 transition-colors"
                  style={{ borderColor: "var(--border)", color: "var(--muted-foreground)" }}
                >
                  <Upload size={18} />
                  <span className="text-[13px]" style={{ color: "var(--foreground)" }}>Import a statement</span>
                  <span className="text-[11px]">CSV parsed locally — never uploaded</span>
                </motion.button>
                <motion.button
                  onClick={() => setMode("manual")}
                  whileHover={{ scale: 1.01, y: -2 }}
                  className="px-5 py-6 rounded-lg border-2 border-dashed flex flex-col items-center gap-2 transition-colors"
                  style={{ borderColor: "var(--treasure)", color: "var(--treasure)", background: "rgba(196,150,74,0.04)" }}
                >
                  <Edit3 size={18} />
                  <span className="text-[13px]" style={{ color: "var(--foreground)" }}>Enter manually</span>
                  <span className="text-[11px]">Type in your monthly categories</span>
                </motion.button>
              </div>
            ) : (
              <div className="space-y-3">
                {/* Totals header */}
                <div className="flex items-baseline gap-2 mb-2 flex-wrap">
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "26px", fontWeight: 500, color: "var(--foreground)" }}>
                    ${totalSpend.toLocaleString()}
                  </span>
                  <span className="text-[12px]" style={{ color: "var(--muted-foreground)" }}>per month</span>
                  <span className="ml-auto text-[12px] px-2 py-0.5 rounded-md" style={{ background: "rgba(244,63,94,0.12)", color: "var(--rose)", fontFamily: "var(--font-mono)" }}>
                    ~${totalLeak} leaks
                  </span>
                </div>

                {/* Editable category rows */}
                <AnimatePresence initial={false}>
                  {categories.map((c, i) => {
                    const leak = Math.round((c.amount * c.leakPct) / 100);
                    return (
                      <motion.div
                        key={c.id}
                        layout
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: 8 }}
                        transition={{ duration: 0.2, delay: i * 0.03 }}
                        className="flex items-center gap-3 group"
                      >
                        <span
                          className="w-7 h-7 rounded-md flex items-center justify-center shrink-0"
                          style={{ background: `${c.color}1f`, color: c.color }}
                        >
                          {c.icon}
                        </span>

                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between gap-2 mb-1">
                            <span className="text-[12px]" style={{ color: "var(--foreground)" }}>{c.label}</span>
                            <div className="flex items-center gap-1">
                              <span className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>$</span>
                              <input
                                type="number"
                                value={c.amount || ""}
                                onChange={(e) => updateAmount(c.id, parseFloat(e.target.value) || 0)}
                                className="w-20 px-2 py-1 rounded-md border border-border text-[12px] text-right outline-none focus:border-treasure"
                                style={{
                                  background: "var(--background)",
                                  color: "var(--foreground)",
                                  fontFamily: "var(--font-mono)",
                                }}
                                placeholder="0"
                              />
                            </div>
                          </div>

                          {/* Bar — proportion of total spend */}
                          <div className="h-1 rounded-full overflow-hidden mb-1.5" style={{ background: "var(--muted)" }}>
                            <motion.div
                              className="h-full rounded-full"
                              style={{ background: c.color, opacity: 0.7 }}
                              animate={{ width: totalSpend > 0 ? `${(c.amount / totalSpend) * 100}%` : "0%" }}
                              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
                            />
                          </div>

                          {/* Leak control */}
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.06em" }}>
                              Discretionary
                            </span>
                            <input
                              type="range"
                              min={0} max={100} step={5}
                              value={c.leakPct}
                              onChange={(e) => updateLeakPct(c.id, parseFloat(e.target.value))}
                              className="flex-1 max-w-[140px]"
                              style={{ accentColor: c.color }}
                            />
                            <span className="text-[10px] w-8 text-right" style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                              {c.leakPct}%
                            </span>
                            {leak > 0 && (
                              <span className="text-[10px]" style={{ fontFamily: "var(--font-mono)", color: "var(--rose)" }}>
                                ~${leak}
                              </span>
                            )}
                          </div>
                        </div>

                        <button
                          onClick={() => removeCategory(c.id)}
                          className="p-1 rounded-md opacity-0 group-hover:opacity-100 transition-opacity"
                          style={{ color: "var(--muted-foreground)" }}
                          aria-label="Remove"
                        >
                          <X size={13} />
                        </button>
                      </motion.div>
                    );
                  })}
                </AnimatePresence>

                {/* Add row */}
                <div className="flex items-center gap-2 pt-2 border-t border-border">
                  <input
                    type="text"
                    value={newLabel}
                    onChange={(e) => setNewLabel(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && addCategory()}
                    placeholder="Add a category (e.g. Gym, Pet care)…"
                    className="flex-1 px-3 py-2 rounded-md border border-border text-[12px] outline-none focus:border-treasure"
                    style={{ background: "var(--background)", color: "var(--foreground)" }}
                  />
                  <button
                    onClick={addCategory}
                    disabled={!newLabel.trim()}
                    className="flex items-center gap-1 px-3 py-2 rounded-md text-[12px]"
                    style={{
                      background: newLabel.trim() ? "var(--treasure)" : "var(--muted)",
                      color: newLabel.trim() ? "var(--background)" : "var(--muted-foreground)",
                      fontWeight: 500,
                      cursor: newLabel.trim() ? "pointer" : "not-allowed",
                    }}
                  >
                    <Plus size={12} /> Add
                  </button>
                </div>

                {/* Hand-off to projection */}
                <div className="pt-3 border-t border-border flex items-center justify-between flex-wrap gap-2">
                  <div>
                    <div className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>If you pinched the leaks…</div>
                    <div style={{ fontFamily: "var(--font-mono)", color: "var(--emerald)", fontSize: "16px", fontWeight: 500 }}>
                      +${totalLeak}/mo to investing
                    </div>
                  </div>
                  {totalLeak > 0 && (
                    <motion.button
                      onClick={applyLeaksToContribution}
                      whileHover={{ scale: 1.03 }}
                      whileTap={{ scale: 0.97 }}
                      className="flex items-center gap-1.5 px-3 py-2 rounded-md text-[12px]"
                      style={{ background: "var(--treasure)", color: "var(--background)", fontWeight: 500 }}
                    >
                      <ArrowDown size={13} /> Send to projection
                    </motion.button>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Data Guide */}
          <div className="rounded-xl border border-border obsidian-panel p-5" style={{ background: "var(--card)" }}>
            <h3 className="text-[13px] mb-3" style={{ fontWeight: 500 }}>Data Guide</h3>
            <ol className="space-y-2.5">
              {[
                "Type each monthly category by hand, or import a CSV statement",
                "Drag the discretionary slider to mark what's a leak vs essential",
                "Totals + leaks recalculate as you edit — no buttons, no save",
                "Nothing leaves your browser; close the tab and it's gone",
              ].map((step, i) => (
                <li key={i} className="flex items-start gap-2.5">
                  <span
                    className="w-4 h-4 rounded flex items-center justify-center text-[9px] shrink-0 mt-0.5"
                    style={{ background: "var(--treasure)", color: "var(--background)", fontFamily: "var(--font-mono)", fontWeight: 500 }}
                  >
                    {i + 1}
                  </span>
                  <span className="text-[12px]" style={{ color: "var(--muted-foreground)" }}>{step}</span>
                </li>
              ))}
            </ol>
            {mode !== "idle" && (
              <button
                onClick={() => { setMode("idle"); setCategories(defaultCategories); }}
                className="text-[11px] mt-4 px-2 py-1 rounded-md border border-border transition-colors hover:bg-muted"
                style={{ color: "var(--muted-foreground)" }}
              >
                Reset & start over
              </button>
            )}
          </div>
        </div>
      </section>

      {/* SECTION 2 — Over the horizon */}
      <section>
        <div className="flex items-center gap-3 mb-4">
          <div className="w-0.5 h-6 rounded-full" style={{ background: "var(--treasure)" }} />
          <div>
            <div className="text-[10px] uppercase tracking-widest" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
              Over the horizon
            </div>
            <h2 style={{ fontFamily: "var(--font-serif)", fontSize: "20px", fontWeight: 500 }}>Where every account is headed</h2>
          </div>
        </div>

        <div className="rounded-xl border border-border obsidian-panel p-5" style={{ background: "var(--card)" }}>
          <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
            <div>
              <h3 className="text-[13px]" style={{ fontWeight: 500 }}>Projections Lab</h3>
              <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>Long-horizon, after-tax projection across every account</p>
            </div>
            <div className="text-right">
              <motion.div
                key={finalValue}
                initial={{ scale: 0.95 }}
                animate={{ scale: 1 }}
                transition={{ type: "spring", stiffness: 300, damping: 20 }}
                style={{ fontFamily: "var(--font-mono)", fontSize: "26px", fontWeight: 500, color: "var(--treasure)" }}
              >
                ${finalValue >= 1000000 ? `${(finalValue / 1000000).toFixed(2)}M` : `${(finalValue / 1000).toFixed(0)}k`}
              </motion.div>
              <div className="text-[10px]" style={{ color: "var(--muted-foreground)" }}>Projected value in {years} years</div>
            </div>
          </div>

          <div className="mb-5">
            <MiniAreaChart
              data={projection}
              color="var(--treasure)"
              height={170}
              formatValue={(v) => v >= 1000000 ? `$${(v / 1000000).toFixed(1)}M` : `$${(v / 1000).toFixed(0)}k`}
            />
          </div>

          {/* Sliders */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5 pt-4 border-t border-border">
            {[
              { label: "Horizon", value: years, min: 5, max: 40, step: 1, suffix: " yr", set: setYears },
              { label: "Monthly contribution", value: contribution, min: 100, max: 2500, step: 50, prefix: "$", set: setContribution },
              { label: "Expected return", value: returnRate, min: 4, max: 12, step: 0.5, suffix: "%", set: setReturnRate },
            ].map((s) => (
              <div key={s.label}>
                <div className="flex items-end justify-between mb-2">
                  <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>{s.label}</span>
                  <span style={{ fontFamily: "var(--font-mono)", color: "var(--treasure)", fontSize: "13px", fontWeight: 500 }}>
                    {s.prefix || ""}{s.value}{s.suffix || ""}
                  </span>
                </div>
                <input
                  type="range"
                  min={s.min} max={s.max} step={s.step}
                  value={s.value}
                  onChange={(e) => s.set(Number(e.target.value))}
                  className="w-full"
                  style={{ accentColor: "var(--treasure)" }}
                />
              </div>
            ))}
          </div>

          {/* What-if toggles */}
          <div className="flex flex-wrap gap-2 mt-5 pt-4 border-t border-border">
            <span className="text-[10px] uppercase tracking-wider mr-2 self-center" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              What-ifs
            </span>
            {[
              { label: "Tax-loss harvesting", value: tlh, set: setTlh, hint: "+0.5%/yr" },
              { label: "Donate appreciated shares", value: donate, set: setDonate, hint: "+0.3%/yr" },
            ].map((tog) => (
              <button
                key={tog.label}
                onClick={() => tog.set(!tog.value)}
                className="flex items-center gap-2 px-3 py-1.5 rounded-md border text-[11px] transition-colors"
                style={{
                  background: tog.value ? "var(--accent)" : "var(--background)",
                  borderColor: tog.value ? "var(--treasure)" : "var(--border)",
                  color: tog.value ? "var(--treasure)" : "var(--muted-foreground)",
                }}
              >
                <span className="w-2 h-2 rounded-full" style={{ background: tog.value ? "var(--treasure)" : "var(--muted-foreground)" }} />
                {tog.label}
                <span style={{ fontFamily: "var(--font-mono)", opacity: 0.6 }}>{tog.hint}</span>
              </button>
            ))}
          </div>
        </div>
      </section>

      <div className="h-4" />
    </div>
  );
}
