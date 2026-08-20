import { useState } from "react";
import { motion } from "motion/react";
import { Sun, Moon, GraduationCap, Briefcase, Info, Check } from "lucide-react";
import { PageHeader } from "./PageHeader";

export function ProfileView() {
  const [name] = useState("Operator");
  const [stockCap, setStockCap] = useState(3000);
  const [cryptoCap, setCryptoCap] = useState(1500);
  const [optionsCap, setOptionsCap] = useState(500);
  const [profitTarget, setProfitTarget] = useState(150);
  const [lossLimit, setLossLimit] = useState(500);
  const [risk, setRisk] = useState("Balanced");
  const [filing, setFiling] = useState("Single");
  const [income, setIncome] = useState(85000);
  const [employerMatch, setEmployerMatch] = useState(5);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [level, setLevel] = useState<"beginner" | "pro">("beginner");

  const totalCap = stockCap + cryptoCap + optionsCap;

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
      <PageHeader
        eyebrow="Settings — Profile"
        title="Your account"
        subtitle="Capital, discipline rules, and tax filing. Saved here, read by the agents on their next tick."
      />

      {/* Quick "applies on next tick" reassurance */}
      <div className="flex items-center gap-2 text-[11px] px-3 py-2 rounded-lg border border-dashed" style={{ borderColor: "rgba(16,185,129,0.4)", background: "rgba(16,185,129,0.05)" }}>
        <Check size={12} style={{ color: "var(--emerald)" }} />
        <span style={{ color: "var(--muted-foreground)" }}>
          Changes apply on the next agent tick (~30s). Profit target and loss limit apply immediately.
        </span>
      </div>

      {/* CAPITAL */}
      <Section title="Capital" description="How much you've allocated per asset class">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Slider label="Stock" value={stockCap} setValue={setStockCap} min={0} max={50000} step={250} prefix="$" />
          <Slider label="Crypto" value={cryptoCap} setValue={setCryptoCap} min={0} max={25000} step={100} prefix="$" />
          <Slider label="Options" value={optionsCap} setValue={setOptionsCap} min={0} max={15000} step={100} prefix="$" />
        </div>
        <div className="mt-3 pt-3 border-t border-border flex items-center justify-between">
          <span className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>Total deployed across Trezo</span>
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--treasure)", fontWeight: 500, fontSize: "16px" }}>
            ${totalCap.toLocaleString()}
          </span>
        </div>
      </Section>

      {/* DISCIPLINE */}
      <Section title="Discipline" description="The lines the bots will not cross">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Slider label="Daily profit target" value={profitTarget} setValue={setProfitTarget} min={50} max={2000} step={25} prefix="$" hint="Bots ease off after hitting this" />
          <Slider label="Daily loss limit" value={lossLimit} setValue={setLossLimit} min={100} max={5000} step={50} prefix="$" hint="Everything pauses if breached" />
          <div>
            <label className="text-[10px] uppercase tracking-wider mb-2 block" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              Risk tolerance
            </label>
            <div className="flex flex-wrap gap-1.5">
              {["Conservative", "Balanced", "Aggressive", "Expert"].map((r) => (
                <button
                  key={r}
                  onClick={() => setRisk(r)}
                  className="px-2.5 py-1.5 rounded-md text-[11px] border transition-colors"
                  style={{
                    background: risk === r ? "var(--accent)" : "var(--background)",
                    borderColor: risk === r ? "var(--treasure)" : "var(--border)",
                    color: risk === r ? "var(--treasure)" : "var(--foreground)",
                  }}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
        </div>
      </Section>

      {/* TAX */}
      <Section title="Tax" description="Powers the Tax Optimizer estimates. Optional fields stay local.">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="text-[10px] uppercase tracking-wider mb-2 block" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              Filing status
            </label>
            <div className="flex flex-wrap gap-1.5">
              {["Single", "Married", "HoH"].map((s) => (
                <button
                  key={s}
                  onClick={() => setFiling(s)}
                  className="px-2.5 py-1.5 rounded-md text-[11px] border transition-colors"
                  style={{
                    background: filing === s ? "var(--accent)" : "var(--background)",
                    borderColor: filing === s ? "var(--treasure)" : "var(--border)",
                    color: filing === s ? "var(--treasure)" : "var(--foreground)",
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
          <Slider label="W-2 income" value={income} setValue={setIncome} min={0} max={400000} step={5000} prefix="$" hint="Optional — drives the bracket estimate" />
          <Slider label="Employer 401(k) match" value={employerMatch} setValue={setEmployerMatch} min={0} max={15} step={0.5} suffix="%" hint="So projections include free money" />
        </div>
      </Section>

      {/* DISPLAY */}
      <Section title="Display preferences" description="How the rest of the app looks and how chatty it is">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Theme switch */}
          <div>
            <div className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              Theme
            </div>
            <div className="relative inline-flex p-1 rounded-lg border border-border" style={{ background: "var(--background)" }}>
              {(["dark", "light"] as const).map((opt) => (
                <button
                  key={opt}
                  onClick={() => setTheme(opt)}
                  className="relative px-4 py-2 text-[12px] rounded-md flex items-center gap-1.5 z-10"
                  style={{ color: theme === opt ? "var(--background)" : "var(--muted-foreground)" }}
                >
                  {theme === opt && (
                    <motion.div
                      layoutId="profile-theme-pill"
                      className="absolute inset-0 rounded-md"
                      style={{ background: "var(--treasure)" }}
                      transition={{ type: "spring", stiffness: 380, damping: 30 }}
                    />
                  )}
                  <span className="relative">{opt === "dark" ? <Moon size={12} /> : <Sun size={12} />}</span>
                  <span className="relative capitalize">{opt}</span>
                </button>
              ))}
            </div>
            <p className="text-[11px] mt-2" style={{ color: "var(--muted-foreground)" }}>
              Neo Obsidian is the product — light mode is for daytime browsers.
            </p>
          </div>

          {/* Experience level */}
          <div>
            <div className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
              Experience level
            </div>
            <div className="relative inline-flex p-1 rounded-lg border border-border" style={{ background: "var(--background)" }}>
              {([
                { id: "beginner", label: "Beginner", icon: <GraduationCap size={12} /> },
                { id: "pro", label: "Pro", icon: <Briefcase size={12} /> },
              ] as const).map((opt) => (
                <button
                  key={opt.id}
                  onClick={() => setLevel(opt.id)}
                  className="relative px-4 py-2 text-[12px] rounded-md flex items-center gap-1.5 z-10"
                  style={{ color: level === opt.id ? "var(--background)" : "var(--muted-foreground)" }}
                >
                  {level === opt.id && (
                    <motion.div
                      layoutId="profile-level-pill"
                      className="absolute inset-0 rounded-md"
                      style={{ background: "var(--treasure)" }}
                      transition={{ type: "spring", stiffness: 380, damping: 30 }}
                    />
                  )}
                  <span className="relative">{opt.icon}</span>
                  <span className="relative">{opt.label}</span>
                </button>
              ))}
            </div>
            <p className="text-[11px] mt-2" style={{ color: "var(--muted-foreground)" }}>
              {level === "beginner"
                ? "Plain-English explainers appear next to every control."
                : "Explainers hidden. Numbers and dials only."}
            </p>
          </div>
        </div>
      </Section>

      <div className="h-4" />
    </div>
  );
}

function Section({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="rounded-xl border border-border obsidian-panel p-5"
      style={{ background: "var(--card)" }}
    >
      <div className="flex items-end justify-between mb-4">
        <div>
          <h3 className="text-[14px]" style={{ fontWeight: 500, fontFamily: "var(--font-serif)" }}>{title}</h3>
          <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>{description}</p>
        </div>
      </div>
      {children}
    </motion.section>
  );
}

function Slider({ label, value, setValue, min, max, step, prefix, suffix, hint }: {
  label: string; value: number; setValue: (v: number) => void;
  min: number; max: number; step: number; prefix?: string; suffix?: string; hint?: string;
}) {
  return (
    <div>
      <div className="flex items-end justify-between mb-2">
        <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
          {label}
        </span>
        <span style={{ fontFamily: "var(--font-mono)", color: "var(--treasure)", fontSize: "13px", fontWeight: 500 }}>
          {prefix || ""}{value.toLocaleString()}{suffix || ""}
        </span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={(e) => setValue(parseFloat(e.target.value))}
        className="w-full"
        style={{ accentColor: "var(--treasure)" }}
      />
      {hint && (
        <p className="text-[10px] mt-1.5" style={{ color: "var(--muted-foreground)" }}>{hint}</p>
      )}
    </div>
  );
}
