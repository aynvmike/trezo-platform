"use client";

import { cn } from "@/lib/utils";

/**
 * TCS badge — color-codes a Trade Confidence Score (0-100) by tier.
 *
 * EQ-5 (rv:scanners-scale, 2026-09-01): the engine moved TCS to ONE
 * 0-100 scale on 2026-07-08 (patterns/scoring.py). The tiers here were
 * still 800/650/500, so every live pattern score rendered "weak".
 *
 *  - 0-49:   grey (no signal)
 *  - 50-64:  amber (watch)
 *  - 65-79:  weave (good)
 *  - 80-100: treasure (strong)
 */
export function TcsBadge({
  tcs,
  size = "md",
  label
}: {
  tcs: number;
  size?: "sm" | "md";
  label?: string;
}) {
  const tier =
    tcs >= 80 ? "strong" : tcs >= 65 ? "good" : tcs >= 50 ? "watch" : "weak";

  const palette: Record<typeof tier, string> = {
    strong: "bg-treasure-200 text-treasure-800 ring-treasure-300",
    good:   "bg-weave-100 text-weave-800 ring-weave-200",
    watch:  "bg-amber-100 text-amber-800 ring-amber-200",
    weak:   "bg-weave-50 text-weave-500 ring-weave-100"
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full ring-1 font-mono",
        palette[tier],
        size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs"
      )}
      title={label ?? `Trade Confidence Score ${tcs}/100`}
    >
      {label && <span className="font-sans text-[10px] uppercase tracking-widest opacity-70">{label}</span>}
      <span>{tcs}</span>
    </span>
  );
}
