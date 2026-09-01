"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight, ArrowLeft, Check, X, Sparkles, Plug, ShieldCheck,
  Layers as LayersIcon, Gauge,
} from "lucide-react";
import { saveTourSettings } from "./actions";
import { BROKER_PROVIDERS } from "@/lib/broker-providers";

/* Trezo tokens — gold = --accent (gold in BOTH light + dark); card = --surface,
   text = --foreground, etc. all read the active theme so it's readable either way. */
const GOLD = "rgb(var(--accent))";
const GOLD_TINT = "rgb(var(--accent) / 0.12)";
const CARD = "rgb(var(--surface))";
const BG = "rgb(var(--background))";
const FG = "rgb(var(--foreground))";
const MUTED = "rgb(var(--muted))";
const MUTEDFG = "rgb(var(--muted-foreground))";
const BORDER = "rgb(var(--border))";
const EMERALD = "rgb(16 185 129)";
const ROSE = "rgb(244 63 94)";
const SERIF = "var(--font-serif)";
const MONO = "var(--font-mono)";

/* PAGES-04: derive the broker list from the provider registry instead of a
   hand-typed list — "tradier" had no provider entry, so picking it led
   nowhere. Only `status: "available"` cards are selectable; planned ones
   are shown greyed so the user knows what is coming. Banking (Plaid) and
   the live Alpaca venue are not brokers to route paper orders through. */
const brokers = BROKER_PROVIDERS
  .filter((p) => p.category !== "banking" && p.venue !== "live")
  .map((p) => ({
    id: p.key,
    name: p.label,
    available: p.status === "available",
    desc: p.status === "available"
      ? (p.category === "crypto" ? "Crypto · OAuth connect" : "Stocks & options · OAuth connect")
      : "Coming soon — no public OAuth flow yet",
  }));

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
  { title: "Connect a broker", sub: "Pick one — the connect itself happens on Settings → Connections", icon: <Plug size={14} /> },
  { title: "Trading mode", sub: "Paper only — live execution is not built yet", icon: <ShieldCheck size={14} /> },
  { title: "The seven layers", sub: "A tour — layers are switched on in Bot Tuning, not here", icon: <LayersIcon size={14} /> },
  { title: "Daily risk limit", sub: "Your safety cap — the one setting this wizard saves", icon: <Gauge size={14} /> },
];

function WovenBasketHero({ activeLayers }: { activeLayers: number[] }) {
  const rings = [1, 2, 3, 4, 5, 6, 7];
  return (
    <div className="relative flex h-44 items-center justify-center overflow-hidden">
      {rings.map((n) => {
        const size = 170 - (n - 1) * 22;
        const isActive = activeLayers.includes(n);
        return (
          <div
            key={n}
            className="absolute rounded-full"
            style={{
              width: size, height: size,
              border: `1px solid ${isActive ? GOLD : BORDER}`,
              opacity: isActive ? 0.9 - n * 0.06 : 0.25,
            }}
          />
        );
      })}
      <div
        className="absolute rounded-full animate-pulse"
        style={{ width: 36, height: 36, background: `radial-gradient(circle, ${GOLD} 0%, transparent 70%)` }}
      />
      <div className="absolute animate-spin" style={{ width: 170, height: 170, animationDuration: "18s" }}>
        <div className="absolute left-1/2 top-0 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ background: GOLD, boxShadow: `0 0 12px ${GOLD}` }} />
      </div>
    </div>
  );
}

function BrokerHero({ selected }: { selected: string }) {
  return (
    <div className="relative flex h-32 items-center justify-center overflow-hidden">
      <div
        className="absolute left-[18%] flex h-12 w-12 items-center justify-center rounded-xl"
        style={{ background: GOLD, color: BG, fontFamily: SERIF, fontSize: "18px", fontWeight: 500 }}
      >
        T
      </div>
      <div className="absolute right-[18%] flex h-12 w-12 items-center justify-center rounded-xl border" style={{ background: CARD, borderColor: BORDER }}>
        <Plug size={18} style={{ color: selected ? EMERALD : MUTEDFG }} />
      </div>
      <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
        <line x1="22%" y1="50%" x2="78%" y2="50%" stroke={selected ? GOLD : BORDER} strokeWidth={1.5} strokeDasharray="4 4" />
      </svg>
      {selected ? (
        <div
          className="absolute top-1/2 h-2 w-2 -translate-y-1/2 rounded-full"
          style={{ background: GOLD, boxShadow: `0 0 10px ${GOLD}`, left: "20%", animation: "trezo-travel 1.6s ease-in-out infinite alternate" }}
        />
      ) : null}
    </div>
  );
}

