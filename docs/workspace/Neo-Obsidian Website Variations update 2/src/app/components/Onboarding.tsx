import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  ArrowRight, ArrowLeft, Check, X, Sparkles, Plug, ShieldCheck, Layers as LayersIcon,
  Gauge,
} from "lucide-react";

type Props = {
  open: boolean;
  onClose: () => void;
  onComplete: (config: OnboardingConfig) => void;
};

export type OnboardingConfig = {
  broker: string;
  mode: "paper" | "live";
  activeLayers: number[];
  dailyRiskLimit: number;
};

const brokers = [
  { id: "alpaca", name: "Alpaca", desc: "Commission-free stocks & crypto API" },
  { id: "ibkr", name: "Interactive Brokers", desc: "Global multi-asset access" },
  { id: "tradier", name: "Tradier", desc: "Options-friendly broker API" },
  { id: "coinbase", name: "Coinbase", desc: "Crypto-only · spot trading" },
];

const allLayers = [
  { id: 1, name: "Crypto", desc: "BTC, ETH, alt momentum" },
  { id: 2, name: "Stock", desc: "Equity breakouts" },
  { id: 3, name: "Options", desc: "Debit spreads, directional" },
  { id: 4, name: "Stock Weekly", desc: "Weekly chart patterns" },
  { id: 5, name: "Wheel", desc: "CSP → CC cycles" },
  { id: 6, name: "Dividends", desc: "High-yield capture" },
  { id: 7, name: "KINDRIP", desc: "Responsible long-only ETFs" },
];

const stepMeta = [
  { title: "Welcome to Trezo", sub: "Seven layers, one woven basket", icon: <Sparkles size={14} /> },
  { title: "Connect a broker", sub: "Choose where Trezo routes your orders", icon: <Plug size={14} /> },
  { title: "Trading mode", sub: "Start safe — switch to live when ready", icon: <ShieldCheck size={14} /> },
  { title: "Pick your layers", sub: "Activate or pause any layer later", icon: <LayersIcon size={14} /> },
  { title: "Daily risk limit", sub: "Your safety cap — bots pause if breached", icon: <Gauge size={14} /> },
];

/* ─── Hero illustrations (one per step) ─────────────────────────────────── */

