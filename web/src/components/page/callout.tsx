import { cn } from "@/lib/utils";

/**
 * Callout - the colored notice band used for warnings, info, and
 * positive confirmations. Replaces ad-hoc `<div className="bg-amber-50 ...">`
 * blocks scattered across pages.
 */
export function Callout({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: "info" | "good" | "warn" | "bad";
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const toneClass =
    tone === "good"
      ? "border-emerald-200 bg-emerald-50 text-emerald-900"
      : tone === "warn"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : tone === "bad"
      ? "border-red-200 bg-red-50 text-red-900"
      : "border-weave-200 bg-weave-50/60 text-weave-800";

  return (
    <div
      className={cn(
        "rounded-xl border p-4 text-sm leading-relaxed",
        toneClass,
        className
      )}
    >
      {title ? <p className="font-medium mb-1">{title}</p> : null}
      {children}
    </div>
  );
}
