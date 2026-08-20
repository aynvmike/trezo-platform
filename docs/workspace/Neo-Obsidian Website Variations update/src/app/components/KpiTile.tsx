import { motion } from "motion/react";
import { AnimatedNumber } from "./AnimatedNumber";

type Props = {
  label: string;
  value: string;
  sub: string;
  delta?: string;
  deltaDir?: "up" | "down" | "neutral";
  pill?: string;
  pillColor?: string;
  index?: number;
};

const deltaColors = {
  up: "var(--emerald)",
  down: "var(--rose)",
  neutral: "var(--muted-foreground)",
};

// Parse "+$2,147" / "$142,380" / "4 / 7" into animatable parts
function parseValue(raw: string) {
  const match = raw.match(/^([^\d\-]*)([-\d,\.]+)(.*)$/);
  if (!match) return null;
  const prefix = match[1];
  const numStr = match[2].replace(/,/g, "");
  const suffix = match[3];
  const num = parseFloat(numStr);
  if (isNaN(num)) return null;
  const decimals = numStr.includes(".") ? (numStr.split(".")[1].length) : 0;
  return { prefix, num, suffix, decimals };
}

export function KpiTile({ label, value, sub, delta, deltaDir = "neutral", pill, pillColor, index = 0 }: Props) {
  const parsed = parseValue(value);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.08, ease: [0.22, 1, 0.36, 1] }}
      whileHover="hover"
      className="relative rounded-xl p-4 flex flex-col gap-2 border border-border overflow-hidden group"
      style={{ background: "var(--card)" }}
    >
      {/* Obsidian sheen */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: "linear-gradient(135deg, rgba(196,150,74,0.04) 0%, transparent 40%, transparent 60%, rgba(196,150,74,0.02) 100%)",
        }}
      />

      {/* Brass edge glow on hover */}
      <motion.div
        className="absolute inset-0 pointer-events-none rounded-xl"
        variants={{ hover: { opacity: 1 } }}
        initial={{ opacity: 0 }}
        transition={{ duration: 0.25 }}
        style={{
          boxShadow: "inset 0 0 0 1px var(--treasure), 0 8px 24px -8px rgba(196,150,74,0.25)",
        }}
      />

      {/* Hover lift */}
      <motion.div
        variants={{ hover: { y: -3 } }}
        transition={{ duration: 0.2 }}
        className="relative flex flex-col gap-2 h-full"
      >
        <div className="flex items-center justify-between">
          <span className="text-[11px] uppercase tracking-wider" style={{ color: "var(--muted-foreground)", letterSpacing: "0.08em" }}>
            {label}
          </span>
          {pill && (
            <motion.span
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: index * 0.08 + 0.2 }}
              className="text-[10px] px-2 py-0.5 rounded-full"
              style={{
                background: pillColor ? `${pillColor}18` : "var(--muted)",
                color: pillColor || "var(--muted-foreground)",
                fontFamily: "var(--font-mono)",
              }}
            >
              {pill}
            </motion.span>
          )}
        </div>

        <div className="flex items-end gap-2">
          <span
            className="leading-none"
            style={{ fontFamily: "var(--font-mono)", fontSize: "22px", fontWeight: 500, color: "var(--foreground)" }}
          >
            {parsed ? (
              <AnimatedNumber
                value={parsed.num}
                prefix={parsed.prefix}
                suffix={parsed.suffix}
                decimals={parsed.decimals}
                duration={1100 + index * 120}
              />
            ) : value}
          </span>
          {delta && (
            <span className="text-[12px] mb-0.5" style={{ color: deltaColors[deltaDir], fontFamily: "var(--font-mono)" }}>
              {deltaDir === "up" ? "▲" : deltaDir === "down" ? "▼" : ""} {delta}
            </span>
          )}
        </div>

        <p className="text-[12px] leading-snug" style={{ color: "var(--muted-foreground)" }}>
          {sub}
        </p>
      </motion.div>
    </motion.div>
  );
}