function WovenBasketHero({ activeLayers }: { activeLayers: number[] }) {
  // Concentric rings 1 (outer/volatile) → 7 (inner/protected)
  const rings = [1, 2, 3, 4, 5, 6, 7];
  return (
    <div className="relative h-44 flex items-center justify-center overflow-hidden">
      {rings.map((n) => {
        const size = 170 - (n - 1) * 22;
        const isActive = activeLayers.includes(n);
        return (
          <motion.div
            key={n}
            className="absolute rounded-full"
            style={{
              width: size,
              height: size,
              border: `1px solid ${isActive ? "var(--treasure)" : "var(--border)"}`,
              opacity: isActive ? 0.9 - n * 0.06 : 0.25,
            }}
            initial={{ scale: 0.6, opacity: 0 }}
            animate={{ scale: 1, opacity: isActive ? 0.9 - n * 0.06 : 0.25 }}
            transition={{ delay: n * 0.06, duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
          />
        );
      })}
      {/* Inner glow */}
      <motion.div
        className="absolute rounded-full"
        style={{
          width: 36, height: 36,
          background: "radial-gradient(circle, var(--treasure) 0%, transparent 70%)",
          opacity: 0.6,
        }}
        animate={{ scale: [1, 1.25, 1], opacity: [0.5, 0.85, 0.5] }}
        transition={{ duration: 3.6, repeat: Infinity, ease: "easeInOut" }}
      />
      {/* Orbiting chip */}
      <motion.div
        className="absolute"
        style={{ width: 170, height: 170 }}
        animate={{ rotate: 360 }}
        transition={{ duration: 18, repeat: Infinity, ease: "linear" }}
      >
        <div className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2">
          <motion.div
            className="w-2 h-2 rounded-full"
            style={{ background: "var(--treasure)", boxShadow: "0 0 12px var(--treasure)" }}
          />
        </div>
      </motion.div>
    </div>
  );
}

function BrokerHero({ selected }: { selected: string }) {
  return (
    <div className="relative h-32 flex items-center justify-center overflow-hidden">
      {/* Trezo node */}
      <motion.div
        initial={{ scale: 0.7, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="absolute left-[18%] flex items-center justify-center w-12 h-12 rounded-xl"
        style={{ background: "var(--treasure)", color: "var(--background)", fontFamily: "var(--font-serif)", fontSize: "18px", fontWeight: 500 }}
      >
        T
      </motion.div>
      {/* Broker node */}
      <motion.div
        initial={{ scale: 0.7, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.4, delay: 0.1 }}
        className="absolute right-[18%] flex items-center justify-center w-12 h-12 rounded-xl border border-border"
        style={{ background: "var(--card)" }}
      >
        <Plug size={18} style={{ color: selected ? "var(--emerald)" : "var(--muted-foreground)" }} />
      </motion.div>
      {/* Connection line */}
      <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none">
        <motion.line
          x1="22%" y1="50%" x2="78%" y2="50%"
          stroke={selected ? "var(--treasure)" : "var(--border)"}
          strokeWidth={1.5}
          strokeDasharray="4 4"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.7, delay: 0.2 }}
        />
      </svg>
      {/* Traveling pulse */}
      {selected && (
        <motion.div
          className="absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full"
          style={{ background: "var(--treasure)", boxShadow: "0 0 10px var(--treasure)", left: "22%" }}
          animate={{ left: ["22%", "78%"] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
        />
      )}
    </div>
  );
}

function ModeHero({ mode }: { mode: "paper" | "live" }) {
  return (
    <div className="relative h-32 flex items-center justify-center overflow-hidden">
      <motion.div
        className="absolute"
        animate={{ x: mode === "paper" ? -50 : 50, rotate: mode === "paper" ? -6 : 6 }}
        transition={{ type: "spring", stiffness: 200, damping: 18 }}
      >
        <div
          className="px-5 py-4 rounded-lg border"
          style={{
            background: mode === "paper" ? "var(--card)" : "var(--background)",
            borderColor: mode === "paper" ? "var(--emerald)" : "var(--border)",
            boxShadow: mode === "paper" ? "0 8px 32px rgba(16,185,129,0.18)" : "0 4px 12px rgba(0,0,0,0.2)",
          }}
        >
          <div className="text-[10px] mb-1" style={{ color: "var(--emerald)", fontFamily: "var(--font-mono)" }}>PAPER</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "16px", color: "var(--foreground)" }}>$0 risk</div>
        </div>
      </motion.div>
      <motion.div
        className="absolute"
        animate={{ x: mode === "live" ? -50 : 50, rotate: mode === "live" ? -6 : 6 }}
        transition={{ type: "spring", stiffness: 200, damping: 18 }}
      >
        <div
          className="px-5 py-4 rounded-lg border"
          style={{
            background: mode === "live" ? "var(--card)" : "var(--background)",
            borderColor: mode === "live" ? "var(--rose)" : "var(--border)",
            boxShadow: mode === "live" ? "0 8px 32px rgba(244,63,94,0.18)" : "0 4px 12px rgba(0,0,0,0.2)",
          }}
        >
          <div className="text-[10px] mb-1" style={{ color: "var(--rose)", fontFamily: "var(--font-mono)" }}>LIVE</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "16px", color: "var(--foreground)" }}>Real $</div>
        </div>
      </motion.div>
    </div>
  );
}

function LayersHero({ active }: { active: number[] }) {
  return (
    <div className="relative h-32 flex items-end justify-center gap-1.5 overflow-hidden pb-2">
      {[1, 2, 3, 4, 5, 6, 7].map((n) => {
        const isOn = active.includes(n);
        const height = 30 + n * 8;
        return (
          <motion.div
            key={n}
            className="rounded-md flex items-end justify-center pb-1.5"
            style={{
              width: 26,
              background: isOn ? "var(--treasure)" : "var(--muted)",
              opacity: isOn ? 0.85 : 0.4,
            }}
            initial={{ height: 0 }}
            animate={{
              height: isOn ? height : height * 0.5,
              opacity: isOn ? 0.85 : 0.4,
            }}
            transition={{ type: "spring", stiffness: 220, damping: 20, delay: n * 0.04 }}
          >
            <span className="text-[9px]" style={{ fontFamily: "var(--font-mono)", color: isOn ? "var(--background)" : "var(--muted-foreground)", fontWeight: 500 }}>
              {n}
            </span>
          </motion.div>
        );
      })}
    </div>
  );
}

