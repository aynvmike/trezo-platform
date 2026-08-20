import { motion } from "motion/react";

const layers = [
  { id: 1, name: "Crypto", status: "active", pnl: 417.50, risk: "High" },
  { id: 2, name: "Stock", status: "active", pnl: 221.25, risk: "Medium" },
  { id: 3, name: "Options", status: "active", pnl: 545.00, risk: "High" },
  { id: 4, name: "Stock Weekly", status: "idle", pnl: 0, risk: "Low" },
  { id: 5, name: "Wheel", status: "active", pnl: 180.00, risk: "Low" },
  { id: 6, name: "Dividends", status: "paused", pnl: 0, risk: "V.Low" },
  { id: 7, name: "KINDRIP", status: "active", pnl: 92.00, risk: "Low" },
];

const statusColor: Record<string, string> = {
  active: "var(--emerald)",
  idle: "var(--muted-foreground)",
  paused: "var(--amber)",
};

export function WovenBasketHero() {
  const total = layers.reduce((s, l) => s + l.pnl, 0);
  const active = layers.filter(l => l.status === "active").length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      className="relative rounded-2xl border border-border overflow-hidden"
      style={{ background: "var(--card)", minHeight: 220 }}
    >
      {/* Sheen */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: "linear-gradient(135deg, rgba(196,150,74,0.06) 0%, transparent 35%, transparent 65%, rgba(196,150,74,0.03) 100%)",
        }}
      />

      <div className="relative grid grid-cols-1 md:grid-cols-2">
        {/* Left — ring visualization */}
        <div className="relative h-[220px] flex items-center justify-center overflow-hidden">
          {layers.map((layer, i) => {
            const size = 200 - i * 22;
            const isOn = layer.status === "active";
            return (
              <motion.div
                key={layer.id}
                className="absolute rounded-full"
                style={{
                  width: size,
                  height: size,
                  border: `1px solid ${isOn ? "var(--treasure)" : "var(--border)"}`,
                  opacity: isOn ? 0.85 - i * 0.06 : 0.2,
                }}
                initial={{ scale: 0.6, opacity: 0 }}
                animate={{ scale: 1, opacity: isOn ? 0.85 - i * 0.06 : 0.2 }}
                transition={{ delay: 0.1 + i * 0.07, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
              />
            );
          })}

          {/* Core glow */}
          <motion.div
            className="absolute rounded-full"
            style={{
              width: 28, height: 28,
              background: "radial-gradient(circle, var(--treasure) 0%, transparent 70%)",
            }}
            animate={{ scale: [1, 1.4, 1], opacity: [0.6, 1, 0.6] }}
            transition={{ duration: 3.6, repeat: Infinity, ease: "easeInOut" }}
          />

          {/* Orbiting status dots */}
          {[1, 2, 3, 5, 7].map((n, i) => {
            const radius = 100 - (n - 1) * 11;
            return (
              <motion.div
                key={`orbit-${n}`}
                className="absolute"
                style={{ width: radius * 2, height: radius * 2 }}
                animate={{ rotate: 360 }}
                transition={{ duration: 20 + n * 4, repeat: Infinity, ease: "linear" }}
              >
                <div
                  className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full"
                  style={{ background: "var(--treasure)", boxShadow: "0 0 8px var(--treasure)" }}
                />
              </motion.div>
            );
          })}
        </div>

        {/* Right — readout */}
        <div className="px-6 py-6 flex flex-col justify-center gap-4">
          <div>
            <div className="text-[10px] uppercase tracking-widest mb-1" style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}>
              Woven Basket
            </div>
            <h2 style={{ fontFamily: "var(--font-serif)", fontSize: "26px", fontWeight: 500, color: "var(--foreground)", lineHeight: 1.15 }}>
              Seven layers, <br />one strategy
            </h2>
            <p className="text-[12px] mt-2" style={{ color: "var(--muted-foreground)" }}>
              Outer rings carry volatility, inner rings carry protection. Every ring earns its keep.
            </p>
          </div>

          <div className="flex items-center gap-5 pt-2 border-t border-border">
            <div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "18px", fontWeight: 500, color: "var(--emerald)" }}>
                +${total.toFixed(0)}
              </div>
              <div className="text-[10px]" style={{ color: "var(--muted-foreground)", letterSpacing: "0.05em" }}>TODAY'S P&L</div>
            </div>
            <div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "18px", fontWeight: 500, color: "var(--foreground)" }}>
                {active}/7
              </div>
              <div className="text-[10px]" style={{ color: "var(--muted-foreground)", letterSpacing: "0.05em" }}>ACTIVE</div>
            </div>
            <div className="flex gap-1.5 ml-auto">
              {layers.map((l, i) => (
                <motion.div
                  key={l.id}
                  initial={{ scale: 0, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ delay: 0.5 + i * 0.05 }}
                  className="w-5 h-5 rounded flex items-center justify-center text-[9px]"
                  style={{
                    background: l.status === "active" ? "var(--treasure)" : "var(--muted)",
                    color: l.status === "active" ? "var(--background)" : "var(--muted-foreground)",
                    fontFamily: "var(--font-mono)",
                    fontWeight: 500,
                    opacity: l.status === "active" ? 1 : 0.5,
                  }}
                  title={`${l.name} — ${l.status}`}
                >
                  {l.id}
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
