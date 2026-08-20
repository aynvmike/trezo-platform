import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Shield, AlertTriangle, Check, X, Radio } from "lucide-react";
import { PageHeader } from "./PageHeader";

const checklist = [
  { id: "mode", label: "Live mode toggle armed", desc: "You're about to flip from PAPER to LIVE", done: false, required: true },
  { id: "auto", label: "Auto-trade is ON", desc: "Bots will execute signals automatically", done: true, required: true },
  { id: "broker", label: "Broker connected", desc: "Alpaca · healthy · refreshed 2 min ago", done: true, required: true },
  { id: "options", label: "Options approval Level 3+", desc: "Required for spreads and Wheel layer", done: true, required: false },
  { id: "buying-power", label: "Sufficient buying power", desc: "≥ $5,000 across connected accounts", done: true, required: true },
];

export function LiveTradingView() {
  const [isLive, setIsLive] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const requiredDone = checklist.filter((c) => c.required && c.id !== "mode").every((c) => c.done);

  const beginGoLive = () => setConfirming(true);
  const cancelGoLive = () => setConfirming(false);
  const confirmGoLive = () => {
    setIsLive(true);
    setConfirming(false);
  };
  const goBackToPaper = () => setIsLive(false);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
      <PageHeader
        eyebrow="Settings — Live Trading"
        title="Live trading"
        subtitle="The paper-to-live switch. Live mode routes real orders through your brokerage. Take your time here."
      />

      {/* Mode banner — the unmissable state */}
      <motion.div
        layout
        transition={{ type: "spring", stiffness: 200, damping: 22 }}
        className="relative rounded-2xl border-2 overflow-hidden p-6"
        style={{
          background: isLive
            ? "linear-gradient(135deg, rgba(244,63,94,0.12) 0%, var(--card) 60%)"
            : "linear-gradient(135deg, rgba(16,185,129,0.10) 0%, var(--card) 60%)",
          borderColor: isLive ? "var(--rose)" : "var(--emerald)",
        }}
      >
        {/* Pulsing dot in corner when live */}
        {isLive && (
          <motion.div
            className="absolute top-4 right-4 w-3 h-3 rounded-full"
            style={{ background: "var(--rose)", boxShadow: "0 0 16px var(--rose)" }}
            animate={{ scale: [1, 1.3, 1], opacity: [1, 0.5, 1] }}
            transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
          />
        )}

        <div className="flex items-start justify-between gap-6">
          <div className="flex items-start gap-4">
            <div
              className="w-14 h-14 rounded-xl flex items-center justify-center shrink-0"
              style={{
                background: isLive ? "var(--rose)" : "var(--emerald)",
                color: "var(--background)",
                boxShadow: `0 8px 24px ${isLive ? "rgba(244,63,94,0.3)" : "rgba(16,185,129,0.3)"}`,
              }}
            >
              {isLive ? <Radio size={22} /> : <Shield size={22} />}
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-widest mb-1" style={{ color: isLive ? "var(--rose)" : "var(--emerald)", letterSpacing: "0.12em", fontWeight: 600 }}>
                Current mode
              </div>
              <div style={{ fontFamily: "var(--font-serif)", fontSize: "30px", fontWeight: 500, lineHeight: 1, color: isLive ? "var(--rose)" : "var(--emerald)" }}>
                {isLive ? "LIVE" : "PAPER"}
              </div>
              <p className="text-[13px] mt-2 max-w-md" style={{ color: "var(--muted-foreground)" }}>
                {isLive
                  ? "Real orders route to your broker. Every fill moves real capital."
                  : "Simulated orders only. Nothing leaves the sandbox. Safe to test anything."}
              </p>
            </div>
          </div>

          <div className="shrink-0">
            {!isLive ? (
              <button
                onClick={beginGoLive}
                disabled={!requiredDone}
                className="px-4 py-2.5 rounded-md text-[13px] transition-all"
                style={{
                  background: requiredDone ? "var(--rose)" : "var(--muted)",
                  color: requiredDone ? "white" : "var(--muted-foreground)",
                  fontWeight: 500,
                  cursor: requiredDone ? "pointer" : "not-allowed",
                  boxShadow: requiredDone ? "0 4px 14px rgba(244,63,94,0.25)" : "none",
                }}
              >
                Go live →
              </button>
            ) : (
              <button
                onClick={goBackToPaper}
                className="px-4 py-2.5 rounded-md text-[13px]"
                style={{ background: "var(--emerald)", color: "var(--background)", fontWeight: 500 }}
              >
                ← Back to paper
              </button>
            )}
          </div>
        </div>
      </motion.div>

      {/* Go-live checklist */}
      <section>
        <h2 className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
          Go-live checklist
        </h2>
        <div className="rounded-xl border border-border obsidian-panel divide-y divide-border overflow-hidden" style={{ background: "var(--card)" }}>
          {checklist.map((c, i) => {
            const isDone = c.id === "mode" ? isLive : c.done;
            return (
              <motion.div
                key={c.id}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
                className="flex items-center gap-4 px-5 py-3.5"
              >
                <motion.div
                  className="w-6 h-6 rounded-full flex items-center justify-center shrink-0"
                  style={{
                    background: isDone ? "rgba(16,185,129,0.15)" : "var(--muted)",
                    color: isDone ? "var(--emerald)" : "var(--muted-foreground)",
                  }}
                  animate={{ scale: isDone ? [1, 1.15, 1] : 1 }}
                  transition={{ duration: 0.4 }}
                >
                  {isDone ? <Check size={12} /> : <X size={12} />}
                </motion.div>
                <div className="flex-1">
                  <div className="text-[13px]" style={{ fontWeight: 500, color: "var(--foreground)" }}>
                    {c.label}
                    {!c.required && (
                      <span className="text-[10px] ml-2 px-1.5 py-0.5 rounded" style={{ background: "var(--muted)", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                        OPTIONAL
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>{c.desc}</p>
                </div>
              </motion.div>
            );
          })}
        </div>
      </section>

      {/* Options Approval Badge */}
      <section>
        <h2 className="text-[11px] uppercase tracking-widest mb-3" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
          Options approval
        </h2>
        <div className="rounded-xl border border-border obsidian-panel p-5 flex items-center gap-5" style={{ background: "var(--card)" }}>
          <div className="w-14 h-14 rounded-xl flex items-center justify-center shrink-0" style={{ background: "rgba(196,150,74,0.15)", color: "var(--treasure)", fontFamily: "var(--font-mono)", fontSize: "22px", fontWeight: 500 }}>
            L3
          </div>
          <div className="flex-1">
            <div className="text-[13px]" style={{ fontWeight: 500 }}>Level 3 — Spreads & long options</div>
            <p className="text-[11px] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
              Granted by Alpaca on June 02, 2026. Covers debit/credit spreads and long calls/puts. Required for the Options and Wheel layers.
            </p>
          </div>
          <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: "rgba(16,185,129,0.12)", color: "var(--emerald)", fontFamily: "var(--font-mono)" }}>
            APPROVED
          </span>
        </div>
      </section>

      {/* Confirmation modal */}
      <AnimatePresence>
        {confirming && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <motion.div
              className="absolute inset-0"
              style={{ background: "rgba(0,0,0,0.7)", backdropFilter: "blur(8px)" }}
              onClick={cancelGoLive}
            />
            <motion.div
              initial={{ opacity: 0, y: 20, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 10, scale: 0.98 }}
              transition={{ duration: 0.3 }}
              className="relative w-full max-w-md rounded-2xl border-2 overflow-hidden"
              style={{ background: "var(--card)", borderColor: "var(--rose)" }}
            >
              <div className="p-6">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: "rgba(244,63,94,0.15)", color: "var(--rose)" }}>
                    <AlertTriangle size={18} />
                  </div>
                  <h2 style={{ fontFamily: "var(--font-serif)", fontSize: "20px", fontWeight: 500 }}>
                    Switch to live mode?
                  </h2>
                </div>
                <p className="text-[13px]" style={{ color: "var(--muted-foreground)" }}>
                  Every signal above your TCS threshold will route a <span style={{ color: "var(--rose)", fontWeight: 500 }}>real order</span> through your broker. Your daily loss limit and auto-trade settings still apply, but real money is on the line.
                </p>
                <p className="text-[12px] mt-3 px-3 py-2 rounded-md border border-dashed" style={{ borderColor: "var(--border)", background: "var(--muted)", color: "var(--muted-foreground)" }}>
                  You can switch back to paper instantly. Open positions stay open across the switch.
                </p>
                <div className="flex items-center justify-end gap-2 mt-5">
                  <button
                    onClick={cancelGoLive}
                    className="px-3 py-2 rounded-md text-[12px] border border-border transition-colors hover:bg-muted"
                    style={{ color: "var(--foreground)" }}
                  >
                    Stay on paper
                  </button>
                  <motion.button
                    onClick={confirmGoLive}
                    whileHover={{ scale: 1.03 }}
                    whileTap={{ scale: 0.97 }}
                    className="px-4 py-2 rounded-md text-[12px]"
                    style={{ background: "var(--rose)", color: "white", fontWeight: 500, boxShadow: "0 4px 14px rgba(244,63,94,0.3)" }}
                  >
                    Yes, go live
                  </motion.button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="h-4" />
    </div>
  );
}