function RiskGaugeHero({ value, max }: { value: number; max: number }) {
  const pct = value / max;
  // Arc from -120° to 120°
  const start = -120;
  const end = 120;
  const angle = start + (end - start) * pct;
  const R = 56;
  const cx = 90;
  const cy = 90;
  const toXY = (a: number) => {
    const rad = (a - 90) * (Math.PI / 180);
    return { x: cx + R * Math.cos(rad), y: cy + R * Math.sin(rad) };
  };
  const arcPath = (a1: number, a2: number) => {
    const p1 = toXY(a1);
    const p2 = toXY(a2);
    const large = a2 - a1 > 180 ? 1 : 0;
    return `M ${p1.x} ${p1.y} A ${R} ${R} 0 ${large} 1 ${p2.x} ${p2.y}`;
  };
  const needle = toXY(angle);

  return (
    <div className="relative h-32 flex items-center justify-center overflow-hidden">
      <svg width="180" height="120" viewBox="0 0 180 120">
        {/* Track */}
        <path d={arcPath(start, end)} stroke="var(--border)" strokeWidth={6} fill="none" strokeLinecap="round" />
        {/* Filled portion */}
        <motion.path
          d={arcPath(start, end)}
          stroke="var(--treasure)"
          strokeWidth={6}
          fill="none"
          strokeLinecap="round"
          initial={false}
          animate={{ pathLength: pct }}
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          style={{ pathLength: pct }}
        />
        {/* Tick marks */}
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => {
          const a = start + (end - start) * p;
          const inner = toXY(a);
          const a2 = a - 90;
          const tickLen = 5;
          const ox = cx + (R + 8) * Math.cos((a - 90) * Math.PI / 180);
          const oy = cy + (R + 8) * Math.sin((a - 90) * Math.PI / 180);
          return <circle key={i} cx={ox} cy={oy} r={1.2} fill="var(--muted-foreground)" opacity={0.5} />;
        })}
        {/* Needle */}
        <motion.line
          x1={cx} y1={cy}
          x2={needle.x} y2={needle.y}
          stroke="var(--treasure)"
          strokeWidth={2}
          strokeLinecap="round"
          animate={{ x2: needle.x, y2: needle.y }}
          transition={{ type: "spring", stiffness: 180, damping: 18 }}
        />
        <circle cx={cx} cy={cy} r={5} fill="var(--treasure)" />
        <circle cx={cx} cy={cy} r={2.5} fill="var(--background)" />
      </svg>
      {/* Value below */}
      <div className="absolute bottom-1 left-1/2 -translate-x-1/2 text-[11px]" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
        ${value} / ${max}
      </div>
    </div>
  );
}

/* ─── Ambient background ────────────────────────────────────────────────── */

