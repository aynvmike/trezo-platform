import { motion } from "motion/react";

export function AmbientBackground() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none" style={{ zIndex: 0 }}>
      {/* Subtle dot grid */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(circle, var(--border) 1px, transparent 1px)",
          backgroundSize: "32px 32px",
          opacity: 0.4,
          maskImage: "radial-gradient(ellipse at center, black 30%, transparent 80%)",
          WebkitMaskImage: "radial-gradient(ellipse at center, black 30%, transparent 80%)",
        }}
      />

      {/* Drifting glow blobs */}
      <motion.div
        className="absolute rounded-full"
        style={{
          width: 520, height: 520,
          left: "-15%", top: "-10%",
          background: "radial-gradient(circle, var(--treasure) 0%, transparent 65%)",
          opacity: 0.10, filter: "blur(60px)",
        }}
        animate={{ x: [0, 40, 0], y: [0, 30, 0] }}
        transition={{ duration: 24, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute rounded-full"
        style={{
          width: 460, height: 460,
          right: "-12%", bottom: "-10%",
          background: "radial-gradient(circle, var(--sky) 0%, transparent 65%)",
          opacity: 0.08, filter: "blur(70px)",
        }}
        animate={{ x: [0, -35, 0], y: [0, -25, 0] }}
        transition={{ duration: 28, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute rounded-full"
        style={{
          width: 320, height: 320,
          right: "20%", top: "30%",
          background: "radial-gradient(circle, var(--emerald) 0%, transparent 65%)",
          opacity: 0.06, filter: "blur(60px)",
        }}
        animate={{ x: [0, 25, 0], y: [0, 20, 0] }}
        transition={{ duration: 32, repeat: Infinity, ease: "easeInOut" }}
      />
    </div>
  );
}