function ModeHero({ mode }: { mode: "paper" | "live" }) {
  const slide = (active: boolean) => ({
    transform: `translateX(${active ? -50 : 50}px) rotate(${active ? -6 : 6}deg)`,
    transition: "transform 0.45s cubic-bezier(0.22,1,0.36,1)",
  });
  return (
    <div className="relative flex h-32 items-center justify-center overflow-hidden">
      <div className="absolute" style={slide(mode === "paper")}>
        <div
          className="rounded-lg border px-5 py-4"
          style={{
            background: mode === "paper" ? CARD : BG,
            borderColor: mode === "paper" ? EMERALD : BORDER,
            boxShadow: mode === "paper" ? "0 8px 32px rgba(16,185,129,0.18)" : "0 4px 12px rgba(0,0,0,0.2)",
          }}
        >
          <div className="mb-1 text-[10px]" style={{ color: EMERALD, fontFamily: MONO }}>PAPER</div>
          <div style={{ fontFamily: MONO, fontSize: "16px", color: FG }}>$0 risk</div>
        </div>
      </div>
      <div className="absolute" style={slide(mode === "live")}>
        <div
          className="rounded-lg border px-5 py-4"
          style={{
            background: mode === "live" ? CARD : BG,
            borderColor: mode === "live" ? ROSE : BORDER,
            boxShadow: mode === "live" ? "0 8px 32px rgba(244,63,94,0.18)" : "0 4px 12px rgba(0,0,0,0.2)",
          }}
        >
          <div className="mb-1 text-[10px]" style={{ color: ROSE, fontFamily: MONO }}>LIVE</div>
          <div style={{ fontFamily: MONO, fontSize: "16px", color: MUTEDFG }}>Not built</div>
        </div>
      </div>
    </div>
  );
}

function LayersHero({ active }: { active: number[] }) {
  return (
    <div className="relative flex h-32 items-end justify-center gap-1.5 overflow-hidden pb-2">
      {[1, 2, 3, 4, 5, 6, 7].map((n) => {
        const isOn = active.includes(n);
        const height = 30 + n * 8;
        return (
          <div
            key={n}
            className="flex items-end justify-center rounded-md pb-1.5"
            style={{
              width: 26,
              height: isOn ? height : height * 0.5,
              background: isOn ? GOLD : MUTED,
              opacity: isOn ? 0.85 : 0.4,
              transition: "height 0.4s cubic-bezier(0.22,1,0.36,1), opacity 0.3s",
            }}
          >
            <span className="text-[9px]" style={{ fontFamily: MONO, color: isOn ? BG : MUTEDFG, fontWeight: 500 }}>{n}</span>
          </div>
        );
      })}
    </div>
  );
}

function RiskGaugeHero({ value, max }: { value: number; max: number }) {
  const pct = Math.min(1, Math.max(0, value / max));
  const start = -120;
  const end = 120;
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
  const angle = start + (end - start) * pct;
  return (
    <div className="relative flex h-32 items-center justify-center overflow-hidden">
      <svg width="180" height="120" viewBox="0 0 180 120">
        <path d={arcPath(start, end)} stroke={BORDER} strokeWidth={6} fill="none" strokeLinecap="round" />
        <path
          d={arcPath(start, end)}
          stroke={GOLD}
          strokeWidth={6}
          fill="none"
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray={`${pct} 1`}
          style={{ transition: "stroke-dasharray 0.4s cubic-bezier(0.22,1,0.36,1)" }}
        />
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => {
          const a = start + (end - start) * p;
          const ox = cx + (R + 8) * Math.cos((a - 90) * Math.PI / 180);
          const oy = cy + (R + 8) * Math.sin((a - 90) * Math.PI / 180);
          return <circle key={i} cx={ox} cy={oy} r={1.2} fill={MUTEDFG} opacity={0.5} />;
        })}
        <g style={{ transform: `rotate(${angle}deg)`, transformOrigin: "90px 90px", transition: "transform 0.4s cubic-bezier(0.22,1,0.36,1)" }}>
          <line x1={cx} y1={cy} x2={cx} y2={cy - R} stroke={GOLD} strokeWidth={2} strokeLinecap="round" />
        </g>
        <circle cx={cx} cy={cy} r={5} fill={GOLD} />
        <circle cx={cx} cy={cy} r={2.5} fill={BG} />
      </svg>
      <div className="absolute bottom-1 left-1/2 -translate-x-1/2 text-[11px]" style={{ color: MUTEDFG, fontFamily: MONO }}>
        ${value} / ${max}
      </div>
    </div>
  );
}