function AmbientLayers() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      <motion.div
        className="absolute rounded-full"
        style={{
          width: 360, height: 360,
          left: "-10%", top: "10%",
          background: "radial-gradient(circle, var(--treasure) 0%, transparent 65%)",
          opacity: 0.18, filter: "blur(40px)",
        }}
        animate={{ x: [0, 30, 0], y: [0, -20, 0] }}
        transition={{ duration: 18, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute rounded-full"
        style={{
          width: 320, height: 320,
          right: "-10%", bottom: "5%",
          background: "radial-gradient(circle, var(--sky) 0%, transparent 65%)",
          opacity: 0.14, filter: "blur(50px)",
        }}
        animate={{ x: [0, -25, 0], y: [0, 25, 0] }}
        transition={{ duration: 22, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute rounded-full"
        style={{
          width: 220, height: 220,
          right: "30%", top: "-5%",
          background: "radial-gradient(circle, var(--emerald) 0%, transparent 65%)",
          opacity: 0.10, filter: "blur(40px)",
        }}
        animate={{ x: [0, 20, 0], y: [0, 15, 0] }}
        transition={{ duration: 26, repeat: Infinity, ease: "easeInOut" }}
      />
    </div>
  );
}

/* ─── Main component ────────────────────────────────────────────────────── */

export function Onboarding({ open, onClose, onComplete }: Props) {
  const [step, setStep] = useState(0);
  const [broker, setBroker] = useState<string>("");
  const [mode, setMode] = useState<"paper" | "live">("paper");
  const [activeLayers, setActiveLayers] = useState<number[]>([1, 2, 3, 5, 7]);
  const [riskLimit, setRiskLimit] = useState(500);

  const totalSteps = stepMeta.length;
  const meta = stepMeta[step];

  const canAdvance =
    step === 1 ? !!broker :
    step === 3 ? activeLayers.length > 0 :
    true;

  const next = () => {
    if (step < totalSteps - 1) {
      setStep(step + 1);
    } else {
      onComplete({ broker, mode, activeLayers, dailyRiskLimit: riskLimit });
    }
  };
  const back = () => step > 0 && setStep(step - 1);

  const toggleLayer = (id: number) =>
    setActiveLayers((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));

  const renderHero = () => {
    switch (step) {
      case 0: return <WovenBasketHero activeLayers={[1, 2, 3, 4, 5, 6, 7]} />;
      case 1: return <BrokerHero selected={broker} />;
      case 2: return <ModeHero mode={mode} />;
      case 3: return <LayersHero active={activeLayers} />;
      case 4: return <RiskGaugeHero value={riskLimit} max={5000} />;
      default: return null;
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.25 }}
        >
          {/* Backdrop */}
          <motion.div
            className="absolute inset-0"
            style={{ background: "rgba(0,0,0,0.65)", backdropFilter: "blur(10px)" }}
            onClick={onClose}
          />
          <AmbientLayers />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, y: 28, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.97 }}
            transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
            className="relative w-full max-w-xl rounded-2xl overflow-hidden"
            style={{
              background: "var(--card)",
              border: "1px solid var(--border)",
              boxShadow: "0 24px 80px rgba(0,0,0,0.5), 0 0 0 1px rgba(196,150,74,0.08)",
            }}
          >
            {/* Subtle obsidian sheen */}
            <div
              className="absolute inset-0 pointer-events-none"
              style={{
                background: "linear-gradient(135deg, rgba(196,150,74,0.04) 0%, transparent 30%, transparent 70%, rgba(196,150,74,0.02) 100%)",
              }}
            />

            {/* Top — progress + close */}
            <div className="relative px-6 pt-5 pb-4 border-b border-border" style={{ background: "var(--background)" }}>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <motion.div
                    className="w-7 h-7 rounded-md flex items-center justify-center"
                    style={{ background: "var(--treasure)" }}
                    animate={{ boxShadow: ["0 0 0 0 rgba(196,150,74,0.4)", "0 0 0 6px rgba(196,150,74,0)", "0 0 0 0 rgba(196,150,74,0)"] }}
                    transition={{ duration: 2.4, repeat: Infinity }}
                  >
                    <span className="text-[11px] font-bold text-black/80" style={{ fontFamily: "var(--font-serif)" }}>T</span>
                  </motion.div>
                  <span className="text-[10px] uppercase tracking-widest" style={{ color: "var(--treasure)", letterSpacing: "0.1em", fontWeight: 600 }}>
                    Setup · {step + 1} of {totalSteps}
                  </span>
                </div>
                <button
                  onClick={onClose}
                  className="p-1 rounded-md transition-colors hover:bg-muted"
                  style={{ color: "var(--muted-foreground)" }}
                  aria-label="Close"
                >
                  <X size={15} />
                </button>
              </div>

              {/* Progress bar */}
              <div className="flex gap-1.5">
                {stepMeta.map((_, i) => (
                  <div key={i} className="flex-1 h-1 rounded-full overflow-hidden" style={{ background: "var(--muted)" }}>
                    <motion.div
                      className="h-full rounded-full"
                      style={{ background: "var(--treasure)" }}
                      initial={false}
                      animate={{ width: i < step ? "100%" : i === step ? "55%" : "0%" }}
                      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                    />
                  </div>
                ))}
              </div>
            </div>

            {/* HERO graphic */}
            <div
              className="relative px-6 pt-6 pb-2"
              style={{
                background: "linear-gradient(180deg, var(--background) 0%, var(--card) 100%)",
              }}
            >
              <AnimatePresence mode="wait">
                <motion.div
                  key={`hero-${step}`}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                >
                  {renderHero()}
                </motion.div>
              </AnimatePresence>
            </div>

            {/* Body */}
            <div className="relative px-6 pt-2 pb-6" style={{ minHeight: "240px" }}>
              <div className="flex items-center gap-2 mb-1" style={{ color: "var(--treasure)" }}>
                {meta.icon}
                <span className="text-[10px] uppercase tracking-wider" style={{ letterSpacing: "0.1em", fontWeight: 600 }}>
                  Step {step + 1}
                </span>
              </div>
              <h2 style={{ fontFamily: "var(--font-serif)", fontSize: "22px", fontWeight: 500, color: "var(--foreground)" }}>
                {meta.title}
              </h2>
              <p className="text-[13px] mt-1" style={{ color: "var(--muted-foreground)" }}>
                {meta.sub}
              </p>

              <div className="mt-4">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={`body-${step}`}
                    initial={{ opacity: 0, x: 14 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -14 }}
                    transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
                  >
                    {step === 0 && <WelcomeStep />}

                    {step === 1 && (
                      <div className="grid grid-cols-2 gap-2">
                        {brokers.map((b, i) => (
                          <motion.button
                            key={b.id}
                            initial={{ opacity: 0, y: 8 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.05 }}
                            whileHover={{ y: -2 }}
                            onClick={() => setBroker(b.id)}
                            className="relative px-3 py-3 rounded-lg border text-left overflow-hidden"
                            style={{
                              background: broker === b.id ? "var(--accent)" : "var(--background)",
                              borderColor: broker === b.id ? "var(--treasure)" : "var(--border)",
                            }}
                          >
                            <div className="text-[12px]" style={{ color: "var(--foreground)", fontWeight: 500 }}>{b.name}</div>
                            <div className="text-[10px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>{b.desc}</div>
                            {broker === b.id && (
                              <motion.div
                                initial={{ scale: 0, rotate: -90 }}
                                animate={{ scale: 1, rotate: 0 }}
                                transition={{ type: "spring", stiffness: 400, damping: 18 }}
                                className="absolute top-2 right-2 w-4 h-4 rounded-full flex items-center justify-center"
                                style={{ background: "var(--treasure)" }}
                              >
                                <Check size={10} style={{ color: "var(--background)" }} />
                              </motion.div>
                            )}
                          </motion.button>
                        ))}
                      </div>
                    )}

                    {step === 2 && (
                      <div className="grid grid-cols-2 gap-3">
                        {[
                          { id: "paper", label: "Paper Mode", sub: "Simulated trades — start here", reco: true, color: "var(--emerald)" },
                          { id: "live", label: "Live Mode", sub: "Real orders, real capital", reco: false, color: "var(--rose)" },
                        ].map((opt) => (
                          <motion.button
                            key={opt.id}
                            whileHover={{ y: -2 }}
                            onClick={() => setMode(opt.id as "paper" | "live")}
                            className="px-4 py-3 rounded-lg border text-left"
                            style={{
                              background: mode === opt.id ? "var(--accent)" : "var(--background)",
                              borderColor: mode === opt.id ? opt.color : "var(--border)",
                            }}
                          >
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-[13px]" style={{ color: "var(--foreground)", fontWeight: 500 }}>{opt.label}</span>
                              {opt.reco && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "rgba(16,185,129,0.12)", color: "var(--emerald)", fontFamily: "var(--font-mono)" }}>
                                  RECO
                                </span>
                              )}
                            </div>
                            <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{opt.sub}</p>
                          </motion.button>
                        ))}
                      </div>
                    )}

                    {step === 3 && (
                      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                        {allLayers.map((l, i) => {
                          const isOn = activeLayers.includes(l.id);
                          return (
                            <motion.button
                              key={l.id}
                              initial={{ opacity: 0, y: 4 }}
                              animate={{ opacity: 1, y: 0 }}
                              transition={{ delay: i * 0.03 }}
                              whileHover={{ x: 2 }}
                              onClick={() => toggleLayer(l.id)}
                              className="flex items-center gap-2.5 px-2.5 py-2 rounded-md border text-left"
                              style={{
                                background: isOn ? "var(--accent)" : "var(--background)",
                                borderColor: isOn ? "var(--treasure)" : "var(--border)",
                              }}
                            >
                              <motion.span
                                className="w-5 h-5 rounded flex items-center justify-center text-[10px] shrink-0"
                                style={{
                                  background: isOn ? "var(--treasure)" : "var(--muted)",
                                  color: isOn ? "var(--background)" : "var(--muted-foreground)",
                                  fontFamily: "var(--font-mono)", fontWeight: 500,
                                }}
                                animate={{ scale: isOn ? [1, 1.18, 1] : 1 }}
                                transition={{ duration: 0.3 }}
                              >
                                {l.id}
                              </motion.span>
                              <div className="flex-1 min-w-0">
                                <div className="text-[12px]" style={{ color: "var(--foreground)", fontWeight: 500 }}>{l.name}</div>
                                <div className="text-[10px] truncate" style={{ color: "var(--muted-foreground)" }}>{l.desc}</div>
                              </div>
                            </motion.button>
                          );
                        })}
                      </div>
                    )}

                    {step === 4 && (
                      <div>
                        <div className="px-4 py-3 rounded-lg border border-border" style={{ background: "var(--background)" }}>
                          <div className="flex items-end justify-between mb-2">
                            <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
                              Max loss per day
                            </span>
                            <span style={{ fontFamily: "var(--font-mono)", fontSize: "20px", fontWeight: 500, color: "var(--treasure)" }}>
                              ${riskLimit}
                            </span>
                          </div>
                          <input
                            type="range"
                            min={100}
                            max={5000}
                            step={50}
                            value={riskLimit}
                            onChange={(e) => setRiskLimit(Number(e.target.value))}
                            className="w-full"
                            style={{ accentColor: "var(--treasure)" }}
                          />
                          <div className="flex justify-between mt-1">
                            <span className="text-[10px]" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>$100</span>
                            <span className="text-[10px]" style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>$5,000</span>
                          </div>
                        </div>
                        <p className="text-[11px] mt-2" style={{ color: "var(--muted-foreground)" }}>
                          Today's losses reach this cap → every layer pauses. Change any time in <span style={{ color: "var(--treasure)" }}>Bot Tuning</span>.
                        </p>
                      </div>
                    )}
                  </motion.div>
                </AnimatePresence>
              </div>
            </div>

            {/* Footer */}
            <div className="relative px-6 py-4 border-t border-border flex items-center justify-between" style={{ background: "var(--background)" }}>
              <button
                onClick={back}
                disabled={step === 0}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] transition-colors"
                style={{
                  color: step === 0 ? "var(--muted-foreground)" : "var(--foreground)",
                  opacity: step === 0 ? 0.35 : 1,
                  cursor: step === 0 ? "default" : "pointer",
                }}
              >
                <ArrowLeft size={13} /> Back
              </button>

              <motion.button
                onClick={next}
                disabled={!canAdvance}
                whileHover={canAdvance ? { scale: 1.04 } : undefined}
                whileTap={canAdvance ? { scale: 0.96 } : undefined}
                className="relative flex items-center gap-1.5 px-4 py-2 rounded-md text-[12px] overflow-hidden"
                style={{
                  background: canAdvance ? "var(--treasure)" : "var(--muted)",
                  color: canAdvance ? "var(--background)" : "var(--muted-foreground)",
                  fontWeight: 500,
                  cursor: canAdvance ? "pointer" : "not-allowed",
                }}
              >
                {canAdvance && (
                  <motion.div
                    className="absolute inset-0"
                    style={{
                      background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent)",
                    }}
                    animate={{ x: ["-100%", "200%"] }}
                    transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
                  />
                )}
                <span className="relative">{step === totalSteps - 1 ? "Finish setup" : "Continue"}</span>
                <ArrowRight size={13} className="relative" />
              </motion.button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function WelcomeStep() {
  const items = [
    { n: "1", text: "Connect a broker — Alpaca, IBKR, Tradier, or Coinbase" },
    { n: "2", text: "Choose paper or live mode (paper is safe to test)" },
    { n: "3", text: "Pick which wealth layers to run on day one" },
    { n: "4", text: "Set a daily risk cap so bots pause if you bleed" },
  ];
  return (
    <div>
      <div className="space-y-2">
        {items.map((s, i) => (
          <motion.div
            key={s.n}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.1 + i * 0.07 }}
            className="flex items-start gap-3"
          >
            <span
              className="w-5 h-5 rounded flex items-center justify-center text-[10px] shrink-0 mt-0.5"
              style={{ background: "var(--treasure)", color: "var(--background)", fontFamily: "var(--font-mono)", fontWeight: 500 }}
            >
              {s.n}
            </span>
            <span className="text-[12px]" style={{ color: "var(--foreground)" }}>{s.text}</span>
          </motion.div>
        ))}
      </div>
      <p className="text-[11px] mt-3" style={{ color: "var(--muted-foreground)" }}>
        Takes about a minute. Nothing goes live until you say so.
      </p>
    </div>
  );
}
