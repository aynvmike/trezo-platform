import { motion } from "motion/react";
import { ArrowRight, ShieldCheck, Zap, Activity, Layers as LayersIcon } from "lucide-react";
import { AtomHero } from "./AtomHero";
import { AmbientBackground } from "./AmbientBackground";

const layers = [
  { id: 1, name: "Crypto", desc: "BTC, ETH, alt momentum — the outer ring takes volatility first", risk: "Very High" },
  { id: 2, name: "Stock", desc: "Equity breakouts and pullbacks on daily trend", risk: "High" },
  { id: 3, name: "Options", desc: "Directional debit spreads when IV rank is low", risk: "High" },
  { id: 4, name: "Stock Weekly", desc: "Weekly chart patterns only — slower cadence", risk: "Medium" },
  { id: 5, name: "Wheel", desc: "Cash-secured puts cycling into covered calls", risk: "Medium" },
  { id: 6, name: "Dividends", desc: "High-yield capture around ex-dividend windows", risk: "Low" },
  { id: 7, name: "KINDRIP", desc: "The treasure core — responsible long-only ETFs", risk: "Very Low" },
];

const principles = [
  {
    icon: <ShieldCheck size={18} />,
    title: "Calm over dense",
    body: "Plain-English sits beside every number. No flashing red, no nagging banners — just signals you can read at a glance.",
  },
  {
    icon: <Zap size={18} />,
    title: "Seven bots, one strategy",
    body: "Each layer is an autonomous agent with its own rules. Outer rings take volatility; the inner vault is the treasure they protect.",
  },
  {
    icon: <Activity size={18} />,
    title: "Paper first, always",
    body: "Test every strategy with simulated capital before a dollar goes live. Daily risk caps pause the bots if you bleed.",
  },
];

type Props = {
  onEnter: () => void;
};

