import { cn } from "@/lib/utils";

/**
 * StatusPill - the small uppercase-tracking pill used for badges
 * (status, source tag, severity). Five canonical tones.
 */
export function StatusPill({
  tone = "neutral",
  children,
  className,
}: {
  tone?: "neutral" | "good" | "warn" | "bad" | "treasure";
  children: React.ReactNode;
  className?: string;
}) {
  const toneClass =
    tone === "good"
      ? "bg-emerald-100 text-emerald-800"
      : tone === "warn"
      ? "bg-amber-100 text-amber-800"
      : tone === "bad"
      ? "bg-red-100 text-red-800"
      : tone === "treasure"
      ? "bg-treasure-100 text-treasure-700"
      : "bg-weave-100 text-weave-700";

  return (
    <span
      className={cn(
        "text-[10px] uppercase tracking-widest rounded-full px-2 py-0.5",
        toneClass,
        className
      )}
    >
      {children}
    </span>
  );
}