function AmbientLayers() {
  const blobs = [
    { w: 360, h: 360, left: "-10%", top: "10%", color: GOLD, opacity: 0.18, blur: 40, dur: "18s" },
    { w: 320, h: 320, right: "-10%", bottom: "5%", color: "rgb(56 189 248)", opacity: 0.14, blur: 50, dur: "22s" },
    { w: 220, h: 220, right: "30%", top: "-5%", color: EMERALD, opacity: 0.1, blur: 40, dur: "26s" },
  ];
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {blobs.map((b, i) => (
        <div
          key={i}
          className="absolute rounded-full"
          style={{
            width: b.w, height: b.h, left: b.left, right: b.right, top: b.top, bottom: b.bottom,
            background: `radial-gradient(circle, ${b.color} 0%, transparent 65%)`,
            opacity: b.opacity, filter: `blur(${b.blur}px)`,
            animation: `trezo-drift ${b.dur} ease-in-out infinite`,
            animationDelay: `${i * 2}s`,
          }}
        />
      ))}
    </div>
  );
}

function WelcomeStep() {
  const items = [
    { n: "1", text: "Pick a broker — Alpaca paper today; more as their OAuth opens up" },
    { n: "2", text: "Paper mode — every trade is simulated; live is not built yet" },
    { n: "3", text: "Meet the seven wealth layers (switch them on in Bot Tuning)" },
    { n: "4", text: "Set a daily loss cap so the agents pause if you bleed" },
  ];
  return (
    <div>
      <div className="space-y-2">
        {items.map((s, i) => (
          <div key={s.n} className="flex items-start gap-3" style={{ animation: "trezo-fade-in 0.4s both", animationDelay: `${0.1 + i * 0.07}s` }}>
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px]" style={{ background: GOLD, color: BG, fontFamily: MONO, fontWeight: 500 }}>{s.n}</span>
            <span className="text-[12px]" style={{ color: FG }}>{s.text}</span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px]" style={{ color: MUTEDFG }}>Takes about a minute. Nothing here places a trade.</p>
    </div>
  );
}

export function OnboardingWizard() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  // PAGES-04: only the loss cap is persisted (see actions.ts). The broker
  // pick just decides where to land afterwards; mode and layers are
  // informational and carry no state.
  const [broker, setBroker] = useState<string>("");
  const [riskLimit, setRiskLimit] = useState(500);
  const [saving, setSaving] = useState(false);

  const totalSteps = stepMeta.length;
  const meta = stepMeta[step];
  const canAdvance = step === 1 ? !!broker : true;

  const finish = async () => {
    setSaving(true);
    try {
      await saveTourSettings({ dailyRiskLimit: riskLimit });
    } catch {
      /* best-effort */
    }
    router.push(broker ? "/dashboard/settings/connections" : "/dashboard");
  };
  const next = () => {
    if (step < totalSteps - 1) setStep(step + 1);
    else void finish();
  };
  const back = () => step > 0 && setStep(step - 1);
  const close = () => router.push("/dashboard");

  const renderHero = () => {
    switch (step) {
      case 0: return <WovenBasketHero activeLayers={[1, 2, 3, 4, 5, 6, 7]} />;
      case 1: return <BrokerHero selected={broker} />;
      case 2: return <ModeHero mode="paper" />;
      case 3: return <LayersHero active={[1, 2, 3, 4, 5, 6, 7]} />;
      case 4: return <RiskGaugeHero value={riskLimit} max={5000} />;
      default: return null;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: BG }}>
      <AmbientLayers />

      <div
        className="relative w-full max-w-xl overflow-hidden rounded-2xl"
        style={{ background: CARD, border: `1px solid ${BORDER}`, boxShadow: "0 24px 80px rgba(0,0,0,0.5), 0 0 0 1px rgba(196,150,74,0.08)", animation: "trezo-fade-in 0.45s cubic-bezier(0.22,1,0.36,1) both" }}
      >
        <div className="pointer-events-none absolute inset-0" style={{ background: "linear-gradient(135deg, rgba(196,150,74,0.04) 0%, transparent 30%, transparent 70%, rgba(196,150,74,0.02) 100%)" }} />

        {/* Top — progress + close */}
        <div className="relative border-b px-6 pb-4 pt-5" style={{ borderColor: BORDER, background: BG }}>
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 animate-pulse items-center justify-center rounded-md" style={{ background: GOLD }}>
                <span className="text-[11px] font-bold" style={{ color: BG, fontFamily: SERIF }}>T</span>
              </div>
              <span className="text-[10px] uppercase" style={{ color: GOLD, letterSpacing: "0.1em", fontWeight: 600 }}>
                Setup · {step + 1} of {totalSteps}
              </span>
            </div>
            <button onClick={close} className="rounded-md p-1 transition-colors hover:opacity-70" style={{ color: MUTEDFG }} aria-label="Skip setup">
              <X size={15} />
            </button>
          </div>
          <div className="flex gap-1.5">
            {stepMeta.map((_, i) => (
              <div key={i} className="h-1 flex-1 overflow-hidden rounded-full" style={{ background: MUTED }}>
                <div className="h-full rounded-full" style={{ background: GOLD, width: i < step ? "100%" : i === step ? "55%" : "0%", transition: "width 0.5s cubic-bezier(0.22,1,0.36,1)" }} />
              </div>
            ))}
          </div>
        </div>

        {/* Hero */}
        <div className="relative px-6 pb-2 pt-6" style={{ background: `linear-gradient(180deg, ${BG} 0%, ${CARD} 100%)` }}>
          <div key={`hero-${step}`} style={{ animation: "trezo-fade-in 0.35s cubic-bezier(0.22,1,0.36,1) both" }}>
            {renderHero()}
          </div>
        </div>

        {/* Body */}
        <div className="relative px-6 pb-6 pt-2" style={{ minHeight: "240px" }}>
          <div className="mb-1 flex items-center gap-2" style={{ color: GOLD }}>
            {meta.icon}
            <span className="text-[10px] uppercase" style={{ letterSpacing: "0.1em", fontWeight: 600 }}>Step {step + 1}</span>
          </div>
          <h2 style={{ fontFamily: SERIF, fontSize: "22px", fontWeight: 500, color: FG }}>{meta.title}</h2>
          <p className="mt-1 text-[13px]" style={{ color: MUTEDFG }}>{meta.sub}</p>

          <div className="mt-4" key={`body-${step}`} style={{ animation: "trezo-fade-in 0.3s cubic-bezier(0.22,1,0.36,1) both" }}>
            {step === 0 && <WelcomeStep />}

            {step === 1 && (
              <div className="grid grid-cols-2 gap-2">
                {brokers.map((b) => (
                  <button
                    key={b.id}
                    onClick={() => b.available && setBroker(b.id)}
                    disabled={!b.available}
                    aria-disabled={!b.available}
                    className="relative overflow-hidden rounded-lg border px-3 py-3 text-left transition-transform enabled:hover:-translate-y-0.5"
                    style={{
                      background: broker === b.id ? GOLD_TINT : BG,
                      borderColor: broker === b.id ? GOLD : BORDER,
                      opacity: b.available ? 1 : 0.45,
                      cursor: b.available ? "pointer" : "not-allowed",
                    }}
                  >
                    <div className="text-[12px]" style={{ color: FG, fontWeight: 500 }}>{b.name}</div>
                    <div className="mt-0.5 text-[10px]" style={{ color: MUTEDFG }}>{b.desc}</div>
                    {broker === b.id ? (
                      <div className="absolute right-2 top-2 flex h-4 w-4 items-center justify-center rounded-full" style={{ background: GOLD }}>
                        <Check size={10} style={{ color: BG }} />
                      </div>
                    ) : null}
                  </button>
                ))}
              </div>
            )}

            {step === 2 && (
              /* PAGES-04: informational — there is no live executor to
                 choose. TRADING_MODE is env-gated and inert. */
              <div>
                <div className="rounded-lg border px-4 py-3" style={{ background: GOLD_TINT, borderColor: EMERALD }}>
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-[13px]" style={{ color: FG, fontWeight: 500 }}>Paper Mode</span>
                    <span className="rounded px-1.5 py-0.5 text-[10px]" style={{ background: "rgba(16,185,129,0.12)", color: EMERALD, fontFamily: MONO }}>ACTIVE</span>
                  </div>
                  <p className="text-[11px]" style={{ color: MUTEDFG }}>
                    Every trade is simulated against a paper account. No real money moves.
                  </p>
                </div>
                <p className="mt-2 text-[11px]" style={{ color: MUTEDFG }}>
                  Live trading is not something you switch on here: the real-money
                  executor does not exist yet and is gated behind the go-live
                  checklist. Nothing in this wizard changes that.
                </p>
              </div>
            )}

            {step === 3 && (
              /* PAGES-04: a tour, not a control. The wizard used to offer
                 per-layer toggles that were never persisted; the real
                 on/off switches are the strategy flags in Bot Tuning. */
              <div>
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                  {allLayers.map((l) => (
                    <div
                      key={l.id}
                      className="flex items-center gap-2.5 rounded-md border px-2.5 py-2 text-left"
                      style={{ background: BG, borderColor: BORDER }}
                    >
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px]" style={{ background: GOLD, color: BG, fontFamily: MONO, fontWeight: 500 }}>{l.id}</span>
                      <div className="min-w-0 flex-1">
                        <div className="text-[12px]" style={{ color: FG, fontWeight: 500 }}>{l.name}</div>
                        <div className="truncate text-[10px]" style={{ color: MUTEDFG }}>{l.desc}</div>
                      </div>
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-[11px]" style={{ color: MUTEDFG }}>
                  Layers are enabled and paused in <span style={{ color: GOLD }}>Settings → Bot Tuning</span>, per book. This step just shows you the map.
                </p>
              </div>
            )}

            {step === 4 && (
              <div>
                <div className="rounded-lg border px-4 py-3" style={{ background: BG, borderColor: BORDER }}>
                  <div className="mb-2 flex items-end justify-between">
                    <span className="text-[10px] uppercase" style={{ color: MUTEDFG, letterSpacing: "0.08em" }}>Max loss per day</span>
                    <span style={{ fontFamily: MONO, fontSize: "20px", fontWeight: 500, color: GOLD }}>${riskLimit}</span>
                  </div>
                  <input type="range" min={100} max={5000} step={50} value={riskLimit} onChange={(e) => setRiskLimit(Number(e.target.value))} className="w-full" style={{ accentColor: "rgb(var(--accent))" }} />
                  <div className="mt-1 flex justify-between">
                    <span className="text-[10px]" style={{ color: MUTEDFG, fontFamily: MONO }}>$100</span>
                    <span className="text-[10px]" style={{ color: MUTEDFG, fontFamily: MONO }}>$5,000</span>
                  </div>
                </div>
                <p className="mt-2 text-[11px]" style={{ color: MUTEDFG }}>
                  Today&apos;s losses reach this cap → the Risk Manager stops new entries. Saved to your profile; change any time in <span style={{ color: GOLD }}>Settings → Profile</span>.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="relative flex items-center justify-between border-t px-6 py-4" style={{ borderColor: BORDER, background: BG }}>
          <button
            onClick={back}
            disabled={step === 0}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] transition-colors"
            style={{ color: step === 0 ? MUTEDFG : FG, opacity: step === 0 ? 0.35 : 1, cursor: step === 0 ? "default" : "pointer" }}
          >
            <ArrowLeft size={13} /> Back
          </button>
          <button
            onClick={next}
            disabled={!canAdvance || saving}
            className="relative flex items-center gap-1.5 overflow-hidden rounded-md px-4 py-2 text-[12px] transition-transform hover:scale-[1.03] active:scale-95"
            style={{ background: canAdvance ? GOLD : MUTED, color: canAdvance ? BG : MUTEDFG, fontWeight: 500, cursor: canAdvance && !saving ? "pointer" : "not-allowed" }}
          >
            {canAdvance ? (
              <div className="absolute inset-0" style={{ background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent)", animation: "trezo-shimmer 2s linear infinite" }} />
            ) : null}
            <span className="relative">{saving ? "Saving…" : step === totalSteps - 1 ? "Finish setup" : "Continue"}</span>
            <ArrowRight size={13} className="relative" />
          </button>
        </div>
      </div>
    </div>
  );
}