export function LandingPage({ onEnter }: Props) {
  return (
    <div className="dark relative min-h-screen overflow-x-hidden" style={{ background: "var(--background)", color: "var(--foreground)" }}>
      <AmbientBackground />

      {/* Nav */}
      <motion.nav
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="relative z-10 flex items-center justify-between px-8 py-5 border-b border-border"
        style={{ background: "rgba(11,11,17,0.6)", backdropFilter: "blur(12px)" }}
      >
        <div className="flex items-center gap-2.5">
          <motion.div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: "var(--treasure)" }}
            animate={{ boxShadow: ["0 0 0 0 rgba(196,150,74,0.4)", "0 0 0 8px rgba(196,150,74,0)", "0 0 0 0 rgba(196,150,74,0)"] }}
            transition={{ duration: 2.4, repeat: Infinity }}
          >
            <span className="text-[13px] font-bold text-black/80" style={{ fontFamily: "var(--font-serif)" }}>T</span>
          </motion.div>
          <div>
            <div className="leading-none" style={{ fontFamily: "var(--font-serif)", fontWeight: 500, fontSize: "17px" }}>Trezo</div>
            <div className="text-[9px] mt-0.5" style={{ color: "var(--muted-foreground)", letterSpacing: "0.12em" }}>WOVEN BASKET</div>
          </div>
        </div>

        <div className="hidden md:flex items-center gap-7 text-[13px]" style={{ color: "var(--muted-foreground)" }}>
          <a href="#layers" className="hover:text-foreground transition-colors">The Layers</a>
          <a href="#how" className="hover:text-foreground transition-colors">How it works</a>
          <a href="#contact" className="hover:text-foreground transition-colors">Contact</a>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={onEnter}
            className="text-[13px] px-3 py-1.5 rounded-md transition-colors"
            style={{ color: "var(--muted-foreground)" }}
          >
            Sign in
          </button>
          <motion.button
            onClick={onEnter}
            whileHover={{ scale: 1.04 }}
            whileTap={{ scale: 0.97 }}
            className="relative flex items-center gap-1.5 text-[13px] px-4 py-2 rounded-md overflow-hidden"
            style={{ background: "var(--treasure)", color: "var(--background)", fontWeight: 500 }}
          >
            <motion.div
              className="absolute inset-0"
              style={{ background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent)" }}
              animate={{ x: ["-100%", "200%"] }}
              transition={{ duration: 2.6, repeat: Infinity, ease: "linear" }}
            />
            <span className="relative">Begin weaving</span>
            <ArrowRight size={13} className="relative" />
          </motion.button>
        </div>
      </motion.nav>

      {/* Hero */}
      <section className="relative z-10 px-8 py-16 md:py-24">
        <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
          {/* Copy */}
          <div>
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="inline-flex items-center gap-2 px-3 py-1 rounded-full mb-6 border"
              style={{ borderColor: "rgba(196,150,74,0.3)", background: "rgba(196,150,74,0.06)" }}
            >
              <div className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--treasure)" }} />
              <span className="text-[11px] uppercase tracking-widest" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
                Multi-strategy · Automated
              </span>
            </motion.div>

            <motion.h1
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2, duration: 0.6 }}
              style={{
                fontFamily: "var(--font-serif)",
                fontSize: "clamp(40px, 5.5vw, 64px)",
                fontWeight: 500,
                lineHeight: 1.05,
                letterSpacing: "-0.01em",
              }}
            >
              Seven layers <br />
              <span style={{ color: "var(--treasure)" }}>woven into one</span> <br />
              quiet engine.
            </motion.h1>

            <motion.p
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.35, duration: 0.6 }}
              className="mt-6 text-[16px] leading-relaxed max-w-xl"
              style={{ color: "var(--muted-foreground)" }}
            >
              Trezo is a multi-strategy automated trading platform — a woven basket of seven wealth layers,
              from the most volatile outer ring to the most protected inner vault. Each layer is its own bot.
              All seven run together, so volatility lands somewhere it belongs.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.5 }}
              className="mt-8 flex flex-wrap items-center gap-3"
            >
              <motion.button
                onClick={onEnter}
                whileHover={{ scale: 1.04 }}
                whileTap={{ scale: 0.97 }}
                className="relative flex items-center gap-2 px-5 py-3 rounded-md overflow-hidden"
                style={{ background: "var(--treasure)", color: "var(--background)", fontWeight: 500 }}
              >
                <motion.div
                  className="absolute inset-0"
                  style={{ background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.35), transparent)" }}
                  animate={{ x: ["-100%", "200%"] }}
                  transition={{ duration: 2.6, repeat: Infinity, ease: "linear" }}
                />
                <span className="relative text-[14px]">Begin weaving</span>
                <ArrowRight size={15} className="relative" />
              </motion.button>
              <button
                onClick={onEnter}
                className="px-5 py-3 rounded-md text-[14px] border border-border transition-colors hover:bg-card"
                style={{ color: "var(--foreground)" }}
              >
                I have an account
              </button>
            </motion.div>

            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.7 }}
              className="mt-8 flex items-center gap-5"
            >
              {[
                { label: "Layers", value: "7" },
                { label: "Agents", value: "21" },
                { label: "Brokers", value: "4+" },
              ].map((stat) => (
                <div key={stat.label} className="flex items-baseline gap-1.5">
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "18px", fontWeight: 500, color: "var(--treasure)" }}>
                    {stat.value}
                  </span>
                  <span className="text-[11px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.1em" }}>
                    {stat.label}
                  </span>
                </div>
              ))}
            </motion.div>
          </div>

          {/* Atom */}
          <motion.div
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.3, duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
            className="flex items-center justify-center"
          >
            <AtomHero size={480} />
          </motion.div>
        </div>
      </section>

      {/* 7-Layer explainer */}
      <section id="layers" className="relative z-10 px-8 py-20 border-t border-border" style={{ background: "rgba(18,18,27,0.4)" }}>
        <div className="max-w-7xl mx-auto">
          <div className="max-w-2xl mb-12">
            <div className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
              The Woven Basket
            </div>
            <h2 style={{ fontFamily: "var(--font-serif)", fontSize: "38px", fontWeight: 500, lineHeight: 1.1 }}>
              Outer rings absorb the noise. <br />
              <span style={{ color: "var(--treasure)" }}>The inner vault stays calm.</span>
            </h2>
            <p className="mt-4 text-[14px]" style={{ color: "var(--muted-foreground)" }}>
              Each layer is an autonomous bot with its own strategy, cadence, and risk profile. They share capital but never fight for it.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-7 gap-3">
            {layers.map((layer, i) => (
              <motion.div
                key={layer.id}
                initial={{ opacity: 0, y: 18 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-50px" }}
                transition={{ delay: i * 0.06, duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
                whileHover={{ y: -4 }}
                className="relative rounded-xl border border-border obsidian-panel p-4 flex flex-col gap-3"
                style={{ background: "var(--card)", minHeight: 180 }}
              >
                <div className="flex items-center justify-between">
                  <div
                    className="w-7 h-7 rounded-md flex items-center justify-center text-[12px]"
                    style={{
                      background: i === 6 ? "var(--treasure)" : "var(--muted)",
                      color: i === 6 ? "var(--background)" : "var(--treasure)",
                      fontFamily: "var(--font-mono)",
                      fontWeight: 500,
                    }}
                  >
                    {layer.id}
                  </div>
                  <span className="text-[9px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
                    {layer.risk}
                  </span>
                </div>
                <div>
                  <div className="text-[13px]" style={{ fontWeight: 500 }}>{layer.name}</div>
                  <p className="text-[11px] mt-1 leading-relaxed" style={{ color: "var(--muted-foreground)" }}>
                    {layer.desc}
                  </p>
                </div>
                {i === 6 && (
                  <div className="text-[9px] uppercase tracking-widest mt-auto" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
                    Treasure core
                  </div>
                )}
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Principles */}
      <section id="how" className="relative z-10 px-8 py-20 border-t border-border">
        <div className="max-w-7xl mx-auto">
          <div className="max-w-2xl mb-12">
            <div className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
              How Trezo thinks
            </div>
            <h2 style={{ fontFamily: "var(--font-serif)", fontSize: "38px", fontWeight: 500, lineHeight: 1.1 }}>
              Built for the operator <br />
              <span style={{ color: "var(--treasure)" }}>who doesn't write code.</span>
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {principles.map((p, i) => (
              <motion.div
                key={p.title}
                initial={{ opacity: 0, y: 18 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-50px" }}
                transition={{ delay: i * 0.1, duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
                className="rounded-xl border border-border obsidian-panel p-6"
                style={{ background: "var(--card)" }}
              >
                <div
                  className="w-10 h-10 rounded-lg flex items-center justify-center mb-4"
                  style={{ background: "rgba(196,150,74,0.1)", color: "var(--treasure)" }}
                >
                  {p.icon}
                </div>
                <h3 className="text-[15px] mb-2" style={{ fontWeight: 500 }}>{p.title}</h3>
                <p className="text-[13px] leading-relaxed" style={{ color: "var(--muted-foreground)" }}>{p.body}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="relative z-10 px-8 py-24 border-t border-border">
        <div className="max-w-3xl mx-auto text-center">
          <h2 style={{ fontFamily: "var(--font-serif)", fontSize: "44px", fontWeight: 500, lineHeight: 1.1 }}>
            Start weaving today.
          </h2>
          <p className="mt-4 text-[14px]" style={{ color: "var(--muted-foreground)" }}>
            Paper mode is on by default. Nothing goes live until you say so.
          </p>
          <motion.button
            onClick={onEnter}
            whileHover={{ scale: 1.04 }}
            whileTap={{ scale: 0.97 }}
            className="relative inline-flex items-center gap-2 px-6 py-3 mt-8 rounded-md overflow-hidden"
            style={{ background: "var(--treasure)", color: "var(--background)", fontWeight: 500 }}
          >
            <motion.div
              className="absolute inset-0"
              style={{ background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.35), transparent)" }}
              animate={{ x: ["-100%", "200%"] }}
              transition={{ duration: 2.6, repeat: Infinity, ease: "linear" }}
            />
            <span className="relative text-[14px]">Open the dashboard</span>
            <ArrowRight size={15} className="relative" />
          </motion.button>
        </div>
      </section>

      {/* Footer */}
      <footer id="contact" className="relative z-10 px-8 py-10 border-t border-border" style={{ background: "rgba(18,18,27,0.4)" }}>
        <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: "var(--treasure)" }}>
              <span className="text-[10px] font-bold text-black/80" style={{ fontFamily: "var(--font-serif)" }}>T</span>
            </div>
            <span className="text-[12px]" style={{ color: "var(--muted-foreground)" }}>
              Trezo · Woven Basket · © 2026
            </span>
          </div>
          <div className="flex items-center gap-6 text-[12px]" style={{ color: "var(--muted-foreground)" }}>
            <a href="#" className="hover:text-foreground transition-colors">Privacy</a>
            <a href="#" className="hover:text-foreground transition-colors">Terms</a>
            <a href="#" className="hover:text-foreground transition-colors">Contact</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
