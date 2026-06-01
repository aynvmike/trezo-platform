"use client";

import { cn } from "@/lib/utils";

/**
 * TCS badge — color-codes a Trade Confidence Score (0-1000) by tier.
 *
 *  - 0-499:    grey (no signal)
 *  - 500-649:  amber (watch)
 *  - 650-799:  weave (good)
 *  - 800-1000: treasure (strong)
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
    tcs >= 800 ? "strong" : tcs >= 650 ? "good" : tcs >= 500 ? "watch" : "weak";

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
      title={label ?? `Trade Confidence Score ${tcs}/1000`}
    >
      {label && <span className="font-sans text-[10px] uppercase tracking-widest opacity-70">{label}</span>}
      <span>{tcs}</span>
    </span>
  );
}
